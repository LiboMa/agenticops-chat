"""A resource's issues, fix plans and related resources — the resource page's sub-endpoints (split from web/app.py)."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from agenticops.models import CloudResource, FixPlan, get_db_session, HealthIssue
from agenticops.services.inventory import PRESENT
from agenticops.web.helpers import _guess_type, _infra_ref_key
from agenticops.web.schemas import FixExecutionResponse, HealthIssueResponse

router = APIRouter()


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

    model_config = ConfigDict(from_attributes=True)


class RelatedResourceItem(BaseModel):
    id: Optional[int] = None
    resource_id: str
    resource_type: str
    resource_name: Optional[str] = None
    status: Optional[str] = None
    detail: Optional[str] = None


class RelatedResourcesResponse(BaseModel):
    network: List[RelatedResourceItem] = []
    contains: List[RelatedResourceItem] = []


_INFRA_TYPES = {"VPC", "Subnet", "SecurityGroup", "RouteTable", "IGW", "NAT", "TGW",
                "InternetGateway", "NATGateway", "TransitGateway"}






def _issues_of_resource(resource: CloudResource):
    """Which issues belong to a resource: the ones anchored to it (`resource_ref`, MVP-2.6.1 — within the resource's
    own account: SQLite does not enforce ON DELETE SET NULL, so a stale ref may point at an id another account's row
    now uses; `health_overlay` has the same guard), and — the older tie — the ones whose alarm carried the row's own
    resource id. The alarm's id is often an ARN or an alarm name: the string alone missed every such issue while the
    map and the resource table (by `resource_ref`) counted it (MVP-2.9.0)."""
    from sqlalchemy import and_
    # the id tie stays inside the resource's account too (an issue with no account is kept): a service-linked role
    # has the same name in every account, and another account's issue is not this resource's
    return or_(and_(HealthIssue.resource_ref == resource.id, HealthIssue.account_id == resource.account_id),
               and_(HealthIssue.resource_id == resource.resource_id,
                    or_(HealthIssue.account_id == resource.account_id, HealthIssue.account_id.is_(None))))


@router.get("/api/resources/{resource_id}/issues", response_model=List[HealthIssueResponse])
def api_resource_issues(resource_id: int, limit: int = Query(default=20, le=100), open: bool = Query(default=False)):
    """List health issues for a resource: anchored to it, or carrying its resource id (same account). `open=true`
    keeps the open ones only (the statuses the health overlay counts) — each row's `resource_ref` says whether it
    is anchored here, which is what the resource's health is made of."""
    from agenticops.services.signal_gate import OPEN_ISSUE_STATUSES
    with get_db_session() as session:
        resource = session.query(CloudResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        query = session.query(HealthIssue).filter(_issues_of_resource(resource))
        if open:
            query = query.filter(HealthIssue.status.in_(OPEN_ISSUE_STATUSES))
        issues = query.order_by(HealthIssue.detected_at.desc()).limit(limit).all()
        return [HealthIssueResponse.model_validate(i) for i in issues]


@router.get("/api/resources/{resource_id}/fix-plans", response_model=List[FixPlanWithExecutionsResponse])
async def api_resource_fix_plans(resource_id: int, limit: int = Query(default=20, le=100)):
    """List fix plans for a resource (via linked health issues)."""
    with get_db_session() as session:
        resource = session.query(CloudResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        plans = (
            session.query(FixPlan)
            .options(joinedload(FixPlan.fix_executions))
            .join(HealthIssue, FixPlan.health_issue_id == HealthIssue.id)
            .filter(_issues_of_resource(resource))
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


@router.get("/api/resources/{resource_id}/related", response_model=RelatedResourcesResponse)
async def api_resource_related(resource_id: int):
    """Get related resources — network context or contained resources."""
    with get_db_session() as session:
        resource = session.query(CloudResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        meta = resource.raw_data or {}
        is_infra = resource.resource_type in _INFRA_TYPES
        network: list[RelatedResourceItem] = []
        contains: list[RelatedResourceItem] = []

        if is_infra:
            ref_key = _infra_ref_key(resource.resource_type)
            if ref_key:
                matched = (
                    session.query(CloudResource)
                    .filter(
                        CloudResource.id != resource.id,
                        PRESENT,
                        func.json_extract(CloudResource.raw_data, f"$.{ref_key}") == resource.resource_id,
                    )
                    .limit(100)
                    .all()
                )
                for c in matched:
                    contains.append(RelatedResourceItem(
                        id=c.id, resource_id=c.resource_id,
                        resource_type=c.resource_type,
                        resource_name=c.name, status=c.status,
                    ))
        else:
            for key in ("vpc_id", "subnet_id", "security_groups", "subnet_ids"):
                val = meta.get(key)
                if not val:
                    continue
                ids = val if isinstance(val, list) else [val]
                for rid in ids:
                    if not isinstance(rid, str):
                        continue
                    linked = session.query(CloudResource).filter_by(resource_id=rid).first()
                    if linked:
                        network.append(RelatedResourceItem(
                            id=linked.id, resource_id=linked.resource_id,
                            resource_type=linked.resource_type,
                            resource_name=linked.name, status=linked.status,
                        ))
                    else:
                        network.append(RelatedResourceItem(resource_id=rid, resource_type=_guess_type(rid)))

        return RelatedResourcesResponse(network=network, contains=contains)
