# AgenticOps Docker

Production Docker image for AgenticOps — single image for EC2/ECS/EKS deployment.

## Quick Start

```bash
# Build
./docker/build.sh

# Build + push to ECR
./docker/build.sh push <ecr-repo-url>

# Run locally
docker run --rm -p 8000:8000 \
  -e AIOPS_ADMIN_PASSWORD=test123 \
  -e AIOPS_BEDROCK_REGION=us-east-1 \
  agenticops:latest
```

## Image Contents

### System Tools
| Tool | Version | Purpose |
|------|---------|---------|
| AWS CLI v2 | latest | Agent AWS operations (`aws` commands) |
| kubectl | latest stable | EKS cluster operations |
| uvx | latest | MCP server subprocess (stdio transport) |
| git | system | Skills registry |
| ssh | system | Remote host execution skill |
| jq | system | JSON processing |
| curl | system | Health checks, API calls |

### Python Libraries (all optional extras included)
| Extra | Packages | Purpose |
|-------|----------|---------|
| `[im]` | slack_sdk, lark-oapi | Instant messaging (Slack, Feishu) |
| `[files]` | python-docx, pymupdf | File processing (DOCX, PDF) |
| `[reports]` | weasyprint, python-docx | Report generation (HTML→PDF) |
| `[cloud]` | psycopg2-binary, pgvector | PostgreSQL + vector storage |

### System Libraries (for WeasyPrint PDF rendering)
- libcairo2, libpango-1.0-0, libpangocairo-1.0-0
- libgdk-pixbuf-2.0-0, libglib2.0-0, shared-mime-info

## Build Details

```
docker/
├── Dockerfile         # Multi-stage: Node frontend → Python runtime
├── .dockerignore      # Excludes .git, iac/, docs/, data/, tests/
├── build.sh           # Build + optional push to ECR
└── README.md          # This file
```

**Build context**: Project root (`/`)
**Dockerfile path**: `docker/Dockerfile` (use `-f docker/Dockerfile`)

## Configuration

All configuration via environment variables (`AIOPS_*` prefix):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AIOPS_PROJECT_ROOT` | No | `/app` | Application root path |
| `AIOPS_DEPLOYMENT_PROFILE` | No | `cloud` | `local` or `cloud` |
| `AIOPS_DATABASE_URL` | No | `sqlite:////app/data/agenticops.db` | Database connection |
| `AIOPS_BEDROCK_REGION` | Yes | - | AWS Bedrock region |
| `AIOPS_BEDROCK_MODEL_ID` | No | settings.yaml default | Main LLM model |
| `AIOPS_API_AUTH_ENABLED` | No | `true` | Enable web auth |
| `AIOPS_ADMIN_PASSWORD` | Yes | - | Admin login password |

Full list: see `src/agenticops/config.py` and `config/settings.yaml`.

## Volumes

| Mount Point | Purpose | Required |
|-------------|---------|----------|
| `/app/data` | SQLite DB, reports, knowledge base | Yes (for persistence) |
| `/app/logs` | Application logs | Optional |
| `/app/config` | Custom settings, MCP config | Optional |

**Important**: Set volume ownership to UID 1000 before first run:
```bash
mkdir -p /path/to/data && chown -R 1000:1000 /path/to/data
```

## Health Check

Built-in Docker HEALTHCHECK:
```
GET http://localhost:8000/api/health
Interval: 30s | Timeout: 5s | Start period: 15s | Retries: 3
```

## Architecture

```
┌─────────────────────────────────────────┐
│ Container (UID 1000, agenticops user)   │
│                                         │
│  uvicorn (4 workers, port 8000)         │
│  ├── FastAPI app                        │
│  ├── Agent framework (Strands + Bedrock)│
│  ├── Scheduler (1 worker only, CAS)    │
│  └── IM bots (Feishu/Slack WS)         │
│                                         │
│  Tools: aws, kubectl, uvx, git, ssh    │
└─────────────────────────────────────────┘
         │
         ▼
  /app/data (volume) — SQLite, reports, KB
```
