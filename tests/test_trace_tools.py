"""Tests for distributed tracing tools (trace_tools.py).

Covers: helper functions (_truncate, _parse_lookback, _format_duration,
_build_span_tree, _format_trace_summary) and @tool functions with mocked
Jaeger API responses.
"""

import pytest
from unittest.mock import patch, MagicMock

from agenticops.tools.trace_tools import (
    _truncate,
    _parse_lookback,
    _format_duration,
    _build_span_tree,
    _format_trace_summary,
    query_traces,
    get_trace_detail,
    get_service_dependencies,
    find_error_traces,
)


# ── Helper tests ──────────────────────────────────────────────────────


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_exact_limit_unchanged(self):
        assert _truncate("abcde", 5) == "abcde"

    def test_long_text_truncated(self):
        result = _truncate("abcdefgh", 5)
        assert result.startswith("abcde")
        assert "truncated" in result

    def test_default_limit(self):
        short = "x" * 100
        assert _truncate(short) == short


class TestParseLookback:
    def test_hours(self):
        assert _parse_lookback("1h") == 3600 * 1_000_000

    def test_minutes(self):
        assert _parse_lookback("30m") == 30 * 60 * 1_000_000

    def test_days(self):
        assert _parse_lookback("2d") == 2 * 86400 * 1_000_000

    def test_seconds(self):
        assert _parse_lookback("10s") == 10 * 1_000_000


class TestFormatDuration:
    def test_microseconds(self):
        assert _format_duration(500) == "500µs"

    def test_milliseconds(self):
        assert _format_duration(5_000) == "5ms"

    def test_seconds(self):
        assert _format_duration(1_500_000) == "1.5s"

    def test_zero(self):
        assert _format_duration(0) == "0µs"


class TestBuildSpanTree:
    def test_empty_spans(self):
        assert _build_span_tree([], {}) == "(no spans)"

    def test_single_root_span(self):
        spans = [
            {
                "spanID": "s1",
                "operationName": "/api/health",
                "processID": "p1",
                "startTime": 1000,
                "duration": 5000,
                "tags": [],
                "references": [],
            }
        ]
        processes = {"p1": {"serviceName": "frontend"}}
        tree = _build_span_tree(spans, processes)
        assert "frontend" in tree
        assert "/api/health" in tree
        assert "OK" in tree

    def test_parent_child_tree(self):
        spans = [
            {
                "spanID": "root",
                "operationName": "/checkout",
                "processID": "p1",
                "startTime": 1000,
                "duration": 50000,
                "tags": [],
                "references": [],
            },
            {
                "spanID": "child1",
                "operationName": "/getCart",
                "processID": "p2",
                "startTime": 2000,
                "duration": 40000,
                "tags": [],
                "references": [{"refType": "CHILD_OF", "spanID": "root"}],
            },
        ]
        processes = {
            "p1": {"serviceName": "frontend"},
            "p2": {"serviceName": "cartservice"},
        }
        tree = _build_span_tree(spans, processes)
        assert "frontend" in tree
        assert "cartservice" in tree
        assert "└──" in tree or "├──" in tree

    def test_error_span_marked(self):
        spans = [
            {
                "spanID": "s1",
                "operationName": "/fail",
                "processID": "p1",
                "startTime": 1000,
                "duration": 500,
                "tags": [{"key": "error", "value": True}],
                "references": [],
            }
        ]
        processes = {"p1": {"serviceName": "api"}}
        tree = _build_span_tree(spans, processes)
        assert "ERROR" in tree

    def test_slowest_annotated_when_multiple(self):
        spans = [
            {
                "spanID": "s1",
                "operationName": "/fast",
                "processID": "p1",
                "startTime": 1000,
                "duration": 100,
                "tags": [],
                "references": [],
            },
            {
                "spanID": "s2",
                "operationName": "/slow",
                "processID": "p1",
                "startTime": 2000,
                "duration": 99999,
                "tags": [],
                "references": [],
            },
        ]
        processes = {"p1": {"serviceName": "svc"}}
        tree = _build_span_tree(spans, processes)
        assert "SLOWEST" in tree


class TestFormatTraceSummary:
    def test_empty_trace(self):
        assert _format_trace_summary({"spans": []}) == "(empty trace)"

    def test_basic_summary(self):
        trace = {
            "traceID": "abc123def456",
            "spans": [
                {
                    "spanID": "s1",
                    "operationName": "/api",
                    "processID": "p1",
                    "startTime": 1000,
                    "duration": 5000,
                    "tags": [],
                }
            ],
            "processes": {"p1": {"serviceName": "frontend"}},
        }
        result = _format_trace_summary(trace)
        assert "abc123def456"[:12] in result
        assert "frontend" in result
        assert "1 spans" in result

    def test_error_flag(self):
        trace = {
            "traceID": "err123",
            "spans": [
                {
                    "spanID": "s1",
                    "operationName": "/fail",
                    "processID": "p1",
                    "startTime": 1000,
                    "duration": 500,
                    "tags": [{"key": "error", "value": True}],
                }
            ],
            "processes": {"p1": {"serviceName": "api"}},
        }
        result = _format_trace_summary(trace)
        assert "ERROR" in result


# ── @tool function tests (mocked Jaeger API) ─────────────────────────

_DISABLED_SETTINGS = MagicMock(jaeger_enabled=False)
_ENABLED_SETTINGS = MagicMock(
    jaeger_enabled=True,
    jaeger_query_endpoint="http://jaeger:16686",
    jaeger_default_lookback="1h",
)


class TestQueryTraces:
    @patch("agenticops.tools.trace_tools.settings", _DISABLED_SETTINGS)
    def test_disabled(self):
        result = query_traces(service="frontend")
        assert "disabled" in result.lower()

    @patch("agenticops.tools.trace_tools.settings", _ENABLED_SETTINGS)
    @patch("agenticops.tools.trace_tools._jaeger_get")
    def test_no_traces(self, mock_get):
        mock_get.return_value = {"data": []}
        result = query_traces(service="frontend")
        assert "No traces found" in result

    @patch("agenticops.tools.trace_tools.settings", _ENABLED_SETTINGS)
    @patch("agenticops.tools.trace_tools._jaeger_get")
    def test_returns_traces(self, mock_get):
        mock_get.return_value = {
            "data": [
                {
                    "traceID": "trace001",
                    "spans": [
                        {
                            "spanID": "s1",
                            "operationName": "/api",
                            "processID": "p1",
                            "startTime": 1000,
                            "duration": 5000,
                            "tags": [],
                        }
                    ],
                    "processes": {"p1": {"serviceName": "frontend"}},
                }
            ]
        }
        result = query_traces(service="frontend")
        text = result
        assert "frontend" in text
        assert "trace001" in text

    @patch("agenticops.tools.trace_tools.settings", _ENABLED_SETTINGS)
    @patch("agenticops.tools.trace_tools._jaeger_get")
    def test_api_error(self, mock_get):
        mock_get.side_effect = RuntimeError("connection refused")
        result = query_traces(service="frontend")
        assert "connection refused" in result


class TestGetTraceDetail:
    @patch("agenticops.tools.trace_tools.settings", _DISABLED_SETTINGS)
    def test_disabled(self):
        result = get_trace_detail(trace_id="abc")
        assert "disabled" in result.lower()

    @patch("agenticops.tools.trace_tools.settings", _ENABLED_SETTINGS)
    @patch("agenticops.tools.trace_tools._jaeger_get")
    def test_not_found(self, mock_get):
        mock_get.return_value = {"data": []}
        result = get_trace_detail(trace_id="missing")
        assert "not found" in result

    @patch("agenticops.tools.trace_tools.settings", _ENABLED_SETTINGS)
    @patch("agenticops.tools.trace_tools._jaeger_get")
    def test_returns_detail(self, mock_get):
        mock_get.return_value = {
            "data": [
                {
                    "traceID": "trace001",
                    "spans": [
                        {
                            "spanID": "s1",
                            "operationName": "/checkout",
                            "processID": "p1",
                            "startTime": 1000,
                            "duration": 50000,
                            "tags": [],
                            "references": [],
                        },
                        {
                            "spanID": "s2",
                            "operationName": "/getCart",
                            "processID": "p2",
                            "startTime": 2000,
                            "duration": 30000,
                            "tags": [],
                            "references": [{"refType": "CHILD_OF", "spanID": "s1"}],
                        },
                    ],
                    "processes": {
                        "p1": {"serviceName": "frontend"},
                        "p2": {"serviceName": "cartservice"},
                    },
                }
            ]
        }
        result = get_trace_detail(trace_id="trace001")
        text = result
        assert "frontend" in text
        assert "cartservice" in text
        assert "Services in trace" in text


class TestGetServiceDependencies:
    @patch("agenticops.tools.trace_tools.settings", _DISABLED_SETTINGS)
    def test_disabled(self):
        result = get_service_dependencies()
        assert "disabled" in result.lower()

    @patch("agenticops.tools.trace_tools.settings", _ENABLED_SETTINGS)
    @patch("agenticops.tools.trace_tools._jaeger_get")
    def test_no_deps(self, mock_get):
        mock_get.return_value = {"data": []}
        result = get_service_dependencies()
        assert "No service dependencies" in result

    @patch("agenticops.tools.trace_tools.settings", _ENABLED_SETTINGS)
    @patch("agenticops.tools.trace_tools._jaeger_get")
    def test_returns_deps(self, mock_get):
        mock_get.return_value = {
            "data": [
                {"parent": "frontend", "child": "cartservice", "callCount": 42},
                {"parent": "frontend", "child": "paymentservice", "callCount": 10},
            ]
        }
        result = get_service_dependencies()
        text = result
        assert "frontend → cartservice" in text
        assert "42 calls" in text


class TestFindErrorTraces:
    @patch("agenticops.tools.trace_tools.settings", _DISABLED_SETTINGS)
    def test_disabled(self):
        result = find_error_traces(service="api")
        assert "disabled" in result.lower()

    @patch("agenticops.tools.trace_tools.settings", _ENABLED_SETTINGS)
    @patch("agenticops.tools.trace_tools._jaeger_get")
    def test_no_errors(self, mock_get):
        mock_get.return_value = {"data": []}
        result = find_error_traces(service="api")
        assert "No error traces" in result

    @patch("agenticops.tools.trace_tools.settings", _ENABLED_SETTINGS)
    @patch("agenticops.tools.trace_tools._jaeger_get")
    def test_returns_error_analysis(self, mock_get):
        mock_get.return_value = {
            "data": [
                {
                    "traceID": "err001",
                    "spans": [
                        {
                            "spanID": "s1",
                            "operationName": "/checkout",
                            "processID": "p1",
                            "startTime": 1000,
                            "duration": 5000,
                            "tags": [],
                        },
                        {
                            "spanID": "s2",
                            "operationName": "/charge",
                            "processID": "p2",
                            "startTime": 2000,
                            "duration": 3000,
                            "tags": [{"key": "error", "value": True}],
                        },
                    ],
                    "processes": {
                        "p1": {"serviceName": "frontend"},
                        "p2": {"serviceName": "paymentservice"},
                    },
                }
            ]
        }
        result = find_error_traces(service="frontend")
        text = result
        assert "paymentservice" in text
        assert "1 errors" in text
        assert "/charge" in text
