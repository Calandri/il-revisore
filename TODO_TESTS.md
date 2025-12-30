# TODO - Test Feature (TurboWrap)

## Completato
- [x] DB Models (TestSuite, TestRun, TestCase)
- [x] Alembic migration
- [x] API routes /api/tests/*
- [x] HTMX routes per UI
- [x] Pagina tests.html con dati reali
- [x] TestTask executor per eseguire test in background
- [x] pytest parser (JSON + plain text)
- [x] test-discoverer agent (Gemini Flash 3)
- [x] test_scanner.py - AST scanner per Python, regex per JS/TS
- [x] Drawer dettagli suite con lista file/test
- [x] Code viewer con highlight linea
- [x] Fix Mypy Errors - type: ignore per SQLAlchemy Column assignments
- [x] AI Test Analysis Agent (`agents/test_analyzer.md`)
- [x] Route `/htmx/tests/analyze/{suite_id}` con Gemini Flash
- [x] Template `test_ai_analysis.html` con score e breakdown
- [x] Campo `test_count` in TestSuite per conteggio persistente
- [x] Migration Alembic per `test_count` e `ai_analysis`

## Da Fare

### 1. Altri Framework Parsers
- [ ] Vitest parser (`vitest_parser.py`)
- [ ] Jest parser (`jest_parser.py`)
- [ ] Playwright parser (`playwright_parser.py`)
- [ ] Cypress parser (`cypress_parser.py`)

### 2. Test Execution Improvements
- [ ] WebSocket per streaming output test
- [ ] Polling per aggiornare stato run
- [ ] Mostrare output test in tempo reale
- [ ] Coverage report integration

### 3. AI Test Generation (via Chat)
- [x] Slash command `/create_test` per generare test via chat
- [x] Script `test_tool.py` per operazioni git/test
- [ ] UI button nel drawer per avviare generazione
- [ ] Integrazione con test_enhancer.md agent

### 4. UI Improvements
- [ ] Filtro per status test (passed/failed/skipped)
- [ ] Grafici coverage nel tempo
- [ ] Badge status ultimo run nella sidebar
- [ ] Notifiche toast quando test completano

## Note
- Discovery usa Gemini Flash 3 via CLI
- Scanner usa AST per Python (più preciso) e regex per JS/TS
- Drawer si apre con bottone blu "Esplora test"
- Bottone "Analizza Test" nel drawer chiama `/htmx/tests/analyze/{suite_id}`
- AI Analysis fornisce score 1-10 su 6 dimensioni + suggerimenti
- **`/create_test`**: Comando chat per generare test. Uso: `/create_test src/module.py`
  - Legge il file sorgente
  - Chiede tipo test e scenari da coprire
  - Genera test completi (pytest/vitest/jest)
  - Crea branch, scrive file, esegue test
