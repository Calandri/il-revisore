# BUG CRITICO: Claude CLI Extended Thinking

> **Data scoperta**: 2025-12-25
> **Versioni affette**: Claude CLI v2.0.64+
> **Stato**: RISOLTO con workaround

---

## IL PROBLEMA

```bash
# QUESTO SI BLOCCA INDEFINITAMENTE:
echo "prompt" | claude --print --verbose --output-format stream-json \
  --settings '{"alwaysThinkingEnabled": true}'
```

**Sintomi:**
- Il processo rimane in esecuzione con 0% CPU
- TCP connections attive verso API Anthropic (160.79.104.10:443)
- Nessun output su stdout
- Nessun errore su stderr
- Il processo non termina mai (testato fino a 2+ ore)

---

## LA CAUSA

Il flag `--settings '{"alwaysThinkingEnabled": true}'` è **BUGGY** nelle versioni recenti di Claude CLI:

- È un setting non documentato ufficialmente
- Funzionava in versioni precedenti ma è una regressione
- Il CLI accetta il parametro senza errori ma poi si blocca

---

## LA SOLUZIONE

Usare la variabile d'ambiente `MAX_THINKING_TOKENS` invece:

```bash
# QUESTO FUNZIONA PERFETTAMENTE (2-3 secondi):
echo "prompt" | MAX_THINKING_TOKENS=8000 claude --print --verbose \
  --output-format stream-json
```

**Nel codice Python:**

```python
# PRIMA (buggy):
args.extend(["--settings", json.dumps({"alwaysThinkingEnabled": True})])

# DOPO (funziona):
env["MAX_THINKING_TOKENS"] = "8000"
```

---

## TEST DI VERIFICA

```bash
# Test SENZA extended thinking (baseline - ~3 sec)
echo "Say hello in JSON" | claude --print --verbose \
  --model claude-opus-4-5-20251101 --output-format stream-json 2>&1 | head -10

# Test CON extended thinking via env var (~3 sec, include thinking block)
echo "Say hello in JSON" | MAX_THINKING_TOKENS=4000 claude --print --verbose \
  --model claude-opus-4-5-20251101 --output-format stream-json 2>&1 | head -50
```

**Output atteso con thinking:**
```json
{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"..."}]}}
{"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}}
```

---

## FILE MODIFICATI

- `src/turbowrap/review/reviewers/claude_cli_reviewer.py` (linee 537-542)

```python
# Extended thinking via MAX_THINKING_TOKENS env var
# NOTE: --settings {"alwaysThinkingEnabled": true} is BUGGY in Claude CLI v2.0.64+
# and causes the process to hang indefinitely. Use env var instead.
if self.settings.thinking.enabled:
    env["MAX_THINKING_TOKENS"] = str(self.settings.thinking.budget_tokens)
    logger.info(f"[CLAUDE CLI] Extended thinking enabled: MAX_THINKING_TOKENS={env['MAX_THINKING_TOKENS']}")
```

---

## RIFERIMENTI

- Config: `thinking.budget_tokens` (default: 8000, range: 1000-50000)
- Config: `thinking.enabled` (default: True)
