---
name: jarvis-audio
description: Use this skill when the user asks to edit, fix, improve, debug, or understand anything related to Jarvis audio, hearing, microphone, voice input, STT, speech-to-text, VAD, wake word, utterance detection, "audição do Jarvis", "microfone", "reconhecimento de voz", "transcrição", or "whisper". Also use when changing audio config parameters like sample rate, VAD aggressiveness, silence threshold, or Whisper model size.
tools: Read, Edit, Bash, Grep
---

# Jarvis — Sistema de Audição (Audio + STT)

Este skill fornece compreensão profunda de como o Jarvis captura, filtra e transcreve a voz do usuário. Leia este documento inteiro antes de fazer qualquer edição no sistema de áudio.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---------|-----------------|
| `jarvis/sensors/audio.py` | Captura do microfone, VAD, detecção de utterances |
| `jarvis/processing/stt.py` | Transcrição de áudio → texto (Whisper) |
| `jarvis/config.py` | Todos os parâmetros configuráveis via `.env` |
| `jarvis/modes/realtime.py` | Orquestra audio → STT → Agent → TTS |

---

## Arquitetura do pipeline de áudio

```
Microfone (sounddevice)
    │
    │  int16, mono, 16kHz, 480 amostras/frame (30ms)
    ▼
_sd_callback()                    ← Thread de alta prioridade do sounddevice
    │  coloca frame em queue (maxsize=200)
    ▼
_chunk_queue (Queue)              ← Buffer entre threads
    │
    ▼
_vad_loop() / _process_chunk()   ← Thread dedicada "jarvis-vad" (daemon)
    │
    │  webrtcvad.Vad.is_speech()  → True / False por frame
    │
    ├── is_speech=False → pre_buffer (fila circular, PRE_SPEECH_MS)
    │
    └── is_speech=True  → speech_frames (acumulação)
              │
              │  silêncio por ≥ SILENCE_THRESHOLD_MS
              ▼
         _emit_utterance()
              │
              │  asyncio.run_coroutine_threadsafe()
              ▼
         _on_utterance(audio_bytes)    ← Coroutine no event loop asyncio
              │
              ▼
         STTProcessor.transcribe()    ← Executado em ThreadPoolExecutor
              │
              ▼
         Texto filtrado → Agent.chat()
```

---

## Classe `AudioSensor` — detalhes internos

### Por que há 3 threads?

O sounddevice opera em uma **thread de áudio de alta prioridade** (imposta pelo OS). Fazer qualquer coisa pesada nessa thread (VAD, I/O, logging) causa dropouts de áudio. Por isso:

- **Thread 1 (sounddevice)**: só coloca bytes na queue, sem processamento
- **Thread 2 (jarvis-vad)**: consome a queue, roda VAD, detecta utterances
- **Thread 3 (asyncio event loop)**: recebe a utterance via `run_coroutine_threadsafe`, roda STT no executor

### Pre-speech buffer

O VAD detecta fala *depois* que ela começa — os primeiros milissegundos podem ser perdidos. O `_pre_buffer` é uma **fila circular** de `PRE_SPEECH_MS / FRAME_DURATION_MS` frames que ficam sempre prontos. Quando fala é detectada, esses frames são **prepend**ados ao `speech_frames`, recuperando o início da fala.

```python
# Config padrão: 300ms de pre-buffer (10 frames de 30ms)
PRE_SPEECH_MS: int = 300
_pre_buffer_size: int = int(PRE_SPEECH_MS / FRAME_DURATION_MS)  # = 10
```

### Filtro de utterances curtas

Qualquer utterance com menos de `_min_speech_frames = 3` frames (< 90ms) é descartada silenciosamente em `_emit_utterance()`. Isso elimina cliques, batidas na mesa e ruídos impulsivos.

### Parâmetros VAD (webrtcvad)

| Parâmetro | Config | Efeito |
|-----------|--------|--------|
| `VAD_AGGRESSIVENESS` | 0–3 (padrão: 3) | 0 = máxima sensibilidade, 3 = máxima filtragem de ruído. Valor 3 é ideal para ambientes com ruído de fundo (ventilador, teclado). |
| `AUDIO_SAMPLE_RATE` | 16000 Hz | webrtcvad só aceita: 8000, 16000, 32000 ou 48000. 16k é o padrão para Whisper. |
| `FRAME_DURATION_MS` | 30ms | webrtcvad só aceita: 10, 20 ou 30ms. 30ms é o mais estável. |
| `SILENCE_THRESHOLD_MS` | 1000ms | Quantos ms de silêncio para considerar que o usuário terminou de falar. Reduzir → responde mais rápido mas corta frases. Aumentar → mais natural mas adiciona latência. |
| `FRAME_SIZE` | 480 amostras | Calculado automaticamente: `16000 * 30 / 1000 = 480`. Não alterar diretamente. |

---

## Classe `STTProcessor` — detalhes internos

### Lazy loading e thread safety

O modelo Whisper **não é carregado no `__init__`** — ele carrega na primeira chamada a `transcribe()`. Isso evita travar o startup por causa do download/descompressão do modelo (~244MB para `small`, ~769MB para `medium`). Um `threading.Lock` garante que dois threads nunca tentem carregar o modelo ao mesmo tempo.

```python
# Carregamento com compute_type="int8" → quantização para CPU
# É 2-4x mais rápido que float32 na CPU, sem perda perceptível de qualidade
self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
```

### Conversão de formato

O áudio chega como `bytes` de inteiros de 16 bits. O Whisper espera `float32` normalizado entre -1.0 e +1.0:

```python
audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
```

`32768.0 = 2^15` — máximo valor de int16. Essa divisão normaliza para [-1.0, 1.0].

### Parâmetros de transcrição

```python
self._model.transcribe(
    audio_np,
    beam_size=5,                        # Busca beam: mais lento mas mais preciso que greedy
    language=self._language,            # "pt" força português; None = auto-detect
    condition_on_previous_text=False,   # IMPORTANTE: evita "cascata de alucinações"
    vad_filter=True,                    # Filtra silêncio residual internamente
    vad_parameters=dict(
        min_silence_duration_ms=300,
        speech_pad_ms=100,
    ),
)
```

**Por que `condition_on_previous_text=False`?** Quando True, o Whisper usa a transcrição anterior como contexto para a próxima. Isso pode fazer com que um erro de transcrição "contamine" as próximas utterances em loop. Com False, cada utterance é tratada de forma independente.

### Sistema de 3 filtros anti-alucinação

O Whisper tem tendência a "alucinar" — gerar texto coerente mesmo em silêncio ou ruído. Os 3 filtros combatem isso:

#### Filtro 1: `no_speech_prob` (probabilidade de não-fala)

Cada segmento do Whisper retorna uma probabilidade de que aquele trecho seja silêncio/ruído. Se a média superar `STT_NO_SPEECH_THRESHOLD` (padrão: 0.6 = 60%), a transcrição é descartada.

```
avg_no_speech = sum(s.no_speech_prob for s in segments) / len(segments)
if avg_no_speech > 0.6: return ""  # descarta
```

#### Filtro 2: `avg_logprob` (confiança geral)

`avg_logprob` é a log-probabilidade média dos tokens gerados — quão "certo" o modelo está. Valores muito negativos (ex: -2.0) indicam baixa confiança. O threshold padrão é -1.0.

```
avg_logprob = sum(s.avg_logprob for s in segments) / len(segments)
if avg_logprob < -1.0: return ""  # descarta
```

#### Filtro 3: `_is_repetitive()` — detecção de loop

O Whisper às vezes entra em loop repetindo frases ("Vai com a mão. Vai com a mão. Vai com a mão."). Dois critérios detectam isso:

1. **Razão de palavras únicas**: se menos de 45% das palavras são únicas → repetitivo
2. **Razão de trigramas únicos**: se menos de 50% dos trigramas são únicos → repetitivo

```python
unique_ratio = len(set(words)) / len(words)
if unique_ratio < 0.45: return True  # repetitivo

trigrams = [tuple(words[i:i+3]) for i in range(len(words) - 2)]
unique_trigram_ratio = len(set(trigrams)) / len(trigrams)
if unique_trigram_ratio < 0.5: return True
```

---

## Como o áudio se conecta ao resto do sistema

No `RealtimeMode._on_utterance()`:

1. Checa `self._processing` — se o agente já está respondendo, **ignora** a nova utterance (não enfileira)
2. Chama `self.tts.stop()` — interrompe TTS imediatamente se o usuário falou
3. Roda `self.stt.transcribe()` no **ThreadPoolExecutor** (não bloqueia o event loop)
4. Aplica filtro mínimo: texto com menos de 2 caracteres é descartado
5. Checa se é comando de anotação (`"ativar modo anotação"`) — trata separadamente
6. Checa se é comando de aprendizado (`"lembra que ..."`) — trata separadamente
7. Se nada especial: chama `await self._respond(text)`

---

## Guia de edição — onde mexer para cada tipo de mudança

### Quero que o Jarvis responda mais rápido após o usuário terminar de falar
→ Reduzir `SILENCE_THRESHOLD_MS` em `config.py` (ex: 800ms)
→ Risco: pode cortar frases longas ou pausas naturais

### Quero que o VAD filtre menos ruído (está cortando voz)
→ Reduzir `VAD_AGGRESSIVENESS` de 3 para 1 ou 2 em `config.py`
→ Risco: pode capturar mais ruído de fundo

### Quero melhorar a qualidade da transcrição (aceitar mais erros de alucinação)
→ Aumentar `STT_NO_SPEECH_THRESHOLD` (ex: 0.7 ou 0.8) em `config.py`
→ Risco: mais transcrições espúrias em silêncio

### Quero mudar o modelo Whisper (velocidade vs. qualidade)
→ Alterar `WHISPER_MODEL` no `.env`:
- `tiny` (39MB): ~1-2s, muito rápido, menos preciso
- `base` (74MB): ~2-3s, bom custo-benefício
- `small` (244MB): ~3-5s, recomendado para uso geral
- `medium` (769MB): ~5-10s, melhor qualidade, mais lento
- `large-v3` (1.5GB): máxima qualidade, CPU pode ser impraticável

### Quero adicionar wake word ("Jarvis, ...")
→ Editar `modes/realtime.py`, método `_on_utterance()`
→ Filtrar o texto transcrito antes de chamar `_respond()`
→ Exemplo: `if not text.lower().startswith("jarvis"): return`

### Quero que o Jarvis ouça mesmo enquanto processa
→ Remover `if self._processing: return` em `_on_utterance()`
→ Cuidado: precisará de fila de utterances para não perder falas

---

## Erros comuns e diagnóstico

| Sintoma | Causa provável | Onde investigar |
|---------|---------------|-----------------|
| Jarvis não ouve nada | sounddevice não instalado ou microfone errado | `audio.py: start()` — ver device list |
| Transcreve ruído/silêncio | `STT_NO_SPEECH_THRESHOLD` muito alto ou VAD muito permissivo | `config.py`, `stt.py: transcribe()` |
| Corta o início das palavras | `PRE_SPEECH_MS` muito pequeno | `config.py` |
| Corta frases no meio | `SILENCE_THRESHOLD_MS` muito pequeno | `config.py` |
| "[STT] Descartado — texto repetitivo" | Loop de alucinação do Whisper | Normal, filtro funcionou. Se excessivo: aumentar `STT_REPETITION_THRESHOLD` |
| Queue cheia (frame drops) | VAD loop muito lento | Investigar `_process_chunk()`, considerar reduzir `VAD_AGGRESSIVENESS` |
| Alto uso de CPU | Modelo Whisper muito grande para a máquina | Usar `small` em vez de `medium` |
