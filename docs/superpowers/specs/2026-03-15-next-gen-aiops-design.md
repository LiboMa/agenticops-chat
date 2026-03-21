# Next-Gen AgenticOps Design

> **Date**: 2026-03-15 | **Status**: Draft | **Version**: v4
> **Vision**: [ClawOps Agent-First AIOps Architecture](/Users/malibo/Desktop/Work-AWS/AgenticOps/ClawOps_AgentFirst_AIOps_Architecture.md)
> **Academic Basis**: eARCO (arXiv:2504.11505), OpsAgent (arXiv:2510.24145), AIOpsLab (arXiv:2501.06706), CCAR (arXiv:2603.08736)

---

## 0. Product Identity

**AgenticOps is an intelligent platform that uses existing tools, accumulates operational experience, autonomously takes over operations, self-repairs, and self-iterates.**

It is NOT a monitoring tool, NOT a data platform, NOT a script executor.

Like a real SRE: gets alerts via Slack, opens Datadog/Prometheus/CloudTrail to investigate, figures out root cause, fixes it, writes a post-mortem. Except this SRE never sleeps, never forgets, and gets better with every incident.

---

## 1. Agent-First Framework: Perceive -> Plan -> Act -> Decide -> Verify -> Learn

Aligned with ClawOps vision. No pre-built topology, no static graphs, no data warehousing. Agent investigates on-the-fly using experience + tools.

```
Alert Arrives (via IM Channel / Webhook / CLI)
    |
[PERCEIVE] What do I know?
    * Alert details (source, severity, affected resource)
    * Memory recall: "Have I seen this pattern before?" (KB search)
    * Service context: what service does this resource belong to? (DB query)
    |
[PLAN] What should I investigate?
    * Prompt Optimization: Alert Classifier -> Strategy Selector -> Few-Shot Retriever
    * Wisdom Roadmap: optimal investigation path for this pattern type
    * If novel: LLM generates investigation plan from first principles
    |
[ACT] Execute investigation
    * Uses Connectors to query external systems (CloudWatch, Datadog, CloudTrail, kubectl, ...)
    * Each action produces Evidence with source-weighted confidence
    * Agent decides next step based on findings -- no predefined sequence
    |
[DECIDE] Synthesize RCA
    * Aggregate evidence chain with source weighting
    * Apply confidence scoring (calibrated via human feedback history)
    * Output: RCA + confidence + evidence chain + fix recommendation
    |
[VERIFY] Validate result (dual verification)
    * PostActionValidator: automated T0-T3 observation windows
    * Human Review: accuracy rating + corrections (Ground Truth)
    * Independent self-check: reasoning quality verification
    |
[LEARN] Sediment knowledge
    * Episodic Memory -> Procedural Memory -> Semantic Memory -> Skill
    * Update Wisdom Roadmap investigation strategies
    * Update Skill if gap detected (SkillGapDetector)
    * Penalize wrong knowledge, reinforce correct knowledge
```

### Error Handling

Each phase has defined fallback behavior:

| Phase | Failure | Fallback |
|-------|---------|----------|
| PERCEIVE | Alert classification fails | Use "unknown" category, skip strategy optimization, proceed with first-principles plan |
| PERCEIVE | KB/Memory unavailable | Proceed without historical context (novel investigation) |
| PLAN | No Wisdom match, no similar cases | LLM generates investigation plan from alert context alone |
| ACT | Connector timeout/error | Skip that data source, note gap in evidence, reduce confidence |
| ACT | All connectors fail | Report "insufficient data" with available context, flag for manual investigation |
| DECIDE | Confidence below threshold (<0.3) | Flag for human review, do not auto-execute fix |
| VERIFY | PostActionValidator timeout | Mark UNCERTAIN, push human review |
| LEARN | KB write fails | Log to fallback file, retry on next cycle |

---

## 2. Architecture

```
+-----------------------------------------------------------+
|              Agent Cognitive System                         |
|                                                            |
|  Prompt Optimization Engine (eARCO-inspired)               |
|    Alert Classifier -> Strategy Selector ->                |
|    Few-Shot Retriever -> Prompt Assembler                  |
|                                                            |
|  Four-Layer Memory                                         |
|    Episodic: what happened, when, what we did              |
|    Procedural: how to investigate this type (Wisdom)       |
|    Semantic: generalized patterns (ALB 5xx = target group) |
|    Skill: reusable investigation templates                 |
|                                                            |
|  LLM (reasoning engine)                                   |
|    Writes queries, analyzes data, makes judgments          |
|                                                            |
+-----------------------------------------------------------+
|              Agent Action Capabilities                      |
|                                                            |
|  Connectors (credentials + endpoints)                      |
|    Admin configures access. Agent decides what to query.   |
|    No predefined templates -- Agent explores freely.       |
|                                                            |
|  Tools (execution)                                         |
|    AWS CLI, kubectl, SSH, API calls, Code Interpreter      |
|                                                            |
+-----------------------------------------------------------+
|              Verification Layer                             |
|                                                            |
|  PostActionValidator (automated, T0-T3 windows)            |
|  Human Review (Ground Truth, confidence calibration)       |
|  Self-Verification (independent reasoning quality check)   |
|                                                            |
+-----------------------------------------------------------+
|              Message Intake                                 |
|                                                            |
|  IM Channel (Slack/Feishu) + Webhook + CLI + Web           |
|                                                            |
+-----------------------------------------------------------+
```

### Storage Model

```
Vector KB (second brain) stores:
  - Verified RCA cases (human-reviewed, Ground Truth tagged)
  - SOPs (validated standard procedures)
  - Wisdom Roadmap entries (investigation strategies per pattern)
  - Semantic memory (generalized patterns)

DB (structured storage, SQLite/PG) stores:
  - HealthIssue, FixPlan, Report (workflow state)
  - Service model (Service, ServiceResource, ServiceDependency)
  - ReviewFeedback, CalibrationBin (Ground Truth data)
  - Skill registry (lifecycle state, usage metrics, validation results)
  - Wisdom Roadmap index (pattern classification + retrieval)

AgenticOps does NOT store:
  - Metrics, logs, traces, change events, alert history
  - Any raw data from external systems
  Need data? Connectors fetch on demand. Conclusions go to KB. Raw data discarded.
```

---

## 3. Prompt Optimization Engine

Based on eARCO (Microsoft, arXiv:2504.11505): prompt optimization > RAG > fine-tuning, with 21% accuracy improvement on 180K+ real incidents.

### 3.1 Components

```
+-----------------------------------------+
|       Prompt Optimization Engine         |
+-----------------------------------------+
|                                          |
|  [Alert Classifier]                      |
|    Alert -> Category                     |
|    (cache/network/compute/database/      |
|     security/storage/deployment/...)     |
|                                          |
|  [Strategy Selector]                     |
|    Category -> Best Investigation Plan   |
|    Learned from historical success rate  |
|    Source: Wisdom Roadmap entries         |
|                                          |
|  [Few-Shot Retriever]                    |
|    Category -> Top-K similar past cases  |
|    Via KB vector search (episodic memory)|
|                                          |
|  [Prompt Assembler]                      |
|    Strategy + Few-Shot + Service Context  |
|    + Alert Details -> Optimized Prompt   |
|    Hard budget: 3000 tokens max          |
|                                          |
+-----------------------------------------+
```

### 3.2 Before vs After

```
Before (hand-written prompt, current):
  "You are an AIOps expert. Analyze this alert and find the root cause."
  -> Agent wanders, checks random metrics, slow

After (optimized prompt):
  "ALB 5xx alert on payment-service (critical tier, ECS x3 + Redis + RDS).
   Historical: 85% of similar alerts -> deployment-related.
   Recommended: 1) CloudTrail recent deploys 2) ECS task state 3) Redis connection
   Evidence from 3 similar past incidents attached.
   Shared resources: Redis shared with order-service -- check cascade."
  -> Agent investigates efficiently with direction
```

### 3.3 Alert Classification -> Pattern Matching

```
When a new HealthIssue arrives:
  1. LLM classifies alert into category + generates candidate pattern label
     (e.g., "Redis memory alert" -> category: cache, pattern: cache_memory_exhaustion)
  2. Embedding similarity search against existing Wisdom patterns
     - Match (cosine > 0.85): reuse existing pattern + strategy
     - No match: new pattern, LLM generates investigation plan from first principles
  3. Pattern stored on HealthIssue for downstream retrieval + learning

Deduplication: similar patterns flagged during human review, merged by human.
```

### 3.4 Token Budget

```
System Prompt composition:
  Base Role Definition          ~500 tokens  (static)
  Service Model context         ~300 tokens  (from DB)
  Wisdom / Strategy entries     ~1500 tokens (top-3 relevant, from KB)
  Few-Shot examples             ~500 tokens  (top-1 similar case, from KB)
  Output Rules                  ~200 tokens  (detail level)
  ─────────────────────────────────────
  Total budget:                 ~3000 tokens max

Not all Wisdom entries injected. Top-K retrieval by pattern similarity.

Budget overflow strategy (when assembled prompt exceeds 3000 tokens):
  1. Reduce few-shot to single-paragraph summary (saves ~300 tokens)
  2. Trim wisdom entries by relevance rank (keep top-2 instead of top-3)
  3. Truncate service context to direct dependencies only
  4. Never truncate base role or output rules
```

---

## 4. Four-Layer Memory System

Aligned with ClawOps knowledge sediment architecture. Knowledge evolves from raw to refined:

```
Every RCA produces:
    |
[Episodic Memory] "What happened, when, what we did"
    | (immediate, after each incident)
    v
[Procedural Memory] "How to investigate this type of alert"
    | (after multiple similar incidents -- becomes Wisdom Roadmap entry)
    v
[Semantic Memory] "ALB 5xx is usually caused by target group health failure"
    | (pattern crystallizes across many incidents)
    v
[Skill] Reusable investigation + remediation template
    | (after validation)
    v
[SOP] Formal operational procedure (human-verified)
```

### 4.1 Storage Mapping

| Memory Type | What It Stores | Where | Retrieval |
|------------|---------------|-------|-----------|
| **Episodic** | Individual case records (symptoms, evidence, RCA, fix) | Vector KB | Embedding similarity (alert text) |
| **Procedural** | Investigation strategies per pattern (Wisdom Roadmap) | Vector KB + DB index | Pattern classification -> top-K |
| **Semantic** | Generalized rules ("cache OOM after deploy = usually TTL") | Vector KB | Embedding similarity |
| **Skill** | Reusable templates with lifecycle (see Section 7) | Skills directory + DB registry | Skill matching by category |

### 4.2 Confidence Decay

Knowledge that sits unused decays. Knowledge that gets confirmed strengthens.

```
confidence = base_confidence * 0.99^age_days * (1 + 0.1 * min(recall_count, 10))

- Used often + confirmed: stays high
- Unused for months: slowly decays
- Wrong (human-rejected): actively penalized (base_confidence set to 0)
```

---

## 5. Evidence-Weighted Confidence

Not all evidence is equally trustworthy. Different data sources get different weights:

```
Evidence Source Weights:
  CloudTrail change correlation    0.95  (direct causal: "this was changed 5 min ago")
  APM trace showing error path     0.90  (direct observation)
  Deployment timestamp match       0.85  (strong correlation)
  CloudWatch metric anomaly        0.80  (statistical, could be coincidence)
  Log error pattern match          0.75  (symptomatic, not causal)
  SG/Network rule analysis         0.70  (structural, needs validation)
  KB similar case match            0.50  (analogical, may not apply)
  LLM reasoning without evidence   0.30  (pure inference)

RCA confidence = weighted average of evidence chain
  Each evidence item: {source, weight, finding, relevant: bool}
  Final confidence = sum(weight_i * relevant_i) / sum(weight_i)
  Then calibrated via human feedback bins (Section 8.5)
```

This means: RCA backed by CloudTrail change + deployment match = high confidence. RCA based purely on "similar to past case" = lower confidence, flagged for human review.

---

## 6. Connectors: Credentials + Endpoints

### 6.1 Design

Admin provides credentials and endpoints. Agent decides what to query.

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

### 6.2 Agent Behavior

Agent does NOT follow predefined query sequences. Each step is an autonomous decision:

```
Agent receives alert -> checks Wisdom Roadmap for strategy
  -> uses aws connector: CloudTrail for recent changes
  -> uses datadog connector: metric trends
  -> uses github connector: recent commits
  -> each finding shapes the next query
  Different incidents = different query paths
```

No connector configured? Agent works with what it has. Adapts to available data sources.

### 6.3 Guardrails

- **Rate limiting**: configurable per connector (e.g., Datadog: 30/min)
- **Cost awareness**: connectors with per-query costs flagged to Agent
- **Credential scoping**: connectors are read-only by default. Write operations (rollback PR, PagerDuty ack) go through the existing executor agent with L0-L3 classification. Connector-based write operations are out of scope until Phase 4.
- **Existing AWS integration**: current get_active_account / assume_role / run_aws_cli_readonly becomes the "aws" connector implementation -- wrapped, not replaced.
- **Connectors vs cloud_accounts**: `config/connectors.yaml` manages external system credentials (Datadog, Prometheus, ELK, etc.). The existing `cloud_accounts` DB table manages cloud provider accounts. The "aws" connector bridges between them -- reads active account from cloud_accounts, exposes as connector interface.

---

## 7. Self-Evolving Skills Lifecycle

Aligned with ClawOps SkillGapDetector + SOPAutoWriter + OpsAgent dual self-evolution.

### 7.1 Lifecycle

```
[DETECT] SkillGapDetector
    After RCA: "We don't have a skill for RDS connection timeout"
        |
[GENERATE] SOPAutoWriter
    Draft skill: investigation steps + expected evidence + remediation
        |
[VALIDATE] Sandbox Replay (Phase 2+)
    Inject similar fault scenario -> does skill produce correct RCA?
    Reference: AIOpsLab (arXiv:2501.06706)
        |
[DEPLOY] Promoted to production
    Available for Prompt Optimization retrieval
        |
[MONITOR] Usage Tracking
    Success rate, time-to-RCA, false positive rate
        |
[EVOLVE] Periodic Reflection
    Merge similar skills, retire stale ones, generalize patterns
    "ECS OOM Kill" skill -> generalize to "Container Memory Exhaustion"
    Reference: OpsAgent dual self-evolution (arXiv:2510.24145)
```

### 7.2 Skill Types

| Type | Examples | Lifecycle | Replaced by KB? |
|------|---------|-----------|:---:|
| **Domain frameworks** | kubernetes-admin, database-admin, network-engineer | DETECT->GENERATE->VALIDATE->DEPLOY->EVOLVE | Yes, gradually |
| **Execution tools** | run_on_host, run_kubectl, aws_cli | Permanent infrastructure | No |
| **Connector adapters** | datadog-connector, prometheus-connector | Permanent infrastructure | No |
| **Security classification** | command risk L0-L3, sensitive file blacklist | Permanent infrastructure | No |
| **Auto-generated** | "RDS connection timeout investigation" | Full lifecycle with validation | Absorbed into KB |

### 7.3 Skill Expiration + Refresh

- Infrastructure changes (detected during investigation) -> mark related skills for re-validation
- Skills not used for 6 months -> marked stale, deprioritized
- Human can retire/update skills via chat
- Confidence decay applies (same formula as Section 4.2): `base_confidence * 0.99^age_days * (1 + 0.1 * min(recall_count, 10))`

---

## 8. Dual Verification: Automated + Human

The ClawOps PostActionValidator (automated) + our Human Review (Ground Truth) work together:

### 8.1 PostActionValidator (Automated, Immediate)

After fix execution, automated observation windows:

```
T0 (30s):   Immediate check -- did the command succeed?
T1 (2min):  Short-term -- is the target metric improving?
T2 (5min):  Medium-term -- has the alert cleared?
T3 (15min): Stabilization -- no new related alerts?

Verdicts:
  SUCCESS:          All checks pass through T3
  PARTIAL_SUCCESS:  Metric improved (>20%) but alert not cleared
  FAILED:           Metric unchanged or worsened
  UNCERTAIN:        Insufficient signal (noisy metrics)
```

PARTIAL_SUCCESS innovation (from ClawOps): don't punish knowledge when fix partially works. Mark as "needs companion fix" instead.

### 8.2 Human Review (Ground Truth, 24h+)

Automated verification catches "did the metric recover?" but can't answer "did we fix the right thing?" Only humans can provide Ground Truth.

Three review points:

| Review Point | Trigger | Human Action | System Benefit |
|-------------|---------|-------------|----------------|
| **RCA Review** | After RCA completes | Accurate / Partial / Inaccurate + notes | Calibrate confidence, enrich Wisdom |
| **Fix Effectiveness** | 24h after execution (auto-push via Schedule) | Resolved / Mitigated / Unresolved | Validate SOP quality, adjust KB weight |
| **Service Model** | After Agent proposes grouping | Confirm / Correct | Improve service knowledge |

Review UI: minimal interaction. One click = one Ground Truth data point.

```
+---------------------------------------------------+
|  RCA Review                              I#42      |
|---------------------------------------------------|
|  Root cause: "payment-api v24 cache without TTL"   |
|  Confidence: 0.85 (calibrated: 0.73)               |
|  Evidence: CloudTrail[0.95] + Deployment[0.85]     |
|  PostAction: SUCCESS (T3 passed)                   |
|                                                    |
|  [Accurate]  [Partially Accurate]  [Inaccurate]   |
|  Notes: [optional free text]                       |
+---------------------------------------------------+
```

### 8.3 Self-Verification (Reasoning Quality Check)

Inspired by Voyager CriticAgent pattern and arXiv:2601.22208 (16 reasoning failure types):

Before outputting RCA, Agent performs independent self-check:
- Is the evidence chain logically consistent?
- Am I making a multi-hop reasoning error? (hardest failure type per paper)
- Does the root cause explain ALL symptoms, not just some?
- Would this root cause also explain the timing of the alert?

If self-check fails -> Agent re-investigates or flags low confidence.

### 8.4 Feedback Data Model

```
ReviewFeedback
  id: int (PK)
  review_type: str             # "rca" | "fix_effectiveness" | "service_model"
  health_issue_id: int (FK, nullable)
  fix_plan_id: int (FK, nullable)
  rca_result_id: int (FK, nullable)
  verdict: str                 # "accurate"|"partial"|"inaccurate"|"resolved"|"mitigated"|"unresolved"
  notes: str (nullable)
  corrected_root_cause: str (nullable)
  reviewer: str
  created_at: datetime

  UI flow: Human clicks one of 3 verdict buttons (Section 8.2).
  That's the only required interaction. Notes and corrected_root_cause are optional.
  No separate numeric rating -- verdict IS the Ground Truth signal.

PostActionResult
  id: int (PK)
  fix_plan_id: int (FK)
  health_issue_id: int (FK)
  observed_metric: str         # metric name being checked (e.g., "HealthCheckFailures")
  baseline_value: float        # metric value before fix
  threshold: float             # improvement threshold for "pass"
  t0_result: str               # "pass" | "fail"
  t1_result: str
  t2_result: str
  t3_result: str
  verdict: str                 # "success" | "partial_success" | "failed" | "uncertain"
  metric_improvement: float    # % improvement observed
  created_at: datetime

  Verdict aggregation from t0-t3:
    All pass through T3           -> SUCCESS
    T1 pass (>20% improvement)
      but T2 or T3 fail          -> PARTIAL_SUCCESS
    T0 pass but T1 fail          -> FAILED (metric didn't improve)
    T0 fail                      -> FAILED (command itself failed)
    Metric variance > threshold
      (noisy, can't determine)   -> UNCERTAIN
```

### 8.5 Confidence Calibration

Two-layer calibration: evidence-weighted (Section 5) + human-calibrated.

```
Layer 1: Evidence-weighted confidence (per RCA)
  Based on source weights of evidence chain

Layer 2: Human-calibrated (historical accuracy)
  Bin-based: 0.9-1.0, 0.7-0.9, 0.5-0.7, <0.5
  Updated incrementally on each human review
  Segmented by issue category once 30+ samples per segment

Display: "Confidence: 0.85 (calibrated: 0.73)"
Calibrated < 0.5 -> auto-flag "human review recommended"
```

### 8.6 Combined Verification Flow

**PostActionValidator verdicts mapped to HealthIssue state machine:**

| Verdict | HealthIssue Transition | Notes |
|---------|----------------------|-------|
| SUCCESS | `fix_executed` -> `resolved` | Auto-transition. 24h human review scheduled. |
| PARTIAL_SUCCESS | stays `fix_executed` | Issue remains open. Human review pushed immediately. |
| FAILED | `fix_executed` -> `root_cause_identified` | Rolls back to re-plan. New FixPlan allowed (terminal state rule). |
| UNCERTAIN | stays `fix_executed` | Issue remains open. Human decides next step via review. |

No new states added -- all verdicts map to existing transitions.

```
Fix executed
  |
  +-> PostActionValidator (automated, T0-T3)
  |     -> SUCCESS: auto-resolve, push 24h human review
  |     -> PARTIAL_SUCCESS: keep open, notify, push human review
  |     -> FAILED: rollback to root_cause_identified, flag for re-investigation
  |     -> UNCERTAIN: keep open, push human review
  |
  +-> Human Review (24h later)
  |     -> Accurate + Resolved: KB verified, Wisdom reinforced
  |     -> Accurate + Unresolved: fix tagged ineffective
  |     -> Inaccurate: KB rejected, Wisdom flagged
  |
  +-> Knowledge Sediment
        -> Episodic -> Procedural -> Semantic -> Skill -> SOP
        -> Confidence calibration updated
        -> Skill lifecycle: detect gaps, generate, validate, deploy
```

---

## 9. Service Model

### 9.1 Structured Storage in DB

Service model needs relational queries. Lives in DB, not vector KB.

```
Service (DB table)
  id, name, tier, owner, status (inferred|confirmed), notes, timestamps

ServiceResource (DB table, many-to-many)
  id, service_id (FK), resource_id (FK -> cloud_resources.id), role, is_shared, is_primary
  Note: FK targets cloud_resources (the multi-cloud table). AWSResource is legacy, not referenced.

ServiceDependency (DB table)
  id, source_service_id (FK), target_service_id (FK), type, evidence, status
```

### 9.2 How It Gets Built

Through normal Agent operation, not daemons:

- **Admin tells Agent**: "payment-service = [resource list]" -> stored, confirmed
- **Agent discovers during RCA**: queries tags + SG + APM, proposes grouping, human confirms
- **Agent infers during scan**: matching tags/naming -> proposes in chat, human confirms

### 9.3 Freshness

- During each RCA, Agent verifies current state against stored model
- Mismatch found -> Agent updates and notes the change
- Periodic scan can trigger refresh
- No TTL mechanics -- Agent naturally refreshes during operation

---

## 10. End-to-End Scenario

```
[10:35] Slack #ops-alerts: "FIRING: payment-api HealthCheckFailures"

[PERCEIVE]
  Agent reads IM. Alert classified: category=cache, pattern=cache_memory_exhaustion
  Memory recall: 3 similar past cases found in KB
  Service context: payment-service (critical), Redis shared with order-service

[PLAN] (Prompt Optimization Engine)
  Strategy from Wisdom: "check deployments first" (85% historical success)
  Few-shot: case-42 attached as reference (similar Redis OOM after deploy)
  Optimized prompt assembled (2800 tokens)

[ACT]
  -> aws connector: CloudTrail -> CodePipeline deployed v24 at 10:30 [evidence: 0.95]
  -> kubernetes connector: rollout history confirms v24 [evidence: 0.85]
  -> datadog connector: Redis memory spike at exactly 10:30 [evidence: 0.80]
  -> github connector: v24 diff shows promo:* cache logic, no TTL [evidence: 0.90]
  -> KB: Redis shared with order-service [context]
  -> datadog connector: order-service error rate 2% (up from 0.1%) [evidence: 0.80]

[DECIDE]
  RCA: "payment-api v24 introduced promo:* keys without TTL, exhausting Redis memory.
        Cascade: order-service impacted via shared Redis."
  Evidence-weighted confidence: 0.88
  Calibrated confidence: 0.76
  Fix: Rollback to v23 or set TTL on promo:* keys

[VERIFY]
  Fix executed (L1: kubectl + redis-cli, auto-approved)
  PostActionValidator:
    T0 (30s): command succeeded
    T1 (2min): Redis memory dropping
    T2 (5min): payment-api healthcheck passing
    T3 (15min): no new alerts -> SUCCESS
  Human review (24h): "Resolved" + rating 4/5

[LEARN]
  Episodic: case-142 saved (full evidence chain)
  Procedural: Wisdom "cache_memory_exhaustion" reinforced, deployment path confidence UP
  Semantic: "cache OOM after deploy = check TTL first" pattern strengthened
  Skill: no gap detected (existing skills covered this)
  SOP: auto-generated SOP for "Redis TTL verification after deployment"
  Calibration: 0.88 -> human 4/5 -> bin updated

  RESULT: 3 min total. Next similar: ~1.5 min (Wisdom guides optimal path)
```

---

## 11. Implementation Phases

### Phase 1: Foundation (aligns with ClawOps Q2 2026)

- Connector framework (config/connectors.yaml + base interface)
- Initial connectors: AWS (wrap existing), K8s (wrap existing), Datadog (new), Prometheus (new)
- Service model DB tables (Service, ServiceResource, ServiceDependency)
- Service discovery via chat (Agent proposes, human confirms)
- Alert Classifier + Pattern matching (basic LLM classification)
- Prompt Optimization Engine v1 (Strategy Selector + Few-Shot Retriever + Prompt Assembler)
- Evidence gathering with source weighting
- Existing 10 domain skills continue unchanged; indexed for retrieval by Prompt Optimization Engine. Lifecycle management deferred to Phase 3.

### Phase 2: Verification + Learning (aligns with ClawOps Q3-Q4 2026)

- PostActionValidator (T0-T3 automated verification)
- ReviewFeedback + PostActionResult DB models
- RCA Review Card + Fix Effectiveness UI
- Human feedback -> KB weight adjustment
- Confidence calibration (evidence-weighted + human-calibrated)
- Wisdom Roadmap: entry distillation from resolved+reviewed cases
- Dynamic System Prompt composition (base + service + wisdom + few-shot)
- Four-layer memory classification (episodic -> procedural -> semantic -> skill)

### Phase 3: Self-Evolution (aligns with ClawOps 2027)

- SkillGapDetector: detect missing skills after RCA
- SOPAutoWriter: auto-generate skill from successful RCA
- Skill validation via sandbox replay (AIOpsLab framework)
- Skill expiration + confidence decay + refresh
- Wisdom Roadmap maturation (reinforce/contradict/merge/stale)
- Calibration segmentation by category
- Self-Verification (reasoning quality check, 16 failure types)
- Agent self-proposed Skill updates

### Phase 4: Autonomous Operations (aligns with ClawOps 2028+)

- Cross-service incident correlation (N alerts -> 1 service incident)
- Proactive change risk detection via IM channel monitoring
- Skill generalization ("ECS OOM" -> "Container Memory Exhaustion")
- Code Interpreter: Agent writes custom queries for novel scenarios
- Graduated autonomous remediation (expanding L-level boundaries)
- Multi-agent cross-verification
- Additional connectors on demand (PagerDuty, Jira, ELK, etc.)

---

## 12. API Endpoints (New)

| Group | Endpoint | Method | Purpose |
|-------|----------|--------|---------|
| **Connectors** | `/api/connectors` | GET | List configured connectors |
| | `/api/connectors/{name}` | PUT | Add/update connector |
| | `/api/connectors/{name}` | DELETE | Remove connector |
| | `/api/connectors/{name}/test` | POST | Test connectivity |
| **Services** | `/api/services` | GET | List services |
| | `/api/services/{id}` | GET | Service detail + resources + deps |
| | `/api/services/{id}/confirm` | PUT | Human confirms/corrects |
| **Reviews** | `/api/reviews` | POST | Submit review feedback |
| | `/api/reviews/stats` | GET | Statistics + calibration |
| | `/api/health-issues/{id}/review` | GET | Review status |
| **Verification** | `/api/health-issues/{id}/verification` | GET | PostAction result |
| **Wisdom** | `/api/wisdom` | GET | List Wisdom entries |
| | `/api/wisdom/{pattern}` | GET | Entry for pattern |
| **Skills** | `/api/skills/gaps` | GET | Detected skill gaps |
| | `/api/skills/{name}/lifecycle` | GET | Skill lifecycle state |
| **Calibration** | `/api/calibration` | GET | Calibration table |

---

## 13. Success Metrics

| Metric | Current (1.0) | Target (2.0) | Measurement |
|--------|:------------:|:------------:|-------------|
| RCA accuracy (human-verified) | Unknown | >80% known patterns | Review feedback |
| RCA time for known patterns | ~2-6 min | <2 min | Pipeline timestamps |
| RCA time for novel patterns | ~6 min | ~4 min | Pipeline timestamps |
| PostAction SUCCESS rate | N/A | >70% for L0/L1 fixes | PostActionResult |
| KB verified case ratio | 0% | >50% at 6 months | Review data |
| Confidence calibration error | Unknown | <10% deviation | Calibration vs actuals |
| Wisdom Roadmap coverage | 0 entries | >40 patterns at 6 months | KB count |
| Skill auto-generation rate | 0 | >5 new skills/quarter | Skill registry |
| Skills internalized to KB | 0/10 | >5/10 at 12 months | Usage tracking |
| Service model coverage | 0% | >80% managed resources | DB service entries |
| Evidence-backed RCA ratio | Unknown | >90% (vs pure inference) | Evidence chain analysis |

---

## 14. References

| # | Paper | ArXiv | Key Contribution |
|---|-------|-------|-----------------|
| 1 | eARCO: Prompt Optimization for RCA | 2504.11505 | Prompt > RAG > Fine-tuning, 21% accuracy gain |
| 2 | Why AI Agents Fail at Cloud RCA | 2602.09937 | 12 failure types, architecture > prompts |
| 3 | 16 RCA Reasoning Failure Types | 2601.22208 | Multi-hop reasoning as hardest failure |
| 4 | AIOpsLab: Agent Evaluation | 2501.06706 | Holistic AIOps eval framework (Microsoft) |
| 5 | OpsAgent: Self-Evolution | 2510.24145 | Dual self-evolution mechanism |
| 6 | CCAR: Safe Autonomous Resolution | 2603.08736 | Formal false-positive bounds |
| 7 | RCACopilot (Microsoft) | 2305.15778 | 4-year production RCA, 0.766 accuracy |
| 8 | Pearl's Causal Framework | -- | do-calculus, counterfactual reasoning |

---

*AgenticOps Next-Gen Design v4 -- 2026-03-15*
*Vision: ClawOps Agent-First AIOps Architecture*
