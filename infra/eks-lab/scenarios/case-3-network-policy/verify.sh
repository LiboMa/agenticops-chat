#!/usr/bin/env bash
# Case 3: Redis Dependency Failure — Pipeline verification
# Validates the full auto-fix pipeline for redis-cart unavailability
# Key check: redis-cart has ≥1 ready replica after fix

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}--- Case 3: Verify Pipeline ---${NC}\n"

CASE_START=$SECONDS
PASSED=0
TOTAL=5

# Step 1: Wait for HealthIssue creation
echo -e "\n${BOLD}Step 1/5: HealthIssue detection${NC}"
ISSUE_ID=$(wait_for_health_issue "CrashLoop|ReplicasMismatch|redis|cart" 360) || { report_fail "Step 1 failed"; ISSUE_ID=""; }
[[ -n "$ISSUE_ID" ]] && PASSED=$((PASSED + 1))

if [[ -z "$ISSUE_ID" ]]; then
    report_fail "Cannot continue without HealthIssue — aborting case 3"
    echo -e "\n${RED}Case 3: ${PASSED}/${TOTAL} steps passed${NC}"
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

# Step 5: Verify redis-cart is back and Running
echo -e "\n${BOLD}Step 5/5: Verify redis-cart recovered${NC}"
REDIS_READY=$(kubectl get deploy redis-cart -n online-boutique \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [[ "${REDIS_READY:-0}" -ge 1 ]]; then
    report_pass "redis-cart has ${REDIS_READY} ready replica(s)"
    PASSED=$((PASSED + 1))
else
    report_fail "redis-cart still has ${REDIS_READY:-0} ready replicas"
fi

# Summary
ELAPSED=$(( SECONDS - CASE_START ))
echo ""
report_time "Case 3 total time: ${ELAPSED}s ($(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s)"
if [[ $PASSED -eq $TOTAL ]]; then
    echo -e "\n${GREEN}${BOLD}Case 3: PASSED (${PASSED}/${TOTAL})${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Case 3: FAILED (${PASSED}/${TOTAL})${NC}"
    exit 1
fi
