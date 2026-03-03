#!/usr/bin/env bash
# Case 1: OOM Kill — Pipeline verification
# Validates the full auto-fix pipeline: Alert → Issue → RCA → Fix → Execute → Resolved

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}--- Case 1: Verify Pipeline ---${NC}\n"

CASE_START=$SECONDS
PASSED=0
TOTAL=5

# Step 1: Wait for HealthIssue creation
echo -e "\n${BOLD}Step 1/5: HealthIssue detection${NC}"
ISSUE_ID=$(wait_for_health_issue "oomkill|crashloop|adservice|OOM" 180) || { report_fail "Step 1 failed"; ISSUE_ID=""; }
[[ -n "$ISSUE_ID" ]] && PASSED=$((PASSED + 1))

if [[ -z "$ISSUE_ID" ]]; then
    report_fail "Cannot continue without HealthIssue — aborting case 1"
    echo -e "\n${RED}Case 1: ${PASSED}/${TOTAL} steps passed${NC}"
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
    # Wait a bit more — SRE agent may still be running
    report_info "No fix plan yet, waiting..."
    sleep 30
    FIX_INFO=$(get_fix_plan "$ISSUE_ID")
    if [[ -n "$FIX_INFO" ]]; then
        report_pass "Fix plan found: ${FIX_INFO}"
        PASSED=$((PASSED + 1))
    else
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

# Step 5: Verify fix applied — memory limit should no longer be 32Mi
echo -e "\n${BOLD}Step 5/5: Verify fix applied${NC}"
CURRENT_LIMIT=$(kubectl get deploy adservice -n online-boutique \
    -o jsonpath='{.spec.template.spec.containers[0].resources.limits.memory}' 2>/dev/null || echo "unknown")
if [[ "$CURRENT_LIMIT" != "32Mi" ]]; then
    report_pass "adservice memory limit is now ${CURRENT_LIMIT} (no longer 32Mi)"
    PASSED=$((PASSED + 1))
else
    report_fail "adservice memory limit is still 32Mi — fix was not applied"
fi

# Summary
ELAPSED=$(( SECONDS - CASE_START ))
echo ""
report_time "Case 1 total time: ${ELAPSED}s ($(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s)"
if [[ $PASSED -eq $TOTAL ]]; then
    echo -e "\n${GREEN}${BOLD}Case 1: PASSED (${PASSED}/${TOTAL})${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Case 1: FAILED (${PASSED}/${TOTAL})${NC}"
    exit 1
fi
