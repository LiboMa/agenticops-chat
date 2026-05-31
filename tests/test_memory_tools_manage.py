"""Tests for the memory_manage agent tool."""
import json
from unittest.mock import patch
import pytest


@pytest.fixture
def tmp_memory_dir(tmp_path):
    mem_dir = tmp_path / "agent-memory"
    for agent in ("detect", "rca", "sre", "executor", "reporter", "scan", "shared"):
        (mem_dir / agent).mkdir(parents=True)
    with patch("agenticops.memory.agent_memory.AGENT_MEMORY_DIR", mem_dir):
        yield mem_dir


def test_memory_manage_add_sets_agent_provenance(tmp_memory_dir):
    from agenticops.tools.memory_tools import memory_manage
    from agenticops.memory.agent_memory import parse_frontmatter, _agent_dir
    res = json.loads(memory_manage(action="add", agent_name="detect",
                                   description="EKS pods need NAT for ECR pulls"))
    assert res["status"] == "saved"
    files = [p for p in _agent_dir("detect").glob("*.md") if p.name != "MEMORY.md"]
    fm, _ = parse_frontmatter(files[0].read_text())
    assert fm["created_by"] == "agent"
    assert fm["source"] == "agent"


def test_memory_manage_add_when_full_returns_merge_prompt(tmp_memory_dir):
    from agenticops.tools.memory_tools import memory_manage
    from agenticops.memory.agent_memory import save_memory_file
    for i in range(15):
        save_memory_file(agent_name="detect", filename=f"m{i}.md", body=f"b{i}")
    res = json.loads(memory_manage(action="add", agent_name="detect", description="new one"))
    assert res["status"] == "memory_full"
    assert "current" in res and len(res["current"]) == 15
    assert "merge" in res["message"].lower()


def test_memory_manage_merge(tmp_memory_dir):
    from agenticops.tools.memory_tools import memory_manage
    from agenticops.memory.agent_memory import save_memory_file
    save_memory_file(agent_name="detect", filename="a.md", body="A")
    save_memory_file(agent_name="detect", filename="b.md", body="B")
    res = json.loads(memory_manage(action="merge", agent_name="detect",
                                   sources=["a.md", "b.md"], into="umb.md",
                                   description="merged A+B"))
    assert res["status"] == "merged"


def test_memory_manage_invalid_agent_errors(tmp_memory_dir):
    from agenticops.tools.memory_tools import memory_manage
    import json
    res = json.loads(memory_manage(action="add", agent_name="bogus", description="x"))
    assert "error" in res


def test_memory_manage_gate_blocks_writes_when_disabled(tmp_memory_dir, monkeypatch):
    from agenticops.tools.memory_tools import memory_manage
    import json
    monkeypatch.setattr("agenticops.config.settings.memory_autonomous_write", False, raising=False)
    res = json.loads(memory_manage(action="add", agent_name="detect", description="blocked"))
    assert "error" in res and "disabled" in res["error"].lower()
    # search is NOT gated — should still work
    res2 = json.loads(memory_manage(action="search", agent_name="detect", description="anything"))
    assert "matches" in res2
