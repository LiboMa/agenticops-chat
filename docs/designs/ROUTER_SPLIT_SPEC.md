# Router Split Design Spec v1.0

**Author**: Architect  
**Date**: 2026-05-27  
**Status**: Draft  
**Scope**: `src/agenticops/web/app.py` → modular FastAPI routers

---

## 1. Problem Statement

`web/app.py` has grown to **4,210 lines** with **121 endpoints** in a single file. This causes:

1. **Low testability** — monolithic file requires heavy mock setups; current coverage ~32%
2. **Merge conflicts** — any feature touching the API layer conflicts with others
3. **Cognitive load** — impossible to reason about one domain without reading all 4K lines
4. **Violation of SRP** — one file handles auth, alerts, RCA, KB, schedules, notifications, chat, IM, etc.

## 2. Design Principles

1. **Zero behavioral change** — pure refactor, no API contract changes
2. **Incremental** — can be done router-by-router, each commit independently deployable
3. **Preserve imports** — consumers (tests, frontend) use URL paths, not Python imports
4. **Coverage-friendly** — each router module is independently testable with minimal mocks

## 3. Target Architecture

```
src/agenticops/web/
├── app.py              # Slim: FastAPI app creation, lifespan, middleware, mount routers
├── dependencies.py     # Shared deps: get_db_session, get_current_user, etc.
├── routers/
│   ├── __init__.py
│   ├── health.py       # /api/health, /api/stats
│   ├── settings.py     # /api/settings, /api/regions, /api/scan-focus-options
│   ├── accounts.py     # /api/accounts/*
│   ├── resources.py    # /api/resources/*
│   ├── issues.py       # /api/anomalies/*, /api/issues/*, /api/health-issues/*
│   ├── rca.py          # /api/health-issues/{id}/rca, /api/rag/pipeline/*
│   ├── fix_plans.py    # /api/fix-plans/*, /api/fix-executions/*
│   ├── alerts.py       # /api/webhooks/alert/*
│   ├── providers.py    # /api/providers
│   ├── network.py      # /api/network/*
│   ├── kb.py           # /api/kb/*
│   ├── reports.py      # /api/reports/*
│   ├── schedules.py    # /api/schedules/*
│   ├── notifications.py # /api/notifications/*
│   ├── auth.py         # /api/auth/*, /api/users/*, /api/api-keys/*
│   ├── audit.py        # /api/audit/*
│   ├── chat.py         # /api/chat/*
│   ├── im.py           # /api/im/*, /api/im-aliases, IM callbacks
│   ├── docs.py         # /api/local-docs/*
│   └── views.py        # / , /resources, /anomalies, /reports, /network, /app/*
└── schemas/            # (existing, no change)
```

## 4. Wave Plan

### Wave 1 — Low-risk, high-independence (Week 1)

| Router | Endpoints | Lines (est.) | Dependencies |
|--------|-----------|-------------|--------------|
| `schedules.py` | 7 | ~200 | DB session only |
| `accounts.py` | 5 | ~120 | DB session only |
| `settings.py` | 3 | ~80 | DB session, config |
| `health.py` | 2 | ~100 | DB session, scheduler status |

**Estimated reduction**: app.py shrinks by ~500 lines  
**Risk**: Minimal — these domains have no cross-endpoint dependencies

### Wave 2 — Medium complexity (Week 2)

| Router | Endpoints | Lines (est.) | Dependencies |
|--------|-----------|-------------|--------------|
| `notifications.py` | 7 | ~200 | DB, notifier service |
| `reports.py` | 7 | ~250 | DB, report generator, SES |
| `auth.py` | 8 | ~200 | DB, JWT, password hashing |
| `audit.py` | 3 | ~120 | DB session |
| `kb.py` | 8 | ~250 | DB, SOP upgrader |

**Estimated reduction**: app.py shrinks by ~1,000 more lines

### Wave 3 — Core domain (Week 3)

| Router | Endpoints | Lines (est.) | Dependencies |
|--------|-----------|-------------|--------------|
| `issues.py` | 15 | ~500 | DB, RCA engine, fix plan generator |
| `fix_plans.py` | 9 | ~350 | DB, executor service |
| `alerts.py` | 4 | ~100 | DB, alert processor |
| `rca.py` | 3 | ~150 | RCA engine, RAG pipeline |

### Wave 4 — IM & Views (Week 4)

| Router | Endpoints | Lines (est.) | Dependencies |
|--------|-----------|-------------|--------------|
| `im.py` | 8+ | ~400 | IM services, WebSocket |
| `chat.py` | 5 | ~300 | Agent orchestrator, streaming |
| `views.py` | 7 | ~150 | Static file serving |
| `network.py` | 4 | ~100 | DB, topology builder |
| `resources.py` | 3 | ~80 | DB session |
| `providers.py` | 1 | ~60 | Provider registry |

## 5. Migration Pattern

Each router extraction follows this pattern:

```python
# src/agenticops/web/routers/schedules.py
from fastapi import APIRouter, Depends
from ..dependencies import get_db_session

router = APIRouter(prefix="/api/schedules", tags=["schedules"])

@router.get("", response_model=List[ScheduleResponse])
async def list_schedules(db=Depends(get_db_session)):
    ...
```

```python
# src/agenticops/web/app.py (after extraction)
from .routers import schedules, accounts, settings, ...

app.include_router(schedules.router)
app.include_router(accounts.router)
```

### Shared Dependencies (`dependencies.py`)

Extract from app.py:
- `get_db_session()` — SQLAlchemy session factory
- `get_current_user()` — JWT auth dependency
- `require_role(role)` — role-based access
- `get_scheduler()` — scheduler instance access

## 6. Testing Strategy

Each router gets its own test file:
```
tests/web/
├── test_router_schedules.py
├── test_router_accounts.py
├── ...
```

Using `TestClient` with the isolated router:
```python
from fastapi.testclient import TestClient
from fastapi import FastAPI
from agenticops.web.routers.schedules import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)
```

This allows testing each router with **minimal mocks** — only its declared dependencies.

## 7. Validation Criteria

Per-wave completion checklist:
- [ ] All extracted endpoints respond identically (same status codes, response bodies)
- [ ] Existing tests pass without modification (URL paths unchanged)
- [ ] New router-specific tests achieve ≥80% coverage for the extracted module
- [ ] `app.py` line count decreases by expected amount
- [ ] No import cycles introduced

## 8. Coverage Impact Projection

| Phase | app.py lines | Est. coverage |
|-------|-------------|---------------|
| Current | 4,210 | 32% |
| After Wave 1 | ~3,700 | app.py 35%, new routers 80%+ |
| After Wave 2 | ~2,700 | app.py 40%, new routers 80%+ |
| After Wave 3 | ~1,700 | app.py 50%, new routers 80%+ |
| After Wave 4 | ~500 (shell) | app.py 90%+, overall target 60%+ |

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Circular imports | `dependencies.py` breaks cycles; routers never import each other |
| Middleware ordering | Middleware stays in `app.py`; routers inherit it |
| WebSocket endpoints (chat) | Keep in dedicated `chat.py` router, test with async client |
| Frontend breaking | Pure URL refactor — no path changes, no breaking |
| Test file relocation | Tests use HTTP paths, not Python imports — zero impact |

## 10. Non-Goals

- **No API versioning** in this phase (future consideration)
- **No schema changes** — response models stay as-is
- **No business logic changes** — pure structural refactor
- **No new endpoints** — only move existing ones

---

*Architect 📐 | Router Split Design Spec v1.0*
