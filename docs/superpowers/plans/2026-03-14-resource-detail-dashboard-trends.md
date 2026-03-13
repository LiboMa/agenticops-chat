# Resource Detail + Dashboard Trends Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add resource detail page with type-aware tabs and dashboard sparkline trends strip.

**Architecture:** 4 new backend endpoints (resource issues, fix-plans, related, dashboard trends) + 3 new frontend files (ResourceDetail page, 2 hooks) + modifications to Dashboard, App router, CommandPalette, Resources list. All data from existing DB tables via aggregation queries.

**Tech Stack:** FastAPI, SQLAlchemy, React, TanStack Query, Tailwind CSS (no chart library — pure CSS sparklines)

**Spec:** `docs/superpowers/specs/2026-03-14-resource-detail-dashboard-trends-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `src/agenticops/web/frontend/src/pages/ResourceDetail.tsx` | Detail page with 5 tabs |
| `src/agenticops/web/frontend/src/hooks/useResourceDetail.ts` | Hooks for resource detail data (issues, fix-plans, related) |
| `src/agenticops/web/frontend/src/hooks/useDashboardTrends.ts` | Hook for `/api/dashboard/trends` |
| `tests/test_resource_detail_api.py` | Backend API tests |
| `tests/test_dashboard_trends_api.py` | Dashboard trends API tests |

### Modified files
| File | Change |
|------|--------|
| `src/agenticops/web/app.py` | Add 4 API endpoints + response schemas |
| `src/agenticops/web/frontend/src/App.tsx` | Add `resources/:id` route |
| `src/agenticops/web/frontend/src/pages/Dashboard.tsx` | Add TrendStrip component |
| `src/agenticops/web/frontend/src/pages/Resources.tsx` | Row click navigates to detail |
| `src/agenticops/web/frontend/src/components/CommandPalette.tsx` | Fix resource route |
| `src/agenticops/web/frontend/src/api/types.ts` | Add trend + related resource types |

---

## Chunk 1: Backend API Endpoints

### Task 1: Resource Issues + Fix Plans endpoints

**Files:**
- Modify: `src/agenticops/web/app.py` (after line ~1388, the existing `api_get_resource`)
- Test: `tests/test_resource_detail_api.py`

- [ ] **Step 1: Write tests for resource issues and fix-plans endpoints**

Create `tests/test_resource_detail_api.py`:

```python
"""Tests for resource detail API endpoints."""
import pytest
from datetime import datetime, timedelta
from agenticops.models import (
    Base, AWSAccount, AWSResource, HealthIssue, FixPlan, RCAResult,
    FixExecution, get_engine, get_db_session,
)
from agenticops.web.app import app
from httpx import AsyncClient, ASGITransport


@pytest.fixture(autouse=True)
def setup_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def seed_data():
    """Seed a resource with related issues and fix plans."""
    with get_db_session() as db:
        acct = AWSAccount(name="test", account_id="123456789012", role_arn="arn:aws:iam::role/test", regions=["us-east-1"])
        db.add(acct)
        db.flush()
        res = AWSResource(
            account_id=acct.id, resource_id="i-abc123", resource_type="EC2",
            resource_name="web-prod", region="us-east-1", status="running",
            resource_metadata={"instance_type": "t3.large", "vpc_id": "vpc-111"},
            tags={"env": "prod"},
        )
        db.add(res)
        db.flush()
        issue1 = HealthIssue(
            resource_id="i-abc123", severity="high", source="metric_anomaly",
            title="CPU spike", description="CPU at 95%", status="open",
            detected_at=datetime.utcnow(),
        )
        issue2 = HealthIssue(
            resource_id="i-abc123", severity="medium", source="log_pattern",
            title="Disk full", description="Disk 90%", status="resolved",
            detected_at=datetime.utcnow() - timedelta(days=3),
            resolved_at=datetime.utcnow() - timedelta(days=2),
        )
        db.add_all([issue1, issue2])
        db.flush()
        rca = RCAResult(
            health_issue_id=issue2.id, root_cause="Disk full",
            confidence=0.9, fix_risk_level="L0",
        )
        db.add(rca)
        db.flush()
        plan = FixPlan(
            health_issue_id=issue2.id, rca_result_id=rca.id,
            risk_level="L0", title="Cleanup disk", summary="rm old logs",
            steps=[{"cmd": "rm /tmp/*.log"}], rollback_plan={},
            status="executed",
        )
        db.add(plan)
        db.flush()
        execution = FixExecution(
            fix_plan_id=plan.id, health_issue_id=issue2.id,
            status="succeeded", duration_ms=1200,
        )
        db.add(execution)
        return {"resource_id": res.id, "issue1_id": issue1.id, "issue2_id": issue2.id}


@pytest.mark.asyncio
async def test_resource_issues(seed_data):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/resources/{seed_data['resource_id']}/issues")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["title"] == "CPU spike"  # most recent first


@pytest.mark.asyncio
async def test_resource_fix_plans(seed_data):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/resources/{seed_data['resource_id']}/fix-plans")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Cleanup disk"
        assert data[0]["executions"][0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_resource_issues_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/resources/99999/issues")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_resource_detail_api.py -v`
Expected: FAIL — endpoints don't exist yet

- [ ] **Step 3: Implement the endpoints in app.py**

Add after the existing `api_get_resource` endpoint (~line 1388) in `src/agenticops/web/app.py`:

```python
class FixPlanWithExecutionsResponse(BaseModel):
    """Fix plan with its executions."""
    id: int
    health_issue_id: int
    rca_result_id: int
    risk_level: str
    title: str
    summary: str
    steps: list
    status: str
    approved_by: Optional[str]
    created_at: datetime
    executions: List[FixExecutionResponse] = []

    class Config:
        from_attributes = True


@app.get("/api/resources/{resource_id}/issues", response_model=List[HealthIssueResponse])
async def api_resource_issues(resource_id: int, limit: int = Query(default=20, le=100)):
    """List health issues for a resource."""
    with get_db_session() as session:
        resource = session.query(AWSResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        issues = (
            session.query(HealthIssue)
            .filter(HealthIssue.resource_id == resource.resource_id)
            .order_by(HealthIssue.detected_at.desc())
            .limit(limit)
            .all()
        )
        return [HealthIssueResponse.model_validate(i) for i in issues]


@app.get("/api/resources/{resource_id}/fix-plans", response_model=List[FixPlanWithExecutionsResponse])
async def api_resource_fix_plans(resource_id: int, limit: int = Query(default=20, le=100)):
    """List fix plans for a resource (via linked health issues)."""
    with get_db_session() as session:
        resource = session.query(AWSResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        plans = (
            session.query(FixPlan)
            .join(HealthIssue, FixPlan.health_issue_id == HealthIssue.id)
            .filter(HealthIssue.resource_id == resource.resource_id)
            .order_by(FixPlan.created_at.desc())
            .limit(limit)
            .all()
        )
        result = []
        for p in plans:
            resp = FixPlanWithExecutionsResponse.model_validate(p)
            resp.executions = [FixExecutionResponse.model_validate(e) for e in p.fix_executions]
            result.append(resp)
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_resource_detail_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_resource_detail_api.py src/agenticops/web/app.py
git commit -m "feat(api): add resource issues and fix-plans endpoints"
```

---

### Task 2: Resource Related endpoint

**Files:**
- Modify: `src/agenticops/web/app.py`
- Modify: `tests/test_resource_detail_api.py`

- [ ] **Step 1: Add test for related resources**

Append to `tests/test_resource_detail_api.py`:

```python
@pytest.mark.asyncio
async def test_resource_related(seed_data):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/resources/{seed_data['resource_id']}/related")
        assert resp.status_code == 200
        data = resp.json()
        # With no graph data, falls back to metadata parsing
        assert "network" in data
        assert "contains" in data
        # vpc_id from metadata should appear
        assert any(r["resource_id"] == "vpc-111" for r in data["network"])


@pytest.mark.asyncio
async def test_resource_related_infra_type():
    """Infrastructure resources get 'contains' populated."""
    with get_db_session() as db:
        acct = AWSAccount(name="test2", account_id="222222222222", role_arn="arn:aws:iam::role/t2", regions=["us-east-1"])
        db.add(acct)
        db.flush()
        vpc = AWSResource(
            account_id=acct.id, resource_id="vpc-222", resource_type="VPC",
            resource_name="prod-vpc", region="us-east-1", status="available",
            resource_metadata={"cidr_block": "10.0.0.0/16"}, tags={},
        )
        ec2 = AWSResource(
            account_id=acct.id, resource_id="i-in-vpc", resource_type="EC2",
            resource_name="server", region="us-east-1", status="running",
            resource_metadata={"vpc_id": "vpc-222"}, tags={},
        )
        db.add_all([vpc, ec2])
        db.flush()
        vpc_db_id = vpc.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/resources/{vpc_db_id}/related")
        assert resp.status_code == 200
        data = resp.json()
        assert any(r["resource_id"] == "i-in-vpc" for r in data["contains"])
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_resource_detail_api.py::test_resource_related -v`
Expected: FAIL

- [ ] **Step 3: Implement related endpoint**

Add to `src/agenticops/web/app.py`:

```python
class RelatedResourceItem(BaseModel):
    id: Optional[int] = None
    resource_id: str
    resource_type: str
    resource_name: Optional[str] = None
    status: Optional[str] = None
    detail: Optional[str] = None  # e.g. CIDR, SG rules summary


class RelatedResourcesResponse(BaseModel):
    network: List[RelatedResourceItem] = []
    contains: List[RelatedResourceItem] = []


# Resource types considered infrastructure (show "Contains" tab)
_INFRA_TYPES = {"VPC", "Subnet", "SecurityGroup", "RouteTable", "IGW", "NAT", "TGW", "InternetGateway", "NATGateway", "TransitGateway"}


@app.get("/api/resources/{resource_id}/related", response_model=RelatedResourcesResponse)
async def api_resource_related(resource_id: int):
    """Get related resources — network context or contained resources."""
    with get_db_session() as session:
        resource = session.query(AWSResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        meta = resource.resource_metadata or {}
        is_infra = resource.resource_type in _INFRA_TYPES
        network: list[RelatedResourceItem] = []
        contains: list[RelatedResourceItem] = []

        if is_infra:
            # Infrastructure resource: find resources that reference this one
            # e.g. VPC → find resources with vpc_id matching this resource_id
            ref_key = _infra_ref_key(resource.resource_type)
            if ref_key:
                children = (
                    session.query(AWSResource)
                    .filter(AWSResource.resource_metadata[ref_key].as_string() == resource.resource_id)
                    .limit(50)
                    .all()
                )
                for c in children:
                    contains.append(RelatedResourceItem(
                        id=c.id, resource_id=c.resource_id,
                        resource_type=c.resource_type,
                        resource_name=c.resource_name, status=c.status,
                    ))
        else:
            # Compute resource: extract network refs from metadata
            for key in ("vpc_id", "subnet_id", "security_groups", "subnet_ids"):
                val = meta.get(key)
                if not val:
                    continue
                ids = val if isinstance(val, list) else [val]
                for rid in ids:
                    if not isinstance(rid, str):
                        continue
                    linked = session.query(AWSResource).filter_by(resource_id=rid).first()
                    if linked:
                        network.append(RelatedResourceItem(
                            id=linked.id, resource_id=linked.resource_id,
                            resource_type=linked.resource_type,
                            resource_name=linked.resource_name, status=linked.status,
                        ))
                    else:
                        network.append(RelatedResourceItem(
                            resource_id=rid,
                            resource_type=_guess_type(rid),
                        ))

        return RelatedResourcesResponse(network=network, contains=contains)


def _infra_ref_key(resource_type: str) -> Optional[str]:
    """Map infra type to the metadata key other resources use to reference it."""
    return {
        "VPC": "vpc_id",
        "Subnet": "subnet_id",
        "SecurityGroup": "security_group_id",
    }.get(resource_type)


def _guess_type(resource_id: str) -> str:
    """Guess resource type from AWS ID prefix."""
    prefixes = {"vpc-": "VPC", "subnet-": "Subnet", "sg-": "SecurityGroup", "igw-": "IGW", "nat-": "NAT", "rtb-": "RouteTable"}
    for prefix, rtype in prefixes.items():
        if resource_id.startswith(prefix):
            return rtype
    return "Unknown"
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_resource_detail_api.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_resource_detail_api.py src/agenticops/web/app.py
git commit -m "feat(api): add resource related endpoint with metadata fallback"
```

---

### Task 3: Dashboard Trends endpoint

**Files:**
- Modify: `src/agenticops/web/app.py`
- Create: `tests/test_dashboard_trends_api.py`

- [ ] **Step 1: Write tests**

Create `tests/test_dashboard_trends_api.py`:

```python
"""Tests for dashboard trends API."""
import pytest
from datetime import datetime, timedelta
from agenticops.models import (
    Base, AWSAccount, AWSResource, HealthIssue, FixPlan, RCAResult,
    FixExecution, get_engine, get_db_session,
)
from agenticops.web.app import app
from httpx import AsyncClient, ASGITransport


@pytest.fixture(autouse=True)
def setup_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def seed_trends():
    now = datetime.utcnow()
    with get_db_session() as db:
        acct = AWSAccount(name="t", account_id="111111111111", role_arn="arn:aws:iam::role/t", regions=["us-east-1"])
        db.add(acct)
        db.flush()
        # Resources created over last 3 days
        for i in range(5):
            db.add(AWSResource(
                account_id=acct.id, resource_id=f"i-{i:03d}", resource_type="EC2",
                region="us-east-1", status="running",
                created_at=now - timedelta(days=i % 3),
            ))
        # Issues
        issue = HealthIssue(
            resource_id="i-000", severity="high", source="metric_anomaly",
            title="Test", description="Test", status="resolved",
            detected_at=now - timedelta(days=2),
            resolved_at=now - timedelta(days=1),
        )
        db.add(issue)
        db.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="test", confidence=0.9, fix_risk_level="L0")
        db.add(rca)
        db.flush()
        plan = FixPlan(
            health_issue_id=issue.id, rca_result_id=rca.id,
            risk_level="L0", title="fix", summary="fix it",
            steps=[], rollback_plan={}, status="executed",
        )
        db.add(plan)
        db.flush()
        db.add(FixExecution(
            fix_plan_id=plan.id, health_issue_id=issue.id,
            status="succeeded", duration_ms=3600000,
            started_at=now - timedelta(days=1, hours=1),
            completed_at=now - timedelta(days=1),
        ))


@pytest.mark.asyncio
async def test_dashboard_trends_default(seed_trends):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/dashboard/trends")
        assert resp.status_code == 200
        data = resp.json()
        assert "issues" in data
        assert "severity" in data
        assert "resources" in data
        assert "mttr" in data
        assert "fix_rate" in data
        assert "summary" in data
        assert data["summary"]["mttr_avg_hours"] > 0


@pytest.mark.asyncio
async def test_dashboard_trends_custom_days(seed_trends):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/dashboard/trends?days=30")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_trends_empty():
    """Empty DB should return empty arrays, not error."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/dashboard/trends")
        assert resp.status_code == 200
        data = resp.json()
        assert data["issues"] == []
        assert data["summary"]["mttr_avg_hours"] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_dashboard_trends_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implement trends endpoint**

Add to `src/agenticops/web/app.py` near the stats endpoint (~line 1260):

```python
@app.get("/api/dashboard/trends")
async def api_dashboard_trends(days: int = Query(default=7, ge=1, le=90)):
    """Dashboard trend data — 5 sparkline datasets."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    with get_db_session() as session:
        # 1) Issue trend: opened/resolved per day
        issues_opened = (
            session.query(
                func.date(HealthIssue.detected_at).label("d"),
                func.count().label("n"),
            )
            .filter(HealthIssue.detected_at >= cutoff)
            .group_by("d")
            .all()
        )
        issues_resolved = (
            session.query(
                func.date(HealthIssue.resolved_at).label("d"),
                func.count().label("n"),
            )
            .filter(HealthIssue.resolved_at >= cutoff, HealthIssue.resolved_at.isnot(None))
            .group_by("d")
            .all()
        )
        opened_map = {str(r.d): r.n for r in issues_opened}
        resolved_map = {str(r.d): r.n for r in issues_resolved}
        all_dates = sorted(set(opened_map) | set(resolved_map))
        issues = [{"date": d, "opened": opened_map.get(d, 0), "resolved": resolved_map.get(d, 0)} for d in all_dates]

        # 2) Severity distribution per day
        sev_rows = (
            session.query(
                func.date(HealthIssue.detected_at).label("d"),
                HealthIssue.severity,
                func.count().label("n"),
            )
            .filter(HealthIssue.detected_at >= cutoff)
            .group_by("d", HealthIssue.severity)
            .all()
        )
        sev_map: dict = {}
        for r in sev_rows:
            d = str(r.d)
            sev_map.setdefault(d, {"date": d, "critical": 0, "high": 0, "medium": 0, "low": 0})
            if r.severity in sev_map[d]:
                sev_map[d][r.severity] = r.n
        severity = [sev_map[d] for d in sorted(sev_map)]

        # 3) Resource changes per day
        res_rows = (
            session.query(
                func.date(AWSResource.created_at).label("d"),
                func.count().label("n"),
            )
            .filter(AWSResource.created_at >= cutoff)
            .group_by("d")
            .all()
        )
        resources = [{"date": str(r.d), "added": r.n} for r in res_rows]

        # 4) MTTR per day (resolved issues only)
        resolved_issues = (
            session.query(HealthIssue)
            .filter(
                HealthIssue.resolved_at >= cutoff,
                HealthIssue.resolved_at.isnot(None),
            )
            .all()
        )
        mttr_map: dict = {}
        for iss in resolved_issues:
            d = str(iss.resolved_at.date())
            hours = (iss.resolved_at - iss.detected_at).total_seconds() / 3600
            mttr_map.setdefault(d, []).append(hours)
        mttr = [{"date": d, "avg_hours": round(sum(v) / len(v), 1)} for d, v in sorted(mttr_map.items())]

        # 5) Fix success rate per day
        exec_rows = (
            session.query(
                func.date(FixExecution.completed_at).label("d"),
                FixExecution.status,
                func.count().label("n"),
            )
            .filter(FixExecution.completed_at >= cutoff, FixExecution.completed_at.isnot(None))
            .group_by("d", FixExecution.status)
            .all()
        )
        fx_map: dict = {}
        for r in exec_rows:
            d = str(r.d)
            fx_map.setdefault(d, {"total": 0, "succeeded": 0})
            fx_map[d]["total"] += r.n
            if r.status == "succeeded":
                fx_map[d]["succeeded"] += r.n
        fix_rate = [
            {"date": d, "total": v["total"], "succeeded": v["succeeded"],
             "rate": round(v["succeeded"] / v["total"] * 100, 1) if v["total"] else 0}
            for d, v in sorted(fx_map.items())
        ]

        # Summary
        total_opened = sum(d["opened"] for d in issues)
        total_resolved = sum(d["resolved"] for d in issues)
        all_mttr = [h for vals in mttr_map.values() for h in vals]
        avg_mttr = round(sum(all_mttr) / len(all_mttr), 1) if all_mttr else 0
        total_exec = sum(v["total"] for v in fx_map.values())
        total_succ = sum(v["succeeded"] for v in fx_map.values())
        net_resources = sum(d["added"] for d in resources)

        # Trend direction (compare first half vs second half)
        def _trend(values: list[float]) -> str:
            if len(values) < 2:
                return "flat"
            mid = len(values) // 2
            first = sum(values[:mid]) / mid if mid else 0
            second = sum(values[mid:]) / (len(values) - mid)
            if second > first * 1.1:
                return "up"
            elif second < first * 0.9:
                return "down"
            return "flat"

        mttr_values = [d["avg_hours"] for d in mttr]
        fix_values = [d["rate"] for d in fix_rate]

        return {
            "issues": issues,
            "severity": severity,
            "resources": resources,
            "mttr": mttr,
            "fix_rate": fix_rate,
            "summary": {
                "issues_opened": total_opened,
                "issues_resolved": total_resolved,
                "resource_net_change": net_resources,
                "mttr_avg_hours": avg_mttr,
                "mttr_trend": _trend(mttr_values),
                "fix_rate_pct": round(total_succ / total_exec * 100, 1) if total_exec else 0,
                "fix_rate_trend": _trend(fix_values),
            },
        }
```

Also add at the top imports if not already present: `from datetime import timedelta`

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_dashboard_trends_api.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run all backend tests together**

Run: `python -m pytest tests/test_resource_detail_api.py tests/test_dashboard_trends_api.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_dashboard_trends_api.py src/agenticops/web/app.py
git commit -m "feat(api): add dashboard trends endpoint with 5 sparkline datasets"
```

---

## Chunk 2: Frontend — Types, Hooks, Route

### Task 4: Add TypeScript types

**Files:**
- Modify: `src/agenticops/web/frontend/src/api/types.ts`

- [ ] **Step 1: Add types for trends, related resources, and fix-plan-with-executions**

Append to `src/agenticops/web/frontend/src/api/types.ts`:

```typescript
// Dashboard trends
export interface TrendDay {
  date: string;
  opened?: number;
  resolved?: number;
}

export interface SeverityDay {
  date: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface ResourceDay {
  date: string;
  added: number;
}

export interface MttrDay {
  date: string;
  avg_hours: number;
}

export interface FixRateDay {
  date: string;
  total: number;
  succeeded: number;
  rate: number;
}

export interface TrendSummary {
  issues_opened: number;
  issues_resolved: number;
  resource_net_change: number;
  mttr_avg_hours: number;
  mttr_trend: "up" | "down" | "flat";
  fix_rate_pct: number;
  fix_rate_trend: "up" | "down" | "flat";
}

export interface DashboardTrends {
  issues: TrendDay[];
  severity: SeverityDay[];
  resources: ResourceDay[];
  mttr: MttrDay[];
  fix_rate: FixRateDay[];
  summary: TrendSummary;
}

// Resource detail — related resources
export interface RelatedResourceItem {
  id: number | null;
  resource_id: string;
  resource_type: string;
  resource_name: string | null;
  status: string | null;
  detail: string | null;
}

export interface RelatedResources {
  network: RelatedResourceItem[];
  contains: RelatedResourceItem[];
}

// Fix plan with executions (for resource detail)
export interface FixPlanWithExecutions {
  id: number;
  health_issue_id: number;
  rca_result_id: number;
  risk_level: string;
  title: string;
  summary: string;
  steps: unknown[];
  status: string;
  approved_by: string | null;
  created_at: string;
  executions: FixExecution[];
}
```

- [ ] **Step 2: Commit**

```bash
git add src/agenticops/web/frontend/src/api/types.ts
git commit -m "feat(types): add dashboard trends and resource detail types"
```

---

### Task 5: Create hooks

**Files:**
- Create: `src/agenticops/web/frontend/src/hooks/useDashboardTrends.ts`
- Create: `src/agenticops/web/frontend/src/hooks/useResourceDetail.ts`

- [ ] **Step 1: Create useDashboardTrends hook**

```typescript
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { DashboardTrends } from "@/api/types";

export function useDashboardTrends(days: number = 7) {
  return useQuery({
    queryKey: ["dashboardTrends", days],
    queryFn: () => apiFetch<DashboardTrends>(`/dashboard/trends?days=${days}`),
    staleTime: 60_000,
  });
}
```

- [ ] **Step 2: Create useResourceDetail hook**

```typescript
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Resource, HealthIssue, FixPlanWithExecutions, RelatedResources } from "@/api/types";

export function useResource(id: number) {
  return useQuery({
    queryKey: ["resource", id],
    queryFn: () => apiFetch<Resource>(`/resources/${id}`),
    enabled: id > 0,
  });
}

export function useResourceIssues(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["resourceIssues", id],
    queryFn: () => apiFetch<HealthIssue[]>(`/resources/${id}/issues`),
    enabled: id > 0 && enabled,
    staleTime: 30_000,
  });
}

export function useResourceFixPlans(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["resourceFixPlans", id],
    queryFn: () => apiFetch<FixPlanWithExecutions[]>(`/resources/${id}/fix-plans`),
    enabled: id > 0 && enabled,
    staleTime: 30_000,
  });
}

export function useResourceRelated(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["resourceRelated", id],
    queryFn: () => apiFetch<RelatedResources>(`/resources/${id}/related`),
    enabled: id > 0 && enabled,
    staleTime: 60_000,
  });
}
```

- [ ] **Step 3: Commit**

```bash
git add src/agenticops/web/frontend/src/hooks/useDashboardTrends.ts src/agenticops/web/frontend/src/hooks/useResourceDetail.ts
git commit -m "feat(hooks): add dashboard trends and resource detail hooks"
```

---

### Task 6: Add route + update CommandPalette + Resources list

**Files:**
- Modify: `src/agenticops/web/frontend/src/App.tsx`
- Modify: `src/agenticops/web/frontend/src/components/CommandPalette.tsx`
- Modify: `src/agenticops/web/frontend/src/pages/Resources.tsx`

- [ ] **Step 1: Add ResourceDetail lazy import and route to App.tsx**

After the existing `Resources` lazy import (line 9), add:
```typescript
const ResourceDetail = lazy(() => import("@/pages/ResourceDetail"));
```

After the `resources` route block (~line 71), add:
```tsx
<Route
  path="resources/:id"
  element={
    <Suspense fallback={<Spinner />}>
      <ResourceDetail />
    </Suspense>
  }
/>
```

- [ ] **Step 2: Fix CommandPalette resource route**

In `src/agenticops/web/frontend/src/components/CommandPalette.tsx` line 27, change:
```typescript
// FROM:
return `/app/resources?highlight=${item.id}`;
// TO:
return `/app/resources/${item.id}`;
```

- [ ] **Step 3: Add row click navigation to Resources.tsx**

In `src/agenticops/web/frontend/src/pages/Resources.tsx`, add `useNavigate`:

```typescript
import { useNavigate } from "react-router-dom";
```

Inside the component, add:
```typescript
const navigate = useNavigate();
```

Add `onRowClick` prop to DataTable:
```tsx
<DataTable
  columns={columns}
  data={data ?? []}
  rowKey={(r) => r.id}
  emptyMessage="No resources found."
  onRowClick={(r) => navigate(`/app/resources/${r.id}`)}
/>
```

Note: Check if DataTable supports `onRowClick`. If not, need to add it.

- [ ] **Step 4: Check DataTable for onRowClick support and add if missing**

Read `src/agenticops/web/frontend/src/components/ui/DataTable.tsx` to check. If `onRowClick` doesn't exist, add it as an optional prop.

- [ ] **Step 5: Compile check**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit`
Expected: No errors (ResourceDetail.tsx doesn't exist yet, so the lazy import won't cause compile error — it's dynamic)

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/web/frontend/src/App.tsx src/agenticops/web/frontend/src/components/CommandPalette.tsx src/agenticops/web/frontend/src/pages/Resources.tsx
git commit -m "feat(frontend): add resource detail route, fix command palette, add row click"
```

---

## Chunk 3: Frontend — ResourceDetail Page + Dashboard Trends

### Task 7: ResourceDetail page

**Files:**
- Create: `src/agenticops/web/frontend/src/pages/ResourceDetail.tsx`

- [ ] **Step 1: Create the ResourceDetail page**

```tsx
import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useResource, useResourceIssues, useResourceFixPlans, useResourceRelated } from "@/hooks/useResourceDetail";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { StatusIndicator } from "@/components/ui/StatusIndicator";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import type { RelatedResourceItem } from "@/api/types";

const INFRA_TYPES = new Set(["VPC", "Subnet", "SecurityGroup", "RouteTable", "IGW", "NAT", "TGW", "InternetGateway", "NATGateway", "TransitGateway"]);

type Tab = "overview" | "issues" | "fix-plans" | "network" | "tags";

export default function ResourceDetail() {
  const { id } = useParams<{ id: string }>();
  const resourceId = Number(id);
  const [tab, setTab] = useState<Tab>("overview");

  const resource = useResource(resourceId);
  const issues = useResourceIssues(resourceId, tab === "issues");
  const fixPlans = useResourceFixPlans(resourceId, tab === "fix-plans");
  const related = useResourceRelated(resourceId, tab === "network");

  if (resource.isLoading) return <Spinner label="Loading resource..." />;
  if (resource.error) return <ErrorBanner message={resource.error.message} onRetry={() => resource.refetch()} />;
  if (!resource.data) return <ErrorBanner message="Resource not found" />;

  const r = resource.data;
  const isInfra = INFRA_TYPES.has(r.resource_type);
  const networkTabLabel = isInfra ? "Contains" : "Network";

  const tabs: { key: Tab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "issues", label: "Issues" },
    { key: "fix-plans", label: "Fix Plans" },
    { key: "network", label: networkTabLabel },
    { key: "tags", label: "Tags" },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <Link to="/app/resources" className="text-muted-foreground hover:text-foreground text-sm">&larr; Resources</Link>
      </div>
      <Card>
        <div className="px-5 py-4 border-b">
          <div className="flex items-center gap-3 mb-2">
            <Badge className="bg-primary-100 text-primary-700">{r.resource_type}</Badge>
            <h1 className="text-lg font-semibold">{r.resource_name || r.resource_id}</h1>
          </div>
          <div className="flex items-center gap-6 text-sm text-muted-foreground">
            <span className="font-mono text-xs">{r.resource_id}</span>
            {r.resource_arn && <span className="font-mono text-xs truncate max-w-xs">{r.resource_arn}</span>}
            <span>{r.region}</span>
            <StatusIndicator status={r.status} />
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b px-5">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                tab === t.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <CardBody>
          {tab === "overview" && <OverviewTab metadata={r.resource_metadata} />}
          {tab === "issues" && <IssuesTab issues={issues} />}
          {tab === "fix-plans" && <FixPlansTab fixPlans={fixPlans} />}
          {tab === "network" && <NetworkTab related={related} isInfra={isInfra} />}
          {tab === "tags" && <TagsTab tags={r.tags} />}
        </CardBody>
      </Card>
    </div>
  );
}

/* --- Tab Components --- */

function OverviewTab({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([, v]) => v != null && v !== "");
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">No metadata available.</p>;
  return (
    <div className="grid grid-cols-2 gap-x-8 gap-y-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between py-1.5 border-b border-border/50">
          <span className="text-sm text-muted-foreground">{k.replace(/_/g, " ")}</span>
          <span className="text-sm font-mono">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
        </div>
      ))}
    </div>
  );
}

function IssuesTab({ issues }: { issues: ReturnType<typeof useResourceIssues> }) {
  if (issues.isLoading) return <Spinner />;
  if (!issues.data?.length) return <p className="text-sm text-muted-foreground">No issues found.</p>;
  return (
    <div className="space-y-1">
      {issues.data.map((i) => (
        <Link
          key={i.id}
          to={`/app/issues/${i.id}`}
          className="flex items-center justify-between py-2 px-2 rounded-md hover:bg-accent transition-colors"
        >
          <div className="flex items-center gap-3">
            <SeverityBadge severity={i.severity} />
            <span className="text-sm">{i.title}</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{i.status}</span>
            <span>{formatShortDate(i.detected_at)}</span>
          </div>
        </Link>
      ))}
    </div>
  );
}

function FixPlansTab({ fixPlans }: { fixPlans: ReturnType<typeof useResourceFixPlans> }) {
  if (fixPlans.isLoading) return <Spinner />;
  if (!fixPlans.data?.length) return <p className="text-sm text-muted-foreground">No fix plans found.</p>;
  return (
    <div className="space-y-1">
      {fixPlans.data.map((p) => (
        <Link
          key={p.id}
          to={`/app/fix-plans/${p.id}`}
          className="flex items-center justify-between py-2 px-2 rounded-md hover:bg-accent transition-colors"
        >
          <div className="flex items-center gap-3">
            <Badge className="text-xs">{p.risk_level}</Badge>
            <span className="text-sm">{p.title}</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{p.status}</span>
            {p.executions.length > 0 && (
              <span>{p.executions[0].status}</span>
            )}
          </div>
        </Link>
      ))}
    </div>
  );
}

function ResourceLink({ item }: { item: RelatedResourceItem }) {
  const inner = (
    <span className="flex items-center gap-2">
      <Badge className="text-[10px] px-1.5 py-0 bg-primary/10 text-primary">{item.resource_type}</Badge>
      <span className="text-sm">{item.resource_name || item.resource_id}</span>
    </span>
  );
  if (item.id) {
    return (
      <Link to={`/app/resources/${item.id}`} className="text-primary hover:underline">
        {inner}
      </Link>
    );
  }
  return <span className="text-muted-foreground">{inner}</span>;
}

function NetworkTab({ related, isInfra }: { related: ReturnType<typeof useResourceRelated>; isInfra: boolean }) {
  if (related.isLoading) return <Spinner />;
  const data = related.data;
  if (!data) return <p className="text-sm text-muted-foreground">No related resources.</p>;

  const items = isInfra ? data.contains : data.network;
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No related resources found.</p>;

  return (
    <div className="space-y-1">
      {items.map((item, i) => (
        <div key={`${item.resource_id}-${i}`} className="flex items-center justify-between py-2 px-2 border-b border-border/50">
          <ResourceLink item={item} />
          {item.status && <StatusIndicator status={item.status} />}
        </div>
      ))}
    </div>
  );
}

function TagsTab({ tags }: { tags: Record<string, string> }) {
  const entries = Object.entries(tags);
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">No tags.</p>;
  return (
    <div className="grid grid-cols-2 gap-x-8 gap-y-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between py-1.5 border-b border-border/50">
          <span className="text-sm text-muted-foreground">{k}</span>
          <span className="text-sm font-mono">{v}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: TypeScript check**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/agenticops/web/frontend/src/pages/ResourceDetail.tsx
git commit -m "feat(frontend): add ResourceDetail page with type-aware tabs"
```

---

### Task 8: Dashboard TrendStrip

**Files:**
- Modify: `src/agenticops/web/frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Add TrendStrip to Dashboard**

Add to Dashboard.tsx — import the hook and add the component. Insert the TrendStrip between the Pipeline Bar and Content Grid sections.

Add import:
```typescript
import { useDashboardTrends } from "@/hooks/useDashboardTrends";
```

Add state for days inside the component:
```typescript
const [trendDays, setTrendDays] = useState(7);
const trends = useDashboardTrends(trendDays);
```

Also add `useState` to the existing import from "react".

Insert this JSX after the Pipeline Bar (`</div>` at ~line 92) and before the Content Grid:

```tsx
{/* Trend Strip */}
{trends.data && (
  <div className="duo-fade mb-8" style={{ animationDelay: "340ms" }}>
    <div className="flex items-center justify-between mb-3">
      <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground">
        Trends
      </div>
      <div className="flex gap-1">
        {[7, 30, 90].map((d) => (
          <button
            key={d}
            onClick={() => setTrendDays(d)}
            className={`text-[10px] px-2.5 py-1 rounded-md font-medium transition-colors ${
              trendDays === d
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {d}d
          </button>
        ))}
      </div>
    </div>
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
      <TrendCard
        label="Issues"
        value={`+${trends.data.summary.issues_opened} / -${trends.data.summary.issues_resolved}`}
        data={trends.data.issues.map((d) => d.opened ?? 0)}
        color="bg-red-500/30"
      />
      <TrendCard
        label="Severity"
        value={`${trends.data.severity.reduce((s, d) => s + d.critical, 0)} crit`}
        data={trends.data.severity.map((d) => d.critical + d.high + d.medium + d.low)}
        color="bg-orange-500/30"
      />
      <TrendCard
        label="Resources"
        value={`+${trends.data.summary.resource_net_change}`}
        data={trends.data.resources.map((d) => d.added)}
        color="bg-primary/30"
      />
      <TrendCard
        label="MTTR"
        value={`${trends.data.summary.mttr_avg_hours}h`}
        trend={trends.data.summary.mttr_trend}
        trendGoodDirection="down"
        data={trends.data.mttr.map((d) => d.avg_hours)}
        color="bg-amber-400/30"
      />
      <TrendCard
        label="Fix Rate"
        value={`${trends.data.summary.fix_rate_pct}%`}
        trend={trends.data.summary.fix_rate_trend}
        trendGoodDirection="up"
        data={trends.data.fix_rate.map((d) => d.rate)}
        color="bg-green-500/30"
      />
    </div>
  </div>
)}
```

Add the TrendCard component at the bottom of the file (before the default export or as a helper):

```tsx
function TrendCard({
  label,
  value,
  trend,
  trendGoodDirection,
  data,
  color,
}: {
  label: string;
  value: string;
  trend?: "up" | "down" | "flat";
  trendGoodDirection?: "up" | "down";
  data: number[];
  color: string;
}) {
  const max = Math.max(...data, 1);
  const arrow = trend === "up" ? "↑" : trend === "down" ? "↓" : "";
  const arrowColor =
    trend && trendGoodDirection
      ? trend === trendGoodDirection
        ? "text-green-500"
        : trend === "flat"
        ? ""
        : "text-red-500"
      : "";

  return (
    <div className="bg-card border rounded-lg px-4 py-3">
      <div className="text-[10px] font-medium tracking-[0.08em] uppercase text-muted-foreground">
        {label}
      </div>
      <div className="font-mono text-lg font-light tracking-tight mt-1 mb-2">
        {value}
        {arrow && (
          <span className={`text-xs ml-1 ${arrowColor}`}>{arrow}</span>
        )}
      </div>
      <div className="flex items-end gap-[2px] h-5">
        {data.map((v, i) => (
          <div
            key={i}
            className={`flex-1 rounded-sm ${color}`}
            style={{ height: `${Math.max((v / max) * 100, 4)}%` }}
          />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: TypeScript check**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Build check**

Run: `cd src/agenticops/web/frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/web/frontend/src/pages/Dashboard.tsx
git commit -m "feat(dashboard): add compact trend strip with 5 sparkline cards"
```

---

### Task 9: Final verification

- [ ] **Step 1: Run all backend tests**

Run: `python -m pytest tests/test_resource_detail_api.py tests/test_dashboard_trends_api.py -v`
Expected: ALL PASS

- [ ] **Step 2: Syntax check backend**

Run: `python3 -m py_compile src/agenticops/web/app.py`
Expected: No errors

- [ ] **Step 3: Frontend full build**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build`
Expected: No errors

- [ ] **Step 4: Run existing test suite to check for regressions**

Run: `python -m pytest tests/ -v --timeout=30 -x`
Expected: No new failures

- [ ] **Step 5: Final commit if any DataTable changes were needed**

```bash
git add -A
git commit -m "fix: DataTable onRowClick support for resource navigation"
```
