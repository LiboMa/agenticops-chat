"""Global search API endpoint — extracted from app.py (no logic change)."""

from fastapi import APIRouter, Query
from sqlalchemy import func

from agenticops.models import CloudResource, FixPlan, HealthIssue, Report, get_db_session
from agenticops.web.schemas import SearchResponse, SearchResultItem

router = APIRouter()


@router.get("/api/search", response_model=SearchResponse)
async def api_search(
    q: str = Query(..., min_length=1),
    types: str = Query(default="issues,fix_plans,reports,resources"),
    limit: int = Query(default=5, le=10),
):
    """Global search across issues, fix plans, reports, and resources."""
    search_types = {t.strip() for t in types.split(",")}
    search_term = f"%{q.lower()}%"
    results: dict = {}

    with get_db_session() as db:
        if "issues" in search_types:
            rows = (
                db.query(HealthIssue)
                .filter(
                    func.lower(HealthIssue.title).like(search_term)
                    | func.lower(HealthIssue.description).like(search_term)
                )
                .limit(limit)
                .all()
            )
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
            rows = (
                db.query(FixPlan)
                .filter(func.lower(FixPlan.title).like(search_term))
                .limit(limit)
                .all()
            )
            results["fix_plans"] = [
                SearchResultItem(
                    id=r.id, title=r.title,
                    subtitle=(r.summary or "")[:100],
                    entity_type="fix_plan", status=r.status,
                    parent_id=r.health_issue_id,
                    created_at=r.created_at,
                ).model_dump()
                for r in rows
            ]

        if "reports" in search_types:
            rows = (
                db.query(Report)
                .filter(
                    func.lower(Report.title).like(search_term)
                    | func.lower(Report.summary).like(search_term)
                )
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
            rows = (
                db.query(CloudResource)
                .filter(
                    func.lower(CloudResource.resource_id).like(search_term)
                    | func.lower(CloudResource.name).like(search_term)
                    | func.lower(CloudResource.resource_type).like(search_term)
                )
                .limit(limit)
                .all()
            )
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
