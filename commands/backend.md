# /backend - Start Backend Dev Server

Start the backend development server for this repository and provide access URL.

## Step 1: Detect Backend Project

Analyze the repository structure to identify:
- **Language/Framework**:
  - Python: FastAPI, Django, Flask (look for `requirements.txt`, `pyproject.toml`, `Pipfile`)
  - Node.js: Express, NestJS, Fastify (look for `package.json` with server deps)
  - Go: Gin, Echo, Fiber (look for `go.mod`)
  - Rust: Actix, Axum (look for `Cargo.toml`)
- **Directory structure**: Check `/backend`, `/server`, `/api`, `/apps/api`, `/packages/api`, or root

## Step 2: Setup Environment

1. **Virtual environment** (Python):
   ```bash
   # Check for existing venv
   source .venv/bin/activate  # or venv/bin/activate
   # Or create if missing
   python -m venv .venv && source .venv/bin/activate
   ```

2. **Install dependencies**:
   - Python: `pip install -r requirements.txt` or `pip install -e .`
   - Node.js: `pnpm install` / `npm install`
   - Go: `go mod download`

3. **Environment variables**:
   - Check for `.env.example` → copy to `.env` if missing
   - Verify required variables are set

## Step 3: Database (if needed)

Check if the backend needs a database:
- Look for database connection strings in config
- Run migrations if needed: `alembic upgrade head`, `prisma migrate`, etc.
- Skip if using SQLite or external DB already configured

## Step 4: Start Dev Server

Find and execute the correct start command:

**Python (FastAPI/Django/Flask)**:
```bash
# FastAPI with uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
# or from package.json/pyproject.toml scripts
```

**Node.js**:
```bash
pnpm dev  # or npm run dev
```

- Run in background to monitor output
- Note the port (usually 8000, 8080, 3001, 5000)

## Step 5: Monitor & Fix

Watch the logs for 10-15 seconds:
1. **Import errors**: Fix missing imports or install packages
2. **Database connection**: Check connection string, ensure DB is running
3. **Port conflicts**: Kill existing process or use different port
4. **Missing environment variables**: Add to `.env` file
5. **Migration errors**: Run pending migrations

If errors are fixable, fix them and restart the server.

## Step 6: Verify & Provide URL

Once running without errors:
1. Confirm the server is responding (look for "Uvicorn running", "Listening on", etc.)
2. Test a health endpoint if available: `/health`, `/api/health`, `/`
3. Provide the public URL

**Public base URL**: `https://turbo-repo.com`

Common port mappings:
| Framework | Default Port | Public URL |
|-----------|-------------|------------|
| FastAPI | 8000 | https://turbo-repo.com:8000 |
| Django | 8000 | https://turbo-repo.com:8000 |
| Flask | 5000 | https://turbo-repo.com:5000 |
| Express | 3001 | https://turbo-repo.com:3001 |
| NestJS | 3000 | https://turbo-repo.com:3000 |

## Response Format

```markdown
## Backend Dev Server

**Stato**: [Avviato | Errore | Corretto e Riavviato]
**Framework**: [FastAPI/Django/Express/etc.]
**Linguaggio**: [Python/Node.js/Go]
**Directory**: [path del backend]
**Comando**: [comando eseguito]
**Porta**: [numero porta]

### URL Pubblico
- **Base URL**: https://turbo-repo.com:[PORT]
- **API Docs** (se disponibile): https://turbo-repo.com:[PORT]/docs
- **Health Check**: https://turbo-repo.com:[PORT]/health

### Log (ultime righe)
[mostra le ultime 15-20 righe di log]

### Problemi Risolti (se presenti)
- [elenco dei problemi risolti automaticamente]

### Endpoints Principali
- GET /api/... - [descrizione]
- POST /api/... - [descrizione]

### Note
[eventuali avvisi o informazioni utili]
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: Keep the server running in background - do not exit the process.**
**IMPORTANT: Bind to 0.0.0.0 to allow external access, not just localhost.**
