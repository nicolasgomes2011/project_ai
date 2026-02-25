# TASK — Trocar LLM (Groq → Claude) + Corrigir visão (leitura de tela) + Melhorar latência

## Contexto / Problemas observados
Rodando no PC (Windows) com:
`python -m jarvis --mode realtime`

O sistema inicia com áudio + visão “ativas” no log, mas:
1) A IA responde que não consegue ver a tela, mesmo com “Visão: ✓” e “Sensor de visão iniciado”.
2) O tempo de resposta está muito lento: algumas perguntas levam **15+ segundos** para serem respondidas.
3) A IA não parece identificar bem o que está rolando na tela — possivelmente por:
   - visão não estar chegando no prompt,
   - frame desatualizado (delay),
   - pipeline lento (captura/STT/LLM) que faz o contexto visual chegar “atrasado”.

Ao encerrar, aparece warning:
`Task was destroyed but it is pending! ... RealtimeMode._on_utterance() ...`
indicando shutdown incompleto.

Obs: no notebook onde foi desenvolvido inicialmente parecia ok; no PC atual pode existir algo de permissão/captura bloqueada.

---

## Objetivos (mudanças solicitadas)
1) Trocar o provedor/motor de LLM:
   - Atualmente: Groq.
   - Desejado: Anthropic Claude (porque já pago mensal e quero melhor qualidade).
   - Manter Groq opcional como fallback (se for fácil).

2) Corrigir bug da “Visão”:
   - Garantir captura real de tela e envio do contexto visual para o agente/LLM.
   - Não depender de OCR (Tesseract pode estar ausente). Visão deve funcionar com screenshot mesmo sem OCR.
   - Fazer o agente “assumir” que tem visão ativa quando estiver, e responder coerentemente quando perguntado.

3) Melhorar latência (respostas rápidas e visão atualizada):
   - Instrumentar o pipeline para medir tempo por etapa e identificar gargalos.
   - Reduzir o “end-to-end latency” (fala → resposta) e garantir que o frame usado seja RECENTE.
   - Se a visão é usada, garantir que o frame esteja dentro de um limite (ex.: capturado nos últimos 1–2s); caso contrário, capturar novamente antes de responder.

4) Ajustar encerramento:
   - Remover “Task was destroyed but it is pending!” com cancelamento/await corretos das tasks.

---

## Requisitos de implementação

### A) Provider Claude (Anthropic)
- Localizar onde o provider é selecionado (config/env/factory).
- Implementar provider Anthropic com `ANTHROPIC_API_KEY` e modelo configurável por env.
- Atualizar README com instruções e exemplos de `.env`.

### B) Visão: captura de tela + anexação no prompt (com logs)
- Localizar:
  - onde a tela é capturada (ex.: `mss`)
  - onde vira “contexto” pro agente
- Adicionar logs (modo debug) para:
  - confirmar captura (resolução, tamanho, timestamp, monitor)
  - confirmar que a imagem/descrição chegou no payload do LLM
- Comportamento esperado:
  - Se visão ativa, ao perguntar “Você consegue ver minha tela?” o Jarvis deve confirmar e descrever algo mínimo do frame atual.
- OCR:
  - Se Tesseract não existir, ainda assim usar screenshot.
  - Se existir, habilitar OCR.
- Windows:
  - Tratar exceções de captura (permissão/tela preta/multi-monitor) e logar erro explicitamente.

### C) Performance / Latência (novo)
- Medir e logar tempos por etapa (em ms), por exemplo:
  - VAD/segmentação de fala
  - STT (Whisper) tempo de transcrição
  - Captura de visão (screenshot) tempo
  - OCR (se ativo) tempo
  - Montagem do prompt/contexto
  - Tempo da chamada ao LLM (TTFB e total)
- Reduzir latência com medidas práticas:
  - Não bloquear resposta esperando OCR se OCR estiver lento (usar OCR assíncrono ou “best effort”).
  - Reduzir tamanho do contexto visual (ex.: downscale/qualidade JPEG) antes de enviar (se multimodal suportado).
  - Cache do último frame + timestamp e política de “frame freshness” (usar frame recente; se velho, capturar novo).
  - Evitar reprocessar visão a cada micro-interação se não for necessário.
- Verificar se o modo realtime está esperando tool calls/retries desnecessários.

### D) Shutdown correto
- No Ctrl+C:
  - cancelar tasks pendentes (incluindo `_on_utterance`)
  - `await gather(return_exceptions=True)`
  - parar sensores 1x (sem duplicar logs)
- Encerrar sem warnings.

---

## Critérios de aceite (DoD)
- Rodar `python -m jarvis --mode realtime` e obter:
  - Provider: Claude conectado (modelo via ENV).
  - Resposta mais rápida (visivelmente menor que ~15s em perguntas simples) e logs mostrando onde era o gargalo.
  - Visão funcional:
    - captura confirmada por logs (resolução/timestamp)
    - frame usado é recente (política de freshness)
    - ao perguntar “Você consegue ver minha tela?”, o Jarvis confirma e descreve algo do frame atual
  - Encerramento limpo sem “Task was destroyed but it is pending!”

---

## Pistas do meu teste
- “Visão: ✓” e “Sensor de visão iniciado”, mas o LLM disse que não vê a tela.
- “Tesseract não encontrado — OCR desativado” (ok, mas visão não pode depender disso).
- Latência alta (15+ segundos) e pouca “consciência” do que acontece na tela.