---
name: commit
description: Use this skill when the user asks to commit, create a commit, make a git commit, "faz um commit", "commita", "salva as mudanças no git", or any variation of creating a git commit. Always use English for commit messages. Never add Co-Authored-By lines.
tools: Bash
disable-model-invocation: false
---

# Commit Skill — Jarvis Project Standard

Cria commits seguindo o padrão do projeto: mensagem em **inglês**, sem `Co-Authored-By`.

---

## Regras obrigatórias

1. **Mensagem sempre em inglês** — sem exceção, mesmo que a conversa seja em português.
2. **Sem Co-Authored-By** — nunca adicionar a linha `Co-Authored-By: Claude ...` ou qualquer variante.
3. **Conventional Commits** — usar os prefixos: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `perf`, `style`.
4. **Mensagem concisa** — título em até 72 chars. Body opcional apenas se a mudança for complexa.
5. **Staged files** — adicionar apenas os arquivos que fazem sentido para o commit (não usar `git add -A` cegamente).

---

## Workflow passo a passo

### 1. Verificar o estado atual

```bash
git status
git diff --stat
```

Analise o que mudou antes de qualquer coisa. Identifique:
- Quais arquivos foram modificados e por quê
- Se há arquivos que **não** devem ir neste commit (ex: `.env`, arquivos temporários, configurações locais)

### 2. Entender as mudanças em detalhe

```bash
git diff          # para arquivos não staged
git diff --staged # para arquivos já staged
```

Leia as mudanças para formular uma mensagem precisa. A mensagem deve responder: **"O que essa mudança faz?"**, não "O que foi editado".

### 3. Escolher o tipo de commit

| Prefixo | Quando usar |
|---------|-------------|
| `feat`  | Nova funcionalidade visível pelo usuário |
| `fix`   | Correção de bug |
| `chore` | Tarefa de manutenção, atualização de deps, config |
| `refactor` | Mudança de código sem alterar comportamento |
| `perf`  | Melhoria de performance |
| `docs`  | Apenas documentação |
| `test`  | Apenas testes |
| `style` | Formatação, espaços, sem mudança de lógica |

### 4. Adicionar os arquivos certos

```bash
# Preferir adicionar por nome — nunca `git add -A` sem inspecionar antes
git add jarvis/sensors/audio.py jarvis/config.py
```

Nunca adicionar ao commit:
- `.env` ou qualquer arquivo com secrets
- `__pycache__/`, `*.pyc`
- `.claude/settings.local.json` (configurações locais do Claude)
- Arquivos de log (`logs/session_*.jsonl`)

### 5. Criar o commit

```bash
git commit -m "$(cat <<'EOF'
feat: add wake word detection to realtime mode
EOF
)"
```

Para mudanças complexas, use body:

```bash
git commit -m "$(cat <<'EOF'
refactor: split audio processing into separate VAD thread

Move VAD logic from the main audio callback into a dedicated thread
to prevent blocking the sounddevice high-priority callback.
EOF
)"
```

### 6. Verificar o resultado

```bash
git log --oneline -5
```

---

## Exemplos de mensagens boas vs. ruins

| Ruim | Bom |
|------|-----|
| `fix stuff` | `fix: prevent STT hallucinations on short audio` |
| `update audio` | `refactor: extract VAD loop into dedicated thread` |
| `wip` | `chore: bump faster-whisper to 1.2.1` |
| `changes` | `feat: add content awareness events to observer` |
| `corrigido bug` | `fix: handle missing Tesseract gracefully in VisionSensor` |

---

## Mensagem de commit NUNCA deve conter

- `Co-Authored-By:` — proibido por preferência explícita do projeto
- Texto em português — sempre inglês
- Emojis — não usados neste projeto
- "WIP", "TODO", "fix fix", mensagens vagas
