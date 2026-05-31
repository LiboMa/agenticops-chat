"""Property-based tests for ChatSessionManager — _remove_stale() TTL cleanup.

Feature: chat-session-persistence, Property 5: TTL 过期清理

Uses hypothesis to generate random TTL values (1-120 minutes) and random
last_activity times.  Verifies that _remove_stale() removes agents whose
last_activity exceeds the TTL and keeps agents within the TTL window.

**Validates: Requirements 4.3**
"""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from agenticops.web.session_manager import ChatSessionManager


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# TTL in minutes: 1–120
_ttl_minutes_st = st.integers(min_value=1, max_value=120)

# Offset in minutes from "now" for last_activity.
# Positive = in the past, negative = in the future (still active).
# Range covers well beyond the max TTL so we always get a mix.
_activity_offset_minutes_st = st.integers(min_value=-10, max_value=240)

# Session id — short unique-ish strings
_session_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=4,
    max_size=12,
).filter(lambda s: s.strip())

# A single agent entry: (session_id, activity_offset_minutes)
_agent_entry_st = st.tuples(_session_id_st, _activity_offset_minutes_st)

# List of agent entries with unique session ids (1-20 agents)
_agents_list_st = (
    st.lists(_agent_entry_st, min_size=1, max_size=20)
    .map(lambda entries: {sid: offset for sid, offset in entries})  # deduplicate by sid
)


def _build_manager(ttl_minutes: int, agents_with_offsets: dict[str, int]) -> ChatSessionManager:
    """Create a ChatSessionManager pre-populated with fake agents.

    Args:
        ttl_minutes: TTL value in minutes.
        agents_with_offsets: Mapping of session_id → offset in minutes from
            "now".  Positive offset means the agent's last activity was that
            many minutes *ago* (in the past).
    """
    mgr = ChatSessionManager.__new__(ChatSessionManager)
    mgr._lock = threading.Lock()
    mgr._ttl = timedelta(minutes=ttl_minutes)
    mgr._session_locks = {}

    now = datetime.now(timezone.utc)
    mgr._agents = {}
    mgr._last_activity = {}
    for sid, offset in agents_with_offsets.items():
        mgr._agents[sid] = MagicMock(name=f"Agent-{sid}")
        mgr._last_activity[sid] = now - timedelta(minutes=offset)
        mgr._session_locks[sid] = threading.Lock()

    return mgr


# ---------------------------------------------------------------------------
# Property 5: TTL 过期清理
# ---------------------------------------------------------------------------

class TestTTLExpirationCleanup:
    """Property 5: TTL 过期清理

    For any Agent instance and any positive integer TTL value, when that
    instance's last activity time exceeds the TTL in minutes from the current
    time, _remove_stale() shall remove it from the _agents dict.

    Feature: chat-session-persistence, Property 5: TTL 过期清理
    **Validates: Requirements 4.3**
    """

    @given(ttl_minutes=_ttl_minutes_st, agents_offsets=_agents_list_st)
    @settings(max_examples=150)
    def test_stale_agents_are_removed(self, ttl_minutes, agents_offsets):
        """Agents whose last_activity exceeds the TTL are removed."""
        mgr = _build_manager(ttl_minutes, agents_offsets)

        # Determine which sessions should be stale *before* calling _remove_stale
        expected_stale = {
            sid for sid, offset in agents_offsets.items() if offset > ttl_minutes
        }

        mgr._remove_stale()

        for sid in expected_stale:
            assert sid not in mgr._agents, (
                f"Session {sid!r} (offset={agents_offsets[sid]}m, ttl={ttl_minutes}m) "
                f"should have been removed"
            )
            assert sid not in mgr._last_activity
            assert sid not in mgr._session_locks

    @given(ttl_minutes=_ttl_minutes_st, agents_offsets=_agents_list_st)
    @settings(max_examples=150)
    def test_active_agents_are_kept(self, ttl_minutes, agents_offsets):
        """Agents whose last_activity is within the TTL window are kept."""
        mgr = _build_manager(ttl_minutes, agents_offsets)

        # Agents that are strictly within the TTL should survive.
        # Note: offset < ttl_minutes means last_activity is less than TTL ago.
        expected_kept = {
            sid for sid, offset in agents_offsets.items() if offset < ttl_minutes
        }

        mgr._remove_stale()

        for sid in expected_kept:
            assert sid in mgr._agents, (
                f"Session {sid!r} (offset={agents_offsets[sid]}m, ttl={ttl_minutes}m) "
                f"should have been kept"
            )
            assert sid in mgr._last_activity

    @given(ttl_minutes=_ttl_minutes_st, agents_offsets=_agents_list_st)
    @settings(max_examples=150)
    def test_total_count_is_consistent(self, ttl_minutes, agents_offsets):
        """After cleanup, _agents and _last_activity have the same keys."""
        mgr = _build_manager(ttl_minutes, agents_offsets)

        mgr._remove_stale()

        assert set(mgr._agents.keys()) == set(mgr._last_activity.keys()), (
            "_agents and _last_activity should always have the same key set"
        )

    @given(ttl_minutes=_ttl_minutes_st, agents_offsets=_agents_list_st)
    @settings(max_examples=150)
    def test_no_agents_removed_when_all_active(self, ttl_minutes, agents_offsets):
        """When all agents are within TTL, none are removed."""
        # Force all offsets to be well within TTL
        fresh_offsets = {sid: 0 for sid in agents_offsets}
        mgr = _build_manager(ttl_minutes, fresh_offsets)

        original_count = len(mgr._agents)
        mgr._remove_stale()

        assert len(mgr._agents) == original_count

    @given(ttl_minutes=_ttl_minutes_st, agents_offsets=_agents_list_st)
    @settings(max_examples=150)
    def test_all_agents_removed_when_all_stale(self, ttl_minutes, agents_offsets):
        """When all agents exceed TTL, all are removed."""
        # Force all offsets to be well beyond TTL
        stale_offsets = {sid: ttl_minutes + 60 for sid in agents_offsets}
        mgr = _build_manager(ttl_minutes, stale_offsets)

        mgr._remove_stale()

        assert len(mgr._agents) == 0
        assert len(mgr._last_activity) == 0


# ---------------------------------------------------------------------------
# Tool Messages Reconstruction Tests
# ---------------------------------------------------------------------------


def test_rebuild_tool_messages_skips_bad_entries_keeps_good():
    from agenticops.web.session_manager import _rebuild_tool_messages

    tool_calls = [
        {"name": "scan", "input": {"region": "us-east-1"}, "toolUseId": "t1"},
        {"input": {"oops": 1}},                      # missing name -> skip
        {"name": "detect", "input": {"deep": True}},  # valid
    ]
    msgs = _rebuild_tool_messages(tool_calls)
    # 2 valid calls -> 2 toolUse + 2 toolResult = 4 messages
    assert len(msgs) == 4
    names = [b["toolUse"]["name"] for m in msgs if m["role"] == "assistant" for b in m["content"]]
    assert names == ["scan", "detect"]


def test_rebuild_tool_messages_empty_input_returns_empty():
    from agenticops.web.session_manager import _rebuild_tool_messages
    assert _rebuild_tool_messages([]) == []
    assert _rebuild_tool_messages("not a list") == []


def test_remove_stale_uses_session_lock_for_trigger(monkeypatch):
    """Stale cleanup must hold a per-session lock while triggering summary."""
    from agenticops.web.session_manager import ChatSessionManager
    from datetime import datetime, timezone, timedelta
    import threading

    mgr = ChatSessionManager()
    sid = "sess-1"
    lock = threading.Lock()
    mgr._session_locks[sid] = lock
    mgr._last_activity[sid] = datetime.now(timezone.utc) - timedelta(hours=1)
    mgr._agents[sid] = object()

    held_during_trigger = {}
    def _fake_trigger(s):
        held_during_trigger[s] = lock.locked()
    monkeypatch.setattr("agenticops.web.session_manager._trigger_summary_and_memory", _fake_trigger)

    mgr._remove_stale()
    assert held_during_trigger.get(sid) is True


def test_trigger_does_not_extract_db_memory(monkeypatch):
    import agenticops.web.session_manager as sm
    extracted = {"facts": 0, "exp": 0}

    class _Spy:
        def extract_facts(self, *a, **k): extracted["facts"] += 1; return []
        def extract_experiences(self, *a, **k): extracted["exp"] += 1; return []

    monkeypatch.setattr("agenticops.web.memory_service.MemoryService", _Spy)
    monkeypatch.setattr(sm, "_load_raw_messages", lambda sid: [{"role": "user", "content": "hi"}])
    # summary generation is allowed to run/fail harmlessly; stub it to avoid network
    monkeypatch.setattr("agenticops.web.summary_service.SummaryService", lambda: type("S", (), {"generate_summary": lambda self, *a, **k: None})())
    sm._trigger_summary_and_memory("some-session")
    assert extracted["facts"] == 0 and extracted["exp"] == 0
