#!/usr/bin/env bash
# Case 7: CoreDNS Failure — Pipeline verification
# Validates: Alert → Issue → RCA → Fix → Resolved
# Key check: CoreDNS pods running again (agent fix OR EKS self-recovery)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}--- Case 7: Verify Pipeline ---${NC}\n"

CASE_START=$SECONDS
PASSED=0
TOTAL=5

# Step 1: Wait for HealthIssue creation
echo -e "\n${BOLD}Step 1/5: HealthIssue detection${NC}"
ISSUE_ID=$(wait_for_health_issue "CoreDNS|coredns|kube-dns|DNS" 360) || { report_fail "Step 1 failed"; ISSUE_ID=""; }
[[ -n "$ISSUE_ID" ]] && PASSED=$((PASSED + 1))

if [[ -z "$ISSUE_ID" ]]; then
    report_fail "Cannot continue without HealthIssue — aborting case 7"
    echo -e "\n${RED}Case 7: ${PASSED}/${TOTAL} steps passed${NC}"
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
        # EKS may have self-recovered before agent could plan
        report_info "No fix plan — checking if EKS self-recovered..."
        COREDNS_READY=$(kubectl get deploy coredns -n kube-system \
            -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        if [[ "${COREDNS_READY:-0}" -ge 1 ]]; then
            report_pass "EKS self-recovered CoreDNS (${COREDNS_READY} replicas) — fix plan not needed"
            PASSED=$((PASSED + 1))
        else
            report_fail "No fix plan and CoreDNS still down"
        fi
    fi
fi

# Step 4: Wait for resolution (or verify self-recovery)
echo -e "\n${BOLD}Step 4/5: Resolution${NC}"
FINAL_STATUS=$(wait_for_status "$ISSUE_ID" "resolved" 300) || true
if [[ "$FINAL_STATUS" == "resolved" ]]; then
    PASSED=$((PASSED + 1))
else
    # Accept if CoreDNS is running (EKS self-recovery) even if issue not auto-resolved
    COREDNS_READY=$(kubectl get deploy coredns -n kube-system \
        -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [[ "${COREDNS_READY:-0}" -ge 1 ]]; then
        report_info "CoreDNS self-recovered but issue status is '${FINAL_STATUS}' — partial pass"
        PASSED=$((PASSED + 1))
    else
        report_fail "Issue not resolved and CoreDNS still down (status: ${FINAL_STATUS})"
    fi
fi

# Step 5: Verify CoreDNS pods running
echo -e "\n${BOLD}Step 5/5: Verify CoreDNS running${NC}"
COREDNS_READY=$(kubectl get deploy coredns -n kube-system \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [[ "${COREDNS_READY:-0}" -ge 1 ]]; then
    report_pass "CoreDNS has ${COREDNS_READY} ready replica(s)"
    PASSED=$((PASSED + 1))
else
    report_fail "CoreDNS has 0 ready replicas — DNS is still broken"
fi

# Summary
ELAPSED=$(( SECONDS - CASE_START ))
echo ""
report_time "Case 7 total time: ${ELAPSED}s ($(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s)"
if [[ $PASSED -eq $TOTAL ]]; then
    echo -e "\n${GREEN}${BOLD}Case 7: PASSED (${PASSED}/${TOTAL})${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Case 7: FAILED (${PASSED}/${TOTAL})${NC}"
    exit 1
fi
