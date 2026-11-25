"""MVP-2.9.0 N21 (the 2.8.0 spec's S4): what a reporter run read is recorded by the code while its tools run — the
accounts and regions they ranged over, and whether any result was cut, offloaded or failed. The model never passes
it; a report saved outside a reporter run has none."""
import contextvars
import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from strands import Agent, tool
from strands.models.model import Model

from agenticops.models import Base, CloudAccount, CloudResource, HealthIssue, Report, get_session
from agenticops.run_context import get_run_context, run_context
from agenticops.services import report_coverage as rc


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.storage.backend as storage
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/cov.db")
    monkeypatch.setattr(settings, "reports_dir", tmp_path / "reports")
    monkeypatch.setattr(settings, "report_s3_bucket", "")
    monkeypatch.setattr(storage, "_backend", None)
    monkeypatch.setattr("agenticops.services.content_rendering.enqueue_other_language", lambda report_id: None)
    (tmp_path / "reports").mkdir()
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=1, name="prod", provider="aws", is_enabled=True, regions=["us-east-1", "eu-west-1"]),
               CloudAccount(id=2, name="lab", provider="aws", is_enabled=True, regions=["ap-southeast-1"]),
               CloudAccount(id=3, name="retired", provider="aws", is_enabled=False, regions=["us-west-2"])])
    s.commit()
    yield s
    s.close()
    monkeypatch.setattr(models_mod, "_engine", None)


def _resource(s, n, account=1, region="us-east-1", rtype="EC2"):
    s.add(CloudResource(account_id=account, provider="aws", region=region, resource_type=rtype,
                        resource_id=f"i-{n:04d}", name=f"n{n}", tags={}, raw_data={}, managed=True))


def _issue(s, n, **kw):
    s.add(HealthIssue(resource_id=f"i-{n:04d}", severity="high", source="t", title=f"t{n}", description="",
                      status="open", issue_type="other", **kw))


NOW = datetime(2026, 11, 19, 9, 3, 0, tzinfo=timezone.utc)


# ── the record ────────────────────────────────────────────────────────────────────────────────────────────────

def test_nothing_is_recorded_outside_a_reporter_run():
    assert rc.current() is None
    rc.note_scope(["a"], ["us-east-1"])       # none of these may raise: every tool calls them
    rc.note_truncated(); rc.note_offloaded(); rc.note_failed()
    assert rc.current() is None


def test_a_run_records_what_its_tools_ranged_over():
    with run_context(coverage=rc.begin(NOW)):
        rc.note_scope(["prod", "lab"], ["us-east-1"])
        rc.note_scope(["prod"], ["eu-west-1", ""])
        rc.note_scope([None, ""], None)
        got = rc.current().as_dict()
    assert got == {"accounts": ["lab", "prod"], "regions": ["eu-west-1", "us-east-1"], "completeness": "complete",
                   "partial": {"truncated": 0, "offloaded": 0, "failed": 0}, "read_at": "2026-11-19T09:03:00Z"}
    assert rc.current() is None                # the record ends with the run


@pytest.mark.parametrize("note, key", [(rc.note_truncated, "truncated"), (rc.note_offloaded, "offloaded"), (rc.note_failed, "failed")])
def test_one_result_that_was_cut_offloaded_or_failed_makes_the_run_partial(note, key):
    with run_context(coverage=rc.begin(NOW)):
        note(); note()
        got = rc.current().as_dict()
    assert got["completeness"] == "partial" and got["partial"][key] == 2
    assert sum(got["partial"].values()) == 2


def test_a_note_made_in_a_tools_thread_reaches_the_run():
    """Strands runs a sync tool in another thread under a COPY of the context: the copy holds the same record."""
    with run_context(coverage=rc.begin(NOW)):
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: ctx.run(lambda: (rc.note_scope(["lab"], ["ap-southeast-1"]), rc.note_truncated())))
        t.start(); t.join()
        got = rc.current().as_dict()
    assert got["accounts"] == ["lab"] and got["partial"]["truncated"] == 1


# ── the tools write into it ───────────────────────────────────────────────────────────────────────────────────

def test_a_long_result_that_is_cut_is_counted(db):
    from agenticops.tools.metadata_tools import _truncate
    with run_context(coverage=rc.begin(NOW)):
        assert _truncate("x" * 10, 100) == "x" * 10
        assert rc.current().as_dict()["partial"]["truncated"] == 0
        assert _truncate("x" * 101, 100).startswith("x" * 100 + "\n... (output truncated")
        assert rc.current().as_dict()["partial"]["truncated"] == 1


def test_the_inventory_tool_says_which_accounts_and_regions_it_ranged_over(db):
    from agenticops.tools.metadata_tools import get_managed_resources
    _resource(db, 1); _resource(db, 2, region="eu-west-1"); _resource(db, 3, account=2, region="ap-southeast-1")
    _resource(db, 4, account=3, region="us-west-2")                    # a disabled account is not read
    db.commit()
    with run_context(coverage=rc.begin(NOW)):
        rows = json.loads(get_managed_resources())
        got = rc.current().as_dict()
    assert len(rows) == 3
    assert got["accounts"] == ["lab", "prod"]
    assert got["regions"] == ["ap-southeast-1", "eu-west-1", "us-east-1"]
    assert got["completeness"] == "complete"


def test_a_region_filter_is_the_region_it_ranged_over(db):
    from agenticops.tools.metadata_tools import get_managed_resources
    _resource(db, 1); _resource(db, 2, region="eu-west-1")
    db.commit()
    with run_context(coverage=rc.begin(NOW)):
        get_managed_resources(region="eu-west-1")
        assert rc.current().as_dict()["regions"] == ["eu-west-1"]
    with run_context(coverage=rc.begin(NOW)):
        get_managed_resources(resource_type="RDS")                     # nothing matches: no region was read
        got = rc.current().as_dict()
        assert (got["accounts"], got["regions"]) == (["lab", "prod"], [])


def test_the_inventory_tools_cap_is_a_cut(db, monkeypatch):
    """It hands over at most 50 rows and never says there were more: a report built on it is partial."""
    from agenticops.tools import metadata_tools
    from agenticops.tools.metadata_tools import get_managed_resources
    monkeypatch.setattr(metadata_tools, "MAX_LIST_RESULT_CHARS", 10**6)   # the length limit is the test above
    for n in range(50):
        _resource(db, n)
    db.commit()
    with run_context(coverage=rc.begin(NOW)):
        assert len(json.loads(get_managed_resources())) == 50
        assert rc.current().as_dict()["completeness"] == "complete"    # exactly 50: nothing was left out
    _resource(db, 50)
    db.commit()
    with run_context(coverage=rc.begin(NOW)):
        assert len(json.loads(get_managed_resources())) == 50          # what the model gets is unchanged
        assert rc.current().as_dict()["partial"]["truncated"] == 1


def test_the_issue_list_says_its_accounts_and_when_it_was_cut(db):
    from agenticops.tools.metadata_tools import list_health_issues
    for n in range(3):
        _issue(db, n)
    db.commit()
    with run_context(coverage=rc.begin(NOW)):
        assert len(json.loads(list_health_issues(limit=3))) == 3
        got = rc.current().as_dict()
        assert (got["accounts"], got["regions"], got["completeness"]) == (["lab", "prod"], [], "complete")
    with run_context(coverage=rc.begin(NOW)):
        assert len(json.loads(list_health_issues(limit=2))) == 2
        assert rc.current().as_dict()["partial"]["truncated"] == 1


def test_a_cloud_call_names_the_account_and_region_it_resolved(db, monkeypatch):
    """Every account-addressed tool reaches its credentials through resolve_account_session — the one place."""
    from agenticops.credentials import resolver
    monkeypatch.setattr(resolver, "get_cached_session", lambda key: object())     # as if resolved before
    with run_context(coverage=rc.begin(NOW)):
        resolver.resolve_account_session("lab", "ap-southeast-1")
        resolver.resolve_account_session("prod")
        got = rc.current().as_dict()
    assert (got["accounts"], got["regions"]) == (["lab", "prod"], ["ap-southeast-1"])


def test_a_refused_account_is_not_coverage(db, monkeypatch):
    from agenticops.credentials import resolver
    with run_context(coverage=rc.begin(NOW), bound_account_id=1):
        with pytest.raises(resolver.AccountResolutionError):
            resolver.resolve_account_session("lab", "ap-southeast-1")
        assert rc.current().as_dict()["accounts"] == []


# ── the reporter's hook: results that failed or were offloaded ────────────────────────────────────────────────

def _ended(text, status="success", exception=None):
    return SimpleNamespace(result={"status": status, "content": [{"text": text}]}, exception=exception,
                           tool_use={"name": "t", "toolUseId": "1"})


@pytest.mark.parametrize("event, want", [
    (_ended("[]"), {"truncated": 0, "offloaded": 0, "failed": 0}),
    (_ended("No resources found."), {"truncated": 0, "offloaded": 0, "failed": 0}),
    (_ended("boom", status="error"), {"truncated": 0, "offloaded": 0, "failed": 1}),
    (_ended("Error: no such issue"), {"truncated": 0, "offloaded": 0, "failed": 1}),
    (_ended('{"error": "No enabled accounts found."}'), {"truncated": 0, "offloaded": 0, "failed": 1}),
    (_ended("ok", exception=RuntimeError("x")), {"truncated": 0, "offloaded": 0, "failed": 1}),
    (_ended("[Offloaded: 1 blocks, ~2,000 tokens]\nTool result was offloaded…"), {"truncated": 0, "offloaded": 1, "failed": 0}),
])
def test_the_hook_counts_a_failed_and_an_offloaded_result(event, want):
    from agenticops.agents.reporter_agent import CoverageRecorder
    record = rc.begin(NOW)
    CoverageRecorder(record)._ended(event)
    assert record.as_dict()["partial"] == want


class Scripted(Model):
    """Answers each model call with the next entry of `script`: a final text, or a list of (tool, input) calls."""

    def __init__(self, script):
        self.config = {"model_id": "scripted"}
        self.script, self.calls = list(script), 0

    def update_config(self, **kw):
        self.config.update(kw)

    def get_config(self):
        return self.config

    async def structured_output(self, *a, **k):  # pragma: no cover
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        step = self.script.pop(0) if self.script else "done"
        calls = [] if isinstance(step, str) else step
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(step, str):
            yield {"contentBlockDelta": {"delta": {"text": step}}}
            yield {"contentBlockStop": {}}
        for n, (name, args) in enumerate(calls):
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{self.calls}-{n}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use" if calls else "end_turn"}}


def test_a_real_run_sees_the_offloaders_work(monkeypatch):
    """The whole wiring on a real strands.Agent: the recorder runs AFTER the offloader (which rewrites the result),
    so a result the offloader moved out of the context is counted — and one it left alone is not."""
    from agenticops.agents.reporter_agent import CoverageRecorder
    from agenticops.config import get_agent_context_plugins, settings
    monkeypatch.setattr(settings, "strands_context_manager_auto", True)

    @tool
    def big() -> str:
        """A long result."""
        return "row " * 20000

    @tool
    def small() -> str:
        """A short result."""
        return "three rows"

    record = rc.begin(NOW)
    agent = Agent(model=Scripted([[("big", {})], [("small", {})], "done"]), tools=[big, small], callback_handler=None,
                  plugins=get_agent_context_plugins("reporter"), hooks=[CoverageRecorder(record)])
    agent("go")
    assert record.as_dict()["partial"] == {"truncated": 0, "offloaded": 1, "failed": 0}


# ── the reporter begins the record; save_report stores it ─────────────────────────────────────────────────────

def test_the_reporter_run_carries_a_record_and_ends_it(monkeypatch):
    import importlib
    ra = importlib.import_module("agenticops.agents.reporter_agent")     # (the package exports the tool by that name)
    seen = {}

    class FakeAgent:
        def __init__(self, **kw):
            seen["hooks"] = kw.get("hooks")

    def fake_invoke(agent, prompt, **kw):
        seen["record"] = get_run_context().coverage
        return "saved"
    monkeypatch.setattr(ra, "Agent", FakeAgent)
    monkeypatch.setattr(ra, "BedrockModel", lambda **kw: SimpleNamespace(config=kw))   # takes the factory's aiops_ref
    monkeypatch.setattr("agenticops.agents.preamble.invoke_with_retry", fake_invoke)
    before = datetime.now(timezone.utc)
    assert ra.reporter_agent(report_type="daily") == "saved"
    assert isinstance(seen["record"], rc.Coverage) and before <= seen["record"].read_at <= datetime.now(timezone.utc)
    assert any(isinstance(h, ra.CoverageRecorder) and h.coverage is seen["record"] for h in seen["hooks"])
    assert get_run_context().coverage is None


def test_save_report_stores_the_runs_coverage(db):
    from agenticops.tools.report_tools import save_report
    with run_context(coverage=rc.begin(NOW)):
        rc.note_scope(["prod"], ["us-east-1"]); rc.note_truncated()
        out = save_report(report_type="daily", title="t", summary="s", content_markdown="# d\n\nbody")
    assert "Report #" in out
    db.expire_all()
    report = db.query(Report).one()
    assert report.coverage == {"accounts": ["prod"], "regions": ["us-east-1"], "completeness": "partial",
                               "partial": {"truncated": 1, "offloaded": 0, "failed": 0}, "read_at": "2026-11-19T09:03:00Z"}


def test_a_report_saved_outside_a_reporter_run_has_no_coverage_whatever_the_model_passes(db):
    from agenticops.tools.report_tools import save_report
    save_report(report_type="daily", title="t", summary="s", content_markdown="body",
                report_metadata=json.dumps({"coverage": {"accounts": ["everything"], "completeness": "complete"}}))
    db.expire_all()
    assert db.query(Report).one().coverage is None


def test_the_tool_takes_no_coverage_argument():
    from agenticops.tools.report_tools import save_report
    props = save_report.tool_spec["inputSchema"]["json"]["properties"]
    assert set(props) == {"report_type", "title", "summary", "content_markdown", "report_metadata"}


def test_an_older_database_gets_the_column_and_its_reports_have_no_coverage(tmp_path):
    import sqlalchemy as sa

    import agenticops.models as models
    eng = sa.create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE reports (id INTEGER PRIMARY KEY, report_type VARCHAR(50), title VARCHAR(200), "
                          "summary TEXT, content_markdown TEXT, content_html TEXT, file_path VARCHAR(500), "
                          "report_metadata JSON, created_at DATETIME)"))
        c.execute(sa.text("INSERT INTO reports (report_type, title, summary, content_markdown, report_metadata, created_at) "
                          "VALUES ('daily', 'old', 's', 'body', '{}', '2026-09-01 00:00:00')"))
    models._run_migrate_2_7_0(eng)
    assert "coverage" in {col["name"] for col in sa.inspect(eng).get_columns("reports")}
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT coverage FROM reports")).one() == (None,)
    assert models._statements_2_7_0(sa.inspect(eng), eng.dialect) == []
