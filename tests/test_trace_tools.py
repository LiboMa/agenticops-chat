"""Unit tests for agenticops.tools.trace_tools module.

Covers: query_traces, get_trace_detail, get_service_dependencies,
find_error_traces, and internal helpers.
"""

from unittest.mock import patch, MagicMock

import pytest

from agenticops.tools.trace_tools import (
    _truncate,
    _parse_lookback,
    _format_duration,
    _build_span_tree,
    _format_trace_summary,
    MAX_TRACE_CHARS,
)


# ── Helper tests ─────────────────────────────────────────────────────


class TestTruncate:
    def test_short_unchanged(self):
        assert _truncate("hi", 100) == "hi"

    def test_over_limit(self):
        text = "a" * 5000
        result = _truncate(text)
        assert "truncated" in result


class TestParseLookback:
    def test_seconds(self):
        assert _parse_lookback("30s") == 30 * 1_000_000

    def test_minutes(self):
        assert _parse_lookback("5m") == 5 * 60 * 1_000_000

    def test_hours(self):
        assert _parse_lookback("2h") == 2 * 3600 * 1_000_000

    def test_days(self):
        assert _parse_lookback("1d") == 86400 * 1_000_000

    def test_unknown_unit_defaults_to_hours(self):
        # Unknown unit falls through to 3600 multiplier
        assert _parse_lookback("3x") == 3 * 3600 * 1_000_000


class TestFormatDuration:
    def test_microseconds(self):
        assert _format_duration(500) == "500µs"

    def test_milliseconds(self):
        assert _format_duration(5000) == "5ms"

    def test_seconds(self):
        assert _format_duration(2_500_000) == "2.5s"

    def test_boundary_1000us(self):
        assert _format_duration(1000) == "1ms"

    def test_boundary_1000ms(self):
        assert _format_duration(1_000_000) == "1.0s"


class TestBuildSpanTree:
    def test_empty_spans(self):
        assert _build_span_tree([], {}) == "(no spans)"

    def test_single_root_span(self):
        spans = [{
            "spanID": "s1",
            "operationName": "/api/health",
            "processID": "p1",
            "startTime": 1000,
            "duration": 500,
            "tags": [],
            "references": [],
        }]
        processes = {"p1": {"serviceName": "frontend"}}
        result = _build_span_tree(spans, processes)
        assert "frontend" in result
        assert "/api/health" in result
        assert "OK" in result

    def test_error_span(self):
        spans = [{
            "spanID": "s1",
            "operationName": "/checkout",
            "processID": "p1",
            "startTime": 1000,
            "duration": 500,
            "tags": [{"key": "error", "value": True}],
            "references": [],
        }]
        processes = {"p1": {"serviceName": "cart"}}
        result = _build_span_tree(spans, processes)
        assert "ERROR" in result

    def test_parent_child_tree(self):
        spans = [
            {
                "spanID": "root",
                "operationName": "/api",
                "processID": "p1",
                "startTime": 1000,
                "duration": 5000,
                "tags": [],
                "references": [],
            },
            {
                "spanID": "child1",
                "operationName": "/db",
                "processID": "p2",
                "startTime": 1100,
                "duration": 4000,
                "tags": [],
                "references": [{"refType": "CHILD_OF", "spanID": "root"}],
            },
        ]
        processes = {"p1": {"serviceName": "api"}, "p2": {"serviceName": "db"}}
        result = _build_span_tree(spans, processes)
        assert "api" in result
        assert "db" in result
        assert "SLOWEST" in result  # child is slowest

    def test_slowest_annotation_only_multi_span(self):
        spans = [{
            "spanID": "s1",
            "operationName": "/x",
            "processID": "p1",
            "startTime": 1000,
            "duration": 500,
            "tags": [],
            "references": [],
        }]
        processes = {"p1": {"serviceName": "svc"}}
        result = _build_span_tree(spans, processes)
        # Single span should NOT get SLOWEST marker
        assert "SLOWEST" not in result


class TestFormatTraceSummary:
    def test_empty_trace(self):
        assert _format_trace_summary({"spans": [], "processes": {}}) == "(empty trace)"

    def test_basic_trace(self):
        trace = {
            "traceID": "abc123def456",
            "spans": [{
                "spanID": "s1",
                "operationName": "/health",
                "processID": "p1",
                "startTime": 1000,
                "duration": 5000,
                "tags": [],
            }],
            "processes": {"p1": {"serviceName": "frontend"}},
        }
        result = _format_trace_summary(trace)
        assert "abc123def456"[:12] in result
        assert "frontend" in result
        assert "/health" in result

    def test_error_trace(self):
        trace = {
            "traceID": "errortrace12",
            "spans": [{
                "spanID": "s1",
                "operationName": "/fail",
                "processID": "p1",
                "startTime": 1000,
                "duration": 1000,
                "tags": [{"key": "error", "value": True}],
            }],
            "processes": {"p1": {"serviceName": "backend"}},
        }
        result = _format_trace_summary(trace)
        assert "ERROR" in result


# ── Tool function tests (with mocked Jaeger API) ────────────────────


class TestQueryTraces:
    def _call(self, **kwargs):
        from agenticops.tools.trace_tools import query_traces
        return query_traces._tool_func(**kwargs)

    @patch("agenticops.tools.trace_tools.settings")
    def test_disabled(self, mock_settings):
        mock_settings.jaeger_enabled = False
        result = self._call(service="frontend")
        assert "disabled" in result.lower()

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_no_traces_found(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_settings.jaeger_default_lookback = "1h"
        mock_get.return_value = {"data": []}
        result = self._call(service="frontend")
        assert "No traces found" in result

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_returns_traces(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_settings.jaeger_default_lookback = "1h"
        mock_get.return_value = {"data": [{
            "traceID": "trace123",
            "spans": [{
                "spanID": "s1",
                "operationName": "/api",
                "processID": "p1",
                "startTime": 1000,
                "duration": 5000,
                "tags": [],
            }],
            "processes": {"p1": {"serviceName": "frontend"}},
        }]}
        result = self._call(service="frontend")
        assert "frontend" in result
        assert "1 found" in result

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_with_operation_and_tags(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_settings.jaeger_default_lookback = "1h"
        mock_get.return_value = {"data": []}
        self._call(service="svc", operation="/api", tags="http.status_code:500", min_duration="1s")
        args = mock_get.call_args
        params = args[1]["params"] if "params" in args[1] else args[0][1]
        assert params["operation"] == "/api"
        assert params["minDuration"] == "1s"

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_runtime_error(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_settings.jaeger_default_lookback = "1h"
        mock_get.side_effect = RuntimeError("Connection refused")
        result = self._call(service="frontend")
        assert "Connection refused" in result


class TestGetTraceDetail:
    def _call(self, **kwargs):
        from agenticops.tools.trace_tools import get_trace_detail
        return get_trace_detail._tool_func(**kwargs)

    @patch("agenticops.tools.trace_tools.settings")
    def test_disabled(self, mock_settings):
        mock_settings.jaeger_enabled = False
        result = self._call(trace_id="abc123")
        assert "disabled" in result.lower()

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_trace_not_found(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_get.return_value = {"data": []}
        result = self._call(trace_id="abc123")
        assert "not found" in result.lower()

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_returns_span_tree(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_get.return_value = {"data": [{
            "traceID": "abc123",
            "spans": [
                {
                    "spanID": "s1",
                    "operationName": "/api",
                    "processID": "p1",
                    "startTime": 1000,
                    "duration": 10000,
                    "tags": [],
                    "references": [],
                },
                {
                    "spanID": "s2",
                    "operationName": "/db",
                    "processID": "p2",
                    "startTime": 1100,
                    "duration": 8000,
                    "tags": [],
                    "references": [{"refType": "CHILD_OF", "spanID": "s1"}],
                },
            ],
            "processes": {
                "p1": {"serviceName": "api"},
                "p2": {"serviceName": "db"},
            },
        }]}
        result = self._call(trace_id="abc123")
        assert "api" in result
        assert "db" in result
        assert "Services in trace" in result


class TestGetServiceDependencies:
    def _call(self, **kwargs):
        from agenticops.tools.trace_tools import get_service_dependencies
        return get_service_dependencies._tool_func(**kwargs)

    @patch("agenticops.tools.trace_tools.settings")
    def test_disabled(self, mock_settings):
        mock_settings.jaeger_enabled = False
        result = self._call()
        assert "disabled" in result.lower()

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_no_dependencies(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_settings.jaeger_default_lookback = "1h"
        mock_get.return_value = {"data": []}
        result = self._call()
        assert "No service dependencies" in result

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_returns_deps(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_settings.jaeger_default_lookback = "1h"
        mock_get.return_value = {"data": [
            {"parent": "frontend", "child": "backend", "callCount": 100},
            {"parent": "backend", "child": "db", "callCount": 50},
        ]}
        result = self._call()
        assert "frontend → backend" in result
        assert "100 calls" in result
        assert "backend → db" in result


class TestFindErrorTraces:
    def _call(self, **kwargs):
        from agenticops.tools.trace_tools import find_error_traces
        return find_error_traces._tool_func(**kwargs)

    @patch("agenticops.tools.trace_tools.settings")
    def test_disabled(self, mock_settings):
        mock_settings.jaeger_enabled = False
        result = self._call(service="frontend")
        assert "disabled" in result.lower()

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_no_errors(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_settings.jaeger_default_lookback = "1h"
        mock_get.return_value = {"data": []}
        result = self._call(service="frontend")
        assert "No error traces" in result

    @patch("agenticops.tools.trace_tools._jaeger_get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_returns_error_analysis(self, mock_settings, mock_get):
        mock_settings.jaeger_enabled = True
        mock_settings.jaeger_default_lookback = "1h"
        mock_get.return_value = {"data": [{
            "traceID": "err1",
            "spans": [
                {
                    "spanID": "s1",
                    "operationName": "/checkout",
                    "processID": "p1",
                    "startTime": 1000,
                    "duration": 5000,
                    "tags": [{"key": "error", "value": True}],
                },
                {
                    "spanID": "s2",
                    "operationName": "/db-write",
                    "processID": "p2",
                    "startTime": 1100,
                    "duration": 4000,
                    "tags": [{"key": "error", "value": True}],
                },
            ],
            "processes": {
                "p1": {"serviceName": "cart"},
                "p2": {"serviceName": "postgres"},
            },
        }]}
        result = self._call(service="cart")
        assert "Error origins" in result
        assert "cart" in result
        assert "postgres" in result


# ── _jaeger_get tests ────────────────────────────────────────────────


class TestJaegerGet:
    @patch("agenticops.tools.trace_tools.requests.get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_connection_error(self, mock_settings, mock_get):
        import requests as req
        mock_settings.jaeger_query_endpoint = "http://localhost:16686"
        mock_get.side_effect = req.ConnectionError("refused")
        from agenticops.tools.trace_tools import _jaeger_get
        with pytest.raises(RuntimeError, match="Cannot connect"):
            _jaeger_get("/api/traces")

    @patch("agenticops.tools.trace_tools.requests.get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_http_error(self, mock_settings, mock_get):
        mock_settings.jaeger_query_endpoint = "http://localhost:16686"
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("500")
        mock_get.return_value = resp
        from agenticops.tools.trace_tools import _jaeger_get
        with pytest.raises(Exception):
            _jaeger_get("/api/traces")

    @patch("agenticops.tools.trace_tools.requests.get")
    @patch("agenticops.tools.trace_tools.settings")
    def test_success(self, mock_settings, mock_get):
        mock_settings.jaeger_query_endpoint = "http://localhost:16686"
        resp = MagicMock()
        resp.json.return_value = {"data": []}
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        from agenticops.tools.trace_tools import _jaeger_get
        result = _jaeger_get("/api/traces", {"service": "x"})
        assert result == {"data": []}
