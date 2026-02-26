# TASK — Implementar sistema de Skills + Context Builder (realtime) no Jarvis (Python)

## Objetivo
Evoluir o projeto Jarvis (Python) para um modelo “assistente realtime” menos literal e mais funcional, implementando:
1) um **Context Builder** robusto (áudio + visão + estado do sistema), com **controle de ruído** (não jogar OCR cru no LLM);
2) um **Skill Router** (roteamento por intenção) com **janela de engajamento** (wake word → conversa contínua por N segundos);
3) um **framework de Skills** (plugins) em Python, com metadados, schema de parâmetros, execução, validação e política de confirmação para ações no computador;
4) 3 skills iniciais “estruturantes” e 2 skills de ação como base.

O resultado deve ser incremental (PRs/commits pequenos) e com testes manuais bem definidos.

---

## Contexto / Problemas atuais (baseado no uso realtime)
- Wake word é frágil (variações de STT fazem o sistema ignorar chamadas “JARVES/Jervis/Jarvis,” etc).
- Conversa é binária: sem wake word a frase é descartada, não existe “estado engaged”.
- O modelo “puxa” memória antiga e afirma como contexto atual (contamina o diálogo).
- O OCR da tela vai inteiro ou “ruidoso” e o LLM se perde com facilidade.
- Quando o usuário pede “opinião/ajuda”, o sistema inventa contexto técnico e não pede clarificação.

---

## Requisitos Funcionais
### 1) State machine: idle/engaged
- Estados:
  - `idle`: ignora fala comum, só acorda com wake word.
  - `engaged`: após acordar, aceita fala sem wake word por `ENGAGED_TTL` (ex.: 15s), renovando a cada fala.
- Comandos para voltar ao idle: “dormir”, “parar”, “silêncio”, “encerrar”.
- Cooldown curto para não reativar por eco do TTS.

### 2) Wake word robusto (STT-friendly)
- Normalizar texto (lowercase, remover pontuação, remover acentos).
- Aceitar aliases e variações (ex.: jarvis, jarves, jervis, jarves, jarviz etc) usando fuzzy matching (difflib ou rapidfuzz).
- Logar score e variante detectada.

### 3) Context Builder (controlado)
- Separar contexto em camadas:
  - **Contexto Conversacional**: últimas N falas (curto) + resumo do diálogo.
  - **Contexto do Sistema**: app/janela ativa, título, URL (se possível), timestamp.
  - **Contexto Visual**: por padrão, apenas um **resumo estruturado** da tela (não OCR completo).
- “OCR detalhado” só deve entrar se:
  - usuário pedir explicitamente (“lê isso”, “o que diz nesse erro”, “o que está na tela”), OU
  - roteador detectar intenção visual (ex.: “esse erro aqui” + alta evidência).
- Definir limites: OCR máximo por turno (ex.: 1500–3000 chars) e priorizar regiões relevantes.

### 4) Skill Router (intenção + clarificação)
- Implementar roteamento com saída:
  - `skill_name`, `confidence`, `extracted_params`, `needs_clarification`.
- Quando o pedido for genérico (“me ajuda”, “opinião”), **não inventar contexto**:
  - pedir 1 pergunta objetiva de clarificação
  - oferecer 2–3 caminhos com base em contexto RECENTE (último minuto), não no histórico distante.
- Política anti-alucinação:
  - Não citar nomes de funções/arquivos/erros que não estejam no contexto recente ou no repo analisado naquele momento.

### 5) Framework de Skills em Python (plugins)
Criar um sistema de skills com:
- Descoberta dinâmica (ex.: pasta `jarvis/skills/` com módulos).
- Cada skill deve ter:
  - `name`, `description`, `triggers`, `safety` (requires_confirmation, pii_sensitive), `params_schema`
  - método `can_handle(context) -> score`
  - método `run(context, params, tools) -> result`
- Definir um “contrato” de resultado:
  - `assistant_message` (texto final)
  - `actions` (ações que seriam executadas)
  - `requires_confirmation` (se houver ações)
  - `debug` (opcional, log estruturado)

### 6) Logs e instrumentação
Adicionar logs estruturados por turno:
- wakeword_detected, variant, score
- state idle/engaged, engaged_until
- intent/skill escolhido e confidence
- memory_hits e memory_applied (se existir perfil/memória)
- vision_used (true/false) + reason
- tokens/size do contexto enviado ao LLM (aprox)

---

## Skills iniciais (MVP obrigatório)
### Skill A: `intent_clarifier`
- Aciona quando a frase do usuário é vaga/genérica ou quando nenhum skill tem confidence alto.
- Faz 1 pergunta objetiva e sugere opções:
  1) responder pergunta (Q&A),
  2) interpretar o que está na tela,
  3) executar ação (email/anotação etc).

### Skill B: `screen_understanding`
- Entrega um “resumo da tela”:
  - app/janela ativa, elemento principal (ex.: “terminal”, “gmail”, “editor”), possíveis erros detectados (se evidência).
- Se usuário pedir “lê isso”, aciona OCR detalhado com recorte/limite.
- Não despejar OCR completo por padrão.

### Skill C: `realtime_chat`
- Fallback para perguntas claras de conhecimento geral.
- Deve respeitar políticas: sem suposições de projeto atual e sem memória agressiva.

---

## Skills de ação (base, sem enviar de verdade se não der)
### Skill D: `contacts_lookup` (stub ok)
- Implementar uma interface para resolver contatos:
  - por enquanto pode ser um repositório local JSON/SQLite (stub), mas com API clara para trocar depois por Google Contacts.
- Resolver ambiguidade (ex.: se houver 2 “João”, pedir qual).

### Skill E: `note_mode`
- Comandos:
  - “ativar modo anotação” → começa buffer de transcrição
  - “parar modo anotação” → fecha e gera resumo
- Persistência:
  - MVP: salvar local `notes/YYYY-MM-DD_HHMM.md`
  - Estrutura: título, bullets, decisões, tarefas, transcrição curta (opcional)
- Futuro: preparar interface para Google Docs, mas MVP local.

---

## Orientações de implementação (não quebrar o que já existe)
1) Primeiro mapear onde hoje são:
   - loop realtime,
   - wake word/trigger,
   - STT,
   - visão/OCR,
   - montagem do prompt,
   - chamada ao provider LLM,
   - TTS (se existir).
2) Refatorar em camadas sem mudar comportamento inicialmente.
3) Introduzir state machine (idle/engaged) e logs.
4) Introduzir Context Builder com visual em “resumo”.
5) Introduzir Skill Router + 3 skills MVP.
6) Depois adicionar note_mode e contacts_lookup.
7) Garantir que tudo rode em Windows (ambiente atual) e manter dependências mínimas.

---

## Critérios de aceite (testes manuais)
1) Wake word: “Jarvis”, “JARVES”, “Jervis”, “Jarvis,” aciona >= 90% em 20 tentativas (Whisper small).
2) Engaged window: após acionar 1 vez, consigo falar 2–3 frases sem repetir wake word e ele responde.
3) Sem contaminação: ao dizer “Jarvis” sozinho, ele não deve afirmar “você está trabalhando em X”, deve perguntar “como posso ajudar?”.
4) Pedido genérico: “Jarvis, eu gostaria de ajuda” deve acionar `intent_clarifier` e perguntar “ajuda com o quê?” (sem inventar código).
5) Visão: OCR detalhado só aparece quando solicitado; caso contrário, contexto visual é resumo curto.
6) Note mode: “ativar modo anotação” cria arquivo local; “parar modo anotação” finaliza e resume.

---

## Entregáveis
- Código novo/refatorado com:
  - `jarvis/context_builder.py`
  - `jarvis/state_machine.py`
  - `jarvis/skill_router.py`
  - `jarvis/skills/` (5 skills acima)
  - `jarvis/tools/` (interfaces p/ ações: notes, contacts)
- README curto (ou seção) explicando:
  - como adicionar nova skill,
  - como configurar ENGAGED_TTL e thresholds,
  - como rodar testes manuais.
- Commits pequenos e mensagens claras.

---

## Observação importante (segurança)
Qualquer ação “destrutiva” (enviar email, clicar, deletar, etc) deve exigir confirmação explícita do usuário antes de executar.
No MVP, ações podem ser simuladas (dry-run) e apenas logadas.