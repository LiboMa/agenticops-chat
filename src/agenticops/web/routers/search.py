"""Global search API endpoint — extracted from app.py.

MVP-2.6.0: change plans are labelled `change_plan` (parent = their change request) and change requests are
searchable (`change_requests` group). Both only while change_management_enabled — same rule as /api/changes:
with the flag off there is no change_requests group and no change plan in the fix_plans group.

MVP-2.9.0 N18 (NewUI's command bar lists what this returns):
- what was typed is matched literally — `%` and `_` are characters (they used to match everything);
- a reference finds its thing by number, first in its group: `I#12` / `i12` / `12` an issue, `C#3` / `c3` / `3` a change
  request, `R#7` / `r7` a resource (its inventory number; a bare number is not one — it still matches a native id as text);
- every group has an order — the newest first — so the cut keeps the newest instead of whatever the database gave;
- a plain function: it reads the database (one process — an `async def` handler would hold the event loop).
"""

from fastapi import APIRouter, Depends, Query

from agenticops.auth.actor import Actor
from agenticops.web.deps import current_actor
from sqlalchemy import case, func

from agenticops.config import settings
from agenticops.models import ChangeRequest, CloudResource, FixPlan, HealthIssue, Report, get_db_session
from agenticops.services.inventory import PRESENT
from agenticops.services.listing import like_pattern, ref_number
from agenticops.web.schemas import SearchResponse, SearchResultItem

router = APIRouter()


@router.get("/api/search", response_model=SearchResponse)
def api_search(
    q: str = Query(..., min_length=1),
    types: str = Query(default="issues,fix_plans,reports,resources,change_requests"),
    limit: int = Query(default=5, ge=1, le=10),      # SQLite reads LIMIT -1 as «no limit»
    actor: Actor = Depends(current_actor),
):
    """Global search across issues, fix/change plans, reports, resources and change requests."""
    search_types = {t.strip() for t in types.split(",")}
    search_term = like_pattern(q.lower())
    results: dict = {}

    def has(column):
        return func.lower(column).like(search_term, escape="\\")

    def first(column, number):
        """Order: the row with that number first (when the text is a reference), then the rest."""
        return [case((column == number, 0), else_=1)] if number is not None else []

    issue_no, change_no, resource_no = ref_number(q, "Ii"), ref_number(q, "Cc"), ref_number(q, "Rr", bare=False)

    with get_db_session() as db:
        if "issues" in search_types:
            cond = has(HealthIssue.title) | has(HealthIssue.description)
            if issue_no is not None:
                cond = cond | (HealthIssue.id == issue_no)
            rows = (db.query(HealthIssue).filter(cond)
                    .order_by(*first(HealthIssue.id, issue_no), HealthIssue.detected_at.desc(), HealthIssue.id.desc())
                    .limit(limit).all())
            results["issues"] = [
                SearchResultItem(
                    id=r.id, title=r.title,
                    subtitle=(r.description or "")[:100],
                    entity_type="issue", status=r.status,
                    severity=r.severity, created_at=r.detected_at,
                ).model_dump()
                for r in rows
            ]

        if "fix_plans" in search_types:
            query = db.query(FixPlan).filter(has(FixPlan.title))
            if not settings.change_management_enabled:
                # a change plan links to change pages whose API 404s while the feature is off
                query = query.filter(FixPlan.plan_kind != "change")
            rows = query.order_by(FixPlan.created_at.desc(), FixPlan.id.desc()).limit(limit).all()
            results["fix_plans"] = [
                SearchResultItem(
                    id=r.id, title=r.title,
                    subtitle=(r.summary or "")[:100],
                    entity_type="change_plan" if r.plan_kind == "change" else "fix_plan", status=r.status,
                    parent_id=r.change_request_id if r.plan_kind == "change" else r.health_issue_id,
                    created_at=r.created_at,
                ).model_dump()
                for r in rows
            ]

        if "change_requests" in search_types and settings.change_management_enabled:
            cond = has(ChangeRequest.title)
            if change_no is not None:
                cond = cond | (ChangeRequest.id == change_no)
            rows = (db.query(ChangeRequest).filter(cond)
                    .order_by(*first(ChangeRequest.id, change_no), ChangeRequest.created_at.desc(), ChangeRequest.id.desc())
                    .limit(limit).all())
            results["change_requests"] = [
                SearchResultItem(
                    id=r.id, title=r.title,
                    subtitle=(r.description or "")[:100],
                    entity_type="change_request", status=r.status,
                    parent_id=None,
                    created_at=r.created_at,
                ).model_dump()
                for r in rows
            ]

        if "reports" in search_types:
            from agenticops.services.report_access import visible_filter
            rows = (
                visible_filter(db.query(Report), actor)
                .filter(has(Report.title) | has(Report.summary))
                .order_by(Report.created_at.desc(), Report.id.desc())
                .limit(limit)
                .all()
            )
            results["reports"] = [
                SearchResultItem(
                    id=r.id, title=r.title,
                    subtitle=(r.summary or "")[:100],
                    entity_type="report", report_type=r.report_type,
                    created_at=r.created_at,
                ).model_dump()
                for r in rows
            ]

        if "resources" in search_types:
            cond = has(CloudResource.resource_id) | has(CloudResource.name) | has(CloudResource.resource_type)
            if resource_no is not None:
                cond = cond | (CloudResource.id == resource_no)
            rows = (db.query(CloudResource).filter(PRESENT, cond)
                    .order_by(*first(CloudResource.id, resource_no), CloudResource.updated_at.desc(), CloudResource.id.desc())
                    .limit(limit).all())
            results["resources"] = [
                SearchResultItem(
                    id=r.id,
                    title=r.name or r.resource_id,
                    subtitle=f"{r.resource_type} | {r.region} | {r.resource_id}",
                    entity_type="resource",
                    status=r.status,
                    created_at=r.updated_at,
                ).model_dump()
                for r in rows
            ]

    return SearchResponse(query=q, results=results)
