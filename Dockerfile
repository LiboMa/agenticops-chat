# =============================================================================
# AgenticOps — Production Container (multi-stage)
# Stage 1: Build frontend | Stage 2: Python runtime
# =============================================================================

# Stage 1: Frontend build
FROM node:20-alpine AS frontend
WORKDIR /build
COPY src/agenticops/web/frontend/package*.json ./
RUN npm ci --silent
COPY src/agenticops/web/frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Create non-root user
RUN useradd -r -m -s /bin/bash agenticops

WORKDIR /app

# Install Python dependencies (cached layer)
COPY pyproject.toml README.md ./
COPY src/ ./src/
# Hatchling requires frontend dist dir to exist during install
COPY --from=frontend /build/dist ./src/agenticops/web/frontend/dist
RUN uv pip install --system ".[im,files,reports]"
COPY config/settings.yaml ./config/settings.yaml
COPY skills/ ./skills/
COPY agent-memory/ ./agent-memory/

# Create data directory + empty MCP config (cloud: no stdio MCP)
RUN mkdir -p /app/data /app/config && \
    echo '{"mcpServers": {}}' > /app/config/mcp-servers.json && \
    chown -R agenticops:agenticops /app

USER agenticops

# Environment defaults
ENV AIOPS_DEPLOYMENT_PROFILE=cloud \
    AIOPS_DATABASE_URL=sqlite:////app/data/agenticops.db \
    AIOPS_API_AUTH_ENABLED=true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "agenticops.web.app:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--timeout-keep-alive", "30"]
