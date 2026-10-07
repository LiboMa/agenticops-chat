"""A chat's context (MVP-2.7.0 S5): the linked object (an issue or a change) and the account the chat is bound to.

The server resolves it — a linked object's account and region are the object's own, and a client value that differs
is refused — and it locks at the first sent message (a new context = a new chat). The bound account is what each turn
puts on RunContext.bound_account_id, so every credentialed tool fails closed on any other account."""
from datetime import datetime, timezone

from agenticops.models import ChangeRequest, CloudAccount, HealthIssue

REF = {"health_issue": "I", "change_request": "C"}
_MODEL = {"health_issue": HealthIssue, "change_request": ChangeRequest}


class ContextError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code = status, code


def resolve_context(db, ctx: dict | None) -> dict:
    """The context as stored: {entity_type, entity_id, account_id, region}; raises ContextError (404 / 409 / 422)."""
    ctx = ctx or {}
    primary, account_id, region = ctx.get("primary"), ctx.get("account_id"), ctx.get("region") or None
    if primary:
        etype, eid = primary["entity_type"], primary["entity_id"]
        obj = db.get(_MODEL[etype], eid)
        if obj is None:
            raise ContextError(404, "context_not_found", f"{REF[etype]}#{eid} not found")
        own = obj.account_id
        if account_id is not None and own is not None and account_id != own:
            raise ContextError(409, "context_account_mismatch",
                               f"{REF[etype]}#{eid} belongs to account {own}, not {account_id}")
        md = getattr(obj, "metric_data", None)
        own_region = md.get("region") if isinstance(md, dict) else None
        return {"entity_type": etype, "entity_id": obj.id, "account_id": own, "region": own_region or region}
    if account_id is not None and db.get(CloudAccount, account_id) is None:
        raise ContextError(422, "unknown_account", f"account {account_id} does not exist")
    return {"entity_type": None, "entity_id": None, "account_id": account_id, "region": region}


def apply_context(row, resolved: dict) -> None:
    row.context_entity_type, row.context_entity_id = resolved["entity_type"], resolved["entity_id"]
    row.context_account_id, row.context_region = resolved["account_id"], resolved["region"]


def lock(row) -> None:
    if row.context_locked_at is None:
        row.context_locked_at = datetime.now(timezone.utc)


def context_views(db, rows) -> dict[int, dict]:
    """{row.id: view} for a page of sessions in at most three queries (accounts, issues, changes)."""
    acct_ids = {r.context_account_id for r in rows if r.context_account_id}
    names = dict(db.query(CloudAccount.id, CloudAccount.name).filter(CloudAccount.id.in_(acct_ids)).all()) if acct_ids else {}
    titles: dict[tuple[str, int], str] = {}
    for etype, model in _MODEL.items():
        ids = {r.context_entity_id for r in rows if r.context_entity_type == etype and r.context_entity_id}
        if ids:
            titles.update({(etype, i): t for i, t in db.query(model.id, model.title).filter(model.id.in_(ids)).all()})
    out = {}
    for r in rows:
        primary = None
        if r.context_entity_type in REF and r.context_entity_id:
            primary = {"entity_type": r.context_entity_type, "entity_id": r.context_entity_id,
                       "ref": f"{REF[r.context_entity_type]}#{r.context_entity_id}",
                       "title": titles.get((r.context_entity_type, r.context_entity_id))}
        out[r.id] = {"primary": primary, "account_id": r.context_account_id,
                     "account_name": names.get(r.context_account_id), "region": r.context_region,
                     "scope_locked": r.context_locked_at is not None}
    return out
