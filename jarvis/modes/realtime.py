"""Modo Realtime — voz + visão + proatividade em tempo real."""

import asyncio
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich import box

from jarvis.core.agent import Agent
from jarvis.core.memory import Memory
from jarvis.sensors.audio import AudioSensor
from jarvis.sensors.vision import VisionSensor
from jarvis.sensors.system_ctx import SystemContext
from jarvis.processing.stt import STTProcessor
from jarvis.processing.tts import TTSProcessor
from jarvis.observer.observer import Observer
from jarvis.observer.decision import DecisionEngine, Action
from jarvis.observer.events import JarvisEvent, EventType


console = Console()


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

        # Estado
        self._running: bool = False
        self._processing: bool = False  # Agente está gerando resposta
        self._last_transcript: str = ""
        self._last_response: str = ""
        self._status_line: str = "Pronto"
        self._mic_active: bool = False
        self._speech_detected: bool = False

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

        await self._respond(text)

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

            status = (
                f"[dim]{mic_icon} {speech_icon} {vision_icon} {proc_icon} "
                f"| {self._status_line} "
                f"| Sessão: {int(self.memory.session_duration)}s[/dim]"
            )
            # Usa print simples para não interferir com o output principal
            # (Rich Live seria mais elegante mas complica o fluxo async)

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
