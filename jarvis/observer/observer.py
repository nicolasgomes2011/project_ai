"""Observer — analisa o estado atual e gera eventos proativos."""

import re
import time
from typing import List, Dict, Optional

from jarvis.observer.events import JarvisEvent, EventType, Priority
from jarvis.config import PROACTIVITY_COOLDOWN, PROACTIVITY_ENABLED


# ------------------------------------------------------------------ #
#  Padrões de detecção                                                 #
# ------------------------------------------------------------------ #

ERROR_PATTERNS = re.compile(
    r"\b(error|exception|traceback|failed|fatal|critical|"
    r"syntax error|module not found|cannot|invalid|"
    r"AttributeError|TypeError|ValueError|KeyError|"
    r"ImportError|NameError|IndexError|ZeroDivision|"
    r"ConnectionError|TimeoutError|PermissionError|"
    r"erro|falhou|falha|inválido|não encontrado)\b",
    re.IGNORECASE,
)

CONFUSION_PATTERNS = re.compile(
    r"("
    # Pedidos diretos de ajuda — variações naturais
    r"preciso de ajuda|preciso ajuda|preciso que me ajude|"
    r"me ajuda|me ajude|pode me ajudar|quero ajuda|"
    r"d[aá] uma ajuda|d[aá] uma força|me d[aá] uma ajuda|"
    r"me salva|me socorre|socorro|"
    # Não saber o que fazer / como prosseguir
    r"n[aã]o sei o que fazer|n[aã]o sei o que devo fazer|"
    r"n[aã]o sei como fazer|n[aã]o sei como prosseguir|"
    r"n[aã]o sei como continuar|n[aã]o sei como avançar|"
    r"n[aã]o sei por onde|n[aã]o sei o que|n[aã]o sei como|"
    r"n[aã]o sei o que devo|n[aã]o sei o que eu devo|"
    r"n[aã]o sei por onde começar|n[aã]o sei o que está|"
    r"sem saber o que fazer|sem ideia do que fazer|sem ideia|"
    r"perdido aqui|perdido nisso|"
    # Estar travado / perdido / bloqueado
    r"estou perdido|t[oô] perdido|to perdido|"
    r"estou travado|t[oô] travado|to travado|"
    r"estou preso|t[oô] preso|to preso|"
    r"estou bloqueado|t[oô] bloqueado|"
    r"estou confuso|t[oô] confuso|"
    r"me sinto perdido|me sinto travado|me sinto confuso|"
    r"n[aã]o estou conseguindo|n[aã]o t[oô] conseguindo|"
    r"n[aã]o consigo|n[aã]o estou entendendo|n[aã]o t[oô] entendendo|"
    r"n[aã]o entendo o que|n[aã]o entendo como|"
    # Problemas com código / execução
    r"n[aã]o funciona|n[aã]o t[aá] funcionando|n[aã]o está funcionando|"
    r"deu erro|deu problema|tá dando erro|está dando erro|"
    r"n[aã]o roda|n[aã]o executa|n[aã]o abre|quebrou|bugou|"
    r"o que esse erro|o que [eé] esse erro|como resolver esse erro|"
    # Inglês
    r"\bhelp\b|don't know|dont know|i'm stuck|im stuck|"
    r"\bstuck\b|\blost\b|\bconfused\b|can't figure|cant figure|"
    r"what should i do|how do i|what is this error"
    r")",
    re.IGNORECASE,
)

IDE_APPS = {"VS Code", "PyCharm", "Cursor", "IntelliJ", "Sublime Text", "Vim"}

BROWSER_APPS = {"Chrome", "Firefox", "Edge", "Safari", "Brave", "Opera"}

TECHNICAL_KEYWORDS = re.compile(
    r"\b(API|HTTP|JSON|SQL|async|await|function|class|import|"
    r"null|undefined|NaN|TypeError|git|docker|kubernetes|"
    r"deploy|pipeline|server|database|query|endpoint)\b",
    re.IGNORECASE,
)

# Padrões para extrair título de conteúdo do window title
_YOUTUBE   = re.compile(r"^(.+?)\s*[-–—]\s*YouTube\b", re.IGNORECASE)
# Twitter/X: "Título / X" ou "Título - Twitter"
_TWITTER   = re.compile(r"^(.+?)\s*(?:/\s*X|[-–—]\s*(?:Twitter|X))\b", re.IGNORECASE)
_REDDIT    = re.compile(r"^(.+?)\s*[-–—]\s*Reddit\b|^(r/\S+)", re.IGNORECASE)
_INSTAGRAM = re.compile(r"Instagram", re.IGNORECASE)
_TIKTOK    = re.compile(r"TikTok", re.IGNORECASE)
# Twitch: "canal - Twitch" ou "Twitch - algo"
_TWITCH    = re.compile(r"^(.+?)\s*[-–—]\s*Twitch\b|^Twitch\b\s*[-–—]\s*(.+)", re.IGNORECASE)
_ARTICLE   = re.compile(
    r"^(.+?)\s*[-–—]\s*.*(news|folha|globo|uol|g1|techcrunch|medium|substack"
    r"|nytimes|bbc|cnn|wired|ars technica|the verge)",
    re.IGNORECASE,
)


def _extract_content_info(window_title: str) -> Optional[tuple]:
    """
    Tenta extrair (tipo_conteudo, titulo) do window title.
    Retorna None se o título não indicar conteúdo reconhecível.
    """
    m = _YOUTUBE.match(window_title)
    if m:
        return ("YouTube", m.group(1).strip())

    m = _TWITTER.match(window_title)
    if m:
        return ("Twitter/X", m.group(1).strip())

    m = _REDDIT.match(window_title)
    if m:
        title = (m.group(1) or m.group(2) or "").strip()
        return ("Reddit", title)

    m = _TWITCH.match(window_title)
    if m:
        title = (m.group(1) or m.group(2) or "").strip()
        return ("Twitch", title)

    if _INSTAGRAM.search(window_title):
        return ("Instagram", window_title)

    if _TIKTOK.search(window_title):
        return ("TikTok", window_title)

    m = _ARTICLE.match(window_title)
    if m:
        return ("Artigo/Notícia", m.group(1).strip())

    return None


# ------------------------------------------------------------------ #
#  Observer                                                            #
# ------------------------------------------------------------------ #

class Observer:
    """
    Analisa o estado dos sensores e gera eventos proativos.
    Implementa cooldown para não ser intrusivo.
    """

    def __init__(self):
        self._last_event_time: float = 0.0
        self._last_window: str = ""
        self._stuck_start: float = 0.0         # Quando entrou na janela atual
        self._proactive_count: int = 0          # Total de eventos proativos
        self._cooldown: float = PROACTIVITY_COOLDOWN
        # Rastreia o último conteúdo comentado (evita repetição no mesmo vídeo/artigo)
        self._last_notified_content: str = ""

    def check(self, state: Dict) -> List[JarvisEvent]:
        """
        Verifica o estado atual e retorna lista de eventos proativos.

        state: {
            "screen_text": str,
            "window_title": str,
            "app_name": str,
            "last_speech": str,
            "elapsed_since_last_response": float,
        }
        """
        events: List[JarvisEvent] = []

        if not PROACTIVITY_ENABLED:
            return events

        if not self._can_be_proactive():
            return events

        screen_text = state.get("screen_text", "")
        window_title = state.get("window_title", "")
        app_name = state.get("app_name", "")
        last_speech = state.get("last_speech", "")
        elapsed = state.get("elapsed_since_last_response", 0.0)
        is_gaming = state.get("activity_type", "UNKNOWN") == "GAMING"

        # --- Detectar mudança de janela ---
        if window_title and window_title != self._last_window:
            self._last_window = window_title
            self._stuck_start = time.time()

        # --- Evento 1: Erro na tela (prioridade alta) ---
        if screen_text and ERROR_PATTERNS.search(screen_text):
            # Só avisa se em IDE e não está jogando (erros de jogo são normais)
            if app_name in IDE_APPS and elapsed > 60 and not is_gaming:
                events.append(JarvisEvent(
                    type=EventType.ERROR_DETECTED,
                    data={"app": app_name},
                    priority=Priority.HIGH,
                    description="Erro detectado na tela",
                    suggestion_prompt=(
                        "Detectei um possível erro ou problema na tela. "
                        "Gostaria de ajuda para resolver?"
                    ),
                ))

        # --- Evento 2: Usuário travado (mesmo app por muito tempo) ---
        time_stuck = time.time() - self._stuck_start if self._stuck_start else 0
        # Não dispara durante gaming — é normal jogar por horas
        if time_stuck > 180 and elapsed > 120 and app_name in IDE_APPS and not is_gaming:
            events.append(JarvisEvent(
                type=EventType.STUCK_DETECTED,
                data={"app": app_name, "minutes": round(time_stuck / 60, 1)},
                priority=Priority.MEDIUM,
                description=f"Usuário em {app_name} há {round(time_stuck/60, 1)} min",
                suggestion_prompt=(
                    f"Você está em {app_name} há alguns minutos. "
                    "Está tendo dificuldade com algo? Posso ajudar?"
                ),
            ))

        # --- Evento 3: Sinal de confusão na fala ---
        if last_speech and CONFUSION_PATTERNS.search(last_speech):
            events.append(JarvisEvent(
                type=EventType.CONFUSION_SIGNAL,
                data={"speech": last_speech[:100]},
                priority=Priority.HIGH,
                description="Possível confusão detectada na fala",
                suggestion_prompt=(
                    f"Parece que você está com dúvida: \"{last_speech[:80]}\". "
                    "Vou ajudar!"
                ),
            ))

        # --- Evento 4: Consciência de conteúdo (YouTube, artigos, redes sociais) ---
        content_event = self._check_content_awareness(
            window_title=window_title,
            app_name=app_name,
            screen_text=screen_text,
            elapsed=elapsed,
            is_gaming=is_gaming,
        )
        if content_event:
            events.append(content_event)

        # Retorna apenas o evento de maior prioridade para não sobrecarregar
        if events:
            events.sort(key=lambda e: e.priority, reverse=True)
            self._last_event_time = time.time()
            self._proactive_count += 1
            return events[:1]  # Apenas 1 evento por vez

        return []

    def _check_content_awareness(
        self,
        window_title: str,
        app_name: str,
        screen_text: str,
        elapsed: float,
        is_gaming: bool,
    ) -> Optional[JarvisEvent]:
        """
        Detecta se o usuário está assistindo/lendo algo interessante e
        retorna um evento para comentar, caso ainda não tenha comentado
        sobre este conteúdo específico.
        """
        if is_gaming or not window_title:
            return None

        # Só dispara se o usuário ficou quieto por pelo menos 20s
        # (não interrompe logo ao abrir algo)
        if elapsed < 20:
            return None

        content_info = _extract_content_info(window_title)
        if content_info is None:
            return None

        content_type, content_title = content_info

        # Não repete comentário sobre o mesmo conteúdo
        content_key = f"{content_type}::{content_title}"
        if content_key == self._last_notified_content:
            return None

        self._last_notified_content = content_key

        # Monta prompt contextual com texto da tela se disponível
        screen_excerpt = screen_text[:300].strip() if screen_text else ""
        screen_hint = (
            f"\nTexto visível na tela: \"{screen_excerpt}\"" if screen_excerpt else ""
        )

        prompt = (
            f"O usuário está {_content_verb(content_type)} no {content_type}: "
            f"\"{content_title}\".{screen_hint}\n"
            "Faça um comentário natural, curto e relevante sobre o que ele está vendo. "
            "Pode ser uma opinião, curiosidade, pergunta, ou observação — "
            "como um amigo que está junto assistindo/lendo a mesma coisa."
        )

        return JarvisEvent(
            type=EventType.CONTENT_AWARENESS,
            data={"content_type": content_type, "title": content_title},
            priority=Priority.MEDIUM,
            description=f"Usuário acessando {content_type}: {content_title[:60]}",
            suggestion_prompt=prompt,
        )

    def _can_be_proactive(self) -> bool:
        """Verifica se o cooldown expirou antes de gerar novo evento."""
        return (time.time() - self._last_event_time) >= self._cooldown


def _content_verb(content_type: str) -> str:
    """Retorna o verbo apropriado para o tipo de conteúdo."""
    verbs = {
        "YouTube": "assistindo a um vídeo",
        "Twitch": "assistindo uma live",
        "Twitter/X": "vendo um post",
        "Reddit": "lendo um post",
        "Instagram": "vendo",
        "TikTok": "vendo",
        "Artigo/Notícia": "lendo um artigo",
    }
    return verbs.get(content_type, "vendo conteúdo")

    def reset_cooldown(self) -> None:
        """Reseta o cooldown (chamar após qualquer interação do usuário)."""
        self._stuck_start = time.time()

    @property
    def proactive_count(self) -> int:
        return self._proactive_count
