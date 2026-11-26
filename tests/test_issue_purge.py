"""`aiops delete issues --all` — every issue and what hangs off it, nothing else (2026-11-23, the issue reset).

The owner asked to clear every issue on three databases and scan again. What makes this more than `DELETE FROM
health_issues`: SQLite REUSES ids — once the table is empty the next issue is I#1 again, so any row left behind that is
keyed by an old issue number (a diagnosis, a fix plan, a run, a timeline event, a signal, a step, a «later», a chat
bound to it, an ITSM link, a case record) would quietly belong to a new issue. And old signals left behind would make
the first re-detected ones noise (three of one fingerprint inside 30 minutes).

Kept on purpose: change requests and everything of theirs, the two audit trails, the inventory, reports, accounts.
"""
import datetime as dt
import sqlite3
from pathlib import Path

import pytest

from agenticops.models import (
    AgentStep, AlertEvent, AttentionSnooze, CaseStudyRecord, ChangeRequest, ChatSession, CloudResource, CommandAudit,
    FixExecution, FixPlan, HealthIssue, ITSMLink, PipelineEvent, RCAResult, Report, SecurityPollCursor, SOPRecord,
    get_session,
)
from agenticops.services import issue_purge
from tests.test_viewer_role import _temp_db

NOW = dt.datetime(2026, 11, 23, 8, 0, 0)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A database with two issues and one change request, each with everything that can hang off it."""
    settings = _temp_db(tmp_path, monkeypatch, "purge.db")
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    kb = tmp_path / "data" / "knowledge_base"
    for sub in ("cases", "sops"):
        (kb / sub).mkdir(parents=True)
    monkeypatch.setattr(settings, "knowledge_base_dir", kb)
    monkeypatch.setattr(settings, "cases_dir", kb / "cases")
    monkeypatch.setattr(settings, "sops_dir", kb / "sops")
    (kb / "cases" / "case_20261101_1.md").write_text("# case of I#1\n")
    (kb / "sops" / "restart-nginx.md").write_text("# SOP\n")
    memory = tmp_path / "agent-memory"
    for agent in ("detect", "rca"):
        (memory / agent).mkdir(parents=True)
    (memory / "detect" / "auto_cpu_spike.md").write_text("---\nagent: detect\nstatus: active\n---\nCPU spikes on x are noise\n")
    (memory / "rca" / "rca_feedback_issue_1.md").write_text("---\nagent: rca\nstatus: active\nrelated_issue_id: 1\n---\nwrong\n")
    (memory / "rca" / "general_rule.md").write_text("---\nagent: rca\nstatus: active\n---\nAlways read CloudTrail first\n")
    (memory / "rca" / "MEMORY.md").write_text("# Rca Agent Memory\n\n- [Rca Feedback Issue 1](rca_feedback_issue_1.md)\n- [General Rule](general_rule.md)\n")

    s = get_session()
    issues = [HealthIssue(resource_id=f"i-{n}", severity="high", source="security_posture", title=f"t{n}",
                          description="d", status="fix_planned") for n in (1, 2)]
    s.add_all(issues); s.flush()
    rca = RCAResult(health_issue_id=issues[0].id, root_cause="x")
    s.add(rca); s.flush()
    fix = FixPlan(health_issue_id=issues[0].id, rca_result_id=rca.id, plan_kind="fix", risk_level="L1", title="p", summary="s")
    cr = ChangeRequest(title="c", description="d", requested_by="user:alice", status="completed")
    s.add_all([fix, cr]); s.flush()
    change_plan = FixPlan(change_request_id=cr.id, plan_kind="change", risk_level="L1", title="cp", summary="s")
    s.add(change_plan); s.flush()
    fix_run = FixExecution(fix_plan_id=fix.id, health_issue_id=issues[0].id, status="succeeded")
    change_run = FixExecution(fix_plan_id=change_plan.id, status="succeeded")
    s.add_all([fix_run, change_run]); s.flush()
    s.add_all([
        PipelineEvent(health_issue_id=issues[0].id, event_type="status_changed", stage="rca", status="ok"),
        PipelineEvent(health_issue_id=issues[1].id, event_type="note_added", stage="note", status="ok"),
        PipelineEvent(change_request_id=cr.id, event_type="change_created", stage="change", status="ok"),
        AlertEvent(source="security_posture", external_id="f-1", severity="high", title="a", health_issue_id=issues[0].id),
        AlertEvent(source="webhook", external_id="n-1", severity="low", title="noise"),
        AgentStep(run_key="r1", agent="rca", item=f"I{issues[0].id}", kind="tool"),
        AgentStep(run_key="r2", agent="executor", item=f"C{cr.id}", kind="tool", execution_id=change_run.id),
        AttentionSnooze(user_id=1, item=f"I{issues[1].id}", situation="s", until=NOW),
        AttentionSnooze(user_id=1, item=f"C{cr.id}", situation="s", until=NOW),
        ITSMLink(entity_type="health_issue", entity_id=issues[0].id, system="jira", record_type="incident", external_id="J-1"),
        ITSMLink(entity_type="fix_plan", entity_id=fix.id, system="jira", record_type="change", external_id="J-2"),
        ITSMLink(entity_type="fix_plan", entity_id=change_plan.id, system="jira", record_type="change", external_id="J-3"),
        ChatSession(session_id="s-issue", name="about I1", context_entity_type="health_issue", context_entity_id=issues[0].id,
                    context_account_id=7),
        ChatSession(session_id="s-change", name="about C1", context_entity_type="change_request", context_entity_id=cr.id),
        CaseStudyRecord(case_id="case_20261101_1", source_issue_id=issues[0].id),
        SOPRecord(filename="from-issue.md", source_issue_id=issues[0].id),
        SOPRecord(filename="hand-written.md"),
        SecurityPollCursor(account_id="acct", source="guardduty", region="eu-west-1"),
        CommandAudit(tool="run_aws_cli", tier="write", command="aws ec2 create-tags", outcome="executed", fix_plan_id=fix.id),
        CloudResource(account_id=7, provider="aws", region="eu-west-1", resource_type="EC2", resource_id="i-1"),
        Report(report_type="daily", title="r", summary="s", content_markdown="I#1 was fixed"),
    ])
    ids = {"cr": cr.id, "change_plan": change_plan.id, "change_run": change_run.id}
    s.commit()
    s.close()
    return {"settings": settings, "kb": kb, "memory": memory, "tmp": tmp_path, "ids": ids}


def _count(model, **by):
    s = get_session()
    try:
        return s.query(model).filter_by(**by).count()
    finally:
        s.close()


def test_a_dry_run_counts_and_changes_nothing(world):
    report = issue_purge.purge(dry_run=True)
    counts = dict(report.planned)
    assert counts["health_issues"] == 2 and counts["rca_results"] == 1 and counts["fix_plans (fix)"] == 1
    assert counts["fix_executions (of fix plans)"] == 1 and counts["alert_events"] == 2
    assert report.backup is None and report.deleted == []
    assert _count(HealthIssue) == 2 and _count(AlertEvent) == 2


def test_everything_that_hangs_off_an_issue_is_gone_and_the_change_side_is_whole(world):
    report = issue_purge.purge(yes=True)
    assert dict(report.deleted) == dict(report.planned)           # what the dry run said is what was done
    for model in (HealthIssue, RCAResult, AlertEvent, CaseStudyRecord):
        assert _count(model) == 0, model
    assert _count(FixPlan, plan_kind="fix") == 0 and _count(FixExecution, health_issue_id=None) == 1
    assert _count(PipelineEvent) == 1 and _count(PipelineEvent, change_request_id=world["ids"]["cr"]) == 1
    assert _count(AgentStep) == 1 and _count(AgentStep, item=f"C{world['ids']['cr']}") == 1
    assert _count(AttentionSnooze) == 1 and _count(ITSMLink) == 1
    assert _count(ITSMLink, entity_type="fix_plan", entity_id=world["ids"]["change_plan"]) == 1
    assert _count(SOPRecord) == 1 and _count(SOPRecord, filename="hand-written.md") == 1
    # kept: the change, its plan and run, the two audit trails, inventory, reports, poll cursors (not asked)
    assert _count(ChangeRequest) == 1 and _count(FixPlan, plan_kind="change") == 1
    assert _count(CommandAudit) == 1 and _count(CloudResource) == 1 and _count(Report) == 1
    assert _count(SecurityPollCursor) == 1
    # a chat bound to an issue stays, unbound from it — its account binding stays (a chat is never widened);
    # one bound to a change is untouched
    s = get_session()
    try:
        bound = {c.session_id: (c.context_entity_type, c.context_entity_id, c.context_account_id) for c in s.query(ChatSession)}
    finally:
        s.close()
    assert bound["s-issue"] == (None, None, 7)
    assert bound["s-change"] == ("change_request", world["ids"]["cr"], None)


def test_the_next_issue_is_number_one_and_nothing_old_hangs_on_it(world):
    issue_purge.purge(yes=True)
    s = get_session()
    try:
        new = HealthIssue(resource_id="i-9", severity="low", source="security_posture", title="new", description="d")
        s.add(new); s.commit()
        assert new.id == 1                                        # SQLite gave the old number again …
        assert s.query(RCAResult).filter_by(health_issue_id=1).count() == 0
        assert s.query(PipelineEvent).filter_by(health_issue_id=1).count() == 0
        assert s.query(AlertEvent).filter_by(health_issue_id=1).count() == 0
        assert s.query(AgentStep).filter_by(item="I1").count() == 0
        assert s.query(ITSMLink).filter_by(entity_type="health_issue", entity_id=1).count() == 0
        assert s.query(FixPlan).filter_by(health_issue_id=1).count() == 0
        assert s.query(ChatSession).filter_by(context_entity_type="health_issue", context_entity_id=1).count() == 0
    finally:
        s.close()


def test_a_backup_is_taken_first_and_holds_everything(world):
    report = issue_purge.purge(yes=True)
    assert report.backup and Path(report.backup).parent == Path(world["settings"].data_dir) / "backups"
    c = sqlite3.connect(report.backup)
    try:
        assert c.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert c.execute("select count(*) from health_issues").fetchone()[0] == 2
        assert c.execute("select count(*) from alert_events").fetchone()[0] == 2
    finally:
        c.close()


def test_the_poll_cursors_go_only_when_asked(world):
    issue_purge.purge(yes=True, reset_poll_cursors=True)
    assert _count(SecurityPollCursor) == 0


def test_without_yes_nothing_happens(world):
    with pytest.raises(issue_purge.PurgeRefused, match="--yes"):
        issue_purge.purge()
    assert _count(HealthIssue) == 2 and not (Path(world["settings"].data_dir) / "backups").exists()


def test_not_sqlite_is_refused(world, monkeypatch):
    monkeypatch.setattr(world["settings"], "database_url", "postgresql://u@h/db")
    with pytest.raises(issue_purge.PurgeRefused, match="SQLite"):
        issue_purge.purge(yes=True)


def test_while_another_process_runs_nothing_happens(world):
    import fcntl
    lock = Path(world["settings"].data_dir) / ".scheduler.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)          # what a running AgenticOps process holds
        with pytest.raises(issue_purge.PurgeRefused, match="another AgenticOps process"):
            issue_purge.purge(yes=True)
    assert _count(HealthIssue) == 2


def test_a_failure_part_way_leaves_every_row_where_it_was(world, monkeypatch):
    real = issue_purge._delete_steps

    def failing(conn, steps):
        real(conn, steps)
        raise RuntimeError("disk full")

    monkeypatch.setattr(issue_purge, "_delete_steps", failing)
    with pytest.raises(RuntimeError, match="disk full"):
        issue_purge.purge(yes=True)
    assert _count(HealthIssue) == 2 and _count(RCAResult) == 1 and _count(AlertEvent) == 2


def test_learned_knowledge_is_moved_aside_not_deleted(world):
    report = issue_purge.purge(yes=True, move_knowledge=True, memory_dirs=[world["memory"]])
    dest = Path(report.knowledge_moved_to)
    assert (dest / "knowledge_base" / "cases" / "case_20261101_1.md").read_text() == "# case of I#1\n"
    assert (dest / "knowledge_base" / "sops" / "restart-nginx.md").exists()
    assert not list((world["kb"] / "cases").iterdir()) and not list((world["kb"] / "sops").iterdir())
    moved = sorted(str(p.relative_to(dest)) for p in dest.rglob("*.md") if "agent-memory" in p.parts)
    assert moved == ["agent-memory/detect/auto_cpu_spike.md", "agent-memory/rca/rca_feedback_issue_1.md"]
    assert (world["memory"] / "rca" / "general_rule.md").exists()            # a memory not from an issue stays
    index = (world["memory"] / "rca" / "MEMORY.md").read_text()
    assert "general_rule.md" in index and "rca_feedback_issue_1" not in index


def _vectors(world, *rows):
    """A case_vectors table (init_db makes it with raw SQL; the test database is created from the models) + rows."""
    from sqlalchemy import text
    from agenticops.models import get_engine
    with get_engine().begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS case_vectors (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT "
                          "NOT NULL, field_name TEXT NOT NULL, vector BLOB NOT NULL, resource_type TEXT DEFAULT '', "
                          "metadata_json TEXT DEFAULT '{}', UNIQUE(case_id, field_name))"))
        for case_id, field in rows:
            conn.execute(text("insert into case_vectors (case_id, field_name, vector) values (:c, :f, x'00')"),
                         {"c": case_id, "f": field})


def _vector_ids():
    from sqlalchemy import text
    from agenticops.models import get_engine
    with get_engine().connect() as conn:
        return sorted(r[0] for r in conn.execute(text("select case_id from case_vectors")))


def test_without_move_knowledge_only_what_came_from_an_issue_moves_aside(world):
    """The owner, 2026-11-26 (review ④): a case or SOP written from an issue names that issue's number, and the
    reset gives the number to a new issue — so it leaves the knowledge base with its record: its vectors go, its file
    moves into the backup's knowledge folder. Knowledge from elsewhere and the agent memories stay."""
    (world["kb"] / "sops" / "from-issue.md").write_text("# SOP from I#1\n")
    (world["kb"] / "cases" / "case_sample.md").write_text("# a sample case\n")
    _vectors(world, ("case_20261101_1", "root_cause"), ("from-issue", "root_cause"), ("case_sample", "root_cause"),
             ("restart-nginx", "root_cause"))
    planned = dict(issue_purge.purge(dry_run=True).planned)
    assert planned["case_vectors (from issues)"] == 2 and planned["knowledge files from issues"] == 2
    report = issue_purge.purge(yes=True)
    assert _vector_ids() == ["case_sample", "restart-nginx"]
    dest = Path(report.knowledge_moved_to)
    assert (dest / "knowledge_base" / "cases" / "case_20261101_1.md").read_text() == "# case of I#1\n"
    assert (dest / "knowledge_base" / "sops" / "from-issue.md").exists()
    assert "case_20261101_1.md" in (dest / "MANIFEST.tsv").read_text()
    assert sorted(p.name for p in (world["kb"] / "cases").iterdir()) == ["case_sample.md"]
    assert sorted(p.name for p in (world["kb"] / "sops").iterdir()) == ["restart-nginx.md"]
    assert (world["memory"] / "detect" / "auto_cpu_spike.md").exists()       # memories move only when asked
    assert _count(SOPRecord, filename="hand-written.md") == 1


def test_a_record_pointing_outside_the_knowledge_base_moves_no_file(world, tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text("not ours\n")
    s = get_session()
    s.add(CaseStudyRecord(case_id="case_odd", source_issue_id=1, file_path=str(outside)))
    s.commit(); s.close()
    issue_purge.purge(yes=True)
    assert outside.exists()


def test_a_refused_or_counted_purge_migrates_nothing(world, monkeypatch):
    """Review ⑤: the CLI ran init_db (the startup migrations — writes) before the refusals; now only a real run does,
    after its checks, the lock and the backup."""
    from typer.testing import CliRunner
    from agenticops.cli.main import app
    calls = []
    monkeypatch.setattr("agenticops.models.init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr("agenticops.cli.main.init_db", lambda: calls.append("cli init_db"))
    runner = CliRunner()
    assert runner.invoke(app, ["delete", "issues", "--all"]).exit_code == 1          # no --yes
    assert runner.invoke(app, ["delete", "issues", "--all", "--dry-run"]).exit_code == 0
    with pytest.raises(issue_purge.PurgeRefused):
        issue_purge.purge(yes=False)
    assert calls == []


def test_a_real_purge_migrates_after_the_backup(world, monkeypatch):
    order = []
    real_backup = issue_purge._backup
    monkeypatch.setattr("agenticops.models.init_db", lambda: order.append("init_db"))
    monkeypatch.setattr(issue_purge, "_backup", lambda *a: (order.append("backup"), real_backup(*a))[1])
    issue_purge.purge(yes=True)
    assert order == ["backup", "init_db"]


def test_the_cli_refuses_without_all_and_prints_the_counts(world, monkeypatch):
    from typer.testing import CliRunner
    from agenticops.cli.main import app
    runner = CliRunner()
    refused = runner.invoke(app, ["delete", "issues", "--yes"])
    assert refused.exit_code != 0 and _count(HealthIssue) == 2
    dry = runner.invoke(app, ["delete", "issues", "--all", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "health_issues" in dry.output and _count(HealthIssue) == 2
    done = runner.invoke(app, ["delete", "issues", "--all", "--yes"])
    assert done.exit_code == 0, done.output
    assert _count(HealthIssue) == 0 and "backup" in done.output.lower()
