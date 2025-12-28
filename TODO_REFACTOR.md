# 📄 TODO: Refactoring & Centralizzazione Codice

Questo documento elenca le attività necessarie per centralizzare il codice duplicato e ridurre il debito tecnico in `src/turbowrap`.

## 🛠️ 1. Utilities Core (File & Common)
Obiettivo: Avere una "Single Source of Truth" per operazioni su file e conteggio token.

- [x] **Unificare `file_utils.py`**:
    - [x] Migrare logica da `review/utils/file_utils.py` a `utils/file_utils.py`.
    - [ ] Aggiornare tutte le importazioni nel codebase per puntare a `utils/file_utils.py`.
    - [ ] Eliminare `review/utils/file_utils.py`.

- [ ] **Refactoring `structure_generator.py`**:
    - [ ] Rimuovere costanti duplicate (`IGNORE_DIRS`, estensioni).
    - [ ] Usare `file_utils.should_ignore` invece dell'implementazione locale.
    - [ ] Usare `file_utils.calculate_tokens` invece del wrapper locale.

- [ ] **Refactoring `chat_cli/hooks.py`**:
    - [ ] Usare `file_utils` per il conteggio token invece di logica custom.

## 🐙 2. Git Operations Centralization
Obiettivo: Eliminare la duplicazione massiccia tra `utils/git_utils.py` e `api/routes/git.py`.

- [x] **Unificare Modelli Dati**:
    - [x] Fondere `CommitInfo` (presente in entrambi i file con campi simili).
    - [x] Fondere `GitStatus` (presente in entrambi).
    - [x] Spostare tutti i modelli condivisi in `utils/git_utils.py` o un nuovo `models/git.py`.

- [x] **Centralizzare Esecuzione Comandi**:
    - [x] Refactorizzare `utils/git_utils.py` per esporre una funzione robusta `run_git_command` (che gestisce auth, timeout, env variables).
    - [x] Aggiornare `api/routes/git.py` per usare questa funzione invece di implementare `subprocess.run` internamente.
    - [x] Aggiornare `api/routes/repos.py` per usare la stessa utility.

- [x] **Standardizzare Risoluzione Conflitti AI**:
    - [x] Analisi: `git_utils.py` usa Claude CLI, `api/routes/git.py` usa Gemini Flash.
    - [x] Creare una strategia unificata (es. `AbstractConflictResolver`) in `utils/git_utils.py` o `llm/operations`.
    - [x] Implementare strategie concrete per Claude e Gemini.
    - [x] Aggiornare entrambi i consumatori per usare la strategia centralizzata.

## 🧠 3. LLM Client Abstraction
Obiettivo: Evitare l'inizializzazione diretta di client SDK sparsi per il codice.

- [ ] **Refactoring Reviewers**:
    - [ ] `ClaudeReviewer` (`review/reviewers/claude_reviewer.py`) istanzia `anthropic.Anthropic` direttamente.
    - [ ] Aggiornare per usare il wrapper centralizzato in `llm/claude.py` (se supporta le funzionalità necessarie come il caching o thinking mode).
    - [ ] Se il wrapper non supporta "Thinking Mode", estenderlo invece di bypassarlo.

- [ ] **Gemini Integrazione**:
    - [ ] Verificare che `GeminiCLI` usato in `api/routes/git.py` sia allineato con `llm/gemini.py`.

## 🧹 4. Linting & Validation
Obiettivo: Estrarre logica di validazione codice.

- [ ] **Validazione Centralizzata**:
    - [ ] Estrarre la logica di run di `ruff` da `chat_cli/hooks.py`.
    - [ ] Creare `utils/lint_utils.py` o `tools/linter.py`.
    - [ ] Riutilizzare questa logica in `fix/validator.py` (se applicabile).

---
*Piano generato il 2025-12-28 basato sull'analisi della struttura corrente.*
