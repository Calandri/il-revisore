# TurboWrap - AI-Powered Repository Orchestrator
FROM python:3.11-slim

# Install git, Node.js, and dependencies for Claude CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

# Copy and install dependencies first (better layer caching)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir . email-validator

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY agents/ ./agents/

# Setup Claude Code agents and settings
RUN mkdir -p /root/.claude/agents
COPY agents/ /root/.claude/agents/
COPY config/claude-settings.json /root/.claude/settings.json

# Create data directory for SQLite
RUN mkdir -p /data

# Environment defaults
ENV TURBOWRAP_SERVER_HOST=0.0.0.0
ENV TURBOWRAP_SERVER_PORT=8000
ENV TURBOWRAP_DB_URL=sqlite:////data/turbowrap.db
ENV TURBOWRAP_REPOS_DIR=/data/repos
ENV PYTHONPATH=/app/src

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/status')" || exit 1

CMD ["python", "-m", "uvicorn", "turbowrap.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
