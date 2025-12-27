# /format - Format Code

Run code formatters on the codebase to ensure consistent style.

**IMPORTANT**: Use the branch specified in the context above. First verify you're on the correct branch:
```bash
git checkout <branch-from-context>
git pull origin <branch-from-context>
```

## Steps

### Step 1: Identify Project Type
Detect formatters by checking configuration files:
- Python: `pyproject.toml` (ruff, black), `setup.cfg`
- JavaScript/TypeScript: `package.json` (prettier), `.prettierrc`
- Both: Full-stack project

### Step 2: Check Current State
```bash
git status --porcelain
```
Note any uncommitted changes - formatting will modify files.

### Step 3: Run Formatters

**For Python projects:**
```bash
# Prefer ruff format (fast, compatible with black)
ruff format .

# Check what would change without applying
ruff format . --check --diff
```

**For JavaScript/TypeScript projects:**
```bash
# With prettier
npx prettier --write .

# Check only
npx prettier --check .
```

### Step 4: Review Changes
```bash
git diff --stat
git diff
```

Show what files were modified and the actual changes.

### Step 5: Stage Changes (if requested)
```bash
git add -A
```

## Response Format

```markdown
## Formattazione Codice

**Branch**: {branch_name}
**Formatter**: ruff / prettier

### Pre-Check
- File non committati: [Sì/No]
- File da formattare: X

### Esecuzione
```bash
ruff format .
```

### Risultato
| File | Stato |
|------|-------|
| src/api/routes.py | ✓ Formattato |
| src/utils/helpers.py | ✓ Formattato |
| src/models/user.py | - Già OK |

**Totale**: 5 file formattati, 12 già conformi

### Modifiche Applicate
```diff
# Preview delle modifiche principali
- def foo(x,y,z):
+ def foo(x, y, z):
```

### Prossimi Passi
I file sono stati formattati. Per committare:
```bash
git add -A
git commit -m "style: format code"
```
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: Run the formatter and show actual results - don't just explain what would happen.**
**IMPORTANT: Always show a preview of changes before committing.**
