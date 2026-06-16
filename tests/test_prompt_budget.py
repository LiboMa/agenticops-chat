"""Prompt budget golden tests — pin assembled prompt sizes and hygiene.

Catches silent prompt bloat (memory growth, skills XML growth, model-config
drift) and regressions of the S1/S3/S7 prompt fixes:
- S1: memory block must stay LAST in build_system_prompt (cache stability)
- S3: no CJK characters shipped to the model in any base prompt
- S7: sub-agent tool docstrings carry their routing keywords
"""

import re

import pytest

# Base prompt size goldens (chars), ±25% tolerance. Re-baseline deliberately
# when a prompt is intentionally changed — never widen the tolerance.
BASE_PROMPT_GOLDENS = {
    "main": 10_100,
    "sre": 9_700,
    "detect": 8_900,
    "rca": 8_000,
    "executor": 5_000,
    "reporter": 3_800,
    "scan": 2_000,
}

TOLERANCE = 0.25

_CJK_RE = re.compile(r"[一-鿿]")


def _base_prompts() -> dict[str, str]:
    from agenticops.agents.main_agent import MAIN_SYSTEM_PROMPT
    from agenticops.agents.sre_agent import SRE_SYSTEM_PROMPT
    from agenticops.agents.detect_agent import DETECT_SYSTEM_PROMPT
    from agenticops.agents.rca_agent import RCA_SYSTEM_PROMPT
    from agenticops.agents.executor_agent import EXECUTOR_SYSTEM_PROMPT
    from agenticops.agents.reporter_agent import REPORTER_SYSTEM_PROMPT
    from agenticops.agents.scan_agent import SCAN_SYSTEM_PROMPT

    return {
        "main": MAIN_SYSTEM_PROMPT,
        "sre": SRE_SYSTEM_PROMPT,
        "detect": DETECT_SYSTEM_PROMPT,
        "rca": RCA_SYSTEM_PROMPT,
        "executor": EXECUTOR_SYSTEM_PROMPT,
        "reporter": REPORTER_SYSTEM_PROMPT,
        "scan": SCAN_SYSTEM_PROMPT,
    }


class TestBasePromptSizes:
    @pytest.mark.parametrize("agent_name", list(BASE_PROMPT_GOLDENS))
    def test_size_within_golden_range(self, agent_name):
        prompts = _base_prompts()
        size = len(prompts[agent_name])
        golden = BASE_PROMPT_GOLDENS[agent_name]
        low, high = golden * (1 - TOLERANCE), golden * (1 + TOLERANCE)
        assert low <= size <= high, (
            f"{agent_name} base prompt is {size} chars, outside golden range "
            f"[{low:.0f}, {high:.0f}] (golden={golden}). If the change is "
            f"intentional, re-baseline BASE_PROMPT_GOLDENS."
        )


class TestPromptHygiene:
    def test_no_cjk_in_base_prompts(self):
        # S3 regression guard: TODO notes in Chinese were shipped to the
        # model as instructions; base prompts must stay English-only.
        for name, prompt in _base_prompts().items():
            match = _CJK_RE.search(prompt)
            assert match is None, (
                f"{name} base prompt contains CJK character {match.group()!r} "
                f"at offset {match.start()} — prompts must be English-only"
            )

    def test_no_unsubstituted_placeholders(self):
        for name, prompt in _base_prompts().items():
            assert "__SKILLS_BLOCK__" not in prompt, name
            assert "__LOCAL_FILE_BLOCK__" not in prompt, name

    def test_rca_sre_share_skill_activation_fragment(self):
        prompts = _base_prompts()
        assert "ACTIVATE DOMAIN SKILLS" in prompts["rca"]
        assert "ACTIVATE DOMAIN SKILLS" in prompts["sre"]
        # Agent-specific extra routes preserved
        assert "distributed-tracing" in prompts["rca"]
        assert "security-engineer" in prompts["sre"]
        # Shared block present in both
        assert "LOCAL FILE INSPECTION" in prompts["rca"]
        assert "LOCAL FILE INSPECTION" in prompts["sre"]


class TestSkillsXmlBudget:
    def test_skills_xml_under_budget(self):
        from agenticops.skills.loader import get_available_skills_xml

        xml = get_available_skills_xml()
        assert len(xml) < 5_000, (
            f"skills XML is {len(xml)} chars (> 5,000 budget) — injected into "
            f"every agent prompt; trim descriptions or skill count"
        )


class TestAssembledPromptBudget:
    @pytest.mark.parametrize("agent_name", list(BASE_PROMPT_GOLDENS))
    def test_assembled_under_budget(self, agent_name):
        from agenticops.agents.preamble import build_system_prompt

        base = _base_prompts()[agent_name]
        # agent_name="" skips memory (variable per machine); skills included.
        assembled = build_system_prompt(
            base, include_account=False, include_skills=True, agent_name=""
        )
        assert len(assembled) < 20_000, (
            f"{agent_name} assembled prompt (no memory) is {len(assembled)} "
            f"chars (> 20,000 budget)"
        )


class TestStabilityOrdering:
    def test_memory_block_is_last(self):
        # S1 regression guard: memory is the most volatile block and must sit
        # at the END of the assembled prompt so its churn doesn't invalidate
        # the Bedrock prompt-cache prefix (skills XML, output rules).
        from unittest.mock import patch

        from agenticops.agents.preamble import build_system_prompt

        fake_memory = "<agent_memory>FAKE_MEMORY_BLOCK</agent_memory>"
        with patch(
            "agenticops.memory.agent_memory.load_agent_memory",
            return_value=fake_memory,
        ):
            assembled = build_system_prompt(
                "BASE_PROMPT_TEXT",
                include_account=False,
                include_skills=True,
                agent_name="detect",
            )

        mem_pos = assembled.find("FAKE_MEMORY_BLOCK")
        assert mem_pos != -1, "memory block missing from assembled prompt"
        # Everything else (base, skills XML, output rules) must come before it
        assert assembled.find("BASE_PROMPT_TEXT") < mem_pos
        skills_pos = assembled.find("<available_skills>")
        if skills_pos != -1:
            assert skills_pos < mem_pos, "skills XML must precede memory block"
        rules_pos = assembled.find("OUTPUT FORMAT RULES")
        assert rules_pos != -1 and rules_pos < mem_pos, (
            "output rules must precede memory block"
        )


class TestRoutingDocstrings:
    # S7 regression guard: tool docstrings are the routing contract sent to
    # the model — each must keep its core routing keywords.
    CASES = {
        "scan_agent": ("agenticops.agents.scan_agent", ["scan", "discover", "inventory"]),
        "detect_agent": ("agenticops.agents.detect_agent", ["health", "security", "status"]),
        "rca_agent": ("agenticops.agents.rca_agent", ["RCA", "root cause", "investigate"]),
        "sre_agent": ("agenticops.agents.sre_agent", ["fix", "remediate", "READ-ONLY"]),
        "sre_query": ("agenticops.agents.sre_agent", ["CATCH-ALL", "kubectl"]),
        "executor_agent": ("agenticops.agents.executor_agent", ["execute", "approved"]),
        "reporter_agent": ("agenticops.agents.reporter_agent", ["report", "summary"]),
    }

    @pytest.mark.parametrize("tool_name", list(CASES))
    def test_docstring_routing_keywords(self, tool_name):
        import importlib

        module_path, keywords = self.CASES[tool_name]
        module = importlib.import_module(module_path)
        tool_fn = getattr(module, tool_name)
        # Strands @tool wraps the function; docstring survives on the wrapper
        # or the original — check both.
        doc = (getattr(tool_fn, "__doc__", "") or "")
        if not doc and hasattr(tool_fn, "original_function"):
            doc = tool_fn.original_function.__doc__ or ""
        if not doc and hasattr(tool_fn, "tool_spec"):
            doc = str(tool_fn.tool_spec.get("description", ""))
        assert doc, f"{tool_name} has no accessible docstring/description"
        doc_lower = doc.lower()
        for kw in keywords:
            assert kw.lower() in doc_lower, (
                f"{tool_name} docstring lost routing keyword {kw!r}"
            )
