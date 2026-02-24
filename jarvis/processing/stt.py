"""STT — Speech-to-Text usando faster-whisper (local, offline)."""

import numpy as np
from typing import Optional
import threading

from jarvis.config import WHISPER_MODEL_SIZE, WHISPER_LANGUAGE, AUDIO_SAMPLE_RATE


class STTProcessor:
    """
    Transcreve áudio para texto usando faster-whisper.
    O modelo é carregado na primeira chamada (lazy loading).
    """

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._model_size = WHISPER_MODEL_SIZE
        self._language = WHISPER_LANGUAGE  # "pt", "en" ou None (auto)

    def _load_model(self) -> None:
        """Carrega o modelo (pode demorar na primeira vez — download automático)."""
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
            print(f"[STT] Carregando modelo Whisper '{self._model_size}'... (primeira vez pode demorar)")
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",  # Mais rápido na CPU
            )
            print("[STT] Modelo carregado.")
        except ImportError:
            raise RuntimeError(
                "faster-whisper não instalado. Execute: pip install faster-whisper"
            )

    def transcribe(self, audio_bytes: bytes, sample_rate: int = None) -> str:
        """
        Transcreve audio_bytes (int16, mono, 16kHz) para texto.
        Thread-safe: pode ser chamado de múltiplos threads.
        """
        if not audio_bytes:
            return ""

        with self._lock:
            self._load_model()

        sr = sample_rate or AUDIO_SAMPLE_RATE

        # Converter bytes int16 → float32 normalizado
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Duração mínima: descartar áudio muito curto (< 0.3s)
        if len(audio_np) / sr < 0.3:
            return ""

        try:
            segments, info = self._model.transcribe(
                audio_np,
                beam_size=5,
                language=self._language,
                vad_filter=True,                  # Filtra silêncio residual
                vad_parameters=dict(
                    min_silence_duration_ms=200,
                    speech_pad_ms=100,
                ),
            )
            text = " ".join(seg.text for seg in segments).strip()
            return text
        except Exception as e:
            print(f"[STT] Erro na transcrição: {e}")
            return ""

    @property
    def is_ready(self) -> bool:
        return self._model is not None
