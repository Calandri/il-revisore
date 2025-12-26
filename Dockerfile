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

# Install Claude CLI and Gemini CLI globally
RUN npm install -g @anthropic-ai/claude-code @google/gemini-cli

# Create non-root user (Claude CLI requires non-root for --dangerously-skip-permissions)
RUN useradd -m -s /bin/bash appuser

WORKDIR /app

# Copy and install dependencies first (better layer caching)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir . email-validator

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY agents/ ./agents/

# Setup Claude Code agents and settings for appuser
RUN mkdir -p /home/appuser/.claude/agents
COPY agents/ /home/appuser/.claude/agents/
COPY config/claude-settings.json /home/appuser/.claude/settings.json
RUN chown -R appuser:appuser /home/appuser/.claude

# Create data directory for SQLite
RUN mkdir -p /data && chown -R appuser:appuser /data

# Set ownership of app directory
RUN chown -R appuser:appuser /app

# Environment defaults
ENV TURBOWRAP_SERVER_HOST=0.0.0.0
ENV TURBOWRAP_SERVER_PORT=8000
ENV TURBOWRAP_DB_URL=sqlite:////data/turbowrap.db
ENV TURBOWRAP_REPOS_DIR=/data/repos
ENV PYTHONPATH=/app/src

EXPOSE 8000

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/status')" || exit 1

CMD ["python", "-m", "uvicorn", "turbowrap.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
