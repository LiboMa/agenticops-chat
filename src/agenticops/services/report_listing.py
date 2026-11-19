"""The reports list (MVP-2.9.0 N21, the 2.8.0 spec's S4): searched, dated and counted on the server — over every
report the caller may see, not over the page that happens to be loaded."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import case, or_

from agenticops.models import Report
from agenticops.services import report_access
from agenticops.services.listing import like_pattern, ref_number


def page_reports(session, actor, *, report_type: Optional[str] = None, q: Optional[str] = None,
                 date_from: Optional[date] = None, date_to: Optional[date] = None,
                 limit: int, offset: int = 0) -> tuple[list[Report], int, int]:
    """(rows of this page, how many match, how many the caller may see in all) — newest first.

    `q` is read in the title, the summary and the body, any case, `%` and `_` as characters. «R#145» / «r145» is
    the reference: that report and nothing else. A bare «145» is that report first, then every report whose text
    holds it. `date_from` / `date_to` are whole UTC days, both included (`created_at` is stored as naive UTC)."""
    visible = report_access.visible_filter(session.query(Report), actor)
    all_total = visible.count()

    query = visible
    if report_type:
        query = query.filter(Report.report_type == report_type)
    if date_from is not None:
        query = query.filter(Report.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        query = query.filter(Report.created_at < datetime.combine(date_to + timedelta(days=1), time.min))

    order = [Report.created_at.desc(), Report.id.desc()]
    term = (q or "").strip()
    if term:
        reference = ref_number(term, "Rr", bare=False)
        if reference is not None:
            query = query.filter(Report.id == reference)
        else:
            pattern = like_pattern(term)
            match = [Report.title.ilike(pattern, escape="\\"), Report.summary.ilike(pattern, escape="\\"),
                     Report.content_markdown.ilike(pattern, escape="\\")]
            number = ref_number(term, "Rr")
            if number is not None:
                match.append(Report.id == number)
                order.insert(0, case((Report.id == number, 0), else_=1))
            query = query.filter(or_(*match))

    total = query.count()
    rows = query.order_by(*order).offset(max(0, offset)).limit(limit).all()
    return rows, total, all_total
