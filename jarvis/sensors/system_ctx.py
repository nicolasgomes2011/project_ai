"""Sensor de contexto do sistema: janela ativa, clipboard, app em foco."""

import time
from typing import Dict, Optional


class SystemContext:
    """
    Coleta informações do sistema operacional:
    - Título e app da janela ativa
    - Conteúdo do clipboard
    """

    def __init__(self):
        self._last_window: str = ""
        self._last_window_time: float = 0.0
        self._cache_ttl: float = 1.0  # segundos

    def get_active_window(self) -> str:
        """Retorna o título da janela ativa ou string vazia."""
        try:
            import pygetwindow as gw
            window = gw.getActiveWindow()
            if window and window.title:
                return window.title.strip()
        except Exception:
            pass
        return ""

    def get_clipboard(self) -> str:
        """Retorna o conteúdo do clipboard (primeiros 500 chars)."""
        try:
            import pyperclip
            text = pyperclip.paste()
            return text[:500] if text else ""
        except Exception:
            return ""

    def get_context(self) -> Dict[str, str]:
        """Retorna dicionário com todo o contexto do sistema."""
        window_title = self.get_active_window()
        return {
            "window_title": window_title,
            "app_name": self._extract_app_name(window_title),
            "clipboard": self.get_clipboard(),
            "timestamp": str(time.time()),
        }

    def _extract_app_name(self, window_title: str) -> str:
        """Infere o nome do app a partir do título da janela."""
        if not window_title:
            return ""

        title_lower = window_title.lower()

        app_patterns = {
            "VS Code": ["visual studio code", "vscode", "code -"],
            "PyCharm": ["pycharm"],
            "Cursor": ["cursor"],
            "IntelliJ": ["intellij idea"],
            "Chrome": ["google chrome", "chrome"],
            "Firefox": ["mozilla firefox", "firefox"],
            "Edge": ["microsoft edge"],
            "Terminal": ["powershell", "cmd", "terminal", "bash", "wsl"],
            "Slack": ["slack"],
            "Teams": ["microsoft teams"],
            "Notion": ["notion"],
            "Excel": ["excel"],
            "Word": ["word"],
        }

        for app_name, patterns in app_patterns.items():
            if any(p in title_lower for p in patterns):
                return app_name

        return window_title.split(" - ")[-1].strip() if " - " in window_title else window_title[:30]
