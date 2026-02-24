## Jarvis “Vivo”: Voz + Visão em tempo real

### Objetivo da experiência
O Jarvis deve funcionar em modo contínuo:
- Ouve minha voz (e opcionalmente áudio do sistema) e responde por voz.
- “Vê” o que eu vejo (principalmente minha TELA; opcionalmente webcam) e entende o contexto para me auxiliar enquanto trabalho, estudo, jogo ou navego.
- Não é apenas reativo: deve detectar oportunidades de ajudar e sugerir ações de forma proativa, sem ser intrusivo.

---

## Conceito central: Loop de Percepção → Eventos → Orquestração

### Sensores (inputs)
1) **Áudio do microfone**
   - Captura contínua
   - VAD (detecção de fala) para reduzir custo/latência
   - STT (speech-to-text) local (preferencial) ou via serviço

2) **Visão (mínimo: captura de tela)**
   - Captura de tela contínua em baixa taxa (ex.: 1–3 FPS) + captura sob demanda (hotkey)
   - Extração de contexto:
     - OCR (texto na tela) quando útil
     - “Descrição visual” (frame summary) quando útil
     - Detecção de elementos relevantes (janelas, títulos, app em foco)

3) Contexto do sistema
   - App ativo, título da janela, clipboard, notificações
   - (Opcional) logs de teclado/mouse com muito cuidado e consentimento

---

## Proatividade (o que faz ele parecer “vivo”)
O Jarvis deve ter um módulo “Observer” que cria eventos como:
- “Usuário está há 3 min numa tela de erro”
- “Detectei um formulário com campo inválido”
- “Usuário abriu uma IDE e está em debug”
- “Você falou ‘não sei’ ou demonstrou dúvida”
- “Uma reunião vai começar em 10 min”
- “Mudou para uma página com termos técnicos”

Esses eventos alimentam o “Decision Engine” que escolhe:
- ficar quieto
- perguntar se pode ajudar
- sugerir 1 ação objetiva
- executar uma tool segura (se permitido)

Regra: proatividade deve ser **curta**, **não repetitiva**, e com **cooldown**.

---

## Latência e Estratégia de Custo
- Voz: responder em 300ms–2s após fim da fala (meta)
- Visão: não enviar frames “brutos” o tempo todo ao LLM
  - Fazer pré-processamento local (OCR + resumo do frame)
  - Enviar apenas: (a) texto detectado relevante, (b) descrição compacta, (c) recorte sob demanda

---

## Modo de interação
- Wake word (“Jarvis”) ou Push-to-talk
- Resposta por TTS (voz)
- Modo “silencioso” (somente texto) e modo “assistência contínua”
- Indicadores visíveis:
  - mic on/off
  - visão on/off
  - quando está gravando ou analisando

---

## Segurança e Privacidade (obrigatório)
- Por padrão, processar áudio/visão local quando possível
- Nunca registrar áudio/vídeo bruto em logs
- Logs apenas de:
  - transcrição (se permitido)
  - eventos resumidos
  - decisões e tools chamadas
- Whitelist de ferramentas e permissões por “nível de risco”
- “Kill switch” (atalho) para desligar tudo instantaneamente

---

## MVP Real-time (primeira entrega “viva”)
- Captura de microfone + VAD + STT
- TTS para respostas
- Captura de tela (1 FPS) + OCR sob demanda
- Detector de contexto simples:
  - app ativo, título de janela
  - palavras-chave no OCR/transcrição
- Proatividade mínima:
  - sugere ajuda quando detecta erro/impasse
- Tudo com memória e logs estruturados