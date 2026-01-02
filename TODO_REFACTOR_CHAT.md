# Refactoring CLI-CHAT: To-Do List

## Obiettivo
Reorganizzare e centralizzare le utility condivise del modulo `chat_cli` per migliorare la manutenibilità, ridurre la duplicazione di codice e facilitare il riutilizzo in altri moduli.

---

## 1. Creazione Nuove Utility

### 1.1 `src/turbowrap/utils/async_utils.py`
- [ ] Spostare il wrapper `asyncio_timeout` (compatibilità Python < 3.11) da `process_manager.py`
- [ ] Funzione: Fornisce `asyncio.timeout()` su Python 3.10, nativa su Python 3.11+
- [ ] Importare in: `process_manager.py`

### 1.2 `src/turbowrap/utils/env_utils.py`
- [ ] Spostare `_build_env_with_api_keys()` da `process_manager.py`
- [ ] Funzione: Costruisce variabili di ambiente con chiavi API necessarie
- [ ] Riutilizzabile per qualsiasi processo che necessita di API keys (Claude, Gemini, GitHub, etc.)
- [ ] Importare in: `process_manager.py`

### 1.3 `src/turbowrap/utils/hooks.py`
- [ ] Spostare la classe `HookRegistry` e la logica del registro globale da `chat_cli/hooks.py`
- [ ] Funzione: Gestione centralizzata di hook system
- [ ] Permette hook-driven architecture per altri moduli
- [ ] Importare in: `chat_cli/hooks.py`

### 1.4 `src/turbowrap/utils/context_utils.py`
- [ ] Spostare `load_structure_documentation()` da `context_generator.py`
- [ ] Funzione: Carica file di documentazione per il contesto CLI
- [ ] Potenzialmente riutilizzabile per altri sistemi di context generation
- [ ] Importare in: `context_generator.py`

---

## 2. Aggiornamento Utility Esistenti

### 2.1 `src/turbowrap/utils/file_utils.py`
- [ ] Aggiungere/Spostare `_validate_working_dir()` da `process_manager.py`
- [ ] Funzione: Validazione e sicurezza path (controlla directory traversal, esiste, etc.)
- [ ] Centralizza la logica di validazione file system
- [ ] Importare in: `process_manager.py`

---

## 3. Refactoring Moduli chat_cli

### 3.1 `src/turbowrap/chat_cli/process_manager.py`
- [ ] Rimuovere funzioni spostate (asyncio_timeout, build_env_with_api_keys, validate_working_dir)
- [ ] Aggiungere import: `from turbowrap.utils.async_utils import asyncio_timeout`
- [ ] Aggiungere import: `from turbowrap.utils.env_utils import build_env_with_api_keys`
- [ ] Aggiungere import: `from turbowrap.utils.file_utils import validate_working_dir`
- [ ] Verificare che tutti i test passino dopo i cambiamenti

### 3.2 `src/turbowrap/chat_cli/context_generator.py`
- [ ] Rimuovere `load_structure_documentation()`
- [ ] Aggiungere import: `from turbowrap.utils.context_utils import load_structure_documentation`
- [ ] Verificare che tutti i test passino

### 3.3 `src/turbowrap/chat_cli/hooks.py`
- [ ] Mantenere hook specifici della chat (classe ChatHooks con metodi specifici)
- [ ] Importare ed estendere `HookRegistry` da `utils.hooks`
- [ ] Aggiungere import: `from turbowrap.utils.hooks import HookRegistry`
- [ ] Verificare che tutti i test passino

---

## 4. Verifica e Testing

### 4.1 Test Unitari
- [ ] Eseguire test per `chat_cli/` per assicurarsi nessuna regressione
- [ ] Verificare import di nuovi moduli utility
- [ ] Testare che la funzionalità rimane identica

### 4.2 Type Checking
- [ ] Eseguire `mypy` per verificare type safety
- [ ] Assicurarsi che gli import siano corretti nei file utility

### 4.3 Lint
- [ ] Eseguire `ruff` per verificare code quality
- [ ] Eseguire `ruff format` se necessario

---

## 5. Git Commit

### 5.1 Per Ogni Fase
- [ ] Commit per ogni batch di utility (es. "refactor: extract async_utils and env_utils")
- [ ] Commit per ogni batch di refactoring moduli (es. "refactor: update process_manager imports")
- [ ] Message format: `refactor: [scope]` con descrizione dettagliata

### 5.2 Final Push
- [ ] Push a origin/main
- [ ] Verificare che tutti i test CI passino

---

## Status

| Fase | Status | Note |
|------|--------|------|
| Planning | ✅ Completato | Lista e analisi effettuate |
| 1. Creazione Utility | ⏳ Pending | In attesa di inizio |
| 2. Aggiornamento Utility | ⏳ Pending | In attesa di fase 1 |
| 3. Refactoring moduli | ⏳ Pending | In attesa di fase 1-2 |
| 4. Testing | ⏳ Pending | In attesa di fase 3 |
| 5. Git | ⏳ Pending | In attesa di fase 4 |

---

## Benefici Attesi

✅ **Modularità**: Utility riutilizzabili in altri moduli
✅ **DRY**: Elimina duplicazione di codice
✅ **Manutenibilità**: Logica centralizzata, più facile da aggiornare
✅ **Testabilità**: Utility più facili da testare in isolamento
✅ **Scalabilità**: Base solida per aggiungere nuove funzionalità
