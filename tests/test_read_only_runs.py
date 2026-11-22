"""A diagnosis and a fix-plan run only read — in code (MVP-2.9.0 N30).

Until N30 that was the prompts' word. The account-bound cloud CLI tool these two agents hold ran every command it
could not call a read, with a ledger row and no question; the host and kubectl tools asked «confirm?» once, and the
model answered itself by calling again with require_confirmation=True — nobody is there in a pipeline run. During
N26's measurement the plan agent sent an unclassifiable command to a real account that way.

rca_agent() and sre_agent() now call their model under RunContext.read_only_run, and the ONE check point every
command tool passes (services/command_audit.change_context_refusal) refuses what the code does not know to be
read-only: nothing is sent, and the ledger says `refused` / `read_only_run`.
"""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from strands import Agent

from agenticops.models import CommandAudit, get_session
from agenticops.run_context import RunContext, get_run_context, run_context
from agenticops.services.command_audit import change_context_refusal, guarded_run
from tests.test_run_guard import Scripted
from tests.test_viewer_role import _temp_db

KINDS = ["diagnosis", "plan"]
SAYS = "only reads"                      # the words every such refusal carries


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    settings = _temp_db(tmp_path, monkeypatch, "n30.db")
    monkeypatch.setattr(settings, "command_audit_enabled", True)
    monkeypatch.setattr(settings, "change_management_enabled", True)
    s = get_session()
    yield s
    s.close()


def _rows(db):
    db.expire_all()
    return [(r.tool, r.tier, r.outcome, r.reason) for r in db.query(CommandAudit).order_by(CommandAudit.id)]


# ── the flag ─────────────────────────────────────────────────────────────────

def test_no_run_is_read_only_unless_it_says_so():
    assert RunContext().read_only_run is None and get_run_context().read_only_run is None


# ── the check point ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("tier", ["write", "unknown"])
def test_the_check_point_refuses_what_is_not_known_to_be_a_read(ledger, kind, tier):
    with run_context(read_only_run=kind):
        out = change_context_refusal(tool="run_on_host", tier=tier, command="systemctl restart nginx",
                                     account="dev", region="eu-west-1", target="i-1")
    assert out and SAYS in out and "require_confirmation" in out and out.endswith("Command: systemctl restart nginx")
    assert f"'{tier}'" in out                                    # it says how the code read the command
    assert _rows(ledger) == [("run_on_host", tier, "refused", "read_only_run")]
    row = ledger.query(CommandAudit).one()
    assert (row.account, row.region, row.target, row.command) == ("dev", "eu-west-1", "i-1", "systemctl restart nginx")


@pytest.mark.parametrize("kind", KINDS)
def test_a_read_passes_the_check_point_and_leaves_no_row(ledger, kind):
    with run_context(read_only_run=kind):
        assert change_context_refusal(tool="run_on_host", tier="readonly", command="df -h") is None
    assert _rows(ledger) == []


def test_the_refusal_says_where_a_change_belongs(ledger):
    with run_context(read_only_run="diagnosis"):
        diagnosis = change_context_refusal(tool="run_kubectl", tier="write", command="delete pod x")
    with run_context(read_only_run="plan"):
        plan = change_context_refusal(tool="run_kubectl", tier="write", command="delete pod x")
    assert "diagnosis run" in diagnosis and "recommendation" in diagnosis and "step of the plan" not in diagnosis
    assert "fix-plan run" in plan and "step of the plan" in plan and "approved" in plan
    for text in (diagnosis, plan):
        assert "do not" in text.lower()                          # … send it again


def test_the_refusal_names_no_cloud_and_no_tool_of_its_own(ledger):
    # the sentence goes to a model that may be working on any provider (the house rule for agent prompts)
    for kind in KINDS:
        with run_context(read_only_run=kind):
            text = change_context_refusal(tool="provider_gcp_cli", tier="unknown", command="x").lower()
        for word in ("aws", "amazon", "kubectl", "azure", "gcloud", "google", "aliyun", "ssm", "ec2"):
            assert word not in text, word


def test_a_kind_the_code_does_not_know_still_refuses(ledger):
    with run_context(read_only_run="something-new"):
        out = change_context_refusal(tool="run_aws_cli", tier="write", command="aws ec2 stop-instances --instance-ids i-1")
    assert out and SAYS in out
    assert _rows(ledger) == [("run_aws_cli", "write", "refused", "read_only_run")]


def test_an_approved_plan_in_the_context_does_not_lift_it(ledger):
    # what lifts a change review's guard — its plan was approved — is no reason for a diagnosis to change anything
    with run_context(read_only_run="diagnosis", fix_plan_id=7, change_request_id=3), \
            patch("agenticops.services.command_audit.approved_plan_in_context", return_value=7):
        out = change_context_refusal(tool="run_on_host", tier="write", command="systemctl restart nginx")
    assert out and SAYS in out
    assert _rows(ledger) == [("run_on_host", "write", "refused", "read_only_run")]


def test_a_read_only_account_is_still_answered_as_one(ledger):
    # both flags at once: the account's answer comes first (it is also the one that hides Secrets)
    with run_context(read_only=True, read_only_run="plan"):
        out = change_context_refusal(tool="run_kubectl", tier="write", command="delete pod x")
    assert "This account is read-only" in out
    assert _rows(ledger) == [("run_kubectl", "write", "refused", "read_only_account")]


def test_a_change_review_is_answered_as_before(ledger):
    with run_context(change_request_id=3):
        out = change_context_refusal(tool="run_kubectl", tier="write", command="delete pod x")
    assert "no approved plan yet" in out
    assert _rows(ledger) == [("run_kubectl", "write", "refused", "change_not_approved")]


# ── the three tools every agent shares ───────────────────────────────────────

@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("command,tier", [("aws ec2 stop-instances --instance-ids i-1", "write"),
                                          ("aws iam generate-credential-report", "unknown")])
def test_the_shared_cloud_cli_refuses_confirmed_or_not(ledger, kind, command, tier):
    from agenticops.tools.aws_cli_tool import run_aws_cli
    with run_context(read_only_run=kind), patch("agenticops.tools.aws_cli_tool._execute_aws_cli") as ex:
        for confirmed in (False, True):
            assert SAYS in run_aws_cli(command=command, require_confirmation=confirmed)
    assert not ex.called
    assert _rows(ledger) == [("run_aws_cli", tier, "refused", "read_only_run")] * 2


@pytest.mark.parametrize("kind", KINDS)
def test_a_host_command_is_refused_confirmed_or_not(ledger, kind):
    from agenticops.skills.execution import run_on_host
    with run_context(read_only_run=kind), patch("agenticops.skills.execution._run_auto_ladder") as ladder, \
            patch("agenticops.skills.execution._run_ssh_for_host") as ssh, \
            patch("agenticops.skills.execution._execute_ssm") as ssm:
        for confirmed in (False, True):
            for method in ("auto", "ssh", "ssm"):
                out = run_on_host(host_id="i-0123456789abcdef0", command="kill -9 1234", method=method,
                                  require_confirmation=confirmed)
                assert SAYS in out
    assert not (ladder.called or ssh.called or ssm.called)
    assert set(_rows(ledger)) == {("run_on_host", "write", "refused", "read_only_run")} and len(_rows(ledger)) == 6


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("command,tier", [
    ("scale deployment/x --replicas=2", "write"), ("delete pod x", "write"), ("exec -it x -- sh", "write"),
    ("-n shop rollout restart deployment/web", "write"), ("--context prod get pods", "unknown"),
])
def test_kubectl_is_refused_confirmed_or_not(ledger, kind, command, tier):
    from agenticops.skills.execution import run_kubectl
    with run_context(read_only_run=kind), patch("agenticops.skills.execution._execute_kubectl") as ex:
        for confirmed in (False, True):
            assert SAYS in run_kubectl(cluster_name="c1", command=command, require_confirmation=confirmed)
    assert not ex.called
    assert [row[1:] for row in _rows(ledger)] == [(tier, "refused", "read_only_run")] * 2


@pytest.mark.parametrize("kind", KINDS)
def test_reads_still_run_and_leave_no_row(ledger, kind):
    from agenticops.skills.execution import run_kubectl, run_on_host
    from agenticops.tools.aws_cli_tool import run_aws_cli
    with run_context(read_only_run=kind), \
            patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="{}") as aws, \
            patch("agenticops.skills.execution._run_auto_ladder", return_value="up 5 days") as host, \
            patch("agenticops.skills.execution._execute_kubectl", return_value="NAME READY") as kube:
        assert run_aws_cli(command="aws ec2 describe-instances --region eu-west-1") == "{}"
        assert run_on_host(host_id="i-0123456789abcdef0", command="df -h") == "up 5 days"
        assert run_kubectl(cluster_name="c1", command="get pods -A") == "NAME READY"
        assert run_kubectl(cluster_name="c1", command="-n shop logs deploy/web --tail=50") == "NAME READY"
    assert aws.called and host.called and kube.call_count == 2
    assert _rows(ledger) == []


def test_it_is_not_the_read_only_accounts_flag(ledger):
    # the account's flag also hides Secrets and makes the actor a viewer; a diagnosis reads what it could read before
    from agenticops.skills.execution import run_kubectl
    with run_context(read_only_run="diagnosis"), \
            patch("agenticops.skills.execution._execute_kubectl", return_value="OK") as ex:
        assert get_run_context().read_only is False
        assert run_kubectl(cluster_name="c1", command="get secret db -o yaml") == "OK"
    assert ex.called and _rows(ledger) == []


def test_outside_such_a_run_nothing_changes(ledger):
    from agenticops.tools.aws_cli_tool import run_aws_cli
    command = "aws ec2 create-tags --resources i-1 --tags Key=a,Value=b"
    with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="ok") as ex:
        asked = run_aws_cli(command=command)
        assert "requires confirmation" in asked and SAYS not in asked and not ex.called
        assert run_aws_cli(command=command, require_confirmation=True) == "ok"
    assert _rows(ledger) == [("run_aws_cli", "write", "refused", "confirmation"), ("run_aws_cli", "write", "executed", None)]


# ── the tools bound to one account (what these two agents hold once the issue's account is resolved) ──────────

def _account(name, provider, **credentials):
    return SimpleNamespace(id=1, name=name, provider=provider, credentials=credentials, regions=["eu-west-1"], labels={})


def _aws(monkeypatch):
    from agenticops.providers.aws import AWSProvider
    provider = AWSProvider(_account("dev", "aws"))
    session = Mock()
    session.get_credentials.return_value.get_frozen_credentials.return_value = SimpleNamespace(
        access_key="AKIAIOSFODNN7EXAMPLE", secret_key="x", token=None)       # AWS's documented EXAMPLE key, never real
    provider._session = session
    return provider.cli_tool(), "agenticops.providers.aws.subprocess.run"


def _ssh(monkeypatch):
    from agenticops.providers.ssh import SSHProvider
    provider = SSHProvider(_account("idc-1", "ssh", host="10.0.0.5", username="ops"))
    provider._cfg = {"host": "10.0.0.5", "username": "ops"}
    return provider.cli_tool(), "agenticops.providers.ssh.subprocess.run"


def _kube(monkeypatch):
    from agenticops.providers.kubernetes import KubernetesProvider
    provider = KubernetesProvider(_account("c1", "kubernetes", context="prod"))
    provider._cfg = {"context": "prod", "kubeconfig_path": "/dev/null"}
    return provider.cli_tool(), "agenticops.providers.kubernetes.subprocess.run"


def _azure(monkeypatch):
    from agenticops.providers.azure import AzureProvider
    return AzureProvider(_account("az-1", "azure", subscription_id="s")).cli_tool(), "agenticops.providers.azure.subprocess.run"


def _gcp(monkeypatch):
    from agenticops.providers.gcp import GCPProvider
    return GCPProvider(_account("gcp-1", "gcp", project_id="p")).cli_tool(), "agenticops.providers.gcp.subprocess.run"


def _alicloud(monkeypatch):
    from agenticops.providers.alicloud import AlicloudProvider
    return AlicloudProvider(_account("ali-1", "alicloud")).cli_tool(), "agenticops.providers.alicloud.subprocess.run"


ACCOUNT_TOOLS = [
    # build,   ledger name,            not a read (tier),                                              a read
    (_aws, "provider_aws_cli", [("aws ec2 create-tags --resources i-1 --tags Key=a,Value=b", "write"),
                                ("aws iam generate-credential-report", "unknown")], "aws ec2 describe-instances"),
    (_ssh, "provider_ssh", [("systemctl reload nginx", "write")], "df -h"),
    (_kube, "provider_kubectl", [("scale deployment/x --replicas=2", "write"),
                                 ("--context prod get pods", "unknown")], "get pods -A"),
    (_azure, "provider_azure_cli", [("az vm deallocate --name x --resource-group g", "unknown")], "az vm list"),
    (_gcp, "provider_gcp_cli", [("gcloud compute instances delete x", "unknown")], "gcloud compute instances list"),
    (_alicloud, "provider_alicloud_cli", [("aliyun ecs StopInstance --InstanceId i-1", "unknown")], None),
]
IDS = [row[1] for row in ACCOUNT_TOOLS]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("build,name,refused,_read", ACCOUNT_TOOLS, ids=IDS)
def test_an_account_bound_tool_sends_nothing_that_is_not_a_read(ledger, monkeypatch, kind, build, name, refused, _read):
    tool, target = build(monkeypatch)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""))
    monkeypatch.setattr(target, run)
    with run_context(read_only_run=kind):
        for command, _tier in refused:
            assert SAYS in tool(command)
    assert not run.called
    assert [row[:1] + row[2:] for row in _rows(ledger)] == [(name, "refused", "read_only_run")] * len(refused)
    assert [row[1] for row in _rows(ledger)] == [tier for _command, tier in refused]


@pytest.mark.parametrize("build,name,_refused,read", [row for row in ACCOUNT_TOOLS if row[3]], ids=IDS[:-1])
def test_an_account_bound_tool_still_reads(ledger, monkeypatch, build, name, _refused, read):
    tool, target = build(monkeypatch)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""))
    monkeypatch.setattr(target, run)
    with run_context(read_only_run="diagnosis"):
        assert SAYS not in tool(read)
    assert run.called and _rows(ledger) == []


@pytest.mark.parametrize("build,name,refused,_read", ACCOUNT_TOOLS[:1], ids=IDS[:1])
def test_outside_such_a_run_the_account_bound_tool_is_as_it_was(ledger, monkeypatch, build, name, refused, _read):
    # the tool has no confirmation of its own: outside a read-only run a write is run and recorded (chat, executor)
    tool, target = build(monkeypatch)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""))
    monkeypatch.setattr(target, run)
    assert tool(refused[0][0]) == "{}"
    assert run.called and _rows(ledger) == [(name, "write", "executed", None)]


def test_known_gap_a_provider_whose_reads_the_code_cannot_tell_gets_nothing_through(ledger, monkeypatch):
    # every command of this provider's CLI is tier `unknown` today, a describe included: on such an account a
    # diagnosis or a plan run can send no command at all. Said in the release note; no such account is registered.
    tool, target = _alicloud(monkeypatch)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""))
    monkeypatch.setattr(target, run)
    with run_context(read_only_run="diagnosis"):
        assert SAYS in tool("aliyun ecs DescribeInstances")
    assert not run.called


def test_the_shared_run_wrapper_refuses_before_the_change_gate(ledger):
    run = Mock(return_value="ok")
    with run_context(read_only_run="plan"):
        out = guarded_run(tool="provider_aws_cli", tier="write", command="aws ec2 delete-vpc --vpc-id vpc-1",
                          run=run, outcome_of=lambda text: ("executed", 0))
    assert SAYS in out and not run.called
    assert _rows(ledger) == [("provider_aws_cli", "write", "refused", "read_only_run")]


# ── who sets the flag ────────────────────────────────────────────────────────

# The helpers below never make the database unreachable (other files patch get_db_session to raise): a module first
# imported under such a patch keeps the mock for the rest of the session. Each test that enters an agent function
# takes the `ledger` fixture's own empty database instead — issue #7 is not in it, which both functions handle.

@contextmanager
def _a_diagnosis(agent_class=None, invoke=None):
    """rca_agent() with its model and its post-run checks out of the way."""
    ra = "agenticops.agents.rca_agent"
    patches = [patch(f"{ra}.BedrockModel"),
               patch("agenticops.config.get_agent_model_config", return_value=("scripted", 16384)),
               patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()),
               patch(f"{ra}.resolve_rca_effort", return_value=(0, None)),
               patch("agenticops.services.agent_log_service.track_agent"),
               patch("agenticops.services.rca_quality.run_post_rca_pipeline")]
    if invoke is not None:
        patches.append(patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke))
    with patch(f"{ra}.Agent", **({"side_effect": agent_class} if agent_class else {})) as agent_cls:
        for p in patches:
            p.start()
        try:
            if agent_class is None:
                agent_cls.return_value.messages = []
            yield agent_cls
        finally:
            for p in reversed(patches):
                p.stop()


@contextmanager
def _a_plan_run(agent, invoke=None):
    """sre_agent() with the agent it would build replaced, and its bookkeeping out of the way."""
    from agenticops.agents import sre_agent as mod
    patches = [patch.object(mod, "_create_sre_agent", return_value=agent),
               patch.object(mod, "rejection_feedback", return_value=""),
               patch("agenticops.services.agent_log_service.track_agent"),
               patch("agenticops.services.pipeline_events.plan_written_since", return_value=True),
               patch("agenticops.services.pipeline_events.log_agent_failed")]
    if invoke is not None:
        patches.append(patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke))
    for p in patches:
        p.start()
    try:
        yield mod
    finally:
        for p in reversed(patches):
            p.stop()


def _seen_by(seen):
    def invoke(agent, prompt, **kw):
        ctx = get_run_context()
        seen["during"] = (ctx.read_only_run, ctx.read_only)
        return "done"
    return invoke


def test_a_diagnosis_calls_its_model_as_a_read_only_run_and_leaves_no_flag_behind(ledger):
    seen = {}
    with _a_diagnosis(invoke=_seen_by(seen)):
        from agenticops.agents.rca_agent import rca_agent
        assert rca_agent(issue_id=7) == "done"
    assert seen["during"] == ("diagnosis", False)
    assert get_run_context().read_only_run is None


def test_a_fix_plan_run_calls_its_model_as_a_read_only_run_and_leaves_no_flag_behind(ledger):
    seen = {}
    with _a_plan_run(MagicMock(), invoke=_seen_by(seen)) as mod:
        assert mod.sre_agent(issue_id=7) == "done"
    assert seen["during"] == ("plan", False)
    assert get_run_context().read_only_run is None


def test_a_run_that_fails_leaves_no_flag_behind_either(ledger):
    def boom(agent, prompt, **kw):
        raise RuntimeError("model unavailable")
    with _a_plan_run(MagicMock(), invoke=boom) as mod:
        assert mod.sre_agent(issue_id=7).startswith("SRE agent error")
    with _a_diagnosis(invoke=boom):
        from agenticops.agents.rca_agent import rca_agent
        assert rca_agent(issue_id=7).startswith("RCA agent error")
    assert get_run_context().read_only_run is None


def test_a_general_query_is_not_such_a_run(ledger):
    # sre_query is the chat's catch-all: its commands follow the chat's rules, as before
    from agenticops.agents import sre_agent as mod
    seen = {}
    with patch.object(mod, "_create_sre_agent", return_value=MagicMock()), \
            patch.object(mod, "get_all_cli_tools", return_value=[]), \
            patch("agenticops.agents.preamble.invoke_with_retry", side_effect=_seen_by(seen)), \
            patch("agenticops.services.agent_log_service.track_agent"):
        assert mod.sre_query(query="list the queues") == "done"
    assert seen["during"] == (None, False)


def test_a_change_review_keeps_its_own_guard_and_takes_no_flag(ledger):
    from agenticops.agents import sre_agent as mod
    seen = {}
    with patch.object(mod, "_create_sre_agent", return_value=MagicMock()), \
            patch("agenticops.agents.preamble.invoke_with_retry", side_effect=_seen_by(seen)), \
            patch("agenticops.services.agent_log_service.track_agent"), \
            patch("agenticops.services.change_service.get_change", return_value={"id": 5, "account_id": None}):
        assert mod.sre_agent_review_change(5) == "done"
    assert seen["during"] == (None, False)


# ── end to end: the real entry function, a real agent loop, the real tool ────────────────────────────────────

def _confirmed(tool_name, **args):
    """A model that calls a command tool with require_confirmation=True straight away — what the two agents'
    models did when a tool asked «confirm?» — and then says it is done."""
    return Scripted([[(tool_name, {**args, "require_confirmation": True})], "done"])


def test_what_the_plan_agents_model_confirms_for_itself_is_not_sent(ledger):
    from agenticops.skills.execution import run_on_host
    agent = Agent(model=_confirmed("run_on_host", host_id="i-0123456789abcdef0", command="systemctl restart nginx"),
                  tools=[run_on_host], callback_handler=None)
    with _a_plan_run(agent) as mod, patch("agenticops.skills.execution._run_auto_ladder") as ladder:
        assert "done" in mod.sre_agent(issue_id=7)
    assert not ladder.called
    assert _rows(ledger) == [("run_on_host", "write", "refused", "read_only_run")]
    [result] = [block["toolResult"] for message in agent.messages for block in message["content"] if "toolResult" in block]
    assert SAYS in result["content"][0]["text"] and "fix-plan run" in result["content"][0]["text"]


def test_what_the_diagnosis_agents_model_confirms_for_itself_is_not_sent(ledger):
    from agenticops.skills.execution import run_kubectl
    built = {}

    def build(**kwargs):                 # rca_agent() builds its Agent inline: a real one, with a scripted model
        built["agent"] = Agent(model=_confirmed("run_kubectl", cluster_name="c1", command="delete pod web-1"),
                               tools=[run_kubectl], callback_handler=None)
        return built["agent"]

    with _a_diagnosis(agent_class=build), patch("agenticops.skills.execution._execute_kubectl") as ex:
        from agenticops.agents.rca_agent import rca_agent
        assert "done" in rca_agent(issue_id=7)
    assert not ex.called
    assert _rows(ledger) == [("run_kubectl", "write", "refused", "read_only_run")]
    [result] = [block["toolResult"] for message in built["agent"].messages for block in message["content"]
                if "toolResult" in block]
    assert SAYS in result["content"][0]["text"] and "diagnosis run" in result["content"][0]["text"]


def test_the_same_model_outside_such_a_run_gets_its_command_through(ledger):
    # the control: without the flag the confirmed command runs — so the two tests above test the flag, not the mocks
    from agenticops.skills.execution import run_on_host
    agent = Agent(model=_confirmed("run_on_host", host_id="i-0123456789abcdef0", command="kill -9 1234"),
                  tools=[run_on_host], callback_handler=None)
    with patch("agenticops.skills.execution._run_auto_ladder", return_value="ok") as ladder:
        agent("go")
    assert ladder.called
    assert _rows(ledger) == [("run_on_host", "write", "executed", None)]


# ── the executor is never such a run ─────────────────────────────────────────

def test_the_executor_clears_the_flag_for_its_own_run(tmp_path, monkeypatch):
    # nothing calls executor_agent() from inside a diagnosis or a plan run today (a new thread starts with a fresh
    # context); if something ever does, the run that acts on an approved plan must not be told «you only read»
    from agenticops.config import settings
    from tests import test_run_measured_facts as facts
    _temp_db(tmp_path, monkeypatch, "n30-exec.db")
    monkeypatch.setattr(settings, "executor_enabled", True)
    db = get_session()
    try:
        plan_id = facts._approved_plan(db)
    finally:
        db.close()
    seen = {}
    with run_context(read_only_run="plan"), facts._executor_build(), \
            patch("agenticops.agents.preamble.invoke_with_retry", side_effect=_seen_by(seen)):
        from agenticops.agents.executor_agent import executor_agent
        assert executor_agent(fix_plan_id=plan_id) == "done"
        assert get_run_context().read_only_run == "plan"         # … and the caller's own flag is back afterwards
    assert seen["during"] == (None, False)
