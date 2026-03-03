---
name: distributed-tracing
description: "Distributed trace analysis via Jaeger — cross-service causal chain construction, latency bottleneck identification, error propagation tracking. Provides 4 trace query tools and decision trees for investigating cascading failures across microservices."
metadata:
  author: agenticops
  version: "1.0"
  domain: observability
tools:
  - agenticops.tools.trace_tools.query_traces
  - agenticops.tools.trace_tools.get_trace_detail
  - agenticops.tools.trace_tools.get_service_dependencies
  - agenticops.tools.trace_tools.find_error_traces
---

# Distributed Tracing Skill

## Overview

When this skill is activated, 4 trace query tools are dynamically registered:

| Tool | Purpose | Key Args |
|------|---------|----------|
| `query_traces` | Find traces for a service (summary list) | `service`, `lookback`, `operation`, `min_duration`, `limit` |
| `get_trace_detail` | Full span tree for a trace ID | `trace_id` |
| `get_service_dependencies` | Service-to-service call graph | `lookback` |
| `find_error_traces` | Error traces grouped by origin service | `service`, `lookback`, `limit` |

## When to Activate This Skill

Activate when the issue involves ANY of:
- **Service degradation** (latency spikes, timeout errors, 5xx responses)
- **Cascading failures** (multiple services affected, unclear origin)
- **Cross-service errors** (error in service A caused by downstream service B)
- **Intermittent failures** (some requests fail, others succeed — trace sampling reveals the pattern)

Do NOT activate for:
- Single-service issues (e.g., pod OOM, node disk pressure)
- Infrastructure-only issues (e.g., VPC routing, security groups)
- Issues where the failing service is already clearly identified

## Investigation Decision Tree

### 1. Service Degradation (High Latency / 5xx)

```
Alert: "frontend HighErrorRate" or "HighLatencyP99"
│
├── Step 1: get_service_dependencies()
│   → Understand the full call graph: who calls whom?
│
├── Step 2: query_traces(service="frontend", lookback="15m", min_duration="1s")
│   → Find slow traces — which traces are taking > 1s?
│
├── Step 3: get_trace_detail(trace_id=SLOWEST_TRACE)
│   → See the full span tree — WHERE is the time being spent?
│   → Look for the SLOWEST span — that's the bottleneck
│
│   Example span tree:
│   frontend: /checkout [5.2s] OK
│   ├── checkoutservice: /PlaceOrder [4.8s] OK
│   │   ├── cartservice: /GetCart [4.5s] ERROR  ← majority of time
│   │   │   └── redis-cart: GET [4.2s] ERROR    ← ROOT CAUSE
│   │   └── productcatalogservice: /GetProduct [50ms] OK
│   └── currencyservice: /Convert [30ms] OK
│
├── Step 4: find_error_traces(service="frontend")
│   → Confirm error pattern: which downstream service has most errors?
│
└── Conclusion: Root cause is redis-cart (4.2s timeout),
    NOT frontend (which is just the symptom)
```

### 2. Intermittent Failures

```
Alert: "Service X intermittent 5xx"
│
├── Step 1: query_traces(service="X", lookback="30m")
│   → Compare successful vs failed traces
│
├── Step 2: get_trace_detail(FAILED_TRACE_ID)
│   → Find where the error occurs in the chain
│
├── Step 3: get_trace_detail(SUCCESSFUL_TRACE_ID)
│   → Compare — what's different? Different path? Different downstream?
│
└── Common patterns:
    - Load balancer routing to unhealthy backend
    - Connection pool exhaustion (some requests get pooled conn, others timeout)
    - Retry storms (downstream overload causes more retries → more overload)
```

### 3. Unknown Dependency Failure

```
Alert on service A, but service A pods/metrics look healthy
│
├── Step 1: get_service_dependencies()
│   → Discover: A → B → C → D (chain you didn't know about)
│
├── Step 2: find_error_traces(service="A")
│   → Error origins show: D has 95% of errors, not A
│
├── Step 3: get_trace_detail(ERROR_TRACE_ID)
│   → Confirms: D is the fault origin, errors propagate D → C → B → A
│
└── Conclusion: Investigate service D, not A
```

## Interpreting Span Trees

### Key Signals

| Signal | Meaning |
|--------|---------|
| SLOWEST span deep in the tree | Downstream bottleneck — root cause is the slow service |
| ERROR on leaf span only | Single point of failure — error originates at the leaf |
| ERROR propagating up the tree | Cascading failure — fix the deepest ERROR first |
| One branch slow, others fast | Isolated issue in one dependency path |
| All branches slow | Possible network issue or shared resource (DB, cache) saturation |

### Duration Analysis

- Compare span duration to its parent — if a child is >80% of parent's duration, that child is the bottleneck
- Gaps between child spans indicate processing time in the parent service
- Overlapping child spans indicate parallel calls (fan-out pattern)

### Error Tags

Jaeger uses the `error=true` tag on spans. Additional context from:
- `http.status_code`: HTTP response code (500, 503, 504)
- `otel.status_code`: OpenTelemetry status (ERROR)
- `otel.status_description`: Error message text

## Confidence Scoring with Traces

| Evidence | Confidence Boost |
|----------|-----------------|
| Trace shows clear bottleneck (>80% of total duration in one span) | +0.3 |
| Multiple error traces point to same downstream service | +0.2 |
| Service dependency graph confirms the affected path | +0.1 |
| Trace evidence correlates with metric anomaly timing | +0.2 |

Example: Without traces, confidence might be 0.4 (speculation).
With traces showing redis-cart as bottleneck across 15/20 error traces: 0.4 + 0.3 + 0.2 + 0.1 = **0.9** (high confidence).
