# Phase 3: Self-Evolution + Phase 4: Autonomous Operations — Strategic Plan

> **For agentic workers:** These phases are 1-2 years out. This plan is task-level (goals + files + dependencies), not step-level. Detailed TDD plans should be written when each phase begins, using the codebase state at that time.

**Spec:** `docs/superpowers/specs/2026-03-15-next-gen-aiops-design.md` (Sections 7, 11 Phase 3-4)

**Prerequisites:** Phase 1 (Foundation) + Phase 2 (Verification + Learning) complete.

---

# Phase 3: Self-Evolution (2027)

**Goal:** The system learns from its own successes and failures. Skills are auto-generated, validated, and evolved. Wisdom Roadmap matures through reinforcement, contradiction, and merging. Self-verification catches reasoning failures before they reach humans.

---

## Task 1: SkillGapDetector

**Goal:** After each RCA, detect if the investigation required knowledge/steps that no existing skill covers.

**Files:**
- Create: `src/agenticops/skills/gap_detector.py`
- Modify: `src/agenticops/agents/rca_agent.py` (trigger gap detection post-RCA)
- Test: `tests/test_skill_gap_detector.py`

**Logic:**
- After RCA completes, compare investigation steps against activated skills
- If RCA used tools/patterns not covered by any skill → flag as skill gap
- Store gap in DB (`SkillGap` model: pattern, missing_capability, source_issue_id)
- Trigger SOPAutoWriter if gap detected 3+ times for same pattern

**Dependencies:** Existing skills system (`skills/loader.py`), RCA Agent

---

## Task 2: SOPAutoWriter

**Goal:** Auto-generate a draft skill from a successful RCA investigation path.

**Files:**
- Create: `src/agenticops/skills/sop_writer.py`
- Modify: `src/agenticops/skills/evolution.py` (extend existing)
- Test: `tests/test_sop_writer.py`

**Logic:**
- Input: RCA evidence chain + investigation steps + root cause + fix plan
- LLM generates: SKILL.md with investigation steps, expected evidence, remediation
- Output saved to `skills/draft/` (not production until validated)
- Reference: OpsAgent dual self-evolution (arXiv:2510.24145)

**Dependencies:** Task 1 (SkillGapDetector triggers this)

---

## Task 3: Skill Validation via Sandbox Replay

**Goal:** Validate auto-generated skills by replaying similar fault scenarios.

**Files:**
- Create: `src/agenticops/skills/validator.py`
- Create: `src/agenticops/testing/fault_injector.py` (optional, if lab available)
- Test: `tests/test_skill_validator.py`

**Logic:**
- Take draft skill + similar past case from KB
- Run RCA agent with ONLY the draft skill activated (isolated test)
- Compare RCA output against known Ground Truth from the past case
- Score: did the skill lead to correct root cause?
- Pass → promote to production. Fail → mark for revision.
- Reference: AIOpsLab framework (arXiv:2501.06706)

**Dependencies:** Task 2 (draft skills exist), KB has Ground Truth data (Phase 2 reviews)

---

## Task 4: Skill Expiration + Confidence Decay

**Goal:** Skills that are unused or whose infrastructure has changed get deprioritized.

**Files:**
- Modify: `src/agenticops/skills/loader.py` (add usage tracking)
- Create: `src/agenticops/skills/lifecycle.py` (expiration + refresh logic)
- Modify: `src/agenticops/models.py` (add SkillRegistry model: name, status, last_used, confidence, validation_result)
- Test: `tests/test_skill_lifecycle.py`

**Logic:**
- Confidence decay formula: `base_confidence * 0.99^age_days * (1 + 0.1 * min(recall_count, 10))`
- Skills not used for 6 months → marked `stale`
- Infrastructure changes detected during investigation → related skills flagged for re-validation
- Human can retire/update skills via chat or API

**Dependencies:** Skill usage tracking (integrated during skill activation in agents)

---

## Task 5: Wisdom Roadmap Maturation

**Goal:** Wisdom entries evolve through reinforcement, contradiction, merging, and staleness.

**Files:**
- Create: `src/agenticops/wisdom/maturation.py`
- Modify: `src/agenticops/wisdom/roadmap.py` (add maturation hooks)
- Test: `tests/test_wisdom_maturation.py`

**Logic:**
- **Reinforce**: Human reviews "accurate" → increment success_count, boost confidence
- **Contradict**: Human reviews "inaccurate" → decrement confidence, flag for review
- **Merge**: If two patterns have >80% overlapping investigation steps → suggest merge
- **Stale**: Wisdom not recalled for 6 months → reduce confidence via decay
- Periodic reflection job (weekly): scan all wisdom entries, apply maturation rules

**Dependencies:** Phase 2 Wisdom Roadmap + Review system

---

## Task 6: Calibration Segmentation by Category

**Goal:** Separate calibration bins per issue category for more precise confidence estimates.

**Files:**
- Modify: `src/agenticops/verification/calibration.py` (add category segmentation)
- Test: `tests/test_calibration.py` (extend)

**Logic:**
- When category has 30+ reviews → create category-specific bins
- `get_calibrated_confidence(db, 0.85, category="cache")` uses category bin if available, falls back to "all"
- Trigger: automatic when bin count crosses threshold

**Dependencies:** Phase 2 calibration + enough review data

---

## Task 7: Self-Verification (Reasoning Quality Check)

**Goal:** Before outputting RCA, Agent independently checks its own reasoning quality.

**Files:**
- Create: `src/agenticops/verification/self_check.py`
- Modify: `src/agenticops/agents/rca_agent.py` (add self-check step before output)
- Test: `tests/test_self_check.py`

**Logic:**
- Inspired by Voyager CriticAgent pattern + arXiv:2601.22208 (16 reasoning failure types)
- After evidence synthesis, before saving RCA:
  1. Is the evidence chain logically consistent?
  2. Multi-hop reasoning check (hardest failure type)
  3. Does root cause explain ALL symptoms?
  4. Timing consistency check
- If any check fails → re-investigate or flag low confidence
- Implementation: separate LLM call with critic prompt, independent of main RCA reasoning

**Dependencies:** RCA agent, Bedrock API (additional LLM call)

---

## Task 8: Agent Self-Proposed Skill Updates

**Goal:** After successful investigations, Agent suggests skill improvements.

**Files:**
- Modify: `src/agenticops/skills/evolution.py`
- Modify: `src/agenticops/agents/rca_agent.py` (post-RCA skill update proposal)

**Logic:**
- If Agent used a skill but deviated from its steps → propose update
- If Agent found edge case not covered by skill → propose addition
- Proposals stored in `skill_proposals` table, reviewed by human via UI/chat
- Human approves → skill updated automatically

**Dependencies:** Tasks 1-4 (skill lifecycle infrastructure)

---

## Phase 3 Dependency Graph

```
Task 1 (SkillGapDetector) ── Task 2 (SOPAutoWriter) ── Task 3 (Skill Validation)
                                                              |
Task 4 (Skill Expiration) ─────────────────────────────── Task 8 (Self-Proposed Updates)

Task 5 (Wisdom Maturation)    [independent]
Task 6 (Calibration Segmentation)  [independent]
Task 7 (Self-Verification)    [independent]
```

Parallel tracks: Skills lifecycle (1-4, 8), Wisdom maturation (5), Calibration (6), Self-verification (7).

---

# Phase 4: Autonomous Operations (2028+)

**Goal:** The system operates with minimal human oversight. Cross-service incident correlation, proactive risk detection, graduated autonomous remediation, and multi-agent cross-verification.

---

## Task 9: Cross-Service Incident Correlation

**Goal:** N alerts from different services → 1 root incident.

**Files:**
- Create: `src/agenticops/correlation/engine.py`
- Create: `src/agenticops/correlation/grouper.py`
- Modify: `src/agenticops/services/pipeline_service.py`

**Logic:**
- When multiple HealthIssues arrive within time window (e.g., 5 min):
  - Check Service Model for shared resources or dependencies
  - If correlated → group into single incident, single RCA
  - Uses graph engine for dependency traversal
- Dedup: shared Redis between payment + order service → 2 alerts → 1 incident

**Key challenge:** Timing window calibration, false positive grouping

---

## Task 10: Proactive Change Risk Detection

**Goal:** Monitor IM channels and CloudTrail for risky changes BEFORE they cause incidents.

**Files:**
- Create: `src/agenticops/proactive/change_monitor.py`
- Modify: `src/agenticops/im/` (IM channel monitoring for deploy announcements)

**Logic:**
- Parse IM messages for deployment/change signals
- Cross-reference with Wisdom Roadmap: "deployments to payment-service have 30% incident rate"
- Alert team proactively: "payment-service deploy detected, historically risky"
- This is intelligence, not prevention — Agent informs, doesn't block

---

## Task 11: Skill Generalization

**Goal:** Abstract specific skills into reusable pattern templates.

**Logic:**
- "ECS OOM Kill" + "K8s OOM Kill" → "Container Memory Exhaustion" (pluggable data source)
- LLM analyzes multiple similar skills, extracts common investigation pattern
- Creates parameterized template skill with data source abstraction
- Reference: OpsAgent dual self-evolution (arXiv:2510.24145)

---

## Task 12: Code Interpreter

**Goal:** Agent writes custom queries/scripts for novel scenarios.

**Logic:**
- When existing tools/connectors can't answer the question
- Agent generates Python/SQL/PromQL code on-the-fly
- Sandboxed execution environment (container-based)
- Results fed back into evidence chain with weight 0.60 (custom code)

---

## Task 13: Graduated Autonomous Remediation

**Goal:** Expand L-level boundaries as system proves reliability.

**Logic:**
- Track: PostActionValidator success rate per L-level
- When L1 success rate > 95% for 3 months → propose expanding L1 scope
- When L2 success rate > 90% for 6 months → propose auto-approve L2
- Human approves expansion — never automatic
- Reference: CCAR framework (arXiv:2603.08736) formal false-positive bounds

---

## Task 14: Multi-Agent Cross-Verification

**Goal:** Multiple agents independently analyze the same incident, consensus determines confidence.

**Logic:**
- For high-severity incidents: spawn 2-3 RCA agents with different strategies
- Compare root causes:
  - All agree → high confidence
  - 2/3 agree → medium confidence, note dissent
  - All disagree → low confidence, flag for human
- Reference: mABC multi-agent RCA (arXiv:2404.12135)

---

## Task 15: Additional Connectors On-Demand

**Goal:** Expand connector ecosystem as needed.

**Candidates:**
- PagerDuty (incident management)
- Jira (ticket tracking)
- ELK/OpenSearch (log analysis)
- Grafana (dashboard queries)
- GitHub Actions (CI/CD status)
- Terraform/CloudFormation (IaC state)

**Pattern:** Each follows `ConnectorBase` ABC from Phase 1. Agent requests connector during investigation → if not available, logged as connector gap → admin provisions.

---

## Phase 4 Dependency Graph

```
Task 9 (Cross-Service Correlation) depends on Phase 1 Service Model + Phase 3 Wisdom
Task 10 (Proactive Detection) depends on IM integration + Phase 3 Wisdom
Task 11 (Skill Generalization) depends on Phase 3 skill lifecycle
Task 12 (Code Interpreter) independent
Task 13 (Graduated Autonomy) depends on Phase 2 PostActionValidator + sufficient data
Task 14 (Multi-Agent Verification) depends on Phase 1 connectors + Phase 3 self-verification
Task 15 (Additional Connectors) independent, on-demand
```

---

# Cross-Phase Summary

| Phase | Timeline | Tasks | Key Outcome |
|-------|----------|-------|-------------|
| **Phase 1** | Q2 2026 | 18 | Agent can use external tools, classify alerts, optimize prompts, weight evidence |
| **Phase 2** | Q3-Q4 2026 | 14 | System learns from automated + human feedback, builds Wisdom Roadmap |
| **Phase 3** | 2027 | 8 | Skills self-generate and evolve, reasoning self-checks, wisdom matures |
| **Phase 4** | 2028+ | 7 | Cross-service correlation, proactive detection, graduated autonomy |
| **Total** | | **47 tasks** | Full Agent-First AIOps with self-evolution |

### The Learning Flywheel

```
Phase 1: Agent investigates with tools + evidence weighting
    |
Phase 2: Human reviews create Ground Truth -> calibration + wisdom
    |
Phase 3: System generates its own skills -> validates -> deploys
    |
Phase 4: System correlates across services -> detects proactively -> expands autonomy
    |
Each cycle makes the next faster and more accurate
```
