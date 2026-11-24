"""Web-account administration (MVP-2.8.0 S2 rework, owner 2026-11-09) — the rules behind /api/users.

- A role is the user row's own `is_admin` + `permissions` (`auth/roles`), as `aiops users` stores it.
- Passwords are generated here (`secrets.token_urlsafe(12)`, like the CLI), returned once, never stored in clear,
  never written to the audit trail.
- Nobody disables or demotes themselves; the last active admin is never disabled or demoted.
- Disabling ends every session of the user and revokes every API key; re-enabling brings neither back — it clears
  what a CLI disable (which only flips is_active) left alive, and keys are re-issued. Resetting a password ends the user's
  sessions, except the caller's own current one when they reset their own (the new password must stay on screen).
- Every change writes one audit row in the same transaction as the change.
- Deleting (MVP-2.8.0, owner 2026-11-10) is soft: the row stays with `deleted_at` set, so its login name is never
  given to anyone else (records name people by `user:<email>`) and private chats / reports keep an owner nobody else
  can ever be. It ends the sessions, revokes the keys and removes unsent chat uploads at once; a deleted user is
  gone from every admin view (404 / not listed) and no sign-in path accepts them (auth/service). Refused for
  yourself, for the last active admin, and while a change request waits on them as its requester.
"""
import secrets
from typing import Optional

from sqlalchemy import update

from agenticops.auth.models import APIKey, Session, User
from agenticops.auth.roles import grants, role_of
from agenticops.models import get_db_session

EMAIL_MAX = 255
NAME_MAX = 100


class UserAdminError(Exception):
    """A refused change: the HTTP status, a stable code the page words, and a sentence for logs / the API."""

    def __init__(self, status: int, code: str, detail: str, extra: Optional[dict] = None):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail
        self.extra = extra or {}


def _row(u: User) -> dict:
    role, settings_view = role_of(u)
    return {"id": u.id, "email": u.email, "name": u.name, "role": role, "settings_view": settings_view,
            "is_active": bool(u.is_active), "last_login_at": u.last_login_at, "created_at": u.created_at}


def _role_values(u: User) -> dict:
    role, settings_view = role_of(u)
    return {"role": role, "settings_view": settings_view}


def _audit(s, action: str, u: User, caller, old: Optional[dict] = None, new: Optional[dict] = None) -> None:
    from agenticops.audit.service import AuditService
    email = getattr(caller, "email", None)
    AuditService.log(action, "user", str(u.id), entity_name=u.email, user_id=getattr(caller, "id", None),
                     user_email=email, actor=f"user:{email}" if email else None,
                     old_values=old, new_values=new, session=s)


def _get(s, user_id: int) -> User:
    u = s.query(User).filter_by(id=user_id).filter(User.deleted_at.is_(None)).first()
    if u is None:
        raise UserAdminError(404, "not_found", f"user {user_id} not found")
    return u


def _end_sessions(s, user_id: int, keep_token_hash: Optional[str] = None) -> None:
    q = s.query(Session).filter(Session.user_id == user_id)
    if keep_token_hash:
        q = q.filter(Session.token_hash != keep_token_hash)
    q.delete(synchronize_session=False)


def _other_active_admins(s, user_id: int) -> int:
    rows = s.query(User).filter(User.is_active.is_(True), User.deleted_at.is_(None), User.id != user_id).all()
    return sum(1 for u in rows if role_of(u)[0] == "admin")


def _grants(role: str, settings_view: bool) -> tuple[bool, list[str]]:
    try:
        return grants(role, settings_view)
    except ValueError as e:
        raise UserAdminError(422, "invalid_role", str(e))


def list_users() -> list[dict]:
    with get_db_session() as s:
        return [_row(u) for u in s.query(User).filter(User.deleted_at.is_(None)).order_by(User.email).all()]


def create_user(*, email: str, name: Optional[str], role: str, settings_view: bool, caller) -> tuple[dict, str]:
    from agenticops.auth.service import hash_password
    email = (email or "").strip()
    if not 1 <= len(email) <= EMAIL_MAX:
        raise UserAdminError(422, "invalid_email", f"a sign-in name has 1–{EMAIL_MAX} characters")
    is_admin, permissions = _grants(role, settings_view)
    name = (name or "").strip()[:NAME_MAX] or None
    password = secrets.token_urlsafe(12)
    with get_db_session() as s:
        taken = s.query(User).filter_by(email=email).first()
        if taken is not None and taken.deleted_at is not None:
            raise UserAdminError(409, "name_taken_by_deleted", f"{email!r} belonged to a deleted user; pick another name")
        if taken is not None:
            raise UserAdminError(409, "email_taken", f"a user named {email!r} exists")
        u = User(email=email, name=name, password_hash=hash_password(password), is_admin=is_admin,
                 permissions=permissions, is_active=True)
        s.add(u)
        s.flush()
        _audit(s, "user.create", u, caller, new={**_role_values(u), "is_active": True})
        return _row(u), password


def update_user(user_id: int, *, role: Optional[str] = None, settings_view: Optional[bool] = None,
                is_active: Optional[bool] = None, caller) -> dict:
    with get_db_session() as s:
        u = _get(s, user_id)
        old = _role_values(u)
        if role is None and settings_view is None:
            new = dict(old)
        else:
            target = role if role is not None else old["role"]
            new = {"role": target, "settings_view": bool(settings_view) if settings_view is not None else False}
        is_admin, permissions = _grants(new["role"], new["settings_view"])
        disable = is_active is False and u.is_active
        enable = is_active is True and not u.is_active
        demote = old["role"] == "admin" and new["role"] != "admin"
        if (demote or disable) and caller is not None and getattr(caller, "id", None) == u.id:
            raise UserAdminError(409, "self_change", "you cannot disable or demote yourself")
        if (demote or disable) and old["role"] == "admin" and u.is_active and _other_active_admins(s, u.id) == 0:
            raise UserAdminError(409, "last_admin", "the last active admin cannot be disabled or demoted")
        if new != old:
            u.is_admin, u.permissions = is_admin, permissions
            _audit(s, "user.update", u, caller, old=old, new=new)
            if "write" not in permissions:     # MVP-2.8.0: the user's keys lose write with the user; never regain it
                from agenticops.services.api_keys import downgrade_keys
                downgrade_keys(s, u.id, caller=caller)
        if disable:
            u.is_active = False
            _end_sessions(s, u.id)
            s.execute(update(APIKey).where(APIKey.user_id == u.id).values(is_active=False))
            _audit(s, "user.disable", u, caller, old={"is_active": True}, new={"is_active": False})
        if enable:
            u.is_active = True
            # what a disable that did not end them left behind (the CLI's only flips is_active): old sessions and
            # API keys stay dead — keys are re-issued (S2 rework review)
            _end_sessions(s, u.id)
            s.execute(update(APIKey).where(APIKey.user_id == u.id).values(is_active=False))
            _audit(s, "user.enable", u, caller, old={"is_active": False}, new={"is_active": True})
        s.flush()
        return _row(u)


def reset_password(user_id: int, *, caller, keep_token_hash: Optional[str] = None) -> str:
    from agenticops.auth.service import hash_password
    password = secrets.token_urlsafe(12)
    with get_db_session() as s:
        u = _get(s, user_id)
        u.password_hash = hash_password(password)
        own = caller is not None and getattr(caller, "id", None) == u.id
        _end_sessions(s, u.id, keep_token_hash if own else None)
        _audit(s, "user.reset_password", u, caller)
        return password


# change requests that wait on their requester (attention shows them only to that requester), or may come back to
# them: a review can return one as needs_clarification — so a requester with any of these is not deleted
_WAITING_ON_REQUESTER = ("draft", "needs_clarification", "under_review")


def delete_user(user_id: int, *, caller) -> None:
    """Soft-delete a user (see the module doc). One `user.delete` audit row; the unsent uploads' files go after the
    commit (their rows go in the transaction)."""
    from datetime import datetime, timezone
    from agenticops.chat.attachments import service as attachments, store
    from agenticops.models import ChangeRequest
    with get_db_session() as s:
        u = _get(s, user_id)
        if caller is not None and getattr(caller, "id", None) == u.id:
            raise UserAdminError(409, "self_change", "you cannot delete yourself")
        if role_of(u)[0] == "admin" and u.is_active and _other_active_admins(s, u.id) == 0:
            raise UserAdminError(409, "last_admin", "the last active admin cannot be deleted")
        key = f"user:{u.email}"
        open_ids = [cid for (cid,) in s.query(ChangeRequest.id)
                    .filter(ChangeRequest.requested_by == key, ChangeRequest.status.in_(_WAITING_ON_REQUESTER))
                    .order_by(ChangeRequest.id).all()]
        if open_ids:
            refs = [f"C#{cid}" for cid in open_ids]
            raise UserAdminError(409, "has_open_requests",
                                 f"{u.email} still has change requests waiting on them: {', '.join(refs)}",
                                 extra={"refs": refs})
        sessions = s.query(Session).filter(Session.user_id == u.id).count()
        keys = s.query(APIKey).filter(APIKey.user_id == u.id, APIKey.is_active.is_(True)).count()
        u.deleted_at = datetime.now(timezone.utc)
        u.is_active = False
        _end_sessions(s, u.id)
        s.execute(update(APIKey).where(APIKey.user_id == u.id).values(is_active=False))
        removed = attachments.delete_staged_of(s, key)
        _audit(s, "user.delete", u, caller, old={"deleted": False},
               new={"deleted": True, "sessions_ended": sessions, "keys_revoked": keys, "attachments_removed": len(removed)})
    for att_id in removed:
        store.remove_staged(att_id)
