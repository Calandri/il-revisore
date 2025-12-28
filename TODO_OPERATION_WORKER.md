# TODO: Operation Worker per Streaming Live

## Obiettivo
Creare un SharedWorker (`operation-worker.js`) per streaming live delle operazioni in Live Tasks.

## Tasks

- [x] 1. **operation_tracker.py** - Aggiungere pub/sub (subscribe, unsubscribe, publish_event)
- [x] 2. **operations.py** - Endpoint SSE `/api/operations/{id}/stream`
- [x] 3. **claude_cli.py** - Pubblicare chunks al tracker durante esecuzione
- [x] 4. **gemini.py** - Pubblicare chunks al tracker durante esecuzione
- [x] 5. **operation-worker.js** - SharedWorker per connessioni SSE
- [x] 6. **base.html** - Inizializzare worker globalmente
- [x] 7. **live_tasks.html** - Usare il worker per streaming
- [ ] 8. **Test end-to-end** - Verificare streaming funziona

## File da Modificare

| File | Path |
|------|------|
| Operation Tracker | `src/turbowrap/core/operation_tracker.py` |
| Operations API | `src/turbowrap/api/routes/operations.py` |
| Claude CLI | `src/turbowrap/llm/claude_cli.py` |
| Gemini CLI | `src/turbowrap/llm/gemini.py` |
| Operation Worker | `src/turbowrap/api/static/js/operation-worker.js` (NEW) |
| Base Template | `src/turbowrap/api/templates/base.html` |
| Live Tasks | `src/turbowrap/api/templates/pages/live_tasks.html` |

## Pattern di Riferimento

Usare lo stesso pattern di `chat-worker.js`:
- SharedWorker mantiene connessione SSE
- Buffer output per pagine disconnesse
- Broadcast a tutte le pagine connesse
- State sync quando la pagina torna

## Note

- Piano completo in: `/Users/niccolocalandri/.claude/plans/shimmying-swinging-corbato.md`
- Commit iniziale: 57d59dc
