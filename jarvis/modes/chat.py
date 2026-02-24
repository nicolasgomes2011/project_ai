"""Modo Chat — interação por texto no terminal (MVP base)."""

from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.text import Text
from rich import print as rprint

from jarvis.core.agent import Agent
from jarvis.core.memory import Memory
from jarvis.sensors.system_ctx import SystemContext


console = Console()


class ChatMode:
    """
    Modo texto simples: usuário digita → Jarvis responde.
    Opcionalmente captura contexto do sistema (janela ativa, clipboard).
    """

    def __init__(self, use_context: bool = True):
        self.memory = Memory()
        self.agent = Agent(self.memory)
        self.system_ctx = SystemContext()
        self.use_context = use_context
        self._running = False

    def run(self) -> None:
        """Loop principal do modo chat."""
        self._print_banner()
        self._running = True

        while self._running:
            try:
                user_input = Prompt.ask("\n[bold cyan]Você[/bold cyan]")
            except (EOFError, KeyboardInterrupt):
                self._shutdown()
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Comandos especiais
            if user_input.lower() in ("/quit", "/exit", "/sair"):
                self._shutdown()
                break
            if user_input.lower() in ("/clear", "/limpar"):
                self.memory.clear()
                console.clear()
                self._print_banner()
                continue
            if user_input.lower() in ("/help", "/ajuda"):
                self._print_help()
                continue
            if user_input.lower() == "/contexto":
                ctx = self.system_ctx.get_context()
                console.print(Panel(str(ctx), title="Contexto do Sistema", style="dim"))
                continue

            # Processa e responde
            context = self.system_ctx.get_context() if self.use_context else None

            with console.status("[bold yellow]Jarvis pensando...[/bold yellow]", spinner="dots"):
                try:
                    response = self.agent.chat(user_input, context)
                except Exception as e:
                    console.print(f"[red]Erro ao chamar o agente: {e}[/red]")
                    continue

            console.print(
                Panel(
                    Text(response, style="white"),
                    title="[bold green]Jarvis[/bold green]",
                    border_style="green",
                )
            )

    def _print_banner(self) -> None:
        console.print(Panel(
            "[bold green]JARVIS[/bold green] — Modo Chat\n"
            "[dim]Digite sua mensagem. Comandos: /ajuda /limpar /contexto /sair[/dim]",
            border_style="green",
        ))

    def _print_help(self) -> None:
        console.print(Panel(
            "/ajuda    — Mostra esta ajuda\n"
            "/limpar   — Limpa o histórico de conversa\n"
            "/contexto — Mostra contexto do sistema atual\n"
            "/sair     — Encerra o Jarvis",
            title="Comandos",
            border_style="cyan",
        ))

    def _shutdown(self) -> None:
        self._running = False
        console.print("\n[dim]Jarvis encerrado. Até logo![/dim]")
