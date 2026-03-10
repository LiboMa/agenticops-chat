# Deep Research: HolmesGPT & Keep — Lessons for AgenticOps

> Date: 2026-03-01 | Scope: Architecture, features, integration patterns

---

## 1. Project Profiles

| Dimension | HolmesGPT | Keep | AgenticOps |
|-----------|-----------|------|------------|
| **Focus** | LLM-powered RCA for K8s/infra | AIOps alert management platform | AI ops assistant (multi-agent) |
| **Stars** | ~1.9K | ~8.5K | Private |
| **Codebase** | ~39K LOC Python | ~200K+ LOC (Python + TypeScript) | ~25K LOC (Python + TypeScript) |
| **LLM usage** | Core — agentic loop with tool calling | Ancillary — summarization, correlation | Core — multi-agent orchestration |
| **Strengths** | Deep K8s RCA, runbook catalog, tool approval | 130+ integrations, alert pipeline, workflow engine | Multi-agent routing, graph topology, skills system |

---

## 2. Architecture Patterns Worth Adopting

### 2.1 HolmesGPT: YAML-Defined Toolsets with Jinja2 Templating

HolmesGPT defines tools entirely in YAML with Jinja2 command templates — no Python code needed for CLI wrappers:

```yaml
# plugins/toolsets/kubernetes/core.yaml
tools:
  - name: "kubectl_describe"
    command: "kubectl describe {{ kind }} {{ name }}{% if namespace %} -n {{ namespace }}{% endif %}"
    transformers:
      - name: llm_summarize
        config:
          input_threshold: 1000
          prompt: "Summarize focusing on errors, warnings, non-standard states..."
```

Key innovation: each tool can declare **transformers** — when output exceeds threshold, a cheap/fast model (e.g. gpt-4o-mini) summarizes it *before* it enters the main agent's context window. This is per-tool, pre-insertion compression.

**Relevance to AgenticOps**: Our Skills system (V1.1) does dynamic tool registration via `activate_skill()`, but tool definitions still require Python `@tool` functions. We could adopt:
- **YAML-defined command tools** for simple CLI wrappers (kubectl, aws cli) — no Python needed
- **Per-tool output transformers** — LLM-summarize large outputs before context insertion (better than our flat `_truncate()` at 4000 chars)
- **Toolset grouping** for the `tools/` directory (group aws_cli_tool, metadata_tools, graph_tools into named sets)

### 2.2 HolmesGPT: Three-Tier Context Window Management

HolmesGPT has the most sophisticated context management we've seen. Three tiers:

**Tier 1 — Tool Output Transformers** (pre-insertion):
Per-tool `llm_summarize` transformer compresses large outputs using a fast/cheap model *before* they enter the conversation. Declarative in YAML (see 2.1 above).

**Tier 2 — Conversation History Compaction** (`core/truncation/compaction.py`):
When conversation approaches context limit (configurable % threshold), the LLM itself summarizes the entire history. Preserves: system prompt + last user prompt + compacted summary. This is semantic compression, not just dropping old messages.

**Tier 3 — Fair-Allocation Tool Truncation** (`core/truncation/input_context_window_limiter.py`):
After compaction, if still over limit: sort tool messages by size, allocate equal shares, small tools keep full output, large tools get truncated proportionally. Extra-large results get saved to filesystem — agent gets a file path + preview and can `cat`/`grep` as needed.

Additional safeguards (`safeguards.py`):
- Repeated identical tool call detection (same tool + same params = blocked)
- Redundant filtered log queries (if unfiltered returned nothing, filtered won't either)
- On the LAST iteration of the agent loop, tools are set to `None` to force a text response (prevents infinite loops)

**Relevance to AgenticOps**: We use `SlidingWindowConversationManager(window_size=40)` which drops old messages, plus flat `_truncate()` at 4000 chars. HolmesGPT's approach is far more sophisticated. Consider:
- **LLM-based conversation compaction** via Strands SDK hooks (summarize before sliding window drops)
- **Per-tool output summarization** using a cheap model (haiku) before context insertion
- **Repeated tool call detection** — `BeforeToolCall` hook checking call signature cache
- **Fair-allocation truncation** — proportional size limits instead of flat cutoff

### 2.3 Keep: Provider Factory with Auto-Discovery

Keep's most innovative pattern — 130+ integrations with **zero framework code changes** to add a new one:

```python
class BaseProvider(metaclass=abc.ABCMeta):
    PROVIDER_SCOPES: list[ProviderScope] = []      # Required permissions
    PROVIDER_METHODS: list[ProviderMethod] = []     # Callable methods
    FINGERPRINT_FIELDS: list[str] = []              # Fields for alert dedup
    PROVIDER_CATEGORY: list[str]                    # "Monitoring", "Incident Management", ...
    PROVIDER_TAGS: list[str]                        # "alert", "ticketing", "messaging", ...

    def validate_config(self): ...
    def _get_alerts(self) -> list[AlertDto]: ...
    def _notify(self, **kwargs): ...
    def _query(self, **kwargs): ...

class BaseTopologyProvider(BaseProvider):            # Adds pull_topology()
class BaseIncidentProvider(BaseProvider):            # Adds _get_incidents()

# Factory auto-discovers providers by walking providers/ directory
class ProvidersFactory:
    # Uses inspect.signature() to extract method params
    # Detects capabilities via __dict__.get() checks
    # Generates UI config forms from dataclass field metadata
    # Caches to providers_cache.json
```

**Key design**: Class-level declarations (`PROVIDER_SCOPES`, `FINGERPRINT_FIELDS`, `PROVIDER_TAGS`) drive the entire UI, deduplication behavior, and capability detection. Auth config uses Python dataclass field metadata for auto-generated forms.

**Relevance to AgenticOps**: Our HealthPatrol pipeline could adopt this for multi-source alert ingestion. Concrete path:
1. Define `BaseAlertProvider` with `get_alerts()`, `FINGERPRINT_FIELDS`, `validate_config()`
2. Implement: CloudWatchProvider, PrometheusProvider, DatadogProvider, PagerDutyProvider
3. Factory auto-discovers from `providers/` directory
4. HealthPatrol webhook routes to provider-specific parsers

### 2.4 Keep: CEL-to-SQL Compilation

Keep uses Common Expression Language (CEL) for alert querying, compiled to SQL at runtime:

```
severity == "critical" && source == "prometheus" && lastReceived > "1h"
→ SELECT * FROM alerts WHERE severity='critical' AND source='prometheus' AND last_received > now()-interval '1h'
```

**Relevance to AgenticOps**: Our agents query the DB via metadata_tools (Python functions). For power users and the web UI, a CEL or filter DSL would enable flexible querying without writing Python. Lower priority but elegant pattern.

---

## 3. Feature Gap Analysis

### 3.1 Alert Deduplication Pipeline (Keep — HIGH PRIORITY)

Keep has a production-grade multi-stage alert pipeline (`alert_deduplicator.py`):

```
Ingest → Fingerprint → Deduplicate → Extract → Map → Enrich → Route → Correlate
```

- **Fingerprinting**: SHA-256 of provider-defined fields (e.g., Datadog uses `monitor_id + host`). Per-provider `FINGERPRINT_FIELDS` class attribute.
- **Full vs Partial dedup**: Full = exact hash match (same alert, same values). Partial = same fingerprint, different hash (same alert, changed values → update existing).
- **Ignore fields**: Configurable fields excluded from hash (e.g., `lastReceived` always changes)
- **Statistics**: Dedup events tracked per rule per hour for dashboards
- **Three-stage enrichment**:
  1. Extraction rules — regex field extraction from alert payload
  2. Mapping rules — CSV or topology-based enrichment
  3. Workflow enrichment — action-triggered enrichment with audit trail
- **`Extra.allow` on AlertDto** — accepts ANY provider-specific fields, preserving full payload

**Gap in AgenticOps**: Our HealthPatrol pipeline goes `Ingest → Detect → RCA → Fix` but lacks deduplication. 50 identical CloudWatch alarms = 50 HealthIssues. Need:
- Fingerprint field on HealthIssue model (SHA-256 of key identifying fields)
- Dedup check in `save_health_issue()` — same fingerprint within window → increment count, update timestamps
- Configurable dedup window per source (e.g., 5 min for CloudWatch, 10 min for Prometheus)
- `enriched_fields` tracking — which fields were added post-ingestion

### 3.2 3-Tier Tool Approval Framework (HolmesGPT — MEDIUM PRIORITY)

HolmesGPT classifies tools into three tiers:

| Tier | Description | Behavior |
|------|-------------|----------|
| `unrestricted` | Read-only queries | Always allowed |
| `restricted` | Write operations | Allowed with logging |
| `approval_required` | Destructive ops | Pauses for human approval |

**Gap in AgenticOps**: Our `security.py` has three tiers (readonly/write/blocked) but enforcement is limited to the Skills execution tools. HolmesGPT applies it to *all* tools uniformly. We should:
- Extend the security classification to aws_cli_tool and metadata_tools
- Wire into Strands SDK `BeforeToolCall` hook for centralized enforcement
- Use `InterruptException` for approval_required tier (native SDK support)

### 3.3 Incident State Machine (Keep — MEDIUM PRIORITY)

Keep has a formal incident lifecycle with rich metadata:

```
FIRING → ACKNOWLEDGED → RESOLVED
         ↓ (merge)
         MERGED
```

Key features:
- **Incident types**: `MANUAL`, `AI`, `RULE`, `TOPOLOGY` — tracking how each was created
- **AI-generated names/summaries**: `ai_generated_name`, `generated_summary` fields
- **Merge/split**: `merged_into_incident_id`, `merged_by`, `merged_at` with full provenance
- **Same-incident-in-the-past**: `same_incident_in_the_past_id` — similar incident detection
- **Running numbers**: Auto-incrementing per-tenant (INC-1, INC-2, ...)
- **Resolve strategies** (`ResolveOn`): ALL alerts must resolve, or FIRST/LAST alert resolving triggers resolution
- **Affected services**: Auto-populated from alert `service` fields via topology

**Gap in AgenticOps**: Our HealthIssue state machine has 9 states but lacks:
- **Acknowledgment tracking** (who acked, when)
- **SLA timers** (time-to-ack, time-to-resolve)
- **Alert grouping** (multiple alerts → one incident)
- **Merge capability** (duplicate incidents → merge into one)
- **Similar-incident-in-past linking** (for knowledge reuse)

### 3.4 Runbook-Gated Tool Access (HolmesGPT — MEDIUM PRIORITY)

HolmesGPT's most elegant pattern: **restricted/dangerous tools are hidden until a runbook is activated**.

The `fetch_runbook` tool loads a markdown runbook. When it succeeds, `_runbook_in_use = True` triggers a tool list refresh — unlocking write-capable tools that were previously hidden. This ensures the LLM follows approved procedures before getting dangerous capabilities.

Runbook content is wrapped in `<runbook>` XML tags with instructions: "these are DIRECTIONS not ACTUAL RESULTS. Follow the steps using TOOLS." The LLM reports execution as a checklist:
```
1. ✅ *Check pod memory usage* — 87% allocated
2. ❌ *Could not analyze process mailbox sizes* — Observer not enabled
```

**Gap in AgenticOps**: Our `activate_skill()` already unlocks dynamic tools — same pattern! But we don't gate write tools behind skill activation. Consider:
- Executor agent: hide `run_on_host`/`run_kubectl` until a relevant skill is activated
- Alert-to-skill mapping: CloudWatch alarm type → auto-suggest relevant skill
- Investigation checklists in SKILL.md decision trees (partially there already)

### 3.5 Workflow Engine (Keep — LOW PRIORITY for now)

Keep has a YAML-based workflow engine:

```yaml
workflow:
  triggers:
    - type: alert
      filters:
        - key: severity
          value: critical
  steps:
    - name: enrich-with-topology
      provider: topology
    - name: create-ticket
      provider: jira
      if: "{{ alert.source == 'prometheus' }}"
  actions:
    - name: notify-oncall
      provider: slack
```

**Gap in AgenticOps**: Our auto-fix pipeline is code-driven (`pipeline_service.py`). A declarative workflow engine would let users define custom automation without Python. However, our current pipeline covers the primary use case well. Defer unless users request custom workflows.

---

## 4. AI/LLM Usage Comparison

| Pattern | HolmesGPT | Keep | AgenticOps |
|---------|-----------|------|------------|
| **Agentic loop** | Custom ReAct loop, parallel tool exec (16 workers) | No — single-shot OpenAI calls | Strands SDK agents (sequential tools) |
| **Multi-agent** | No — single `ToolCallingLLM` class | No | Yes — 7 specialized agents |
| **LLM provider** | LiteLLM (any provider) | OpenAI only (hardcoded) | AWS Bedrock (via Strands SDK) |
| **Context management** | 3-tier: transform → compact → truncate | N/A | Sliding window (reactive, 40 turns) |
| **Fast model** | Yes — cheap model for tool output summarization | N/A | No — same model for everything |
| **Tool definition** | YAML + Jinja2 (declarative) | N/A | Python `@tool` functions (imperative) |
| **Output control** | Jinja2 system prompt + structured JSON output | N/A | 3-level detail (concise/medium/detailed) |
| **Early stopping** | Repeated call detection + last-iteration tool=None | N/A | Not implemented |
| **Streaming** | SSE via FastAPI (6 event types) | N/A | SSE via FastAPI (5 event types) |
| **AI for correlation** | N/A | Incident clustering with human-in-the-loop + feedback | N/A |

**Key takeaways**:
- HolmesGPT's single-agent with **parallel tool execution** (ThreadPoolExecutor, 16 workers) is faster for investigations. Our agents execute tools sequentially.
- HolmesGPT's **fast model** pattern (cheap model for tool output summarization) is cost-effective. We use the same expensive model for everything.
- Keep's **human-in-the-loop AI** for incident clustering (suggest → review → commit → feedback) is a mature pattern we lack.
- HolmesGPT's **structured output** with 7 investigation sections + fallback to markdown parsing is more robust than our free-form agent responses.

---

## 5. Integration Patterns

### 5.1 MCP Integration (HolmesGPT)

HolmesGPT has first-class MCP support with 3 connection modes (SSE, Streamable HTTP, Stdio) and pre-built add-ons deployed as Helm sidecars:

| MCP Add-on | Purpose |
|------------|---------|
| AWS | AWS API access via IRSA |
| Azure | Azure API access |
| GCP | GCP API access |
| GitHub | Repository/issue access |
| Confluence | Documentation search |
| K8s Remediation | Write operations (separate from read) |
| MariaDB / Sentry / Prefect | Domain-specific access |

Each add-on has its own deployment + NetworkPolicy. Headers support Jinja2 templating for auth passthrough:
```yaml
extra_headers:
  Authorization: "{{ request_context.headers['Authorization'] }}"
  X-Api-Key: "{{ env.CORALOGIX_API_KEY }}"
```

**Relevance**: Strands SDK has native MCP support. We could:
1. **Consume MCP servers** — replace some Python tool implementations with standard MCP servers (AWS, GitHub)
2. **Expose AgenticOps as MCP server** — let other AI tools use our scan/detect/graph capabilities
3. **Auth passthrough** — Jinja2 header templating for multi-tenant scenarios

### 5.2 Webhook-Based Alert Ingestion (Keep)

Keep accepts alerts via webhooks with provider-specific parsers:

```
POST /alerts/event/{provider_type}
Content-Type: application/json
{provider-specific payload}
```

**Relevance**: Our HealthPatrol already has `POST /api/alerts/ingest` webhook endpoints. Keep's pattern of provider-specific parsers is more extensible — each provider type gets its own payload normalizer. Consider adding provider-type routing to our ingest endpoint.

---

## 6. Prioritized Recommendations

### Tier 1 — High Impact, Moderate Effort

| # | Recommendation | Source | Effort | Impact |
|---|---------------|--------|--------|--------|
| 1 | **Alert deduplication pipeline** — fingerprint-based dedup on HealthIssue creation with per-source configurable windows, full/partial dedup detection, occurrence counting | Keep | 2-3 days | Prevents alert storms from creating duplicate issues |
| 2 | **Fast-model tool output summarization** — use cheap model (Haiku) to compress large tool outputs before context insertion, declared per-tool | HolmesGPT | 2-3 days | Better context utilization, preserves semantic info vs char truncation |
| 3 | **Repeated tool call detection + early stopping** — `BeforeToolCall` hook checking call signature cache, last-iteration force-text-response | HolmesGPT | 1 day | Saves tokens, prevents infinite agent loops |
| 4 | **Conversation compaction** — LLM-based history summarization before sliding window drops messages | HolmesGPT | 2 days | Preserves investigation context across long sessions |

### Tier 2 — Medium Impact, Medium Effort

| # | Recommendation | Source | Effort | Impact |
|---|---------------|--------|--------|--------|
| 5 | **Centralized tool security via hooks** — `BeforeToolCall` hook enforcing 3-tier approval across ALL tools (not just skills) | HolmesGPT | 2-3 days | Uniform security policy, audit trail for free |
| 6 | **Provider abstraction for alert sources** — `BaseAlertProvider` with auto-discovery, `FINGERPRINT_FIELDS`, capability flags | Keep | 3-5 days | Multi-source alert ingestion (CloudWatch + Prometheus + Datadog) |
| 7 | **Incident grouping with merge/split** — Incident model wrapping multiple HealthIssues, AI-suggested clustering with human-in-the-loop | Keep | 3-4 days | Reduces noise, better incident management |
| 8 | **Runbook-gated tool access** — hide write tools until relevant skill/runbook is activated | HolmesGPT | 1-2 days | Safer executor, approved procedures before dangerous capabilities |
| 9 | **MCP integration** — consume external MCP servers (AWS, GitHub) + expose AgenticOps as MCP server | HolmesGPT | 3-4 days | Extensibility, interop with other AI tools |

### Tier 3 — Nice to Have, Larger Effort

| # | Recommendation | Source | Effort | Impact |
|---|---------------|--------|--------|--------|
| 10 | **YAML-defined command tools** — declarative tool definitions with Jinja2 templates for CLI wrappers | HolmesGPT | 3-4 days | Faster tool authoring, no Python needed for simple wrappers |
| 11 | **Alert-to-skill mapping** — auto-activate relevant skills based on alert type/source | HolmesGPT | 2 days | Faster RCA, less LLM guessing |
| 12 | **SLA tracking** — time-to-ack, time-to-resolve, running incident numbers (INC-1, INC-2) | Keep | 2-3 days | Operational metrics, reporting |
| 13 | **CEL/DSL query language** — user-facing filter expressions compiled to SQLAlchemy | Keep | 5-7 days | Power user querying |
| 14 | **Declarative workflow engine** — YAML-based automation with triggers, steps, actions, conditionals | Keep | 1-2 weeks | Custom automation without code |
| 15 | **Enrichment audit trail** — track what was enriched, by whom, with TTL metadata (`enriched_fields` list) | Keep | 2-3 days | Traceability |

---

## 7. Patterns We Already Do Better

| Area | AgenticOps Advantage |
|------|---------------------|
| **Multi-agent orchestration** | 7 specialized agents vs single-agent (HolmesGPT) or no agents (Keep) |
| **Graph topology + SRE algorithms** | SPOF detection, dependency chains, capacity risk — neither has this |
| **Skills system** | Progressive disclosure, dynamic tool loading, domain knowledge packages |
| **Fix execution pipeline** | End-to-end RCA → Fix → Verify → Resolve with approval gates |
| **Output detail control** | 3-level (concise/medium/detailed) — neither has this |
| **Infrastructure graph** | NetworkX-based topology with 20+ node types and SRE algorithms |

---

## 8. Summary

HolmesGPT and Keep address different slices of the AIOps problem:

- **HolmesGPT** (~39K LOC) excels at LLM-driven investigation with the most sophisticated context window management we've seen (3-tier: transform → compact → truncate), YAML-defined tools with Jinja2 templating, runbook-gated tool access, and MCP-first extensibility. Its single-agent architecture is simpler but less scalable than our multi-agent approach. It has **no database, no fix execution, no graph analysis**.

- **Keep** (~200K+ LOC) excels at alert lifecycle management with 130+ provider integrations via auto-discovery factory, production-grade alert deduplication, three-stage enrichment pipeline, incident merge/split, YAML workflow engine, CEL-to-SQL query compilation, and topology-driven incident correlation. It has **no autonomous agents, no RCA, no remediation**.

**AgenticOps sits at the intersection** — we have the multi-agent intelligence (7 specialized agents) with broader operational scope than either. Our graph topology + SRE algorithms (SPOF, dependency chains, capacity risk), skills system, and end-to-end fix execution pipeline are unique differentiators.

**Top 4 highest-value improvements:**

1. **Alert deduplication** (from Keep) — fingerprint-based dedup to prevent alert storms creating duplicate HealthIssues
2. **Fast-model tool output summarization** (from HolmesGPT) — use Haiku to compress large tool outputs before context insertion
3. **Conversation compaction** (from HolmesGPT) — LLM-based history summarization instead of blind sliding window
4. **Centralized security hooks** (from HolmesGPT) — `BeforeToolCall` hook for uniform 3-tier tool approval + audit trail
