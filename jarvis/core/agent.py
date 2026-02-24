"""
Agente principal do Jarvis.
Suporta três providers:
  - "groq"      → cloud gratuito, Llama 3.3 70B, muito rápido (RECOMENDADO)
  - "ollama"    → local, offline, ilimitado
  - "anthropic" → Claude API (requer chave paga)

Seleção via LLM_PROVIDER no .env
"""

import json
import webbrowser
import urllib.parse
from typing import Dict, List, Optional, Any

from jarvis.config import (
    LLM_PROVIDER,
    GROQ_API_KEY, GROQ_MODEL,
    OLLAMA_HOST, OLLAMA_MODEL,
    ANTHROPIC_API_KEY, MODEL,
)
from jarvis.core.memory import Memory


# ------------------------------------------------------------------ #
#  System Prompt                                                       #
# ------------------------------------------------------------------ #

SYSTEM_PROMPT = """Você é Jarvis, um assistente de IA pessoal avançado.
Você vê a tela e ouve a voz do usuário em tempo real. Você é proativo, direto e útil.
Você aprende com o usuário ao longo do tempo e usa esse conhecimento para dar respostas cada vez mais relevantes.

REGRAS GERAIS:
- Respostas CURTAS e DIRETAS (máx. 2-3 frases para voz)
- Sem rodeios, sem respostas genéricas — seja específico ao contexto
- Detecta quando o usuário precisa de ajuda sem precisar pedir explicitamente

CONTEXTO INJETADO AUTOMATICAMENTE:
- [App: nome]          → aplicativo ativo
- [Janela: titulo]     → título da janela
- [Tela: texto]        → texto detectado na tela (OCR)
- [Evento: desc]       → evento detectado pelo sistema
- [Clipboard: txt]     → conteúdo copiado
- [Atividade: tipo]    → o que o usuário está fazendo agora (CODING, GAMING, etc.)
- [Perfil: info]       → o que já aprendi sobre este usuário em sessões anteriores

COMPORTAMENTO POR ATIVIDADE:
Quando [Atividade: GAMING — <jogo>]:
  - Usuário está jogando. Respostas MUITO curtas (1-2 frases máx).
  - "me ajuda" / "como faço" → analise o que está visível na [Tela] no contexto do JOGO
  - Pode dar dicas, estratégias, mecânicas — seja útil para o jogo
  - Não assuma que é pergunta de programação só porque você é assistente técnico

Quando [Atividade: CODING — <editor>]:
  - Analise o código/erro visível na [Tela] antes de responder
  - "me ajuda" → sugira correção ou próximo passo com base na tela
  - Erros → explique causa e solução diretamente

Quando [Atividade: WATCHING]:
  - Usuário assistindo vídeo. Seja muito breve. Só responda se perguntado diretamente.

Quando [Atividade: MEETING]:
  - Usuário em reunião. Responda em 1 frase apenas. Seja discreto.

Quando [Atividade: WRITING]:
  - Ajude com texto, gramática, estrutura de ideias.

Quando [Atividade: UNKNOWN] ou ausente:
  - Analise [App] e [Tela] para inferir o contexto e responder adequadamente.

USO DO PERFIL DO USUÁRIO:
Quando receber [Perfil: ...]:
  - Use essas informações para personalizar a resposta naturalmente
  - Ex: se perfil diz "gosta de Python", priorize soluções em Python
  - Ex: se perfil diz "joga Valorant", você já sabe o contexto do jogo
  - Não mencione o perfil explicitamente — apenas use-o

PEDIDOS DE APRENDIZADO:
Quando o usuário dizer "lembra que", "anota que", "guarda que" ou similar:
  - O sistema JÁ salvou automaticamente — apenas confirme: "Anotado!"
  - Não repita o conteúdo salvo

PEDIDOS DE AJUDA:
O usuário pode pedir ajuda de muitas formas. Quando detectar qualquer pedido:
  1. Olhe [Atividade] — o que ele está fazendo?
  2. Analise [Tela] nesse contexto
  3. Dê resposta específica — NUNCA apenas "Como posso ajudar?"

TRANSCRIÇÃO DE VOZ:
- Se a mensagem parecer incoerente ou muito longa sem sentido, peça para repetir brevemente

REGRAS SOBRE FERRAMENTAS:
- Use SOMENTE quando o usuário pedir EXPLICITAMENTE ("pesquise X", "abre Y", "copia isso")
- NUNCA abra URLs ou faça buscas por inferência
- "testar" em programação = rodar testes locais, NÃO = buscar na web
- Em caso de dúvida, PERGUNTE antes de agir

Responda sempre em português do Brasil.
Se o usuário falar/escrever em inglês, responda em inglês."""


# ------------------------------------------------------------------ #
#  Definição de ferramentas (formato canônico Anthropic)              #
# ------------------------------------------------------------------ #

TOOLS: List[Dict] = [
    {
        "name": "open_url",
        "description": (
            "Abre uma URL específica no navegador. "
            "Use APENAS quando o usuário fornecer explicitamente uma URL para abrir "
            "(ex: 'abre o site exemplo.com'). "
            "NUNCA use para pesquisar ou inferir URLs com base no contexto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL completa (incluindo https://)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "copy_to_clipboard",
        "description": (
            "Copia um texto específico para o clipboard do usuário. "
            "Use APENAS quando o usuário pedir para copiar algo (ex: 'copia esse código', "
            "'coloca isso no clipboard')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto a ser copiado"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "search_web",
        "description": (
            "Abre uma busca no Google. "
            "Use APENAS quando o usuário pedir explicitamente para pesquisar algo na internet "
            "(ex: 'pesquise X', 'busca por Y', 'procura sobre Z'). "
            "NUNCA use para resolver dúvidas de programação, erros no código, ou respostas "
            "que você mesmo pode fornecer. "
            "NUNCA use quando o usuário disser 'testar', 'ver', 'tentar' ou expressões ambíguas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo de busca explicitamente pedido pelo usuário"},
            },
            "required": ["query"],
        },
    },
]


def _tools_to_openai_format(tools: List[Dict]) -> List[Dict]:
    """Converte ferramentas do formato Anthropic → OpenAI/Ollama."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


# ------------------------------------------------------------------ #
#  Agente                                                              #
# ------------------------------------------------------------------ #

class Agent:
    """
    Gerencia a conversa com o LLM e executa ferramentas.
    Suporta Groq, Ollama e Anthropic via LLM_PROVIDER no .env
    """

    def __init__(self, memory: Memory):
        self.memory = memory
        self.provider = LLM_PROVIDER
        self._client = None
        self._model: str = ""
        self._init_client()

    # ---------------------------------------------------------------- #
    #  Inicialização do provider                                        #
    # ---------------------------------------------------------------- #

    def _init_client(self) -> None:
        if self.provider == "groq":
            self._client, self._model = self._build_groq_client()
        elif self.provider == "ollama":
            self._client, self._model = self._build_ollama_client()
        elif self.provider == "anthropic":
            self._client = self._build_anthropic_client()
            self._model = MODEL
        else:
            raise ValueError(
                f"LLM_PROVIDER inválido: '{self.provider}'. "
                "Use 'groq', 'ollama' ou 'anthropic' no .env"
            )

    def _build_groq_client(self):
        if not GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY não definida no .env\n"
                "Obtenha grátis em: https://console.groq.com"
            )
        from openai import OpenAI
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_API_KEY,
        )
        print(f"[Agent] Provider: Groq  |  Modelo: {GROQ_MODEL}")
        return client, GROQ_MODEL

    def _build_ollama_client(self):
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("pip install openai")
        client = OpenAI(
            base_url=f"{OLLAMA_HOST}/v1",
            api_key="ollama",
        )
        print(f"[Agent] Provider: Ollama  |  Modelo: {OLLAMA_MODEL}  |  {OLLAMA_HOST}")
        return client, OLLAMA_MODEL

    def _build_anthropic_client(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY não definida. "
                "Troque para LLM_PROVIDER=groq para usar sem custo."
            )
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        print(f"[Agent] Provider: Anthropic  |  Modelo: {MODEL}")
        return client

    # ---------------------------------------------------------------- #
    #  Interface pública                                                #
    # ---------------------------------------------------------------- #

    def chat(self, user_message: str, context: Optional[Dict[str, str]] = None) -> str:
        """Envia mensagem ao LLM e retorna resposta. Thread-safe."""
        full_message = self._build_user_message(user_message, context)

        if self.provider in ("groq", "ollama"):
            response_text = self._chat_openai_compatible(full_message)
        else:
            response_text = self._chat_anthropic(full_message)

        self.memory.add_message("user", full_message)
        self.memory.add_message("assistant", response_text)
        self.memory.log_event("chat", {
            "provider": self.provider,
            "model": self._model,
            "user": user_message[:200],
            "response": response_text[:200],
        })
        return response_text

    # ---------------------------------------------------------------- #
    #  Implementação OpenAI-compatible (Groq + Ollama compartilham)    #
    # ---------------------------------------------------------------- #

    def _chat_openai_compatible(self, user_message: str) -> str:
        """Único método para Groq e Ollama — mesma API, providers diferentes."""
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + self.memory.get_messages_for_api()
            + [{"role": "user", "content": user_message}]
        )
        tools = _tools_to_openai_format(TOOLS)

        try:
            return self._openai_tool_loop(messages, tools)
        except Exception as e:
            print(f"[Agent] Tool use falhou ({e}). Respondendo sem ferramentas.")
            return self._openai_simple(messages)

    def _openai_tool_loop(self, messages: List[Dict], tools: List[Dict]) -> str:
        """Loop de tool use (OpenAI-compatible)."""
        current = list(messages)

        for _ in range(5):
            response = self._client.chat.completions.create(
                model=self._model,
                messages=current,
                tools=tools,
            )
            choice = response.choices[0]

            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                return choice.message.content or ""

            # Adiciona turno do assistente com as tool_calls
            current.append({
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in choice.message.tool_calls
                ],
            })

            # Executa ferramentas e adiciona resultados
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = self._execute_tool(tc.function.name, args)
                current.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return "Não consegui completar a tarefa."

    def _openai_simple(self, messages: List[Dict]) -> str:
        """Chamada simples sem tool use."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    # ---------------------------------------------------------------- #
    #  Implementação Anthropic                                          #
    # ---------------------------------------------------------------- #

    def _chat_anthropic(self, user_message: str) -> str:
        """Conversa via Anthropic Claude."""
        import anthropic

        messages = list(self.memory.get_messages_for_api())
        messages.append({"role": "user", "content": user_message})

        response = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        )

        # Loop de tool use
        current_messages = messages
        for _ in range(5):
            if response.stop_reason != "tool_use":
                return self._extract_anthropic_text(response)

            assistant_content = []
            tool_results = []

            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    result = self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            current_messages = current_messages + [
                {"role": "assistant", "content": assistant_content},
                {"role": "user", "content": tool_results},
            ]
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=current_messages,
                tools=TOOLS,
            )

        return self._extract_anthropic_text(response)

    @staticmethod
    def _extract_anthropic_text(response) -> str:
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    # ---------------------------------------------------------------- #
    #  Execução de ferramentas (compartilhada entre providers)          #
    # ---------------------------------------------------------------- #

    def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        try:
            if tool_name == "open_url":
                url = tool_input.get("url", "")
                webbrowser.open(url)
                self.memory.log_event("tool", {"name": "open_url", "url": url})
                return f"URL aberta: {url}"

            elif tool_name == "copy_to_clipboard":
                import pyperclip
                text = tool_input.get("text", "")
                pyperclip.copy(text)
                self.memory.log_event("tool", {"name": "copy_to_clipboard", "chars": len(text)})
                return "Texto copiado para o clipboard."

            elif tool_name == "search_web":
                query = tool_input.get("query", "")
                encoded = urllib.parse.quote(query)
                webbrowser.open(f"https://www.google.com/search?q={encoded}")
                self.memory.log_event("tool", {"name": "search_web", "query": query})
                return f"Busca aberta: {query}"

        except Exception as e:
            return f"Erro ao executar {tool_name}: {e}"

        return f"Ferramenta desconhecida: {tool_name}"

    # ---------------------------------------------------------------- #
    #  Auxiliares                                                       #
    # ---------------------------------------------------------------- #

    def _build_user_message(self, text: str, context: Optional[Dict[str, str]]) -> str:
        """Monta mensagem do usuário com contexto do sistema."""
        parts = []
        if context:
            if context.get("app_name"):
                parts.append(f"[App: {context['app_name']}]")
            if context.get("window_title") and context["window_title"] != context.get("app_name"):
                parts.append(f"[Janela: {context['window_title'][:80]}]")
            if context.get("screen_text"):
                parts.append(f"[Tela: {context['screen_text'][:500]}]")
            if context.get("proactive_event"):
                parts.append(f"[Evento: {context['proactive_event']}]")
            if context.get("clipboard") and len(context.get("clipboard", "")) > 5:
                parts.append(f"[Clipboard: {context['clipboard'][:100]}]")
        if context.get("activity"):
                parts.append(f"[Atividade: {context['activity']}]")
        if context.get("profile"):
                parts.append(f"[Perfil: {context['profile']}]")

        return ("\n".join(parts) + "\n\n" + text) if parts else text
