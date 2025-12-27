# /review - Code Review

Review the latest changes: if there's an open PR for the current branch, review the PR; otherwise, review the last commit.

**IMPORTANT**: Use the branch specified in the context above. First verify you're on the correct branch:
```bash
git checkout <branch-from-context>
git pull origin <branch-from-context>
```

## Decision Flow

### Step 1: Check for Open PR
```bash
gh pr view --json state,number,title,url 2>/dev/null
```

- If a PR exists and is open → **Review PR**
- If no PR or PR is closed/merged → **Review Last Commit**

---

## Option A: Review PR

### Get PR Details
```bash
gh pr view --json number,title,body,url,headRefName,baseRefName,additions,deletions,files
```

### Get PR Diff
```bash
gh pr diff
```

### Analyze PR
For each changed file:
1. Understand the purpose of the change
2. Check for potential issues:
   - Security vulnerabilities (OWASP Top 10)
   - Performance problems
   - Missing error handling
   - Logic errors
   - Breaking changes
   - Code style violations
3. Suggest improvements

---

## Option B: Review Last Commit

### Get Commit Info
```bash
git log -1 --format="%H%n%an%n%ae%n%ad%n%s%n%b" --date=format:"%Y-%m-%d %H:%M"
```

### Get Changed Files
```bash
git diff-tree --no-commit-id --name-status -r HEAD
```

### Get Diff
```bash
git diff HEAD~1 HEAD
```

### Analyze Commit
Same analysis as PR review, focused on the single commit.

---

## Response Format

```markdown
## Code Review

**Tipo**: 🔀 Pull Request / 📝 Ultimo Commit
**Branch**: {branch_name}

---

### [Se PR] Info Pull Request
| Campo | Valore |
|-------|--------|
| **PR #** | #123 |
| **Titolo** | feat: add user authentication |
| **Base** | main ← feature/auth |
| **URL** | https://github.com/owner/repo/pull/123 |
| **Modifiche** | +350 / -120 |

### [Se Commit] Info Commit
| Campo | Valore |
|-------|--------|
| **Hash** | `abc1234` |
| **Autore** | Nome <email@example.com> |
| **Data** | 2024-01-15 14:30 |
| **Messaggio** | feat: add user authentication |

---

### File Modificati
| File | Tipo | +/- | Review |
|------|------|-----|--------|
| src/auth/login.py | M | +120/-30 | ⚠️ |
| src/auth/utils.py | A | +85/-0 | ✓ |
| tests/test_auth.py | A | +145/-0 | ✓ |

---

### Analisi Dettagliata

#### ✓ Punti Positivi
- Buona separazione delle responsabilità
- Test coverage adeguato
- Documentazione inline presente

#### ⚠️ Warning
1. **[src/auth/login.py:45]** - Potenziale SQL injection
   ```python
   # Attuale
   query = f"SELECT * FROM users WHERE email = '{email}'"
   # Suggerimento
   query = "SELECT * FROM users WHERE email = %s"
   ```

2. **[src/auth/utils.py:23]** - Manca gestione errori
   ```python
   # Suggerimento: aggiungere try/except
   ```

#### 🔴 Problemi Critici
- Nessun problema critico rilevato

oppure:

- **SECURITY**: Password in chiaro nel log (src/auth/login.py:78)
- **BREAKING**: Cambio di API incompatibile con versione precedente

---

### Riepilogo
| Categoria | Count |
|-----------|-------|
| ✓ OK | 8 file |
| ⚠️ Warning | 2 issues |
| 🔴 Critico | 0 issues |

### Verdetto
**✅ Approvato** / **⚠️ Approvato con riserve** / **❌ Richiede modifiche**

### Prossimi Passi
1. [Azioni specifiche da completare]
2. [Fix da applicare prima del merge]
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: Focus on actionable feedback - specific issues with line numbers and suggested fixes.**
**IMPORTANT: Prioritize security issues over style issues.**
**IMPORTANT: Be constructive - highlight what's done well, not just problems.**
