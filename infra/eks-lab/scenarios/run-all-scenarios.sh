#!/usr/bin/env bash
# AgenticOps EKS Lab — Master scenario orchestrator
# Runs all 10 closed-loop validation cases sequentially:
#   inject → verify → cleanup → cool-down
#
# Usage:
#   AGENTICOPS_URL=http://localhost:8000 bash run-all-scenarios.sh
#
# Prerequisites:
#   - EKS cluster deployed and healthy (5 nodes, Online Boutique running)
#   - AgenticOps API running and receiving AlertManager webhooks
#   - kubectl configured (KUBECONFIG set or in PATH)
#   - Port-forwards active: Prometheus 9090, AlertManager 9093
#
# Output:
#   - Console: per-case PASS/FAIL + timing
#   - CSV: .timing-results.csv (case, elapsed, status, timestamp)
#
# Validated: 2026-03-06 — 10/10 cases passing 5/5

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

COOL_DOWN="${COOL_DOWN:-45}"
CASES_PASSED=0
CASES_TOTAL=10
RUN_START=$SECONDS
TIMING_CSV="${SCRIPT_DIR}/.timing-results.csv"

# Initialize timing CSV
echo "case,elapsed_seconds,status,timestamp" > "$TIMING_CSV"

echo ""
echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  AgenticOps — Closed-Loop Validation (10 Cases)           ║${NC}"
echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
report_info "AgenticOps API: ${AGENTICOPS_URL}"
report_info "KUBECONFIG:     ${KUBECONFIG}"
report_info "Cool-down:      ${COOL_DOWN}s between cases"
report_info "Timing CSV:     ${TIMING_CSV}"
echo ""

# ---------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------
echo -e "${BOLD}Pre-flight checks:${NC}"

API_STATUS=$(curl -sf "${AGENTICOPS_URL}/api/health" 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('checks',{}).get('aws',{}).get('status',''))" 2>/dev/null || echo "")
if [[ "$API_STATUS" == "ok" ]]; then
    report_pass "AgenticOps API reachable, AWS credentials valid"
else
    report_fail "AgenticOps API not reachable or AWS credentials invalid"
    exit 1
fi

NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ "$NODE_COUNT" -ge 3 ]]; then
    report_pass "EKS cluster has ${NODE_COUNT} nodes"
else
    report_fail "EKS cluster has ${NODE_COUNT} nodes (need ≥3)"
    exit 1
fi

DEPLOY_COUNT=$(kubectl get deploy -n online-boutique --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ "$DEPLOY_COUNT" -ge 10 ]]; then
    report_pass "Online Boutique has ${DEPLOY_COUNT} deployments"
else
    report_fail "Online Boutique has ${DEPLOY_COUNT} deployments (need ≥10)"
    exit 1
fi

AM_STATUS=$(curl -sf http://localhost:9093/api/v2/status 2>/dev/null \
    | python3 -c "import sys,json; print('ok')" 2>/dev/null || echo "")
if [[ "$AM_STATUS" == "ok" ]]; then
    report_pass "AlertManager reachable on port 9093"
else
    report_fail "AlertManager not reachable (port-forward needed)"
    exit 1
fi

echo ""

# ---------------------------------------------------------------
# run_case NUM NAME DIR
# ---------------------------------------------------------------
run_case() {
    local case_num="$1"
    local case_name="$2"
    local case_dir="$3"
    local case_start=$SECONDS

    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  Case ${case_num}/10: ${case_name}${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    bash "${SCRIPT_DIR}/${case_dir}/inject.sh"
    if bash "${SCRIPT_DIR}/${case_dir}/verify.sh"; then
        CASES_PASSED=$((CASES_PASSED + 1))
        collect_timing "case-${case_num}" "$(( SECONDS - case_start ))" "PASSED"
    else
        collect_timing "case-${case_num}" "$(( SECONDS - case_start ))" "FAILED"
    fi

    report_info "Cleaning up chaos artifacts..."
    cleanup_chaos_artifacts
    restore_clean_state

    # Node-level recovery may need extra time
    if [[ "$case_num" == "4" ]]; then
        report_info "Node-level case — extended cool-down (90s)..."
        sleep 90
    else
        report_info "Cool-down ${COOL_DOWN}s..."
        sleep "$COOL_DOWN"
    fi
}

# ===============================================================
# Phase 1: Cases 1-3 (Pod-level failures)
# ===============================================================
echo -e "\n${BLUE}${BOLD}▶ Phase 1: Pod-Level Failures (Cases 1-3)${NC}\n"

run_case 1  "OOM Kill (adservice)"          "case-1-oom"
run_case 2  "Bad Image (productcatalog)"    "case-2-bad-image"
run_case 3  "Redis Crash (redis-cart)"      "case-3-network-policy"

# ===============================================================
# Phase 2: Cases 4-10 (Node, cluster, infra failures)
# ===============================================================
echo -e "\n${BLUE}${BOLD}▶ Phase 2: Advanced Cases (Cases 4-10)${NC}\n"

run_case 4  "Node DiskPressure"             "case-4-node-disk-pressure"
run_case 5  "Pod Pending (CPU exhaustion)"  "case-5-pod-pending"
run_case 6  "Unhealthy Targets (readiness)" "case-6-unhealthy-targets"
run_case 7  "CoreDNS Down"                  "case-7-coredns-down"
run_case 8  "PVC Pending (wrong SC)"        "case-8-pvc-pending"
run_case 9  "HPA Maxed Out"                 "case-9-hpa-maxed"
run_case 10 "Service Crash (cartservice)"   "case-10-service-deleted"

# ===============================================================
# Final Report
# ===============================================================
RUN_ELAPSED=$(( SECONDS - RUN_START ))
echo ""
echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Validation Results                                       ║${NC}"
echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Timing table
if [[ -f "$TIMING_CSV" ]]; then
    echo -e "${BOLD}  Timing:${NC}"
    echo ""
    column -t -s',' "$TIMING_CSV" | sed 's/^/    /'
    echo ""

    # Calculate stats
    AVG_ELAPSED=$(tail -n +2 "$TIMING_CSV" | awk -F',' '{sum+=$2; n++} END{if(n>0) printf "%.0f", sum/n; else print "0"}')
    MAX_ELAPSED=$(tail -n +2 "$TIMING_CSV" | awk -F',' 'BEGIN{max=0} {if($2+0>max) max=$2+0} END{printf "%.0f", max}')
    echo -e "  Average MTTR: ${AVG_ELAPSED}s ($(( AVG_ELAPSED / 60 ))m $(( AVG_ELAPSED % 60 ))s)"
    echo -e "  Max MTTR:     ${MAX_ELAPSED}s ($(( MAX_ELAPSED / 60 ))m $(( MAX_ELAPSED % 60 ))s)"
fi

echo ""
report_time "Total run time: ${RUN_ELAPSED}s ($(( RUN_ELAPSED / 60 ))m $(( RUN_ELAPSED % 60 ))s)"
echo ""

# Acceptance criteria
echo -e "${BOLD}  Acceptance Criteria:${NC}"
echo ""
if [[ $CASES_PASSED -ge 7 ]]; then
    echo -e "    ${GREEN}✓${NC} Auto-fix rate: ${CASES_PASSED}/${CASES_TOTAL} (target: ≥7/10)"
else
    echo -e "    ${RED}✗${NC} Auto-fix rate: ${CASES_PASSED}/${CASES_TOTAL} (target: ≥7/10)"
fi
if [[ -f "$TIMING_CSV" ]]; then
    echo -e "    $([ "$MAX_ELAPSED" -le 600 ] && echo "${GREEN}✓${NC}" || echo "${YELLOW}?${NC}") Max MTTR: ${MAX_ELAPSED}s (target: ≤600s)"
    echo -e "    ${YELLOW}?${NC} Avg detection: review per-case output (target: ≤3 min)"
fi
echo -e "    ${YELLOW}?${NC} Per-cycle cost ≤ \$3 — check Bedrock billing"
echo ""

if [[ $CASES_PASSED -eq $CASES_TOTAL ]]; then
    echo -e "${GREEN}${BOLD}  ★ ALL ${CASES_TOTAL} CASES PASSED ★${NC}"
    echo ""
    exit 0
elif [[ $CASES_PASSED -ge 7 ]]; then
    echo -e "${YELLOW}${BOLD}  PASSED: ${CASES_PASSED}/${CASES_TOTAL} (meets acceptance criteria)${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}${BOLD}  FAILED: ${CASES_PASSED}/${CASES_TOTAL} (below acceptance criteria)${NC}"
    echo ""
    exit 1
fi
