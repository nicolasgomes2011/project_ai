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
│   ├── agent.py         # Integração Claude API + tool use
│   └── memory.py        # Histórico de conversação + logs JSONL
├── sensors/
│   ├── audio.py         # Microfone → VAD (webrtcvad) → utterances
│   ├── vision.py        # Captura de tela (mss) → OCR (Tesseract)
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

### 1. Instalar Ollama (LLM local — gratuito e ilimitado)

```bash
# 1. Baixe e instale: https://ollama.com
# 2. Após instalar, baixe um modelo (escolha conforme sua RAM):
ollama pull llama3.2:3b    # ~2 GB RAM — mais rápido, ideal para voz
ollama pull llama3.1:8b    # ~5 GB RAM — melhor qualidade
ollama pull qwen2.5:7b     # ~5 GB RAM — excelente para português
```

O Ollama inicia automaticamente como serviço em `localhost:11434`.

### 2. Dependências Python

```bash
pip install -r requirements.txt
```

### 3. Variáveis de Ambiente

```bash
cp .env.example .env
# Edite .env se quiser mudar o modelo (padrão: llama3.2:3b)
```

> **Sem API key necessária** para o modo Ollama.

### 3. Tesseract OCR (para modo realtime com visão)

**Windows:**
- Baixe em: https://github.com/UB-Mannheim/tesseract/wiki
- Instale e anote o caminho (ex: `C:\Program Files\Tesseract-OCR\tesseract.exe`)
- Configure `TESSERACT_PATH` no `.env`
- Baixe pacotes de idioma: `por` (Português) e `eng` (Inglês)

**Linux:**
```bash
sudo apt install tesseract-ocr tesseract-ocr-por
```

### 4. Modelo STT (Whisper) — download automático

Na primeira execução do modo realtime, o modelo Whisper (`small` por padrão, ~244 MB) é baixado automaticamente.

Para usar um modelo menor (mais rápido):
```
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
python -m jarvis --mode realtime --no-vision   # Só voz (sem OCR)
python -m jarvis --mode realtime --no-voice    # Sem microfone/TTS
python -m jarvis --mode realtime --no-context  # Sem contexto do sistema
python -m jarvis --version
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
- Tela capturada a 1 FPS + OCR sob demanda
- Observer monitora: erros na tela, travamentos, sinais de confusão
- Respostas por voz (edge-tts ou pyttsx3)
- **Kill switch:** Ctrl+C

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
- Kill switch instantâneo: Ctrl+C

---

## Logs

Sessão gravada em `logs/session_<timestamp>.jsonl`:
```json
{"ts": 1234567890, "type": "chat", "data": {"user": "...", "response": "..."}}
{"ts": 1234567890, "type": "tool", "data": {"name": "open_url", "url": "..."}}
```
