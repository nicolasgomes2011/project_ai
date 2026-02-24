"""Configuração central do Jarvis. Carrega do .env e define constantes."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Diretórios
BASE_DIR = Path(__file__).parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# --- Provider LLM ---
# "groq"       → cloud gratuito, rápido, sem instalar nada (RECOMENDADO)
# "ollama"     → local, offline, ilimitado (requer instalação)
# "anthropic"  → Claude (requer chave paga)
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq")

# --- Groq (cloud gratuito) ---
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
# Modelos disponíveis no free tier:
#   llama-3.3-70b-versatile  → melhor qualidade (6k req/dia)
#   llama-3.1-8b-instant     → mais rápido, ideal para voz (14k req/dia)
#   gemma2-9b-it             → alternativa leve
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Ollama (local) ---
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# --- Anthropic (opcional) ---
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
MODEL: str = os.getenv("JARVIS_MODEL", "claude-sonnet-4-6")

# --- Idioma ---
LANGUAGE: str = os.getenv("JARVIS_LANGUAGE", "pt")

# --- Áudio ---
AUDIO_SAMPLE_RATE: int = 16000      # Hz (webrtcvad exige: 8k, 16k, 32k ou 48k)
AUDIO_CHANNELS: int = 1             # Mono
FRAME_DURATION_MS: int = 30         # ms por frame VAD (10, 20 ou 30)
FRAME_SIZE: int = int(AUDIO_SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 amostras
VAD_AGGRESSIVENESS: int = 2         # 0 (permissivo) a 3 (agressivo)
SILENCE_THRESHOLD_MS: int = 800     # ms de silêncio para encerrar utterance
PRE_SPEECH_MS: int = 300            # ms de buffer pré-fala

# --- Visão ---
SCREEN_CAPTURE_FPS: float = 1.0     # Frames por segundo
OCR_LANGUAGES: str = "por+eng"      # Idiomas do Tesseract
TESSERACT_CMD: str = os.getenv(
    "TESSERACT_PATH",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# --- STT ---
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL", "small")
WHISPER_LANGUAGE: str = "pt" if LANGUAGE == "pt" else None  # None = auto-detect

# --- TTS ---
TTS_VOICE: str = os.getenv("JARVIS_TTS_VOICE", "pt-BR-FranciscaNeural")
TTS_RATE: str = os.getenv("JARVIS_TTS_RATE", "+10%")
TTS_USE_EDGE: bool = os.getenv("JARVIS_TTS_EDGE", "True").lower() == "true"

# --- Proatividade ---
PROACTIVITY_COOLDOWN: int = int(os.getenv("PROACTIVITY_COOLDOWN", "120"))
