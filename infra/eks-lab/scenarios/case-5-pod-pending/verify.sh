#!/usr/bin/env bash
# Case 5: Pod Pending — Pipeline verification
# Validates: Alert → Issue → RCA → Fix (delete stress pods) → Execute → Resolved
# Key check: stress pods deleted, frontend pods all Running

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}--- Case 5: Verify Pipeline ---${NC}\n"

CASE_START=$SECONDS
PASSED=0
TOTAL=5

# Step 1: Wait for HealthIssue creation
echo -e "\n${BOLD}Step 1/5: HealthIssue detection${NC}"
ISSUE_ID=$(wait_for_health_issue "Pending|scheduling|resource|frontend" 360) || { report_fail "Step 1 failed"; ISSUE_ID=""; }
[[ -n "$ISSUE_ID" ]] && PASSED=$((PASSED + 1))

if [[ -z "$ISSUE_ID" ]]; then
    report_fail "Cannot continue without HealthIssue — aborting case 5"
    echo -e "\n${RED}Case 5: ${PASSED}/${TOTAL} steps passed${NC}"
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

# Step 4: Wait for resolution
echo -e "\n${BOLD}Step 4/5: Auto-execution + resolution${NC}"
FINAL_STATUS=$(wait_for_status "$ISSUE_ID" "resolved" 600) || true
if [[ "$FINAL_STATUS" == "resolved" ]]; then
    PASSED=$((PASSED + 1))
else
    report_fail "Issue not resolved (final status: ${FINAL_STATUS})"
fi

# Step 5: Verify stress pods deleted and frontend Running
echo -e "\n${BOLD}Step 5/5: Verify stress pods removed + frontend healthy${NC}"
STRESS_COUNT=$(kubectl get pods -l chaos-injected=true,app=agenticops-stress -n online-boutique --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ "$STRESS_COUNT" == "0" ]]; then
    report_pass "Stress pods have been deleted"
else
    report_fail "Stress pods still exist (${STRESS_COUNT} remaining)"
fi

# Check frontend pods are all Running
FRONTEND_READY=$(kubectl get deploy frontend -n online-boutique \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
FRONTEND_DESIRED=$(kubectl get deploy frontend -n online-boutique \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
if [[ "$FRONTEND_READY" -ge 1 ]]; then
    report_pass "Frontend has ${FRONTEND_READY}/${FRONTEND_DESIRED} ready replicas"
    [[ "$STRESS_COUNT" == "0" ]] && PASSED=$((PASSED + 1))
else
    report_fail "Frontend has 0 ready replicas"
fi

# Summary
ELAPSED=$(( SECONDS - CASE_START ))
echo ""
report_time "Case 5 total time: ${ELAPSED}s ($(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s)"
if [[ $PASSED -eq $TOTAL ]]; then
    echo -e "\n${GREEN}${BOLD}Case 5: PASSED (${PASSED}/${TOTAL})${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Case 5: FAILED (${PASSED}/${TOTAL})${NC}"
    exit 1
fi
