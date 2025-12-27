# Accesso EC2 TurboWrap

## Istanza

| Campo | Valore |
|-------|--------|
| **Nome** | TurboRepo |
| **Instance ID** | `i-02cac4811086c1f92` |
| **Regione** | `eu-west-3` (Parigi) |
| **IP Pubblico** | `35.181.63.225` |
| **IP Privato** | `172.31.24.70` |

## Accesso via AWS SSM

L'accesso avviene tramite AWS SSM (Systems Manager). NON serve SSH o chiavi PEM.

### Comando base

```bash
aws ssm send-command \
  --region eu-west-3 \
  --instance-ids "i-02cac4811086c1f92" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["<COMANDO>"]' \
  --query "Command.CommandId" \
  --output text
```

### Leggere output del comando

```bash
# Aspetta qualche secondo, poi:
aws ssm get-command-invocation \
  --region eu-west-3 \
  --command-id "<COMMAND_ID>" \
  --instance-id "i-02cac4811086c1f92" \
  --query "StandardOutputContent" \
  --output text
```

### Esempio completo

```bash
# 1. Invia comando
CMD_ID=$(aws ssm send-command \
  --region eu-west-3 \
  --instance-ids "i-02cac4811086c1f92" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["ls -la /mnt/repos"]' \
  --query "Command.CommandId" \
  --output text)

# 2. Aspetta e leggi output
sleep 3
aws ssm get-command-invocation \
  --region eu-west-3 \
  --command-id "$CMD_ID" \
  --instance-id "i-02cac4811086c1f92" \
  --query "StandardOutputContent" \
  --output text
```

## Struttura Filesystem

| Path | Descrizione |
|------|-------------|
| `/mnt/repos/` | **EBS montato** - Repository clonate (persistente) |
| `/opt/turbowrap/` | Installazione TurboWrap |
| `/opt/turbowrap/data/repos/` | Altra location per repos |

## Operazioni Comuni

### Listare repository

```bash
ls -la /mnt/repos
```

### Trovare cartelle .reviews (da eliminare se causano problemi)

```bash
find /mnt/repos /opt/turbowrap/data/repos -type d -name .reviews 2>/dev/null
```

### Eliminare cartelle .reviews

```bash
find /mnt/repos /opt/turbowrap/data/repos -type d -name .reviews -exec rm -rf {} + 2>/dev/null
```

### Vedere spazio disco

```bash
df -h
```

### Vedere mount points

```bash
lsblk
```

### Controllare servizi Docker

```bash
docker ps
```

## Note Importanti

1. **Regione**: Sempre specificare `--region eu-west-3` (Parigi)
2. **Timeout**: I comandi SSM hanno un timeout, per comandi lunghi usare `--timeout-seconds`
3. **EBS**: I dati persistenti sono su `/mnt/repos` (volume EBS da 12GB)
4. **Non eliminare le repo**: Solo le cartelle `.reviews/` o altri artifact, MAI le repository stesse
