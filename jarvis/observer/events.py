"""Definição de eventos do Jarvis — usados pelo Observer e Decision Engine."""

from dataclasses import dataclass, field
from enum import Enum
import time


class EventType(str, Enum):
    # Eventos de sensor
    TRANSCRIPTION = "transcription"       # Fala do usuário transcrita
    SCREEN_CHANGE = "screen_change"       # Conteúdo da tela mudou significativamente
    WINDOW_CHANGE = "window_change"       # Usuário trocou de app/janela

    # Eventos proativos (gerados pelo Observer)
    ERROR_DETECTED = "error_detected"     # Erro visível na tela
    STUCK_DETECTED = "stuck_detected"     # Usuário parece travado
    IDE_OPEN = "ide_open"                 # IDE/editor aberto
    DEBUG_MODE = "debug_mode"             # Modo debug ativo
    CONFUSION_SIGNAL = "confusion_signal" # Usuário demonstrou dúvida/confusão
    TECHNICAL_CONTENT = "technical_content"  # Conteúdo técnico complexo
    CONTENT_AWARENESS = "content_awareness"  # Novo conteúdo relevante na tela (YouTube, artigo, etc.)

    # Eventos do sistema
    KILL_SWITCH = "kill_switch"           # Desligar tudo
    MODE_CHANGE = "mode_change"           # Mudança de modo (silencioso, ativo, etc.)


class Priority(int, Enum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


@dataclass
class JarvisEvent:
    type: EventType
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    priority: Priority = Priority.MEDIUM

    # Para eventos proativos — o que dizer ao agente
    description: str = ""         # Descrição legível do evento
    suggestion_prompt: str = ""   # Prompt a enviar ao agente
