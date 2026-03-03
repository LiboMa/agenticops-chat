"""Distributed tracing tools for Strands agents.

Queries the Jaeger Query API to retrieve traces, span trees, service
dependencies, and error patterns.  Designed for dynamic registration via
the ``distributed-tracing`` Agent Skill.
"""

import logging
import time
from typing import Any

import requests
from strands import tool

from agenticops.config import settings

logger = logging.getLogger(__name__)

# ── Output size limits (matches metadata_tools.py / execution.py) ─────
MAX_TRACE_CHARS = 4000


def _truncate(text: str, limit: int = MAX_TRACE_CHARS) -> str:
    """Truncate tool output to *limit* characters."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (output truncated)"


# ── Internal helpers ──────────────────────────────────────────────────

def _jaeger_get(path: str, params: dict | None = None) -> dict:
    """Make a GET request to the Jaeger Query API.

    Raises:
        RuntimeError: On connection error or non-200 response.
    """
    url = f"{settings.jaeger_query_endpoint}{path}"
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Jaeger at {settings.jaeger_query_endpoint}. "
            "Ensure Jaeger is deployed and accessible."
        )
    except requests.HTTPError as e:
        raise RuntimeError(f"Jaeger API error: {e}")


def _parse_lookback(lookback: str) -> int:
    """Convert a lookback string (e.g. '1h', '30m', '2d') to microseconds."""
    unit = lookback[-1].lower()
    value = int(lookback[:-1])
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = value * multipliers.get(unit, 3600)
    return seconds * 1_000_000  # Jaeger uses microseconds


def _format_duration(duration_us: int) -> str:
    """Format microsecond duration to human-readable string."""
    if duration_us < 1000:
        return f"{duration_us}µs"
    ms = duration_us / 1000
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def _build_span_tree(spans: list[dict], processes: dict) -> str:
    """Build an indented span tree from Jaeger trace spans.

    Returns a formatted tree like:
        frontend: /checkout [5.2s] OK
        ├── checkoutservice: /PlaceOrder [4.8s] OK
        │   ├── cartservice: /GetCart [4.5s] ERROR
        │   │   └── redis-cart: GET [4.2s] ERROR ← SLOWEST
        │   └── productcatalogservice: /GetProduct [50ms] OK
        └── currencyservice: /Convert [30ms] OK
    """
    if not spans:
        return "(no spans)"

    # Index spans by spanID
    by_id: dict[str, dict] = {s["spanID"]: s for s in spans}

    # Build parent → children mapping
    children: dict[str, list[dict]] = {}
    root_spans: list[dict] = []
    for span in spans:
        refs = span.get("references", [])
        parent_id = None
        for ref in refs:
            if ref.get("refType") == "CHILD_OF":
                parent_id = ref.get("spanID")
                break
        if parent_id and parent_id in by_id:
            children.setdefault(parent_id, []).append(span)
        else:
            root_spans.append(span)

    # Sort children by startTime
    for kids in children.values():
        kids.sort(key=lambda s: s.get("startTime", 0))
    root_spans.sort(key=lambda s: s.get("startTime", 0))

    # Find slowest span for annotation
    slowest_id = max(spans, key=lambda s: s.get("duration", 0))["spanID"]

    # Recursive render
    lines: list[str] = []

    def _render(span: dict, prefix: str, is_last: bool, is_root: bool) -> None:
        svc = processes.get(span.get("processID", ""), {}).get(
            "serviceName", "unknown"
        )
        op = span.get("operationName", "?")
        dur = _format_duration(span.get("duration", 0))
        has_error = any(
            t.get("key") == "error" and t.get("value") is True
            for t in span.get("tags", [])
        )
        status = "ERROR" if has_error else "OK"
        marker = " ← SLOWEST" if span["spanID"] == slowest_id and len(spans) > 1 else ""

        if is_root:
            connector = ""
            child_prefix = ""
        else:
            connector = "└── " if is_last else "├── "
            child_prefix = "    " if is_last else "│   "

        lines.append(f"{prefix}{connector}{svc}: {op} [{dur}] {status}{marker}")

        kids = children.get(span["spanID"], [])
        for i, child in enumerate(kids):
            _render(child, prefix + child_prefix, i == len(kids) - 1, False)

    for i, root in enumerate(root_spans):
        _render(root, "", i == len(root_spans) - 1, True)

    return "\n".join(lines)


def _format_trace_summary(trace: dict) -> str:
    """One-line summary of a trace."""
    spans = trace.get("spans", [])
    processes = trace.get("processes", {})
    if not spans:
        return "(empty trace)"

    trace_id = trace.get("traceID", "?")
    # Root span = earliest start
    root = min(spans, key=lambda s: s.get("startTime", 0))
    root_svc = processes.get(root.get("processID", ""), {}).get(
        "serviceName", "?"
    )
    root_op = root.get("operationName", "?")
    total_dur = max(
        s.get("startTime", 0) + s.get("duration", 0) for s in spans
    ) - min(s.get("startTime", 0) for s in spans)
    has_error = any(
        any(t.get("key") == "error" and t.get("value") is True for t in s.get("tags", []))
        for s in spans
    )
    error_flag = " ERROR" if has_error else ""

    return (
        f"{trace_id[:12]} | {root_svc}:{root_op} | "
        f"{_format_duration(total_dur)} | {len(spans)} spans{error_flag}"
    )


# ── @tool functions ───────────────────────────────────────────────────


@tool
def query_traces(
    service: str,
    lookback: str = "",
    operation: str = "",
    min_duration: str = "",
    limit: int = 20,
    tags: str = "",
) -> str:
    """Query distributed traces for a service from Jaeger.

    Returns a summary list of recent traces showing trace ID, root service,
    duration, span count, and error flag.  Use get_trace_detail() on a
    specific trace ID to see the full span tree.

    Args:
        service: Service name to query traces for (e.g. 'frontend', 'cartservice').
        lookback: Time window to search (e.g. '1h', '30m', '2d'). Defaults to config.
        operation: Filter by operation name (optional).
        min_duration: Minimum trace duration filter (e.g. '500ms', '1s') (optional).
        limit: Maximum number of traces to return (default 20).
        tags: Comma-separated key:value tag filters (e.g. 'http.status_code:500') (optional).

    Returns:
        Formatted trace summaries or error message.
    """
    if not settings.jaeger_enabled:
        return "Distributed tracing is disabled (AIOPS_JAEGER_ENABLED=false)."

    params: dict[str, Any] = {
        "service": service,
        "limit": min(limit, 50),
        "lookback": _parse_lookback(lookback or settings.jaeger_default_lookback),
    }
    if operation:
        params["operation"] = operation
    if min_duration:
        params["minDuration"] = min_duration
    if tags:
        for tag in tags.split(","):
            tag = tag.strip()
            if ":" in tag:
                k, v = tag.split(":", 1)
                params[f"tag:{k.strip()}"] = v.strip()

    try:
        data = _jaeger_get("/api/traces", params)
    except RuntimeError as e:
        return str(e)

    traces = data.get("data", [])
    if not traces:
        return f"No traces found for service '{service}' in the specified time window."

    lines = [f"Traces for '{service}' ({len(traces)} found):\n"]
    for trace in traces:
        lines.append(f"  {_format_trace_summary(trace)}")

    return _truncate("\n".join(lines))


@tool
def get_trace_detail(trace_id: str) -> str:
    """Get the full span tree for a specific distributed trace.

    Shows the complete call chain across services with duration and error
    status at each hop.  Use this to identify which downstream service is
    the actual bottleneck or error source.

    Args:
        trace_id: The Jaeger trace ID to retrieve.

    Returns:
        Formatted span tree showing the cross-service call chain.
    """
    if not settings.jaeger_enabled:
        return "Distributed tracing is disabled (AIOPS_JAEGER_ENABLED=false)."

    try:
        data = _jaeger_get(f"/api/traces/{trace_id}")
    except RuntimeError as e:
        return str(e)

    traces = data.get("data", [])
    if not traces:
        return f"Trace '{trace_id}' not found."

    trace = traces[0]
    spans = trace.get("spans", [])
    processes = trace.get("processes", {})

    total_dur = max(
        s.get("startTime", 0) + s.get("duration", 0) for s in spans
    ) - min(s.get("startTime", 0) for s in spans) if spans else 0

    header = f"Trace {trace_id} (total: {_format_duration(total_dur)}, {len(spans)} spans)\n"
    tree = _build_span_tree(spans, processes)

    # Collect services involved
    services = sorted({
        processes.get(s.get("processID", ""), {}).get("serviceName", "?")
        for s in spans
    })

    result = f"{header}{tree}\n\nServices in trace: {', '.join(services)}"
    return _truncate(result)


@tool
def get_service_dependencies(lookback: str = "") -> str:
    """Get the service-to-service dependency graph from trace data.

    Shows which services call which other services and the call count.
    Useful for understanding the request flow topology before investigating
    a specific trace.

    Args:
        lookback: Time window (e.g. '1h', '30m'). Defaults to config.

    Returns:
        Service dependency adjacency list.
    """
    if not settings.jaeger_enabled:
        return "Distributed tracing is disabled (AIOPS_JAEGER_ENABLED=false)."

    end_ts = int(time.time() * 1000)  # milliseconds
    lb = lookback or settings.jaeger_default_lookback
    unit = lb[-1].lower()
    value = int(lb[:-1])
    multipliers = {"s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}
    lookback_ms = value * multipliers.get(unit, 3_600_000)

    try:
        data = _jaeger_get("/api/dependencies", {
            "endTs": end_ts,
            "lookback": lookback_ms,
        })
    except RuntimeError as e:
        return str(e)

    deps = data.get("data", [])
    if not deps:
        return f"No service dependencies found in the last {lb}. Traces may not be flowing yet."

    # Group by parent
    by_parent: dict[str, list[tuple[str, int]]] = {}
    for d in deps:
        parent = d.get("parent", "?")
        child = d.get("child", "?")
        count = d.get("callCount", 0)
        by_parent.setdefault(parent, []).append((child, count))

    lines = [f"Service Dependencies (last {lb}):\n"]
    for parent in sorted(by_parent):
        for child, count in sorted(by_parent[parent]):
            lines.append(f"  {parent} → {child} ({count} calls)")

    return _truncate("\n".join(lines))


@tool
def find_error_traces(
    service: str,
    lookback: str = "",
    limit: int = 10,
) -> str:
    """Find traces with errors for a service and summarize error patterns.

    Queries Jaeger for traces tagged with errors, then groups them by the
    service where the error originated to help identify the real fault
    source in a microservice chain.

    Args:
        service: Service name to search for error traces.
        lookback: Time window (e.g. '1h', '30m'). Defaults to config.
        limit: Maximum number of error traces to return (default 10).

    Returns:
        Error trace summaries grouped by originating service.
    """
    if not settings.jaeger_enabled:
        return "Distributed tracing is disabled (AIOPS_JAEGER_ENABLED=false)."

    params: dict[str, Any] = {
        "service": service,
        "limit": min(limit, 30),
        "lookback": _parse_lookback(lookback or settings.jaeger_default_lookback),
        "tags": '{"error":"true"}',
    }

    try:
        data = _jaeger_get("/api/traces", params)
    except RuntimeError as e:
        return str(e)

    traces = data.get("data", [])
    if not traces:
        return f"No error traces found for service '{service}'."

    # Analyze error origins
    error_origins: dict[str, int] = {}
    error_operations: dict[str, set[str]] = {}
    for trace in traces:
        processes = trace.get("processes", {})
        for span in trace.get("spans", []):
            has_error = any(
                t.get("key") == "error" and t.get("value") is True
                for t in span.get("tags", [])
            )
            if has_error:
                svc = processes.get(span.get("processID", ""), {}).get(
                    "serviceName", "unknown"
                )
                error_origins[svc] = error_origins.get(svc, 0) + 1
                error_operations.setdefault(svc, set()).add(
                    span.get("operationName", "?")
                )

    lines = [f"Error traces for '{service}' ({len(traces)} traces with errors):\n"]

    # Error origin summary
    lines.append("Error origins (service → error count):")
    for svc, count in sorted(error_origins.items(), key=lambda x: -x[1]):
        ops = ", ".join(sorted(error_operations.get(svc, set())))
        lines.append(f"  {svc}: {count} errors (operations: {ops})")

    lines.append(f"\nTrace summaries:")
    for trace in traces[:limit]:
        lines.append(f"  {_format_trace_summary(trace)}")

    return _truncate("\n".join(lines))
