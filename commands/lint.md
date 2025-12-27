# /lint - Lint Analysis

Run linting tools on the codebase and analyze the results.

## Analysis Steps

### Step 1: Identify Project Type
Detect the project type by checking for configuration files:
- Python: `pyproject.toml`, `setup.py`, `ruff.toml`
- JavaScript/TypeScript: `package.json`, `eslint.config.js`, `.eslintrc.*`
- Both: Full-stack project

### Step 2: Run Linters

**For Python projects:**
```bash
# Check for ruff (preferred)
ruff check . --output-format=grouped

# If ruff not available, try pylint
pylint --output-format=colorized src/
```

**For JavaScript/TypeScript projects:**
```bash
# Check for eslint
npx eslint . --format=stylish

# Or with pnpm
pnpm eslint . --format=stylish
```

### Step 3: Categorize Issues
Group issues by severity and type:
- **Errors**: Must fix (syntax errors, undefined vars, etc.)
- **Warnings**: Should fix (unused imports, complexity, etc.)
- **Info**: Style suggestions

### Step 4: Analyze Results
For each issue category:
1. Count total issues
2. Identify most common problems
3. List files with most issues
4. Suggest batch fixes

## Response Format

```markdown
## Analisi Lint

**Progetto**: {project_name}
**Branch**: {branch_name}
**Linter**: ruff / eslint

### Riepilogo
| Severità | Count |
|----------|-------|
| ❌ Errori | 5 |
| ⚠️ Warning | 23 |
| ℹ️ Info | 12 |

### Problemi Più Comuni
| Codice | Descrizione | Count |
|--------|-------------|-------|
| E501 | Line too long | 15 |
| F401 | Unused import | 8 |
| W291 | Trailing whitespace | 5 |

### File con Più Issues
| File | Errori | Warning |
|------|--------|---------|
| src/api/routes.py | 3 | 8 |
| src/utils/helpers.py | 2 | 5 |

### Dettaglio Errori Critici
```
src/api/routes.py:45:1: E999 SyntaxError: invalid syntax
src/models/user.py:12:5: F821 undefined name 'response'
```

### Fix Automatici Disponibili
```bash
# Applica fix automatici con ruff
ruff check . --fix

# O con eslint
npx eslint . --fix
```

### Raccomandazioni
1. [Suggerimento specifico basato sugli errori trovati]
2. [Suggerimento per prevenire errori futuri]
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: Always run the actual linting commands - don't just list what should be done.**
**IMPORTANT: If auto-fix is available, offer to run it but wait for user confirmation before applying.**
