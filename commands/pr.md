# /pr - Create Pull Request

Create a Pull Request from the current branch to main.

## Pre-PR Checklist

### Step 1: Verify Branch State
```bash
git branch --show-current
git status
git log origin/main..HEAD --oneline
```

Check:
- Not on main/master branch
- All changes committed
- Commits exist that aren't in main

### Step 2: Sync with Remote
```bash
git fetch origin
git push origin <current-branch>
```

Ensure local branch is pushed to remote.

### Step 3: Gather PR Information

**Commits to include:**
```bash
git log origin/main..HEAD --format="%h %s"
```

**Files changed:**
```bash
git diff origin/main...HEAD --stat
```

**Diff summary:**
```bash
git diff origin/main...HEAD --shortstat
```

### Step 4: Generate PR Content

Based on the commits and changes, generate:

1. **Title**: Concise summary (from branch name or main commit)
2. **Description**:
   - What changes were made
   - Why (context/motivation)
   - How to test
   - Screenshots if UI changes
3. **Labels**: bug, feature, documentation, etc.
4. **Reviewers**: Suggest based on changed files

### Step 5: Create PR

Using GitHub CLI:
```bash
gh pr create \
  --title "Title here" \
  --body "Description here" \
  --base main \
  --head <current-branch>
```

Or provide the URL to create manually:
`https://github.com/<owner>/<repo>/compare/main...<branch>`

## Response Format

```markdown
## Creazione Pull Request

### Branch Info
- **Branch sorgente**: `feature/my-feature`
- **Branch destinazione**: `main`
- **Commits**: 5 commits
- **File modificati**: 12 files (+350 / -120)

### Commits Inclusi
| Hash | Messaggio |
|------|-----------|
| abc123 | feat: add login form |
| def456 | feat: add validation |
| ghi789 | test: add login tests |

### File Modificati
| File | Modifiche |
|------|-----------|
| src/auth/login.py | +120 / -0 |
| src/auth/validators.py | +45 / -10 |
| tests/test_login.py | +80 / -0 |
| ... | ... |

---

### PR Generata

**Titolo**: feat: Add user login functionality

**Descrizione**:
## Summary
- Added login form with email/password validation
- Implemented JWT token authentication
- Added comprehensive test coverage

## Changes
- New login component with form validation
- Backend authentication endpoint
- Unit and integration tests

## Test Plan
- [ ] Login with valid credentials
- [ ] Login with invalid credentials shows error
- [ ] Token is stored correctly

---

### Comando per Creare PR
```bash
gh pr create --title "feat: Add user login" --body "..." --base main
```

### Link Alternativo
[Crea PR manualmente](https://github.com/owner/repo/compare/main...feature/my-feature)

### PR Creata
**URL**: https://github.com/owner/repo/pull/123
**Stato**: Open
**Reviewers suggeriti**: @teammate1, @teammate2
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: If gh CLI is available, use it to create the PR automatically.**
**IMPORTANT: Generate a meaningful PR description based on the actual commits and changes.**
