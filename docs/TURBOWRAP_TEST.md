# TurboWrapTest - AI-Powered Test Framework

## Overview

TurboWrapTest è un framework di testing basato su AI che wrappa i test tramite **GeminiCLI** o **ClaudeCLI**.
Ogni test è definito da un file agent `.md` che contiene le istruzioni complete per l'esecuzione.

**Default CLI**: Gemini Flash (più economico e veloce)
**Alternative**: Claude CLI (per test più complessi)

---

## Struttura Agent File

Ogni test agent è salvato in `tests/agents/<nome>.md` con struttura YAML + Markdown:

```markdown
---
name: test_user_creation
description: Test creazione utente via API
framework: turbowrap
cli: gemini  # oppure 'claude'
timeout: 300  # secondi
tags:
  - api
  - users
  - integration
requires_db: true
db_cleanup: true  # pulisce automaticamente i record creati
created_at: 2025-01-15
author: nome_autore
---

# Test: Creazione Utente via API

## Obiettivo
Verificare che l'endpoint POST /api/users crei correttamente un nuovo utente.

## Prerequisiti
- Database accessibile
- API server running su localhost:8000

## Setup
Prima di eseguire il test, assicurarsi che:
1. Non esistano utenti con email `test@example.com`
2. Le tabelle `users` e `user_sessions` siano accessibili

## Test Steps

### Step 1: Preparazione dati
Crea un payload JSON con:
- email: test_turbowrap_<timestamp>@example.com
- name: Test User
- role: user

### Step 2: Chiamata API
Esegui POST su /api/users con il payload.
Verifica:
- Status code 201
- Response contiene `id` valido
- Response contiene `created_at`

### Step 3: Verifica Database
Controlla nel database che:
- Record utente esiste
- Email corrisponde
- Timestamps sono corretti

### Step 4: Cleanup
**IMPORTANTE - Modifiche Database:**
Questo test crea i seguenti record:
- 1 record in tabella `users`

Il test DEVE eliminare questi record al termine (success o failure).

## Expected Results
- API ritorna 201 Created
- Utente salvato correttamente in DB
- Nessun record orfano dopo cleanup

## Files di Contesto
<!-- File che l'agent deve leggere per capire il contesto -->
- src/turbowrap/api/routes/users.py
- src/turbowrap/db/models.py

## Notes
Eventuali note aggiuntive per l'agent.
```

---

## Frontmatter YAML - Campi

| Campo | Tipo | Required | Descrizione |
|-------|------|----------|-------------|
| `name` | string | ✅ | Identificativo univoco del test |
| `description` | string | ✅ | Breve descrizione |
| `framework` | string | ✅ | Sempre `turbowrap` |
| `cli` | string | ❌ | `gemini` (default) o `claude` |
| `timeout` | number | ❌ | Timeout in secondi (default: 300) |
| `tags` | array | ❌ | Tags per categorizzazione |
| `requires_db` | boolean | ❌ | Se il test accede al database |
| `db_cleanup` | boolean | ❌ | Se pulire automaticamente il DB |
| `created_at` | string | ❌ | Data creazione |
| `author` | string | ❌ | Autore del test |

---

## Sezioni Markdown Obbligatorie

### 1. `## Obiettivo`
Cosa deve verificare il test. Chiaro e conciso.

### 2. `## Test Steps`
Passi sequenziali che l'agent deve eseguire. Ogni step deve essere verificabile.

### 3. `## Expected Results`
Risultati attesi. L'agent confronterà i risultati reali con questi.

### 4. `## Files di Contesto` (opzionale ma consigliato)
Lista di file che l'agent deve leggere per comprendere il contesto del codice.

---

## Database State Management

**REGOLA FONDAMENTALE**: Se un test modifica il database, DEVE:

1. **Documentare esplicitamente** quali record crea/modifica
2. **Implementare cleanup** che elimina i record creati
3. **Essere idempotente** - eseguibile più volte senza side effects

### Pattern consigliato

```markdown
## Database Changes
Questo test effettua le seguenti modifiche:

### Record Creati
- Tabella `users`: 1 record con email pattern `test_tw_*`
- Tabella `sessions`: 1 record collegato all'utente

### Cleanup Strategy
Al termine del test (success o failure):
1. DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_tw_%')
2. DELETE FROM users WHERE email LIKE 'test_tw_%'
```

---

## Output JSON

Ogni test produce un output JSON standardizzato salvato su S3:

```json
{
  "test_name": "test_user_creation",
  "status": "passed",  // "passed" | "failed" | "error" | "timeout"
  "executed_at": "2025-01-15T10:30:00Z",
  "duration_seconds": 45.2,
  "cli_used": "gemini",
  "steps": [
    {
      "name": "Preparazione dati",
      "status": "passed",
      "duration_ms": 150
    },
    {
      "name": "Chiamata API",
      "status": "passed",
      "duration_ms": 1200,
      "details": {
        "status_code": 201,
        "response_time_ms": 1180
      }
    }
  ],
  "errors": [],  // Array di errori se presenti
  "improvements": [
    "Considerare l'aggiunta di test per email duplicate",
    "Aggiungere validazione formato email"
  ],
  "db_cleanup_status": "completed",
  "s3_logs_path": "s3://bucket/turbowrap-tests/2025/01/15/test_user_creation_abc123.json"
}
```

### Campi Output

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `status` | string | Stato finale: passed/failed/error/timeout |
| `errors` | array | Lista errori riscontrati |
| `improvements` | array | Suggerimenti AI per migliorare il test o il codice |
| `steps` | array | Dettaglio esecuzione per ogni step |
| `db_cleanup_status` | string | Stato cleanup DB: completed/failed/skipped |

---

## Workflow Completo

### 1. Creazione Test (via Chat CLI)

```
User: /test_turbowrap

Agent: Ciao! Creiamo insieme un nuovo TurboWrapTest.
       Che tipo di test vuoi creare?

       1. API Test (endpoint HTTP)
       2. Database Test (query/mutations)
       3. Integration Test (multi-componente)
       4. Custom

User: 1

Agent: Ottimo! Quale endpoint vuoi testare?

User: POST /api/repositories

Agent: Quali verifiche vuoi fare?
       - Status code
       - Response body structure
       - Database state
       - ...

[L'agent guida l'utente e genera il file .md]
```

### 2. Visualizzazione (UI)

Pagina `/tests` con due tab:
- **Test Suites**: Test tradizionali (pytest, vitest, jest)
- **TurboWrapTest**: Test AI-powered

### 3. Esecuzione (UI)

1. Utente seleziona un TurboWrapTest
2. Toggle per scegliere CLI (Gemini/Claude)
3. Click "Run Test"
4. Progress in real-time via SSE
5. Risultato JSON visualizzato

### 4. Storage

- **Agent files**: `tests/agents/*.md` (git tracked)
- **Results**: S3 `turbowrap-tests/{year}/{month}/{day}/{test_name}_{uuid}.json`
- **Logs**: S3 `turbowrap-tests-logs/...`

---

## Best Practices

### DO ✅

- Usare nomi descrittivi: `test_user_creation_with_valid_email`
- Documentare OGNI modifica database
- Includere cleanup esplicito
- Specificare file di contesto rilevanti
- Usare timestamp nei dati test per unicità

### DON'T ❌

- Non creare test che dipendono da stato esterno
- Non hardcodare ID o valori che cambiano
- Non lasciare record orfani nel database
- Non assumere ordine di esecuzione tra test

---

## CLI Selection Guide

| Scenario | CLI Consigliato | Motivo |
|----------|-----------------|--------|
| Test semplici API | Gemini | Veloce, economico |
| Test con logica complessa | Claude | Reasoning migliore |
| Test database multi-step | Claude | Gestisce meglio le transazioni |
| Test di validazione | Gemini | Sufficiente per check semplici |
| Test con file grandi | Claude | Context window maggiore |

---

## Integrazione con Sistema Esistente

### Database Models

I risultati sono salvati nella tabella `test_runs` con:
- `type = 'turbowrap'`
- `agent_file` = path al file .md
- `result_s3_path` = path S3 del JSON output
- `cli_type` = 'gemini' | 'claude'

### API Endpoints

- `POST /api/tests/turbowrap/run/{test_name}` - Esegue test
- `GET /api/tests/turbowrap/results/{run_id}` - Risultati
- `GET /api/tests/turbowrap/list` - Lista test disponibili

### Events (SSE)

Durante l'esecuzione, eventi via SSE:
- `test_started`
- `step_started`
- `step_completed`
- `test_completed`
- `test_failed`

---

## Esempio Minimale

```markdown
---
name: test_health_check
description: Verifica endpoint health
framework: turbowrap
cli: gemini
timeout: 60
---

# Test: Health Check Endpoint

## Obiettivo
Verificare che GET /health risponda correttamente.

## Test Steps

### Step 1: Chiamata endpoint
GET /health
Verifica status 200.

### Step 2: Verifica response
Response deve contenere:
- `status: "healthy"`
- `timestamp` presente

## Expected Results
- Status 200
- JSON valido con status "healthy"
```

---

## Troubleshooting

### Test timeout
- Aumentare `timeout` nel frontmatter
- Verificare che le risorse siano accessibili
- Controllare logs S3 per dettagli

### Cleanup fallito
- Verificare permessi database
- Controllare che le query di cleanup siano corrette
- Usare pattern univoci (timestamp) per identificare record test

### CLI error
- Verificare API keys configurate
- Controllare rate limits
- Provare switch a CLI alternativo
