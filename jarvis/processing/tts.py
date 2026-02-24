"""TTS — Text-to-Speech com suporte a edge-tts (online) e pyttsx3 (offline)."""

import asyncio
import threading
import tempfile
import os
from typing import Optional

from jarvis.config import TTS_VOICE, TTS_RATE, TTS_USE_EDGE


class TTSProcessor:
    """
    Converte texto em fala.
    - Primário: edge-tts (melhor qualidade, requer internet)
    - Fallback: pyttsx3 (offline, qualidade inferior)
    """

    def __init__(self):
        self._playing = False
        self._stop_event = threading.Event()
        self._voice = TTS_VOICE
        self._rate = TTS_RATE
        self._use_edge = TTS_USE_EDGE
        self._pyttsx3_engine = None
        self._pygame_init = False

    # ------------------------------------------------------------------ #
    #  API pública                                                         #
    # ------------------------------------------------------------------ #

    def speak(self, text: str) -> None:
        """Fala o texto de forma síncrona (bloqueia até terminar)."""
        if not text.strip():
            return
        self._stop_event.clear()

        if self._use_edge:
            # Roda o loop async em thread se não houver loop ativo
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Já estamos num loop (realtime mode chama speak_async diretamente)
                    asyncio.ensure_future(self.speak_async(text))
                    return
            except RuntimeError:
                pass
            asyncio.run(self.speak_async(text))
        else:
            self._speak_pyttsx3(text)

    async def speak_async(self, text: str) -> None:
        """Fala o texto de forma assíncrona."""
        if not text.strip():
            return
        self._stop_event.clear()
        self._playing = True
        try:
            if self._use_edge:
                await self._speak_edge(text)
            else:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._speak_pyttsx3, text
                )
        finally:
            self._playing = False

    def stop(self) -> None:
        """Para a reprodução imediatamente."""
        self._stop_event.set()
        self._playing = False
        if self._pygame_init:
            try:
                import pygame
                pygame.mixer.music.stop()
            except Exception:
                pass
        if self._pyttsx3_engine:
            try:
                self._pyttsx3_engine.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    #  Implementações                                                      #
    # ------------------------------------------------------------------ #

    async def _speak_edge(self, text: str) -> None:
        """Gera áudio com edge-tts e reproduz com pygame."""
        try:
            import edge_tts
        except ImportError:
            print("[TTS] edge-tts não instalado, usando pyttsx3")
            await asyncio.get_event_loop().run_in_executor(
                None, self._speak_pyttsx3, text
            )
            return

        self._ensure_pygame()

        tmp_path = None
        try:
            communicate = edge_tts.Communicate(text, self._voice, rate=self._rate)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name

            await communicate.save(tmp_path)

            if self._stop_event.is_set():
                return

            import pygame
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                if self._stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                await asyncio.sleep(0.05)

        except Exception as e:
            print(f"[TTS] Erro edge-tts: {e}. Usando pyttsx3.")
            await asyncio.get_event_loop().run_in_executor(
                None, self._speak_pyttsx3, text
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _speak_pyttsx3(self, text: str) -> None:
        """Fala com pyttsx3 (offline)."""
        try:
            import pyttsx3
            if self._pyttsx3_engine is None:
                self._pyttsx3_engine = pyttsx3.init()
                # Ajusta velocidade (200 wpm padrão)
                rate = self._pyttsx3_engine.getProperty("rate")
                self._pyttsx3_engine.setProperty("rate", int(rate * 1.1))

            if not self._stop_event.is_set():
                self._pyttsx3_engine.say(text)
                self._pyttsx3_engine.runAndWait()
        except ImportError:
            print(f"[TTS] Sem motor TTS disponível. Resposta: {text}")
        except Exception as e:
            print(f"[TTS] Erro pyttsx3: {e}")

    def _ensure_pygame(self) -> None:
        if not self._pygame_init:
            try:
                import pygame
                pygame.mixer.init()
                self._pygame_init = True
            except Exception as e:
                print(f"[TTS] Aviso: pygame não inicializou ({e}). Usando pyttsx3.")
                self._use_edge = False

    # ------------------------------------------------------------------ #
    #  Estado                                                              #
    # ------------------------------------------------------------------ #

    @property
    def is_playing(self) -> bool:
        return self._playing
