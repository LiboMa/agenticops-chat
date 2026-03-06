#!/usr/bin/env bash
# AgenticOps EKS Lab — Phase 2 scenario orchestrator
# Runs Cases 4-10 sequentially: inject → verify → cleanup → cool-down
#
# Usage:
#   AGENTICOPS_URL=http://localhost:8000 bash run-phase2.sh
#
# Prerequisites:
#   - EKS cluster deployed (setup.sh)
#   - AgenticOps API running and receiving AlertManager webhooks
#   - kubectl configured
#   - Phase 1 passed (Cases 1-3)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

COOL_DOWN=60
CASES_PASSED=0
CASES_TOTAL=7
PHASE_START=$SECONDS

echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  AgenticOps Phase 2 — Advanced Cases (7/10)          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
report_info "AgenticOps API: ${AGENTICOPS_URL}"
report_info "KUBECONFIG: ${KUBECONFIG}"
report_info "Cool-down between cases: ${COOL_DOWN}s"
echo ""

run_case() {
    local case_num="$1"
    local case_name="$2"
    local case_dir="$3"
    local case_start=$SECONDS

    echo -e "\n${BOLD}━━━ Case ${case_num}/10: ${case_name} ━━━${NC}"
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
    report_info "Cool-down ${COOL_DOWN}s..."
    sleep "$COOL_DOWN"
}

# ---------------------------------------------------------------
# Case 4: Node DiskPressure
# ---------------------------------------------------------------
run_case 4 "Node DiskPressure" "case-4-node-disk-pressure"

# ---------------------------------------------------------------
# Case 5: Pod Pending (Resource Exhaustion)
# ---------------------------------------------------------------
run_case 5 "Pod Pending (Resource Exhaustion)" "case-5-pod-pending"

# ---------------------------------------------------------------
# Case 6: Unhealthy LB Targets
# ---------------------------------------------------------------
run_case 6 "Unhealthy LB Targets" "case-6-unhealthy-targets"

# ---------------------------------------------------------------
# Case 7: CoreDNS Failure
# ---------------------------------------------------------------
run_case 7 "CoreDNS Failure" "case-7-coredns-down"

# ---------------------------------------------------------------
# Case 8: PVC Pending (Wrong StorageClass)
# ---------------------------------------------------------------
run_case 8 "PVC Pending (Wrong StorageClass)" "case-8-pvc-pending"

# ---------------------------------------------------------------
# Case 9: HPA Not Scaling
# ---------------------------------------------------------------
run_case 9 "HPA Not Scaling (maxReplicas=1)" "case-9-hpa-maxed"

# ---------------------------------------------------------------
# Case 10: Service Deleted (5xx Surge)
# ---------------------------------------------------------------
run_case 10 "Service Deleted (cartservice)" "case-10-service-deleted"

# ---------------------------------------------------------------
# Final Summary
# ---------------------------------------------------------------
PHASE_ELAPSED=$(( SECONDS - PHASE_START ))
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Phase 2 Results                                    ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
report_time "Total time: ${PHASE_ELAPSED}s ($(( PHASE_ELAPSED / 60 ))m $(( PHASE_ELAPSED % 60 ))s)"
echo ""

if [[ $CASES_PASSED -eq $CASES_TOTAL ]]; then
    echo -e "${GREEN}${BOLD}  ALL PASSED: ${CASES_PASSED}/${CASES_TOTAL} cases${NC}"
else
    echo -e "${YELLOW}${BOLD}  PARTIAL: ${CASES_PASSED}/${CASES_TOTAL} cases passed${NC}"
fi

echo ""
echo -e "  Acceptance criteria:"
echo -e "    $([ $CASES_PASSED -ge 5 ] && echo "${GREEN}✓${NC}" || echo "${RED}✗${NC}") Cases passing: ${CASES_PASSED}/${CASES_TOTAL} (target: ≥5/7 for Phase 2)"
echo -e "    ${YELLOW}?${NC} Detection latency ≤ 3 min — review timing CSV"
echo -e "    ${YELLOW}?${NC} Total MTTR ≤ 10 min — review timing CSV"
echo ""

# Show timing results if available
TIMING_CSV="${SCRIPT_DIR}/.timing-results.csv"
if [[ -f "$TIMING_CSV" ]]; then
    echo -e "${BOLD}  Timing Results:${NC}"
    column -t -s',' "$TIMING_CSV" | sed 's/^/    /'
    echo ""
fi

if [[ $CASES_PASSED -eq $CASES_TOTAL ]]; then
    exit 0
else
    echo -e "  Review individual case output above for failure details."
    echo -e "  Common issues:"
    echo -e "    - AlertManager 'for' duration + group_wait can add ~6 min to detection"
    echo -e "    - Node-level cases (4) require longer recovery (~5 min)"
    echo -e "    - PVC storageClassName is immutable — executor must delete+recreate"
    echo -e "    - CoreDNS may self-recover via EKS addon controller"
    exit 1
fi
