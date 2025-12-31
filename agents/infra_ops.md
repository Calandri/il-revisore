# Infrastructure Operations Agent

Agent for infrastructure operations on AWS EC2.

## EC2 TurboWrap (Production)

| Field | Value |
|-------|-------|
| **Name** | TurboRepo |
| **Instance ID** | `i-02cac4811086c1f92` |
| **Region** | `eu-west-3` (Paris) |
| **Public IP** | `35.181.63.225` |

## How to Execute Commands

Use AWS SSM (NOT SSH):

```bash
# 1. Send command
aws ssm send-command \
  --region eu-west-3 \
  --instance-ids "i-02cac4811086c1f92" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["<COMMAND>"]' \
  --query "Command.CommandId" \
  --output text

# 2. Wait 3-5 seconds

# 3. Read output
aws ssm get-command-invocation \
  --region eu-west-3 \
  --command-id "<COMMAND_ID>" \
  --instance-id "i-02cac4811086c1f92" \
  --query "StandardOutputContent" \
  --output text
```

## EC2 Filesystem

| Path | Description |
|------|-------------|
| `/mnt/repos/` | **EBS 12GB** - Cloned repositories |
| `/opt/turbowrap/data/repos/` | Alternative repos location |

## Common Operations

### Delete .reviews folders (cause ScopeValidationError)

```bash
find /mnt/repos /opt/turbowrap/data/repos -type d -name .reviews -exec rm -rf {} + 2>/dev/null
```

### Check disk space

```bash
df -h
```

### List repos

```bash
ls -la /mnt/repos
```

## IMPORTANT

- Always use `--region eu-west-3`
- DO NOT delete repositories, only system files (.reviews, .turbowrap, etc.)
- Repos are temporary - they are cloned for review/fix and then deleted
