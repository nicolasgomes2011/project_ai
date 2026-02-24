"""Memória de conversação e log de eventos estruturado do Jarvis."""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from jarvis.config import LOG_DIR


class Memory:
    """
    Mantém histórico de conversação (para contexto da API) e grava
    logs de eventos em formato JSONL para análise posterior.
    """

    def __init__(self, max_history: int = 40):
        self.max_history = max_history          # Máximo de pares user/assistant
        self._conversation: List[Dict] = []     # Histórico completo
        self._events: List[Dict] = []           # Log de eventos em memória
        self.session_start: float = time.time()
        self.last_response_time: float = time.time()
        self._log_file: Path = LOG_DIR / f"session_{int(self.session_start)}.jsonl"

    # ------------------------------------------------------------------ #
    #  Conversação                                                         #
    # ------------------------------------------------------------------ #

    def add_message(self, role: str, content: str) -> None:
        """Adiciona mensagem ao histórico. role: 'user' | 'assistant'."""
        self._conversation.append({
            "role": role,
            "content": content,
            "ts": time.time(),
        })
        # Mantém apenas os últimos max_history pares
        if len(self._conversation) > self.max_history * 2:
            self._conversation = self._conversation[-(self.max_history * 2):]

        if role == "assistant":
            self.last_response_time = time.time()

    def get_messages_for_api(self) -> List[Dict[str, str]]:
        """Retorna histórico no formato aceito pela Anthropic API."""
        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self._conversation
        ]

    def get_last_user_message(self) -> str:
        """Retorna a última mensagem do usuário ou string vazia."""
        for msg in reversed(self._conversation):
            if msg["role"] == "user":
                return msg["content"]
        return ""

    def get_recent_summary(self, n_exchanges: int = 3) -> str:
        """Retorna um resumo das últimas n_exchanges trocas."""
        recent = self._conversation[-(n_exchanges * 2):]
        lines = []
        for msg in recent:
            role = "Usuário" if msg["role"] == "user" else "Jarvis"
            text = msg["content"]
            if len(text) > 200:
                text = text[:200] + "..."
            lines.append(f"{role}: {text}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Limpa histórico de conversação (mantém logs)."""
        self._conversation.clear()

    # ------------------------------------------------------------------ #
    #  Log de eventos                                                      #
    # ------------------------------------------------------------------ #

    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Grava evento estruturado em memória e em arquivo JSONL."""
        entry = {
            "ts": time.time(),
            "type": event_type,
            "data": data,
        }
        self._events.append(entry)
        self._append_to_log(entry)

    def _append_to_log(self, entry: Dict) -> None:
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass  # Não interrompe a execução por falha de log

    # ------------------------------------------------------------------ #
    #  Utilidades                                                          #
    # ------------------------------------------------------------------ #

    @property
    def session_duration(self) -> float:
        return time.time() - self.session_start

    @property
    def message_count(self) -> int:
        return len(self._conversation)
