"""What a diagnosis and a fix-plan run hold, tool by tool (MVP-2.9.0 N30).

«These two agents only read» is a claim about EVERY tool they can call, not only the three that take a command
line. This file builds both agents as the product builds them — the real strands.Agent with its plugins, a scripted
model — reads their registries, and holds every tool to one of five answers. A tool added to either agent fails
here until someone says which answer is its.
"""
from unittest.mock import MagicMock, patch

import pytest

from agenticops.config import settings
from agenticops.models import get_session
from tests.test_run_guard import Scripted
from tests.test_viewer_role import _temp_db

# 1. Reads only: the platform's own records, the cloud through describe / query calls, the relation graph, the
#    knowledge base, memory, a skill's reference text, a tool result set aside by the context offloader.
READS = {
    "get_active_account", "get_managed_resources", "get_health_issue", "get_rca_result",
    "lookup_cloudtrail_events", "get_metrics", "query_logs", "query_provider_metrics", "query_provider_logs",
    "search_sops", "search_similar_cases", "search_agent_memory", "read_skill_reference", "retrieve_offloaded_content",
    "describe_ec2", "describe_rds", "list_lambda_functions",
    "describe_vpcs", "describe_subnets", "describe_security_groups", "describe_route_tables", "describe_nat_gateways",
    "describe_transit_gateways", "describe_load_balancers", "describe_region_topology", "analyze_vpc_topology",
    "describe_eks_clusters", "describe_eks_nodegroups", "check_eks_pod_ip_capacity", "map_eks_to_vpc_topology",
    "query_reachability", "query_impact_radius", "find_network_path", "detect_network_anomalies",
    "analyze_dependency_chain", "detect_single_points_of_failure", "analyze_capacity_risk", "simulate_edge_removal",
    "get_topology_evidence",
}
# 2. Writes the run's own result into the platform's database — what the run is for. Nothing outside it.
OWN_RECORDS = {"save_rca_result", "update_health_issue_status", "save_fix_plan"}
# 3. Resolves and caches an account's credentials for the reads that follow; changes no resource.
CREDENTIALS = {"assume_role"}
# 4. Sends a command line. Each passes the ONE check point (services/command_audit.change_context_refusal), which
#    in such a run refuses what the code does not know to be a read — tests/test_read_only_runs.py, and for a host
#    line tests/test_host_reads_only.py. The tool bound to the issue's account, which takes run_aws_cli_readonly's
#    place once the account is resolved, passes it too.
COMMANDS = {"run_on_host", "run_kubectl", "run_aws_cli_readonly"}
# 5. Loads a skill's text. In such a run it registers only the read tools on an allow-list
#    (skills/tools.READ_ONLY_SKILL_TOOLS); it stamps the skill's last use in a file on this host.
SKILLS = {"activate_skill"}

GROUPS = (READS, OWN_RECORDS, CREDENTIALS, COMMANDS, SKILLS)
KNOWN = set().union(*GROUPS)


@pytest.fixture
def db(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch, "tools.db")
    monkeypatch.setattr(settings, "acp_enhanced_enabled", True)          # as the committed settings have it
    monkeypatch.setattr(settings, "rca_topology_context_enabled", True)
    monkeypatch.setattr(settings, "strands_context_manager_auto", True)
    s = get_session()
    yield s
    s.close()


def _diagnosis_registry() -> set:
    """rca_agent() builds its Agent inline: let it, with a scripted model, and read the registry it runs with."""
    seen = {}

    def invoke(agent, prompt, **kw):
        seen["names"] = set(agent.tool_registry.registry)
        return "done"

    ra = "agenticops.agents.rca_agent"
    with patch(f"{ra}.BedrockModel", return_value=Scripted([])), patch(f"{ra}.build_system_prompt", return_value="p"), \
            patch("agenticops.config.get_agent_model_config", return_value=("scripted", 16384)), \
            patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
            patch(f"{ra}.resolve_rca_effort", return_value=(0, None)), \
            patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke), \
            patch("agenticops.services.agent_log_service.track_agent"), \
            patch("agenticops.services.rca_quality.run_post_rca_pipeline"):
        from agenticops.agents.rca_agent import rca_agent
        assert rca_agent(issue_id=7) == "done"
    return seen["names"]


def _fix_plan_registry(cli_tool=None) -> set:
    """sre_agent()'s own build, as it asks for it."""
    from agenticops.agents import sre_agent as mod
    seen = {}

    def invoke(agent, prompt, **kw):
        seen["names"] = set(agent.tool_registry.registry)
        return "done"

    with patch.object(mod, "BedrockModel", return_value=Scripted([])), \
            patch.object(mod, "build_system_prompt", return_value="p"), \
            patch.object(mod, "rejection_feedback", return_value=""), \
            patch.object(mod, "get_cli_tool_for_issue", return_value=cli_tool), \
            patch("agenticops.config.get_agent_model_config", return_value=("scripted", 16384)), \
            patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
            patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke), \
            patch("agenticops.services.agent_log_service.track_agent"), \
            patch("agenticops.services.pipeline_events.plan_written_since", return_value=True):
        assert mod.sre_agent(issue_id=7) == "done"
    return seen["names"]


def test_a_tool_has_one_answer():
    assert sum(len(group) for group in GROUPS) == len(KNOWN)


def test_every_tool_of_a_diagnosis_is_accounted_for(db):
    names = _diagnosis_registry()
    assert names - KNOWN == set(), "a tool nobody has said «only reads» about"
    assert {"save_rca_result", "run_on_host", "run_kubectl", "run_aws_cli_readonly", "activate_skill",
            "get_topology_evidence", "retrieve_offloaded_content"} <= names        # … and it is the real registry
    assert len(names) == 38


def test_every_tool_of_a_fix_plan_run_is_accounted_for(db):
    names = _fix_plan_registry()
    assert names - KNOWN == set(), "a tool nobody has said «only reads» about"
    assert {"save_fix_plan", "run_on_host", "run_kubectl", "run_aws_cli_readonly", "activate_skill",
            "retrieve_offloaded_content"} <= names
    assert "enhanced_task" not in names                 # the delegated backend runs outside every command check
    assert len(names) == 39


def test_no_tool_is_listed_that_neither_agent_holds(db):
    assert KNOWN == _diagnosis_registry() | _fix_plan_registry()


def test_neither_agent_can_change_its_own_memory_or_write_a_skill(db):
    # the tools that write files on this host belong to Main; a diagnosis or a plan run holds none of them
    held = _diagnosis_registry() | _fix_plan_registry()
    assert not held & {"memory_manage", "skill_manage", "create_skill", "improve_skill", "promote_skill",
                       "write_local_file", "send_to_channel", "distribute_report", "run_aws_cli", "run_skill_script"}


def test_the_account_bound_tool_takes_the_fallbacks_place(db):
    from strands import tool

    @tool
    def run_aws_cli_dev(command: str) -> str:
        """The cloud CLI bound to one account."""
        return ""

    names = _fix_plan_registry(cli_tool=run_aws_cli_dev)
    # issue #7 is not in this database, so no account is resolved: the fallback stays …
    assert "run_aws_cli_readonly" in names
    from agenticops.agents import sre_agent as mod
    with patch.object(mod, "BedrockModel", return_value=Scripted([])), \
            patch.object(mod, "build_system_prompt", return_value="p"), \
            patch("agenticops.config.get_agent_model_config", return_value=("scripted", 16384)), \
            patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()):
        bound = set(mod._create_sre_agent(cli_tool=run_aws_cli_dev, fix_plan=True).tool_registry.registry)
    # … and with one resolved, the bound tool is there instead of it
    assert "run_aws_cli_dev" in bound and "run_aws_cli_readonly" not in bound
    assert bound - {"run_aws_cli_dev"} == names - {"run_aws_cli_readonly"}


def test_the_fallback_cloud_cli_refuses_what_is_not_a_read_by_itself():
    from agenticops.tools.aws_cli_tool import run_aws_cli_readonly
    with patch("agenticops.tools.aws_cli_tool._execute_aws_cli") as ex:
        for command in ("aws ec2 stop-instances --instance-ids i-1", "aws iam generate-credential-report"):
            assert run_aws_cli_readonly(command=command).startswith("Error")
    assert not ex.called


# ── the two prompts say what the code does ───────────────────────────────────

def test_the_prompts_no_longer_tell_the_model_to_confirm_for_itself():
    from agenticops.agents.rca_agent import RCA_SYSTEM_PROMPT
    from agenticops.agents.sre_agent import SRE_BASE_PROMPT, SRE_SYSTEM_PROMPT
    for prompt in (RCA_SYSTEM_PROMPT, SRE_BASE_PROMPT, SRE_SYSTEM_PROMPT):
        assert "require confirmation" not in prompt
        assert "present them to the user" not in prompt
        assert "Read-only commands execute automatically" not in prompt
        assert "__READ_ONLY_RUN_RULE__" not in prompt


def test_each_prompt_says_the_run_only_reads_and_where_a_change_belongs():
    from agenticops.agents.preamble import READ_ONLY_RUN_RULE
    from agenticops.agents.rca_agent import RCA_SYSTEM_PROMPT
    from agenticops.agents.sre_agent import SRE_BASE_PROMPT, SRE_SYSTEM_PROMPT
    assert "refuses any command it does not know to be read-only" in READ_ONLY_RUN_RULE
    assert "confirmed or not" in READ_ONLY_RUN_RULE              # … the model's own «confirmation» changes nothing
    assert RCA_SYSTEM_PROMPT.count(READ_ONLY_RUN_RULE) == 1
    assert "A diagnosis only reads: " + READ_ONLY_RUN_RULE in RCA_SYSTEM_PROMPT
    assert "a change goes into your recommendations, never\n        into a tool call" in RCA_SYSTEM_PROMPT
    assert "Host lines: plain reads joined by | ; && ||" in RCA_SYSTEM_PROMPT   # where host commands matter most
    for prompt in (SRE_BASE_PROMPT, SRE_SYSTEM_PROMPT):
        assert prompt.count(READ_ONLY_RUN_RULE) == 1
        assert "A fix-plan run only reads: " + READ_ONLY_RUN_RULE + " — a change is a plan step, never a tool call." in prompt


def test_the_new_sentences_name_no_cloud():
    from agenticops.agents.rca_agent import RCA_SYSTEM_PROMPT
    from agenticops.agents.sre_agent import SRE_BASE_PROMPT
    for prompt, first, last in ((RCA_SYSTEM_PROMPT, "     d. A diagnosis only reads", "awk, sed or find."),
                                (SRE_BASE_PROMPT, "     d. A fix-plan run only reads", "never a tool call.")):
        start = prompt.index(first)
        passage = prompt[start:prompt.index(last, start) + len(last)].lower()
        for word in ("aws", "amazon", "ec2", "ssm", "eks", "kubectl", "azure", "gcloud", "google", "aliyun"):
            assert word not in passage, (word, passage)
