"""Tests for src/agenticops/services/pipeline_events.py — covering _resolve_trace_id
fallback paths, log_event exception handling, and get_timeline."""

import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from types import ModuleType
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# _resolve_trace_id
# ---------------------------------------------------------------------------

class TestResolveTraceId:
    """Cover the three branches: param, ContextVar, DB fallback, and None."""

    def test_returns_param_when_provided(self):
        from agenticops.services.pipeline_events import _resolve_trace_id
        assert _resolve_trace_id("abc-123", 1) == "abc-123"

    @patch("agenticops.services.pipeline_events.get_trace_id", create=True)
    def test_falls_back_to_context_var(self, mock_get_trace):
        """When trace_id param is None, reads from ContextVar."""
        mock_get_trace.return_value = "ctx-trace-42"
        with patch.dict("sys.modules", {"agenticops.config": MagicMock(get_trace_id=mock_get_trace)}):
            from importlib import reload
            import agenticops.services.pipeline_events as mod
            reload(mod)
            result = mod._resolve_trace_id(None, 99)
        assert result == "ctx-trace-42"

    def test_falls_back_to_db_lookup(self):
        """When ContextVar is unavailable, reads from DB."""
        mock_issue = MagicMock()
        mock_issue.trace_id = "db-trace-7"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_issue

        mock_models = MagicMock()
        mock_models.get_db_session.return_value = mock_session
        mock_models.HealthIssue = MagicMock()

        # Make ContextVar import fail, then DB lookup succeed
        bad_config = MagicMock()
        bad_config.get_trace_id.side_effect = Exception("no ctx")

        with patch.dict("sys.modules", {
            "agenticops.config": bad_config,
            "agenticops.models": mock_models,
        }):
            from importlib import reload
            import agenticops.services.pipeline_events as mod
            reload(mod)
            result = mod._resolve_trace_id(None, 5)
        assert result == "db-trace-7"

    def test_returns_none_when_all_fail(self):
        """When param is None, ContextVar fails, DB fails → returns None."""
        bad_config = MagicMock()
        bad_config.get_trace_id.side_effect = Exception("no ctx")
        bad_models = MagicMock()
        bad_models.get_db_session.side_effect = Exception("no db")

        with patch.dict("sys.modules", {
            "agenticops.config": bad_config,
            "agenticops.models": bad_models,
        }):
            from importlib import reload
            import agenticops.services.pipeline_events as mod
            reload(mod)
            result = mod._resolve_trace_id(None, 999)
        assert result is None


# ---------------------------------------------------------------------------
# log_event — exception handling
# ---------------------------------------------------------------------------

class TestLogEvent:
    def test_log_event_succeeds(self):
        """log_event creates a PipelineEvent and adds to session."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_models = MagicMock()
        mock_models.get_db_session.return_value = mock_session

        with patch.dict("sys.modules", {"agenticops.models": mock_models}):
            from importlib import reload
            import agenticops.services.pipeline_events as mod
            reload(mod)
            mod.log_event(
                health_issue_id=1,
                event_type="rca_started",
                stage="rca",
                status="completed",
                detail={"key": "value"},
                actor="test",
                duration_ms=150,
                trace_id="t-1",
            )
        mock_session.add.assert_called_once()

    def test_log_event_never_raises(self):
        """log_event swallows exceptions — best-effort."""
        bad_models = MagicMock()
        bad_models.get_db_session.side_effect = Exception("db down")

        with patch.dict("sys.modules", {"agenticops.models": bad_models}):
            from importlib import reload
            import agenticops.services.pipeline_events as mod
            reload(mod)
            # Should not raise
            mod.log_event(health_issue_id=1, event_type="boom", stage="rca")


# ---------------------------------------------------------------------------
# get_timeline
# ---------------------------------------------------------------------------

class TestGetTimeline:
    def test_returns_formatted_events(self):
        """get_timeline returns a list of dicts from PipelineEvent rows."""
        now = datetime.now(timezone.utc)
        mock_event = MagicMock()
        mock_event.id = 10
        mock_event.event_type = "rca_completed"
        mock_event.stage = "rca"
        mock_event.status = "completed"
        mock_event.detail = json.dumps({"root_cause": "OOM"})
        mock_event.actor = "agent"
        mock_event.duration_ms = 200
        mock_event.created_at = now
        mock_event.trace_id = "tr-5"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        query_chain = mock_session.query.return_value.filter_by.return_value.order_by.return_value
        query_chain.all.return_value = [mock_event]

        mock_models = MagicMock()
        mock_models.get_db_session.return_value = mock_session
        mock_models.PipelineEvent = MagicMock()
        mock_models.PipelineEvent.created_at = MagicMock()
        mock_models.PipelineEvent.created_at.asc.return_value = "asc"

        with patch.dict("sys.modules", {"agenticops.models": mock_models}):
            from importlib import reload
            import agenticops.services.pipeline_events as mod
            reload(mod)
            timeline = mod.get_timeline(1)

        assert len(timeline) == 1
        assert timeline[0]["event_type"] == "rca_completed"
        assert timeline[0]["detail"] == {"root_cause": "OOM"}
        assert timeline[0]["trace_id"] == "tr-5"

    def test_empty_timeline(self):
        """get_timeline returns [] when no events exist."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        query_chain = mock_session.query.return_value.filter_by.return_value.order_by.return_value
        query_chain.all.return_value = []

        mock_models = MagicMock()
        mock_models.get_db_session.return_value = mock_session
        mock_models.PipelineEvent = MagicMock()
        mock_models.PipelineEvent.created_at = MagicMock()
        mock_models.PipelineEvent.created_at.asc.return_value = "asc"

        with patch.dict("sys.modules", {"agenticops.models": mock_models}):
            from importlib import reload
            import agenticops.services.pipeline_events as mod
            reload(mod)
            timeline = mod.get_timeline(42)

        assert timeline == []

    def test_event_with_null_detail(self):
        """Events with detail=None should return detail=None."""
        mock_event = MagicMock()
        mock_event.id = 1
        mock_event.event_type = "alert_received"
        mock_event.stage = "alert"
        mock_event.status = "completed"
        mock_event.detail = None
        mock_event.actor = "system"
        mock_event.duration_ms = None
        mock_event.created_at = None
        mock_event.trace_id = None

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        query_chain = mock_session.query.return_value.filter_by.return_value.order_by.return_value
        query_chain.all.return_value = [mock_event]

        mock_models = MagicMock()
        mock_models.get_db_session.return_value = mock_session
        mock_models.PipelineEvent = MagicMock()
        mock_models.PipelineEvent.created_at = MagicMock()
        mock_models.PipelineEvent.created_at.asc.return_value = "asc"

        with patch.dict("sys.modules", {"agenticops.models": mock_models}):
            from importlib import reload
            import agenticops.services.pipeline_events as mod
            reload(mod)
            timeline = mod.get_timeline(1)

        assert timeline[0]["detail"] is None
        assert timeline[0]["created_at"] is None
