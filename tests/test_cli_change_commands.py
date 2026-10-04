from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from agenticops.models import Base, CloudAccount, get_session


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(settings, "change_management_enabled", True)
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cli.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[])); s.commit()
    yield s
    s.close()
    models_mod._engine = None


def _plain_console(buf: StringIO, width: int) -> Console:
    """Markup is still parsed; color_system=None keeps highlighter ANSI out of the text (FORCE_COLOR may be set)."""
    return Console(file=buf, width=width, color_system=None)


def _as_the_repl_prints_it(out: str) -> str:
    """The REPL prints a handler's return value with console.print, which parses Rich markup."""
    buf = StringIO()
    _plain_console(buf, 1000).print(out)
    return buf.getvalue()


def _review_stores(status, risk_level=None, text="SRE: planned, L1"):
    """A start_review stand-in: leaves the row the way a finished review does, then returns the SRE's text."""
    from agenticops.models import ChangeRequest

    def _review(cr_id, *, sync):
        s = get_session()
        cr = s.get(ChangeRequest, cr_id)
        cr.status, cr.risk_level = status, risk_level
        s.commit()
        s.close()
        return text
    return _review


def _cr(status, **fields):
    """A change_service.get_change result, trimmed to the keys the CLI reads."""
    return {"id": 4, "status": status, "title": "Tag web", "risk_level": "L1", "requested_change_type": "normal",
            "effective_change_type": None, **fields}


def _row(**fields):
    """One change_service.list_changes row."""
    return {"id": 1, "title": "Tag web", "status": "planned", "risk_level": "L1", "effective_change_type": "standard",
            "requested_by": "cli:m", "updated_at": "2026-09-17T00:00:00", **fields}


def test_helpers():
    from agenticops.cli.main import _extract_target_hints, _parse_change_ref
    assert _extract_target_hints("tag i-0abc12345678 and sg-1234abcd plus arn:aws:s3:::b1") == ["i-0abc12345678", "sg-1234abcd", "arn:aws:s3:::b1"]
    assert _parse_change_ref("C12") == 12 and _parse_change_ref("c#7") == 7 and _parse_change_ref("12") is None
    # Minor 6: exactly C<digits> or C#<digits>; a stray '#', a letter or a non-ASCII digit is not a change ref
    assert [_parse_change_ref(t) for t in ("C#12", " C3 ", "C0")] == [12, 3, 0]
    for token in ("12", "C", "CX", "C1#2", "#C12", "C²"):
        assert _parse_change_ref(token) is None, token
    # Minor 11: a hex id ends at a word boundary (a 20-hex id is no id); an ARN never ends in . , ; : )
    assert _extract_target_hints("i-0123456789abcdef0123") == []
    assert _extract_target_hints("(sg-1234abcd).") == ["sg-1234abcd"]
    assert _extract_target_hints("see arn:aws:s3:::b1.") == ["arn:aws:s3:::b1"]
    assert _extract_target_hints("arn:aws:iam::123456789012:role/x)") == ["arn:aws:iam::123456789012:role/x"]


def test_slash_change_creates_and_reviews_sync(db):
    from agenticops.cli import main as cli
    from agenticops.models import ChangeRequest
    buf = StringIO()
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(buf, 1000)), \
         patch("agenticops.services.change_service.start_review", side_effect=_review_stores("planned", "L1")) as sr, \
         patch("agenticops.services.change_service.notify_change_requested"), \
         patch("getpass.getuser", return_value="malibo"):
        out = cli._slash_change(None, ["add", "tag", "Env=prod", "to", "i-0abc12345678", "--account", "dev"])
    cr = db.query(ChangeRequest).one()
    assert f"✓ Change request C#{cr.id} — status: planned · risk L1" in out
    assert "SRE: planned, L1" in buf.getvalue()
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
        with patch.object(cs, "get_change", return_value=_cr("planned", title="t")), \
             patch("rich.prompt.Confirm.ask", return_value=True), \
             patch.object(cs, "approve_and_execute", return_value={"id": 4, "status": "executing"}) as ap:
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
        with patch.object(cs, "get_change", return_value=_cr("planned", title="t")), \
             patch("rich.prompt.Confirm.ask", return_value=True), \
             patch.object(cs, "approve_and_execute", side_effect=cs.ChangeStateError("is 'approved'")):
            assert "approved" in cli._slash_approve(None, ["C4", "again"])


def test_slash_approve_change_runs_it(db):
    """Owner ruling 2026-10-03: /approve C<id> approves AND queues the run; /execute C<id> is only the retry."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch("getpass.getuser", return_value="malibo"), \
         patch.object(cs, "get_change", return_value=_cr("planned", title="t")), \
         patch("rich.prompt.Confirm.ask", return_value=True):
        with patch.object(cs, "approve_and_execute", return_value={"id": 4, "status": "executing"}) as ae:
            out = cli._slash_approve(None, ["C4", "looks", "good"])
        assert ae.call_args.kwargs["actor"].key == "cli:malibo" and ae.call_args.kwargs["reason"] == "looks good"
        assert "approved" in out and "queued for execution" in out and "/execute" not in out
        with patch.object(cs, "approve_and_execute", return_value={"id": 4, "status": "approved"}):
            out = cli._slash_approve(None, ["C4", "looks", "good"])
        assert "could not be queued" in out and "/execute C4" in out


def test_slash_changes_lists(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    rows = [{"id": 1, "title": "Tag web", "status": "planned", "risk_level": "L1", "effective_change_type": "standard",
             "requested_by": "cli:m", "updated_at": "2026-09-17T00:00:00"}]
    with patch("agenticops.cli.main.init_db"), patch.object(cs, "list_changes", return_value=rows) as lc:
        out = cli._slash_changes(None, ["planned"])
    assert "Tag web" in out and "C#1" in out
    assert lc.call_args.kwargs["status"] == "planned"


def test_slash_changes_never_truncates_the_change_id(db):
    """At the 120-column render the id must stay whole: a `C#…` cell names nothing to /approve."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    rows = [{"id": 1234, "title": "Add Env=prod tag to i-0abc12345678 for the quarterly audit", "status": "needs_clarification",
             "risk_level": "L2", "effective_change_type": "emergency", "requested_by": "cli:malibo",
             "updated_at": "2026-09-18T01:02:03+00:00"}]
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", Console(file=StringIO(), width=120)), \
         patch.object(cs, "list_changes", return_value=rows):
        out = cli._slash_changes(None, [])
    for text in ("C#1234", "needs clarification", "emergency", "cli:malibo", "2026-09-18 01:02"):
        assert text in out


# ── Controller rulings ───────────────────────────────────────────────


def test_slash_approve_change_prompts_for_a_missing_reason(db):
    """Ruling 4: `Prompt` is bound before the C<id> branch, and an empty answer never approves."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch("getpass.getuser", return_value="malibo"), \
         patch.object(cs, "get_change", return_value=_cr("planned", title="t")):
        with patch.object(cs, "approve_and_execute") as ap, patch("rich.prompt.Prompt.ask", return_value=""), \
             patch("rich.prompt.Confirm.ask") as ca:
            out = cli._slash_approve(None, ["C4"])
        assert "A reason is required" in out
        ap.assert_not_called()
        ca.assert_not_called()
        with patch.object(cs, "approve_and_execute", return_value={"id": 4, "status": "executing"}) as ap, \
             patch("rich.prompt.Prompt.ask", return_value="ok"), patch("rich.prompt.Confirm.ask", return_value=True):
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
    """Ruling 6 + wiring: usage lines and /help name C<id>; the three new commands are dispatchable.
    Minor 12: `[reason...]` is escaped in the raw strings, so Rich prints it instead of eating it as a tag."""
    from agenticops.cli import main as cli
    usage = cli._slash_approve(None, [])
    help_text = cli._slash_help(None, [])
    assert "\\[reason...]" in usage and "\\[reason...]" in help_text
    assert "/approve <plan_id|C<id>> [reason...]" in _as_the_repl_prints_it(usage)
    assert "/approve <plan_id|C<id>> [reason...]" in _as_the_repl_prints_it(help_text)
    assert "/execute <plan_id|C<id>>" in cli._slash_execute(None, [])
    assert "/execute <plan_id|C<id>>" in help_text
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

    buf = StringIO()
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(buf, 1000)), \
         patch("agenticops.services.change_service.start_review", side_effect=_review), \
         patch("agenticops.services.change_service.notify_change_requested"):
        out = cli._slash_change(None, ["rotate", "logs"])
    assert "did not complete (review crashed reading [/var/log])" in _as_the_repl_prints_it(out)
    assert "Checked [/var/log] on the [prod] hosts" in buf.getvalue()


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


# ── Kill switch: every CLI change entry point (review Imp #1) ──────────

_DISABLED = "[yellow]Change management is disabled (change_management_enabled=false).[/yellow]"


@pytest.mark.parametrize("command,args", [
    ("_slash_changes", []), ("_slash_reject", ["C4", "no"]), ("_slash_approve", ["C4", "ok"]), ("_slash_execute", ["C4"]),
])
def test_kill_switch_covers_every_cli_change_command(db, command, args):
    """With change management off each entry point answers "disabled" before any service call or prompt
    (/change itself: test_slash_change_disabled)."""
    from agenticops.cli import main as cli
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    with patch.object(settings, "change_management_enabled", False), patch("agenticops.cli.main.init_db"), \
         patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch.object(cs, "list_changes", return_value=[]) as lc, patch.object(cs, "reject") as rj, \
         patch.object(cs, "get_change", return_value=_cr("approved")) as gc, patch.object(cs, "approve") as ap, \
         patch.object(cs, "request_execution") as ex, patch("rich.prompt.Prompt.ask", return_value="ok") as pa, \
         patch("rich.prompt.Confirm.ask", return_value=True) as ca:
        out = getattr(cli, command)(None, args)
    assert out == _DISABLED
    for reached in (lc, rj, gc, ap, ex, pa, ca):
        reached.assert_not_called()


def test_kill_switch_leaves_the_fix_plan_path_alone(db):
    """Only C<id> is gated: with the flag off a plain plan id still reaches the fix-plan code."""
    from agenticops.cli import main as cli
    from agenticops.config import settings
    with patch.object(settings, "change_management_enabled", False), patch("agenticops.cli.main.init_db"):
        assert "Fix plan #12 not found." in cli._slash_approve(None, ["12"])
        assert "Fix plan #12 not found." in cli._slash_execute(None, ["12"])


# ── /changes: plain text at the terminal's width (Imp #2, Minors 1, 2, 10) ──


def test_slash_changes_returns_text_the_repl_can_print(db):
    """No ANSI in the returned table: the REPL console's highlighter bolds the `[` of every "\\x1b[" it is
    given, and the terminal then shows colour codes as literal fragments."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cs, "list_changes", return_value=[_row()]):
        out = cli._slash_changes(None, [])
    assert "\x1b" not in out
    repl = StringIO()
    # the REPL console's settings (main.py `console`); colour pinned on so the check cannot pass vacuously
    Console(file=repl, highlight=True, force_terminal=True, tab_size=2, width=200, color_system="truecolor").print(out)
    assert "\x1b\x1b[" not in repl.getvalue()


def test_slash_changes_fits_the_terminal_and_keeps_the_id_whole(db):
    """Rendered at the REPL console's width; only C# refuses to wrap, so a 5-digit id stays whole and no line
    is wider than the terminal."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    title = "Add Env=prod tag to the web and db hosts"
    assert len(title) == 40
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", Console(file=StringIO(), width=60)), \
         patch.object(cs, "list_changes", return_value=[_row(id=12345, title=title)]):
        out = cli._slash_changes(None, [])
    assert "C#12345" in out
    assert max(len(line) for line in out.splitlines()) <= 60


@pytest.mark.parametrize("args", [["needs", "clarification"], ["needs-clarification"]])
def test_slash_changes_filters_by_the_status_as_displayed(db, args):
    """The table shows `needs clarification`; that spelling (and the dashed one) is the filter."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cs, "list_changes", return_value=[]) as lc:
        cli._slash_changes(None, args)
    assert lc.call_args.kwargs["status"] == "needs_clarification"


def test_slash_changes_rejects_an_unknown_status(db):
    """An unknown status is named with the valid ones — never a silent "No change requests found."."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cs, "list_changes") as lc:
        out = cli._slash_changes(None, ["bogus"])
    assert "Unknown status 'bogus'" in out and "Valid:" in out and "planned" in out
    lc.assert_not_called()


# ── /change: flags, and a head that tells what the review recorded (Minors 3, 7, 8, 11, 13) ──


def test_slash_change_emergency_flag_is_stored(db):
    from agenticops.cli import main as cli
    from agenticops.models import ChangeRequest
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch("agenticops.services.change_service.start_review", return_value=None), \
         patch("agenticops.services.change_service.notify_change_requested"):
        cli._slash_change(None, ["restart", "web", "--emergency"])
    cr = db.query(ChangeRequest).one()
    assert cr.requested_change_type == "emergency" and cr.description == "restart web"


@pytest.mark.parametrize("args", [["tag", "x", "--account"], ["tag", "--account", "--emergency"]])
def test_slash_change_account_needs_a_name(db, args):
    """`--account` at the end, or followed by a flag, is a usage error — never a silently dropped account and
    never an account named `--emergency`."""
    from agenticops.cli import main as cli
    from agenticops.models import ChangeRequest
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch("agenticops.services.change_service.start_review") as sr, \
         patch("agenticops.services.change_service.notify_change_requested"):
        out = cli._slash_change(None, args)
    assert "--account needs an account name" in out
    assert db.query(ChangeRequest).count() == 0
    sr.assert_not_called()


def test_slash_change_unknown_account_error_is_shown_literally(db):
    """The service echoes the typed account name; a `[/x]` in it must not raise out of the REPL's print."""
    from agenticops.cli import main as cli
    from agenticops.models import ChangeRequest
    with patch("agenticops.cli.main.init_db"), patch("agenticops.services.change_service.start_review") as sr:
        out = cli._slash_change(None, ["x", "--account", "[/x]"])
    assert out.startswith("[red]")
    assert "account '[/x]' not found" in _as_the_repl_prints_it(out)
    assert db.query(ChangeRequest).count() == 0
    sr.assert_not_called()


def test_slash_change_names_why_the_review_did_not_start(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch.object(cs, "start_review", side_effect=cs.ChangeStateError("[/x] busy")), \
         patch.object(cs, "notify_change_requested"):
        out = cli._slash_change(None, ["tag", "i-0abc12345678"])
    assert "did not complete (review not started: [/x] busy)" in _as_the_repl_prints_it(out)
    assert "✓" not in out


def test_slash_change_never_ticks_a_review_that_has_not_finished(db):
    """Only a recorded verdict earns the ✓: a CR still under_review (another reviewer took it over, or it has
    not finished) gets the yellow head."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch.object(cs, "start_review", side_effect=_review_stores("under_review")), \
         patch.object(cs, "notify_change_requested"):
        out = cli._slash_change(None, ["tag", "i-0abc12345678"])
    assert "has not finished here" in out and "✓" not in out


def test_slash_change_offers_approval_only_for_a_planned_change(db):
    """The approve hint appears only for `planned` and names the requester≠approver rule; the Web link is absolute."""
    from agenticops.cli import main as cli
    from agenticops.config import settings
    from agenticops.models import ChangeRequest
    from agenticops.services import change_service as cs
    outs = {}
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch.object(settings, "web_base_url", "https://ops.example.com/"), patch.object(cs, "notify_change_requested"):
        for status, risk in (("planned", "L1"), ("needs_clarification", None)):
            with patch.object(cs, "start_review", side_effect=_review_stores(status, risk)):
                outs[status] = cli._slash_change(None, ["tag", "i-0abc12345678"])
    planned_id, clarify_id = [cr.id for cr in db.query(ChangeRequest).order_by(ChangeRequest.id)]
    assert f"/approve C{planned_id}" in outs["planned"] and "someone other than the requester" in outs["planned"]
    assert f"https://ops.example.com/app/changes/{planned_id}" in outs["planned"]
    assert "/approve" not in outs["needs_clarification"]
    assert f"https://ops.example.com/app/changes/{clarify_id}" in outs["needs_clarification"]


def test_slash_change_prints_the_review_itself_and_returns_only_the_status(db):
    """The SRE's Markdown is rendered on the console; the returned text holds no Markdown trigger, so the REPL
    prints it as Rich markup — never as Markdown, which would show `[green]` raw."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    buf = StringIO()
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(buf, 1000)), \
         patch.object(cs, "start_review", side_effect=_review_stores("planned", "L1", "## Review\n```bash\necho hi\n```")), \
         patch.object(cs, "notify_change_requested"):
        out = cli._slash_change(None, ["tag", "i-0abc12345678"])
    assert "```" not in out and not out.startswith("#")
    assert "echo hi" in buf.getvalue() and "```" not in buf.getvalue()  # rendered as Markdown, not printed raw
    seen = _as_the_repl_prints_it(out)
    assert "✓ Change request" in seen and "[green]" not in seen


# ── /approve C<id>: shown and confirmed, refused before any prompt (Minor 5) ──


def test_slash_approve_change_refuses_a_change_that_is_not_planned_before_any_prompt(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch.object(cs, "get_change", return_value=_cr("approved")), patch.object(cs, "approve") as ap, \
         patch("rich.prompt.Prompt.ask", return_value="ok") as pa, patch("rich.prompt.Confirm.ask", return_value=True) as ca:
        out = cli._slash_approve(None, ["C4"])
    assert "only a planned change" in out
    for reached in (pa, ca, ap):
        reached.assert_not_called()


def test_slash_approve_change_shows_it_and_asks_before_approving(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    buf = StringIO()
    change = _cr("planned", title="[prod] rotate keys", risk_level="L2", effective_change_type="standard")
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(buf, 1000)), \
         patch.object(cs, "get_change", return_value=change), patch.object(cs, "approve") as ap, \
         patch("rich.prompt.Confirm.ask", return_value=False):
        out = cli._slash_approve(None, ["C4", "reviewed"])
    assert "Approval cancelled" in out
    ap.assert_not_called()
    shown = buf.getvalue()
    assert "Title: [prod] rotate keys" in shown and "Risk: L2" in shown and "Type: standard" in shown


# ── /execute C<id>: refused before the prompt; errors shown literally (Minors 4, 5, 13) ──


def test_slash_execute_change_not_found_is_red_and_never_prompts(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch.object(cs, "get_change", side_effect=cs.ChangeNotFound("ChangeRequest #4 not found")), \
         patch("rich.prompt.Confirm.ask") as ca:
        out = cli._slash_execute(None, ["C4"])
    assert out == "[red]ChangeRequest #4 not found[/red]"
    ca.assert_not_called()


def test_slash_execute_change_refuses_a_change_that_is_not_approved_before_the_prompt(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch.object(cs, "get_change", return_value=_cr("planned")), patch.object(cs, "request_execution") as ex, \
         patch("rich.prompt.Confirm.ask", return_value=True) as ca:
        out = cli._slash_execute(None, ["C4"])
    assert "only an approved change" in out
    ca.assert_not_called()
    ex.assert_not_called()


def test_slash_execute_change_error_is_shown_literally(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch.object(cs, "get_change", return_value=_cr("approved")), \
         patch.object(cs, "request_execution", side_effect=cs.ChangeStateError("[/x] boom")), \
         patch("rich.prompt.Confirm.ask", return_value=True):
        out = cli._slash_execute(None, ["C4"])
    assert "[/x] boom" in _as_the_repl_prints_it(out)


@pytest.mark.parametrize("command,args,failing", [
    ("_slash_reject", ["C4", "no"], "reject"),
    ("_slash_approve", ["C4", "ok"], "get_change"),
    ("_slash_approve", ["C4", "ok"], "approve"),
])
def test_change_command_errors_are_shown_literally(db, command, args, failing):
    """Every service error the change commands print is escaped: a `[/x]` in it must not raise out of the REPL."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(StringIO(), 1000)), \
         patch.object(cs, "get_change", return_value=_cr("planned")), patch("rich.prompt.Confirm.ask", return_value=True), \
         patch.object(cs, failing, side_effect=cs.ChangeStateError("[/x] refused")):
        out = getattr(cli, command)(None, args)
    assert out.startswith("[red]") and "[/x] refused" in _as_the_repl_prints_it(out)


# ── Control characters in free text (Minor 9) ──────────────────────────


def test_control_characters_in_a_title_never_reach_the_terminal(db):
    """escape() handles markup only: an ESC sequence in a title (web/IM intake) could conceal text on the
    terminal — here in /changes and in the summary a human confirms an execution against."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    title = "\x1b[8mhidden\x1b[0m visible"
    with patch("agenticops.cli.main.init_db"), patch.object(cs, "list_changes", return_value=[_row(title=title)]):
        out = cli._slash_changes(None, [])
    assert "\x1b" not in out and "hidden" in out
    buf = StringIO()
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(buf, 1000)), \
         patch.object(cs, "get_change", return_value=_cr("approved", title=title)), \
         patch.object(cs, "request_execution") as ex, patch("rich.prompt.Confirm.ask", return_value=False):
        cli._slash_execute(None, ["C4"])
    assert "\x1b" not in buf.getvalue() and "hidden" in buf.getvalue()
    ex.assert_not_called()


# ── Final wave: /fix list rendered like /changes, fix plans only (CLI-1) ──


def _plans(db):
    """One fix plan with bracketed free text and one change plan (whose issue column read `None`)."""
    from agenticops.models import ChangeRequest, FixPlan, HealthIssue, RCAResult
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    cr = ChangeRequest(title="Tag web", description="add Env=prod", requested_by="cli:m", status="planned", risk_level="L1")
    db.add(cr); db.flush()
    db.add_all([
        FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="[prod] web", summary="s",
                status="approved", approved_by="user:[ops]"),
        FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="tag the web hosts", summary="s",
                status="pending_approval"),
    ])
    db.commit()


def test_slash_fix_list_returns_text_the_repl_can_print(db):
    """As /changes: no ANSI in the returned table — the REPL's highlighter splits every "\\x1b[" it is given."""
    from agenticops.cli import main as cli
    _plans(db)
    with patch("agenticops.cli.main.init_db"):
        out = cli._slash_fix(None, ["list"])
    assert "\x1b" not in out
    repl = StringIO()
    Console(file=repl, highlight=True, force_terminal=True, tab_size=2, width=200, color_system="truecolor").print(out)
    assert "\x1b\x1b[" not in repl.getvalue()


def test_slash_fix_list_shows_free_text_literally(db):
    """A title and an approver are free text: `[prod]` / `[ops]` show instead of vanishing as Rich tags."""
    from agenticops.cli import main as cli
    _plans(db)
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", Console(file=StringIO(), width=200)):
        seen = _as_the_repl_prints_it(cli._slash_fix(None, ["list"]))
    assert "[prod] web" in seen and "user:[ops]" in seen


def test_fix_list_usage_shows_the_issue_id_argument():
    """`[issue_id]` is escaped, so Rich prints it instead of eating it as a tag (as `[reason...]`, Minor 12)."""
    from agenticops.cli import main as cli
    for text in (cli._slash_fix(None, []), cli._slash_fix(None, ["bogus"]), cli._slash_help(None, [])):
        assert "/fix list [issue_id] [--status S] [--risk L]" in _as_the_repl_prints_it(text)


def test_slash_fix_list_lists_fix_plans_only(db):
    """A change plan has no issue; /changes lists it, /fix list does not."""
    from agenticops.cli import main as cli
    _plans(db)
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", Console(file=StringIO(), width=200)):
        seen = _as_the_repl_prints_it(cli._slash_fix(None, ["list"]))
    assert "tag the web hosts" not in seen and "[prod] web" in seen


# ── Final wave: /changes at 80 columns (CLI-C1) ──


def test_slash_changes_at_80_columns_folds_instead_of_cutting(db):
    """At a common terminal width a long cell folds inside its border instead of ending in "…"; the id stays
    whole and the Updated cell reads YYYY-MM-DD HH:MM. At 80 columns that cell folds too (whole at 120, above)."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    row = _row(id=12345, title="Add Env=prod tag to the web and db hosts", status="needs_clarification",
               requested_by="cli:malibo", updated_at="2026-09-18T01:02:03+00:00")
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", Console(file=StringIO(), width=80)), \
         patch.object(cs, "list_changes", return_value=[row]):
        out = cli._slash_changes(None, [])
    lines = out.splitlines()
    assert "…" not in out and "C#12345" in out
    assert max(len(line) for line in lines) <= 80
    first = next(i for i, line in enumerate(lines) if "C#12345" in line)
    updated = "".join(line.split("│")[-2].strip() for line in lines[first:] if line.startswith("│"))
    assert updated.replace(" ", "") == "2026-09-1801:02", updated  # no "T", no seconds, no offset


# ── Final wave: confirm summaries stay one line per field (CLI-B) ──


def test_confirm_summaries_keep_the_title_on_one_line(db):
    """A newline in a title cannot add a field line: the human confirms against exactly one `Status:`."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    title = "web\nStatus: approved"
    for command, status in (("_slash_approve", "planned"), ("_slash_execute", "approved")):
        buf = StringIO()
        with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", _plain_console(buf, 1000)), \
             patch.object(cs, "get_change", return_value=_cr(status, title=title)), \
             patch.object(cs, "approve") as ap, patch.object(cs, "request_execution") as ex, \
             patch("rich.prompt.Confirm.ask", return_value=False):
            getattr(cli, command)(None, ["C4", "reviewed"])
        lines = buf.getvalue().splitlines()
        assert "  Title: web Status: approved" in lines, command
        assert [line.strip() for line in lines if line.strip().startswith("Status:")] == [f"Status: {status}"], command
        assert not ap.called and not ex.called


# ── Final wave: a code fence in free text cannot turn a reply into Markdown (CLI-FENCE) ──


def test_a_fence_in_a_title_never_reaches_the_reply(db):
    """print_with_truncation renders a whole reply as Markdown when it holds a fence — the reply's Rich tags would
    then print raw. _safe_text breaks every run of 3+ backticks; single and double ones are left alone."""
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch.object(cli, "console", Console(file=StringIO(), width=200)), \
         patch.object(cs, "list_changes", return_value=[_row(title="run ```rm -rf /tmp/x``` now")]):
        out = cli._slash_changes(None, [])
    assert "```" not in out and "rm -rf /tmp/x" in out
    assert cli._safe_text("a `b` ``c``") == "a `b` ``c``"
    assert "```" not in cli._safe_text("````") and cli._safe_text("````").replace("\u200b", "") == "````"
