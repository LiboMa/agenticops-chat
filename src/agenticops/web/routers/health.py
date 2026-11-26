"""GET /api/health — what the process can reach: database, Bedrock, the model, the scheduler (split from web/app.py)."""
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from agenticops.config import settings
from agenticops.models import get_db_session
from agenticops.web.schemas import HealthCheckResult, HealthResponse

router = APIRouter()


class _HealthSkip(Exception):
    """A health check that does not apply (MVP-2.9.0 N35: the Bedrock identity while Bedrock is turned off)."""


@router.get("/api/health", response_model=HealthResponse)
def api_health():
    """Health check endpoint."""
    import time
    import shutil
    import boto3
    from agenticops import __version__

    checks = {}

    # 1. Database check
    db_start = time.time()
    try:
        with get_db_session() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = HealthCheckResult(
            status="ok",
            latency_ms=int((time.time() - db_start) * 1000),
        )
    except Exception as e:
        checks["database"] = HealthCheckResult(
            status="error",
            error=str(e),
        )

    # 2. AWS credentials check — the Bedrock identity; skipped while Bedrock is turned off (MVP-2.9.0 N35: the models
    # are another provider's, and the box may have no AWS identity at all)
    aws_start = time.time()
    from agenticops.llm import registry as provider_registry
    try:
        if not provider_registry.bedrock_enabled():
            raise _HealthSkip
        from agenticops.config import get_bedrock_boto_session
        sts = get_bedrock_boto_session().client("sts")
        identity = sts.get_caller_identity()
        checks["aws"] = HealthCheckResult(
            status="ok",
            latency_ms=int((time.time() - aws_start) * 1000),
            details={"account_id": identity.get("Account")},
        )
    except _HealthSkip:
        checks["aws"] = HealthCheckResult(status="skipped", details={"reason": "bedrock_off"})
    except Exception as e:
        checks["aws"] = HealthCheckResult(
            status="error",
            error=str(e),
        )

    # 3. Disk space check
    try:
        usage = shutil.disk_usage(settings.reports_dir)
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        used_pct = (usage.used / usage.total) * 100

        if used_pct > 90:
            disk_status = "error"
        elif used_pct > 80:
            disk_status = "warning"
        else:
            disk_status = "ok"

        checks["disk"] = HealthCheckResult(
            status=disk_status,
            details={
                "path": str(settings.reports_dir),
                "free_gb": round(free_gb, 2),
                "total_gb": round(total_gb, 2),
                "used_pct": round(used_pct, 2),
            },
        )
    except Exception as e:
        checks["disk"] = HealthCheckResult(
            status="error",
            error=str(e),
        )

    # Determine overall status
    if checks["database"].status == "error":
        overall_status = "unhealthy"
    elif any(c.status == "error" for c in checks.values()):
        overall_status = "degraded"
    elif any(c.status == "warning" for c in checks.values()):
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return HealthResponse(
        status=overall_status,
        version=__version__,
        timestamp=datetime.now(timezone.utc),
        checks=checks,
    )
