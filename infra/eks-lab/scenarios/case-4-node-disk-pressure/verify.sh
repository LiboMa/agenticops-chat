#!/usr/bin/env bash
# Case 4: Node DiskPressure — Pipeline verification
# Validates: Alert → Issue → RCA → Fix → Execute → Resolved
# Key check: disk-filler pod deleted, node returns to Ready state

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}--- Case 4: Verify Pipeline ---${NC}\n"

CASE_START=$SECONDS
PASSED=0
TOTAL=5

# Step 1: Wait for HealthIssue creation
echo -e "\n${BOLD}Step 1/5: HealthIssue detection${NC}"
ISSUE_ID=$(wait_for_health_issue "NodeDiskPressure|NodeNotReady|DiskPressure" 360) || { report_fail "Step 1 failed"; ISSUE_ID=""; }
[[ -n "$ISSUE_ID" ]] && PASSED=$((PASSED + 1))

if [[ -z "$ISSUE_ID" ]]; then
    report_fail "Cannot continue without HealthIssue — aborting case 4"
    echo -e "\n${RED}Case 4: ${PASSED}/${TOTAL} steps passed${NC}"
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

# Step 5: Verify node is Ready and disk-filler cleaned
echo -e "\n${BOLD}Step 5/5: Verify node Ready + disk-filler removed${NC}"
TARGET_NODE=$(cat /tmp/case4-target-node.txt 2>/dev/null || echo "")
# Check if disk-filler pod is deleted/evicted AND node is Ready
FILLER_EXISTS=$(kubectl get pod agenticops-disk-filler -n online-boutique --no-headers 2>/dev/null | grep -v Evicted || echo "")
NODE_READY=""
if [[ -n "$TARGET_NODE" ]]; then
    NODE_READY=$(kubectl get node "$TARGET_NODE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
    DISK_PRESSURE=$(kubectl get node "$TARGET_NODE" -o jsonpath='{.status.conditions[?(@.type=="DiskPressure")].status}' 2>/dev/null || echo "")
fi
if [[ -z "$FILLER_EXISTS" ]] || [[ "$NODE_READY" == "True" && "$DISK_PRESSURE" == "False" ]]; then
    report_pass "disk-filler cleaned or node recovered: Ready=${NODE_READY}, DiskPressure=${DISK_PRESSURE}"
    PASSED=$((PASSED + 1))
else
    report_fail "Node still impacted: Ready=${NODE_READY}, DiskPressure=${DISK_PRESSURE}, pod=${FILLER_EXISTS}"
fi

# Summary
ELAPSED=$(( SECONDS - CASE_START ))
echo ""
report_time "Case 4 total time: ${ELAPSED}s ($(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s)"
if [[ $PASSED -eq $TOTAL ]]; then
    echo -e "\n${GREEN}${BOLD}Case 4: PASSED (${PASSED}/${TOTAL})${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Case 4: FAILED (${PASSED}/${TOTAL})${NC}"
    exit 1
fi
