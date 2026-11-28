"""A person's verdict on an issue's diagnosis and its root-cause location, and the location statistics (split from
web/app.py)."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agenticops.auth.actor import Actor
from agenticops.models import get_db_session, HealthIssue, RCAResult
from agenticops.web.deps import current_actor

router = APIRouter()
logger = logging.getLogger(__name__)


class RcaFeedbackRequest(BaseModel):
    """Schema for RCA-level human verdict (MVP-2.2.0 ground-truth capture).

    location_verdict (MVP-2.6.1) judges the root-cause location on its own; at least one of the two is given.
    """
    verdict: Optional[str] = Field(None, pattern="^(correct|incorrect)$")
    note: str = ""
    location_verdict: Optional[str] = Field(None, pattern="^(correct|partial|incorrect)$")
    # MVP-2.9.0: the diagnosis the person was shown. When it is no longer the newest the verdict is refused (409
    # `rca_changed`) instead of landing on one they did not read. None = older clients: the newest, as before.
    rca_id: Optional[int] = Field(None, ge=1)


@router.post("/api/health-issues/{issue_id}/rca-feedback", status_code=201)
async def api_rca_feedback(issue_id: int, data: RcaFeedbackRequest, actor: Actor = Depends(current_actor)):
    """Record a human verdict on the latest RCA result for an issue.

    'incorrect' also writes an rca agent-memory entry so future runs on the
    same pattern see the correction (ground-truth flywheel start). A location
    verdict needs a location with a candidate left (valid or partial); its
    judge is the session actor, never the request body.
    """
    from datetime import timezone as _tz

    if data.verdict is None and data.location_verdict is None:
        raise HTTPException(status_code=422, detail="Give verdict, location_verdict, or both")
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")
        rca = (
            session.query(RCAResult)
            .filter_by(health_issue_id=issue_id)
            .order_by(RCAResult.created_at.desc())
            .first()
        )
        if not rca:
            raise HTTPException(status_code=404, detail="No RCA result for this issue")
        if data.rca_id is not None and data.rca_id != rca.id:
            return JSONResponse(status_code=409, content={
                "detail": (f"The diagnosis changed: RCA #{rca.id} is now the newest one of issue #{issue_id}, "
                           f"and the verdict was given on RCA #{data.rca_id}. Reload and judge the current one."),
                "code": "rca_changed", "rca_id": rca.id})
        if data.location_verdict is not None:
            if rca.location_status not in ("valid", "partial"):
                raise HTTPException(status_code=409, detail=(
                    f"RCA #{rca.id} has no root-cause location to judge (location {rca.location_status or 'absent'})"))
            rca.location_verdict = data.location_verdict
            rca.location_verdict_by = actor.key
            rca.location_verdict_at = datetime.now(_tz.utc)
        if data.verdict is not None:
            rca.human_verdict = data.verdict
            rca.human_note = data.note or None
            rca.verified_at = datetime.now(_tz.utc)
        rca_id = rca.id
        root_cause = rca.root_cause or ""
        issue_type = getattr(issue, "issue_type", "other")
        resource_id = issue.resource_id

    try:
        from agenticops.services.pipeline_events import log_event
        log_event(issue_id, "rca_human_feedback", "rca",
                  detail={"rca_id": rca_id, "verdict": data.verdict, "location_verdict": data.location_verdict,
                          "by": actor.key, "note": (data.note or "")[:2000]})   # whole: it is quoted back
    except Exception:
        pass

    if data.verdict == "incorrect":
        try:
            from agenticops.memory.agent_memory import save_memory_file

            body = (
                f"For {issue_type} issues on `{resource_id}`, the conclusion "
                f"\"{root_cause[:300]}\" was judged INCORRECT by a human "
                f"(issue I#{issue_id}, RCA #{rca_id})."
            )
            if data.note:
                body += f"\n\nHuman note: {data.note}"
            body += "\n\nDo not repeat this conclusion without new decisive evidence."
            save_memory_file(
                "rca", f"rca_feedback_issue_{issue_id}",
                memory_type="feedback", source="user", body=body,
                related_issue_id=issue_id, collision_safe=True,
            )
        except Exception:
            logger.debug("rca feedback memory write failed", exc_info=True)

    recorded = " and ".join(f"{what} '{v}'" for what, v in (("verdict", data.verdict),
                                                           ("location verdict", data.location_verdict)) if v)
    return {"rca_id": rca_id, "verdict": data.verdict, "location_verdict": data.location_verdict,
            "message": f"Human {recorded} recorded on RCA #{rca_id}"}


@router.get("/api/rca/location-stats")
def api_rca_location_stats(days: int = Query(30, ge=1, le=365)):
    """Root-cause location quality over the last `days` days (what each figure counts: services/rca_location)."""
    from agenticops.services.rca_location import location_stats

    with get_db_session() as session:
        return location_stats(session, days)
