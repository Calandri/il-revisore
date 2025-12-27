# /frontend - Start Frontend Dev Server

Start the frontend development server for this repository and provide access URL.

## Step 1: Detect Frontend Project

Analyze the repository structure to identify:
- **Package manager**: Check for `pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`, `bun.lockb`
- **Framework**: React, Vue, Next.js, Nuxt, Vite, Angular, Svelte, Astro
- **Monorepo structure**: Check if frontend is in `/frontend`, `/client`, `/web`, `/apps/web`, `/packages/frontend`

## Step 2: Install Dependencies (if needed)

Before starting, ensure dependencies are installed:
```bash
# Use the detected package manager
pnpm install  # or npm install / yarn install
```

## Step 3: Start Dev Server

Find and execute the correct start command from `package.json`:
- Priority order: `dev`, `start:dev`, `serve`, `start`
- Run in background so you can monitor output
- Note the port from the output (usually 3000, 5173, 8080, 4200)

## Step 4: Monitor & Fix

Watch the logs for 10-15 seconds:
1. **Compilation errors**: Fix TypeScript/ESLint errors if simple
2. **Missing modules**: Run install again or install specific package
3. **Port conflicts**: Kill existing process or use different port
4. **Environment variables**: Check for missing `.env` files, create from `.env.example`

If errors are fixable, fix them and restart the server.

## Step 5: Verify & Provide URL

Once running without errors:
1. Confirm the server is responding (check for "ready" or "compiled successfully" message)
2. Provide the public URL

**Public base URL**: `https://turbo-repo.com`

Common port mappings:
| Framework | Default Port | Public URL |
|-----------|-------------|------------|
| Vite | 5173 | https://turbo-repo.com:5173 |
| Next.js | 3000 | https://turbo-repo.com:3000 |
| Create React App | 3000 | https://turbo-repo.com:3000 |
| Vue CLI | 8080 | https://turbo-repo.com:8080 |
| Angular | 4200 | https://turbo-repo.com:4200 |

## Response Format

```markdown
## Frontend Dev Server

**Stato**: [Avviato | Errore | Corretto e Riavviato]
**Framework**: [nome framework rilevato]
**Package Manager**: [pnpm/npm/yarn]
**Directory**: [path del frontend]
**Comando**: [comando eseguito]
**Porta**: [numero porta]

### URL Pubblico
https://turbo-repo.com:[PORT]

### Log (ultime righe)
[mostra le ultime 15-20 righe di log]

### Problemi Risolti (se presenti)
- [elenco dei problemi risolti automaticamente]

### Note
[eventuali avvisi o informazioni utili]
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: Keep the server running in background - do not exit the process.**
