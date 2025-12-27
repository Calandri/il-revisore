# Infrastructure Operations Agent

Agente per operazioni infrastrutturali su AWS EC2.

## EC2 TurboWrap (Produzione)

| Campo | Valore |
|-------|--------|
| **Nome** | TurboRepo |
| **Instance ID** | `i-02cac4811086c1f92` |
| **Regione** | `eu-west-3` (Parigi) |
| **IP Pubblico** | `35.181.63.225` |

## Come Eseguire Comandi

Usa AWS SSM (NON SSH):

```bash
# 1. Invia comando
aws ssm send-command \
  --region eu-west-3 \
  --instance-ids "i-02cac4811086c1f92" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["<COMANDO>"]' \
  --query "Command.CommandId" \
  --output text

# 2. Aspetta 3-5 secondi

# 3. Leggi output
aws ssm get-command-invocation \
  --region eu-west-3 \
  --command-id "<COMMAND_ID>" \
  --instance-id "i-02cac4811086c1f92" \
  --query "StandardOutputContent" \
  --output text
```

## Filesystem EC2

| Path | Descrizione |
|------|-------------|
| `/mnt/repos/` | **EBS 12GB** - Repository clonate |
| `/opt/turbowrap/data/repos/` | Altra location repos |

## Operazioni Comuni

### Eliminare cartelle .reviews (causano ScopeValidationError)

```bash
find /mnt/repos /opt/turbowrap/data/repos -type d -name .reviews -exec rm -rf {} + 2>/dev/null
```

### Vedere spazio disco

```bash
df -h
```

### Listare repos

```bash
ls -la /mnt/repos
```

## IMPORTANTE

- Sempre usare `--region eu-west-3`
- NON eliminare le repository, solo i file di sistema (.reviews, .turbowrap, etc.)
- Le repo sono temporanee - vengono clonate per review/fix e poi eliminate
