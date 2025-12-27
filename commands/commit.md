# /commit - Last Commit Analysis

Analyze the last commit on the current branch in detail: what changed, why, and potential issues.

**IMPORTANT**: Use the branch specified in the context above. First verify you're on the correct branch:
```bash
git checkout <branch-from-context>
git pull origin <branch-from-context>
```

## Analysis Steps

### Step 1: Get Commit Info
```bash
git log -1 --format="%H%n%an%n%ae%n%ad%n%s%n%b" --date=format:"%Y-%m-%d %H:%M"
```

Extract:
- Commit hash (short + full)
- Author name and email
- Date and time
- Commit message (subject + body)

### Step 2: Get Changed Files
```bash
git diff-tree --no-commit-id --name-status -r HEAD
```

Categorize changes:
- **A** = Added (new files)
- **M** = Modified
- **D** = Deleted
- **R** = Renamed

### Step 3: Analyze Diff
```bash
git diff HEAD~1 HEAD --stat
```

Show:
- Lines added/removed per file
- Total insertions/deletions
- Files with most changes

### Step 4: Code Review
For each significantly changed file:
1. Show the diff (`git diff HEAD~1 HEAD -- <file>`)
2. Identify what was changed
3. Flag potential issues:
   - Security concerns (hardcoded secrets, SQL injection, etc.)
   - Performance issues
   - Missing error handling
   - Breaking changes

### Step 5: Commit Quality Assessment
Evaluate:
- Is the commit message descriptive?
- Is the commit atomic (single purpose)?
- Are there any files that shouldn't be committed (.env, node_modules, etc.)?

## Response Format

```markdown
## Analisi Ultimo Commit

### Info Commit
| Campo | Valore |
|-------|--------|
| **Hash** | `abc1234` (abc1234567890...) |
| **Autore** | Nome <email@example.com> |
| **Data** | 2024-01-15 14:30 |
| **Messaggio** | feat: add user authentication |

### File Modificati
| Stato | File | +/- |
|-------|------|-----|
| M | src/auth/login.py | +45 / -12 |
| A | src/auth/utils.py | +120 / -0 |
| D | old_auth.py | -0 / -85 |

**Totale**: 3 file, +165 insertions, -97 deletions

### Riepilogo Modifiche
[Descrizione delle modifiche principali per ogni file]

### Potenziali Problemi
- [ ] Nessun problema rilevato

oppure:
- [x] **ATTENZIONE**: Possibile secret hardcoded in config.py:15
- [x] **SUGGERIMENTO**: Manca gestione errori in login.py:42

### Qualità Commit
- **Messaggio**: [Buono/Migliorabile] - [commento]
- **Atomicità**: [Sì/No] - [commento]
- **File inappropriati**: [Nessuno/Lista]

### Diff Dettagliato
[Mostra i diff più significativi con syntax highlighting]
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: Focus on actionable insights, not just listing changes.**
