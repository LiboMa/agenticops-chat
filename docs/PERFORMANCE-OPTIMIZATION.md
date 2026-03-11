# AgenticOps — Performance Optimization Report

> Date: 2026-03-11 | Status: Phase 1 shipped, Phase 2-4 planned

## What Was Done (Phase 1)

### 1. Bedrock Prompt Caching — Enabled

All 7 agents now use Strands SDK native prompt caching:

```python
from strands.models.model import CacheConfig

BedrockModel(
    ...,
    cache_config=CacheConfig(strategy="auto"),  # cache system+tools+history prefix
    cache_tools="default",                       # cache tool definitions
)
```

**How it works:**
- First request: Bedrock caches system prompt + tools + conversation prefix (1.25x write cost)
- Subsequent requests: prefix match reads from cache (0.1x read cost, ~85% TTFT reduction)
- TTL: 5 minutes (Bedrock default), auto-refreshed by frequent calls
- Minimum prefix: 2048 tokens (all agents exceed this — smallest is Reporter at ~3,416 tokens)

**Config toggle:** `AIOPS_BEDROCK_CACHE_ENABLED=false` to disable (default: true)

**Files changed:**
| File | Change |
|------|--------|
| `config.py` | Added `bedrock_cache_enabled` setting |
| `main_agent.py` | Added cache_config + cache_tools |
| `scan_agent.py` | Added cache_config + cache_tools |
| `detect_agent.py` | Added cache_config + cache_tools |
| `rca_agent.py` | Added cache_config + cache_tools |
| `sre_agent.py` | Added cache_config + cache_tools |
| `executor_agent.py` | Added cache_config + cache_tools |
| `reporter_agent.py` | Added cache_config + cache_tools |

### 2. Model ID Bug Fix

Scan, detect, and reporter agents referenced `settings.bedrock_model_id_sonnet` which was **undefined** in config.py. Fixed to use `settings.bedrock_model_id_cheap` (Haiku 4.5) as intended by the tiered model design.

### 3. Static Prefix Token Estimates

| Agent | System Prompt | Tools | Skills XML | Total Prefix | Model |
|-------|--------------|-------|------------|-------------|-------|
| Main | ~1,942 | ~3,600 | ~574 | **~6,116** | Opus 4.6 |
| Scan | ~784 | ~3,150 | 0 | **~3,934** | Haiku 4.5 |
| Detect | ~1,583 | ~3,000 | 0 | **~4,583** | Haiku 4.5 |
| RCA | ~2,007 | ~5,400 | ~574 | **~7,981** | Opus 4.6 |
| SRE | ~2,402 | ~5,700 | ~574 | **~8,676** | Opus 4.6 |
| Executor | ~1,259 | ~3,450 | ~574 | **~5,283** | Opus 4.6 |
| Reporter | ~892 | ~1,950 | ~574 | **~3,416** | Haiku 4.5 |

### 4. Cost Impact (estimated at 100 conversations/day, 90% cache hit)

| Metric | Before | After | Savings |
|--------|--------|-------|---------|
| Input cost (static prefix) | $79.73/day | $17.31/day | **$62.42/day** |
| TTFT (Opus, 6K prefix) | 300-500ms | 50-80ms | **~85%** |
| TTFT (Haiku, 4K prefix) | 100-200ms | 20-40ms | **~80%** |
| "check health" total | 4-7s | 3-5s | **-30%** |
| "fix issue" full chain | 30-55s | 26-47s | **-15%** |
| Annualized saving | — | — | **~$22,783** |

### 5. Verification

```python
# After a chat interaction, check cache metrics:
result = agent("hello")
usage = result.metrics.latest_agent_invocation.usage
print(usage.get("cacheWriteInputTokens"))  # First call: > 0
# Second call:
print(usage.get("cacheReadInputTokens"))   # Should be > 0 (cache hit)
```

---

## Planned (Phase 2-4)

### Phase 2: Response Time Optimization

| Item | Description | Expected Impact |
|------|-------------|-----------------|
| **Sub-agent instance caching** | Cache Agent instances per (agent_type, account_id) with TTL=30m instead of recreating each call | -0.1~0.3s per sub-agent call |
| **CLI streaming** | Switch `cli/main.py` from sync `agent()` to `agent.stream_async()` for real-time token output | Perceived latency 30s → <2s |
| **Main agent max_tokens=4096** | Router+summarizer doesn't need 16K output tokens | ~5-10% inference speedup |
| **Retry strategy** | Custom `ModelRetryStrategy(max_attempts=4, initial_delay=2, max_delay=30)` | Throttle recovery 4s → 2s |

### Phase 3: Backend + Frontend

| Item | Location | Expected Impact |
|------|----------|-----------------|
| **N+1 query fix** | `app.py` session list endpoint | 51 queries → 1 (JOIN + GROUP BY) |
| **Message pagination** | `app.py` session detail + `useChatSession.ts` | Large session load -80% |
| **Scroll throttle** | `MessageList.tsx` | CPU -50% during streaming |
| **SummarizingConversationManager** | Main + RCA agents | Long conversations preserve context via Haiku summaries |

### Phase 4: Deep Optimization (as needed)

- Frontend virtual scrolling (`@tanstack/react-virtual`)
- I#/R# reference LRU cache (preprocessor.py)
- SSM async execution (`asyncio.to_thread()`)
- Vector search indexing (sqlite-vss / pgvector ivfflat)
