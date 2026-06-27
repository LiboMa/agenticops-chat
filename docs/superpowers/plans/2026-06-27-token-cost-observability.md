# Token & Cost Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-message token+cost display in the chat box and a Token & Cost dashboard (Web + CLI) that analyzes Bedrock spend by agent / actor / model across day / month / year.

**Architecture:** A pure cost function (`cost.py`) converts token dicts → USD via `config.token_cost_table`. Cost + actor are snapshotted onto `agent_logs` rows at write time (additive columns). A query service (`cost_service.py`) does real-time `GROUP BY` time-bucket + dimension over `agent_logs` (no rollup tables). A new `/api/cost/summary` router feeds the extended `AgentMetrics.tsx` scorecard dashboard (recharts), the chat per-message footer reuses the existing `/api/agent-logs/timeline/{trace_id}`, and an `aiops cost` CLI command reuses `cost_service`.

**Tech Stack:** Python 3.12, SQLAlchemy (sync), FastAPI, pydantic-settings, pytest; React + TypeScript + TanStack Query + recharts; Rich (CLI).

## Global Constraints

- DB migrations are **additive only** via the startup `ALTER TABLE … ADD COLUMN` pattern in `models.py` (`run_migrations`, guarded by `insp.get_columns`). No Alembic. All new columns nullable or defaulted.
- All timestamps are **UTC** (`datetime.now(timezone.utc)`); time bucketing is UTC.
- Cost is **snapshotted at write time** — never recomputed historically.
- Cost computation **never raises**: unknown model → `0.0` + one WARNING log.
- Token write path is **fire-and-forget** (errors logged, never raised) — preserve that in `agent_log_service`.
- Test commands run from repo root with `.venv/bin/python -m pytest … -p no:cacheprovider`.
- Commit with `git commit --no-verify` (Code Defender hook bypass per repo policy).
- Frontend: no new lib beyond **recharts**; `npx tsc --noEmit` must pass.

---

### Task 1: Pure cost computation module

**Files:**
- Create: `src/agenticops/cost.py`
- Test: `tests/test_cost.py`
- Modify: `src/agenticops/config.py:748-755` (add `cache_write` + `opus-4-8` to `token_cost_table`)

**Interfaces:**
- Consumes: `agenticops.config.settings.token_cost_table` (dict[str, dict[str, float]]).
- Produces:
  - `normalize_model_key(model_id: str) -> str`
  - `compute_cost(model_id: str, tokens: dict) -> float`  — `tokens` keys: `input, output, cache_read, cache_write` (missing → 0)
  - `compute_cost_breakdown(model_id: str, tokens: dict) -> dict`  — returns `{"input","output","cache_read","cache_write","total"}` USD floats

- [ ] **Step 1: Extend the cost table in config.py**

Replace the `token_cost_table` default (config.py ~line 748) with:

```python
    token_cost_table: dict[str, dict[str, float]] = Field(
        default={
            "claude-opus-4-8":   {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
            "claude-opus-4-6":   {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
            "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
            "claude-haiku-4-5":  {"input": 0.80, "output": 4.0,  "cache_read": 0.08, "cache_write": 1.00},
        },
        description="Token cost rates per 1M tokens by model family",
    )
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_cost.py
from agenticops.cost import normalize_model_key, compute_cost, compute_cost_breakdown


def test_normalize_strips_prefixes_and_version():
    assert normalize_model_key("global.anthropic.claude-opus-4-6-v1") == "claude-opus-4-6"
    assert normalize_model_key("us.anthropic.claude-opus-4-8") == "claude-opus-4-8"
    assert normalize_model_key("global.anthropic.claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert normalize_model_key("global.anthropic.claude-haiku-4-5-20251001-v1:0") == "claude-haiku-4-5"


def test_compute_cost_opus48():
    # 1M input @15 + 1M output @75 + 1M cache_read @1.50 + 1M cache_write @18.75
    tokens = {"input": 1_000_000, "output": 1_000_000, "cache_read": 1_000_000, "cache_write": 1_000_000}
    assert compute_cost("global.anthropic.claude-opus-4-8", tokens) == 15.0 + 75.0 + 1.50 + 18.75


def test_compute_cost_missing_keys_default_zero():
    assert compute_cost("global.anthropic.claude-sonnet-4-6", {"input": 1_000_000}) == 3.0


def test_unknown_model_returns_zero(caplog):
    assert compute_cost("some.unknown.model", {"input": 1_000_000}) == 0.0


def test_breakdown_sums_to_total():
    tokens = {"input": 500_000, "output": 200_000, "cache_read": 100_000, "cache_write": 0}
    b = compute_cost_breakdown("global.anthropic.claude-sonnet-4-6", tokens)
    assert round(b["total"], 6) == round(b["input"] + b["output"] + b["cache_read"] + b["cache_write"], 6)
    assert b["input"] == 0.5 * 3.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cost.py -p no:cacheprovider -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agenticops.cost'`

- [ ] **Step 4: Write the implementation**

```python
# src/agenticops/cost.py
"""Pure token→USD cost computation, table-driven from config.token_cost_table.

Never raises: an unknown model yields 0.0 + one WARNING. Snapshot semantics —
callers store the returned value; historical cost is not recomputed.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_TOKEN_KEYS = ("input", "output", "cache_read", "cache_write")


def normalize_model_key(model_id: str) -> str:
    """Map a full Bedrock model id to a token_cost_table key.

    e.g. 'global.anthropic.claude-opus-4-6-v1' -> 'claude-opus-4-6'
         'global.anthropic.claude-haiku-4-5-20251001-v1:0' -> 'claude-haiku-4-5'
    """
    if not model_id:
        return ""
    key = model_id.strip()
    # drop region/provider prefixes
    key = re.sub(r"^(global|us|eu|apac)\.", "", key)
    key = re.sub(r"^anthropic\.", "", key)
    # claude-<family>-<major>-<minor> ... keep through the minor version
    m = re.match(r"(claude-[a-z]+-\d+-\d+)", key)
    return m.group(1) if m else key


def _rates(model_id: str) -> dict | None:
    from agenticops.config import settings
    table = settings.token_cost_table or {}
    key = normalize_model_key(model_id)
    rates = table.get(key)
    if rates is None:
        logger.warning("No cost rates for model '%s' (key '%s'); cost=0", model_id, key)
    return rates


def compute_cost_breakdown(model_id: str, tokens: dict) -> dict:
    """Per-category USD cost. Missing token keys / unknown model → 0."""
    rates = _rates(model_id)
    out = {k: 0.0 for k in _TOKEN_KEYS}
    if rates:
        for k in _TOKEN_KEYS:
            out[k] = (int(tokens.get(k, 0) or 0) / 1_000_000.0) * float(rates.get(k, 0.0))
    out["total"] = sum(out[k] for k in _TOKEN_KEYS)
    return out


def compute_cost(model_id: str, tokens: dict) -> float:
    """Total USD cost for a token dict. Never raises."""
    return compute_cost_breakdown(model_id, tokens)["total"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cost.py -p no:cacheprovider -q`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/cost.py tests/test_cost.py src/agenticops/config.py
git commit --no-verify -m "feat(cost): pure token→USD cost module + cache_write/opus-4-8 rates"
```

---

### Task 2: Schema migration — agent_logs cost/actor columns + chat_messages.trace_id

**Files:**
- Modify: `src/agenticops/models.py` (`AgentLog` ~line 582; `ChatMessage` ~line 802; `run_migrations` ~line 1005)
- Test: `tests/test_cost_migration.py`

**Interfaces:**
- Produces: `AgentLog.cache_write_tokens:int`, `AgentLog.cost_usd:float`, `AgentLog.actor_type:str`, `AgentLog.actor_id:str|None`, index `idx_agent_log_actor_time`; `ChatMessage.trace_id:str|None`.

- [ ] **Step 1: Add columns to the ORM models**

In `AgentLog` (after `cache_read_tokens`, ~line 599) add:
```python
    cache_write_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    actor_type: Mapped[str] = mapped_column(String(20), default="system")
    actor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
```
In `AgentLog.__table_args__` add a third index:
```python
        Index("idx_agent_log_actor_time", "actor_type", "created_at"),
```
In `ChatMessage` (after `token_usage`, ~line 811) add:
```python
    trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
```

- [ ] **Step 2: Add the additive migration block**

In `run_migrations` in models.py, immediately after the existing `agent_logs` token-columns migration block (the one ending with `CREATE INDEX IF NOT EXISTS idx_agent_log_trace`), append:

```python
    # Migration: add cost/actor columns to agent_logs
    if insp.has_table("agent_logs"):
        cols = {c["name"] for c in insp.get_columns("agent_logs")}
        more = []
        if "cache_write_tokens" not in cols:
            more.append("ALTER TABLE agent_logs ADD COLUMN cache_write_tokens INTEGER DEFAULT 0")
        if "cost_usd" not in cols:
            more.append("ALTER TABLE agent_logs ADD COLUMN cost_usd FLOAT DEFAULT 0")
        if "actor_type" not in cols:
            more.append("ALTER TABLE agent_logs ADD COLUMN actor_type VARCHAR(20) DEFAULT 'system'")
        if "actor_id" not in cols:
            more.append("ALTER TABLE agent_logs ADD COLUMN actor_id VARCHAR(100)")
        if more:
            with engine.connect() as conn:
                for stmt in more:
                    conn.execute(text(stmt))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_log_actor_time ON agent_logs(actor_type, created_at)"))
                conn.commit()

    # Migration: add trace_id to chat_messages
    if insp.has_table("chat_messages"):
        cols = {c["name"] for c in insp.get_columns("chat_messages")}
        if "trace_id" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN trace_id VARCHAR(36)"))
                conn.commit()
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_cost_migration.py
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from agenticops.models import Base, AgentLog, init_db


def test_agent_log_has_cost_actor_columns():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("agent_logs")}
    assert {"cache_write_tokens", "cost_usd", "actor_type", "actor_id"} <= cols
    chat_cols = {c["name"] for c in inspect(eng).get_columns("chat_messages")}
    assert "trace_id" in chat_cols


def test_agent_log_defaults():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(eng)
    s = sessionmaker(bind=eng)()
    row = AgentLog(agent_name="rca", action="x", input_summary="", output_summary="")
    s.add(row); s.commit(); s.refresh(row)
    assert row.cost_usd == 0.0
    assert row.actor_type == "system"
    assert row.cache_write_tokens == 0
```

Note: if `init_db` does not auto-run `run_migrations` on a fresh engine, the `create_all` from the ORM models already creates the new columns (they're in the model). The migration block only matters for pre-existing DBs; the test covers the model definition. Verify `init_db` calls `Base.metadata.create_all`.

- [ ] **Step 4: Run test to verify it fails, then passes**

Run: `.venv/bin/python -m pytest tests/test_cost_migration.py -p no:cacheprovider -q`
Expected: FAIL before Step 1-2 edits applied; PASS after.

- [ ] **Step 5: Verify pre-existing-DB migration path**

Run against the real dev DB to confirm the ALTER blocks apply cleanly:
```bash
.venv/bin/python -c "from agenticops.models import init_db; init_db(); print('migration ok')"
```
Expected: prints `migration ok`, no exception.

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/models.py tests/test_cost_migration.py
git commit --no-verify -m "feat(cost): additive agent_logs cost/actor columns + chat_messages.trace_id"
```

---

### Task 3: Write-path — snapshot cost + cache_write + actor in agent_log_service

**Files:**
- Modify: `src/agenticops/services/agent_log_service.py`
- Test: `tests/test_agent_log_cost.py`

**Interfaces:**
- Consumes: `agenticops.cost.compute_cost` (Task 1); `AgentLog` columns (Task 2).
- Produces: `_AgentTracker.cache_write_tokens`; `log_agent_call(..., cache_write_tokens=0, actor_type="system", actor_id=None)`; `track_agent(agent_name, action, input_summary, parent_agent=None, actor_type="system", actor_id=None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_log_cost.py
from unittest.mock import patch, MagicMock
from agenticops.services import agent_log_service as svc


def test_log_agent_call_snapshots_cost_and_actor():
    captured = {}
    class FakeDB:
        def add(self, obj): captured["obj"] = obj
    from contextlib import contextmanager
    @contextmanager
    def fake_session():
        yield FakeDB()
    with patch("agenticops.models.get_db_session", fake_session):
        svc.log_agent_call(
            agent_name="rca", action="rca", input_summary="x",
            input_tokens=1_000_000, output_tokens=0,
            model_id="global.anthropic.claude-sonnet-4-6",
            actor_type="user", actor_id="malibo",
        )
    obj = captured["obj"]
    assert obj.cost_usd == 3.0          # 1M input @ $3/1M sonnet
    assert obj.actor_type == "user"
    assert obj.actor_id == "malibo"
    assert obj.cache_write_tokens == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_log_cost.py -p no:cacheprovider -q`
Expected: FAIL — `TypeError: log_agent_call() got an unexpected keyword argument 'actor_type'`

- [ ] **Step 3: Implement**

In `_AgentTracker.__slots__` add `"cache_write_tokens"`; init `self.cache_write_tokens = 0`; in `set_result` add `self.cache_write_tokens = usage.get("cacheWriteInputTokens", 0)`.

Extend `log_agent_call` signature with `cache_write_tokens: int = 0, actor_type: str = "system", actor_id: Optional[str] = None`. Inside, before the `db.add`, compute cost:
```python
        from agenticops.cost import compute_cost
        cost_usd = compute_cost(model_id or "", {
            "input": input_tokens, "output": output_tokens,
            "cache_read": cache_read_tokens, "cache_write": cache_write_tokens,
        })
```
Add to the `AgentLog(...)` kwargs: `cache_write_tokens=cache_write_tokens, cost_usd=cost_usd, actor_type=actor_type, actor_id=actor_id`.

Extend `track_agent` signature with `actor_type: str = "system", actor_id: Optional[str] = None`; pass `cache_write_tokens=tracker.cache_write_tokens, actor_type=actor_type, actor_id=actor_id` into its `log_agent_call(...)` call.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent_log_cost.py -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/services/agent_log_service.py tests/test_agent_log_cost.py
git commit --no-verify -m "feat(cost): snapshot cost_usd + cache_write + actor on agent_logs write"
```

---

### Task 4: Aggregation service — cost_service.cost_summary

**Files:**
- Create: `src/agenticops/services/cost_service.py`
- Test: `tests/test_cost_service.py`

**Interfaces:**
- Consumes: `AgentLog` (Task 2 columns).
- Produces:
  `cost_summary(start: datetime, end: datetime, bucket: str = "day", group_by: str = "agent", filters: dict | None = None) -> dict`
  returning `{"totals": {...}, "series": [...], "breakdown": [...]}` (shapes below).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cost_service.py
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import agenticops.models as models
from agenticops.models import Base, AgentLog, init_db
from agenticops.services import cost_service


def _seed(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(eng)
    Session = sessionmaker(bind=eng)
    from contextlib import contextmanager
    @contextmanager
    def fake_session():
        s = Session()
        try:
            yield s; s.commit()
        finally:
            s.close()
    monkeypatch.setattr(models, "get_db_session", fake_session)
    s = Session()
    d1 = datetime(2026, 6, 20, 10, tzinfo=timezone.utc)
    d2 = datetime(2026, 6, 21, 10, tzinfo=timezone.utc)
    s.add_all([
        AgentLog(agent_name="rca", action="a", input_summary="", output_summary="",
                 input_tokens=1000, output_tokens=500, cost_usd=2.0, actor_type="user", actor_id="malibo",
                 model_id="claude-opus-4-8", created_at=d1),
        AgentLog(agent_name="sre", action="a", input_summary="", output_summary="",
                 input_tokens=2000, output_tokens=800, cost_usd=3.0, actor_type="system",
                 model_id="claude-opus-4-8", created_at=d2),
    ])
    s.commit(); s.close()


def test_cost_summary_totals_and_buckets(monkeypatch):
    _seed(monkeypatch)
    out = cost_service.cost_summary(
        start=datetime(2026, 6, 19, tzinfo=timezone.utc),
        end=datetime(2026, 6, 22, tzinfo=timezone.utc),
        bucket="day", group_by="agent",
    )
    assert round(out["totals"]["cost_usd"], 2) == 5.0
    assert out["totals"]["call_count"] == 2
    # two distinct day buckets
    buckets = {row["bucket"] for row in out["series"]}
    assert buckets == {"2026-06-20", "2026-06-21"}
    # breakdown by agent, sorted desc by cost
    assert out["breakdown"][0]["key"] == "sre"
    assert out["breakdown"][0]["cost_usd"] == 3.0


def test_cost_summary_actor_filter(monkeypatch):
    _seed(monkeypatch)
    out = cost_service.cost_summary(
        start=datetime(2026, 6, 19, tzinfo=timezone.utc),
        end=datetime(2026, 6, 22, tzinfo=timezone.utc),
        bucket="day", group_by="actor", filters={"actor_type": "user"},
    )
    assert round(out["totals"]["cost_usd"], 2) == 2.0
    assert out["breakdown"][0]["key"] == "user"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cost_service.py -p no:cacheprovider -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agenticops.services.cost_service'`

- [ ] **Step 3: Implement**

```python
# src/agenticops/services/cost_service.py
"""Real-time token/cost aggregation over agent_logs (no rollup tables)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func

_GROUP_COL = {"agent": "agent_name", "actor": "actor_type", "model": "model_id"}
_BUCKET_FMT = {"hour": "%Y-%m-%d %H:00", "day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}


def _bucket_expr(col, bucket: str):
    """DB-portable time-bucket string. SQLite: strftime; else fall back to date()."""
    fmt = _BUCKET_FMT.get(bucket, "%Y-%m-%d")
    try:
        return func.strftime(fmt, col)            # sqlite
    except Exception:
        return func.date(col)


def cost_summary(
    start: datetime,
    end: datetime,
    bucket: str = "day",
    group_by: str = "agent",
    filters: Optional[dict] = None,
) -> dict:
    from agenticops.models import AgentLog, get_db_session

    filters = filters or {}
    gcol_name = _GROUP_COL.get(group_by, "agent_name")

    with get_db_session() as db:
        gcol = getattr(AgentLog, gcol_name)
        bexpr = _bucket_expr(AgentLog.created_at, bucket)

        def base_query():
            q = db.query(AgentLog).filter(
                AgentLog.created_at >= start, AgentLog.created_at < end
            )
            if filters.get("actor_type"):
                q = q.filter(AgentLog.actor_type == filters["actor_type"])
            if filters.get("actor_id"):
                q = q.filter(AgentLog.actor_id == filters["actor_id"])
            if filters.get("agent_name"):
                q = q.filter(AgentLog.agent_name == filters["agent_name"])
            if filters.get("model_id"):
                q = q.filter(AgentLog.model_id == filters["model_id"])
            return q

        # totals
        t = base_query().with_entities(
            func.coalesce(func.sum(AgentLog.input_tokens), 0),
            func.coalesce(func.sum(AgentLog.output_tokens), 0),
            func.coalesce(func.sum(AgentLog.cache_read_tokens), 0),
            func.coalesce(func.sum(AgentLog.cache_write_tokens), 0),
            func.coalesce(func.sum(AgentLog.cost_usd), 0.0),
            func.count(AgentLog.id),
        ).one()
        ti, to, tcr, tcw, tcost, tcalls = t
        total_tokens = ti + to + tcr + tcw
        cache_hit_pct = round(100.0 * tcr / (ti + tcr), 1) if (ti + tcr) else 0.0
        totals = {
            "input": ti, "output": to, "cache_read": tcr, "cache_write": tcw,
            "total_tokens": total_tokens, "cost_usd": round(tcost, 6),
            "cache_hit_pct": cache_hit_pct, "call_count": tcalls,
        }

        # series: bucket × group
        srows = base_query().with_entities(
            bexpr.label("b"), gcol.label("g"),
            func.coalesce(func.sum(AgentLog.cost_usd), 0.0),
            func.coalesce(func.sum(AgentLog.input_tokens + AgentLog.output_tokens
                                   + AgentLog.cache_read_tokens + AgentLog.cache_write_tokens), 0),
        ).group_by("b", "g").all()
        series_map: dict[str, dict] = {}
        for b, g, cost, toks in srows:
            entry = series_map.setdefault(b, {"bucket": b, "cost_usd": 0.0, "total_tokens": 0, "by": {}})
            entry["cost_usd"] = round(entry["cost_usd"] + (cost or 0.0), 6)
            entry["total_tokens"] += int(toks or 0)
            entry["by"][g or "unknown"] = {"cost_usd": round(cost or 0.0, 6), "tokens": int(toks or 0)}
        series = sorted(series_map.values(), key=lambda r: r["bucket"])

        # breakdown by dimension
        brows = base_query().with_entities(
            gcol.label("g"),
            func.count(AgentLog.id),
            func.coalesce(func.sum(AgentLog.input_tokens), 0),
            func.coalesce(func.sum(AgentLog.output_tokens), 0),
            func.coalesce(func.sum(AgentLog.cache_read_tokens), 0),
            func.coalesce(func.sum(AgentLog.cache_write_tokens), 0),
            func.coalesce(func.sum(AgentLog.cost_usd), 0.0),
        ).group_by("g").all()
        breakdown = []
        for g, calls, bi, bo, bcr, bcw, bcost in brows:
            toks = bi + bo + bcr + bcw
            breakdown.append({
                "key": g or "unknown", "calls": calls,
                "input": bi, "output": bo, "cache_read": bcr, "cache_write": bcw,
                "tokens": toks,
                "cache_hit_pct": round(100.0 * bcr / (bi + bcr), 1) if (bi + bcr) else 0.0,
                "cost_usd": round(bcost or 0.0, 6),
            })
        breakdown.sort(key=lambda r: r["cost_usd"], reverse=True)

        return {"totals": totals, "series": series, "breakdown": breakdown}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cost_service.py -p no:cacheprovider -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/services/cost_service.py tests/test_cost_service.py
git commit --no-verify -m "feat(cost): cost_service real-time day/month/year aggregation"
```

---

### Task 5: API — /api/cost/summary router + cost on agent-logs endpoints

**Files:**
- Create: `src/agenticops/web/routers/cost.py`
- Modify: `src/agenticops/web/app.py:253-262` (register router); `src/agenticops/web/routers/agent_logs.py` (add `cost_usd` to list + summary + timeline)
- Test: `tests/test_cost_api.py`

**Interfaces:**
- Consumes: `cost_service.cost_summary` (Task 4).
- Produces: `GET /api/cost/summary` returning the Task-4 dict; `period` shorthand → (start, end, bucket).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cost_api.py
from fastapi.testclient import TestClient
from unittest.mock import patch
from agenticops.web.app import app

client = TestClient(app)


def test_cost_summary_endpoint():
    fake = {"totals": {"cost_usd": 5.0, "call_count": 2}, "series": [], "breakdown": []}
    with patch("agenticops.services.cost_service.cost_summary", return_value=fake):
        r = client.get("/api/cost/summary?period=30d&group_by=agent")
    assert r.status_code == 200
    assert r.json()["totals"]["cost_usd"] == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cost_api.py -p no:cacheprovider -q`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 3: Implement the router**

```python
# src/agenticops/web/routers/cost.py
"""Token & cost summary API — real-time aggregation over agent_logs."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter()

_PERIOD = {  # shorthand → (timedelta, default bucket)
    "7d": (timedelta(days=7), "day"),
    "30d": (timedelta(days=30), "day"),
    "day": (timedelta(days=30), "day"),
    "month": (timedelta(days=365), "month"),
    "year": (timedelta(days=365 * 3), "year"),
}


@router.get("/api/cost/summary")
async def api_cost_summary(
    period: str = Query("30d"),
    bucket: Optional[str] = None,
    group_by: str = Query("agent"),
    actor_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    model_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    from agenticops.services import cost_service

    delta, default_bucket = _PERIOD.get(period, _PERIOD["30d"])
    end_dt = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)
    start_dt = datetime.fromisoformat(start) if start else (end_dt - delta)
    filters = {k: v for k, v in {
        "actor_type": actor_type, "actor_id": actor_id,
        "agent_name": agent_name, "model_id": model_id,
    }.items() if v}
    return cost_service.cost_summary(
        start=start_dt, end=end_dt,
        bucket=bucket or default_bucket, group_by=group_by, filters=filters,
    )
```

- [ ] **Step 4: Register the router in app.py**

After the `agent_logs` router registration (app.py ~line 254) add:
```python
from agenticops.web.routers import cost as _cost_router
app.include_router(_cost_router.router)
```

- [ ] **Step 5: Add cost_usd to agent_logs endpoints**

In `routers/agent_logs.py`: add `"cost_usd": r.cost_usd, "cache_write_tokens": r.cache_write_tokens, "actor_type": r.actor_type, "actor_id": r.actor_id` to the list-row dict (`/api/agent-logs`); add `func.sum(AgentLog.cost_usd)` to the per-agent and per-model aggregations in `/api/agent-logs/summary` (new `cost_usd` field per group + top-level `total_cost_usd`); add per-node `cost_usd` to the timeline endpoint.

- [ ] **Step 6: Run tests to verify pass + no regression**

Run: `.venv/bin/python -m pytest tests/test_cost_api.py tests/test_agent_logs*.py -p no:cacheprovider -q`
Expected: PASS (new test + existing agent-logs tests still green)

- [ ] **Step 7: Commit**

```bash
git add src/agenticops/web/routers/cost.py src/agenticops/web/app.py src/agenticops/web/routers/agent_logs.py tests/test_cost_api.py
git commit --no-verify -m "feat(cost): /api/cost/summary + cost_usd on agent-logs endpoints"
```

---

### Task 6: Attribution wiring — actor_type/actor_id at every entry point

**Files:**
- Modify: `src/agenticops/web/app.py` (SSE chat handler — `track_agent` call), `src/agenticops/cli/main.py` (chat REPL `track_agent` call), `src/agenticops/services/pipeline_service.py`, `src/agenticops/services/rca_service.py`, `src/agenticops/services/resolution_service.py`, `src/agenticops/scheduler/scheduler.py`
- Test: `tests/test_actor_attribution.py`

**Interfaces:**
- Consumes: `track_agent(..., actor_type, actor_id)` (Task 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_actor_attribution.py
import inspect
from agenticops.services import agent_log_service


def test_track_agent_accepts_actor_params():
    sig = inspect.signature(agent_log_service.track_agent)
    assert "actor_type" in sig.parameters
    assert "actor_id" in sig.parameters


def test_web_sse_passes_user_actor():
    # the SSE handler must pass actor_type="user" to track_agent
    import agenticops.web.app as appmod
    src = inspect.getsource(appmod)
    assert 'actor_type="user"' in src


def test_background_services_pass_system_actor():
    import agenticops.services.pipeline_service as p
    src = inspect.getsource(p)
    assert 'actor_type=' in src  # system/schedule attribution present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_actor_attribution.py -p no:cacheprovider -q`
Expected: FAIL on `test_web_sse_passes_user_actor` / background test (params exist from Task 3, wiring not done)

- [ ] **Step 3: Wire each entry point**

- Web SSE chat handler (the `with track_agent("main", "chat", …)` in app.py stream path): change to
  ```python
  _actor = getattr(getattr(request, "state", None), "user", None)
  with track_agent("main", "chat", user_input[:200],
                   actor_type="user" if _actor else "system",
                   actor_id=getattr(_actor, "username", None)) as _trk:
  ```
- CLI chat REPL (`with _track("main", "chat", …)` in cli/main.py): add `actor_type="cli", actor_id=__import__("getpass").getuser()`.
- `pipeline_service` / `rca_service` / `resolution_service`: where they invoke agents through `track_agent`, pass `actor_type="system"`. (If they call agents without `track_agent`, the default `"system"` already applies — add an explicit `actor_type="system"` comment-anchored call only where `track_agent` is already used.)
- `scheduler/scheduler.py`: where a scheduled run invokes an agent, pass `actor_type="schedule", actor_id=<schedule name>`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_actor_attribution.py -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/web/app.py src/agenticops/cli/main.py src/agenticops/services/*.py src/agenticops/scheduler/scheduler.py tests/test_actor_attribution.py
git commit --no-verify -m "feat(cost): attribute token spend to user/cli/system/schedule actors"
```

---

### Task 7: Per-message token+cost in chat persist + API response

**Files:**
- Modify: `src/agenticops/web/app.py` (SSE assistant-persist ~line 4492-4498: extend token_usage JSON + set message trace_id), `src/agenticops/web/schemas.py` (`ChatMessageResponse`), `src/agenticops/cli/main.py` (`_cli_persist_message` token_usage shape)
- Test: `tests/test_message_token_usage.py`

**Interfaces:**
- Consumes: `cost.compute_cost` (Task 1), `ChatMessage.trace_id` (Task 2), `get_trace_id` (config).
- Produces: persisted `token_usage = {"input","output","cache_read","cache_write","cost_usd","model"}` + `trace_id` on assistant messages; `ChatMessageResponse.trace_id` + `cost_usd`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_message_token_usage.py
from agenticops.cost import compute_cost


def test_message_token_usage_includes_cost():
    # the persisted shape must carry cost_usd derived from compute_cost
    tu = {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_write": 0,
          "model": "global.anthropic.claude-sonnet-4-6"}
    tu["cost_usd"] = compute_cost(tu["model"], tu)
    assert tu["cost_usd"] == 3.0
    assert set(tu) >= {"input", "output", "cache_read", "cache_write", "cost_usd", "model"}


def test_schema_has_trace_and_cost_fields():
    from agenticops.web.schemas import ChatMessageResponse
    fields = ChatMessageResponse.model_fields
    assert "trace_id" in fields
    assert "cost_usd" in fields
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_message_token_usage.py -p no:cacheprovider -q`
Expected: FAIL — `ChatMessageResponse` has no `trace_id`/`cost_usd`

- [ ] **Step 3: Implement**

In `web/schemas.py` `ChatMessageResponse`, add `trace_id: Optional[str] = None` and `cost_usd: Optional[float] = None`.

In the SSE assistant-persist block (app.py ~4492): replace the `token_usage={"input": …, "output": …}` construction with the extended dict including `cache_read`, `cache_write`, `model` (from `get_agent_model_config("main")[0]`), and `cost_usd = compute_cost(model, tu)`; also set the new `ChatMessage.trace_id = get_trace_id()`. Where `ChatMessageResponse` is built from a row, populate `trace_id=row.trace_id` and `cost_usd=(row.token_usage or {}).get("cost_usd")`.

In `cli/main.py` `_cli_persist_message`, build the same extended `token_usage` shape via `compute_cost`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_message_token_usage.py -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/web/app.py src/agenticops/web/schemas.py src/agenticops/cli/main.py tests/test_message_token_usage.py
git commit --no-verify -m "feat(cost): per-message token_usage carries cost_usd + trace_id"
```

---

### Task 8: CLI — `aiops cost` command

**Files:**
- Modify: `src/agenticops/cli/main.py` (add `cost` command), `src/agenticops/cli/display.py` (refactor `/tokens` cost calc to use `cost.compute_cost`)
- Test: `tests/test_cli_cost.py`

**Interfaces:**
- Consumes: `cost_service.cost_summary` (Task 4).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_cost.py
from unittest.mock import patch
from click.testing import CliRunner
from agenticops.cli.main import cli  # adjust import to the click/typer group name


def test_aiops_cost_runs():
    fake = {"totals": {"cost_usd": 5.0, "total_tokens": 3300, "cache_hit_pct": 60.0, "call_count": 2},
            "series": [], "breakdown": [{"key": "rca", "calls": 1, "tokens": 1500,
                                         "cache_hit_pct": 0.0, "cost_usd": 2.0}]}
    with patch("agenticops.services.cost_service.cost_summary", return_value=fake):
        res = CliRunner().invoke(cli, ["cost", "--period", "month", "--by", "agent"])
    assert res.exit_code == 0
    assert "5.0" in res.output or "$5" in res.output
    assert "rca" in res.output
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_cost.py -p no:cacheprovider -q`
Expected: FAIL — no `cost` command (verify the actual group symbol in cli/main.py first; adjust import).

- [ ] **Step 3: Implement**

Add a `cost` command to the existing CLI group (match the framework already used — click or typer). It computes `start/end` from `--period {day,month,year}` + `--days N`, calls `cost_service.cost_summary(group_by=--by)`, and renders a Rich table: a totals line (`Total $X · N tokens · cache Y%`) + a breakdown table (`key · calls · tokens · cache% · $cost`). In `cli/display.py`, replace the inline per-model cost math in the `/tokens` handler with `from agenticops.cost import compute_cost`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_cli_cost.py -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/cli/main.py src/agenticops/cli/display.py tests/test_cli_cost.py
git commit --no-verify -m "feat(cost): aiops cost CLI command (day/month/year × agent/actor/model)"
```

---

### Task 9: Frontend — per-message footer (inline expand)

**Files:**
- Modify: `src/agenticops/web/frontend/src/components/chat/TokenMetrics.tsx`, the message renderer (`components/chat/MessageItem.tsx` or `MessageList.tsx`), `src/agenticops/web/frontend/src/api/types.ts` (message type += `trace_id`, `cost_usd`), `lib/chatStream.ts` (thread the fields)
- Create: `src/agenticops/web/frontend/src/hooks/useTraceTimeline.ts`
- Test: manual + `npx tsc --noEmit`

**Interfaces:**
- Consumes: `GET /api/agent-logs/timeline/{trace_id}` (existing, now with `cost_usd`); message `token_usage` + `trace_id` (Task 7).

- [ ] **Step 1: Extend the message type**

In `api/types.ts`, add to the chat message interface: `trace_id?: string; cost_usd?: number; token_usage?: { input: number; output: number; cache_read?: number; cache_write?: number; cost_usd?: number; model?: string };`

- [ ] **Step 2: Build the footer component**

Rewrite `TokenMetrics.tsx` to render the compact footer `↑{input} ↓{output} Σ{total} · ${cost} · details ▾` and, when expanded, fetch `/api/agent-logs/timeline/{trace_id}` via a new `useTraceTimeline(traceId, enabled)` TanStack Query hook and render a per-sub-agent table (agent · model · in · out · cache · $). Collapse/expand is local `useState`.

- [ ] **Step 3: Mount it under each assistant message**

In the message renderer, after the assistant message body, render `{m.role === 'assistant' && m.token_usage && <TokenMetrics msg={m} />}`.

- [ ] **Step 4: Verify types + build**

Run:
```bash
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build
```
Expected: no type errors; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/web/frontend/src
git commit --no-verify -m "feat(cost): per-message token+cost footer with inline sub-agent breakdown"
```

---

### Task 10: Frontend — Cost dashboard (scorecard + mix chart) in AgentMetrics

**Files:**
- Modify: `src/agenticops/web/frontend/src/pages/AgentMetrics.tsx`, `package.json` (+recharts)
- Create: `src/agenticops/web/frontend/src/hooks/useCostSummary.ts`
- Test: manual + `npx tsc --noEmit`

**Interfaces:**
- Consumes: `GET /api/cost/summary` (Task 5).

- [ ] **Step 1: Add recharts**

Run:
```bash
cd src/agenticops/web/frontend && npm install recharts
```

- [ ] **Step 2: Create the data hook**

`hooks/useCostSummary.ts`: a TanStack Query hook `useCostSummary({period, bucket, groupBy, filters})` calling `/api/cost/summary` with those query params, returning `{totals, series, breakdown}`.

- [ ] **Step 3: Build the scorecard UI**

In `AgentMetrics.tsx` add a "Cost" section (above or as a tab alongside the existing tables): (1) KPI cards row — Total Cost (with ▲/▼ vs previous period), Total Tokens, Cache-Hit %, Call Count from `totals`; (2) a recharts `ComposedChart` — stacked `Bar` per series `by`-dimension key (cost) + a `Line` for `total_tokens` on a right `YAxis`; controls: Day/Month/Year toggle (sets `period`+`bucket`) and a stack-by `<select>` (agent/actor/model → `groupBy`); (3) a recharts `PieChart` donut of `breakdown` cost share; (4) three breakdown bar-lists (By Agent / By Actor / By Model) from `breakdown` for the chosen dimension, each row clickable to set a filter.

- [ ] **Step 4: Verify types + build**

Run:
```bash
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build
```
Expected: no type errors; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/web/frontend/src src/agenticops/web/frontend/package.json src/agenticops/web/frontend/package-lock.json
git commit --no-verify -m "feat(cost): token & cost dashboard (scorecard + stacked-bar/line/donut mix)"
```

---

### Task 11: End-to-end verification + docs

**Files:**
- Modify: `CLAUDE.md` (web module note: cost endpoints/dashboard), `docs/WORKFLOW.md` (brief cost-observability note), `README.md` (feature mention)

- [ ] **Step 1: Full backend test sweep**

Run: `.venv/bin/python -m pytest tests/test_cost.py tests/test_cost_migration.py tests/test_agent_log_cost.py tests/test_cost_service.py tests/test_cost_api.py tests/test_actor_attribution.py tests/test_message_token_usage.py tests/test_cli_cost.py -p no:cacheprovider -q`
Expected: all PASS.

- [ ] **Step 2: Regression sweep on touched areas**

Run: `.venv/bin/python -m pytest tests/test_agent_logs*.py tests/test_chat* tests/test_notifier.py -p no:cacheprovider -q`
Expected: PASS (no regressions in agent-logs / chat).

- [ ] **Step 3: Manual E2E**

Start the server, run a chat turn → confirm the per-message footer shows tokens+cost and expands to sub-agents; trigger an auto-RCA → confirm it appears under `actor_type=system` in the dashboard; run `aiops cost --period month --by actor` and confirm totals match the Web dashboard for the same range.

- [ ] **Step 4: Update docs**

Add to `CLAUDE.md` web row: `/api/cost/summary` + cost dashboard; one line in `docs/WORKFLOW.md` and a README feature mention. Keep concise.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/WORKFLOW.md README.md
git commit --no-verify -m "docs: token & cost observability (dashboard + per-message + aiops cost)"
```

---

## Self-Review

**Spec coverage:** §4 schema → Task 2; §5 cost.py → Task 1; §6 attribution → Tasks 3+6; §7 cost_service → Task 4; §8 API → Task 5; §9.1 dashboard → Task 10; §9.2 per-message → Tasks 7+9; §9.3 CLI → Task 8; §10 tests → each task + Task 11; §3 cache_write passthrough → Task 3 (`set_result`). All sections covered.

**Placeholder scan:** No TBD/TODO; every code step has real code. Task 6 & 9 & 10 reference exact files; the only deliberate "verify the actual symbol" notes (CLI group name in Task 8, message renderer file in Task 9) are because those are framework-detail lookups the implementer confirms in-file — code shown for the change itself.

**Type consistency:** `cost_summary` return `{totals, series, breakdown}` consistent across Tasks 4/5/8/10; `token_usage` shape `{input,output,cache_read,cache_write,cost_usd,model}` consistent across Tasks 3/7/9; `actor_type`/`actor_id` consistent across Tasks 2/3/6; `compute_cost(model_id, tokens)` signature consistent across Tasks 1/3/7/8.
