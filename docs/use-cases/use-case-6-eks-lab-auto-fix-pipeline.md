# Use Case 6: EKS Lab Auto-Fix Pipeline — Closed-Loop Remediation

**Date**: 2026-03-03
**Status**: Validated (Case 1 OOM Kill)
**Environment**: EKS Lab on AWS bastion (VPC internal, no public endpoint)

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    AgenticOps Auto-Fix Pipeline                        │
│                  (Closed-Loop Incident Remediation)                    │
└─────────────────────────────────────────────────────────────────────────┘

① DETECT
   Prometheus (kube-state-metrics + node-exporter)
       │  scrape every 15s
       ▼
   PrometheusRule (10 alert rules in alert-rules.yaml)
       │  evaluate every 30s
       ▼
② ALERT
   AlertManager
       │  POST webhook (group_wait: 10s)
       ▼
③ INGEST
   AgenticOps API  ──POST /api/webhooks/prometheus──►  _process_webhook_alert()
       │  parse_prometheus() → create_health_issue() (fingerprint dedup)
       ▼
   HealthIssue #N created  [status: open]
       │
       ▼
④ AUTO-RCA  (daemon thread)
   rca_service.trigger_auto_rca()
       │  Main Agent → rca_agent()  (Bedrock Sonnet 4.6)
       │  - Reads HealthIssue + alert context
       │  - activate_skill("kubernetes-admin") for K8s decision trees
       │  - run_kubectl() for live cluster inspection
       │  - search_sops() + search_similar_cases() for KB lookup
       ▼
   RCA Result saved  [status: root_cause_identified]
       │
       ▼
⑤ AUTO-SRE  (daemon thread)
   pipeline_service.trigger_auto_sre()
       │  sre_agent()  (Bedrock Sonnet 4.6)
       │  - Reads RCA result + HealthIssue
       │  - Assesses risk level (L0/L1/L2/L3)
       │  - Generates fix plan with pre/post checks + rollback
       ▼
   FixPlan saved  [status: fix_planned, risk_level: L0-L3]
       │
       ▼
⑥ AUTO-APPROVE
   pipeline_service.trigger_auto_approve()
       │  L0/L1 → auto-approved (settings.executor_auto_approve_l0_l1)
       │  L2/L3 → paused, requires human approval via API/chat
       ▼
   FixPlan approved  [status: fix_approved]
       │
       ▼
⑦ AUTO-EXECUTE  (daemon thread)
   pipeline_service.trigger_auto_execute()
       │  executor_agent()  (Bedrock Opus 4.6)
       │  7-step protocol: VERIFY → GATE → PRE-CHECK → EXECUTE → POST-CHECK → ROLLBACK → FINALIZE
       │  - run_kubectl() for K8s operations (uses KUBECONFIG env var)
       │  - run_on_host() for SSM/SSH host commands
       │  - run_aws_cli() for AWS API operations
       ▼
   Execution completed  [status: resolved]
       │
       ▼
⑧ POST-RESOLUTION
   resolution_service (background)
       │  - RAG pipeline: distill case → generate/update SOP
       │  - Auto-notifications to configured channels (Feishu/Slack/etc.)
       ▼
   Knowledge Base updated + Notification sent
```

## Risk Level Classification

| Level | Description | Approval | Examples |
|-------|-------------|----------|----------|
| **L0** | Read-only verification | Auto | Confirm metric recovered |
| **L1** | Single workload remediation | Auto | `kubectl rollout undo`, `set resources`, `delete networkpolicy`, `scale deployment` |
| **L2** | Multi-resource changes | Human | Resize instance, modify SG rules, multi-namespace changes |
| **L3** | High-risk operations | Human | Service restart, failover, data migration, node drain |

## Validated Case: OOM Kill → CrashLoopBackOff → Auto-Fix

### Scenario
- **Target**: `adservice` (Java, normal memory ~300Mi)
- **Injection**: `kubectl set resources deploy/adservice --limits=memory=64Mi`
- **Expected**: OOM Kill → CrashLoopBackOff → auto-detect → auto-fix

### Pipeline Execution Timeline

| Step | Event | Latency |
|------|-------|---------|
| ① | Prometheus detects OOM metric (container_oom_events_total) | ~15s |
| ② | AlertManager fires `KubePodOOMKilled` alert | ~30s |
| ③ | AgenticOps receives webhook → HealthIssue #1 created | <1s |
| ④ | Auto-RCA: identifies OOM root cause (exit code 137, memory limit too low) | ~90s |
| ⑤ | Auto-SRE: generates L1 fix plan (kubectl set resources --limits=memory=300Mi) | ~60s |
| ⑥ | Auto-approve: L1 plan auto-approved | <1s |
| ⑦ | Executor: runs kubectl set resources on adservice | ~45s |
| ⑧ | Issue resolved, adservice running with 300Mi memory | - |
| **Total MTTR** | | **~4 min** |

### Result
- Issue #1: `open` → `investigating` → `root_cause_identified` → `fix_planned` → `fix_approved` → **resolved**
- FixPlan #1: status=**executed**, risk_level=**L1**
- adservice memory: 64Mi → **300Mi** (restored)

## Code Path

```
app.py:_process_webhook_alert()
  → parse_prometheus()
  → create_health_issue()  [fingerprint dedup, 5-min window]
  → rca_service.trigger_auto_rca()           # daemon thread
    → metadata_tools.save_rca_result()
    → pipeline_service.trigger_auto_sre()     # daemon thread
      → metadata_tools.save_fix_plan()
      → pipeline_service.trigger_auto_approve()
      → pipeline_service.trigger_auto_execute()  # daemon thread
        → metadata_tools.save_execution_result()
        → resolution_service (RAG + notify)
```

## Key Configuration

| Setting | Value | Env Var |
|---------|-------|---------|
| `auto_rca_enabled` | true | `AIOPS_AUTO_RCA_ENABLED` |
| `auto_fix_enabled` | true | `AIOPS_AUTO_FIX_ENABLED` |
| `executor_enabled` | true | `AIOPS_EXECUTOR_ENABLED` |
| `executor_auto_approve_l0_l1` | true | `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1` |
| `notifications_enabled` | true | `AIOPS_NOTIFICATIONS_ENABLED` |
| `bedrock_model_id` | Sonnet 4.6 | `AIOPS_BEDROCK_MODEL_ID` |
| `bedrock_model_id_strong` | Opus 4.6 | `AIOPS_BEDROCK_MODEL_ID_STRONG` |

## Alert Rules (10 PrometheusRule alerts)

| Alert | Trigger | For | Case |
|-------|---------|-----|------|
| KubePodCrashLooping | restarts > 3 | 2m | 1 |
| KubePodOOMKilled | OOM events > 0 | 0m | 1 |
| KubePodNotReady | pod not ready | 3m | 3 |
| KubeDeploymentReplicasMismatch | available ≠ desired | 5m | 2 |
| NodeNotReady | node condition | 3m | 4 |
| NodeDiskPressure | disk pressure | 3m | 4 |
| TargetDown | target unreachable | 2m | 6 |
| HighErrorRate | 5xx > 5% | 3m | 10 |
| HighLatencyP99 | p99 > 2s | 5m | - |
| KubePVCPending | PVC pending | 5m | 8 |

## Deployment (Bastion Host)

```bash
# 1. Set KUBECONFIG for kubectl access
export KUBECONFIG=/home/ubuntu/agenticops-chat/infra/eks-lab/kubeconfig

# 2. Start AgenticOps API (tmux session)
cd /home/ubuntu/agenticops-chat
uvicorn agenticops.web.app:app --host 0.0.0.0 --port 8000

# 3. Verify
curl http://localhost:8000/api/health
kubectl get pods -n online-boutique

# 4. Inject fault (example: Case 1 OOM)
kubectl set resources deploy/adservice -n online-boutique --limits=memory=64Mi

# 5. Monitor pipeline
watch -n5 'curl -s http://localhost:8000/api/health-issues | python3 -m json.tool'
```
