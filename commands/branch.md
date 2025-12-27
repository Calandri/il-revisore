# /branch - Create New Branch

Create a new git branch from the current state or from main.

**IMPORTANT**: Use the branch specified in the context above as the starting point. First verify you're on the correct branch:
```bash
git checkout <branch-from-context>
git pull origin <branch-from-context>
```

## Interactive Flow

### Step 1: Get Current State
```bash
git branch --show-current
git status --porcelain
```

Check:
- Current branch name
- Any uncommitted changes (warn user)

### Step 2: Determine Branch Name

If the user provided a name in the command (e.g., `/branch fix-login-bug`), use it.

Otherwise, ask what type of branch:
- `feature/` - New functionality
- `fix/` - Bug fix
- `hotfix/` - Urgent production fix
- `refactor/` - Code refactoring
- `docs/` - Documentation
- `test/` - Test additions

Then suggest a name based on context or ask the user.

### Step 3: Create Branch

**Option A: From current branch**
```bash
git checkout -b <branch-name>
```

**Option B: From main (recommended for new features)**
```bash
git fetch origin
git checkout -b <branch-name> origin/main
```

### Step 4: Verify and Push
```bash
git branch --show-current
git push -u origin <branch-name>
```

## Branch Naming Conventions

Follow these patterns:
- `feature/add-user-auth`
- `fix/login-validation-error`
- `hotfix/security-patch-v2`
- `refactor/cleanup-api-routes`
- `docs/update-readme`

Rules:
- Lowercase only
- Use hyphens, not underscores or spaces
- Be descriptive but concise
- Include ticket number if available: `feature/JIRA-123-add-auth`

## Response Format

```markdown
## Creazione Nuovo Branch

### Stato Attuale
- **Branch corrente**: `main`
- **Working tree**: Pulito / [X file modificati]
- **Remote**: `origin`

### Nuovo Branch
- **Nome**: `feature/my-new-feature`
- **Basato su**: `origin/main`

### Comandi Eseguiti
```bash
git fetch origin
git checkout -b feature/my-new-feature origin/main
git push -u origin feature/my-new-feature
```

### Risultato
Branch `feature/my-new-feature` creato e pushato con successo.

**Prossimi passi:**
1. Inizia a lavorare sulle modifiche
2. Committa le modifiche: `git commit -m "..."`
3. Pusha gli aggiornamenti: `git push`
4. Quando pronto, crea una PR con `/pr`
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: If there are uncommitted changes, warn the user and suggest stashing or committing first.**
**IMPORTANT: If the user provides a branch name after the command (e.g., `/branch fix-bug`), use it directly.**
