#!/usr/bin/env bash
# Case 9: HPA Not Scaling — Pipeline verification
# Validates: Alert → Issue → RCA → Fix (patch maxReplicas) → Execute → Resolved
# Key check: HPA maxReplicas > 1

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}--- Case 9: Verify Pipeline ---${NC}\n"

CASE_START=$SECONDS
PASSED=0
TOTAL=5

# Step 1: Wait for HealthIssue creation
echo -e "\n${BOLD}Step 1/5: HealthIssue detection${NC}"
ISSUE_ID=$(wait_for_health_issue "HPA|autoscal|maxReplicas|maxed|frontend" 360) || { report_fail "Step 1 failed"; ISSUE_ID=""; }
[[ -n "$ISSUE_ID" ]] && PASSED=$((PASSED + 1))

if [[ -z "$ISSUE_ID" ]]; then
    report_fail "Cannot continue without HealthIssue — aborting case 9"
    echo -e "\n${RED}Case 9: ${PASSED}/${TOTAL} steps passed${NC}"
    exit 1
fi

# Step 2: Wait for RCA completion
echo -e "\n${BOLD}Step 2/5: Root Cause Analysis${NC}"
if wait_for_status "$ISSUE_ID" "root_cause_identified|fix_planned|fix_approved|fix_executed|resolved" 300 >/dev/null; then
    PASSED=$((PASSED + 1))
else
    report_fail "RCA did not complete in time"
fi

# Step 3: Wait for fix plan creation
echo -e "\n${BOLD}Step 3/5: Fix Plan creation${NC}"
FIX_INFO=$(get_fix_plan "$ISSUE_ID")
if [[ -n "$FIX_INFO" ]]; then
    report_pass "Fix plan found: ${FIX_INFO}"
    PASSED=$((PASSED + 1))
else
    for wait in 30 30 30; do
        report_info "No fix plan yet, waiting ${wait}s..."
        sleep "$wait"
        FIX_INFO=$(get_fix_plan "$ISSUE_ID")
        if [[ -n "$FIX_INFO" ]]; then
            report_pass "Fix plan found: ${FIX_INFO}"
            PASSED=$((PASSED + 1))
            break
        fi
    done
    if [[ -z "$FIX_INFO" ]]; then
        report_fail "No fix plan created for issue ${ISSUE_ID}"
    fi
fi

# Step 4: Wait for resolution
echo -e "\n${BOLD}Step 4/5: Auto-execution + resolution${NC}"
FINAL_STATUS=$(wait_for_status "$ISSUE_ID" "resolved" 600) || true
if [[ "$FINAL_STATUS" == "resolved" ]]; then
    PASSED=$((PASSED + 1))
else
    report_fail "Issue not resolved (final status: ${FINAL_STATUS})"
fi

# Step 5: Verify HPA maxReplicas > 1
echo -e "\n${BOLD}Step 5/5: Verify HPA maxReplicas patched${NC}"
MAX_REPLICAS=$(kubectl get hpa frontend-hpa -n online-boutique \
    -o jsonpath='{.spec.maxReplicas}' 2>/dev/null || echo "0")
if [[ "$MAX_REPLICAS" -gt 1 ]]; then
    report_pass "HPA maxReplicas is now ${MAX_REPLICAS} (was 1)"
    PASSED=$((PASSED + 1))
elif [[ "$MAX_REPLICAS" == "0" ]]; then
    # HPA may have been deleted entirely (also a valid fix)
    HPA_EXISTS=$(kubectl get hpa frontend-hpa -n online-boutique --no-headers 2>/dev/null || echo "")
    if [[ -z "$HPA_EXISTS" ]]; then
        report_pass "HPA frontend-hpa was deleted (valid fix — removes scaling constraint)"
        PASSED=$((PASSED + 1))
    else
        report_fail "HPA maxReplicas is still ${MAX_REPLICAS}"
    fi
else
    report_fail "HPA maxReplicas is still ${MAX_REPLICAS} — fix was not applied"
fi

# Summary
ELAPSED=$(( SECONDS - CASE_START ))
echo ""
report_time "Case 9 total time: ${ELAPSED}s ($(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s)"
if [[ $PASSED -eq $TOTAL ]]; then
    echo -e "\n${GREEN}${BOLD}Case 9: PASSED (${PASSED}/${TOTAL})${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Case 9: FAILED (${PASSED}/${TOTAL})${NC}"
    exit 1
fi
