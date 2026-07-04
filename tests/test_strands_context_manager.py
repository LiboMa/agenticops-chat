"""Strands SDK 自动上下文治理开关 + helper 测试。"""
from agenticops.config import settings, get_agent_context_manager


def test_default_flag_enabled():
    # 默认开启 auto 上下文治理
    assert settings.strands_context_manager_auto is True


def test_helper_returns_auto_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "strands_context_manager_auto", True)
    assert get_agent_context_manager("main") == "auto"
    assert get_agent_context_manager("executor") == "auto"


def test_helper_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "strands_context_manager_auto", False)
    assert get_agent_context_manager("main") is None


def test_all_agents_resolve_context_manager(monkeypatch):
    """开关开时，7 个 agent 名都解析到 "auto"（构造点注入的兜底断言）。"""
    monkeypatch.setattr(settings, "strands_context_manager_auto", True)
    for name in ("main", "scan", "detect", "rca", "sre", "executor", "reporter"):
        assert get_agent_context_manager(name) == "auto"
