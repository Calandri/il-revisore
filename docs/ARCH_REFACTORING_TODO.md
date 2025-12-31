# ARCH Refactoring TODO List

**Data creazione**: 2025-12-31
**Data completamento**: 2025-12-31
**Obiettivo**: Ridurre fix.py da ~1600 a ~800 righe (-50%), fix_issues() da 223 a ~40 righe (-82%)

---

## STEP 1: PendingQuestionStore (1-2h) - BASSO RISCHIO ✅ COMPLETATO

### Obiettivo
Incapsulare 4 dict globali in un singleton thread-safe.

### Task

- [x] **1.1** Creare file `src/turbowrap/api/services/pending_question_store.py`
- [x] **1.2** Migrare dict globali:
  - `_pending_clarifications` → `store._clarifications`
  - `_clarification_answers` → `store._clarification_futures`
  - `_pending_scope_violations` → `store._scope_violations`
  - `_scope_violation_responses` → `store._scope_futures`
- [x] **1.3** Migrare `register_scope_question()` → `store.register_scope_violation()`
- [x] **1.4** Migrare `wait_for_scope_response()` → `store.wait_for_scope_response()`
- [x] **1.5** Aggiornare fix.py per usare `PendingQuestionStore.get_instance()`
- [x] **1.6** Rimuovere dict e funzioni originali da fix.py

### File Coinvolti
- **NUOVO**: `src/turbowrap/api/services/pending_question_store.py`
- **MODIFICA**: `src/turbowrap/api/routes/fix.py` (linee 53-95)

---

## STEP 2: FixClarifyService (2-3h) - MEDIO RISCHIO

### Obiettivo
Estrarre ~200 righe di business logic da `/clarify` endpoint.

### Task

- [ ] **2.1** Creare file `src/turbowrap/api/services/fix_clarify_service.py`
- [ ] **2.2** Estrarre `_format_issues_for_clarify()` → `service._format_issues()`
- [ ] **2.3** Estrarre `_format_answers_for_clarify()` → `service._format_answers()`
- [ ] **2.4** Estrarre blocchi da `clarify_before_fix()`:
  - [ ] Mark IN_PROGRESS (522-531) → `service._mark_issues_in_progress()`
  - [ ] Build prompt (536-566) → `service._build_prompt()`
  - [ ] Run CLI (568-591) → `service._run_clarifier()`
  - [ ] Parse response (593-693) → `service._parse_and_build_response()`
  - [ ] Save clarifications (657-685) → `service._save_clarifications()`
- [ ] **2.5** Snellire endpoint `/clarify` → thin controller (~15 righe)
- [ ] **2.6** Rimuovere helper originali da fix.py

### File Coinvolti
- **NUOVO**: `src/turbowrap/api/services/fix_clarify_service.py`
- **MODIFICA**: `src/turbowrap/api/routes/fix.py` (linee 471-694)

---

## STEP 3: FixPlanService (3-4h) - MEDIO RISCHIO

### Obiettivo
Estrarre ~300 righe di business logic da `/plan` endpoint.

### Task

- [ ] **3.1** Creare file `src/turbowrap/api/services/fix_plan_service.py`
- [ ] **3.2** Estrarre `_create_fallback_plan()` → `service._create_fallback_plan()`
- [ ] **3.3** Estrarre blocchi da `create_fix_plan()`:
  - [ ] Build prompt (740-758) → `service._build_planning_prompt()`
  - [ ] Run CLI (760-801) → `service._run_planner()`
  - [ ] Parse JSON (803-841) → `service._parse_planner_response()`
  - [ ] Build ExecutionSteps (847-878) → `service._build_execution_steps()`
  - [ ] Build IssueTodos (889-959) → `service._build_issue_todos()`
  - [ ] Save TODO files (961-963) → `service._save_todos()`
  - [ ] Save to DB (965-977) → `service._save_plans_to_db()`
- [ ] **3.4** Snellire endpoint `/plan` → thin controller (~15 righe)
- [ ] **3.5** Rimuovere helper originali da fix.py

### File Coinvolti
- **NUOVO**: `src/turbowrap/api/services/fix_plan_service.py`
- **MODIFICA**: `src/turbowrap/api/routes/fix.py` (linee 697-1042)

---

## STEP 4: Refactor fix_issues() (2-3h) - BASSO RISCHIO

### Obiettivo
Spezzare metodo di 223 righe in metodi privati più piccoli.

### Task

- [ ] **4.1** Estrarre `_emit_session_started()` (linee 143-151)
- [ ] **4.2** Estrarre `_setup_fix_session()` (linee 154-170)
- [ ] **4.3** Estrarre `_run_fix_rounds()` (linee 180-318)
- [ ] **4.4** Estrarre `_execute_single_round()` (dentro loop)
- [ ] **4.5** Estrarre `_process_approved_issues()` (linee 288-312)
- [ ] **4.6** Estrarre `_mark_remaining_failed()` (linee 320-329)
- [ ] **4.7** Semplificare `fix_issues()` → coordinator (~40 righe)

### File Coinvolti
- **MODIFICA**: `src/turbowrap/fix/orchestrator.py` (linee 119-342)

---

## STEP FINALE: Verifica

- [ ] **F.1** Eseguire `uv run ruff check .`
- [ ] **F.2** Eseguire `uv run mypy src/`
- [ ] **F.3** Eseguire `uv run pytest`
- [ ] **F.4** Test manuale: /clarify, /plan, /fix flow completo

---

## Metriche Attese

| File | Prima | Dopo | Riduzione |
|------|-------|------|-----------|
| fix.py | ~1600 righe | ~800 righe | -50% |
| orchestrator.py fix_issues() | 223 righe | ~40 righe | -82% |

---

## File Nuovi da Creare

1. `src/turbowrap/api/services/pending_question_store.py`
2. `src/turbowrap/api/services/fix_clarify_service.py`
3. `src/turbowrap/api/services/fix_plan_service.py`

---

## Funzioni Rimosse da fix.py

- `_format_issues_for_clarify()` → FixClarifyService
- `_format_answers_for_clarify()` → FixClarifyService
- `register_scope_question()` → PendingQuestionStore
- `wait_for_scope_response()` → PendingQuestionStore
- `_create_fallback_plan()` → FixPlanService
- 4 dict globali → PendingQuestionStore

---

## Note

- Ogni step è **indipendente** e può essere committato separatamente
- Se uno step causa regressioni → git revert
- I service sono **additivi** (non rompono l'esistente finché non si fa il passaggio finale)
- Seguire pattern esistente in `fix_session_service.py`
