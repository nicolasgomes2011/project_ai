---
name: jarvis-visualize
description: Use this skill when the user asks to "visualize Jarvis", "show Jarvis status", "mostre o estado do Jarvis", "como está o Jarvis", "status da IA", "dashboard do Jarvis", "visão geral do projeto", or wants a health check / overview of the Jarvis AI assistant project.
tools: Read, Glob, Grep, Bash
---

# Jarvis — Skill de Visualização do Sistema

Gera um painel de status completo do assistente de IA Jarvis para o usuário.

## Objetivo

Apresentar de forma clara e estruturada o estado atual do projeto Jarvis: configuração ativa, arquitetura, logs recentes e saúde geral do sistema.

---

## Workflow

### Fase 1 — Coletar dados em paralelo

Execute todas estas leituras **antes** de montar o output:

```bash
# Raiz do projeto
PROJECT_ROOT="C:/Users/gomes/OneDrive/Documentos/Projetos/project_ai"

# 1. Configuração ativa (.env se existir, senão config.py)
cat "$PROJECT_ROOT/.env" 2>/dev/null || echo "(sem .env)"

# 2. Sessões de log mais recentes (últimas 3)
ls -t "$PROJECT_ROOT/jarvis/session_*.jsonl" 2>/dev/null | head -3

# 3. Última sessão — últimas 20 linhas
ls -t "$PROJECT_ROOT/jarvis/session_*.jsonl" 2>/dev/null | head -1 | xargs tail -20 2>/dev/null

# 4. Perfil do usuário persistente (se existir)
cat "$PROJECT_ROOT/logs/user_profile.json" 2>/dev/null | head -30

# 5. Requirements instalados vs. esperados
pip show faster-whisper edge-tts webrtcvad-wheels sounddevice mss pytesseract 2>/dev/null | grep -E "^(Name|Version):"
```

Leia também:
- `jarvis/config.py` — para mostrar configuração com valores padrão
- `jarvis/observer/events.py` — para listar EventTypes disponíveis
- `jarvis/core/agent.py` — para listar as ferramentas disponíveis ao agente

### Fase 2 — Montar o painel

Apresente o resultado neste formato estruturado:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  JARVIS — PAINEL DE STATUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## LLM Provider
  Provider ativo : [groq | anthropic | ollama]
  Modelo         : [nome do modelo]
  API Key        : [presente / AUSENTE]

## Áudio / STT
  Modelo Whisper : [tiny | base | small | medium | large]
  Sample Rate    : [Hz]
  VAD Agressividade: [0-3]
  Silêncio UTT   : [ms]

## TTS
  Voz            : [nome da voz edge-tts]
  Taxa           : [+X%]
  Engine         : [edge-tts | pyttsx3 (fallback)]

## Visão
  FPS            : [fps]
  OCR Idiomas    : [por+eng | etc]
  Tesseract      : [caminho ou AUSENTE]

## Proatividade
  Cooldown       : [segundos]s entre eventos

## Sessões de Log
  Total de sessões : [N]
  Última sessão    : [timestamp] — [N linhas / eventos]
  Troca mais recente: [última fala do usuário se disponível]

## Arquitetura — Módulos
  [lista de módulos com  ✅ presente | ⚠️ arquivo vazio | ❌ ausente]
  - jarvis/__main__.py
  - jarvis/config.py
  - jarvis/core/agent.py
  - jarvis/core/memory.py
  - jarvis/sensors/audio.py
  - jarvis/sensors/vision.py
  - jarvis/sensors/system_ctx.py
  - jarvis/processing/stt.py
  - jarvis/processing/tts.py
  - jarvis/observer/events.py
  - jarvis/observer/observer.py
  - jarvis/observer/decision.py
  - jarvis/modes/chat.py
  - jarvis/modes/realtime.py

## Eventos do Observer (tipos registrados)
  [lista de EventType disponíveis com descrição curta]

## Ferramentas do Agente
  [lista de tools disponíveis no core/agent.py]

## Dependências
  [lista com nome + versão instalada ou "(não instalado)"]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STATUS GERAL: [SAUDÁVEL | ATENÇÃO | CRÍTICO]
  [breve diagnóstico: o que está faltando ou precisa atenção]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Critérios para STATUS GERAL

| Condição | Status |
|---|---|
| Tudo presente e API key configurada | SAUDÁVEL |
| API key ausente OU Tesseract ausente OU deps faltando | ATENÇÃO |
| Múltiplos módulos ausentes OU sem nenhuma API key | CRÍTICO |

---

## Regras de apresentação

- Não faça perguntas — execute e mostre o painel completo de uma vez.
- Se `.env` não existir, mostre os defaults do `config.py`.
- Para API keys: mostre apenas se **presente** ou **AUSENTE** — nunca o valor real.
- Se um arquivo de módulo não existir, marque `❌` — não tente criá-lo.
- Última sessão de log: mostre apenas o resumo (não despeje o JSONL inteiro).
- Use o formato de painel acima como template — adapte se dados não estiverem disponíveis.
