# APP.PY Router Split Plan

**Author**: Architect  
**Date**: 2026-04-06  
**Status**: Proposed  
**Tracking**: P2 Tech Debt — `app.py` 5,655 LOC → target ~800 LOC core + 12 routers

---

## 1. Problem

`src/agenticops/web/app.py` is a 5,655 LOC monolith containing **151 endpoints**. This causes:
- Merge conflicts on any concurrent feature work
- Slow IDE indexing and poor navigation
- Difficult to assign ownership or review scope
- Testing requires importing the entire app for any endpoint

## 2. Precedent

`graph_router` (line 49/881) is already extracted to `agenticops/graph/api.py` and included via `app.include_router()`. We follow the same pattern.

## 3. Target Structure

```
src/agenticops/web/
├── app.py                    # ~800 LOC: lifespan, middleware, models, SPA mount, include_router()
├── session_manager.py        # (existing)
├── memory_service.py         # (existing)
├── summary_service.py        # (existing)
└── routers/
    ├── __init__.py
    ├── accounts.py           # /api/accounts/*          (6 endpoints, ~120 LOC)
    ├── anomalies.py          # /api/anomalies/* + /api/issues/*  (10 endpoints, ~170 LOC)
    ├── audit.py              # /api/audit/*             (3 endpoints, ~100 LOC)
    ├── auth.py               # /api/auth/* + /api/users/* + /api/api-keys/*  (7 endpoints, ~200 LOC)
    ├── chat.py               # /api/chat/*              (5 endpoints, ~300 LOC — includes SSE streaming)
    ├── fix_plans.py          # /api/fix-plans/* + /api/fix-executions/*  (9 endpoints, ~300 LOC)
    ├── health_issues.py      # /api/health-issues/*     (12 endpoints, ~450 LOC)
    ├── im.py                 # /api/im/* + /api/im-aliases/* + callbacks  (9 endpoints, ~400 LOC)
    ├── kb.py                 # /api/kb/* + /api/rag/*   (8 endpoints, ~250 LOC)
    ├── memory.py             # /api/memory/* + /api/agent-memory/*  (6 endpoints, ~120 LOC)
    ├── notifications.py      # /api/notifications/*     (7 endpoints, ~200 LOC)
    ├── reports.py            # /api/reports/* + /api/share  (9 endpoints, ~350 LOC)
    ├── resources.py          # /api/resources/* + /api/scan + /api/health-check + /api/trace  (8 endpoints, ~300 LOC)
    ├── schedules.py          # /api/schedules/*         (8 endpoints, ~200 LOC)
    ├── settings.py           # /api/settings/* + /api/regions  (10 endpoints, ~200 LOC)
    ├── skills.py             # /api/skills/*            (6 endpoints, ~200 LOC)
    ├── dashboard.py          # /api/stats + /api/dashboard/* + /api/search + /api/providers + /api/local-docs  (7 endpoints, ~300 LOC)
    └── webhooks.py           # /api/webhooks/*          (4 endpoints, ~80 LOC)
```

**Total**: 18 routers + core app.py

## 4. Endpoint → Router Mapping

| Router | Prefix | Endpoints | Lines (est.) | Priority |
|--------|--------|-----------|-------------|----------|
| `settings.py` | `/api/settings`, `/api/regions` | 10 | ~200 | **Wave 1** |
| `accounts.py` | `/api/accounts` | 6 | ~120 | **Wave 1** |
| `webhooks.py` | `/api/webhooks` | 4 | ~80 | **Wave 1** |
| `audit.py` | `/api/audit` | 3 | ~100 | **Wave 1** |
| `schedules.py` | `/api/schedules` | 8 | ~200 | **Wave 1** |
| `skills.py` | `/api/skills` | 6 | ~200 | **Wave 1** |
| `notifications.py` | `/api/notifications` | 7 | ~200 | **Wave 2** |
| `memory.py` | `/api/memory`, `/api/agent-memory` | 6 | ~120 | **Wave 2** |
| `kb.py` | `/api/kb`, `/api/rag` | 8 | ~250 | **Wave 2** |
| `reports.py` | `/api/reports`, `/api/share` | 9 | ~350 | **Wave 2** |
| `auth.py` | `/api/auth`, `/api/users`, `/api/api-keys` | 7 | ~200 | **Wave 2** |
| `resources.py` | `/api/resources`, `/api/scan`, `/api/health-check`, `/api/trace` | 8 | ~300 | **Wave 3** |
| `anomalies.py` | `/api/anomalies`, `/api/issues` | 10 | ~170 | **Wave 3** |
| `health_issues.py` | `/api/health-issues` | 12 | ~450 | **Wave 3** |
| `fix_plans.py` | `/api/fix-plans`, `/api/fix-executions`, `/api/executor` | 9 | ~300 | **Wave 3** |
| `dashboard.py` | `/api/stats`, `/api/dashboard`, `/api/search`, `/api/providers`, `/api/local-docs` | 7 | ~300 | **Wave 3** |
| `chat.py` | `/api/chat` | 5 | ~300 | **Wave 4** |
| `im.py` | `/api/im`, `/api/im-aliases`, callbacks | 9 | ~400 | **Wave 4** |

## 5. Implementation Strategy

### Wave 1 — Low-risk, self-contained (6 routers, ~900 LOC)
Settings, Accounts, Webhooks, Audit, Schedules, Skills — these have minimal cross-dependencies and clean CRUD patterns.

### Wave 2 — Medium complexity (5 routers, ~1,120 LOC)
Notifications, Memory, KB, Reports, Auth — some shared utilities (db session, auth middleware).

### Wave 3 — Core domain (5 routers, ~1,520 LOC)
Resources, Anomalies, Health Issues, Fix Plans, Dashboard — heavy cross-references, need shared response models.

### Wave 4 — Stateful/streaming (2 routers, ~700 LOC)
Chat (SSE streaming) and IM (webhook callbacks, bot integrations) — most complex, extract last.

## 6. Shared Concerns

Items that stay in `app.py` or move to shared modules:

```
app.py (core):
  - FastAPI() instantiation + lifespan handler
  - Middleware (CORS, auth, etc.)
  - SPA static mount + catch-all route
  - include_router() calls
  - Pydantic response models → move to routers/models.py (shared)

routers/_deps.py (new):
  - get_db_session dependency
  - get_current_user dependency  
  - Common query parameter patterns
  - _ensure_aws_session helper

routers/models.py (new):
  - All Pydantic response/request models (currently ~300 LOC in app.py header)
```

## 7. Migration Rules (for Developer)

1. **One router per PR** — do NOT batch. Each PR = one router extraction + tests pass.
2. **No behavior changes** — pure mechanical move. Same function names, same decorators, same logic.
3. **Replace `@app.get(...)` → `@router.get(...)`** with `router = APIRouter(prefix="/api/xxx", tags=["xxx"])`.
4. **Imports follow the function** — each router imports only what it uses.
5. **Response models stay co-located** — if a model is used by only one router, move it there. Shared models → `routers/models.py`.
6. **Test verification**: after each extraction, run `pytest tests/test_web_*.py tests/test_api_*.py -x` + `curl` smoke test on key endpoints.
7. **Frontend regression**: `cd frontend && npm run build` must pass (no API path changes).

## 8. What NOT to Change

- **Zero URL changes** — all paths stay identical
- **Zero response schema changes** — byte-for-byte compatible
- **`graph_router`** — already extracted, leave as-is
- **lifespan handler** — stays in app.py
- **SSE streaming logic** — extract in Wave 4 only, after patterns are proven

## 9. Effort Estimate

| Wave | Routers | Est. Time | Reviewer |
|------|---------|-----------|----------|
| Wave 1 | 6 | 2-3 hours | Tester (API test pass) |
| Wave 2 | 5 | 3-4 hours | Tester |
| Wave 3 | 5 | 4-5 hours | Architect (domain review) + Tester |
| Wave 4 | 2 | 2-3 hours | Architect + Tester |

**Total**: ~12-15 hours of Developer time across 1-2 weeks.

## 10. Success Criteria

- [ ] `app.py` ≤ 1,000 LOC (from 5,655)
- [ ] All 151 endpoints accessible at same paths
- [ ] `pytest` full suite green (1,390+ passed)
- [ ] Frontend build + smoke test pass
- [ ] Each router is independently testable
- [ ] No circular imports

## 11. Recommended Start

**Wave 1, first router: `accounts.py`** (6 endpoints, cleanest CRUD, zero cross-deps).

```python
# src/agenticops/web/routers/accounts.py
from fastapi import APIRouter, HTTPException, Query
from agenticops.models import get_db_session, CloudAccount
# ... minimal imports

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

@router.get("", response_model=List[AccountResponse])
async def list_accounts(...):
    ...
```

Then in `app.py`:
```python
from agenticops.web.routers.accounts import router as accounts_router
app.include_router(accounts_router)
```

---

*@Developer: Start with Wave 1 after the hypothesis + coverage sprint wraps up. One router per PR, green tests before merge.*
