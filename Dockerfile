# -----------------------------------------------------------------------------
# AgenticOps — Production Container (Ubuntu 24.04 + uv)
# For future ECS/EKS deployment
# -----------------------------------------------------------------------------
FROM ubuntu:24.04 AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git build-essential libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install Python 3.12 via uv
RUN uv python install 3.12

# Create non-root user
RUN useradd -r -m -s /bin/bash agenticops

WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY skills/ ./skills/
COPY config/ ./config/

# Install via uv
RUN uv venv .venv --python 3.12 && \
    . .venv/bin/activate && \
    uv pip install -e .

# Create data directory
RUN mkdir -p /app/data && chown -R agenticops:agenticops /app /app/data

# Switch to non-root
USER agenticops

# Environment defaults
ENV PATH="/app/.venv/bin:$PATH" \
    AIOPS_DATABASE_URL=sqlite:////app/data/agenticops.db \
    AIOPS_API_AUTH_ENABLED=true \
    AIOPS_DEPLOYMENT_PROFILE=cloud

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "agenticops.web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
