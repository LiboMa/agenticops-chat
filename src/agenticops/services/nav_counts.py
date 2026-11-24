"""The sidebar's numbers in one request (MVP-2.8.0, owner 2026-11-10: direction A) — GET /api/ui/nav-counts.

Every number is «something waiting for someone to act»:
- attention: the to-do items waiting on this person (services/attention, the same source as /api/ui/attention and
  the «在等我» tab — the sidebar, the top bar and the tab never disagree), and how many of them are critical issues;
  the only number that follows the account scope, because the page it opens does too;
- security_high: open high / critical security findings (the Security page's own definition);
- schedules_failed: schedules whose newest run failed;
- skill_drafts: skill drafts waiting to be reviewed and published.
A viewer can act on none of these: no numbers, and the other queries are not run. A count that fails is None —
never 0, so a broken query is never read as «nothing waiting» — and is logged.
"""
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _attention(actor, account_id: Optional[int], now: datetime) -> dict:
    from agenticops.services.attention import attention_items
    items = attention_items(actor, account_id=account_id, now=now)
    # issue rows are «I<n>» (a change row carries a risk level, never a severity)
    critical = sum(1 for i in items if str(i.get("id", "")).startswith("I") and i.get("severity") == "critical")
    return {"total": len(items), "critical": critical}


def _schedules_failed() -> int:
    from agenticops.models import get_db_session
    from agenticops.scheduler.scheduler import latest_executions
    with get_db_session() as s:
        return sum(1 for e in latest_executions(s).values() if e.status == "failed")


def _skill_drafts() -> int:
    from agenticops.skills.loader import discover_skills
    return sum(1 for sk in discover_skills() if getattr(sk, "is_draft", False))


def _security_high() -> int:
    from agenticops.services import security_service
    return security_service.open_high_findings()


def _safe(name: str, fn: Callable[[], object]):
    try:
        return fn()
    except Exception:
        logger.warning("nav-counts: the %s count failed", name, exc_info=True)
        return None


def nav_counts(actor, *, account_id: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    generated_at = now.isoformat()
    if getattr(actor, "read_only", False):
        return {"read_only": True, "attention": {"total": 0, "critical": 0}, "security_high": None,
                "schedules_failed": None, "skill_drafts": None, "generated_at": generated_at}
    return {
        "read_only": False,
        "attention": _safe("attention", lambda: _attention(actor, account_id, now)),
        "security_high": _safe("security", _security_high),
        "schedules_failed": _safe("schedules", _schedules_failed),
        "skill_drafts": _safe("skills", _skill_drafts),
        "generated_at": generated_at,
    }
