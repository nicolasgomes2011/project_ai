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
# "anthropic"  → Claude (PADRÃO — requer ANTHROPIC_API_KEY)
# "groq"       → cloud gratuito, rápido (requer GROQ_API_KEY)
# "ollama"     → local, offline, ilimitado (requer instalação)
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "anthropic")

# --- Anthropic Claude (padrão) ---
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
# Modelos disponíveis:
#   claude-sonnet-4-6        → RECOMENDADO: melhor qualidade + visão multimodal
#   claude-haiku-4-5-20251001 → mais rápido e barato
ANTHROPIC_MODEL: str = os.getenv("JARVIS_MODEL", "claude-sonnet-4-6")
MODEL: str = ANTHROPIC_MODEL  # alias de compatibilidade

# --- Groq (fallback cloud gratuito) ---
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
# Modelos disponíveis no free tier:
#   llama-3.1-8b-instant     → mais rápido, ideal para voz (14k req/dia)
#   llama-3.3-70b-versatile  → melhor qualidade (6k req/dia)
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Ollama (local) ---
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# --- Idioma ---
LANGUAGE: str = os.getenv("JARVIS_LANGUAGE", "pt")

# --- Áudio ---
AUDIO_SAMPLE_RATE: int = 16000      # Hz (webrtcvad exige: 8k, 16k, 32k ou 48k)
AUDIO_CHANNELS: int = 1             # Mono
FRAME_DURATION_MS: int = 30         # ms por frame VAD (10, 20 ou 30)
FRAME_SIZE: int = int(AUDIO_SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 amostras
VAD_AGGRESSIVENESS: int = 3         # 0 (permissivo) a 3 (agressivo) — 3 filtra ruído de fundo
SILENCE_THRESHOLD_MS: int = 1000    # ms de silêncio para encerrar utterance
PRE_SPEECH_MS: int = 300            # ms de buffer pré-fala

# --- Visão ---
SCREEN_CAPTURE_FPS: float = 1.0     # Frames por segundo
OCR_LANGUAGES: str = "por+eng"      # Idiomas do Tesseract
TESSERACT_CMD: str = os.getenv(
    "TESSERACT_PATH",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
# Idade máxima do frame (s) antes de forçar nova captura ao responder
VISION_FRAME_MAX_AGE_S: float = float(os.getenv("VISION_FRAME_MAX_AGE_S", "2.0"))
# Ativa logs de debug da visão (resolução, timestamp, tamanho)
VISION_DEBUG: bool = os.getenv("VISION_DEBUG", "false").lower() == "true"
# Qualidade JPEG do screenshot enviado ao LLM (1-95)
VISION_JPEG_QUALITY: int = int(os.getenv("VISION_JPEG_QUALITY", "50"))
# Largura máxima do screenshot enviado ao LLM (px)
VISION_MAX_WIDTH: int = int(os.getenv("VISION_MAX_WIDTH", "1280"))

# --- STT ---
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL", "medium")
WHISPER_LANGUAGE: str = "pt" if LANGUAGE == "pt" else None  # None = auto-detect

# Filtros de qualidade do Whisper (reduz alucinações e ruído de fundo)
# no_speech_prob: se a média dos segmentos indicar > X% de "não é fala", descarta
STT_NO_SPEECH_THRESHOLD: float = float(os.getenv("STT_NO_SPEECH_THRESHOLD", "0.6"))
# avg_logprob: probabilidade logarítmica média — muito negativa = baixa confiança
STT_LOG_PROB_THRESHOLD: float = float(os.getenv("STT_LOG_PROB_THRESHOLD", "-1.0"))
# Razão de palavras únicas: < X indica texto repetitivo (alucinação)
STT_REPETITION_THRESHOLD: float = float(os.getenv("STT_REPETITION_THRESHOLD", "0.45"))

# --- TTS ---
TTS_VOICE: str = os.getenv("JARVIS_TTS_VOICE", "pt-BR-FranciscaNeural")
TTS_RATE: str = os.getenv("JARVIS_TTS_RATE", "+10%")
TTS_USE_EDGE: bool = os.getenv("JARVIS_TTS_EDGE", "True").lower() == "true"

# --- Proatividade ---
PROACTIVITY_COOLDOWN: int = int(os.getenv("PROACTIVITY_COOLDOWN", "120"))

# --- Aprendizado persistente ---
PROFILE_PATH: Path = LOG_DIR / "user_profile.json"
SESSION_SUMMARY_MIN_EXCHANGES: int = int(os.getenv("SESSION_SUMMARY_MIN_EXCHANGES", "5"))

# --- Modo Anotação ---
NOTES_DIR: Path = LOG_DIR  # Notas salvas junto com os logs de sessão
