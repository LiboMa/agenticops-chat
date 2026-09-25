from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from agenticops.models import Base, CloudAccount, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cli.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[])); s.commit()
    yield s
    s.close()
    models_mod._engine = None


def test_helpers():
    from agenticops.cli.main import _extract_target_hints, _parse_change_ref
    assert _extract_target_hints("tag i-0abc12345678 and sg-1234abcd plus arn:aws:s3:::b1") == ["i-0abc12345678", "sg-1234abcd", "arn:aws:s3:::b1"]
    assert _parse_change_ref("C12") == 12 and _parse_change_ref("c#7") == 7 and _parse_change_ref("12") is None


def test_slash_change_creates_and_reviews_sync(db):
    from agenticops.cli import main as cli
    with patch("agenticops.cli.main.init_db"), \
         patch("agenticops.services.change_service.start_review", return_value="SRE: planned, L1") as sr, \
         patch("agenticops.services.change_service.notify_change_requested"), \
         patch("getpass.getuser", return_value="malibo"):
        out = cli._slash_change(None, ["add", "tag", "Env=prod", "to", "i-0abc12345678", "--account", "dev"])
    assert "C#" in out and "SRE: planned, L1" in out
    from agenticops.models import ChangeRequest
    cr = db.query(ChangeRequest).one()
    assert cr.source == "cli" and cr.requested_by == "cli:malibo" and cr.target_hints == ["i-0abc12345678"] and cr.account_id is not None
    sr.assert_called_once_with(cr.id, sync=True)


def test_slash_change_disabled(db):
    from agenticops.cli import main as cli
    from agenticops.config import settings
    with patch.object(settings, "change_management_enabled", False), patch("agenticops.cli.main.init_db"):
        assert "disabled" in cli._slash_change(None, ["x"])


def test_slash_approve_reject_execute_changes(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch("getpass.getuser", return_value="malibo"):
        with patch.object(cs, "approve", return_value={"id": 4, "status": "approved"}) as ap:
            out = cli._slash_approve(None, ["C4", "looks", "good"])
        assert "approved" in out and ap.call_args.kwargs["reason"] == "looks good" and ap.call_args.kwargs["actor"].key == "cli:malibo"
        with patch.object(cs, "reject", return_value={"id": 4, "status": "rejected"}) as rj:
            out = cli._slash_reject(None, ["C4", "not", "now"])
        assert "rejected" in out and rj.call_args.kwargs["reason"] == "not now"
        assert "Usage" in cli._slash_reject(None, ["C4"])  # reason required
        with patch.object(cs, "get_change", return_value={"id": 4, "status": "approved", "title": "t", "risk_level": "L1"}), \
             patch.object(cs, "request_execution", return_value={"execution_id": 9, "fix_plan_id": 2, "change": {}}) as ex, \
             patch("rich.prompt.Confirm.ask", return_value=True):
            out = cli._slash_execute(None, ["C4"])
        assert "Execution #9" in out and ex.called
        with patch.object(cs, "approve", side_effect=cs.ChangeStateError("is 'approved'")):
            assert "approved" in cli._slash_approve(None, ["C4", "again"])


def test_slash_changes_lists(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    rows = [{"id": 1, "title": "Tag web", "status": "planned", "risk_level": "L1", "effective_change_type": "standard",
             "requested_by": "cli:m", "updated_at": "2026-09-17T00:00:00"}]
    with patch("agenticops.cli.main.init_db"), patch.object(cs, "list_changes", return_value=rows) as lc:
        out = cli._slash_changes(None, ["planned"])
    assert "Tag web" in out or "C#1" in out
    assert lc.call_args.kwargs["status"] == "planned"


def test_slash_changes_never_truncates_the_change_id(db):
    """At the 120-column render the id must stay whole: a `C#…` cell names nothing to /approve."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    rows = [{"id": 1234, "title": "Add Env=prod tag to i-0abc12345678 for the quarterly audit", "status": "needs_clarification",
             "risk_level": "L2", "effective_change_type": "emergency", "requested_by": "cli:malibo",
             "updated_at": "2026-09-18T01:02:03+00:00"}]
    with patch("agenticops.cli.main.init_db"), patch.object(cs, "list_changes", return_value=rows):
        out = cli._slash_changes(None, [])
    for text in ("C#1234", "needs clarification", "emergency", "cli:malibo", "2026-09-18T01:02:03"):
        assert text in out


# ── Controller rulings ───────────────────────────────────────────────


def test_slash_approve_change_prompts_for_a_missing_reason(db):
    """Ruling 4: `Prompt` is bound before the C<id> branch, and an empty answer never approves."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch("getpass.getuser", return_value="malibo"):
        with patch.object(cs, "approve") as ap, patch("rich.prompt.Prompt.ask", return_value=""):
            out = cli._slash_approve(None, ["C4"])
        assert "A reason is required" in out
        ap.assert_not_called()
        with patch.object(cs, "approve", return_value={"id": 4, "status": "approved"}) as ap, \
             patch("rich.prompt.Prompt.ask", return_value="ok"):
            cli._slash_approve(None, ["C4"])
        assert ap.call_args.kwargs["reason"] == "ok"


def test_slash_change_says_when_the_review_did_not_complete(db):
    """Ruling 5: a CR still in draft after the review is reported as not reviewed, never with a ✓."""
    from agenticops.cli import main as cli
    with patch("agenticops.cli.main.init_db"), \
         patch("agenticops.services.change_service.start_review", return_value=None), \
         patch("agenticops.services.change_service.notify_change_requested"):
        out = cli._slash_change(None, ["tag", "i-0abc12345678"])
    assert "did not complete" in out and "no verdict was recorded" in out
    assert "✓" not in out


def test_slash_change_shows_the_reason_a_real_review_rolled_back(db):
    """Ruling 5 end to end: the real service rolls a verdict-less review back and /change shows its reason."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), \
         patch.object(cs, "notify_change_requested"), patch.object(cs, "notify_change_result"), \
         patch("agenticops.agents.sre_agent.sre_agent_review_change", return_value="I forgot to submit"):
        out = cli._slash_change(None, ["tag", "i-0abc12345678"])
    assert "status: draft" in out and "did not complete (review ended without a verdict" in out
    assert "✓" not in out


def test_slash_change_reports_a_completed_review(db):
    """The ✓ head: a review that recorded a verdict shows the status and risk the platform stored."""
    from agenticops.cli import main as cli
    from agenticops.models import ChangeRequest

    def _review(cr_id, *, sync):
        s = get_session()
        cr = s.get(ChangeRequest, cr_id)
        cr.status, cr.risk_level = "planned", "L1"
        s.commit()
        s.close()
        return "SRE: planned, L1"

    with patch("agenticops.cli.main.init_db"), \
         patch("agenticops.services.change_service.start_review", side_effect=_review), \
         patch("agenticops.services.change_service.notify_change_requested"):
        out = cli._slash_change(None, ["tag", "i-0abc12345678"])
    cr = db.query(ChangeRequest).one()
    assert f"✓ Change request C#{cr.id} — status: planned · risk L1" in out
    assert "did not complete" not in out


def test_usage_help_and_command_table_name_change_refs():
    """Ruling 6 + wiring: usage lines and /help name C<id>; the three new commands are dispatchable."""
    from agenticops.cli import main as cli
    assert "/approve <plan_id|C<id>> [reason...]" in cli._slash_approve(None, [])
    assert "/execute <plan_id|C<id>>" in cli._slash_execute(None, [])
    help_text = cli._slash_help(None, [])
    assert "/approve <plan_id|C<id>> [reason...]" in help_text and "/execute <plan_id|C<id>>" in help_text
    assert "Changes:" in help_text and "/change <description>" in help_text
    assert "/changes " in help_text and "/reject C<id> <reason>" in help_text
    assert cli.SLASH_COMMANDS["change"] is cli._slash_change
    assert cli.SLASH_COMMANDS["changes"] is cli._slash_changes
    assert cli.SLASH_COMMANDS["reject"] is cli._slash_reject


def test_reference_links_include_change_refs():
    """Ruling 7: C#N is linked once (de-duplicated) next to the existing I#N / R#N links."""
    from agenticops.cli.display import format_reference_links
    out = format_reference_links("see C#7, I#3 and C#7 again", "http://x")
    assert out.count("C#7 → http://x/app/changes/7") == 1
    assert "I#3 → http://x/app/issues/3" in out


# ── Free text is shown literally (titles, SRE text, rollback reasons) ──


def _plain_console(buf: StringIO, width: int) -> Console:
    """Markup is still parsed; color_system=None keeps highlighter ANSI out of the text (FORCE_COLOR may be set)."""
    return Console(file=buf, width=width, color_system=None)


def _as_the_repl_prints_it(out: str) -> str:
    """The REPL prints a handler's return value with console.print, which parses Rich markup."""
    buf = StringIO()
    _plain_console(buf, 1000).print(out)
    return buf.getvalue()


def test_slash_changes_shows_bracketed_titles_literally(db):
    """`[urgent]` must not vanish as a Rich tag and `[/var/log]` must not raise, in the table or in the REPL's print."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    rows = [{"id": 5, "title": "[urgent] rotate logs in [/var/log]", "status": "planned", "risk_level": "L1",
             "effective_change_type": "normal", "requested_by": "web:ops", "updated_at": "2026-09-18T01:02:03"}]
    with patch("agenticops.cli.main.init_db"), patch.object(cs, "list_changes", return_value=rows):
        out = cli._slash_changes(None, [])
    seen = _as_the_repl_prints_it(out)
    assert "[urgent]" in seen and "[/var/log]" in seen


def test_slash_change_output_survives_bracketed_review_text(db):
    """SRE text and a rollback reason are shown as written; a `[/...]` in either must not crash the REPL's print."""
    from agenticops.cli import main as cli
    from agenticops.models import ChangeRequest

    def _review(cr_id, *, sync):
        s = get_session()
        s.get(ChangeRequest, cr_id).review_reasons = ["review crashed reading [/var/log]"]
        s.commit()
        s.close()
        return "Checked [/var/log] on the [prod] hosts"

    with patch("agenticops.cli.main.init_db"), \
         patch("agenticops.services.change_service.start_review", side_effect=_review), \
         patch("agenticops.services.change_service.notify_change_requested"):
        out = cli._slash_change(None, ["rotate", "logs"])
    seen = _as_the_repl_prints_it(out)
    assert "did not complete (review crashed reading [/var/log])" in seen
    assert "Checked [/var/log] on the [prod] hosts" in seen


def test_slash_execute_change_confirmation_shows_the_whole_title(db):
    """The human confirming an execution sees the title as written: `[prod]` is not a Rich tag."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    buf = StringIO()
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(buf, 200)), \
         patch.object(cs, "get_change", return_value={"id": 4, "status": "approved", "title": "[prod] delete old snapshots",
                                                      "risk_level": "L2"}), \
         patch.object(cs, "request_execution") as ex, patch("rich.prompt.Confirm.ask", return_value=False):
        out = cli._slash_execute(None, ["C4"])
    assert "Title: [prod] delete old snapshots" in buf.getvalue()
    assert "cancelled" in out and not ex.called
