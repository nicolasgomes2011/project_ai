# JARVIS — Assistente de IA com Voz + Visão em Tempo Real

> Assistente pessoal que ouve, vê e age — de forma proativa — enquanto você trabalha.

---

## Arquitetura

```
Loop: Sensores → Observer → Decision Engine → Agente (Claude) → TTS
         ↑                                         ↓
      Microfone / Tela / Sistema            Ferramentas (browser, clipboard...)
```

### Módulos
```
jarvis/
├── __main__.py          # Ponto de entrada: python -m jarvis
├── config.py            # Configuração central (lê do .env)
├── core/
│   ├── agent.py         # LLM agent (Anthropic/Groq/Ollama) + tool use + timing
│   └── memory.py        # Histórico de conversação + logs JSONL
├── sensors/
│   ├── audio.py         # Microfone → VAD (webrtcvad) → utterances
│   ├── vision.py        # Captura de tela (mss) → OCR (Tesseract, opcional)
│   │                    #   → screenshot base64 para Claude Vision
│   └── system_ctx.py    # Janela ativa, clipboard, app em foco
├── processing/
│   ├── stt.py           # Speech-to-Text (faster-whisper, local)
│   └── tts.py           # Text-to-Speech (edge-tts ou pyttsx3)
├── observer/
│   ├── events.py        # Dataclasses de eventos
│   ├── observer.py      # Detecta situações (erros, travamentos, confusão)
│   └── decision.py      # Decide: ignorar / sugerir / executar
└── modes/
    ├── chat.py          # Modo texto (terminal)
    └── realtime.py      # Modo realtime (voz + visão + proatividade)
```

---

## Setup

### 1. Dependências Python

```bash
pip install -r requirements.txt
```

### 2. Configurar o Provider LLM

Copie o arquivo de exemplo e edite:

```bash
cp .env.example .env
```

#### Opção A — Anthropic Claude (padrão, recomendado)

O provider padrão é Anthropic. Requer uma API key paga.

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
JARVIS_MODEL=claude-sonnet-4-6
```

Benefícios do Claude:
- **Visão multimodal**: enxerga o screenshot real da tela (sem OCR)
- Melhor compreensão de contexto e qualidade de resposta
- Suporte a português nativo

Obtenha sua chave em: https://console.anthropic.com

#### Opção B — Groq (gratuito, fallback)

Para usar sem custo, com Llama no Groq Cloud:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.1-8b-instant
```

Obtenha sua chave grátis em: https://console.groq.com
Sem cartão de crédito necessário.

#### Opção C — Ollama (local, offline)

Para rodar completamente offline:

```bash
# 1. Baixe e instale: https://ollama.com
# 2. Baixe um modelo
ollama pull llama3.2:3b    # ~2 GB RAM — mais rápido
ollama pull llama3.1:8b    # ~5 GB RAM — melhor qualidade
```

```env
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
```

### 3. Visão (captura de tela)

A visão funciona em dois modos:

#### Modo A: Claude Vision (sem Tesseract — recomendado com Anthropic)

Com `LLM_PROVIDER=anthropic`, o Jarvis captura a tela com `mss` e envia o screenshot JPEG
diretamente ao Claude como imagem multimodal. **Não requer Tesseract**.

O Claude consegue descrever o que está na tela e responder com base no conteúdo visual.

#### Modo B: OCR com Tesseract (texto extraído, todos os providers)

Se quiser extração de texto via OCR (útil para Groq/Ollama):

**Windows:**
- Baixe em: https://github.com/UB-Mannheim/tesseract/wiki
- Instale e configure no `.env`:
  ```env
  TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
  ```
- Baixe pacotes de idioma: `por` (Português) e `eng` (Inglês)

**Linux:**
```bash
sudo apt install tesseract-ocr tesseract-ocr-por
```

**Nota:** Se Tesseract não estiver instalado, com Anthropic a visão multimodal funciona normalmente. Com Groq/Ollama, a visão será desativada.

#### Configurações de visão (`.env`)

```env
VISION_FRAME_MAX_AGE_S=2.0    # Idade máxima do frame antes de capturar novo
VISION_JPEG_QUALITY=50        # Qualidade JPEG (1-95; menor = mais rápido/barato)
VISION_MAX_WIDTH=1280         # Largura máxima do screenshot
VISION_DEBUG=false            # true = logs de captura (resolução, timestamp, tamanho)
```

### 4. Modelo STT (Whisper) — download automático

Na primeira execução do modo realtime, o modelo Whisper (`small` por padrão, ~244 MB) é baixado automaticamente.

Para usar um modelo menor (mais rápido):
```env
WHISPER_MODEL=tiny   # 39 MB, menor precisão
WHISPER_MODEL=base   # 74 MB
WHISPER_MODEL=small  # 244 MB (padrão recomendado)
```

---

## Rodar

### Modo Chat (texto)
```bash
python -m jarvis
python -m jarvis --mode chat
```

### Modo Realtime (voz + visão)
```bash
python -m jarvis --mode realtime
```

### Opções
```bash
python -m jarvis --mode realtime --no-vision   # Só voz (sem captura de tela)
python -m jarvis --mode realtime --no-voice    # Sem microfone/TTS
python -m jarvis --mode realtime --no-context  # Sem contexto do sistema
python -m jarvis --version
```

---

## Como selecionar o provider / modelo

Edite o `.env` e altere:

```env
# Para Anthropic (padrão):
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
JARVIS_MODEL=claude-sonnet-4-6        # ou claude-haiku-4-5-20251001

# Para Groq (gratuito):
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.1-8b-instant      # ou llama-3.3-70b-versatile

# Para Ollama (local):
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2:3b
```

Reinicie o Jarvis após alterar o `.env`.

---

## Instrumentação de Performance

O sistema loga automaticamente os tempos de cada etapa do pipeline:

```
[Perf] STT: 340ms | 'você consegue ver minha tela'
[Perf] Visão: 45ms | frame_age=0.8s | ocr=False | b64=True
[Perf] Montagem prompt: 2ms | LLM (anthropic): 1850ms | Total chat: 1852ms
[Perf] Resposta total: 1920ms (LLM incluso: 1852ms)
```

Para ativar logs detalhados de visão (resolução, tamanho JPEG, timestamp):
```env
VISION_DEBUG=true
```

---

## Modos de Operação

### `chat`
- Modo texto no terminal
- Injeta contexto automático: app ativo, janela, clipboard
- Comandos: `/ajuda`, `/limpar`, `/contexto`, `/sair`

### `realtime`
- Captura contínua do microfone
- VAD detecta início/fim de fala automaticamente
- STT transcreve localmente (faster-whisper)
- Tela capturada a 1 FPS
  - Com Anthropic: screenshot JPEG enviado como imagem ao Claude
  - Com Groq/Ollama: texto OCR extraído por Tesseract (se disponível)
- Observer monitora: erros na tela, travamentos, sinais de confusão
- Respostas por voz (edge-tts ou pyttsx3)
- **Kill switch:** Ctrl+C (encerramento limpo)

---

## Proatividade

O Observer detecta situações e o Decision Engine decide agir:

| Situação | Ação |
|---|---|
| Erro na tela (IDE) + usuário parado | Sugere ajuda |
| Mesmo app por >3 min sem interação | Pergunta se está travado |
| Usuário diz "não sei", "me ajuda", etc. | Responde proativamente |

**Regras anti-spam:**
- Cooldown configurável entre eventos proativos (padrão: 120s)
- Nunca interrompe fala do usuário ou processamento em andamento
- Máximo 1 evento proativo por checagem

---

## Ferramentas disponíveis

O agente pode executar:
- `open_url` — abre URL no navegador
- `copy_to_clipboard` — copia texto
- `search_web` — busca no Google

---

## Privacidade e Segurança

- STT roda **localmente** (faster-whisper, sem enviar áudio para servidores)
- Nenhum áudio/vídeo bruto é gravado
- Logs estruturados (JSONL) em `/logs/` contêm apenas: transcrições, eventos e decisões
- TTS online (edge-tts) envia apenas o texto da resposta à Microsoft; use `JARVIS_TTS_EDGE=False` para modo 100% offline
- Com Anthropic: screenshots são enviados à API Anthropic para análise visual (igual ao Claude.ai)
- Kill switch instantâneo: Ctrl+C

---

## Logs

Sessão gravada em `logs/session_<timestamp>.jsonl`:
```json
{"ts": 1234567890, "type": "chat", "data": {"user": "...", "response": "...", "has_vision": true}}
{"ts": 1234567890, "type": "tool", "data": {"name": "open_url", "url": "..."}}
```

---

## Arquivos modificados (changelog)

| Arquivo | O que mudou |
|---|---|
| `jarvis/config.py` | Provider padrão alterado para `anthropic`; novas vars `VISION_FRAME_MAX_AGE_S`, `VISION_DEBUG`, `VISION_JPEG_QUALITY`, `VISION_MAX_WIDTH`; `ANTHROPIC_MODEL` como constante explícita |
| `jarvis/core/agent.py` | Provider Anthropic como padrão em `_init_client()`; suporte a visão multimodal em `_chat_anthropic()` (imagem JPEG em base64); timing de performance em `chat()`; bug fix de indentação em `_build_user_message()`; campo `vision_mode` no contexto |
| `jarvis/sensors/vision.py` | Logs de debug com timestamp/resolução/monitor/tamanho; novo método `get_screenshot_base64()` para Claude Vision; `get_screen_context_text()` com fallback quando OCR ausente; `get_frame_age()` e `capture_if_stale()` para frame freshness |
| `jarvis/modes/realtime.py` | `_tracked_utterance()` wrapper para rastrear tasks e evitar "Task was destroyed but pending"; `_pending_utterance_tasks` set + cancelamento no `_shutdown()`; instrumentação de performance (STT, visão, LLM); frame freshness check antes de responder; envio de `screenshot_b64` ao agente para Anthropic |
| `jarvis/__main__.py` | Verificação de Anthropic como provider primário com nome do modelo; mensagem de erro atualizada |
| `.env.example` | Provider padrão alterado para `anthropic`; novas variáveis de visão documentadas |
| `README.md` | Documentação completa de todos os providers, visão multimodal, instruções de `.env`, logs de performance |
