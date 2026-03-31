---
name: jarvis-learning
description: Use this skill when the user asks to edit, fix, improve, debug, or understand anything related to Jarvis learning, memory, user profile, activity detection, session summary, insights, persistent memory, "aprendizado do Jarvis", "memória", "perfil do usuário", "o que o Jarvis aprende", "sessão", "insights", "activity", "ActivitySensor", "UserProfile", or session logs (JSONL).
tools: Read, Edit, Bash, Grep
---

# Jarvis — Sistema de Aprendizado (Memória + Perfil + Atividade)

Este skill fornece compreensão profunda de como o Jarvis aprende sobre o usuário, persiste informações entre sessões e detecta o que o usuário está fazendo. Leia este documento inteiro antes de editar qualquer coisa relacionada ao aprendizado.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---------|-----------------|
| `jarvis/core/memory.py` | Histórico de conversação em memória + log JSONL de eventos |
| `jarvis/core/profile.py` | Perfil persistente do usuário (entre sessões) |
| `jarvis/sensors/activity.py` | Inferência de atividade em tempo real (CODING, GAMING, etc.) |
| `jarvis/modes/realtime.py` | Orquestra aprendizado: coleta atividade, gera resumo de sessão, processa "lembra que" |
| `jarvis/config.py` | Caminhos e parâmetros do sistema de aprendizado |

---

## Visão geral: duas camadas de memória

O Jarvis tem dois sistemas de memória com propósitos distintos:

```
┌─────────────────────────────────────────────────────┐
│  MEMÓRIA DE CURTO PRAZO (Memory)                    │
│  Em RAM — dura apenas a sessão atual               │
│  Contém: histórico de mensagens user/assistant     │
│  Uso: enviado à API para manter contexto           │
│  Arquivo: logs/session_<timestamp>.jsonl (eventos) │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  MEMÓRIA DE LONGO PRAZO (UserProfile)               │
│  Em disco — persiste entre sessões                 │
│  Contém: insights, apps aprendidos, stats          │
│  Uso: injetado no contexto do LLM como "perfil"   │
│  Arquivo: logs/user_profile.json                  │
└─────────────────────────────────────────────────────┘
```

---

## Classe `Memory` — memória de curto prazo

### Estrutura do histórico

```python
self._conversation: List[Dict] = [
    {"role": "user",      "content": "Qual é a capital da França?", "ts": 1234567890.1},
    {"role": "assistant", "content": "Paris.",                      "ts": 1234567890.5},
    ...
]
```

O campo `"ts"` (timestamp) existe apenas internamente. Ao enviar para a API via `get_messages_for_api()`, o campo `"ts"` é removido — a API Anthropic/Groq só aceita `{"role": ..., "content": ...}`.

### Janela deslizante de contexto

O histórico é **truncado automaticamente** para evitar estourar o limite de tokens do LLM:

```python
max_history = 40  # 40 pares = 80 mensagens (user + assistant)
if len(self._conversation) > max_history * 2:
    self._conversation = self._conversation[-(max_history * 2):]
```

Isso mantém sempre as últimas 40 trocas completas. Conversas mais antigas são **descartadas da memória de curto prazo** — mas podem estar nos insights do perfil se a sessão tiver sido resumida.

### Log JSONL — estrutura de eventos

Cada evento do sistema é gravado em `logs/session_<unix_timestamp>.jsonl`:

```json
{"ts": 1740000000.123, "type": "transcription", "data": {"text": "como vai?"}}
{"ts": 1740000001.456, "type": "response", "data": {"text": "Bem! E você?"}}
{"ts": 1740000002.789, "type": "tool", "data": {"name": "search_web", "query": "preço bitcoin"}}
{"ts": 1740000003.012, "type": "profile_learn", "data": {"insight": "prefere Python"}}
{"ts": 1740000004.345, "type": "proactive", "data": {"event": "error_detected", "app": "VS Code"}}
```

Tipos de eventos registrados:
- `transcription` — fala do usuário transcrita pelo Whisper
- `response` — resposta do agente
- `tool` — ferramenta executada (open_url, copy_to_clipboard, search_web)
- `profile_learn` — insight adicionado ao perfil
- `proactive` — evento proativo disparado pelo Observer

---

## Classe `UserProfile` — memória de longo prazo

### Estrutura do JSON persistido

```json
{
  "version": 1,
  "session_count": 12,
  "last_seen": "2026-03-31T21:00:00",
  "learned_apps": {
    "Minecraft": "GAMING",
    "Figma": "WRITING",
    "MoneyMoney": "UNKNOWN"
  },
  "insights": [
    "Prefere Python para desenvolvimento backend",
    "Joga Valorant à noite, geralmente entre 20h e 23h",
    "Está desenvolvendo um assistente de IA pessoal chamado Jarvis",
    "Usa VS Code como editor principal"
  ],
  "activity_stats": {
    "CODING": 34,
    "GAMING": 12,
    "BROWSING": 5,
    "WATCHING": 8
  }
}
```

### Como insights são injetados no LLM

Em `get_context_for_llm()`, os últimos 5 insights são formatados como contexto compacto:

```python
"O que sei sobre você: Prefere Python; Joga Valorant à noite; Está desenvolvendo Jarvis | Atividade mais comum: CODING"
```

Esse texto é inserido no `context["profile"]` e o agente o recebe como parte do system prompt — assim o Jarvis sabe quem é o usuário sem precisar perguntar a cada sessão.

### Deduplicação de insights

```python
key = item[:40].lower()
already_exists = any(key in existing.lower() for existing in self.insights)
if not already_exists:
    self.insights.append(item)
```

Compara os primeiros 40 caracteres (lowercase) do novo insight contra todos os existentes. Não é exata — mas evita duplicatas óbvias como "Prefere Python" e "Prefere Python para backend".

### Limite de 100 insights

Quando supera 100, descarta os mais antigos (FIFO):

```python
if len(self.insights) > _MAX_INSIGHTS:
    self.insights = self.insights[-_MAX_INSIGHTS:]
```

Os insights mais novos (mais recentes) são preservados. Os mais velhos, presumivelmente obsoletos, são descartados.

---

## Classe `ActivitySensor` — detecção de atividade em tempo real

### Hierarquia de prioridades

A detecção segue 4 níveis em ordem de prioridade:

```
1. learned_apps do UserProfile  (confiança: 1.0) ← máxima prioridade
2. Nome do app vs. dicionários  (confiança: 0.8–0.95)
3. Título da janela             (confiança: 0.7–0.9)
4. Texto OCR da tela            (confiança: 0.5) ← último recurso
```

**Por que learned_apps tem prioridade máxima?** O usuário pode ensinar explicitamente ao Jarvis o que um app significa. Ex: "MoneyMoney" não está em nenhum dicionário — o usuário pode dizer "isso é WRITING" e essa associação tem prioridade sobre qualquer heurística.

### Como a detecção funciona nos browsers

Browsers são especiais — o app sempre é "Chrome" ou "Edge", mas o que importa é o **título da janela**:

```python
_BROWSER_TITLE_PATTERNS = {
    "youtube": ActivityType.WATCHING,
    "github":  ActivityType.CODING,
    "notion":  ActivityType.WRITING,
    "meet.google": ActivityType.MEETING,
    # ... ~35 padrões
}
```

Se nenhum padrão casar no título → `BROWSING` genérico com confiança 0.7.

### Detecção via OCR (último recurso)

Se nem o app nem o título revelarem a atividade, o Jarvis olha para o **texto na tela**:

```python
_OCR_CODE_PATTERNS = re.compile(
    r"\b(def |class |import |from |const |SELECT |TypeError |git commit |...)\b"
)
```

Se qualquer um desses tokens aparecer no OCR → `CODING` com confiança 0.5. **Nunca detecta GAMING, WRITING ou WATCHING via OCR** — seria muito impreciso.

---

## Como o aprendizado acontece durante a sessão

### 1. Aprendizado explícito por comando de voz

O usuário fala: *"Lembra que eu prefiro TypeScript para frontend"*

```python
# Em RealtimeMode._check_learn_command():
LEARN_TRIGGERS = ["lembra que ", "anota que ", "guarda que ", "salva que ", ...]

if text_lower.startswith(trigger):
    content = text[len(trigger):].strip()  # "eu prefiro TypeScript para frontend"
    self.profile.add_insights([content])
    self.profile.save()  # persiste imediatamente
    self.memory.log_event("profile_learn", {"insight": content})
    await self.tts.speak_async("Anotado! Vou lembrar disso.")
    return True  # não repassa ao agente
```

O insight é salvo **imediatamente** — sem aguardar o fim da sessão.

### 2. Aprendizado automático no fim da sessão

Ao encerrar (Ctrl+C), `_summarize_session()` é chamado em background thread:

```
Histórico recente (últimas 40 mensagens)
    │
    ▼
Prompt de extração enviado ao LLM:
    "Extraia 3 a 5 fatos CONCRETOS e ÚTEIS sobre o usuário..."
    │
    ▼
LLM retorna bullets:
    "- Está desenvolvendo assistente de voz em Python"
    "- Usa Groq com llama-3.3-70b como provider padrão"
    │
    ▼
_parse_bullets() extrai os bullets
    │
    ▼
profile.add_insights(bullets)
profile.increment_session()
profile.save()
```

**Provider usado para o resumo:**
- Anthropic: usa `_chat_anthropic()` diretamente
- Groq: usa `llama-3.1-8b-instant` (mais rápido e barato — resumo não precisa de 70B)
- Ollama: usa o modelo configurado em `OLLAMA_MODEL`

**Quando o resumo é pulado?**
```python
SESSION_SUMMARY_MIN_EXCHANGES = 5  # mínimo de 5 trocas
if exchange_count < SESSION_SUMMARY_MIN_EXCHANGES:
    print("Sessão curta — resumo ignorado.")
```

Sessões muito curtas (menos de 5 perguntas/respostas) não geram insights úteis.

### 3. Atualização de estatísticas de atividade

A cada resposta, `_respond()` detecta a atividade atual e incrementa o contador:

```python
activity = self.activity_sensor.detect(
    app_name=context.get("app_name"),
    window_title=context.get("window_title"),
    screen_text=context.get("screen_text"),
    learned_apps=self.profile.learned_apps,  # ← usa mapeamentos aprendidos
)
self.profile.update_activity(activity.type.value)
# activity_stats["CODING"] += 1
```

Esses contadores não são salvos em tempo real — apenas no fim da sessão via `profile.save()`.

---

## O ciclo completo de aprendizado ao longo do tempo

```
Sessão 1:
  Usuário pergunta sobre Python, VS Code aberto
  → activity_stats: {CODING: 5}
  → Resumo: "Usa Python, VS Code"
  → profile.json salvo

Sessão 2:
  Usuário: "Lembra que estou desenvolvendo o Jarvis"
  → insight imediato: "estou desenvolvendo o Jarvis"
  → Jogou Valorant, detectado por gaming_apps
  → Resumo: "Desenvolve Jarvis em Python, joga Valorant"
  → profile.json: 2 sessões, activity_stats: {CODING: 8, GAMING: 3}

Sessão 3:
  Jarvis inicia com: "O que sei sobre você: estou desenvolvendo o Jarvis; Usa Python, VS Code; Desenvolve Jarvis em Python"
  → Contexto personalizado desde o primeiro prompt
```

---

## Guia de edição — onde mexer para cada tipo de mudança

### Quero adicionar novos triggers de aprendizado explícito
→ Editar `LEARN_TRIGGERS` em `realtime.py: _check_learn_command()`
→ Adicionar strings como `"aprende que "`, `"nota que "`, etc.

### Quero que o resumo de sessão capture mais informações
→ Editar `summary_prompt` em `realtime.py: _summarize_session()`
→ Adicionar novos pontos de foco na seção "Foque em:"

### Quero aumentar o limite de insights armazenados
→ Alterar `_MAX_INSIGHTS = 100` em `profile.py`
→ Cuidado: muitos insights podem inflar o contexto do LLM

### Quero adicionar uma nova ActivityType (ex: STUDYING)
→ Adicionar `STUDYING = "STUDYING"` ao enum `ActivityType` em `activity.py`
→ Adicionar apps relevantes (ex: `"anki"`, `"quizlet"`) nos dicionários adequados
→ Atualizar `_BROWSER_TITLE_PATTERNS` com sites como `"coursera"`, `"udemy"`
→ O Observer pode precisar de atualização se quiser reagir à nova atividade

### Quero que o Jarvis não aprenda automaticamente (só explícito)
→ Remover ou comentar a chamada `self._summarize_session()` em `_shutdown()`

### Quero ver o perfil atual do usuário
→ Ler `logs/user_profile.json` diretamente
→ Ou: `python -c "from jarvis.core.profile import UserProfile; p=UserProfile.load(); print(p.profile_summary); print(p.insights)"`

### Quero resetar o perfil do usuário
→ Deletar `logs/user_profile.json`
→ Na próxima sessão, Jarvis começa com perfil vazio

---

## Erros comuns e diagnóstico

| Sintoma | Causa provável | Onde investigar |
|---------|---------------|-----------------|
| Jarvis não lembra nada entre sessões | `profile.json` não está sendo salvo | Verificar permissões em `logs/`, ver erros de `[Profile] Aviso: erro ao salvar` |
| Perfil acumula insights redundantes | Deduplicação por prefixo de 40 chars falhou | `profile.py: add_insights()` — os insights são muito diferentes nos primeiros 40 chars |
| Resumo de sessão não é gerado | Menos de 5 trocas ou API falhou | `realtime.py: _summarize_session()` — ver log `[Profile] Sessão curta` ou erro de API |
| ActivitySensor sempre retorna UNKNOWN | App não reconhecido e sem learned_apps | Ensinar: "Jarvis, lembra que [app] é CODING" — será salvo em `learned_apps` |
| `_check_learn_command` não detecta fala | Trigger não bate com o que foi dito | Verificar `LEARN_TRIGGERS` em `realtime.py`; checar transcrição no log JSONL |
| JSONL não é criado | `LOG_DIR` não existe | `config.py: LOG_DIR.mkdir(exist_ok=True)` deve criar automaticamente; verificar permissões |
