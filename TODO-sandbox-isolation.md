# TODO: Sandbox Isolation per Claude CLI

## Problema
Claude CLI eredita tutte le env vars e può leggere tutto il filesystem, inclusi `.env` e altri progetti.

## Soluzione
firejail sandbox con isolamento per progetto + fallback a sudo.

---

## Checklist

### Dockerfile
- [ ] Installare `firejail` e `sudo`
- [ ] Creare user `sandbox` (fallback)
- [ ] Creare `/app/prompts/` per system prompt

### claude_cli.py
- [ ] `_build_sandbox_env()` - env minimale (solo API keys)
- [ ] `_build_sandbox_command()` - firejail con whitelist progetto
- [ ] `_build_fallback_command()` - sudo -u sandbox
- [ ] `_is_firejail_available()` - check se firejail funziona
- [ ] Modificare `execute()` per usare sandbox

### gemini.py
- [ ] Stessa logica sandbox di claude_cli.py

### config.py
- [ ] Aggiungere `SandboxSettings`:
  - `enabled: bool = True`
  - `system_prompt_path: str = "/app/prompts/system.md"`
  - `fallback_enabled: bool = True`

### aws_secrets.py
- [ ] `get_project_secrets(project_id)` - secrets per progetto

### File nuovi
- [ ] `/app/prompts/system.md` - system prompt globale

---

## Cosa Blocca / Permette

| Risorsa | Stato |
|---------|-------|
| `/app/.env` | BLOCCATO |
| `/app/src/` | BLOCCATO |
| `/data/repos/altro-progetto/` | BLOCCATO |
| `/app/prompts/system.md` | read-only |
| `/data/repos/progetto-corrente/` | read-write |
| Network | OK |
| Env: DB_URL, AWS creds | BLOCCATO |
| Env: API keys progetto | OK |

---

## Test

```bash
# Devono FALLIRE:
firejail --whitelist=/data/repos/test cat /app/.env
firejail --whitelist=/data/repos/test ls /data/repos/altro

# Devono FUNZIONARE:
firejail --whitelist=/data/repos/test ls /data/repos/test
firejail curl https://api.github.com
```
