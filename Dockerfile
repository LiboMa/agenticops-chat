# =============================================================================
# AgenticOps — Production Container (multi-stage)
# Stage 1: Build frontend | Stage 2: Python runtime with all dependencies
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

# --- System dependencies ---
# curl: healthcheck + API calls
# ca-certificates: HTTPS
# git: skills registry (clawhub)
# openssh-client: SSH execution skill (run_on_host)
# jq: JSON processing in shell scripts
# unzip: AWS CLI installer
# weasyprint deps: libcairo2, libpango, libgdk-pixbuf (PDF report generation)
# kubectl: EKS operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    openssh-client \
    jq \
    unzip \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    libglib2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# --- AWS CLI v2 ---
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip && \
    unzip -qo /tmp/awscliv2.zip -d /tmp && \
    /tmp/aws/install && \
    rm -rf /tmp/awscliv2.zip /tmp/aws

# --- kubectl ---
RUN curl -fsSL "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    -o /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl

# --- uv (Python package manager + uvx for MCP servers) ---
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv && \
    mv /root/.local/bin/uvx /usr/local/bin/uvx

# --- Create non-root user ---
RUN useradd -r -m -s /bin/bash agenticops

WORKDIR /app

# --- Install Python dependencies (locked versions from uv export) ---
COPY requirements.txt ./
RUN uv pip install --system -r requirements.txt

# --- Install project itself ---
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY --from=frontend /build/dist ./src/agenticops/web/frontend/dist
RUN uv pip install --system --no-deps ".[im,files,reports,cloud]"

# --- Copy config + skills ---
COPY config/settings.yaml ./config/settings.yaml
COPY skills/ ./skills/
COPY agent-memory/ ./agent-memory/

# --- Create directories + empty MCP config ---
RUN mkdir -p /app/data /app/logs /app/config && \
    echo '{"mcpServers": {}}' > /app/config/mcp-servers.json && \
    chown -R agenticops:agenticops /app

# --- Verify all critical tools are installed ---
RUN aws --version && \
    kubectl version --client && \
    uvx --version && \
    python -c "import boto3, yaml, mcp, strands, sqlalchemy, fastapi, networkx, weasyprint; print('All imports OK')"

USER agenticops

# --- Environment defaults ---
ENV AIOPS_PROJECT_ROOT=/app \
    AIOPS_DEPLOYMENT_PROFILE=cloud \
    AIOPS_DATABASE_URL=sqlite:////app/data/agenticops.db \
    AIOPS_API_AUTH_ENABLED=true \
    PATH="/home/agenticops/.local/bin:/usr/local/bin:$PATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "agenticops.web.app:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--timeout-keep-alive", "30"]
