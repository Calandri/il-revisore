# TurboWrap - AI-Powered Repository Orchestrator
FROM python:3.12-slim

# Build arguments for commit info
ARG COMMIT_SHA=unknown
ARG BUILD_DATE=unknown

# Make commit info available at runtime via environment
ENV COMMIT_SHA=$COMMIT_SHA
ENV BUILD_DATE=$BUILD_DATE

# Labels for container identification
LABEL org.opencontainers.image.revision=$COMMIT_SHA
LABEL org.opencontainers.image.created=$BUILD_DATE
LABEL org.opencontainers.image.title="TurboWrap"
LABEL org.opencontainers.image.description="AI-Powered Repository Orchestrator"

# Install git, Node.js, GitHub CLI, AWS CLI, and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    gnupg \
    procps \
    unzip \
    && mkdir -p /etc/apt/keyrings \
    # Node.js
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    # GitHub CLI
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y nodejs gh \
    # AWS CLI v2
    && curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf awscliv2.zip aws \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI, Gemini CLI, and Grok CLI globally
RUN npm install -g @anthropic-ai/claude-code @google/gemini-cli @vibe-kit/grok-cli

# Create non-root user (Claude CLI requires non-root for --dangerously-skip-permissions)
RUN useradd -m -s /bin/bash appuser

WORKDIR /app

# Copy and install local packages first (turbowrap-errors, turbowrap-llm)
COPY packages/ ./packages/
RUN pip install --no-cache-dir ./packages/turbowrap-errors-py/ ./packages/turbowrap-llm/

# Copy and install main dependencies (better layer caching)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir . email-validator

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY agents/ ./agents/
COPY commands/ ./commands/
COPY docs_llm/ ./docs_llm/

# Copy MCP config for production (renamed from .mcp.production.json)
COPY .mcp.production.json ./.mcp.json

# Copy Alembic migrations
COPY alembic.ini ./
COPY alembic/ ./alembic/

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

# Expose main application port and development ports
# 8000-8005: Backend services (main app + 5 dev instances)
# 3000-3005: Frontend services (6 dev instances)
# 6000-6006: Additional services (7 instances)
EXPOSE 8000 8001 8002 8003 8004 8005
EXPOSE 3000 3001 3002 3003 3004 3005
EXPOSE 6000 6001 6002 6003 6004 6005 6006

# Switch to non-root user
USER appuser

# Configure git credential helper for appuser
# When git needs authentication, this helper provides username and token from GITHUB_TOKEN env var
# GitHub accepts 'x-access-token' as username when using PAT/tokens
RUN git config --global credential.helper '!f() { echo "username=x-access-token"; echo "password=${GITHUB_TOKEN}"; }; f'

# Copy entrypoint script
COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Health check (1 minute interval to reduce connection pool usage)
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/status')" || exit 1

CMD ["/app/entrypoint.sh"]
