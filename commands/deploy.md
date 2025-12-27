# /deploy - Deploy to Staging

Deploy the current branch to the staging environment.

**IMPORTANT**: Use the branch specified in the context above. First verify you're on the correct branch:
```bash
git checkout <branch-from-context>
git pull origin <branch-from-context>
```

## Pre-Deploy Checklist

### Step 1: Verify Branch State
```bash
git branch --show-current
git status
git log origin/main..HEAD --oneline
```

Check:
- Correct branch is checked out
- All changes are committed
- Branch is pushed to remote

### Step 2: Run Pre-Deploy Checks
```bash
# Run tests
pytest -v
# or
npm test

# Run linting
ruff check .
# or
npx eslint .

# Type checking
mypy .
# or
npx tsc --noEmit
```

All checks must pass before deploying.

### Step 3: Identify Deploy Method
Check project for deployment configuration:
- AWS: SAM, CDK, Terraform
- Docker: docker-compose, Kubernetes
- Vercel/Netlify: Git-based deploy
- Custom: Makefile, scripts

### Step 4: Execute Deployment

**AWS SAM example:**
```bash
sam build
sam deploy --config-env staging
```

**Docker example:**
```bash
docker-compose -f docker-compose.staging.yml up -d --build
```

**Git-based (Vercel/Netlify):**
```bash
git push origin <branch-name>
# Automatic deploy triggered
```

### Step 5: Verify Deployment
```bash
# Check service health
curl -s https://staging.example.com/health | jq

# Check logs
aws logs tail /aws/staging/app --since 5m
```

## Response Format

```markdown
## Deploy to Staging

**Branch**: {branch_name}
**Target**: Staging environment
**Metodo**: AWS SAM / Docker / Git-push

### Pre-Deploy Check
| Check | Stato |
|-------|-------|
| ✓ Branch aggiornato | OK |
| ✓ Test passati | OK (45 passed) |
| ✓ Lint pulito | OK |
| ✓ Type check | OK |

### Deployment
```bash
sam build && sam deploy --config-env staging
```

### Risultato
- **Status**: ✓ Deployed successfully
- **URL**: https://staging.example.com
- **Versione**: abc1234
- **Tempo**: 2m 34s

### Verifica Post-Deploy
```bash
curl -s https://staging.example.com/health
```
```json
{"status": "healthy", "version": "abc1234"}
```

### Prossimi Passi
1. Verifica manualmente le nuove funzionalità
2. Monitora i log per errori
3. Se tutto OK, procedi con la PR per produzione
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: NEVER deploy to production - this command is for staging only.**
**IMPORTANT: All pre-deploy checks must pass before proceeding with deployment.**
**IMPORTANT: Always verify the deployment succeeded before reporting completion.**
