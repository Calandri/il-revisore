# Piano di Refactoring: Centralizzazione Utils e Rimozione Codice Ridondante

Questo documento analizza lo stato attuale della repository e propone un piano dettagliato per centralizzare il codice duplicato e migliorare l'organizzazione, con focus sulla directory `src/turbowrap`.

## 1. Analisi della Situazione Attuale

Sono state identificate diverse aree di duplicazione e frammentazione del codice, in particolare nelle "utility functions" che dovrebbero essere condivise.

### Aree di Duplicazione Identificate

1.  **File Utilities (`file_utils.py`) frammentate**:
    *   `src/turbowrap/utils/file_utils.py`: Contiene funzioni standalone (`calculate_tokens`, `discover_files`) e costanti (`IGNORE_DIRS`, `BE_EXTENSIONS`).
    *   `src/turbowrap/review/utils/file_utils.py`: Contiene una classe `FileUtils` con metodi statici (`read_file`, `get_language`, `count_lines`, `create_code_snippet`).
    *   **Problema**: Due file con lo stesso nome in path diversi che fanno cose simili. Manca una "Single Source of Truth".

2.  **Structure Generator (`structure_generator.py`) ridondante**:
    *   Ridefinisce costanti già presenti in `file_utils.py`: `IGNORE_DIRS`, `IGNORE_FILES`, `BE_EXTENSIONS`, `FE_EXTENSIONS`.
    *   Ridefinisce logica di conteggio token (`count_tokens` wrapper).
    *   Ridefinisce logica di `should_ignore`.
    *   Ridefinisce logica di `detect_repo_type`.

3.  **Chat Hooks (`hooks.py`)**:
    *   Ridefinisce parzialmente logica di conteggio token (anche se importa correttamente, il wrapper potrebbe essere semplificato).
    *   Contiene logica di linting inline che potrebbe essere estratta.

4.  **Git Utilities**:
    *   Sembra che `git_utils.py` sia stato parzialmente centralizzato in `src/turbowrap/utils/git_utils.py`, ma rimangono commenti e tracce del vecchio codice ("Classes merged from review/utils...").

## 2. Piano di Azione Dettagliato

### Fase 1: Unificazione di `file_utils.py`

L'obiettivo è avere un unico modulo `src/turbowrap/utils/file_utils.py` potente e completo.

**Azioni:**
1.  **Migrare** le funzioni utili da `src/turbowrap/review/utils/file_utils.py` a `src/turbowrap/utils/file_utils.py`.
    *   Convertire i metodi statici di `FileUtils` in funzioni standalone per consistenza con il file di destinazione (approccio funzionale Pythonico).
    *   Funzioni da migrare: `read_lines`, `get_file_hash`, `get_extension`, `is_text_file` (implementazione migliore basata su set esteso), `get_language` (mappa estesa), `create_code_snippet`.
2.  **Eliminare** il file `src/turbowrap/review/utils/file_utils.py` una volta completata la migrazione.
3.  **Aggiornare** tutte le importazioni nel codice che puntavano al vecchio percorso.

### Fase 2: Refactoring di `structure_generator.py`

`StructureGenerator` deve agire come un consumatore di utility, non ridefinirle.

**Azioni:**
1.  **Importare** costanti da `src/turbowrap/utils/file_utils.py`: `IGNORE_DIRS`, `IGNORE_FILES`, `BE_EXTENSIONS`, `FE_EXTENSIONS`.
2.  **Sostituire** la logica locale `should_ignore` con quella importata.
3.  **Sostituire** la logica `repo_type` interna con `detect_repo_type` importata.
4.  **Rimuovere** definizioni ridondanti all'inizio del file.

### Fase 3: Standardizzazione Token Counting e Linting

**Azioni:**
1.  Verificare che **tutti** i punti del codice usino `src/turbowrap/utils/file_utils.py` per il conteggio token (garantendo coerenza con `tiktoken`).
2.  Valutare l'estrazione della logica di linting da `hooks.py` in un modulo `src/turbowrap/utils/linting_utils.py` o simile, se si prevede di usarla altrove (es. nella pipeline di review).

### Fase 4: Pulizia Finale

**Azioni:**
1.  Rimuovere commenti obsoleti come `# Classes merged from ...` in `git_utils.py`.
2.  Verificare `src/turbowrap/review/reviewers/utils/` per assicurarsi che contenga solo utility *specifiche* per i reviewer (es. parsing JSON LLM) e spostare utility generiche in `src/turbowrap/utils` o `src/turbowrap/llm/utils`.

## Vantaggi del Piano

*   **Manutenibilità**: Modificare la lista di `IGNORE_DIRS` in un solo posto aggiorna tutto il sistema.
*   **Chiarezza**: Semplifica la navigazione del codice; le utility sono dove ci si aspetta che siano.
*   **Riduzione Debito Tecnico**: Elimina codice copia-incollato che tende a divergere nel tempo.

## Esecuzione Immediata

Se approvi questo piano, posso iniziare immediatamente con la **Fase 1** e unificare `file_utils.py`.
