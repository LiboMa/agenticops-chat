#!/usr/bin/env bash
# AgenticOps EKS Lab — Phase 1 scenario orchestrator
# Runs all 3 cases sequentially: inject → verify → cool-down
#
# Usage:
#   AGENTICOPS_URL=http://localhost:8000 bash run-phase1.sh
#
# Prerequisites:
#   - EKS cluster deployed (setup.sh)
#   - AgenticOps API running and receiving AlertManager webhooks
#   - kubectl configured

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

COOL_DOWN=30
CASES_PASSED=0
CASES_TOTAL=3
PHASE_START=$SECONDS

echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  AgenticOps Phase 1 — Closed-Loop Validation (3/10) ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
report_info "AgenticOps API: ${AGENTICOPS_URL}"
report_info "KUBECONFIG: ${KUBECONFIG}"
echo ""

# ---------------------------------------------------------------
# Case 1: OOM Kill
# ---------------------------------------------------------------
echo -e "\n${BOLD}━━━ Case 1/3: OOM Kill (adservice) ━━━${NC}"
bash "${SCRIPT_DIR}/case-1-oom/inject.sh"
if bash "${SCRIPT_DIR}/case-1-oom/verify.sh"; then
    CASES_PASSED=$((CASES_PASSED + 1))
fi

if [[ $CASES_PASSED -lt $CASES_TOTAL ]] || true; then
    report_info "Restoring clean state before next case..."
    restore_clean_state
    report_info "Cool-down ${COOL_DOWN}s..."
    sleep "$COOL_DOWN"
fi

# ---------------------------------------------------------------
# Case 2: Bad Image
# ---------------------------------------------------------------
echo -e "\n${BOLD}━━━ Case 2/3: Bad Image (productcatalogservice) ━━━${NC}"
bash "${SCRIPT_DIR}/case-2-bad-image/inject.sh"
if bash "${SCRIPT_DIR}/case-2-bad-image/verify.sh"; then
    CASES_PASSED=$((CASES_PASSED + 1))
fi

report_info "Restoring clean state before next case..."
restore_clean_state
report_info "Cool-down ${COOL_DOWN}s..."
sleep "$COOL_DOWN"

# ---------------------------------------------------------------
# Case 3: NetworkPolicy Blocking
# ---------------------------------------------------------------
echo -e "\n${BOLD}━━━ Case 3/3: NetworkPolicy Blocking (cartservice) ━━━${NC}"
bash "${SCRIPT_DIR}/case-3-network-policy/inject.sh"
if bash "${SCRIPT_DIR}/case-3-network-policy/verify.sh"; then
    CASES_PASSED=$((CASES_PASSED + 1))
fi

# Clean up any remaining chaos artifacts
kubectl delete networkpolicy agenticops-chaos-deny-cartservice -n online-boutique 2>/dev/null || true
restore_clean_state

# ---------------------------------------------------------------
# Final Summary
# ---------------------------------------------------------------
PHASE_ELAPSED=$(( SECONDS - PHASE_START ))
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Phase 1 Results                                    ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
report_time "Total time: ${PHASE_ELAPSED}s ($(( PHASE_ELAPSED / 60 ))m $(( PHASE_ELAPSED % 60 ))s)"
echo ""

if [[ $CASES_PASSED -eq $CASES_TOTAL ]]; then
    echo -e "${GREEN}${BOLD}  ✓ ALL PASSED: ${CASES_PASSED}/${CASES_TOTAL} cases${NC}"
    echo ""
    echo -e "  Acceptance criteria:"
    echo -e "    ${GREEN}✓${NC} Detection latency ≤ 3 min — verify from logs above"
    echo -e "    ${GREEN}✓${NC} Total MTTR ≤ 10 min — verify from logs above"
    echo -e "    ${GREEN}✓${NC} Cases passing: ${CASES_PASSED}/${CASES_TOTAL}"
    exit 0
else
    echo -e "${RED}${BOLD}  ✗ FAILED: ${CASES_PASSED}/${CASES_TOTAL} cases passed${NC}"
    echo ""
    echo -e "  Review individual case output above for failure details."
    echo -e "  Common issues:"
    echo -e "    - AlertManager webhook not reaching AgenticOps API"
    echo -e "    - Agent RCA/SRE prompts need tuning for specific failure mode"
    echo -e "    - Executor kubectl permissions insufficient"
    exit 1
fi
