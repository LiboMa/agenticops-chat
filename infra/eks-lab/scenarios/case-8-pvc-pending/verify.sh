#!/usr/bin/env bash
# Case 8: PVC Pending — Pipeline verification
# Validates: Alert → Issue → RCA → Fix (delete+recreate PVC) → Execute → Resolved
# Key check: bad PVC deleted or replaced with correct StorageClass

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}--- Case 8: Verify Pipeline ---${NC}\n"

CASE_START=$SECONDS
PASSED=0
TOTAL=5

# Step 1: Wait for HealthIssue creation
echo -e "\n${BOLD}Step 1/5: HealthIssue detection${NC}"
ISSUE_ID=$(wait_for_health_issue "PVC|Pending|persistent|storage" 360) || { report_fail "Step 1 failed"; ISSUE_ID=""; }
[[ -n "$ISSUE_ID" ]] && PASSED=$((PASSED + 1))

if [[ -z "$ISSUE_ID" ]]; then
    report_fail "Cannot continue without HealthIssue — aborting case 8"
    echo -e "\n${RED}Case 8: ${PASSED}/${TOTAL} steps passed${NC}"
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

# Step 5: Verify bad PVC is gone or replaced
echo -e "\n${BOLD}Step 5/5: Verify PVC fix applied${NC}"
BAD_PVC_SC=$(kubectl get pvc agenticops-bad-pvc -n online-boutique \
    -o jsonpath='{.spec.storageClassName}' 2>/dev/null || echo "DELETED")
if [[ "$BAD_PVC_SC" == "DELETED" ]]; then
    report_pass "Bad PVC agenticops-bad-pvc has been deleted"
    PASSED=$((PASSED + 1))
elif [[ "$BAD_PVC_SC" != "nonexistent-sc" ]]; then
    report_pass "PVC storageClassName changed from nonexistent-sc to ${BAD_PVC_SC}"
    PASSED=$((PASSED + 1))
else
    # Check if PVC is now Bound (maybe a matching PV was created)
    PVC_PHASE=$(kubectl get pvc agenticops-bad-pvc -n online-boutique \
        -o jsonpath='{.status.phase}' 2>/dev/null || echo "unknown")
    if [[ "$PVC_PHASE" == "Bound" ]]; then
        report_pass "PVC is now Bound (alternative fix applied)"
        PASSED=$((PASSED + 1))
    else
        report_fail "Bad PVC still exists with storageClassName=nonexistent-sc (phase: ${PVC_PHASE})"
    fi
fi

# Summary
ELAPSED=$(( SECONDS - CASE_START ))
echo ""
report_time "Case 8 total time: ${ELAPSED}s ($(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s)"
if [[ $PASSED -eq $TOTAL ]]; then
    echo -e "\n${GREEN}${BOLD}Case 8: PASSED (${PASSED}/${TOTAL})${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Case 8: FAILED (${PASSED}/${TOTAL})${NC}"
    exit 1
fi
