"""Modo Realtime — voz + visão + proatividade em tempo real."""

import asyncio
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional, Set

from rich.console import Console
from rich.panel import Panel

from jarvis.core.agent import Agent
from jarvis.core.memory import Memory
from jarvis.core.profile import UserProfile
from jarvis.sensors.audio import AudioSensor
from jarvis.sensors.vision import VisionSensor
from jarvis.sensors.system_ctx import SystemContext
from jarvis.sensors.activity import ActivitySensor, ActivityState, ActivityType
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
        Tela (1 FPS) → OCR/Screenshot → Observer → Decision → Agente → TTS
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

        # Inteligência contextual e aprendizado persistente
        self.profile: UserProfile = UserProfile.load()
        self.activity_sensor: ActivitySensor = ActivitySensor()
        self._current_activity: ActivityState = ActivityState(
            type=ActivityType.UNKNOWN, confidence=0.0, details=""
        )

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

        # Rastreia tasks de utterance para cancelamento limpo no shutdown
        # (tasks criadas por asyncio.run_coroutine_threadsafe no VAD thread)
        self._pending_utterance_tasks: Set[asyncio.Task] = set()

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
            f"Visão: {'✓' if self.vision_enabled else '✗'} | "
            f"Provider: {self.agent.provider} ({self.agent._model})[/dim]",
            border_style="green",
        ))

        # Configura sensor de áudio — usa wrapper rastreado para shutdown limpo
        if self.audio_sensor:
            self.audio_sensor.set_callback(loop, self._tracked_utterance)
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
    #  Wrapper rastreado para utterances (shutdown limpo)                 #
    # ------------------------------------------------------------------ #

    async def _tracked_utterance(self, audio_bytes: bytes) -> None:
        """
        Wrapper em torno de _on_utterance que registra a task atual no set de
        tasks pendentes. Isso permite que _shutdown() cancele-as corretamente,
        evitando o warning "Task was destroyed but it is pending!".
        """
        task = asyncio.current_task()
        if task is not None:
            self._pending_utterance_tasks.add(task)
        try:
            await self._on_utterance(audio_bytes)
        finally:
            if task is not None:
                self._pending_utterance_tasks.discard(task)

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
        t_stt_start = time.perf_counter()
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(self._executor, self.stt.transcribe, audio_bytes)
        stt_ms = (time.perf_counter() - t_stt_start) * 1000
        self._speech_detected = False

        if text:
            print(f"[Perf] STT: {stt_ms:.0f}ms | '{text[:60]}{'...' if len(text)>60 else ''}'")

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

        # --- Detecção de comando de aprendizado explícito ---
        if await self._check_learn_command(text):
            return  # Já tratado, não repassa ao agente

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
    #  Aprendizado explícito                                               #
    # ------------------------------------------------------------------ #

    async def _check_learn_command(self, text: str) -> bool:
        """
        Detecta comandos explícitos de aprendizado e salva no perfil.
        Retorna True se o texto é um comando de aprendizado.
        """
        text_lower = text.strip().lower()
        LEARN_TRIGGERS = [
            "lembra que ", "lembra disso: ", "anota que ", "guarda que ",
            "remember that ", "salva que ", "memoriza que ",
        ]

        matched_trigger = None
        for trigger in LEARN_TRIGGERS:
            if text_lower.startswith(trigger):
                matched_trigger = trigger
                break

        if matched_trigger is None:
            return False

        # Extrai o conteúdo a aprender
        content = text[len(matched_trigger):].strip()
        if len(content) < 3:
            return False

        self.profile.add_insights([content])
        self.profile.save()
        self.memory.log_event("profile_learn", {"insight": content})

        console.print(f"[magenta][Perfil][/magenta] Aprendido: {content}")
        await self.tts.speak_async("Anotado! Vou lembrar disso.")
        return True

    # ------------------------------------------------------------------ #
    #  Geração de resposta                                                 #
    # ------------------------------------------------------------------ #

    async def _respond(self, text: str, proactive_context: Optional[dict] = None) -> None:
        """Envia texto ao agente e fala a resposta."""
        if self._processing:
            return

        self._processing = True
        self._status_line = "Pensando..."
        t_respond_start = time.perf_counter()

        try:
            context = self.system_ctx.get_context()

            # --- Visão: frame freshness + contexto visual ---
            if self.vision_sensor:
                t_vision_start = time.perf_counter()

                frame_age = self.vision_sensor.get_frame_age()
                if frame_age > cfg.VISION_FRAME_MAX_AGE_S:
                    # Frame desatualizado: captura novo no executor (não bloqueia event loop)
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(self._executor, self.vision_sensor.capture)
                    frame_age = self.vision_sensor.get_frame_age()

                # Contexto textual (OCR ou metadados de fallback)
                screen_text = self.vision_sensor.get_screen_context_text()
                if screen_text:
                    context["screen_text"] = screen_text

                # Para Anthropic: envia screenshot real como imagem multimodal
                if self.agent.provider == "anthropic":
                    b64 = self.vision_sensor.get_screenshot_base64()
                    if b64:
                        context["screenshot_b64"] = b64
                        context["vision_mode"] = "screenshot multimodal anexado"
                    elif screen_text:
                        context["vision_mode"] = "texto OCR"
                elif screen_text:
                    context["vision_mode"] = "texto OCR"

                vision_ms = (time.perf_counter() - t_vision_start) * 1000
                print(
                    f"[Perf] Visão: {vision_ms:.0f}ms | "
                    f"frame_age={frame_age:.1f}s | "
                    f"ocr={bool(self.vision_sensor.get_last_ocr())} | "
                    f"b64={'screenshot_b64' in context}"
                )

            if proactive_context:
                context.update(proactive_context)

            # --- Detecção de atividade atual ---
            activity = self.activity_sensor.detect(
                app_name=context.get("app_name", ""),
                window_title=context.get("window_title", ""),
                screen_text=context.get("screen_text", ""),
                learned_apps=self.profile.learned_apps,
            )
            self._current_activity = activity
            self.profile.update_activity(activity.type.value)
            context["activity"] = activity.label()

            # --- Perfil do usuário ---
            profile_ctx = self.profile.get_context_for_llm()
            if profile_ctx:
                context["profile"] = profile_ctx

            # Chamada ao agente (bloqueante → thread pool)
            t_llm_start = time.perf_counter()
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self._executor, self.agent.chat, text, context
            )
            llm_ms = (time.perf_counter() - t_llm_start) * 1000

            total_ms = (time.perf_counter() - t_respond_start) * 1000
            print(
                f"[Perf] Resposta total: {total_ms:.0f}ms "
                f"(LLM incluso: {llm_ms:.0f}ms)"
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
                "activity_type": self._current_activity.type.value,
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
            # Status line mantida internamente; output não interfere com o Rich console

    # ------------------------------------------------------------------ #
    #  Shutdown                                                            #
    # ------------------------------------------------------------------ #

    async def _shutdown(self, tasks: list) -> None:
        """Encerra o Jarvis de forma limpa, sem warnings de tasks pendentes."""

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

        # Cancela e aguarda tasks de utterance pendentes (evita "Task was destroyed")
        pending_utterances = list(self._pending_utterance_tasks)
        if pending_utterances:
            console.print(
                f"[dim][Shutdown] Cancelando {len(pending_utterances)} task(s) de utterance...[/dim]"
            )
            for t in pending_utterances:
                t.cancel()
            await asyncio.gather(*pending_utterances, return_exceptions=True)
            self._pending_utterance_tasks.clear()

        # Cancela e aguarda tasks de background (observer, status)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Resumo de sessão em background (aprende com a conversa)
        import threading
        console.print("[dim][Profile] Gerando resumo de sessão...[/dim]")
        summary_thread = threading.Thread(
            target=self._summarize_session,
            daemon=True,
            name="jarvis-session-summary",
        )
        summary_thread.start()
        summary_thread.join(timeout=15.0)  # Aguarda até 15s, depois encerra mesmo assim

        self._executor.shutdown(wait=False)
        console.print("\n[dim]Jarvis encerrado. Até logo![/dim]")

    # ------------------------------------------------------------------ #
    #  Aprendizado automático — resumo de sessão                          #
    # ------------------------------------------------------------------ #

    def _summarize_session(self) -> None:
        """
        Gera um resumo da sessão via LLM e salva no perfil do usuário.
        Chamado em background thread no shutdown — não bloqueia o encerramento.
        """
        exchange_count = self.memory.message_count // 2
        if exchange_count < cfg.SESSION_SUMMARY_MIN_EXCHANGES:
            print(f"[Profile] Sessão curta ({exchange_count} trocas) — resumo ignorado.")
            self.profile.increment_session()
            self.profile.save()
            return

        # Coleta histórico recente (últimas 20 trocas para não estourar tokens)
        recent_messages = self.memory.get_messages_for_api()[-40:]
        conversation_text = "\n".join(
            f"{'Usuário' if m['role'] == 'user' else 'Jarvis'}: {m['content'][:300]}"
            for m in recent_messages
        )

        summary_prompt = (
            "Analise a conversa abaixo entre um usuário e seu assistente de IA pessoal Jarvis.\n"
            "Extraia de 3 a 5 fatos CONCRETOS e ÚTEIS sobre o usuário que possam ajudar "
            "o Jarvis em sessões futuras.\n\n"
            "Foque em:\n"
            "- O que o usuário está desenvolvendo/trabalhando atualmente\n"
            "- Jogos que joga ou mencionou\n"
            "- Problemas recorrentes que enfrenta\n"
            "- Preferências de ferramentas, linguagens ou fluxos de trabalho\n"
            "- Qualquer dado pessoal relevante que o usuário compartilhou explicitamente\n\n"
            "NÃO inclua:\n"
            "- Informações genéricas (\"o usuário usa um computador\")\n"
            "- Respostas do Jarvis — apenas fatos sobre o USUÁRIO\n"
            "- Suposições não baseadas na conversa\n\n"
            "Formato: retorne APENAS uma lista de bullets começando com \"-\". "
            "Máximo de 5 bullets.\n\n"
            f"CONVERSA:\n{conversation_text}\n\nBULLETS:"
        )

        try:
            if self.agent.provider == "anthropic":
                # Reutiliza o agente Anthropic diretamente
                response_text = self.agent._chat_anthropic(summary_prompt)
            elif self.agent.provider == "groq":
                from openai import OpenAI
                client = OpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=cfg.GROQ_API_KEY,
                )
                response = client.chat.completions.create(
                    model="llama-3.1-8b-instant",  # Rápido e barato
                    messages=[{"role": "user", "content": summary_prompt}],
                    max_tokens=300,
                    temperature=0.3,
                )
                response_text = response.choices[0].message.content or ""
            else:
                from openai import OpenAI
                client = OpenAI(
                    base_url=f"{cfg.OLLAMA_HOST}/v1",
                    api_key="ollama",
                )
                response = client.chat.completions.create(
                    model=cfg.OLLAMA_MODEL,
                    messages=[{"role": "user", "content": summary_prompt}],
                    max_tokens=300,
                    temperature=0.3,
                )
                response_text = response.choices[0].message.content or ""

            bullets = self._parse_bullets(response_text)
            self.profile.add_insights(bullets)
            self.profile.increment_session()
            self.profile.save()
            print(f"[Profile] Sessão resumida: {len(bullets)} insight(s) salvos.")

        except Exception as e:
            print(f"[Profile] Aviso: resumo de sessão falhou ({e}).")
            self.profile.increment_session()
            self.profile.save()

    @staticmethod
    def _parse_bullets(text: str) -> list:
        """Extrai bullets do formato '- texto' ou '• texto' da resposta do LLM."""
        bullets = []
        for line in text.strip().splitlines():
            line = line.strip()
            if line.startswith(("-", "•", "*", "·")):
                content = line.lstrip("-•*· ").strip()
                if len(content) > 5:
                    bullets.append(content)
        return bullets[:5]

    # ------------------------------------------------------------------ #
    #  Kill switch                                                         #
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
