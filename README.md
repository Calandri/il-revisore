# TurboWrap

AI-Powered Code Repository Orchestrator with Web UI and AWS Deployment.

## Features

- **Multi-Agent Code Review**: Claude Opus reviews code, Gemini Flash validates and challenges
- **Web Dashboard**: Real-time repository management and review streaming
- **AWS Infrastructure**: Production-ready deployment with ALB, EC2, ECR, Cognito
- **SSM Deployment**: Zero-SSH deployment via AWS Systems Manager
- **Structure Generation**: Auto-generate STRUCTURE.md documentation for any repository

## Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| Flash Analyzer | Gemini Flash | Fast repository structure analysis |
| Code Reviewer (BE) | Claude Opus | Backend architecture & quality review |
| Code Reviewer (FE) | Claude Opus | Frontend architecture & quality review |
| Challenger | Gemini Pro | Validates reviews (iterative loop until threshold) |
| Fixer | Claude Opus | Autonomous code fixes based on issues |
| Tree Generator | Gemini Flash | Documentation tree (STRUCTURE.md) |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI + SQLAlchemy + SQLite |
| Frontend | Jinja2 + HTMX + TailwindCSS |
| Auth | AWS Cognito (optional) |
| Container | Docker |
| Cloud | AWS EC2 + ALB + ECR + Route53 + ACM |
| Deployment | AWS SSM (zero-SSH) |

## Quick Start

### Local Development

```bash
# Install dependencies
uv sync

# Set API keys
export ANTHROPIC_API_KEY="your-anthropic-key"
export GOOGLE_API_KEY="your-gemini-key"
export GITHUB_TOKEN="your-github-token"  # for private repos

# Run server
uv run uvicorn src.turbowrap.api.main:app --reload --port 8000

# Open http://localhost:8000
```

### CLI Usage

```bash
# Analyze a repository
uv run turbowrap /path/to/repo

# Generate documentation tree
uv run turbowrap /path/to/repo --tree

# Skip analysis, only review
uv run turbowrap /path/to/repo --skip-flash
```

## AWS Deployment

### Prerequisites

- AWS CLI configured with credentials
- Docker installed
- Domain in Route53 (optional, for HTTPS)

### Infrastructure Setup

```bash
# First-time setup (creates VPC, SGs, ALB, EC2, ACM cert)
./deploy/aws-deploy.sh
```

This creates:
- EC2 instance (`t3.small`) with Docker
- Application Load Balancer with HTTPS
- ACM certificate for your domain
- Security groups (ALB: 80/443, EC2: 8000)
- IAM role with Secrets Manager access
- Route53 A record pointing to ALB

### SSH Access to EC2

```bash
# Connect to TurboRepo instance
ssh -i ~/.ssh/turborepo-key ec2-user@ec2-51-44-252-165.eu-west-3.compute.amazonaws.com

# Instance details:
# - ID: i-02cac4811086c1f92
# - Region: eu-west-3
# - Key: ~/.ssh/turborepo-key
```

### Deploy New Version

```bash
# 1. Build Docker image for x86
docker buildx build --platform linux/amd64 -t turbowrap:latest --load .

# 2. Push to ECR
aws ecr get-login-password --region eu-west-3 | docker login --username AWS --password-stdin <account>.dkr.ecr.eu-west-3.amazonaws.com
docker tag turbowrap:latest <account>.dkr.ecr.eu-west-3.amazonaws.com/turbowrap:latest
docker push <account>.dkr.ecr.eu-west-3.amazonaws.com/turbowrap:latest

# 3. Deploy via SSM (zero-SSH)
aws ssm send-command \
  --region eu-west-3 \
  --instance-ids "i-xxxxx" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker pull <ecr-repo>:latest","docker stop turbowrap","docker rm turbowrap","docker run -d --name turbowrap --restart always -p 8000:8000 -v /opt/turbowrap/data:/data --env-file /opt/turbowrap/.env <ecr-repo>:latest"]'
```

> **Note**: The container runs as non-root user (uid 1000). For existing deployments, fix data directory permissions:
> ```bash
> sudo chown -R 1000:1000 /opt/turbowrap/data
> ```

### Secrets Management

API keys are stored in AWS Secrets Manager:

```bash
# Create/update secret
aws secretsmanager create-secret \
  --name agent-zero/global/api-keys \
  --secret-string '{"ANTHROPIC_API_KEY":"...","GOOGLE_API_KEY":"...","GITHUB_TOKEN":"..."}'
```

### Repository Storage

Cloned repositories are stored on a dedicated **12GB EBS volume** to persist across deployments.

#### Storage Paths

| Environment | Path | Description |
|-------------|------|-------------|
| **EC2 (host)** | `/mnt/repos` | EBS volume mount point |
| **Docker (container)** | `/data/repos` | Mapped via `-v /mnt/repos:/data/repos` |
| **Local dev** | `~/.turbowrap/repos` | Default local path |

#### How It Works

1. **Terraform** creates a gp3 EBS volume and attaches it to EC2 at `/dev/xvdf`
2. **Deploy workflow** auto-mounts the volume to `/mnt/repos` (formats on first use)
3. **Docker** maps `/mnt/repos` → `/data/repos` inside the container
4. **App** uses `TURBOWRAP_REPOS_DIR=/data/repos` to read/write repos

#### Infrastructure (Terraform)

```bash
cd terraform
terraform init
terraform plan    # Preview changes
terraform apply   # Create/update volume
```

Current volume: `vol-018dc9033f9740b30` (12GB gp3, eu-west-3b)

#### Why Separate Volume?

- **Persistence**: Repos survive container restarts and EC2 reboots
- **Disk space**: Main volume is only 8GB, repos can grow large
- **Backup**: Can snapshot EBS volume independently
- **Cost**: ~$1.14/month for 12GB gp3

#### Local Development

In local dev, repos are stored in `~/.turbowrap/repos` by default. You can override with:

```bash
export TURBOWRAP_REPOS_DIR=/custom/path/repos
```

Or with Docker:

```bash
docker run -v /your/local/repos:/data/repos turbowrap:latest
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | Claude API key | Yes |
| `GOOGLE_API_KEY` | Gemini API key | Yes |
| `GITHUB_TOKEN` | GitHub token for private repos | No |
| `TURBOWRAP_AUTH_ENABLED` | Enable Cognito auth | No (default: false) |
| `TURBOWRAP_COGNITO_USER_POOL_ID` | Cognito User Pool ID | If auth enabled |
| `TURBOWRAP_COGNITO_CLIENT_ID` | Cognito App Client ID | If auth enabled |

### Cognito Authentication

```bash
# Enable auth
export TURBOWRAP_AUTH_ENABLED=true
export TURBOWRAP_COGNITO_USER_POOL_ID="eu-west-3_xxxxx"
export TURBOWRAP_COGNITO_CLIENT_ID="xxxxx"
export TURBOWRAP_COGNITO_REGION="eu-west-3"
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           TurboWrap                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     Web Dashboard                             │   │
│  │  FastAPI + HTMX + TailwindCSS                                │   │
│  │  - Repository management                                      │   │
│  │  - Real-time review streaming (SSE)                          │   │
│  │  - Issue tracking                                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────┐    ┌────────────────────────────────────┐     │
│  │  Structure Gen  │    │         Review Orchestrator         │     │
│  │  ───────────────│    │  ──────────────────────────────────│     │
│  │  Gemini Flash   │    │                                     │     │
│  │  - Repo type    │    │  ┌─────────┐      ┌─────────────┐  │     │
│  │  - Tech stack   │    │  │ Claude  │ ───► │   Gemini    │  │     │
│  │  - STRUCTURE.md │    │  │ Opus    │      │ Challenger  │  │     │
│  └─────────────────┘    │  │ Review  │ ◄─── │ (validate)  │  │     │
│                         │  └─────────┘      └─────────────┘  │     │
│                         │       │                  │          │     │
│                         │       └──── Loop until ──┘          │     │
│                         │            50%+ approval            │     │
│                         └────────────────────────────────────┘     │
│                                                                      │
├─────────────────────────────────────────────────────────────────────┤
│                         AWS Infrastructure                           │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │
│  │ Route53 │─►│   ALB   │─►│   EC2   │◄─│   ECR   │  │ Secrets │   │
│  │  (DNS)  │  │ (HTTPS) │  │ Docker  │  │ (Image) │  │ Manager │   │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘   │
│       │            │            │                          │        │
│       └────────────┴────────────┴──────────────────────────┘        │
│                         ACM Certificate                              │
└─────────────────────────────────────────────────────────────────────┘
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/repos` | List repositories |
| POST | `/api/repos` | Clone new repository |
| GET | `/api/tasks/{id}` | Get task details |
| POST | `/api/tasks/{id}/review/stream` | Start review (SSE) |
| GET | `/api/status` | Health check |
| POST | `/auth/login` | Login (Cognito) |
| POST | `/auth/logout` | Logout |

## Output Files

| File | Generated By | Content |
|------|--------------|---------|
| `STRUCTURE.md` | Gemini Flash | Folder structure, components, functions |
| `REVIEW_TODO.md` | Claude Opus | Issues, action items, improvements |
| `REPO_DESCRIPTION.md` | Gemini Flash | Overview, tech stack, architecture |

## Challenger Loop

The review process uses an iterative challenger loop:

1. **Claude Opus** generates initial code review
2. **Gemini Flash** validates review quality (0-100%)
3. If score < 50%, Gemini provides feedback
4. Claude refines review based on feedback
5. Loop until score >= 50% or max iterations reached

This ensures high-quality, actionable reviews.

## Fix System

TurboWrap includes an automated fix system that can resolve issues found during review:

### Fix Flow

1. **Select Issues**: Choose issues to fix from the dashboard
2. **Sequential Execution**: BE issues fixed first, then FE (avoids macOS file watcher limits)
3. **Dynamic Batching**: Issues grouped by workload estimation (max 15 points or 5 issues per batch)
4. **Challenger Review**: Gemini validates all fixes, provides feedback if needed
5. **Commit**: Only issues with files in commit are marked RESOLVED

### Issue Lifecycle

```
OPEN → IN_PROGRESS → RESOLVED → MERGED
                  ↘ FAILED (if CLI crashes)
```

Other statuses: `IGNORED`, `DUPLICATE`

### Workload Estimation

Reviewers estimate fix complexity:
- `estimated_effort`: 1-5 (trivial to major refactor)
- `estimated_files_count`: number of files to modify
- Workload = effort × files (max 15 per batch)

See [Fix System README](src/turbowrap/fix/README.md) for detailed architecture.

## Development

```bash
# Run tests
uv run pytest

# Type check
uv run mypy src/

# Format code
uv run ruff format src/

# Run database migrations
./migrations/migrate.sh
```

## License

MIT
