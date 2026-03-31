---
name: jarvis-vision
description: Use this skill when the user asks to edit, fix, improve, debug, or understand anything related to Jarvis vision, screen capture, OCR, screenshot, screen reading, "visão do Jarvis", "captura de tela", "OCR", "Tesseract", "o que o Jarvis vê", "visão multimodal", or the VisionSensor. Also use when changing vision config like FPS, JPEG quality, max width, OCR languages, or Tesseract path.
tools: Read, Edit, Bash, Grep
---

# Jarvis — Sistema de Visão (VisionSensor + OCR + Multimodal)

Este skill fornece compreensão profunda de como o Jarvis captura a tela, extrai texto via OCR e envia screenshots para o LLM. Leia este documento inteiro antes de editar qualquer coisa relacionada à visão.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---------|-----------------|
| `jarvis/sensors/vision.py` | Captura de tela, OCR, cache de frames, base64 |
| `jarvis/config.py` | Todos os parâmetros configuráveis via `.env` |
| `jarvis/modes/realtime.py` | Integra visão ao pipeline de resposta |
| `jarvis/observer/observer.py` | Usa `get_last_ocr()` para detectar erros na tela |

---

## Arquitetura do pipeline de visão

```
Thread "jarvis-vision" (daemon, background)
    │
    │  a cada 1/SCREEN_CAPTURE_FPS segundos (padrão: 1s)
    ▼
_capture_loop()
    │
    ▼
_take_screenshot()
    │  mss.mss().grab(monitor[1])  ← monitor principal (índice 1)
    │  PIL Image.frombytes("RGB", ...)
    │  img.resize(orig_w//2, orig_h//2)   ← metade da resolução para OCR rápido
    │
    ▼  (guarda em self._last_screenshot com lock)
    │
    ▼ (se OCR ativo)
_run_ocr(screenshot)
    │  image.convert("L")          ← converte para escala de cinza
    │  pytesseract.image_to_string(gray, lang="por+eng", config="--psm 6")
    │
    ▼  (guarda em self._last_ocr com lock)


Thread do event loop asyncio (quando o agente precisa responder)
    │
    ├── get_frame_age() > VISION_FRAME_MAX_AGE_S (2.0s)?
    │       └── Sim → captura novo frame no ThreadPoolExecutor
    │
    ├── get_screen_context_text()  → OCR ou metadado de fallback
    │
    └── Se provider == "anthropic":
            get_screenshot_base64()  → JPEG comprimido → base64
```

---

## Classe `VisionSensor` — detalhes internos

### Por que usar thread separada?

A captura de tela com `mss` e o OCR com Tesseract são operações **bloqueantes** (CPU-bound e I/O). Rodá-las no event loop asyncio travaria o Jarvis inteiro. A thread daemon captura em background, mantendo o cache sempre fresco, enquanto o event loop consulta o cache sem bloquear.

### Thread safety — lock em tudo

Todo acesso a `_last_ocr`, `_last_screenshot`, `_last_frame_time`, etc. é protegido por `threading.Lock`. Isso previne race conditions entre a thread de captura (escrita) e o event loop asyncio (leitura).

```python
# Escrita (thread de captura)
with self._lock:
    self._last_screenshot = screenshot
    self._last_frame_time = now

# Leitura (event loop)
with self._lock:
    screenshot = self._last_screenshot
```

### Por que reduzir resolução pela metade?

```python
img = img.resize((orig_w // 2, orig_h // 2))
```

O OCR não precisa de resolução 4K. Reduzir pela metade:
- Reduz o tempo de OCR em ~75% (área 4x menor)
- Reduz consumo de memória
- Qualidade de reconhecimento de texto mantida (Tesseract lida bem com imagens menores)

Em um monitor 1920x1080, o frame para OCR fica em 960x540.

### O frame para base64 (visão multimodal) passa por pipeline diferente

```python
def get_screenshot_base64(self, quality=None, max_width=None) -> Optional[str]:
    # Usa self._last_screenshot (já em escala 1/2)
    # Aplica redução adicional se largura > VISION_MAX_WIDTH (1280px)
    if w > mw:
        ratio = mw / w
        img = img.resize((int(w * ratio), int(h * ratio)))

    # Comprime para JPEG com qualidade configurável
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=VISION_JPEG_QUALITY, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
```

**Por que JPEG e não PNG?** PNG é lossless mas muito maior (~3x). Para visão contextual, perda leve de qualidade (JPEG quality=50) é imperceptível ao LLM e reduz drasticamente o custo de tokens de imagem na API Anthropic.

---

## Parâmetros configuráveis em `config.py` / `.env`

| Variável | Padrão | Efeito |
|----------|--------|--------|
| `SCREEN_CAPTURE_FPS` | `1.0` | Frames por segundo. 1 FPS = captura a cada 1s. Aumentar consome mais CPU (OCR é caro). Para uso em jogos rápidos, 2 FPS pode ser útil. |
| `OCR_LANGUAGES` | `"por+eng"` | Idiomas do Tesseract. `por+eng` reconhece pt-BR e inglês. Para adicionar espanhol: `"por+eng+spa"`. Requer instalação dos pacotes de idioma do Tesseract. |
| `TESSERACT_CMD` | `C:\Program Files\...` | Caminho para o executável `tesseract.exe`. Configurar via `TESSERACT_PATH` no `.env`. |
| `TESSDATA_PREFIX` | (vazio) | Pasta com arquivos `.traineddata`. Necessário se os modelos de idioma estiverem em local customizado. |
| `VISION_FRAME_MAX_AGE_S` | `2.0` | Quantos segundos o frame pode ter antes de forçar nova captura no momento da resposta. Valor baixo (0.5s) = sempre frame fresco, mais CPU. |
| `VISION_DEBUG` | `false` | Ativa logs de timing: resolução, tempo de captura, tamanho do JPEG. Útil para diagnóstico de performance. |
| `VISION_JPEG_QUALITY` | `50` | Qualidade do JPEG enviado ao LLM (1-95). 50 é boa relação qualidade/tamanho. Aumentar para screenshots com texto pequeno ou ícones detalhados. |
| `VISION_MAX_WIDTH` | `1280` | Largura máxima do screenshot antes da codificação base64. Reduz tokens de imagem na API. |

---

## Dois modos de visão: OCR vs. Multimodal

O Jarvis tem dois caminhos para fornecer contexto visual ao LLM:

### Modo 1: OCR (Tesseract) — para todos os providers

```
Screenshot → escala de cinza → Tesseract → texto → contexto["screen_text"]
```

Vantagens:
- Funciona com qualquer LLM (Groq, Ollama, Anthropic)
- Texto extraído é compacto (poucos tokens)
- Ótimo para terminal, código, documentos

Limitações:
- Não entende layout visual, ícones, imagens
- Falha em texto com fontes muito estilizadas ou antialiasing agressivo
- Lento em telas complexas

### Modo 2: Screenshot multimodal — apenas provider Anthropic

```
Screenshot → JPEG comprimido → base64 → contexto["screenshot_b64"]
→ Anthropic API recebe imagem real como bloco de conteúdo
```

```python
# Em realtime.py, dentro de _respond():
if self.agent.provider == "anthropic":
    b64 = self.vision_sensor.get_screenshot_base64()
    if b64:
        context["screenshot_b64"] = b64
        context["vision_mode"] = "screenshot multimodal anexado"
```

O agente em `core/agent.py` detecta `screenshot_b64` no contexto e o inclui na mensagem como bloco de imagem JPEG (`image/jpeg`).

Vantagens:
- Jarvis vê a tela exatamente como ela está (ícones, cores, layout)
- Entende gráficos, imagens, UI
- Claude Vision é muito superior ao OCR para telas complexas

Limitações:
- Apenas com `LLM_PROVIDER=anthropic`
- Consome tokens de imagem (mais caro)
- Não funciona com Groq/Ollama

---

## Fluxo do `capture_if_stale()` e frame freshness

O Jarvis mantém um cache do último frame. Quando o agente vai responder, ele verifica a idade do frame:

```python
# Em realtime.py _respond():
frame_age = self.vision_sensor.get_frame_age()
if frame_age > cfg.VISION_FRAME_MAX_AGE_S:
    # Frame desatualizado: captura novo AGORA
    await loop.run_in_executor(self._executor, self.vision_sensor.capture)
```

Isso garante que, no momento da resposta, o Jarvis está olhando para a tela atual — não para uma captura de 5 segundos atrás.

---

## Como o Observer usa a visão

O `Observer` consome o OCR para detectar eventos proativos:

```python
# Em observer_loop() do RealtimeMode:
state = {
    "screen_text": self.vision_sensor.get_last_ocr(),  # ← OCR em cache
    ...
}
events = self.observer.check(state)
```

O Observer então aplica regex (`ERROR_PATTERNS`) no texto OCR para detectar erros, tracebacks, etc. **Ele não usa o screenshot base64** — só texto OCR, porque é mais rápido e não precisa de análise visual para detectar padrões de texto como "TypeError" ou "traceback".

---

## Guia de edição — onde mexer para cada tipo de mudança

### Quero aumentar a taxa de captura (mais FPS)
→ Aumentar `SCREEN_CAPTURE_FPS` no `.env` (ex: `2.0`)
→ Cuidado: Tesseract é pesado; 2 FPS pode consumir 20-30% de um core

### Quero desativar OCR mas manter screenshot para Claude Vision
→ `_ocr_enabled = False` em `VisionSensor.__init__()`
→ Ou remover Tesseract do PATH (Jarvis detecta e desativa OCR automaticamente)
→ Visão multimodal (base64) continua funcionando

### Quero adicionar suporte a múltiplos monitores
→ Editar `_take_screenshot()` em `vision.py`
→ `monitors[1]` = monitor principal; `monitors[2]` = segundo monitor
→ Para todos os monitores: usar `monitors[0]` (mss combina tudo)

### Quero que o OCR funcione melhor em texto em inglês
→ Já configurado: `OCR_LANGUAGES = "por+eng"` inclui inglês
→ Se quiser priorizar inglês: trocar para `"eng+por"`

### Quero que o screenshot enviado ao Claude seja maior/mais detalhado
→ Aumentar `VISION_JPEG_QUALITY` (ex: 75 ou 85) no `.env`
→ Aumentar `VISION_MAX_WIDTH` (ex: 1920) no `.env`
→ Impacto: mais tokens de imagem na API, mais custo e latência

### Quero desativar a visão completamente
→ Iniciar Jarvis com `--no-vision`: `python -m jarvis --mode realtime --no-vision`
→ Ou: instanciar `RealtimeMode(vision_enabled=False)`

### Quero ver debug de performance da visão
→ Adicionar `VISION_DEBUG=true` no `.env`
→ Logs mostrarão: resolução, tempo de captura, tempo de OCR, tamanho do JPEG

---

## Erros comuns e diagnóstico

| Sintoma | Causa provável | Onde investigar |
|---------|---------------|-----------------|
| "Tesseract não encontrado — OCR desativado" | `TESSERACT_CMD` errado ou Tesseract não instalado | `config.py: TESSERACT_CMD`, instalar em https://github.com/UB-Mannheim/tesseract/wiki |
| OCR retorna texto com erros/lixo | Tela com fonte muito estilizada; resolução muito baixa | Aumentar `VISION_JPEG_QUALITY`, desativar redução de resolução em `_take_screenshot()` |
| "Nenhum monitor detectado pelo mss" | mss não consegue enumerr monitores (driver, Wayland) | Testar `mss` diretamente no terminal; verificar `monitors[1]` |
| Screenshot muito grande (muitos tokens) | `VISION_MAX_WIDTH` alto + `VISION_JPEG_QUALITY` alto | Reduzir uma ou ambas as configs no `.env` |
| Frame sempre "desatualizado" | Thread de visão crashou silenciosamente | Verificar logs de "Erro na captura" em `_capture_loop()` |
| `_last_screenshot` sempre None | `mss` instalado mas falhou no `grab()` | Ativar `VISION_DEBUG=true` e verificar exceção |
| Claude Vision não funciona | `LLM_PROVIDER != "anthropic"` | Multimodal só funciona com Anthropic; Groq/Ollama usam apenas OCR |
