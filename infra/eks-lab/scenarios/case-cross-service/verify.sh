#!/usr/bin/env bash
# Case Cross-Service: Redis Latency Cascade — Pipeline verification
# Validates: Alert → Issue → RCA (with trace evidence) → Fix → Execute → Resolved
# Key check: RCA root_cause mentions redis, NOT just frontend

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}--- Case Cross-Service: Verify Pipeline ---${NC}\n"

CASE_START=$SECONDS
PASSED=0
TOTAL=7

# Step 1: Wait for HealthIssue creation (frontend alert)
echo -e "\n${BOLD}Step 1/7: HealthIssue detection${NC}"
ISSUE_ID=$(wait_for_health_issue "HighErrorRate|HighLatency|frontend|5xx" 180) || { report_fail "Step 1 failed"; ISSUE_ID=""; }
[[ -n "$ISSUE_ID" ]] && PASSED=$((PASSED + 1))

if [[ -z "$ISSUE_ID" ]]; then
    report_fail "Cannot continue without HealthIssue — aborting"
    echo -e "\n${RED}Case Cross-Service: ${PASSED}/${TOTAL} steps passed${NC}"
    exit 1
fi

# Step 2: Wait for RCA completion
echo -e "\n${BOLD}Step 2/7: Root Cause Analysis${NC}"
if wait_for_status "$ISSUE_ID" "root_cause_identified|fix_planned|fix_approved|fix_executed|resolved" 300 >/dev/null; then
    PASSED=$((PASSED + 1))
else
    report_fail "RCA did not complete in time"
fi

# Step 3: Wait for fix plan creation
echo -e "\n${BOLD}Step 3/7: Fix Plan creation${NC}"
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
echo -e "\n${BOLD}Step 4/7: Auto-execution + resolution${NC}"
FINAL_STATUS=$(wait_for_status "$ISSUE_ID" "resolved" 600) || true
if [[ "$FINAL_STATUS" == "resolved" ]]; then
    PASSED=$((PASSED + 1))
else
    report_fail "Issue not resolved (final status: ${FINAL_STATUS})"
fi

# Step 5: Verify fix applied — redis-cart resources should be restored
echo -e "\n${BOLD}Step 5/7: Verify redis-cart resources restored${NC}"
CURRENT_CPU=$(kubectl get deploy redis-cart -n online-boutique \
    -o jsonpath='{.spec.template.spec.containers[0].resources.limits.cpu}' 2>/dev/null || echo "unknown")
if [[ "$CURRENT_CPU" != "10m" ]]; then
    report_pass "redis-cart CPU limit is now ${CURRENT_CPU} (no longer 10m)"
    PASSED=$((PASSED + 1))
else
    report_fail "redis-cart CPU limit is still 10m — fix was not applied"
fi

# Step 6: Verify RCA root_cause mentions redis (not just frontend)
echo -e "\n${BOLD}Step 6/7: Verify RCA identifies downstream root cause${NC}"
RCA_BODY=$(api_get "/api/health-issues/${ISSUE_ID}")
if [[ -n "$RCA_BODY" ]]; then
    RCA_ROOT_CAUSE=$(echo "$RCA_BODY" | python3 -c "
import json, sys
data = json.load(sys.stdin)
rca = data.get('rca_result', data.get('root_cause', ''))
if isinstance(rca, dict):
    rca = rca.get('root_cause', '')
print(str(rca).lower())
" 2>/dev/null || echo "")
    if echo "$RCA_ROOT_CAUSE" | grep -qi "redis"; then
        report_pass "RCA root_cause mentions redis (downstream identification: correct)"
        PASSED=$((PASSED + 1))
    else
        report_fail "RCA root_cause does not mention redis: '${RCA_ROOT_CAUSE}'"
    fi
else
    report_fail "Could not fetch issue details"
fi

# Step 7: Verify RCA confidence > 0.7 (trace evidence should boost confidence)
echo -e "\n${BOLD}Step 7/7: Verify RCA confidence > 0.7${NC}"
if [[ -n "$RCA_BODY" ]]; then
    CONFIDENCE=$(echo "$RCA_BODY" | python3 -c "
import json, sys
data = json.load(sys.stdin)
rca = data.get('rca_result', {})
if isinstance(rca, dict):
    print(rca.get('confidence', 0))
else:
    print(0)
" 2>/dev/null || echo "0")
    if python3 -c "exit(0 if float('${CONFIDENCE}') > 0.7 else 1)" 2>/dev/null; then
        report_pass "RCA confidence: ${CONFIDENCE} (> 0.7, trace evidence helped)"
        PASSED=$((PASSED + 1))
    else
        report_fail "RCA confidence: ${CONFIDENCE} (expected > 0.7)"
    fi
else
    report_fail "Could not fetch RCA confidence"
fi

# Summary
ELAPSED=$(( SECONDS - CASE_START ))
echo ""
report_time "Case Cross-Service total time: ${ELAPSED}s ($(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s)"
if [[ $PASSED -eq $TOTAL ]]; then
    echo -e "\n${GREEN}${BOLD}Case Cross-Service: PASSED (${PASSED}/${TOTAL})${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Case Cross-Service: FAILED (${PASSED}/${TOTAL})${NC}"
    exit 1
fi
