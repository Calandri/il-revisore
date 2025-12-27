# /refactor - Transform/Refactor Code

Analyze code and suggest or apply refactoring transformations.

**IMPORTANT**: Use the branch specified in the context above. First verify you're on the correct branch:
```bash
git checkout <branch-from-context>
git pull origin <branch-from-context>
```

## Interactive Flow

### Step 1: Understand Scope
Ask the user what to refactor:
- A specific file or function
- A module or component
- The entire codebase structure

If no specific target is provided, analyze the codebase for common refactoring opportunities.

### Step 2: Analyze Current Code
For the target code, identify:
- Code smells (long functions, duplications, etc.)
- Complexity hotspots
- Naming inconsistencies
- Architecture issues

### Step 3: Suggest Refactorings
Common refactoring patterns:
- **Extract Function**: Break long functions into smaller, focused ones
- **Extract Variable**: Name complex expressions
- **Rename**: Improve naming clarity
- **Move**: Relocate code to better locations
- **Consolidate**: Merge duplicate code
- **Simplify Conditionals**: Reduce nested if/else
- **Remove Dead Code**: Delete unused code

### Step 4: Present Options
For each suggestion:
1. Show the current code
2. Explain the problem
3. Show the proposed change
4. Estimate impact/risk

### Step 5: Apply Changes (if approved)
Make the refactoring changes incrementally:
1. Apply one refactoring at a time
2. Verify tests still pass
3. Commit with clear message
4. Move to next refactoring

## Response Format

```markdown
## Analisi Refactoring

**Branch**: {branch_name}
**Target**: [file/modulo/codebase]

### Code Smells Rilevati
| Tipo | File | Linea | Severità |
|------|------|-------|----------|
| Long Function | src/api/routes.py | 45-120 | 🔴 Alta |
| Duplicate Code | src/utils/*.py | - | 🟡 Media |
| Complex Conditional | src/auth/login.py | 78 | 🟡 Media |

### Refactoring Suggeriti

#### 1. Extract Function - `process_user_data` (Alta priorità)
**File**: src/api/routes.py:45-120

**Problema**: Funzione di 75 righe con multiple responsabilità

**Attuale**:
```python
def handle_request(request):
    # 20 righe di validazione
    # 30 righe di processamento
    # 25 righe di formattazione response
```

**Proposta**:
```python
def handle_request(request):
    data = validate_request(request)
    result = process_data(data)
    return format_response(result)

def validate_request(request): ...
def process_data(data): ...
def format_response(result): ...
```

**Impatto**: 🟢 Basso rischio, migliora testabilità

---

#### 2. Consolidate Duplicates (Media priorità)
**File**: src/utils/string_utils.py, src/utils/text_utils.py

**Problema**: Funzioni duplicate `clean_text()` e `sanitize_text()`

**Proposta**: Unificare in una singola funzione in `src/utils/text.py`

---

### Piano di Esecuzione
1. [ ] Extract functions da `handle_request`
2. [ ] Consolidare utilities duplicate
3. [ ] Semplificare conditionals in `login.py`

### Comandi
Per applicare i refactoring:
```bash
# Verifica test prima
pytest -v

# Dopo ogni refactoring
git add -A
git commit -m "refactor: extract validation from handle_request"
pytest -v
```
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: Always suggest incremental changes - never refactor everything at once.**
**IMPORTANT: Run tests after each refactoring to ensure nothing breaks.**
**IMPORTANT: Ask for user confirmation before making changes, unless they explicitly asked to apply.**
