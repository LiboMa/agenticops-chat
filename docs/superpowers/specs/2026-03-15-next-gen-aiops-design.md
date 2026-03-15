# Next-Gen AgenticOps Design

> **Date**: 2026-03-15 | **Status**: Draft | **Version**: v3 (final)

---

## 0. Product Identity

**AgenticOps is an intelligent platform that uses existing tools, accumulates operational experience, autonomously takes over operations, self-repairs, and self-iterates.**

It is NOT a monitoring tool, NOT a data platform, NOT a script executor.

```
Uses platforms     -> consumes existing monitoring/APM/log systems, builds nothing
Uses tools         -> Connectors + Skills + LLM writes its own queries
Accumulates exp    -> KB (second brain) + System Prompt self-evolution
Maintains exp      -> Human review for Ground Truth, experience improves over time
Autonomous takeover -> receives tasks via IM/webhook, decides what to query and how to fix
Self-repairs       -> RCA -> Fix -> Execute closed loop
Self-iterates      -> every resolved issue makes the Agent smarter
```

Like a real SRE: gets alerts via Slack, opens Datadog/Prometheus/CloudTrail to investigate, figures out root cause, fixes it, writes a post-mortem. Except this SRE never sleeps, never forgets, and gets better with every incident.

---

## 1. Problem Statement

AgenticOps 1.0.0 has a validated RCA -> Fix -> Execute closed loop (10/10 EKS scenarios). Three structural gaps remain:

1. **No service awareness** -- sees resources, not services. Limits blast radius analysis and RCA accuracy.
2. **No change correlation** -- doesn't automatically answer "what changed recently?" during RCA.
3. **Self-referential knowledge** -- Agent scores itself, writes its own KB cases, references its own cases. No Ground Truth. No learning from mistakes.

And one foundational gap the v1 spec missed:

4. **Static Agent intelligence** -- System Prompt never changes. An Agent that solved 1000 incidents reasons identically to one that solved 0. No wisdom accumulation at the prompt level.

---

## 2. Architecture

```
+-----------------------------------------------------------+
|                 Agent Cognitive System                      |
|                                                            |
|  System Prompt (self-evolving)                             |
|    Base role + Wisdom Roadmap (auto-updated from exp)      |
|    "For X-type issues, optimal path is A->B->C"           |
|    "Y approach failed last time, try Z first"             |
|                                                            |
|  Knowledge Base (second brain, only persistent store)      |
|    Verified cases + Service model + SOPs + Human feedback  |
|                                                            |
|  Skills (domain frameworks, scaffolding)                   |
|    Gradually internalized as KB accumulates                |
|                                                            |
|  LLM (reasoning engine)                                   |
|    Writes queries, analyzes data, makes judgments          |
|                                                            |
+-----------------------------------------------------------+
|                 Agent Action Capabilities                   |
|                                                            |
|  Connectors (credentials + endpoints)                      |
|    Admin configures system access: Datadog, Prometheus,    |
|    CloudWatch, ELK, CloudTrail, K8s, AWS CLI, SSH, ...    |
|    Agent decides what to query, when, and how              |
|    No predefined query templates -- Agent explores freely  |
|                                                            |
|  Tools (execution)                                         |
|    AWS CLI, kubectl, SSH, API calls, Code Interpreter      |
|    Agent writes its own commands and queries               |
|                                                            |
+-----------------------------------------------------------+
|                 Message Intake                              |
|                                                            |
|  IM Channel (Slack/Feishu) + Webhook + CLI + Web           |
|                                                            |
+-----------------------------------------------------------+
|                 Learning Loop                               |
|                                                            |
|  Human review -> feedback -> KB update ->                  |
|    System Prompt evolution                                 |
|  Every resolved issue = Agent gets smarter                 |
|                                                            |
+-----------------------------------------------------------+
```

### What AgenticOps stores vs. what it does NOT store

```
KB (second brain, vector store) stores:
  - Verified RCA cases (human-reviewed, with Ground Truth tags)
  - SOPs (validated standard procedures)
  - Wisdom Roadmap entries (distilled investigation strategies per issue type)

DB (structured storage, SQLite/PG) stores:
  - HealthIssue, FixPlan, Report (workflow state)
  - ReviewFeedback (review records)
  - Service model (structured: Service, ServiceResource, ServiceDependency tables)
  - Wisdom Roadmap index (pattern -> entry mapping, for retrieval)
  - Confidence calibration data
  - Human feedback records

Note: Service model needs relational queries ("which services share this Redis?",
"what are payment-service's dependencies?"). These are exact-match structural queries,
not semantic search -- vector KB is the wrong tool. Service model lives in DB as
structured tables, queried via SQL. This is still "Agent's memory", just stored
in the appropriate format for the data type.

AgenticOps does NOT store:
  - Metrics (live in CloudWatch/Datadog/Prometheus)
  - Logs (live in CloudWatch Logs/ELK/Datadog)
  - Change events (live in CloudTrail/K8s/CI-CD)
  - Alert history (live in PagerDuty/AlertManager)
  - APM traces (live in Jaeger/X-Ray/Datadog)
  - Any raw data from external systems

Need data? Agent uses Connectors to fetch it on demand.
Done analyzing? Conclusions go to KB. Raw data is discarded.
```

---

## 3. System Prompt Self-Evolution (Wisdom Roadmap)

This is the core differentiator. Every other AIOps tool has static logic. AgenticOps gets smarter with every incident.

### 3.1 Mechanism

After each resolved incident (with human review), the system distills the investigation path into a Wisdom Roadmap entry:

```
Trigger: HealthIssue resolved + ReviewFeedback submitted (verdict: accurate or partial)

Distillation process:
  Input:
    - RCA result (what was the root cause)
    - Investigation path (what did Agent query, in what order)
    - Fix plan (what worked)
    - Human feedback (corrections, additional notes)
    - Time spent (where did Agent waste time)

  Output: Wisdom Roadmap entry
    {
      issue_pattern: "cache_memory_exhaustion"
      service_tier: "critical"
      optimal_investigation_path: [
        "1. Check recent deployments (change correlation - highest signal)",
        "2. Check key patterns and TTL configuration",
        "3. Check connection pool changes",
        "4. Check traffic volume trends"
      ]
      known_pitfalls: [
        "Do NOT restart Redis before checking if shared with other services",
        "Memory spike after deployment usually means missing TTL, not traffic"
      ]
      effective_fix_patterns: [
        "Set TTL on new key patterns",
        "Rollback deployment if TTL fix insufficient"
      ]
      ineffective_approaches: [
        "Scaling Redis memory without fixing root cause (recurs within hours)"
      ]
      confidence: 0.82 (calibrated)
      case_references: ["case-42", "case-67", "case-103"]
      last_updated: "2026-04-15"
    }
```

### 3.2 Issue Pattern Classification

Wisdom Roadmap entries are keyed by `issue_pattern`. Classification mechanism:

```
When a new HealthIssue arrives:
  1. LLM generates a candidate pattern label from the alert content
     (e.g., "Redis memory alert on payment-service" -> "cache_memory_exhaustion")
  2. Embedding similarity search against existing Wisdom entry patterns
     - Match found (cosine > 0.85): reuse existing pattern
     - No match: create new pattern label
  3. Pattern stored on the HealthIssue record for downstream use

Deduplication:
  - Similar patterns flagged during human review
    ("redis_oom" and "cache_memory_exhaustion" look like the same thing?)
  - Human merges -> entries consolidated, references updated
  - LLM-generated labels are free-form but converge via embedding similarity
```

### 3.3 How It Enters the System Prompt

Agent System Prompt is dynamically composed with a **hard token budget**:

```
System Prompt = Base Role Definition (static, ~500 tokens)
              + Service Model context (dynamic, from DB, ~300 tokens)
              + Wisdom Roadmap entries (dynamic, TOP-K relevant, max 2000 tokens)
              + Output Rules based on detail level (dynamic, ~200 tokens)

Total system prompt budget: ~3000 tokens max
```

**Wisdom Roadmap retrieval**: NOT all entries injected. On each RCA invocation:
  1. Classify incoming issue into pattern (Section 3.2)
  2. Retrieve top-5 Wisdom entries by pattern similarity (embedding search)
  3. Truncate to 2000 token budget (typically 3-5 entries)
  4. Entries not retrieved are NOT in the prompt -- they remain in storage for future retrieval

When RCA Agent receives "Redis memory at 95% on payment-service":

```
System Prompt includes:
  "You are an expert SRE agent...  [base role]

   Service context:
   payment-service (critical): ECS x3, Lambda x1, RDS x1, Redis x1 (shared), ALB x1
   Dependencies: auth-service (upstream), order-service (downstream)
   [from DB service model]

   Wisdom for cache_memory_exhaustion issues (3 most relevant entries):
   - Optimal path: check deployments first, then key patterns, then connection pool
   - Known pitfall: do NOT restart Redis before confirming shared resource impact
   - Previously effective: set TTL on new key patterns
   - Previously ineffective: scaling memory without fixing root cause
   [from Wisdom Roadmap, top-K retrieval]"
```

The Agent now starts its investigation with the OPTIMAL path, not a generic exploration.

### 3.3 Evolution Over Time

```
Month 1 (0 resolved issues):
  System Prompt = base role only
  Agent behavior: generic investigation, explores broadly, slow

Month 3 (50 resolved issues):
  System Prompt = base role + 15 Wisdom Roadmap entries
  Agent behavior: knows optimal paths for common issue types
  RCA time: 40% faster for known patterns

Month 6 (200 resolved issues):
  System Prompt = base role + 40 Wisdom Roadmap entries covering most scenarios
  Agent behavior: expert-level for known patterns, still explores for novel issues
  RCA time: 60% faster for known patterns

Month 12+:
  Agent has internalized the equivalent of a senior SRE's years of experience
  Skills become scaffolding that's rarely needed (KB has richer, env-specific knowledge)
  Novel issues are rare; when they occur, the resolution enriches the Wisdom Roadmap
```

### 3.4 Wisdom Roadmap Maintenance

Entries are NOT append-only. They evolve:

- New case confirms existing entry -> confidence UP, case reference added
- New case contradicts entry -> entry flagged for human review
- Human corrects entry -> entry updated, confidence recalculated
- Entry not referenced for 6 months -> marked stale, deprioritized in prompt injection
- Conflicting entries for same pattern -> surfaced to human for resolution

---

## 4. Connectors: Credentials + Endpoints

### 4.1 Design

Admin provides a "notebook" -- credentials and endpoints for each system AgenticOps can access. Agent decides autonomously what to query and when.

```yaml
# config/connectors.yaml (gitignored, admin-managed)
connectors:
  aws:
    role_arn: "arn:aws:iam::123456789:role/aiops-role"
    regions: ["us-east-1", "ap-southeast-1"]

  datadog:
    api_key: "${DATADOG_API_KEY}"
    app_key: "${DATADOG_APP_KEY}"
    site: "datadoghq.com"

  prometheus:
    endpoint: "http://prometheus.monitoring:9090"

  elasticsearch:
    endpoint: "https://es.internal:9200"
    username: "${ES_USER}"
    password: "${ES_PASS}"

  kubernetes:
    kubeconfig: "/path/to/kubeconfig"
    contexts: ["prod-cluster", "staging-cluster"]

  github:
    token: "${GITHUB_TOKEN}"
    repos: ["org/payment-service", "org/order-service"]

  pagerduty:
    api_key: "${PAGERDUTY_API_KEY}"
```

### 4.2 Agent Behavior

Agent does NOT follow predefined query sequences. It reasons about what data it needs:

```
Agent receives: "payment-service Redis memory 95%"

Agent thinks:
  "I need to understand what changed recently and what the memory trend looks like."

  -> Check Wisdom Roadmap: "For cache memory issues, check deployments first"
  -> Uses aws connector: CloudTrail lookup for recent changes to Redis + ECS
  -> Uses kubernetes connector: kubectl rollout history for payment deployments
  -> Uses datadog connector (if configured): Redis memory trend over 24h

  "CloudTrail shows a deployment 30 min ago. Let me check what changed."

  -> Uses github connector: recent commits on payment-service repo
  -> Found: new cache logic without TTL

  "Root cause identified. Now I need to verify blast radius."

  -> Uses KB: payment-service service model shows Redis is shared with order-service
  -> Uses datadog connector: order-service error rate (checking for cascade)

Each step is Agent's autonomous decision. Different incidents = different query paths.
```

### 4.3 No Connector Configured?

Agent works with what it has. No Datadog? Skip APM data, rely on CloudWatch. No GitHub? Skip commit history, rely on CloudTrail. The investigation adapts to available data sources -- just like a real SRE who doesn't have access to every tool.

### 4.4 Guardrails

Agent has broad query access but needs boundaries:

- **Rate limiting**: Max queries per connector per minute (configurable, e.g., Datadog: 30/min). Prevents runaway agents from hammering external APIs.
- **Cost awareness**: Connectors with per-query costs (some APM APIs) can be flagged. Agent informed: "Datadog query costs apply -- use judiciously."
- **Credential scoping**: Connectors are read-only by default. Write access (for fix execution) goes through existing L0-L3 security classification, not through Connectors.
- **Existing AWS integration**: The current AWS auth system (get_active_account, assume_role, run_aws_cli_readonly) becomes the "aws" Connector implementation. Not replaced -- wrapped in the Connector interface for consistency.

---

## 5. Service Model

### 5.1 Structured Storage in DB

Service model requires relational queries ("which services share this Redis?", "what depends on payment-service?"). These are exact-match structural queries -- vector KB is the wrong tool. Service model lives in DB as structured tables.

```
Service (DB table)
  id: int (PK)
  name: str                    # "payment-service"
  tier: "critical" | "standard" | "internal"
  owner: str                   # "fintech-team"
  status: "inferred" | "confirmed"
  notes: text                  # Free-text operational notes
  created_at: datetime
  updated_at: datetime

ServiceResource (DB table, many-to-many)
  id: int (PK)
  service_id: int (FK -> Service)
  resource_id: int (FK -> AWSResource)
  role: str                    # "api" | "datastore" | "cache" | "ingress" | ...
  is_shared: bool              # True if resource belongs to multiple services
  is_primary: bool             # For shared resources: primary owner

ServiceDependency (DB table)
  id: int (PK)
  source_service_id: int (FK -> Service)
  target_service_id: int (FK -> Service)
  type: str                    # "upstream" | "downstream" | "async" | "shared_resource"
  evidence: str                # "datadog_apm" | "sg_rule" | "human"
  status: "inferred" | "confirmed"
```

Example:

```
payment-service (critical, confirmed):
  Resources:
    - ECS: payment-api (x3 tasks, role: api)
    - Lambda: payment-webhook (role: webhook-handler)
    - RDS: pay-master-db (role: primary-datastore)
    - ElastiCache: shared-redis (role: cache, SHARED with order-service)
    - ALB: payment-api-lb (role: ingress)
    - SQS: payment-queue (role: async-queue)
  Dependencies:
    - upstream: auth-service (evidence: Datadog APM)
    - downstream: order-service (evidence: SG rules + API calls)
    - shared: order-service via shared-redis
  Notes:
    - "Redis is shared -- do NOT restart without checking order-service impact"
    - "payment-api deploys via CodePipeline, typically Tuesday/Thursday"
```

Note: operational notes like "do NOT restart Redis before checking impact" are also valuable as Wisdom Roadmap entries (stored in vector KB for semantic retrieval during RCA). The DB stores the structured model; the KB stores the experiential knowledge ABOUT those services.

### 5.2 How Service Model Gets Built

Not through EventBridge daemons or graph databases. Through normal Agent operation:

```
Scenario 1: Admin tells Agent
  Admin: "payment-service consists of these resources: [list]"
  Agent: stores in KB, status=confirmed

Scenario 2: Agent discovers during investigation
  During RCA, Agent queries tags + SG rules + APM
  Agent: "I've identified that pay-redis-01, payment-api ECS, and pay-master-db
          appear to form a service. Should I save this as payment-service?"
  Human: "Yes, also add the Lambda and SQS"
  Agent: stores in KB, status=confirmed

Scenario 3: Agent infers during scan
  Scan Agent notices resources with matching tags/naming patterns
  Agent: proposes service grouping in chat or IM
  Human confirms or corrects -> stored in KB

No background daemons. No event listeners. Normal Agent workflow.
```

### 5.3 Service Model Freshness

Service model in KB may become stale (resources added/removed). Resolution:

- During each RCA, Agent verifies current resource state against KB model
- If mismatch found: Agent updates KB and notes the change
- Periodic scan (existing Schedule system) can trigger service model refresh
- Human can update service model via chat at any time

No TTL mechanics needed. Agent naturally refreshes during normal operation.

---

## 6. Human Review & Ground Truth

### 6.1 Three Review Points

| Review Point | Trigger | Human Action | System Benefit |
|-------------|---------|-------------|----------------|
| **RCA Review** | After RCA completes | Accurate / Partial / Inaccurate + notes | Calibrate confidence, enrich Wisdom Roadmap |
| **Fix Effectiveness** | 24h after execution | Resolved / Mitigated / Unresolved | Validate SOP quality, adjust KB weight |
| **Service Model** | After Agent proposes grouping | Confirm / Correct | Improve service knowledge accuracy |

### 6.2 Review UI

Minimal interaction. One click = one Ground Truth data point.

**RCA Review Card** (Health Issue detail page):

```
+---------------------------------------------------+
|  RCA Review                              I#42      |
|---------------------------------------------------|
|  Agent root cause: "payment-api v24 cache logic    |
|  without TTL caused Redis memory exhaustion"       |
|  Confidence: 0.85 (calibrated: 0.73)               |
|                                                    |
|  [Accurate]  [Partially Accurate]  [Inaccurate]   |
|  Notes: [optional free text]                       |
|  Rating: 1-5 stars                                 |
+---------------------------------------------------+
```

**Fix Effectiveness** (24h after execution, pushed via Schedule):

```
+---------------------------------------------------+
|  Fix Effectiveness                  Fix Plan #7    |
|---------------------------------------------------|
|  Action: Set TTL=3600s for promo:* keys            |
|  24h status: No recurrence                         |
|                                                    |
|  [Resolved]  [Mitigated]  [Not resolved/Recurred] |
+---------------------------------------------------+
```

### 6.3 Feedback Data Model

```
ReviewFeedback
  id: int (PK)
  review_type: str             # "rca" | "fix_effectiveness" | "service_model"
  health_issue_id: int (FK, nullable)
  fix_plan_id: int (FK, nullable)
  rca_result_id: int (FK, nullable)
  verdict: str                 # "accurate" | "partial" | "inaccurate" | "resolved" | "mitigated" | "unresolved"
  rating: int                  # 1-5
  notes: str (nullable)
  corrected_root_cause: str (nullable)
  reviewer: str
  created_at: datetime
```

### 6.4 Feedback -> KB -> Wisdom Roadmap Flow

```
Human submits review
  |
  +-- RCA accurate + fix resolved
  |     -> KB case: verified, weight UP
  |     -> Wisdom Roadmap: reinforce investigation path, confidence UP
  |     -> System Prompt: next similar issue uses this optimal path
  |
  +-- RCA accurate + fix unresolved
  |     -> KB: root cause kept, fix tagged ineffective
  |     -> Wisdom Roadmap: add to ineffective_approaches
  |     -> System Prompt: "this fix didn't work for this pattern"
  |
  +-- RCA inaccurate
  |     -> KB: case tagged rejected, weight = 0
  |     -> If human provides real root cause: new verified case created
  |     -> Wisdom Roadmap: investigation path flagged as misleading
  |     -> Confidence calibration adjusted downward
  |
  +-- Service model correction
        -> KB: service model updated, status = confirmed
```

### 6.5 Confidence Calibration

Simple bin-based, incrementally updated:

```
On each RCA review:
  1. Agent raw confidence -> determine bin (0.9-1.0, 0.7-0.9, 0.5-0.7, <0.5)
  2. Update bin: accuracy = (accurate + partial*0.5) / total
  3. Calibrated confidence = bin accuracy
  4. Segment by issue category once 30+ samples per segment

Display: "Confidence: 0.85 (calibrated: 0.73)"
Calibrated < 0.5 -> auto-flag "human review recommended"
```

### 6.6 Cold Start

```
0-50 reviews:   All results pushed for review. No calibration. Equal KB weight.
50-200 reviews: Global calibration active. Verified cases 2x weight.
200+ reviews:   Segmented calibration. Exception-only review mode.
```

---

## 7. Skills: Scaffolding That Gets Internalized

### 7.1 Repositioned Role

Skills are NOT query template libraries. They are domain decision frameworks that provide scaffolding while KB is still sparse.

```
Skills provide:                    KB eventually provides:
  "For Redis issues, consider       "In OUR environment, Redis issues
   these 5 investigation angles"     are 80% caused by deployments,
                                     check CodePipeline first"

  Generic framework                  Environment-specific wisdom
  (static, may become stale)         (dynamic, always current)
```

As KB accumulates verified cases and Wisdom Roadmap entries, Skills become less critical. The Agent's investigation strategy comes from internalized experience, not external templates.

### 7.2 Skills That Remain Valuable Long-Term

Some Skills provide capabilities, not just knowledge:

- **Execution Skills**: run_on_host (SSH/SSM), run_kubectl -- these are TOOLS, always needed
- **Connector Skills**: how to authenticate and query specific systems -- always needed
- **Security classification**: command risk assessment (L0-L3) -- always needed

These don't get replaced by KB. They're permanent infrastructure.

### 7.3 Skills Self-Evolution Path

```
Month 1: 10 hand-written Skills (current state)
Month 3: KB has 50 verified cases. Agent starts preferring KB over generic Skills.
Month 6: Agent proposes Skill updates based on accumulated experience.
         "The kubernetes-admin Skill says to check node status first for Pod issues.
          But in our environment, 90% of Pod issues are image-related.
          Should I update the investigation priority?"
Month 12: Most generic Skills are superseded by rich, environment-specific KB.
          Only execution/connector/security Skills remain essential.
```

---

## 8. End-to-End Scenario

```
[10:35] Slack #ops-alerts: "FIRING: payment-api HealthCheckFailures"

Agent reads message from IM channel.

REASONING (System Prompt includes Wisdom Roadmap):
  "Cache/service issues: check deployments first (from Wisdom Roadmap)"

INVESTIGATION (Agent decides autonomously):
  -> KB query: payment-service model
     Result: ECS x3, Lambda x1, RDS x1, Redis x1 (shared with order-service), ALB x1
  -> aws connector: CloudTrail recent write events for payment-service resources
     Result: CodePipeline deployed payment-api v24 at 10:30
  -> kubernetes connector: kubectl rollout history
     Result: confirms v24 deployment
  -> datadog connector: Redis memory trend
     Result: memory spike started exactly at 10:30

  "Root cause clear: v24 deployment. Let me check what changed in the code."

  -> github connector: diff for payment-api v23..v24
     Result: new promo cache logic, Redis key prefix promo:*, no TTL set

  "Verified. Now check blast radius."

  -> KB: Redis is shared with order-service
  -> datadog connector: order-service error rate
     Result: 2% error rate (up from 0.1%) -- cascade confirmed

RCA OUTPUT:
  "Root cause: payment-api v24 introduced promo:* cache keys without TTL.
   Redis memory exhausted. Shared with order-service -- cascade impact confirmed.
   Confidence: 0.91 (calibrated: 0.79)
   Fix: Rollback to v23, or set TTL on promo:* keys."

FIX EXECUTION:
  Agent generates fix plan (L1: kubectl + redis-cli) -> auto-approved -> executed -> verified

LEARNING:
  - 24h later: human confirms "Resolved" via review UI
  - KB: case saved as verified, linked to payment-service
  - Wisdom Roadmap: "cache_memory_exhaustion" entry updated
    - "deployment correlation" path reinforced
    - "promo key TTL" added as known pattern
  - System Prompt: next cache issue -> Agent goes straight to deployment check

RESULT:
  Total time: 3 minutes (vs 6 minutes first time this pattern occurred)
  Next time same pattern: ~1.5 minutes (Wisdom Roadmap guides optimal path)
```

---

## 9. Implementation Phases

### Phase 1: Connector Framework + Service Model in KB

- Connector config schema (config/connectors.yaml)
- Base Connector interface (authenticate, query)
- Initial connectors: AWS (existing), K8s (existing), Datadog (new), Prometheus (new)
- Service model as KB entries (not separate DB tables)
- Service discovery via chat (Agent proposes, human confirms)
- RCA/SRE context injection from KB service model

### Phase 2: Human Review Loop + Wisdom Roadmap Foundation

- ReviewFeedback model + DB schema
- RCA Review Card UI (Health Issue detail page)
- Fix Effectiveness Feedback UI (24h push via Schedule)
- KB weight adjustment (verified/rejected/unreviewed)
- Confidence calibration (global, bin-based)
- Wisdom Roadmap entry distillation (from resolved + reviewed cases)
- Dynamic System Prompt composition (base + service context + wisdom entries)

### Phase 3: Wisdom Roadmap Maturation

- Wisdom Roadmap entry evolution (reinforce/contradict/stale)
- Confidence calibration segmentation (by issue category)
- Skills internalization tracking (which Skills are still used vs KB-replaced)
- Agent self-proposed Skill updates
- Exception-only review mode (200+ reviews)

### Phase 4: Advanced Autonomy

- Additional connectors (PagerDuty, Jira, GitHub Actions, ELK, etc.)
- Proactive change risk detection (Agent notices risky changes in IM channel)
- Cross-service incident correlation
- Agent proposes new connectors when it encounters unknown data sources
- Code Interpreter: Agent writes custom queries/scripts for novel scenarios

---

## 10. API Endpoints (New)

| Group | Endpoint | Method | Purpose |
|-------|----------|--------|---------|
| **Connectors** | `/api/connectors` | GET | List configured connectors |
| | `/api/connectors/{name}` | PUT | Add/update connector config |
| | `/api/connectors/{name}/test` | POST | Test connector connectivity |
| **Services** | `/api/services` | GET | List services from KB |
| | `/api/services/{name}` | GET | Service detail (from KB) |
| | `/api/services/{name}/confirm` | PUT | Human confirms/corrects service |
| **Reviews** | `/api/reviews` | POST | Submit review feedback |
| | `/api/reviews/stats` | GET | Review statistics + calibration |
| | `/api/health-issues/{id}/review` | GET | Review status for an issue |
| **Wisdom** | `/api/wisdom` | GET | List Wisdom Roadmap entries |
| | `/api/wisdom/{pattern}` | GET | Wisdom entry for issue pattern |
| **Calibration** | `/api/calibration` | GET | Current calibration table |

---

## 11. Success Metrics

| Metric | Current (1.0) | Target (2.0) | Measurement |
|--------|:------------:|:------------:|-------------|
| RCA accuracy (human-verified) | Unknown | >80% for known patterns | Review feedback |
| RCA time for known patterns | ~2-6 min | <2 min (Wisdom Roadmap) | Pipeline timestamps |
| RCA time for novel patterns | ~6 min | ~4 min (better connectors) | Pipeline timestamps |
| KB verified case ratio | 0% | >50% after 6 months | Review data |
| Confidence calibration error | Unknown | <10% deviation | Calibration vs actuals |
| Wisdom Roadmap coverage | 0 entries | >40 patterns after 6 months | KB count |
| Skills still actively used | 10/10 | <5/10 (rest internalized to KB) | Usage tracking |
| Service model coverage | 0% | >80% of managed resources | KB service entries |

---

*AgenticOps Next-Gen Design v3 -- 2026-03-15*
