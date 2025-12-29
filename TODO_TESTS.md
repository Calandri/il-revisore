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

## Da Fare

### 1. Fix Mypy Errors
Gli errori mypy da fixare:
- `test_parsers/base.py:19` - dict senza type params
- `test_scanner.py:175` - return type mancante
- `test_parsers/pytest_parser.py:60,85` - dict senza type params
- `test_task.py:72,74,113,156,160,164` - TaskConfig attributes
- `test_discovery.py:63,196` - type annotations mancanti

### 2. AI Test Analysis Agent
Creare `agents/test_analyzer.md` che:
- Analizza i test di una suite
- Spiega cosa testa ogni test
- Identifica test mancanti / edge cases
- Suggerisce miglioramenti

Route: `POST /htmx/tests/analyze/{suite_id}`

### 3. Altri Framework Parsers
- [ ] Vitest parser (`vitest_parser.py`)
- [ ] Jest parser (`jest_parser.py`)
- [ ] Playwright parser (`playwright_parser.py`)
- [ ] Cypress parser (`cypress_parser.py`)

### 4. Test Execution Improvements
- [ ] WebSocket per streaming output test
- [ ] Polling per aggiornare stato run
- [ ] Mostrare output test in tempo reale
- [ ] Coverage report integration

### 5. AI Test Generation
- [ ] Agent per generare nuovi test
- [ ] Analisi del codice sorgente
- [ ] Suggerimenti test da scrivere

### 6. UI Improvements
- [ ] Filtro per status test (passed/failed/skipped)
- [ ] Grafici coverage nel tempo
- [ ] Badge status ultimo run nella sidebar
- [ ] Notifiche toast quando test completano

## Note
- Discovery usa Gemini Flash 3 via CLI
- Scanner usa AST per Python (più preciso) e regex per JS/TS
- Drawer si apre con bottone blu "Esplora test"
- Bottone "Analizza con AI" nel drawer (da implementare)
