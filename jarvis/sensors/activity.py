"""Sensor de atividade — infere o que o usuário está fazendo."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class ActivityType(str, Enum):
    CODING   = "CODING"
    GAMING   = "GAMING"
    BROWSING = "BROWSING"
    WATCHING = "WATCHING"
    WRITING  = "WRITING"
    MEETING  = "MEETING"
    IDLE     = "IDLE"
    UNKNOWN  = "UNKNOWN"


@dataclass
class ActivityState:
    type: ActivityType
    confidence: float       # 0.0 – 1.0
    details: str            # Ex: "Valorant", "YouTube", "VS Code"

    def label(self) -> str:
        """Formato para injetar no contexto: 'GAMING — Valorant'"""
        if self.details:
            return f"{self.type.value} — {self.details}"
        return self.type.value


# ------------------------------------------------------------------ #
#  Dicionários de detecção                                            #
# ------------------------------------------------------------------ #

_IDE_APPS: set = {
    "vs code", "vscode", "pycharm", "cursor", "intellij", "intellij idea",
    "sublime text", "vim", "neovim", "emacs", "clion", "webstorm",
    "phpstorm", "rider", "android studio", "xcode", "code",
}

_TERMINAL_APPS: set = {
    "terminal", "powershell", "cmd", "bash", "wsl", "windows terminal",
    "iterm", "hyper", "alacritty", "kitty", "console",
}

_GAMING_APPS: set = {
    # Launchers
    "steam", "epic games", "epic games launcher", "battle.net", "battlenet",
    "ubisoft connect", "origin", "ea app", "gog galaxy", "itch.io",
    "xbox", "xbox app", "playnite",
    # FPS / Battle Royale
    "valorant", "csgo", "cs2", "counter-strike", "counter strike",
    "fortnite", "apex legends", "apex", "call of duty", "warzone",
    "rainbow six siege", "r6siege", "pubg", "battlegrounds",
    "overwatch", "overwatch 2", "hunt showdown", "escape from tarkov",
    "the finals", "xdefiant",
    # MOBA / Strategy
    "league of legends", "lol", "dota 2", "dota2", "smite",
    "heroes of the storm", "age of empires", "starcraft",
    "civilization", "total war",
    # RPG / Action
    "elden ring", "dark souls", "sekiro", "bloodborne",
    "cyberpunk 2077", "cyberpunk", "witcher", "the witcher",
    "red dead redemption", "rdr2", "grand theft auto", "gta",
    "assassin's creed", "assassins creed", "god of war",
    "monster hunter", "final fantasy", "persona",
    "genshin impact", "genshin", "honkai", "star rail",
    "lost ark", "path of exile", "diablo", "hades", "dead cells",
    "hollow knight", "ori", "celeste",
    # Survival / Sandbox
    "minecraft", "terraria", "stardew valley", "valheim",
    "rust", "ark survival", "ark", "satisfactory", "factorio",
    "rimworld", "dwarf fortress", "no man's sky", "subnautica",
    "the forest", "green hell",
    # Simulation / Sports
    "cities skylines", "the sims", "sims 4", "simcity",
    "fifa", "ea sports fc", "pes", "efootball",
    "nba 2k", "madden", "rocket league",
    # Puzzle / Casual
    "among us", "fall guys", "fall guys game", "roblox",
    "chess.com", "lichess", "chess",
    # Outros populares
    "destiny 2", "destiny", "world of warcraft", "wow",
    "new world", "final fantasy xiv", "ffxiv",
    "sea of thieves", "deep rock galactic",
}

_OFFICE_APPS: set = {
    "microsoft word", "word", "libreoffice writer",
    "notion", "obsidian", "roamresearch", "logseq", "typora",
    "bear", "craft", "ulysses", "onenote", "evernote",
}

_SPREADSHEET_APPS: set = {
    "microsoft excel", "excel", "libreoffice calc",
}

_MEETING_APPS: set = {
    "zoom", "microsoft teams", "teams", "google meet", "skype",
    "discord", "webex", "goto meeting", "bluejeans", "whereby",
}

_BROWSER_APPS: set = {
    "google chrome", "chrome", "mozilla firefox", "firefox",
    "microsoft edge", "edge", "safari", "brave", "opera", "vivaldi",
    "chromium", "arc",
}

# Padrões no título da janela quando o app é um BROWSER
_BROWSER_TITLE_PATTERNS: Dict[str, ActivityType] = {
    # WATCHING
    "youtube":           ActivityType.WATCHING,
    "netflix":           ActivityType.WATCHING,
    "twitch":            ActivityType.WATCHING,
    "prime video":       ActivityType.WATCHING,
    "disney+":           ActivityType.WATCHING,
    "hbo max":           ActivityType.WATCHING,
    "crunchyroll":       ActivityType.WATCHING,
    "globoplay":         ActivityType.WATCHING,
    "pluto tv":          ActivityType.WATCHING,
    "paramount+":        ActivityType.WATCHING,
    "apple tv":          ActivityType.WATCHING,
    # CODING
    "github":            ActivityType.CODING,
    "gitlab":            ActivityType.CODING,
    "bitbucket":         ActivityType.CODING,
    "stackoverflow":     ActivityType.CODING,
    "stack overflow":    ActivityType.CODING,
    "codepen":           ActivityType.CODING,
    "replit":            ActivityType.CODING,
    "codesandbox":       ActivityType.CODING,
    "vercel":            ActivityType.CODING,
    "netlify":           ActivityType.CODING,
    "heroku":            ActivityType.CODING,
    "aws console":       ActivityType.CODING,
    "azure":             ActivityType.CODING,
    "google cloud":      ActivityType.CODING,
    "localhost":         ActivityType.CODING,
    "127.0.0.1":         ActivityType.CODING,
    "docs.python":       ActivityType.CODING,
    "mdn web docs":      ActivityType.CODING,
    "developer.":        ActivityType.CODING,
    "npmjs":             ActivityType.CODING,
    "pypi":              ActivityType.CODING,
    "documentation":     ActivityType.CODING,
    # WRITING
    "google docs":       ActivityType.WRITING,
    "google slides":     ActivityType.WRITING,
    "notion":            ActivityType.WRITING,
    "medium":            ActivityType.WRITING,
    "substack":          ActivityType.WRITING,
    "wordpress":         ActivityType.WRITING,
    "overleaf":          ActivityType.WRITING,
    # MEETING
    "meet.google":       ActivityType.MEETING,
    "zoom.us":           ActivityType.MEETING,
    "teams.microsoft":   ActivityType.MEETING,
    # GAMING
    "chess.com":         ActivityType.GAMING,
    "lichess":           ActivityType.GAMING,
    "boardgamearena":    ActivityType.GAMING,
}

# Palavras-chave do texto OCR → inferência de CODING (último recurso)
_OCR_CODE_PATTERNS = re.compile(
    r"\b(def |class |import |from |const |let |var |function |async |await |"
    r"public |private |interface |struct |namespace |#include |"
    r"SELECT |INSERT |UPDATE |DELETE |CREATE TABLE|"
    r"TypeError|ValueError|AttributeError|SyntaxError|NameError|"
    r"git commit|git push|npm run|pip install|docker )\b",
    re.IGNORECASE,
)


# ------------------------------------------------------------------ #
#  ActivitySensor                                                      #
# ------------------------------------------------------------------ #

class ActivitySensor:
    """
    Infere o que o usuário está fazendo com base em:
    1. learned_apps (mapeamentos ensinados pelo usuário — máxima prioridade)
    2. Nome do app (matching contra dicionários)
    3. Título da janela (padrões de browser e outros)
    4. Texto OCR da tela (último recurso — só detecta CODING)

    Stateless: detect() é uma função pura, sem estado interno.
    """

    def detect(
        self,
        app_name: str,
        window_title: str,
        screen_text: str = "",
        learned_apps: Optional[Dict[str, str]] = None,
    ) -> ActivityState:
        """
        Retorna ActivityState com o tipo de atividade mais provável.

        Parâmetros:
            app_name:     Nome extraído pelo SystemContext (ex: "VS Code", "Chrome")
            window_title: Título completo da janela (ex: "project_ai - VS Code")
            screen_text:  Texto OCR da tela (pode ser vazio)
            learned_apps: Dict de mapeamentos aprendidos do UserProfile
        """
        app_lower   = (app_name or "").lower()
        title_lower = (window_title or "").lower()
        learned_apps = learned_apps or {}

        # --- Prioridade 1: mapeamentos ensinados pelo usuário ---
        for learned_app, activity_value in learned_apps.items():
            if learned_app.lower() in title_lower or learned_app.lower() in app_lower:
                try:
                    return ActivityState(
                        type=ActivityType(activity_value),
                        confidence=1.0,
                        details=app_name or learned_app,
                    )
                except ValueError:
                    pass  # ActivityType inválido salvo — ignora

        # --- Prioridade 2: nome do app contra dicionários fixos ---
        state = self._check_app_name(app_lower, app_name)
        if state:
            return state

        # --- Prioridade 3: título da janela ---
        state = self._check_window_title(title_lower, app_lower, app_name, window_title)
        if state:
            return state

        # --- Prioridade 4: conteúdo OCR (último recurso — só CODING) ---
        if screen_text and _OCR_CODE_PATTERNS.search(screen_text):
            return ActivityState(
                type=ActivityType.CODING,
                confidence=0.5,
                details="(inferido pelo OCR)",
            )

        return ActivityState(
            type=ActivityType.UNKNOWN,
            confidence=0.0,
            details=app_name or "",
        )

    def _check_app_name(self, app_lower: str, app_name: str) -> Optional[ActivityState]:
        """Checa o nome do app contra os dicionários fixos."""
        if any(g in app_lower for g in _GAMING_APPS):
            details = self._extract_game_name(app_lower, app_name)
            return ActivityState(ActivityType.GAMING, 0.95, details)

        if any(ide in app_lower for ide in _IDE_APPS):
            return ActivityState(ActivityType.CODING, 0.95, app_name)

        if any(t in app_lower for t in _TERMINAL_APPS):
            return ActivityState(ActivityType.CODING, 0.8, app_name)

        if any(m in app_lower for m in _MEETING_APPS):
            return ActivityState(ActivityType.MEETING, 0.9, app_name)

        if any(o in app_lower for o in _OFFICE_APPS):
            return ActivityState(ActivityType.WRITING, 0.85, app_name)

        if any(s in app_lower for s in _SPREADSHEET_APPS):
            return ActivityState(ActivityType.WRITING, 0.8, app_name)

        return None

    def _check_window_title(
        self,
        title_lower: str,
        app_lower: str,
        app_name: str,
        window_title: str,
    ) -> Optional[ActivityState]:
        """Checa o título da janela, especialmente útil para browsers."""
        is_browser = any(b in app_lower for b in _BROWSER_APPS)

        if is_browser:
            for pattern, activity_type in _BROWSER_TITLE_PATTERNS.items():
                if pattern in title_lower:
                    detail = self._extract_title_detail(window_title)
                    return ActivityState(activity_type, 0.9, detail)
            # Browser sem padrão reconhecido → BROWSING genérico
            return ActivityState(ActivityType.BROWSING, 0.7, app_name)

        # Título pode revelar gaming mesmo que app_name não ajude
        if any(g in title_lower for g in _GAMING_APPS):
            details = self._extract_game_name(title_lower, window_title)
            return ActivityState(ActivityType.GAMING, 0.85, details)

        return None

    @staticmethod
    def _extract_game_name(text_lower: str, fallback: str) -> str:
        """Tenta extrair o nome do jogo detectado a partir do texto."""
        for game in sorted(_GAMING_APPS, key=len, reverse=True):
            if game in text_lower:
                return game.title()
        return fallback[:30] if fallback else "jogo"

    @staticmethod
    def _extract_title_detail(window_title: str) -> str:
        """Extrai a parte informativa do título da janela do browser."""
        for suffix in [
            " - Google Chrome", " - Firefox", " - Microsoft Edge",
            " - Chromium", " - Brave", " – Google Chrome",
            " — Mozilla Firefox", " - Opera",
        ]:
            if window_title.endswith(suffix):
                return window_title[: -len(suffix)][:50]
        parts = window_title.split(" - ")
        return parts[0].strip()[:50] if parts else window_title[:50]
