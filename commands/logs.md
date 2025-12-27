# /logs - Import Server Logs

Fetch and analyze server logs from the deployment environment.

## Steps

### Step 1: Identify Log Source
Check the project for deployment configuration:
- AWS: CloudWatch, ECS, Lambda
- Docker: `docker logs`
- Kubernetes: `kubectl logs`
- PM2: `pm2 logs`
- Systemd: `journalctl`

### Step 2: Fetch Recent Logs
Retrieve logs from the last 30 minutes or last 100 lines.

**AWS CloudWatch example:**
```bash
aws logs tail /aws/lambda/function-name --since 30m --format short
```

**Docker example:**
```bash
docker logs --tail 100 --timestamps container-name
```

**Local development:**
```bash
# Check common log locations
tail -100 logs/app.log
tail -100 /var/log/app/error.log
```

### Step 3: Parse and Categorize
Group log entries by:
- **ERROR**: Application errors, exceptions
- **WARN**: Warnings, deprecations
- **INFO**: Normal operations
- **DEBUG**: Detailed debugging info

### Step 4: Analyze Patterns
Look for:
- Repeated errors (same message multiple times)
- Error frequency (errors per minute)
- Correlated events
- Stack traces and root causes

## Response Format

```markdown
## Analisi Log Server

**Fonte**: CloudWatch / Docker / File locale
**Periodo**: Ultimi 30 minuti
**Totale entries**: 245

### Riepilogo
| Livello | Count | % |
|---------|-------|---|
| ❌ ERROR | 3 | 1.2% |
| ⚠️ WARN | 12 | 4.9% |
| ℹ️ INFO | 230 | 93.9% |

### Errori Rilevati
```
[2024-01-15 14:30:22] ERROR - ConnectionError: Database connection timeout
    at src/db/connection.py:45
    at src/api/routes.py:120

[2024-01-15 14:32:15] ERROR - ValueError: Invalid user input
    at src/validators/user.py:23
```

### Pattern Identificati
| Pattern | Occorrenze | Prima | Ultima |
|---------|------------|-------|--------|
| DB timeout | 3 | 14:30 | 14:45 |
| Auth failure | 5 | 14:20 | 14:50 |

### Metriche
- Errori/minuto: 0.1
- Tempo medio risposta: 245ms
- Richieste totali: 1,234

### Raccomandazioni
1. [Azione suggerita basata sugli errori]
2. [Monitoraggio da attivare]
```

**IMPORTANT: Respond in Italian (the user's default language).**
**IMPORTANT: If no log source is configured, ask the user where to find the logs.**
**IMPORTANT: Focus on actionable insights - errors that need attention, not just listing all entries.**
