# Elasticsearch DSL Query Patterns & Optimization

## Query Types — When to Use What

### Full-Text Search

```json
// match — standard full-text search (analyzed)
{"query": {"match": {"message": "connection timeout error"}}}

// match_phrase — exact phrase in order
{"query": {"match_phrase": {"message": "connection refused"}}}

// multi_match — search across multiple fields
{"query": {"multi_match": {
  "query": "timeout",
  "fields": ["message", "error.description", "log.level"],
  "type": "best_fields"
}}}

// query_string — Lucene syntax (powerful but dangerous with user input)
{"query": {"query_string": {"query": "status:error AND service:payment*"}}}
```

### Exact Match / Filtering

```json
// term — exact keyword match (NOT analyzed, use on keyword fields)
{"query": {"term": {"status.keyword": "error"}}}

// terms — match any of multiple values
{"query": {"terms": {"status.keyword": ["error", "critical"]}}}

// range — numeric/date ranges
{"query": {"range": {"@timestamp": {"gte": "now-1h", "lte": "now"}}}}

// exists — field exists and is not null
{"query": {"exists": {"field": "error.stack_trace"}}}
```

### Compound Queries

```json
// bool — combine multiple conditions
{"query": {"bool": {
  "must": [
    {"match": {"message": "error"}},
    {"range": {"@timestamp": {"gte": "now-1h"}}}
  ],
  "filter": [
    {"term": {"service.keyword": "payment-api"}},
    {"range": {"response_time": {"gte": 5000}}}
  ],
  "must_not": [
    {"term": {"status.keyword": "healthy"}}
  ],
  "should": [
    {"match": {"message": "timeout"}},
    {"match": {"message": "connection refused"}}
  ],
  "minimum_should_match": 1
}}}
```

**Performance note**: Use `filter` context (not `must`) for exact conditions —
filters are cached and don't contribute to relevance scoring.

## Aggregation Patterns

### Metric Aggregations

```json
// Statistics on response time
{"size": 0, "aggs": {
  "response_stats": {"stats": {"field": "response_time"}},
  "p95_latency": {"percentiles": {"field": "response_time", "percents": [50, 95, 99]}},
  "unique_users": {"cardinality": {"field": "user_id.keyword"}}
}}
```

### Bucket Aggregations

```json
// Time-series histogram (for dashboards)
{"size": 0, "aggs": {
  "requests_over_time": {
    "date_histogram": {"field": "@timestamp", "calendar_interval": "5m"},
    "aggs": {
      "avg_latency": {"avg": {"field": "response_time"}},
      "error_count": {"filter": {"term": {"status.keyword": "error"}}}
    }
  }
}}

// Group by field
{"size": 0, "aggs": {
  "by_service": {
    "terms": {"field": "service.keyword", "size": 20},
    "aggs": {
      "error_rate": {
        "filter": {"term": {"status.keyword": "error"}},
        "aggs": {"count": {"value_count": {"field": "_id"}}}
      }
    }
  }
}}
```

### Composite Aggregation (Pagination for Large Results)

```json
// First page
{"size": 0, "aggs": {
  "by_service_and_status": {
    "composite": {
      "size": 100,
      "sources": [
        {"service": {"terms": {"field": "service.keyword"}}},
        {"status": {"terms": {"field": "status.keyword"}}}
      ]
    }
  }
}}

// Next page — use after_key from previous response
{"size": 0, "aggs": {
  "by_service_and_status": {
    "composite": {
      "size": 100,
      "after": {"service": "payment-api", "status": "error"},
      "sources": [
        {"service": {"terms": {"field": "service.keyword"}}},
        {"status": {"terms": {"field": "status.keyword"}}}
      ]
    }
  }
}}
```

## Common Anti-Patterns and Fixes

### 1. Wildcard on Text Fields

**Bad:**
```json
{"query": {"wildcard": {"message": "*timeout*"}}}
```

**Better:** Use `match` or add a `keyword` sub-field:
```json
{"query": {"match": {"message": "timeout"}}}
```

### 2. Leading Wildcards

**Bad:**
```json
{"query": {"wildcard": {"filename.keyword": "*.log"}}}
```

**Better:** Use ngram tokenizer or reverse field:
```json
// At index time, create a reverse field
// Then query: {"wildcard": {"filename.reverse": "gol.*"}}
```

### 3. High-Cardinality Terms Aggregation

**Bad:**
```json
{"aggs": {"all_users": {"terms": {"field": "user_id.keyword", "size": 1000000}}}}
```

**Better:** Use `composite` aggregation with pagination (see above).

### 4. Deep Pagination with from/size

**Bad:**
```json
{"from": 100000, "size": 10, "query": {"match_all": {}}}
```

**Better:** Use `search_after` for deep pagination:
```json
// First request
{"size": 100, "sort": [{"@timestamp": "desc"}, {"_id": "asc"}], "query": {"match_all": {}}}

// Next page — use sort values from last hit
{"size": 100, "sort": [{"@timestamp": "desc"}, {"_id": "asc"}],
 "search_after": ["2026-02-28T10:30:00Z", "doc-id-123"],
 "query": {"match_all": {}}}
```

### 5. Script Fields in Hot Path

**Bad:**
```json
{"script_fields": {"price_usd": {"script": {"source": "doc['price_eur'].value * 1.1"}}}}
```

**Better:** Pre-compute at index time using ingest pipeline:
```json
PUT _ingest/pipeline/convert-price
{"processors": [{"script": {"source": "ctx.price_usd = ctx.price_eur * 1.1"}}]}
```

## SRE-Focused Queries

### Find Error Spikes

```json
{"size": 0, "query": {"range": {"@timestamp": {"gte": "now-1h"}}},
 "aggs": {
   "errors_per_minute": {
     "date_histogram": {"field": "@timestamp", "calendar_interval": "1m"},
     "aggs": {
       "errors": {"filter": {"terms": {"level.keyword": ["ERROR", "FATAL"]}}},
       "error_rate": {
         "bucket_script": {
           "buckets_path": {"errors": "errors._count", "total": "_count"},
           "script": "params.total > 0 ? params.errors / params.total * 100 : 0"
         }
       }
     }
   }
}}
```

### Top Error Messages

```json
{"size": 0,
 "query": {"bool": {
   "filter": [
     {"range": {"@timestamp": {"gte": "now-1h"}}},
     {"terms": {"level.keyword": ["ERROR", "FATAL"]}}
   ]
 }},
 "aggs": {
   "top_errors": {
     "terms": {"field": "error.type.keyword", "size": 20},
     "aggs": {
       "sample": {"top_hits": {"size": 1, "_source": ["message", "stack_trace"]}}
     }
   }
}}
```

### Service Latency Breakdown

```json
{"size": 0,
 "query": {"range": {"@timestamp": {"gte": "now-15m"}}},
 "aggs": {
   "by_service": {
     "terms": {"field": "service.keyword", "size": 50},
     "aggs": {
       "latency_percentiles": {
         "percentiles": {"field": "duration_ms", "percents": [50, 90, 95, 99]}
       },
       "slow_requests": {
         "filter": {"range": {"duration_ms": {"gte": 5000}}},
         "aggs": {"count": {"value_count": {"field": "_id"}}}
       }
     }
   }
}}
```
