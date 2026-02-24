"""STT — Speech-to-Text usando faster-whisper (local, offline)."""

import re
import numpy as np
from typing import Optional
import threading

from jarvis.config import (
    WHISPER_MODEL_SIZE, WHISPER_LANGUAGE, AUDIO_SAMPLE_RATE,
    STT_NO_SPEECH_THRESHOLD, STT_LOG_PROB_THRESHOLD, STT_REPETITION_THRESHOLD,
)


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
            segments_gen, info = self._model.transcribe(
                audio_np,
                beam_size=5,
                language=self._language,
                condition_on_previous_text=False,  # Evita cascata de alucinações
                vad_filter=True,                   # Filtra silêncio residual
                vad_parameters=dict(
                    min_silence_duration_ms=300,
                    speech_pad_ms=100,
                ),
            )

            # Materializa generator para poder inspecionar qualidade
            segments = list(segments_gen)
            if not segments:
                return ""

            # --- Filtro 1: probabilidade de "não é fala" ---
            avg_no_speech = sum(s.no_speech_prob for s in segments) / len(segments)
            if avg_no_speech > STT_NO_SPEECH_THRESHOLD:
                print(f"[STT] Descartado — no_speech_prob={avg_no_speech:.2f}")
                return ""

            # --- Filtro 2: confiança geral muito baixa (alucinação) ---
            avg_logprob = sum(s.avg_logprob for s in segments) / len(segments)
            if avg_logprob < STT_LOG_PROB_THRESHOLD:
                print(f"[STT] Descartado — avg_logprob={avg_logprob:.2f}")
                return ""

            text = " ".join(s.text for s in segments).strip()

            # --- Filtro 3: texto repetitivo (alucinação por loop do Whisper) ---
            if self._is_repetitive(text):
                print(f"[STT] Descartado — texto repetitivo detectado")
                return ""

            return text
        except Exception as e:
            print(f"[STT] Erro na transcrição: {e}")
            return ""

    @staticmethod
    def _is_repetitive(text: str) -> bool:
        """
        Detecta alucinações do Whisper por repetição de frases.
        Ex: "Vai com a mão. Vai com a mão. Vai com a mão." → True
        """
        words = text.split()
        if len(words) < 8:
            return False  # Textos curtos não precisam de verificação

        # Checa razão de palavras únicas (menos de 45% únicas = repetitivo)
        unique_ratio = len(set(w.lower() for w in words)) / len(words)
        if unique_ratio < STT_REPETITION_THRESHOLD:
            return True

        # Checa repetição de trigramas (3 palavras seguidas repetidas)
        trigrams = [tuple(words[i:i+3]) for i in range(len(words) - 2)]
        if len(trigrams) > 3:
            unique_trigram_ratio = len(set(trigrams)) / len(trigrams)
            if unique_trigram_ratio < 0.5:
                return True

        return False

    @property
    def is_ready(self) -> bool:
        return self._model is not None
