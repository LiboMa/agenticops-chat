"""How far this installation is set up (MVP-2.9.0 N23, the 2.8.0 spec's S6): cloud accounts, the main model, who
approves and what runs, message channels — and the record of the last time an account's connection and the model
were actually checked.

«Configured» and «verified» are two things. A check row names what it checked — an account WITH the fingerprint of
its credentials, a model id WITH the region it is called in — so after an account is pointed at other credentials,
or Main is given another model, the old check no longer counts and the item reads «configured, not verified yet».
"""
from __future__ import annotations

import re

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

from agenticops.config import get_agent_model_config, settings
from agenticops.services import exec_switches
from agenticops.models import CloudAccount, ReadinessCheck, get_db_session

DETAIL_MAX = 500
VERIFY_MAX_TOKENS = 16          # all a model verification may spend on output
CUT_AT_LIMIT = "cut_at_limit"   # the reply stopped at those tokens (or was thinking only): the model was reached


def account_subject(account) -> str:
    """The account and the credentials a connection test was made with."""
    from agenticops.credentials.resolver import credential_fingerprint
    snap = SimpleNamespace(credential_source_type=getattr(account, "credential_source_type", "") or "",
                           credentials=dict(account.credentials or {}))
    return f"{account.id}:{credential_fingerprint(snap)}"


def model_subject(model_id: str, region: str) -> str:
    return f"{model_id}@{region}"


def _iso(ts: Optional[datetime]) -> Optional[str]:
    if ts is None:
        return None
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _view(row: Optional[ReadinessCheck]) -> Optional[dict]:
    if row is None:
        return None
    return {"ok": bool(row.ok), "detail": row.detail or "", "checked_at": _iso(row.checked_at), "checked_by": row.checked_by or ""}


def _latest(session, kind: str, subject: str) -> Optional[ReadinessCheck]:
    return (session.query(ReadinessCheck).filter(ReadinessCheck.kind == kind, ReadinessCheck.subject == subject)
            .order_by(ReadinessCheck.checked_at.desc(), ReadinessCheck.id.desc()).first())


def record_check(session, kind: str, subject: str, ok: bool, detail: str, checked_by: str) -> ReadinessCheck:
    """Add one check to `session` (the caller commits). The detail is masked and cut: it is shown on a page."""
    from agenticops.security.redaction import redact_secrets
    row = ReadinessCheck(kind=kind, subject=subject, ok=bool(ok),
                         detail=(redact_secrets(detail or "") or "")[:DETAIL_MAX], checked_by=checked_by or "")
    session.add(row)
    session.flush()
    return row


_REFUSED_CALL = re.compile(r"An error occurred \(([^)]+)\) when calling the (\S+) operation")


def kept_reason(result: dict) -> str:
    """What is kept — and shown to every signed-in account on the setup overview — of a failed account test: the
    test's own `reason` (an error code and operation), else those two read out of a refused call's sentence. The
    sentence itself names the calling principal, the role and both account numbers (MVP-2.9.0 N27, review; the
    model check keeps code + operation for the same reason). Any other text is kept as it is (masked and cut)."""
    if result.get("reason"):
        return str(result["reason"])
    text = str(result.get("error") or "failed")
    refused = _REFUSED_CALL.search(text)
    return f"{refused.group(1)} ({refused.group(2)})" if refused else text


def record_account_test(session, account, result: dict, checked_by: str) -> None:
    """What `POST /api/accounts/{id}/test` found, kept (it used to answer and forget). A test that gave no verdict
    — there is none for this provider — records nothing: the account stays «configured · not verified»."""
    if result.get("untested"):
        return
    record_check(session, "account", account_subject(account), bool(result.get("success")),
                 "" if result.get("success") else kept_reason(result), checked_by)


def _accounts(session) -> dict:
    rows = session.query(CloudAccount).filter(CloudAccount.is_enabled == True).order_by(CloudAccount.name).all()  # noqa: E712
    items = [{"id": a.id, "name": a.name, "provider": a.provider, "regions": len(a.regions or []),
              "check": _view(_latest(session, "account", account_subject(a)))} for a in rows]
    checks = [i["check"] for i in items]
    if not items:
        state = "missing"
    elif any(c is not None and not c["ok"] for c in checks):
        state = "failed"
    elif all(c is not None for c in checks):
        state = "connected"
    else:
        state = "configured"                    # there, and not (all) tested with the credentials it has now
    return {"state": state, "enabled": len(items), "regions": len({r for a in rows for r in (a.regions or [])}), "items": items}


def _where(model_id: str) -> tuple[str, Optional[str], Optional[str]]:
    """Where Main's model is called: (provider, Bedrock region, provider endpoint). A Bedrock model is called in
    bedrock_region; another provider's (MVP-2.9.0 N35) at its base URL — so pointing the provider elsewhere voids
    the old check, as a new region does."""
    from agenticops.llm import registry
    from agenticops.llm.refs import parse_ref
    try:
        ref = parse_ref(model_id)
    except ValueError:
        return "bedrock", settings.bedrock_region, None
    if ref.is_bedrock:
        return "bedrock", settings.bedrock_region, None
    cfg = registry.get(ref.provider)
    return ref.provider, None, (cfg.base_url if cfg else "")


def _model_subject_of(model_id: str) -> tuple[str, Optional[str], Optional[str], str]:
    provider, region, endpoint = _where(model_id)
    return provider, region, endpoint, model_subject(model_id, region if region is not None else endpoint or "")


def _model(session) -> dict:
    model_id, _max_tokens = get_agent_model_config("main")
    # where the model is CALLED — not where resources are scanned
    provider, region, endpoint, subject = _model_subject_of(model_id)
    check = _view(_latest(session, "model", subject))
    state = "configured" if check is None else "verified" if check["ok"] else "failed"
    return {"state": state, "model_id": model_id, "provider": provider, "region": region, "endpoint": endpoint,
            "check": check}


def _execution(actor) -> dict:
    from agenticops.services.ui_actions import route_allows
    read_only = bool(getattr(actor, "read_only", False))
    # who approves: an L0 / L1 fix plan is approved without a person when the pipeline and its auto-approval are on
    # (pipeline_service.trigger_auto_approve — the executor switch decides whether it then RUNS, not this), a
    # standard change when its switch is
    switches = exec_switches.effective()        # the values in force (N25), not the yaml's
    automatic = (switches.auto_fix_enabled and switches.executor_auto_approve_l0_l1) or settings.change_auto_approve_standard
    return {"state": "read_only" if read_only else "partly_automatic" if automatic else "manual",
            "executor_enabled": switches.executor_enabled, "auto_fix_enabled": switches.auto_fix_enabled,
            "auto_approve_l0_l1": switches.executor_auto_approve_l0_l1, "rbac_enforce": bool(settings.rbac_enforce),
            "change_auto_approve_standard": bool(settings.change_auto_approve_standard),
            # «may this person approve a plan at all»: asked about no plan in particular (the rules that read a
            # plan need one to be named — an empty one — or they refuse, fail-closed); route_allows answers «no»
            # for a read-only account by itself
            "you_can_approve": bool(route_allows(actor, "plan.approve", SimpleNamespace(risk_level=None))[0]),
            "read_only": read_only}


def _notifications() -> dict:
    try:
        from agenticops.notify import im_config
        channels = sum(1 for c in im_config.load_channels() if getattr(c, "is_enabled", True))
    except Exception:
        channels = 0
    return {"state": "optional", "channels": channels}      # never blocks a first task


def readiness(actor, *, can_verify: bool) -> dict:
    """The four items of the setup overview, for a signed-in person. Reads only — it never runs a check."""
    with get_db_session() as session:
        accounts, model = _accounts(session), _model(session)
    return {"accounts": accounts, "model": model, "execution": _execution(actor), "notifications": _notifications(),
            "can_verify": bool(can_verify), "generated_at": _iso(datetime.now(timezone.utc))}


def _model_failure(exc: BaseException, failure_reason) -> str:
    """What is kept of a failed verification: for another provider's model (N35) the SDK error's class and HTTP
    status, or why the model cannot be built — never the provider's sentence (an authentication failure can quote
    the key it was given); for Bedrock the error's code and operation (failure_reason)."""
    from agenticops.llm.factory import ModelProviderUnavailable
    if isinstance(exc, ModelProviderUnavailable):
        return exc.reason
    if (type(exc).__module__ or "").split(".")[0] in ("openai", "anthropic"):
        status = getattr(exc, "status_code", None)
        return f"{type(exc).__name__} ({status})" if status else type(exc).__name__
    return failure_reason(exc)


def verify_model(actor) -> dict:
    """One tiny call to Main's model (at most VERIFY_MAX_TOKENS of output), recorded and audited. A reply that stops
    at that limit — a model that thinks first can spend it all — is still an answer: the model was reached with
    these credentials, in this region, under this id. A refused or failed call is a failed verification whose
    detail is the error's code and operation, not its message."""
    from agenticops.agents.preamble import ModelReplyError, converse_text
    from agenticops.audit.service import AuditService
    from agenticops.security.collectors import failure_reason

    model_id, _max_tokens = get_agent_model_config("main")
    provider, region, endpoint, subject = _model_subject_of(model_id)
    try:
        converse_text(model_id, "Reply with the single word: pong", max_tokens=VERIFY_MAX_TOKENS, read_timeout=60, total_attempts=1)
        ok, detail = True, ""
    except ModelReplyError:
        ok, detail = True, CUT_AT_LIMIT
    except Exception as exc:
        ok, detail = False, _model_failure(exc, failure_reason)
    with get_db_session() as session:
        row = record_check(session, "model", subject, ok, detail, actor.key)
        AuditService.log("verify_model", "readiness_check", str(row.id), entity_name=model_id, actor=actor.key,
                         user_id=actor.user_id, new_values={"ok": ok, "region": region, "provider": provider},
                         session=session)
        view = _view(row)
    return {**view, "model_id": model_id, "provider": provider, "region": region, "endpoint": endpoint}
