"""«Later» (MVP-2.9.0 N14): a person puts one of their waiting items at the end of its group for a while.

Nothing about the item changes — it still waits on them, still counts, is still on their list. What is stored is
one row per person and item: until when, and WHAT the item waited for when it was snoozed (`situation`). The mark
applies only while the item still waits for that same thing: a plan that was snoozed and has since been replaced
by a new plan is a new matter, back in its place at once. A row that no longer applies is simply not read; a
person's rows that have ended are swept when that person snoozes next.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from agenticops.config import settings
from agenticops.models import AttentionSnooze, get_db_session
from agenticops.utils.timeutils import as_utc, iso_z


def situation(item: dict) -> str:
    """What an item waits for: its reason and detail, the entity and its version (the web client keys a decided
    item the same way, newui/lib/queue.situation — the two are never compared with each other)."""
    e = item["entity"]
    version = e.get("content_version")
    return f"{item['reason']}|{item.get('reason_detail') or ''}|{e['entity_type']}:{e['entity_id']}|{'' if version is None else version}"


def snooze(user_id: int, actor, item_id: str, *, now: Optional[datetime] = None) -> Optional[dict]:
    """Snooze `item_id` ("I12" / "C3") for this person for `attention_snooze_minutes` → {item, snoozed_until}, or
    None when it is not on their list (there is nothing to put off). Snoozing again starts the time again."""
    from agenticops.services.attention import attention_items
    now = now or datetime.now(timezone.utc)
    row = next((i for i in attention_items(actor, now=now) if i["id"] == item_id), None)
    if row is None:
        return None
    until = now + timedelta(minutes=settings.attention_snooze_minutes)
    with get_db_session() as s:
        s.query(AttentionSnooze).filter(AttentionSnooze.user_id == user_id,
                                        (AttentionSnooze.item == item_id) | (AttentionSnooze.until <= now)).delete(synchronize_session=False)
        s.add(AttentionSnooze(user_id=user_id, item=item_id, situation=situation(row), until=until, created_at=now))
    return {"item": item_id, "snoozed_until": iso_z(until)}


def unsnooze(user_id: int, item_id: str) -> bool:
    """Take a snooze back. False = there was none."""
    with get_db_session() as s:
        return bool(s.query(AttentionSnooze).filter_by(user_id=user_id, item=item_id).delete(synchronize_session=False))


def mark(items: list[dict], user_id: Optional[int], now: datetime) -> None:
    """Give every item `snoozed_until`: an ISO time while this person's snooze of it applies — not ended, and the
    item still waits for what it waited for then —, else None. One query; none when no person is known."""
    for i in items:
        i["snoozed_until"] = None
    if user_id is None or not items:
        return
    with get_db_session() as s:
        rows = {r.item: (r.situation, r.until) for r in
                s.query(AttentionSnooze).filter(AttentionSnooze.user_id == user_id, AttentionSnooze.until > now)}
    for i in items:
        hit = rows.get(i["id"])
        if hit and hit[0] == situation(i) and as_utc(hit[1]) > now:
            i["snoozed_until"] = iso_z(hit[1])
