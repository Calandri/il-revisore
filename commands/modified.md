# /modified - List Modified Files

Show all modified, staged, and untracked files in the working directory.

## Analysis Steps

### Step 1: Git Status Overview
```bash
git status --porcelain
```

Parse status codes:
- `M` = Modified (in worktree)
- `A` = Added (staged)
- `D` = Deleted
- `R` = Renamed
- `??` = Untracked
- `MM` = Modified, staged, then modified again

### Step 2: Detailed Changes

#### Staged Changes (ready to commit)
```bash
git diff --cached --stat
```

#### Unstaged Changes (not yet staged)
```bash
git diff --stat
```

#### Untracked Files
```bash
git ls-files --others --exclude-standard
```

### Step 3: File Details
For each modified file, show:
- File path
- Type of change
- Lines added/removed
- Last modified time

### Step 4: Suggested Actions
Based on the state:
- Files to stage: `git add <file>`
- Files to unstage: `git restore --staged <file>`
- Files to discard: `git restore <file>`
- Untracked to ignore: add to `.gitignore`

## Response Format

```markdown
## File Modificati

**Branch**: `feature/my-branch`
**Confronto con**: `origin/main`

### Riepilogo
| Categoria | Count |
|-----------|-------|
| Staged | 3 |
| Modified | 5 |
| Untracked | 2 |
| Deleted | 1 |

---

### Staged (pronti per commit)
| File | Modifiche |
|------|-----------|
| src/api/auth.py | +45 / -12 |
| src/models/user.py | +20 / -5 |

### Modified (non staged)
| File | Modifiche |
|------|-----------|
| src/utils/helpers.py | +10 / -3 |
| tests/test_auth.py | +30 / -0 |

### Untracked (nuovi file)
- `src/new_feature.py`
- `docs/README.md`

### Deleted
- `old_module.py`

---

### Diff Preview
[Mostra preview delle modifiche più significative]

### Azioni Suggerite

**Per committare tutto:**
```bash
git add .
git commit -m "description"
```

**Per staging selettivo:**
```bash
git add src/api/auth.py src/models/user.py
```

**Per scartare modifiche:**
```bash
git restore src/utils/helpers.py
```
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: Group files logically and highlight important changes.**
