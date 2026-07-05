"""Executor HITL 安全网开关 + helper 测试。

只断言 helper 的可观测契约（关态返回 []、开态返回 1 个 HumanInTheLoop），
不断言 SDK 内部私有属性（如 _allowed_tools），以免 SDK 升级导致脆断。
"""
import importlib

import pytest

from agenticops.config import settings, get_executor_interventions

_has_hitl = importlib.util.find_spec("strands.vended_interventions") is not None


def test_default_hitl_disabled():
    # 默认关闭：先安全上线
    assert settings.executor_hitl_enabled is False


def test_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "executor_hitl_enabled", False)
    assert get_executor_interventions() == []


@pytest.mark.skipif(not _has_hitl, reason="strands.vended_interventions not available in current SDK")
def test_returns_hitl_when_enabled(monkeypatch):
    from strands.vended_interventions.hitl import HumanInTheLoop

    monkeypatch.setattr(settings, "executor_hitl_enabled", True)
    result = get_executor_interventions()
    assert len(result) == 1
    assert isinstance(result[0], HumanInTheLoop)
