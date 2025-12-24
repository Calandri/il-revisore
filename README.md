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
| Code Reviewer | Claude Opus | Deep code review with actionable items |
| Challenger | Gemini Flash | Validates Claude reviews (iterative loop until 50%+ approval) |
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

### Secrets Management

API keys are stored in AWS Secrets Manager:

```bash
# Create/update secret
aws secretsmanager create-secret \
  --name agent-zero/global/api-keys \
  --secret-string '{"ANTHROPIC_API_KEY":"...","GOOGLE_API_KEY":"...","GITHUB_TOKEN":"..."}'
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

## Development

```bash
# Run tests
uv run pytest

# Type check
uv run mypy src/

# Format code
uv run ruff format src/
```

## License

MIT
