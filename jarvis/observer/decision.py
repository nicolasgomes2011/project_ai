"""Decision Engine — decide o que fazer com cada evento proativo."""

from typing import Optional
from jarvis.observer.events import JarvisEvent, EventType, Priority


class Action:
    IGNORE = "ignore"
    SUGGEST = "suggest"
    EXECUTE = "execute"


class DecisionEngine:
    """
    Recebe um evento e decide qual ação tomar:
    - IGNORE: não fazer nada
    - SUGGEST: enviar sugestão ao usuário via agente
    - EXECUTE: executar ferramenta diretamente (futuramente)
    """

    def decide(
        self,
        event: JarvisEvent,
        is_processing: bool = False,
        is_speaking: bool = False,
        is_user_speaking: bool = False,
    ) -> str:
        """
        Retorna a ação a tomar.

        Parâmetros:
            event: O evento gerado pelo Observer
            is_processing: Agente está processando outra requisição
            is_speaking: TTS está falando
            is_user_speaking: Usuário está falando (VAD ativo)
        """
        # Nunca interrompe fala do usuário ou processamento ativo
        if is_user_speaking or is_processing or is_speaking:
            return Action.IGNORE

        # Alta prioridade: erros e confusão → sempre sugere
        if event.priority == Priority.HIGH:
            return Action.SUGGEST

        # Média prioridade: só sugere se evento relevante
        if event.priority == Priority.MEDIUM:
            if event.type in (EventType.STUCK_DETECTED, EventType.IDE_OPEN):
                return Action.SUGGEST

        # Baixa prioridade: ignora
        return Action.IGNORE
