"""Sensor de áudio: captura contínua do microfone com detecção de fala (VAD)."""

import asyncio
import queue
import threading
import time
from typing import Callable, Coroutine, Optional

from jarvis.config import (
    AUDIO_SAMPLE_RATE,
    AUDIO_CHANNELS,
    FRAME_SIZE,
    FRAME_DURATION_MS,
    VAD_AGGRESSIVENESS,
    SILENCE_THRESHOLD_MS,
    PRE_SPEECH_MS,
)


class AudioSensor:
    """
    Captura áudio do microfone em tempo real e detecta utterances completas.

    Pipeline:
        sounddevice callback → thread queue → VAD thread → asyncio callback
    """

    def __init__(self):
        self._chunk_queue: queue.Queue = queue.Queue(maxsize=200)
        self._running: bool = False
        self._stream = None
        self._process_thread: Optional[threading.Thread] = None

        # Estado do VAD
        self._in_speech: bool = False
        self._speech_frames: list = []
        self._silence_count: int = 0
        self._pre_buffer: list = []

        # Limites em número de frames
        self._silence_max: int = int(SILENCE_THRESHOLD_MS / FRAME_DURATION_MS)
        self._pre_buffer_size: int = int(PRE_SPEECH_MS / FRAME_DURATION_MS)
        self._min_speech_frames: int = 3  # evita ruídos curtíssimos

        # Bridge asyncio
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._utterance_callback: Optional[Callable] = None  # coroutine

        # Inicializa VAD
        self._vad = self._init_vad()

    # ------------------------------------------------------------------ #
    #  Inicialização                                                       #
    # ------------------------------------------------------------------ #

    def _init_vad(self):
        try:
            import webrtcvad
            return webrtcvad.Vad(VAD_AGGRESSIVENESS)
        except ImportError:
            print("[Audio] AVISO: webrtcvad não instalado. VAD desativado.")
            return None

    # ------------------------------------------------------------------ #
    #  API pública                                                         #
    # ------------------------------------------------------------------ #

    def set_callback(
        self,
        loop: asyncio.AbstractEventLoop,
        callback: Callable[[bytes], Coroutine],
    ) -> None:
        """Define a coroutine chamada ao detectar utterance completa."""
        self._loop = loop
        self._utterance_callback = callback

    def start(self) -> None:
        """Inicia captura de áudio."""
        try:
            import sounddevice as sd
        except ImportError:
            raise RuntimeError("sounddevice não instalado: pip install sounddevice")

        self._running = True
        self._stream = sd.RawInputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            dtype="int16",
            blocksize=FRAME_SIZE,
            callback=self._sd_callback,
        )
        self._stream.start()

        self._process_thread = threading.Thread(
            target=self._vad_loop, daemon=True, name="jarvis-vad"
        )
        self._process_thread.start()
        print("[Audio] Sensor de áudio iniciado.")

    def stop(self) -> None:
        """Para captura de áudio."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        if self._process_thread:
            self._process_thread.join(timeout=2.0)
        print("[Audio] Sensor de áudio parado.")

    # ------------------------------------------------------------------ #
    #  Callbacks internos                                                  #
    # ------------------------------------------------------------------ #

    def _sd_callback(self, indata, frames, time_info, status) -> None:
        """Chamado pelo sounddevice em thread de áudio (alta prioridade)."""
        if not self._running:
            return
        try:
            self._chunk_queue.put_nowait(bytes(indata))
        except queue.Full:
            pass  # descarta frame se fila cheia

    def _vad_loop(self) -> None:
        """Loop de detecção de fala em thread separada."""
        while self._running:
            try:
                chunk = self._chunk_queue.get(timeout=0.1)
                self._process_chunk(chunk)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Audio] Erro no VAD loop: {e}")

    def _process_chunk(self, chunk: bytes) -> None:
        """Processa um frame de áudio com VAD e detecta utterances."""
        is_speech = self._detect_speech(chunk)

        if is_speech:
            if not self._in_speech:
                # Início da fala: inclui buffer pré-speech para contexto
                self._in_speech = True
                self._speech_frames = list(self._pre_buffer)
            self._speech_frames.append(chunk)
            self._silence_count = 0
        else:
            # Atualiza buffer pré-speech (fila circular)
            self._pre_buffer.append(chunk)
            if len(self._pre_buffer) > self._pre_buffer_size:
                self._pre_buffer.pop(0)

            if self._in_speech:
                self._silence_count += 1
                self._speech_frames.append(chunk)  # inclui silêncio final

                if self._silence_count >= self._silence_max:
                    # Fim da utterance
                    self._emit_utterance()

    def _detect_speech(self, chunk: bytes) -> bool:
        """Retorna True se o frame contém fala."""
        if self._vad is None:
            return True  # sem VAD: tratar tudo como fala
        try:
            return self._vad.is_speech(chunk, AUDIO_SAMPLE_RATE)
        except Exception:
            return False

    def _emit_utterance(self) -> None:
        """Emite a utterance capturada para o callback assíncrono."""
        frames = self._speech_frames[:]
        self._speech_frames = []
        self._in_speech = False
        self._silence_count = 0

        # Descarta utterances muito curtas (ruído)
        if len(frames) < self._min_speech_frames:
            return

        audio_bytes = b"".join(frames)

        if self._loop and self._utterance_callback:
            asyncio.run_coroutine_threadsafe(
                self._utterance_callback(audio_bytes), self._loop
            )

    # ------------------------------------------------------------------ #
    #  Estado                                                              #
    # ------------------------------------------------------------------ #

    @property
    def is_active(self) -> bool:
        return self._running

    @property
    def is_detecting_speech(self) -> bool:
        return self._in_speech
