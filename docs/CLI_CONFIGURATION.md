# TurboWrap CLI Configuration Guide

Guida completa alla configurazione di Claude CLI e Gemini CLI per TurboWrap.

---

## Indice

1. [Modelli Utilizzati](#modelli-utilizzati)
2. [Passaggio API Keys](#passaggio-api-keys)
3. [Extended Thinking](#extended-thinking)
4. [Esempi di Codice](#esempi-di-codice)

---

## Modelli Utilizzati

### Configurazione in `config.py`

```python
class AgentSettings(BaseSettings):
    gemini_model: str = "gemini-3-flash-preview"      # Flash per challenger (veloce)
    gemini_pro_model: str = "gemini-3-pro-preview"    # Pro per fix review (reasoning)
    claude_model: str = "claude-opus-4-5-20251101"    # Opus per review/fix (qualità)
```

### Mapping Ruoli → Modelli

| Ruolo | CLI | Modello | Perché |
|-------|-----|---------|--------|
| **Code Fixer** | Claude | `claude-opus-4-5-20251101` | Massima qualità per modifiche codice |
| **Fix Reviewer** | Gemini | `gemini-3-pro-preview` | Pro per reasoning complesso |
| **PR Reviewer** | Claude | `claude-opus-4-5-20251101` | Analisi approfondita |
| **PR Challenger** | Gemini | `gemini-3-flash-preview` | Flash per velocità |

### Come Passare il Modello ai CLI

**Claude CLI:**
```bash
claude --model claude-opus-4-5-20251101 --print "prompt"
```

**Gemini CLI:**
```bash
gemini -m gemini-3-pro-preview "prompt"
```

**In Python:**
```python
# Claude
process = await asyncio.create_subprocess_exec(
    "claude",
    "--print",
    "--model", self.settings.agents.claude_model,  # ← Modello da settings
    stdin=asyncio.subprocess.PIPE,
    ...
)

# Gemini
process = await asyncio.create_subprocess_exec(
    "gemini",
    "-m", self.settings.agents.gemini_pro_model,  # ← Modello da settings
    stdin=asyncio.subprocess.PIPE,
    ...
)
```

---

## Passaggio API Keys

### Fonte: AWS Secrets Manager

Le API keys sono memorizzate in AWS Secrets Manager:
- **Secret Name:** `agent-zero/global/api-keys`
- **Region:** `eu-west-3`

Contenuto del secret:
```json
{
  "ANTHROPIC_API_KEY": "sk-ant-...",
  "GEMINI_API_KEY": "AIza...",
  "GOOGLE_API_KEY": "AIza..."
}
```

### Utility Functions

```python
# src/turbowrap/utils/aws_secrets.py

def get_anthropic_api_key() -> str | None:
    """Get ANTHROPIC_API_KEY from AWS Secrets Manager."""
    secrets = get_secrets()
    return secrets.get("ANTHROPIC_API_KEY")

def get_gemini_api_key() -> str | None:
    """Get GEMINI_API_KEY from AWS Secrets Manager."""
    secrets = get_secrets()
    return secrets.get("GEMINI_API_KEY")
```

### Come Passare le Keys ai Subprocess

I CLI leggono le API keys da environment variables. Dobbiamo passarle esplicitamente:

```python
from turbowrap.utils.aws_secrets import get_anthropic_api_key, get_gemini_api_key

async def _run_claude_cli(self, prompt: str) -> str | None:
    # 1. Copia environment corrente
    env = os.environ.copy()

    # 2. Aggiungi API key da AWS
    api_key = get_anthropic_api_key()
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    # 3. Passa env al subprocess
    process = await asyncio.create_subprocess_exec(
        "claude",
        "--print",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,  # ← IMPORTANTE: passa l'environment
    )
```

**Stessa logica per Gemini:**
```python
async def _run_gemini_cli(self, prompt: str) -> str | None:
    env = os.environ.copy()
    api_key = get_gemini_api_key()
    if api_key:
        env["GEMINI_API_KEY"] = api_key

    process = await asyncio.create_subprocess_exec(
        "gemini",
        "-m", model,
        stdin=asyncio.subprocess.PIPE,
        env=env,  # ← IMPORTANTE
    )
```

### Fallback Locale

Se AWS non è disponibile (sviluppo locale), le keys vengono lette dall'environment:

```python
def get_secrets() -> dict:
    try:
        # Prova AWS
        client = boto3.client('secretsmanager', region_name=AWS_REGION)
        response = client.get_secret_value(SecretId=SECRET_NAME)
        return json.loads(response['SecretString'])
    except NoCredentialsError:
        # Fallback: environment variables locali
        logger.warning("AWS credentials not found - running locally")
        return {}
```

---

## Extended Thinking

### Cos'è Extended Thinking

Extended Thinking permette a Claude di "pensare più a lungo" prima di rispondere:
- Analisi più approfondita
- Migliore reasoning per task complessi
- Budget configurabile (1k - 50k tokens)

### Configurazione in TurboWrap

```python
# config.py
class ThinkingSettings(BaseSettings):
    enabled: bool = True              # Abilitato di default
    budget_tokens: int = 10000        # Budget token per thinking
```

### Come Abilitare via CLI

**Metodo 1: Flag `--settings`** (quello che usiamo)
```bash
claude --print --settings '{"alwaysThinkingEnabled": true}' "prompt"
```

**Metodo 2: Trigger Words nel prompt**
```
think        → thinking level LOW
think hard   → thinking level MEDIUM
megathink    → thinking level MEDIUM
think harder → thinking level MAX
ultrathink   → thinking level MAX
```

**Metodo 3: Toggle interattivo** (solo sessioni interattive)
- Premi `TAB` per toggle on/off
- Comando `/t` per toggle temporaneo

### Implementazione in Python

```python
async def _run_claude_cli(self, prompt: str) -> str | None:
    # Build CLI arguments
    args = [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--model", self.settings.agents.claude_model,
    ]

    # Add extended thinking if enabled
    if self.settings.thinking.enabled:
        thinking_settings = {"alwaysThinkingEnabled": True}
        args.extend(["--settings", json.dumps(thinking_settings)])
        logger.info("Extended thinking enabled for Claude CLI")

    process = await asyncio.create_subprocess_exec(
        *args,  # ← Unpacking della lista
        stdin=asyncio.subprocess.PIPE,
        ...
    )
```

### Output Formats

Claude CLI supporta due formati JSON:

| Format | Flag | Uso |
|--------|------|-----|
| `json` | `--output-format json` | Output singolo alla fine |
| `stream-json` | `--output-format stream-json --verbose` | Streaming NDJSON in tempo reale |

**Noi usiamo `stream-json` ovunque** per:
- Streaming in tempo reale (reviewer)
- Logging dei costi per modello (orchestrator)
- Consistenza nel parsing

### Stream-JSON Format (NDJSON)

Con `--output-format stream-json --verbose`, ogni riga è un JSON separato:

```bash
claude --print --output-format stream-json --verbose "prompt"
```

Output (una riga JSON per evento):
```json
{"type":"system","subtype":"init","session_id":"...","model":"claude-opus-4-5-20251101",...}
{"type":"assistant","message":{"content":[{"type":"text","text":"Hello..."}],...}}
{"type":"result","result":"Hello world!","total_cost_usd":0.0263,"modelUsage":{...}}
```

**Tipi di eventi:**
- `system` + `init` → Inizializzazione sessione
- `assistant` → Chunks della risposta (streaming)
- `result` → Risultato finale con costi

**Parsing in Python:**
```python
raw_output = "".join(output_chunks)
output = ""
model_usage_list = []

# Parse NDJSON (Newline Delimited JSON)
for line in raw_output.strip().split("\n"):
    if not line.strip():
        continue
    try:
        event = json.loads(line)

        if event.get("type") == "result":
            # Estrai risultato finale
            output = event.get("result", "")

            # Estrai model usage
            for model_name, usage in event.get("modelUsage", {}).items():
                info = ModelUsageInfo(
                    model=model_name,
                    input_tokens=usage.get("inputTokens", 0),
                    output_tokens=usage.get("outputTokens", 0),
                    cost_usd=usage.get("costUSD", 0.0),
                )
                model_usage_list.append(info)

            # Costo totale
            total_cost = event.get("total_cost_usd", 0)
            logger.info(f"Total cost: ${total_cost:.4f}")

    except json.JSONDecodeError:
        continue  # Skip non-JSON lines
```

---

## Esempi di Codice

### Esempio Completo: Claude CLI con Thinking

```python
import asyncio
import json
import os
from turbowrap.config import get_settings
from turbowrap.utils.aws_secrets import get_anthropic_api_key

async def run_claude_with_thinking(prompt: str, repo_path: str) -> str | None:
    settings = get_settings()

    # 1. Prepara environment con API key
    env = os.environ.copy()
    api_key = get_anthropic_api_key()
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    # 2. Costruisci argomenti CLI
    args = [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--model", settings.agents.claude_model,
        "--output-format", "json",
    ]

    # 3. Aggiungi thinking se abilitato
    if settings.thinking.enabled:
        args.extend(["--settings", json.dumps({"alwaysThinkingEnabled": True})])

    # 4. Esegui subprocess
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=repo_path,
        env=env,
    )

    # 5. Invia prompt e leggi output
    stdout, stderr = await asyncio.wait_for(
        process.communicate(input=prompt.encode()),
        timeout=300,
    )

    if process.returncode != 0:
        print(f"Error: {stderr.decode()}")
        return None

    # 6. Parsa JSON output
    try:
        response = json.loads(stdout.decode())
        return response.get("result")
    except json.JSONDecodeError:
        return stdout.decode()
```

### Esempio Completo: Gemini CLI

```python
async def run_gemini_review(prompt: str, repo_path: str) -> str | None:
    settings = get_settings()

    # 1. Prepara environment
    env = os.environ.copy()
    api_key = get_gemini_api_key()
    if api_key:
        env["GEMINI_API_KEY"] = api_key

    # 2. Esegui Gemini CLI
    process = await asyncio.create_subprocess_exec(
        "gemini",
        "-m", settings.agents.gemini_pro_model,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=repo_path,
        env=env,
    )

    stdout, stderr = await asyncio.wait_for(
        process.communicate(input=prompt.encode()),
        timeout=120,
    )

    if process.returncode != 0:
        return None

    return stdout.decode()
```

---

## Troubleshooting

### "API key not found"

1. Verifica che AWS credentials siano configurate:
   ```bash
   aws sts get-caller-identity
   ```

2. Verifica il secret:
   ```bash
   aws secretsmanager get-secret-value \
     --secret-id agent-zero/global/api-keys \
     --region eu-west-3
   ```

3. Fallback locale: esporta la variabile:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   export GEMINI_API_KEY="AIza..."
   ```

### "Claude CLI not found"

Installa Claude CLI:
```bash
npm install -g @anthropic-ai/claude-code
```

### "Thinking not working"

1. Verifica che il modello supporti thinking (Opus, Sonnet 3.7+)
2. Controlla `settings.thinking.enabled` sia `True`
3. Verifica i log per "Extended thinking enabled"

---

## Quick Reference

```python
# Modelli
claude_model = "claude-opus-4-5-20251101"
gemini_flash = "gemini-3-flash-preview"
gemini_pro = "gemini-3-pro-preview"

# CLI Commands
# Claude
claude --print --model MODEL --settings '{"alwaysThinkingEnabled":true}' PROMPT

# Gemini
gemini -m MODEL PROMPT

# Environment Variables (passate via env=)
ANTHROPIC_API_KEY  # Per Claude
GEMINI_API_KEY     # Per Gemini
```
