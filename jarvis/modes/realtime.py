"""Modo Realtime — voz + visão + proatividade em tempo real."""

import asyncio
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel

from jarvis.core.agent import Agent
from jarvis.core.memory import Memory
from jarvis.sensors.audio import AudioSensor
from jarvis.sensors.vision import VisionSensor
from jarvis.sensors.system_ctx import SystemContext
from jarvis.processing.stt import STTProcessor
from jarvis.processing.tts import TTSProcessor
from jarvis.observer.observer import Observer
from jarvis.observer.decision import DecisionEngine, Action
from jarvis.integrations.gdocs import GoogleDocsClient
import jarvis.config as cfg


console = Console()

# --- Modo Anotação — triggers e parâmetros ---
ANNOTATION_ACTIVATE   = ["ativar modo anotação", "ativar anotação", "modo anotação"]
ANNOTATION_DEACTIVATE = ["desativar modo anotação", "desativar anotação", "parar anotação"]
ANNOTATION_SILENCE_TIMEOUT = 300   # 5 minutos sem fala → encerra automaticamente
ANNOTATION_BATCH_SIZE      = 5     # utterances acumuladas antes de gravar no Doc
ANNOTATION_BATCH_INTERVAL  = 60.0  # segundos entre writes forçados


class RealtimeMode:
    """
    Modo principal do Jarvis: opera continuamente com voz, visão e proatividade.

    Loop de sensores:
        Microfone → VAD → STT → Agente → TTS
        Tela (1 FPS) → OCR → Observer → Decision → Agente → TTS
    """

    def __init__(self, vision_enabled: bool = True, voice_enabled: bool = True):
        self.vision_enabled = vision_enabled
        self.voice_enabled = voice_enabled

        # Componentes
        self.memory = Memory()
        self.agent = Agent(self.memory)
        self.system_ctx = SystemContext()
        self.stt = STTProcessor()
        self.tts = TTSProcessor()
        self.observer = Observer()
        self.decision = DecisionEngine()

        # Sensores opcionais
        self.audio_sensor: Optional[AudioSensor] = AudioSensor() if voice_enabled else None
        self.vision_sensor: Optional[VisionSensor] = VisionSensor() if vision_enabled else None

        # Estado geral
        self._running: bool = False
        self._processing: bool = False  # Agente está gerando resposta
        self._last_transcript: str = ""
        self._last_response: str = ""
        self._status_line: str = "Pronto"
        self._mic_active: bool = False
        self._speech_detected: bool = False

        # Estado — modo anotação
        self._annotation_mode: bool = False
        self._annotation_buffer: List[str] = []
        self._annotation_doc_id: str = ""
        self._annotation_doc_url: str = ""
        self._last_annotation_write: float = 0.0
        self._last_utterance_time: float = time.time()
        self._gdocs: Optional[GoogleDocsClient] = None  # lazy init

        # Thread pool para tarefas CPU-bound
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="jarvis")

        # Kill switch
        self._kill_event = asyncio.Event()

    # ------------------------------------------------------------------ #
    #  Ponto de entrada                                                    #
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """Inicia o Jarvis em modo realtime."""
        self._running = True
        loop = asyncio.get_event_loop()

        console.print(Panel(
            "[bold green]JARVIS[/bold green] — Modo Realtime\n"
            "[dim]Ctrl+C para encerrar | Ouvindo continuamente...[/dim]\n"
            f"[dim]Voz: {'✓' if self.voice_enabled else '✗'} | "
            f"Visão: {'✓' if self.vision_enabled else '✗'}[/dim]",
            border_style="green",
        ))

        # Configura sensor de áudio
        if self.audio_sensor:
            self.audio_sensor.set_callback(loop, self._on_utterance)
            self.audio_sensor.start()
            self._mic_active = True

        # Inicia visão em background
        if self.vision_sensor:
            self.vision_sensor.start()

        # Tarefas concorrentes
        tasks = [
            asyncio.create_task(self._observer_loop(), name="observer"),
            asyncio.create_task(self._status_display_loop(), name="status"),
        ]

        try:
            # Aguarda até Ctrl+C ou kill switch
            await self._kill_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown(tasks)

    # ------------------------------------------------------------------ #
    #  Callback de áudio (chamado do thread de VAD)                       #
    # ------------------------------------------------------------------ #

    async def _on_utterance(self, audio_bytes: bytes) -> None:
        """Chamado quando uma utterance completa é detectada."""
        if self._processing:
            return  # Ignora nova fala enquanto processa

        self._speech_detected = True
        self.tts.stop()  # Interrompe TTS se estiver falando

        self._status_line = "Transcrevendo..."
        self.observer.reset_cooldown()

        # STT em thread pool (não bloqueia o loop asyncio)
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(self._executor, self.stt.transcribe, audio_bytes)
        self._speech_detected = False

        if not text or len(text.strip()) < 2:
            self._status_line = "Pronto"
            return

        self._last_transcript = text
        console.print(f"\n[cyan]Você:[/cyan] {text}")

        # --- Detecção de trigger de anotação (antes de responder) ---
        text_lower = text.strip().lower()

        if any(trigger in text_lower for trigger in ANNOTATION_ACTIVATE):
            if not self._annotation_mode:
                await self._start_annotation()
            return  # Não repassa ao agente normal

        if any(trigger in text_lower for trigger in ANNOTATION_DEACTIVATE):
            if self._annotation_mode:
                await self._stop_annotation()
            return  # Não repassa ao agente normal

        # --- Modo anotação ativo: acumula utterance ---
        if self._annotation_mode:
            self._annotation_buffer.append(text)
            self._last_utterance_time = time.time()

            should_flush = (
                len(self._annotation_buffer) >= ANNOTATION_BATCH_SIZE
                or (time.time() - self._last_annotation_write) >= ANNOTATION_BATCH_INTERVAL
            )
            if should_flush:
                await self._flush_annotation_buffer()

        # Jarvis responde normalmente independente do modo anotação
        await self._respond(text)

    # ------------------------------------------------------------------ #
    #  Modo Anotação                                                       #
    # ------------------------------------------------------------------ #

    async def _start_annotation(self) -> None:
        """Ativa modo anotação: autentica, cria Google Doc e confirma por voz."""
        loop = asyncio.get_event_loop()

        try:
            # Lazy init do cliente Google Docs
            if self._gdocs is None:
                self._gdocs = GoogleDocsClient(
                    credentials_path=cfg.GDOCS_CREDENTIALS_PATH,
                    token_path=cfg.GDOCS_TOKEN_PATH,
                )

            console.print("[yellow][Anotação] Autenticando no Google Docs...[/yellow]")
            await loop.run_in_executor(self._executor, self._gdocs.authenticate)

            # Cria documento com título baseado na data/hora atual
            title = f"Notas Jarvis — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            self._annotation_doc_id = await loop.run_in_executor(
                self._executor, self._gdocs.create_document, title
            )
            self._annotation_doc_url = self._gdocs.get_document_url(self._annotation_doc_id)

            # Ativa o modo
            self._annotation_mode = True
            self._annotation_buffer = []
            self._last_annotation_write = time.time()
            self._last_utterance_time = time.time()

            console.print(
                f"[green][Anotação] Modo ativado![/green] Doc: {self._annotation_doc_url}"
            )
            await self.tts.speak_async("Modo anotação ativado. Pode falar à vontade!")

        except FileNotFoundError as e:
            console.print(f"[red][Anotação] {e}[/red]")
            await self.tts.speak_async(
                "Não consegui ativar o modo anotação. "
                "O arquivo de credenciais do Google não foi encontrado."
            )
        except Exception as e:
            console.print(f"[red][Anotação] Erro ao ativar: {e}[/red]")
            await self.tts.speak_async("Ocorreu um erro ao ativar o modo anotação.")

    async def _stop_annotation(self) -> None:
        """Desativa modo anotação: faz flush final e confirma por voz."""
        # Flush do que sobrou no buffer
        if self._annotation_buffer:
            await self._flush_annotation_buffer()

        self._annotation_mode = False
        doc_url = self._annotation_doc_url
        self._annotation_doc_id = ""
        self._annotation_doc_url = ""
        self._annotation_buffer = []

        console.print(f"[yellow][Anotação] Modo desativado. Notas em: {doc_url}[/yellow]")
        await self.tts.speak_async(
            f"Modo anotação desativado. Suas notas foram salvas."
        )

        if doc_url:
            webbrowser.open(doc_url)

    async def _flush_annotation_buffer(self) -> None:
        """Processa utterances acumuladas via LLM e grava no Google Doc."""
        if not self._annotation_buffer:
            return

        utterances = self._annotation_buffer[:]
        self._annotation_buffer = []
        self._last_annotation_write = time.time()

        raw_text = "\n".join(f"- {u}" for u in utterances)
        prompt = (
            "Organize as seguintes falas em notas estruturadas com bullet points. "
            "Agrupe por tema quando possível. Não adicione informações, só organize:\n\n"
            f"{raw_text}"
        )

        loop = asyncio.get_event_loop()
        try:
            formatted = await loop.run_in_executor(
                self._executor, self.agent.chat, prompt, {}
            )

            timestamp = datetime.now().strftime("%H:%M")
            block = f"\n[{timestamp}]\n{formatted}\n"

            await loop.run_in_executor(
                self._executor, self._gdocs.append_text, self._annotation_doc_id, block
            )
            console.print(f"[green][Anotação] {len(utterances)} fala(s) gravada(s) no Doc.[/green]")

        except Exception as e:
            # Devolve utterances ao buffer para não perder
            self._annotation_buffer = utterances + self._annotation_buffer
            console.print(f"[red][Anotação] Erro ao gravar no Doc: {e}[/red]")

    # ------------------------------------------------------------------ #
    #  Geração de resposta                                                 #
    # ------------------------------------------------------------------ #

    async def _respond(self, text: str, proactive_context: Optional[dict] = None) -> None:
        """Envia texto ao agente e fala a resposta."""
        if self._processing:
            return

        self._processing = True
        self._status_line = "Pensando..."

        try:
            context = self.system_ctx.get_context()
            if self.vision_sensor:
                context["screen_text"] = self.vision_sensor.get_last_ocr()
            if proactive_context:
                context.update(proactive_context)

            # Chamada ao agente (bloqueante → thread pool)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self._executor, self.agent.chat, text, context
            )

            self._last_response = response
            console.print(f"[green]Jarvis:[/green] {response}")

            # TTS
            self._status_line = "Falando..."
            await self.tts.speak_async(response)

        except Exception as e:
            console.print(f"[red]Erro: {e}[/red]")
        finally:
            self._processing = False
            self._status_line = "Pronto"

    # ------------------------------------------------------------------ #
    #  Observer loop                                                       #
    # ------------------------------------------------------------------ #

    async def _observer_loop(self) -> None:
        """Verifica proatividade a cada 10 segundos."""
        await asyncio.sleep(30)  # Aguarda 30s antes de começar a verificar

        while self._running:
            await asyncio.sleep(10)

            # Timeout de silêncio no modo anotação
            if self._annotation_mode:
                silence = time.time() - self._last_utterance_time
                if silence > ANNOTATION_SILENCE_TIMEOUT:
                    console.print(
                        "[yellow][Anotação] Timeout de silêncio — encerrando modo anotação[/yellow]"
                    )
                    await self._stop_annotation()
                    continue

            state = {
                "screen_text": self.vision_sensor.get_last_ocr() if self.vision_sensor else "",
                "window_title": self.system_ctx.get_active_window(),
                "app_name": self.system_ctx.get_context().get("app_name", ""),
                "last_speech": self.memory.get_last_user_message(),
                "elapsed_since_last_response": time.time() - self.memory.last_response_time,
            }

            events = self.observer.check(state)
            for event in events:
                action = self.decision.decide(
                    event,
                    is_processing=self._processing,
                    is_speaking=self.tts.is_playing,
                    is_user_speaking=self._speech_detected,
                )
                if action == Action.SUGGEST and event.suggestion_prompt:
                    console.print(f"[yellow][Proativo][/yellow] {event.description}")
                    await self._respond(
                        event.suggestion_prompt,
                        {"proactive_event": event.description},
                    )
                    break  # Um evento proativo por vez

    # ------------------------------------------------------------------ #
    #  Status display                                                      #
    # ------------------------------------------------------------------ #

    async def _status_display_loop(self) -> None:
        """Exibe linha de status no terminal."""
        while self._running:
            await asyncio.sleep(0.5)
            mic_icon = "🎤" if self._mic_active else "🔇"
            vision_icon = "👁" if self.vision_enabled else "—"
            speech_icon = "💬" if self._speech_detected else " "
            proc_icon = "⚙" if self._processing else " "
            annot_icon = "📝" if self._annotation_mode else " "

            status = (
                f"[dim]{mic_icon} {speech_icon} {vision_icon} {proc_icon} {annot_icon} "
                f"| {self._status_line} "
                f"| Sessão: {int(self.memory.session_duration)}s[/dim]"
            )
            # Usa print simples para não interferir com o output principal

    # ------------------------------------------------------------------ #
    #  Shutdown                                                            #
    # ------------------------------------------------------------------ #

    def trigger_kill_switch(self) -> None:
        """Kill switch — para tudo imediatamente."""
        self._running = False
        self.tts.stop()
        if self.audio_sensor:
            self.audio_sensor.stop()
        if self.vision_sensor:
            self.vision_sensor.stop()
        self._kill_event.set()

    async def _shutdown(self, tasks: list) -> None:
        # Encerra modo anotação se ativo
        if self._annotation_mode:
            console.print("[yellow][Anotação] Encerrando modo anotação...[/yellow]")
            await self._stop_annotation()

        self._running = False
        self.tts.stop()

        if self.audio_sensor:
            self.audio_sensor.stop()
        if self.vision_sensor:
            self.vision_sensor.stop()

        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        self._executor.shutdown(wait=False)
        console.print("\n[dim]Jarvis encerrado. Até logo![/dim]")
