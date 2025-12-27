# /merge - Merge Branch to Main

Merge the current branch into main (or master) safely.

## Pre-Merge Checklist

Before merging, verify:
1. **Current branch**: Run `git branch --show-current` to confirm you're on the feature branch
2. **Clean working tree**: Run `git status` - no uncommitted changes
3. **Sync with remote**: Fetch latest changes `git fetch origin`
4. **Tests pass**: Optionally run tests to ensure nothing is broken

## Merge Process

### Step 1: Update main branch
```bash
git checkout main
git pull origin main
```

### Step 2: Merge feature branch
```bash
git merge <feature-branch> --no-ff -m "Merge <feature-branch> into main"
```

Use `--no-ff` to preserve branch history in the merge commit.

### Step 3: Handle conflicts (if any)
If there are merge conflicts:
1. List conflicting files
2. Show the conflict markers
3. Suggest resolution based on context
4. After resolution: `git add .` and `git commit`

### Step 4: Push to remote
```bash
git push origin main
```

### Step 5: Clean up (optional)
```bash
git branch -d <feature-branch>  # Delete local branch
git push origin --delete <feature-branch>  # Delete remote branch
```

## Response Format

```markdown
## Merge to Main

**Branch corrente**: [nome branch]
**Branch target**: main
**Stato**: [Completato | Conflitti | Errore]

### Pre-Merge Check
- [ ] Working tree pulito
- [ ] Branch aggiornato con remote
- [ ] Nessun conflitto rilevato

### Operazioni Eseguite
1. `git checkout main` - OK
2. `git pull origin main` - OK
3. `git merge <branch>` - [OK/Conflitti]
4. `git push origin main` - OK

### Conflitti (se presenti)
| File | Tipo Conflitto |
|------|----------------|
| ... | ... |

[Dettagli risoluzione conflitti]

### Risultato Finale
- Merge completato con successo
- Branch `<feature>` mergiato in `main`
- Remote aggiornato

### Cleanup Suggerito
```bash
git branch -d <feature-branch>
```
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: Ask for confirmation before pushing to main if there are any doubts.**
