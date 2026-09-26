# tests/test_change_tools.py
import json
from unittest.mock import patch

import pytest

from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, get_session
from agenticops.run_context import run_context


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/tools.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[]); s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance", resource_id="i-0abc", name="web"))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None


def test_request_change_uses_context_actor_and_source(db):
    from agenticops.tools.change_tools import request_change
    with run_context(actor="user:alice", actor_user_id=1, actor_permissions=("read", "write"), chat_session_id="sess-1"), \
         patch("agenticops.services.change_service.start_review") as sr, \
         patch("agenticops.services.change_service.notify_change_requested"):
        out = request_change(title="Tag web", description="add Env=prod", account="dev", targets="i-0abc, i-0def")
    assert out.startswith("Change request C#")
    cr = db.query(ChangeRequest).one()
    assert cr.requested_by == "user:alice" and cr.source == "chat" and cr.chat_session_id == "sess-1"
    assert cr.target_hints == ["i-0abc", "i-0def"] and cr.status == "draft"
    sr.assert_not_called()  # in chat, Main calls review_change (sync) next — no async review here


def test_request_change_cli_source_and_errors(db):
    from agenticops.tools.change_tools import request_change
    with run_context(actor="cli:malibo"), patch("agenticops.services.change_service.start_review"), \
         patch("agenticops.services.change_service.notify_change_requested"):
        request_change(title="t", description="d")
        out = request_change(title="t", description="d", account="nope")
    assert db.query(ChangeRequest).one().source == "cli"
    assert "not found" in out  # ChangeValidationError rendered as text, not raised


def test_sre_tools_roundtrip(db):
    from agenticops.services import change_service as cs
    from agenticops.tools.change_tools import (
        attach_change_target, evaluate_change_policy, get_change_request, ground_change_targets, submit_change_review,
    )
    from agenticops.tools.metadata_tools import save_fix_plan
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="cli", actor=cs.Actor("cli", "m"), title="t", description="d",
                                      account_name="dev", targets=["i-0abc", "i-0def"], start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    with run_context(actor="agent:sre", change_request_id=cr["id"]):
        g = json.loads(ground_change_targets(cr["id"]))
        assert g["unresolved"] == ["i-0def"]
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"Reservations":[{}]}'):
            assert "attached" in attach_change_target(cr["id"], "i-0def", "ec2:instance")
        d = json.loads(evaluate_change_policy(cr["id"], "L1", "tag"))
        assert d["action"] == "auto_approve"
        save_fix_plan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="p", summary="s",
                      steps=json.dumps([{"action": "tag", "command": "aws ec2 create-tags"}]),
                      rollback_plan=json.dumps({"steps": ["aws ec2 delete-tags"]}),
                      post_checks=json.dumps([{"check": "present", "command": "aws ec2 describe-tags"}]))
        with patch.object(cs, "notify_change_pending_approval"):
            out = submit_change_review(cr["id"], "approved_for_planning", "L1", "tag", "single tag; low risk")
    assert "planned" in out
    data = json.loads(get_change_request(cr["id"]))
    assert data["status"] == "planned" and data["plan"]["status"] == "pending_approval" and data["review_reasons"][0] == "single tag"


def test_submit_review_error_is_text(db):
    from agenticops.tools.change_tools import submit_change_review
    out = submit_change_review(9999, "approved_for_planning", "L1", "tag", "x")
    assert "not found" in out


def test_execute_change_and_list(db):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    from agenticops.tools.change_tools import execute_change, list_change_requests
    with patch.object(cs, "request_execution", return_value={"execution_id": 7, "fix_plan_id": 3, "change": {"id": 1, "status": "executing"}}) as re:
        with run_context(actor="user:bob"):
            out = execute_change(1)
    assert "execution #7" in out.lower() and re.call_args.kwargs["actor"].key == "user:bob"
    with patch.object(cs, "notify_change_requested"):
        cs.create_change_request(source="cli", actor=cs.Actor("cli", "m"), title="t", description="d", start_review=False)
    rows = json.loads(list_change_requests())
    assert len(rows) == 1 and rows[0]["status"] == "draft"


def test_request_change_description_is_english_only():
    """Agent-facing text is English-only: the routing keywords match a request in any language."""
    import re
    from agenticops.tools.change_tools import request_change
    description = request_change.tool_spec["description"]
    assert "change request" in description and "in any language" in description
    assert not re.search(r"[一-鿿]", description)  # the CJK range test_prompt_budget checks prompts for
