"""The four web-account roles (MVP-2.8.0 S2 rework), as `aiops users` has always stored them: a role is what the
user row's own `is_admin` + `permissions` flags say, never a separate column."""
from typing import Literal

Role = Literal["admin", "writer", "viewer"]
ROLES: tuple[Role, ...] = ("admin", "writer", "viewer")


def role_of(user) -> tuple[Role, bool]:
    """(role, settings_view) of a user row — the same reading as the CLI's `_user_role`."""
    perms = set(getattr(user, "permissions", None) or ())
    if getattr(user, "is_admin", False) or "admin" in perms:
        return "admin", False
    if "write" in perms:
        return "writer", False
    return "viewer", "settings_read" in perms


def grants(role: str, settings_view: bool = False) -> tuple[bool, list[str]]:
    """(is_admin, permissions) to store for a role. `settings_view` (may view Settings read-only) is a viewer's
    only; on any other role, or an unknown role, ValueError."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    if settings_view and role != "viewer":
        raise ValueError("settings_view applies to a viewer only")
    if role == "admin":
        return True, ["read", "write", "admin"]
    if role == "writer":
        return False, ["read", "write"]
    return False, ["read", "settings_read"] if settings_view else ["read"]
