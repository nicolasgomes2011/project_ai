"""
Jarvis — Assistente de IA com Voz + Visão em Tempo Real
Uso: python -m jarvis [--mode chat|realtime] [--no-vision] [--no-voice]
"""

import argparse
import asyncio
import signal
import sys

from rich.console import Console

console = Console()


def _check_provider() -> bool:
    """Verifica se o provider LLM está pronto para uso."""
    from jarvis.config import LLM_PROVIDER, GROQ_API_KEY, GROQ_MODEL, ANTHROPIC_API_KEY, OLLAMA_HOST, OLLAMA_MODEL

    if LLM_PROVIDER == "groq":
        if not GROQ_API_KEY:
            console.print(
                "[red]❌ GROQ_API_KEY não definida.[/red]\n\n"
                "[bold]Para usar o Groq (gratuito):[/bold]\n"
                "  1. Crie conta em: [cyan]https://console.groq.com[/cyan]\n"
                "  2. Gere uma API key (gratuito, sem cartão)\n"
                "  3. Adicione ao [cyan].env[/cyan]: [cyan]GROQ_API_KEY=sua_chave_aqui[/cyan]"
            )
            return False
        # Testa conectividade com Groq
        try:
            from openai import OpenAI
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)
            client.models.list()
        except Exception as e:
            console.print(f"[red]❌ Erro ao conectar com Groq: {e}[/red]")
            return False
        console.print(f"[green]✓ Groq conectado[/green] → modelo: [cyan]{GROQ_MODEL}[/cyan]")
        return True

    elif LLM_PROVIDER == "ollama":
        try:
            import urllib.request
            urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3).read()
        except Exception:
            console.print(
                f"[red]❌ Ollama não está rodando em {OLLAMA_HOST}[/red]\n\n"
                "[bold]Para instalar e iniciar o Ollama:[/bold]\n"
                "  1. Baixe em: [cyan]https://ollama.com[/cyan]\n"
                f"  2. Baixe o modelo: [cyan]ollama pull {OLLAMA_MODEL}[/cyan]"
            )
            return False
        console.print(f"[green]✓ Ollama conectado[/green] → modelo: [cyan]{OLLAMA_MODEL}[/cyan]")
        return True

    elif LLM_PROVIDER == "anthropic":
        if not ANTHROPIC_API_KEY:
            console.print(
                "[red]❌ ANTHROPIC_API_KEY não definida.[/red]\n"
                "Troque para [cyan]LLM_PROVIDER=groq[/cyan] para usar sem custo."
            )
            return False
        console.print("[green]✓ Anthropic configurado[/green]")
        return True

    else:
        console.print(f"[red]❌ LLM_PROVIDER inválido: '{LLM_PROVIDER}'[/red]")
        return False


def run_chat(args) -> None:
    from jarvis.modes.chat import ChatMode
    mode = ChatMode(use_context=not args.no_context)
    mode.run()


def run_realtime(args) -> None:
    from jarvis.modes.realtime import RealtimeMode

    mode = RealtimeMode(
        vision_enabled=not args.no_vision,
        voice_enabled=not args.no_voice,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _sigint_handler(sig, frame):
        console.print("\n[yellow]Encerrando Jarvis...[/yellow]")
        mode.trigger_kill_switch()

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        loop.run_until_complete(mode.run())
    except KeyboardInterrupt:
        mode.trigger_kill_switch()
    finally:
        loop.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Jarvis — Assistente de IA Local com Voz + Visão",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python -m jarvis                              # Modo chat (padrão)
  python -m jarvis --mode realtime             # Modo realtime (voz + visão)
  python -m jarvis --mode realtime --no-vision # Só voz
  python -m jarvis --mode realtime --no-voice  # Só texto + visão
        """,
    )
    parser.add_argument("--mode", choices=["chat", "realtime"], default="chat")
    parser.add_argument("--no-vision", action="store_true", help="Desativa tela/OCR")
    parser.add_argument("--no-voice", action="store_true", help="Desativa mic/TTS")
    parser.add_argument("--no-context", action="store_true", help="Sem contexto do sistema")
    parser.add_argument("--version", action="version", version="Jarvis 0.1.0")

    args = parser.parse_args()

    if not _check_provider():
        sys.exit(1)

    console.print(f"[dim]Iniciando em modo [bold]{args.mode}[/bold]...[/dim]\n")

    if args.mode == "chat":
        run_chat(args)
    else:
        run_realtime(args)


if __name__ == "__main__":
    main()
