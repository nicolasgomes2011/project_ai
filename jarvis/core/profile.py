"""Perfil persistente do usuário — aprende entre sessões."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from jarvis.config import PROFILE_PATH


_PROFILE_VERSION = 1
_MAX_INSIGHTS = 100


class UserProfile:
    """
    Persiste o que Jarvis aprende sobre o usuário entre sessões.

    Arquivo: logs/user_profile.json
    Formato:
    {
        "version": 1,
        "session_count": 12,
        "last_seen": "2026-02-24T21:00:00",
        "learned_apps": {"Minecraft": "GAMING", "Figma": "WRITING"},
        "insights": ["Usuário prefere Python", "Joga Valorant à noite"],
        "activity_stats": {"CODING": 34, "GAMING": 12, "BROWSING": 5}
    }
    """

    def __init__(self):
        self._path: Path = PROFILE_PATH
        self.session_count: int = 0
        self.last_seen: str = ""
        self.learned_apps: Dict[str, str] = {}          # app_name → ActivityType.value
        self.insights: List[str] = []                   # bullet strings, max 100
        self.activity_stats: Dict[str, int] = {}        # ActivityType.value → count

    # ------------------------------------------------------------------ #
    #  Carregamento e persistência                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls) -> "UserProfile":
        """
        Carrega perfil do disco. Cria novo perfil se o arquivo não existir.
        Sempre retorna uma instância válida — nunca lança exceção.
        """
        profile = cls()
        try:
            if PROFILE_PATH.exists():
                with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile._from_dict(data)
                print(f"[Profile] Perfil carregado: {profile.profile_summary}")
            else:
                print("[Profile] Novo usuário — perfil criado.")
        except Exception as e:
            print(f"[Profile] Aviso: não foi possível carregar perfil ({e}). Usando perfil vazio.")
        return profile

    def save(self) -> None:
        """Persiste o perfil no disco. Silencia erros de I/O."""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Profile] Aviso: erro ao salvar perfil ({e}).")

    def _to_dict(self) -> dict:
        return {
            "version": _PROFILE_VERSION,
            "session_count": self.session_count,
            "last_seen": datetime.now().isoformat(timespec="seconds"),
            "learned_apps": self.learned_apps,
            "insights": self.insights,
            "activity_stats": self.activity_stats,
        }

    def _from_dict(self, data: dict) -> None:
        self.session_count = data.get("session_count", 0)
        self.last_seen = data.get("last_seen", "")
        self.learned_apps = data.get("learned_apps", {})
        self.insights = data.get("insights", [])
        self.activity_stats = data.get("activity_stats", {})

    # ------------------------------------------------------------------ #
    #  Mutação — chamados durante a sessão                                 #
    # ------------------------------------------------------------------ #

    def learn_app(self, app_name: str, activity_type_value: str) -> None:
        """
        Associa um app a um tipo de atividade. Persiste imediatamente.
        Ex: learn_app("Figma", "WRITING")
        """
        if app_name and activity_type_value:
            self.learned_apps[app_name] = activity_type_value
            self.save()
            print(f"[Profile] Aprendi: '{app_name}' → {activity_type_value}")

    def add_insights(self, insights: List[str]) -> None:
        """
        Adiciona múltiplos bullet points. Deduplica. Descarta os mais antigos
        quando supera _MAX_INSIGHTS.
        """
        if not insights:
            return
        for item in insights:
            item = item.strip().lstrip("-•*· ").strip()
            if len(item) < 5:
                continue
            # Deduplicação simples: checa se prefixo de 40 chars já existe
            key = item[:40].lower()
            already_exists = any(key in existing.lower() for existing in self.insights)
            if not already_exists:
                self.insights.append(item)

        # Mantém apenas os mais recentes
        if len(self.insights) > _MAX_INSIGHTS:
            self.insights = self.insights[-_MAX_INSIGHTS:]

    def update_activity(self, activity_type_value: str) -> None:
        """Incrementa o contador de atividade detectada (para estatísticas)."""
        if activity_type_value and activity_type_value != "UNKNOWN":
            self.activity_stats[activity_type_value] = (
                self.activity_stats.get(activity_type_value, 0) + 1
            )

    def increment_session(self) -> None:
        """Incrementa o contador de sessões."""
        self.session_count += 1

    # ------------------------------------------------------------------ #
    #  Leitura — para injetar no LLM                                       #
    # ------------------------------------------------------------------ #

    def get_context_for_llm(self, max_chars: int = 300) -> str:
        """
        Retorna um snippet compacto do perfil para injetar no contexto do LLM.
        Prioriza insights mais recentes. Retorna string vazia se perfil vazio.
        """
        parts = []

        if self.insights:
            recent = self.insights[-5:]  # Últimos 5 insights
            parts.append("O que sei sobre você: " + "; ".join(recent))

        if self.activity_stats:
            top = max(self.activity_stats.items(), key=lambda x: x[1])
            parts.append(f"Atividade mais comum: {top[0]}")

        result = " | ".join(parts)
        return result[:max_chars] if result else ""

    @property
    def profile_summary(self) -> str:
        """Resumo legível em uma linha para log de startup."""
        if self.session_count == 0 and not self.insights:
            return "Novo usuário, sem dados ainda."
        top_activity = ""
        if self.activity_stats:
            top = max(self.activity_stats.items(), key=lambda x: x[1])
            top_activity = f" | Atividade mais comum: {top[0]}"
        return (
            f"{self.session_count} sessão(ões) | "
            f"{len(self.insights)} insight(s){top_activity}"
        )

    @property
    def is_empty(self) -> bool:
        return not self.insights and not self.learned_apps and self.session_count == 0
