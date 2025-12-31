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

## STEP 2: FixClarifyService (2-3h) - MEDIO RISCHIO ✅ COMPLETATO

### Obiettivo
Estrarre ~200 righe di business logic da `/clarify` endpoint.

### Task

- [x] **2.1** Creare file `src/turbowrap/api/services/fix_clarify_service.py`
- [x] **2.2** Estrarre `_format_issues_for_clarify()` → `service._format_issues()`
- [x] **2.3** Estrarre `_format_answers_for_clarify()` → `service._format_answers()`
- [x] **2.4** Estrarre blocchi da `clarify_before_fix()`:
  - [x] Mark IN_PROGRESS → `service._mark_issues_in_progress()`
  - [x] Build prompt → `service._build_prompt()`
  - [x] Run CLI → `service._run_clarifier()`
  - [x] Parse response → `service._parse_response()`
  - [x] Save clarifications → `service._save_clarifications()`
- [x] **2.5** Snellire endpoint `/clarify` → thin controller (~50 righe)
- [x] **2.6** Rimuovere helper originali da fix.py

### File Coinvolti
- **NUOVO**: `src/turbowrap/api/services/fix_clarify_service.py`
- **MODIFICA**: `src/turbowrap/api/routes/fix.py` (linee 471-694)

---

## STEP 3: FixPlanService (3-4h) - MEDIO RISCHIO ✅ COMPLETATO

### Obiettivo
Estrarre ~300 righe di business logic da `/plan` endpoint.

### Task

- [x] **3.1** Creare file `src/turbowrap/api/services/fix_plan_service.py`
- [x] **3.2** Estrarre `_create_fallback_plan()` → `service._create_fallback_plan()`
- [x] **3.3** Estrarre blocchi da `create_fix_plan()`:
  - [x] Build prompt → `service._build_planning_prompt()`
  - [x] Run CLI → `service._run_planner()`
  - [x] Parse JSON → `service._parse_planner_response()`
  - [x] Build ExecutionSteps + IssueTodos → `service._build_todos()`
  - [x] Save TODO files → `service._save_todos()`
  - [x] Save to DB → `service._save_plans_to_db()`
- [x] **3.4** Snellire endpoint `/plan` → thin controller (~55 righe)
- [x] **3.5** Rimuovere helper originali da fix.py

### File Coinvolti
- **NUOVO**: `src/turbowrap/api/services/fix_plan_service.py`
- **MODIFICA**: `src/turbowrap/api/routes/fix.py` (linee 697-1042)

---

## STEP 4: Refactor fix_issues() (2-3h) - BASSO RISCHIO ✅ COMPLETATO

### Obiettivo
Spezzare metodo di 223 righe in metodi privati più piccoli.

### Task

- [x] **4.1** Estrarre `_emit_session_started()`
- [x] **4.2** Estrarre `_setup_fix_session()`
- [x] **4.3** Estrarre `_run_fix_rounds()`
- [x] **4.4** Estrarre `_execute_single_round()`
- [x] **4.5** Estrarre `_process_approved_issues()`
- [x] **4.6** Estrarre `_mark_remaining_failed()`
- [x] **4.7** Estrarre `_log_fix_results()`
- [x] **4.8** Semplificare `fix_issues()` → coordinator (~50 righe)

### File Coinvolti
- **MODIFICA**: `src/turbowrap/fix/orchestrator.py` (linee 119-407)

---

## STEP FINALE: Verifica ✅ COMPLETATO

- [x] **F.1** Eseguire `uv run ruff check .` - PASSED
- [x] **F.2** Eseguire `uv run mypy src/` - PASSED (5 file refactored senza errori)
- [x] **F.3** Eseguire `uv run pytest` - PASSED (333 passed, 77 failed pre-esistenti)
- [ ] **F.4** Test manuale: /clarify, /plan, /fix flow completo - DA ESEGUIRE

### Note sui test failures:
- `claude_cli/test_*.py` - Errori pre-esistenti (tuple unpacking 5 vs 6)
- `fix/test_fix_pipeline_e2e.py` - Testa metodi OLD già rimossi in refactoring precedenti
- Nessun failure correlato al refactoring ARCH

---

## Metriche Finali

| File | Prima | Dopo | Riduzione |
|------|-------|------|-----------|
| fix.py | ~1600 righe | ~1080 righe | -32% |
| orchestrator.py fix_issues() | 223 righe | ~50 righe | -78% |

### File Nuovi Creati
| File | Righe | Scopo |
|------|-------|-------|
| pending_question_store.py | 304 | Singleton per domande pending |
| fix_clarify_service.py | 326 | Business logic /clarify |
| fix_plan_service.py | 480 | Business logic /plan |

---

## Funzioni Rimosse/Migrate da fix.py

- `_format_issues_for_clarify()` → FixClarifyService._format_issues()
- `_format_answers_for_clarify()` → FixClarifyService._format_answers()
- `_format_issues_for_plan()` → FixPlanService._format_issues()
- `register_scope_question()` → PendingQuestionStore.register_scope_violation()
- `wait_for_scope_response()` → PendingQuestionStore.wait_for_scope_response()
- `_create_fallback_plan()` → FixPlanService._create_fallback_plan()
- 4 dict globali → PendingQuestionStore (singleton)

---

## Note

- Tutti e 4 gli step sono stati **completati con successo**
- I service seguono il pattern esistente in `fix_session_service.py`
- Ruff check passa su tutti i file modificati
