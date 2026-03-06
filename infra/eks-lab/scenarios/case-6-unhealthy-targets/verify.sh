#!/usr/bin/env bash
# Case 6: Unhealthy LB Targets — Pipeline verification
# Validates: Alert → Issue → RCA → Fix (rollback deployment) → Execute → Resolved
# Key check: checkoutservice pods become Ready after rollback

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}--- Case 6: Verify Pipeline ---${NC}\n"

CASE_START=$SECONDS
PASSED=0
TOTAL=5

# Step 1: Wait for HealthIssue creation
echo -e "\n${BOLD}Step 1/5: HealthIssue detection${NC}"
ISSUE_ID=$(wait_for_health_issue "NotReady|TargetDown|checkoutservice|unhealthy" 360) || { report_fail "Step 1 failed"; ISSUE_ID=""; }
[[ -n "$ISSUE_ID" ]] && PASSED=$((PASSED + 1))

if [[ -z "$ISSUE_ID" ]]; then
    report_fail "Cannot continue without HealthIssue — aborting case 6"
    echo -e "\n${RED}Case 6: ${PASSED}/${TOTAL} steps passed${NC}"
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
    for wait in 30 30 30 30 30 30; do
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

# Auto-approve L2/L3 fix plans (simulates human approval during validation)
if [[ -n "$FIX_INFO" ]]; then
    FIX_PLAN_ID=$(echo "$FIX_INFO" | cut -d'|' -f1 | tr -d ' ')
    FIX_STATUS=$(echo "$FIX_INFO" | cut -d'|' -f2 | tr -d ' ')
    FIX_LEVEL=$(echo "$FIX_INFO" | cut -d'|' -f3 | tr -d ' ')
    if [[ "$FIX_STATUS" == "planned" && ("$FIX_LEVEL" == "L2" || "$FIX_LEVEL" == "L3") ]]; then
        report_info "Fix plan is ${FIX_LEVEL} (requires human approval) — auto-approving for validation..."
        APPROVE_RESP=$(curl -s -X PUT "${AGENTICOPS_URL}/api/fix-plans/${FIX_PLAN_ID}/approve" \
            -H "Content-Type: application/json" \
            -d '{"approved_by": "validation-script"}')
        report_info "Approve response: ${APPROVE_RESP}"
        sleep 5
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

# Step 5: Verify checkoutservice pods are Ready
echo -e "\n${BOLD}Step 5/5: Verify checkoutservice pods Ready${NC}"
READY_REPLICAS=$(kubectl get deploy checkoutservice -n online-boutique \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
DESIRED_REPLICAS=$(kubectl get deploy checkoutservice -n online-boutique \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
if [[ "${READY_REPLICAS:-0}" -ge 1 && "${READY_REPLICAS}" == "${DESIRED_REPLICAS}" ]]; then
    report_pass "checkoutservice: ${READY_REPLICAS}/${DESIRED_REPLICAS} replicas Ready (rollback successful)"
    PASSED=$((PASSED + 1))
else
    report_fail "checkoutservice: ${READY_REPLICAS:-0}/${DESIRED_REPLICAS} replicas Ready — rollback may not have been applied"
fi

# Summary
ELAPSED=$(( SECONDS - CASE_START ))
echo ""
report_time "Case 6 total time: ${ELAPSED}s ($(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s)"
if [[ $PASSED -eq $TOTAL ]]; then
    echo -e "\n${GREEN}${BOLD}Case 6: PASSED (${PASSED}/${TOTAL})${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Case 6: FAILED (${PASSED}/${TOTAL})${NC}"
    exit 1
fi
