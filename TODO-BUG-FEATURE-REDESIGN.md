# TODO: Redesign BUG + FEATURE Architecture

## Overview
Migrazione da `issues` + `linear_issues` a nuova architettura `bugs` + `features`.

---

## Phase 1: Database Schema

### 1.1 Preparazione
- [ ] Backup database produzione
- [ ] Creare script rollback

### 1.2 Creare Migration Alembic
- [ ] Rinominare tabella `issues` → `bugs`
- [ ] Aggiungere colonne Linear a `bugs`:
  - `linear_id` VARCHAR(100) UNIQUE
  - `linear_identifier` VARCHAR(50)
  - `linear_url` VARCHAR(512)
  - `phase_started_at` DATETIME
  - `attachments` JSON
- [ ] Creare tabella `features`
- [ ] Creare tabella `feature_repositories` (pivot multi-repo)

### 1.3 Migrazione Dati
- [ ] Migrare dati da `linear_issues` → `features`
- [ ] Migrare link da `linear_issue_repository_links` → `feature_repositories`
- [ ] Verificare integrità dati migrati

### 1.4 Cleanup
- [ ] DROP tabella `linear_issue_repository_links`
- [ ] DROP tabella `linear_issues`

---

## Phase 2: Backend Models

### 2.1 Enum Updates
File: `src/turbowrap/db/models/base.py`
- [ ] Rinominare `IssueStatus` → `BugStatus`
- [ ] Creare `FeatureStatus` enum:
  ```
  ANALYSIS, DESIGN, DEVELOPMENT, REVIEW, MERGED, ON_HOLD, CANCELLED
  ```
- [ ] Aggiornare `ISSUE_STATUS_TRANSITIONS` → `BUG_STATUS_TRANSITIONS`
- [ ] Creare `FEATURE_STATUS_TRANSITIONS`

### 2.2 Model Files
- [ ] Rinominare `src/turbowrap/db/models/issue.py` → `bug.py`
- [ ] Refactor classe `Issue` → `Bug`
- [ ] Creare `src/turbowrap/db/models/feature.py`:
  - Classe `Feature`
  - Classe `FeatureRepository`
- [ ] Aggiornare `src/turbowrap/db/models/__init__.py`

---

## Phase 3: Backend API

### 3.1 BUG Routes
File: `src/turbowrap/api/routes/bugs.py` (rinominare da `issues.py`)
- [ ] Rinominare file `issues.py` → `bugs.py`
- [ ] Aggiornare prefix `/issues` → `/bugs`
- [ ] Rinominare classi Response/Request
- [ ] Aggiungere endpoint `POST /bugs/{id}/link-linear`

### 3.2 FEATURE Routes
File: `src/turbowrap/api/routes/features.py` (nuovo)
- [ ] `GET /features` - Lista features
- [ ] `POST /features` - Crea feature
- [ ] `GET /features/{id}` - Dettaglio
- [ ] `PATCH /features/{id}` - Update status/content
- [ ] `POST /features/{id}/qa` - Aggiungi Q&A
- [ ] `POST /features/{id}/repos` - Link repository
- [ ] `DELETE /features/{id}/repos/{repo_id}` - Unlink repository

### 3.3 Services
- [ ] Rinominare riferimenti `Issue` → `Bug` in tutti i services
- [ ] Creare `src/turbowrap/api/services/feature_service.py`
- [ ] Aggiornare `review_stream_service.py` (usa Bug)
- [ ] Aggiornare `fix_session_service.py` (usa Bug)

### 3.4 Router Registration
File: `src/turbowrap/api/main.py`
- [ ] Rimuovere import `issues` router
- [ ] Aggiungere import `bugs` router
- [ ] Aggiungere import `features` router

---

## Phase 4: Linear Integration

### 4.1 Rimuovere Vecchia Integrazione
- [ ] Eliminare `src/turbowrap/api/routes/linear.py` (se specifico per linear_issues)
- [ ] Rimuovere modelli `LinearIssue`, `LinearIssueRepositoryLink`

### 4.2 Nuova Integrazione
- [ ] Sync Linear → Feature (on-demand)
- [ ] Update Feature → Linear state

---

## Phase 5: Review/Fix System

### 5.1 Orchestrator
File: `src/turbowrap/review/orchestrator.py`
- [ ] Aggiornare import `Issue` → `Bug`
- [ ] Aggiornare tutte le query
- [ ] Aggiornare status enum references

### 5.2 Fix Orchestrator
File: `src/turbowrap/fix/orchestrator.py`
- [ ] Aggiornare import `Issue` → `Bug`
- [ ] Aggiornare riferimenti

---

## Phase 6: Frontend

### 6.1 Types
File: `apps/turbowrap-widget/src/types/`
- [ ] Rinominare `Issue` type → `Bug`
- [ ] Creare `Feature` type
- [ ] Creare `FeatureRepository` type

### 6.2 API Hooks
- [ ] Aggiornare hooks per `/bugs`
- [ ] Creare hooks per `/features`

### 6.3 Pages
- [ ] Aggiornare pagina Issues → Bugs
- [ ] Creare pagina Features (kanban view)
- [ ] Creare pagina Feature Detail

### 6.4 Components
- [ ] Aggiornare componenti Issue* → Bug*
- [ ] Creare componenti Feature*

---

## Phase 7: Testing

### 7.1 Unit Tests
- [ ] Test Bug model e transizioni stato
- [ ] Test Feature model e transizioni stato
- [ ] Test FeatureRepository pivot

### 7.2 Integration Tests
- [ ] Test API /bugs endpoints
- [ ] Test API /features endpoints
- [ ] Test multi-repo linking

### 7.3 E2E Tests
- [ ] Test flusso review → bug creation
- [ ] Test flusso fix → bug resolution
- [ ] Test flusso feature lifecycle

---

## Phase 8: Documentation

- [ ] Aggiornare API docs (OpenAPI)
- [ ] Aggiornare README con nuova architettura
- [ ] Documentare stati e transizioni

---

## Notes

### Idempotency Keys
- **BUG**: `repository_id` + `file` + `line` + `code`
- **FEATURE**: `linear_id` (se presente)

### Status Enums

**BugStatus:**
```
OPEN → IN_PROGRESS → RESOLVED → IN_REVIEW → MERGED
     ↘ IGNORED
     ↘ DUPLICATE
```

**FeatureStatus:**
```
ANALYSIS → DESIGN → DEVELOPMENT → REVIEW → MERGED
         ↘ ON_HOLD
         ↘ CANCELLED
```

---

## Rollback Plan

Se qualcosa va storto:
1. Restore database da backup
2. Revert migration
3. Rollback code changes (git revert)
