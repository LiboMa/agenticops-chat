# AgenticOps — Project Statistics

**Version**: 2.5.0
**Date**: 2026-09-08
**Branch**: `main` == `MVP-2.5.0` (`f820f19`)

All numbers below are **measured** with the script at the end of this file (line counts via
`wc -l`-equivalent over `git ls-files`; routes from the live FastAPI app; tests from the last full
run). Regenerate rather than hand-edit.

---

## Code Metrics

### Total

| Layer | Files | Lines |
|-------|------:|------:|
| Backend (Python, `src/agenticops/`) | 220 | 66,599 |
| Frontend (TypeScript/React, `web/frontend/src/`) | 139 | 19,562 |
| Tests (`tests/`) | 210 | 59,585 |
| Skills (Markdown, `skills/`) | 50 | — |
| Infrastructure (`iac/`, `infra/`, `docker/`) | 197 | — |
| **Total** | **816** | **145,700+** |

### Backend Breakdown (`src/agenticops/`)

| Module | Files | Lines | Description |
|--------|------:|------:|-------------|
| `tools/` | 21 | 8,890 | Agent tools: metadata DB CRUD, AWS CLI wrapper (account-addressed), network, graph, cloudwatch, notification |
| `web/` | 20 | 8,723 | FastAPI app + `routers/` (webhooks, schedules, skills, security, signals, auth, accounts, cost, memory, audit, search, agent logs) + `schemas.py`; 227 routes |
| `cli/` | 6 | 7,024 | Typer CLI: chat REPL (42 slash commands), init wizard, `skills import`, display |
| `skills/` | 12 | 4,832 | Loader, bundle security scan (`.py` ast / `.sh` line), wide-source import (`sources`), script sandbox, Curator, review/promote/rollback, tools |
| `graph/` | 10 | 4,164 | Infrastructure graph engine (NetworkX): SPOF, capacity, dependencies, change simulation |
| `services/` | 17 | 4,016 | Auto-fix pipeline, RCA + quality gate, Signal Gate, security service, notifications, events, resolution, cost |
| `agents/` | 11 | 2,922 | 7 Strands agents + preamble (model capability gating, thinking shape) + enhanced (ACP) |
| `notify/` | 4 | 2,564 | Multi-channel notifications: email/SES, Slack, Feishu, DingTalk, WeCom, SNS, webhook |
| `im/` | 10 | 1,897 | IM gateways (Feishu WebSocket, Slack, DingTalk, WeCom) |
| `integrations/` | 6 | 1,767 | Webhook alert processing, source parsers (Prometheus/CloudWatch/Datadog) |
| `providers/` | 9 | 1,626 | Multi-cloud provider abstraction; AWS AssumeRole with auto-refresh |
| `models.py` | 1 | 1,458 | SQLAlchemy ORM: 29 tables (HealthIssue, FixPlan, RCAResult, Signal, SecuritySnapshot, …) |
| `pipeline/` | 6 | 1,455 | Pipeline orchestrator, health patrol, RAG pipeline |
| `config.py` | 1 | 1,374 | Pydantic-settings schema (~185 fields), YAML loader, model tiers |
| `security/` | 9 | 1,207 | Cloud Security Review: collectors, pure CIS scoring, NACL-aware reachability, posture snapshot, incremental poll, fail-closed advisor |
| `chat/` | 7 | 1,191 | Message preprocessor, file reader, /send_to, /channel |
| `credentials/` | 4 | 1,131 | Credential resolver (fail-closed, account-keyed cache, subprocess env) |
| `kb/` | 5 | 1,114 | Vector storage (SQLite/pgvector/S3), knowledge base |
| `scan/` | 4 | 969 | AWS resource scanner |
| `galaxy/` | 6 | 836 | Galaxy relationship graph (LLM-hybrid, fail-closed verification) |
| `itsm/` | 5 | 821 | ITSM bridge (ServiceNow / Jira) |
| `scheduler/` | 2 | 788 | Cron scheduler, 8 pipeline types, execution tracking |
| `memory/` | 4 | 771 | Self-optimizing file-based agent memory + Curator |
| `detect/` | 3 | 748 | Anomaly detector: rules + statistics (Z-score, IQR) |
| `report/` | 2 | 660 | Report generator (daily, incident, inventory, security-review) |
| `scanner/` `monitor/` | 7 | 1,156 | Scanning helpers, CloudWatch metrics collector |
| `auth/` `audit/` | 6 | 961 | JWT / API-key auth, audit trail |
| `acp/` | 10 | 478 | Optional ACP enhanced backend (claude-code / kiro-cli / codex) |
| `analyze/` `mcp_manager.py` `storage/` `checker/` `cost.py` | 8 | 1,034 | RCA engine, MCP manager, storage backends, health checker, token→USD |

### Frontend Breakdown (`src/agenticops/web/frontend/src/`)

| Directory | Files | Lines | Description |
|-----------|------:|------:|-------------|
| `pages/` | 16 | 8,397 | Dashboard, Chat, Issues & Plans, Issue/Resource/Schedule/Report/Skill detail, Schedules, Reports, Agent Metrics, Skills, Security, Settings, Galaxy, Login |
| `components/` | 49 | 6,121 | Chat, layout (AppShell, Sidebar, Header), galaxy/, ui/ (DataTable, CronBuilder, badges, steppers) |
| `hooks/` | 45 | 2,220 | TanStack Query hooks for every API resource |
| `api/` | 2 | 1,027 | API client (auth, `ApiError`), TypeScript types |
| `lib/` | 14 | 986 | Pure helpers (chat stream, sessions, attachments, cron, skill source detection, …) |
| `__tests__/` | 8 | 545 | Vitest unit tests over `lib/` (53 cases) |

---

## Key Counts

| Metric | Count | How measured |
|--------|------:|--------------|
| HTTP routes | 227 (217 under `/api/`) | `(method, path)` pairs from `app.routes`, `HEAD` excluded |
| Test files / functions | 210 / 3,994 | `tests/**/*.py`, `def test_` |
| Last full run | **4,333 passed · 85 skipped · 0 failed** (~2 min) | `pytest tests/ -q` on 2026-09-08 |
| Frontend unit tests | 53 | `npx vitest --run` |
| Agent skills (published) | 16 (+ `draft/`) | `git ls-files skills` package dirs |
| Web pages | 15 (+ Login) | `pages/*.tsx` |
| SQLAlchemy tables | 29 | `__tablename__` in `models.py` |
| Config fields | ~185 | `Field(` declarations in `config.py` |
| Strands agents | 7 | main + scan, detect, rca, sre, executor, reporter |
| Pipeline types | 8 | FullScan, Monitoring, DailyReport, HealthPatrol, GalaxyBuild, SecurityPostureSnapshot, SecurityIncrementalPoll, AgentChain |
| CLI slash commands | 42 | `/help` entries in `cli/main.py` |

---

## Architecture Overview

```
   CLI (aiops chat) ─┐
   Web (React+SSE)  ─┼──► Main Agent (router, Opus 5) ──► Scan · Detect · RCA · SRE · Executor · Reporter
   IM bots / webhook─┘            │
                                  ├──► Signal Gate (services/) ── every issue-creation path
                                  ├──► Security engine (security/) ── posture · CIS score · reachability · advisor
                                  ├──► Agent Memory (agent-memory/) · Agent Skills (skills/, sandboxed scripts)
                                  ├──► Graph engine (graph/) · Galaxy (galaxy/)
                                  └──► Provider layer (providers/, credentials/) ──► AWS accounts (AssumeRole, fail-closed)
```

**Auto-Fix Pipeline**: HealthIssue → RCA → quality gate → SRE → Approve (L0/L1 auto, L2/L3 human) → Execute → Resolve

**HealthIssue State Machine**: open → investigating → acknowledged → root_cause_identified → fix_planned → fix_approved → fix_executing → fix_executed → resolved (9 states)

---

## Roadmap

Forward-looking items live in each release note's *Future* section — most recently
[`MVP-2.5.0-RELEASE.md`](MVP-2.5.0-RELEASE.md). Items from the old 1.0.1 roadmap that have since
shipped: `app.py` router split (2.5.0 / main merge), persistent chat sessions (1.1.1),
knowledge-base RAG in RCA (1.0.x), FixPlan approval in the web UI (1.0.x), compliance scanning
(2.5.0 Cloud Security Review — CIS).

---

## Regenerating this file

```bash
# from the repo root, project .venv active
python - <<'PY'
import subprocess, collections
files = subprocess.check_output(["git","ls-files"], text=True).split()
loc = lambda ps: sum(sum(1 for _ in open(p, encoding="utf-8", errors="ignore")) for p in ps)
be = [f for f in files if f.startswith("src/agenticops/") and f.endswith(".py") and "/frontend/" not in f]
fe = [f for f in files if f.startswith("src/agenticops/web/frontend/src/") and f.endswith((".ts",".tsx"))]
te = [f for f in files if f.startswith("tests/") and f.endswith(".py")]
print("backend", len(be), loc(be)); print("frontend", len(fe), loc(fe)); print("tests", len(te), loc(te))
mods = collections.defaultdict(lambda: [0, 0])
for f in be:
    k = f[len("src/agenticops/"):].split("/")[0]; mods[k][0] += 1; mods[k][1] += loc([f])
for k, (n, l) in sorted(mods.items(), key=lambda x: -x[1][1]): print(f"{k:<16}{n:>4}{l:>8}")
PY
PYTHONPATH=src python -c "
from agenticops.web.app import app
s={(m,r.path) for r in app.routes for m in (getattr(r,'methods',None) or []) if m!='HEAD'}
print('routes', len(s), 'api', sum(p.startswith('/api/') for _,p in s))"
git ls-files skills | cut -d/ -f2 | grep -vE 'ADDING_SKILLS.md|^draft$' | sort -u | wc -l   # skills
pytest tests/ -q 2>&1 | tail -1                                                              # tests
```
