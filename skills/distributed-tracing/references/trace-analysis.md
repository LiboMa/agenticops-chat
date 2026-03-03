# Trace Analysis Reference

## Jaeger Query API

### Endpoints Used by trace_tools

| Endpoint | Purpose |
|----------|---------|
| `GET /api/services` | List all traced services |
| `GET /api/traces?service=X` | Query traces for a service |
| `GET /api/traces/{traceID}` | Get full trace with all spans |
| `GET /api/dependencies?endTs=X&lookback=Y` | Service dependency graph |

### Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `service` | string | Service name (required for trace queries) |
| `operation` | string | Filter by operation/endpoint name |
| `lookback` | int | Lookback window in microseconds |
| `limit` | int | Max traces to return |
| `minDuration` | string | Min trace duration (e.g. '1s', '500ms') |
| `tags` | JSON string | Tag filters: `{"error":"true","http.status_code":"500"}` |

## Trace Data Model

### Trace Structure

```
Trace
├── traceID: "abc123def456..."
├── spans: [Span, Span, ...]
└── processes: { "p1": { "serviceName": "frontend" }, ... }
```

### Span Structure

```
Span
├── spanID: "1234567890abcdef"
├── operationName: "/api/checkout"
├── processID: "p1"  (→ look up in processes map)
├── startTime: 1709000000000000  (microseconds since epoch)
├── duration: 5200000  (microseconds)
├── references: [{ "refType": "CHILD_OF", "traceID": "...", "spanID": "parent-id" }]
├── tags: [{ "key": "error", "value": true, "type": "bool" }, ...]
└── logs: [{ "timestamp": ..., "fields": [...] }]
```

### Reference Types

- `CHILD_OF`: Standard parent-child relationship (most common)
- `FOLLOWS_FROM`: Causal but not blocking (async operations)

## Common Microservice Trace Patterns

### 1. Synchronous Chain (Most Common)

```
A → B → C → D
```
Each service waits for downstream response. Latency is additive.
Root cause identification: find the span with the highest self-time.

### 2. Fan-Out

```
A → B
A → C
A → D
```
Service A calls B, C, D in parallel. Total latency = max(B, C, D).
Root cause: the slowest parallel branch.

### 3. Fan-Out/Fan-In

```
A → B → D
A → C → D
```
Both B and C call the same downstream service D.
If D is slow, both paths are affected — D is a shared bottleneck.

### 4. Retry Storm

```
A → B (timeout) → retry → B (timeout) → retry → B (timeout)
```
Multiple spans from A to B with increasing timestamps.
Indicates B is overloaded. Retries make it worse.

### 5. Circuit Breaker Open

```
A → B (fast failure, no downstream spans)
```
B fails immediately without calling its dependencies.
Look for very short span duration + error tag.

## Online Boutique Service Map

```
loadgenerator
    │
    ▼
frontend ─── adservice
    │
    ├── checkoutservice
    │       ├── cartservice ──── redis-cart
    │       ├── productcatalogservice
    │       ├── currencyservice
    │       ├── shippingservice
    │       ├── emailservice
    │       └── paymentservice
    │
    ├── currencyservice
    ├── productcatalogservice
    ├── recommendationservice ──── productcatalogservice
    └── shippingservice
```

### Key Dependency Chains

| Chain | Impact if Broken |
|-------|-----------------|
| `frontend → checkoutservice → cartservice → redis-cart` | Checkout fails |
| `frontend → productcatalogservice` | Product pages fail |
| `frontend → currencyservice` | Price display fails |
| `frontend → recommendationservice → productcatalogservice` | Recommendations fail |

### Expected Latency Ranges (Healthy)

| Service | Typical p99 | Alarm Threshold |
|---------|-------------|-----------------|
| frontend | 200-500ms | >2s |
| checkoutservice | 100-300ms | >1.5s |
| cartservice | 10-50ms | >500ms |
| redis-cart | 1-5ms | >100ms |
| productcatalogservice | 5-20ms | >200ms |
| currencyservice | 5-15ms | >200ms |

## Cascading Failure Analysis Checklist

1. **Identify the alert service** — which service triggered the alert?
2. **Map dependencies** — `get_service_dependencies()` to see the call graph
3. **Find slow/error traces** — `query_traces()` or `find_error_traces()`
4. **Drill into the trace** — `get_trace_detail()` for the span tree
5. **Find the deepest error/slowest span** — that's the likely root cause
6. **Verify with metrics** — does the suspected root cause service show anomalies in CloudWatch/Prometheus?
7. **Check resource state** — use `run_kubectl` to check pods, resources, events for the root cause service
8. **Determine fix** — fix the root cause service, not the alerting service
