"""API keys (MVP-2.8.0, owner 2026-11-10) — the rules behind «My API keys» and the admin's view of them.

- A key is ["read"] or ["read","write"]: never more than its owner's role (a viewer gets read only), never admin.
- The full key exists once — returned at creation; stored hashed; never listed, audited or shown to an admin.
- Revoking flips is_active (the row stays, so the list can say «已撤销»); an owner revokes their own, an admin anyone's.
- A demotion that takes write away downgrades the user's keys to read (one audit row each); nothing ever upgrades one.
- Every create / revoke / downgrade writes one audit row in the same transaction.
Managing keys needs a signed-in session, never a key (web/deps.require_session_user) — a leaked key cannot mint
its successor.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func

from agenticops.auth.models import APIKey, User
from agenticops.models import get_db_session

NAME_MAX = 100
EXPIRY_MAX_DAYS = 3650
_SCOPES = ({"read"}, {"read", "write"})


class ApiKeyError(Exception):
    """A refused key operation: the HTTP status, a stable code the page words, a sentence for logs / the API."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _row(k: APIKey) -> dict:
    return {"id": k.id, "name": k.name, "key_prefix": k.key_prefix, "permissions": list(k.permissions or []),
            "is_active": bool(k.is_active), "last_used_at": k.last_used_at, "expires_at": k.expires_at,
            "created_at": k.created_at}


def _audit(s, action: str, k: APIKey, caller, **details) -> None:
    from agenticops.audit.service import AuditService
    email = getattr(caller, "email", None)
    AuditService.log(action, "api_key", str(k.id), entity_name=k.name, user_id=getattr(caller, "id", None),
                     user_email=email, actor=f"user:{email}" if email else None,
                     details={"owner_id": k.user_id, "key_prefix": k.key_prefix, "permissions": list(k.permissions or []),
                              "expires_at": k.expires_at.isoformat() if k.expires_at else None, **details},
                     session=s)


def list_keys(user_id: int) -> list[dict]:
    with get_db_session() as s:
        return [_row(k) for k in s.query(APIKey).filter_by(user_id=user_id).order_by(APIKey.created_at.desc()).all()]


def create_key(user, *, name: str, permissions, expires_days: Optional[int], caller) -> tuple[dict, str]:
    from agenticops.auth.service import generate_api_key
    name = (name or "").strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise ApiKeyError(422, "invalid_name", f"a key name has 1–{NAME_MAX} characters")
    wanted = set(permissions or ())
    if wanted not in _SCOPES or len(wanted) != len(list(permissions or ())):
        raise ApiKeyError(422, "invalid_scope", 'a key is ["read"] or ["read","write"]')
    if "write" in wanted and "write" not in set(getattr(user, "permissions", None) or ()):
        raise ApiKeyError(403, "scope_exceeds_role", "a read-only account issues read-only keys")
    if expires_days is not None and not 1 <= int(expires_days) <= EXPIRY_MAX_DAYS:
        raise ApiKeyError(422, "invalid_expiry", f"a key expires in 1–{EXPIRY_MAX_DAYS} days, or never")
    key, key_hash = generate_api_key()
    with get_db_session() as s:
        k = APIKey(user_id=user.id, name=name, key_hash=key_hash, key_prefix=key[:12],
                   permissions=sorted(wanted, key=["read", "write"].index), is_active=True,
                   expires_at=_now() + timedelta(days=int(expires_days)) if expires_days else None)
        s.add(k)
        s.flush()
        _audit(s, "api_key.create", k, caller)
        return _row(k), key


def revoke_key(key_id: int, *, owner_id: int, caller, by_admin: bool) -> dict:
    with get_db_session() as s:
        k = s.query(APIKey).filter_by(id=key_id, user_id=owner_id).first()
        if k is None:
            raise ApiKeyError(404, "not_found", f"API key {key_id} not found")
        if k.is_active:
            k.is_active = False
            _audit(s, "api_key.revoke", k, caller, by_admin=by_admin)
        return _row(k)


def downgrade_keys(s, user_id: int, *, caller) -> int:
    """In the caller's transaction (services/user_admin.update_user): the user's keys that carry write become read."""
    n = 0
    for k in s.query(APIKey).filter(APIKey.user_id == user_id).all():
        if "write" in (k.permissions or []) or "admin" in (k.permissions or []):
            before = list(k.permissions or [])
            k.permissions = ["read"]
            _audit(s, "api_key.downgrade", k, caller, before=before)
            n += 1
    return n


def active_counts() -> dict[int, int]:
    """Active, unexpired keys per user id — one query (the user list's «API Key N»)."""
    now = _now()
    with get_db_session() as s:
        q = (s.query(APIKey.user_id, APIKey.expires_at)
             .filter(APIKey.is_active.is_(True)))
        out: dict[int, int] = {}
        for uid, exp in q.all():
            exp = _aware(exp)
            if exp is None or exp > now:
                out[uid] = out.get(uid, 0) + 1
        return out


def owner_exists(user_id: int) -> bool:
    with get_db_session() as s:
        return s.query(func.count(User.id)).filter(User.id == user_id).scalar() > 0
