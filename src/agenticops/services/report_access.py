"""Who may see a report (MVP-2.7.0 S6) — the one rule every report route applies (the chat_access pattern).

A report saved from a private chat belongs to its creator and is `private`: only they and admins see, render,
export and publish it. Every other report is `workspace` (everyone, as before). With api_auth_enabled=false every
caller is web:anonymous and sees every report. A report the caller may not see is reported exactly like a missing one.
"""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_

from agenticops.auth.actor import Actor
from agenticops.config import settings
from agenticops.models import Report
from agenticops.services.chat_access import is_admin

PRIVATE, WORKSPACE = "private", "workspace"
NOT_FOUND = "Report not found"


def owner_for_new_report(actor: Actor, private: bool) -> tuple[Optional[int], str]:
    """(owner_user_id, visibility) for a report this caller saves; private only when its source chat was."""
    if private and settings.api_auth_enabled and actor.kind == "user" and actor.user_id is not None:
        return actor.user_id, PRIVATE
    return (actor.user_id if actor.kind == "user" else None), WORKSPACE


def can_see(report: Report, actor: Actor) -> bool:
    if not settings.api_auth_enabled or (report.visibility or WORKSPACE) == WORKSPACE or is_admin(actor):
        return True
    return actor.user_id is not None and report.owner_user_id == actor.user_id


def owned_by(report: Report, actor: Actor) -> bool:
    return actor.user_id is not None and report.owner_user_id == actor.user_id


def visible_filter(query, actor: Actor):
    if not settings.api_auth_enabled or is_admin(actor):
        return query
    conditions = [Report.visibility != PRIVATE]
    if actor.user_id is not None:
        conditions.append(Report.owner_user_id == actor.user_id)
    return query.filter(or_(*conditions))


def get_visible_report(db, report_id: int, actor: Actor) -> Report:
    report = db.query(Report).filter_by(id=report_id).first()
    if report is None or not can_see(report, actor):
        raise HTTPException(404, NOT_FOUND)
    return report
