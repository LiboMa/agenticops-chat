#!/usr/bin/env bash
# AgenticOps EKS Lab — Scenario framework shared functions
# Sourced by inject.sh, verify.sh, and run-phase1.sh
#
# Provides API polling helpers for the full auto-fix pipeline:
#   Alert → HealthIssue → RCA → SRE fix plan → approve → execute → resolved

# Config (override via env vars)
AGENTICOPS_URL="${AGENTICOPS_URL:-http://localhost:8000}"
KUBECONFIG="${KUBECONFIG:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/kubeconfig}"
export KUBECONFIG

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

report_pass() { echo -e "  ${GREEN}✓ PASS${NC} $*"; }
report_fail() { echo -e "  ${RED}✗ FAIL${NC} $*"; }
report_info() { echo -e "  ${BLUE}ℹ${NC} $*"; }
report_time() { echo -e "  ${YELLOW}⏱${NC} $*"; }

# ---------------------------------------------------------------
# api_get PATH
#   GET the AgenticOps REST API. Returns JSON body.
# ---------------------------------------------------------------
api_get() {
    curl -sf "${AGENTICOPS_URL}${1}" 2>/dev/null || echo ""
}

# ---------------------------------------------------------------
# wait_for_health_issue TITLE_PATTERN TIMEOUT_SECONDS
#   Poll GET /api/health-issues until an issue whose title matches
#   the grep -iE pattern appears. Returns the issue ID on stdout.
#   Exits 1 on timeout.
# ---------------------------------------------------------------
wait_for_health_issue() {
    local pattern="$1"
    local timeout="${2:-180}"
    local start=$SECONDS
    local issue_id=""

    report_info "Waiting for HealthIssue matching '${pattern}' (timeout ${timeout}s)..."
    while (( SECONDS - start < timeout )); do
        local body
        body=$(api_get "/api/health-issues?limit=20")
        if [[ -n "$body" ]]; then
            issue_id=$(echo "$body" | python3 -c "
import json, re, sys
data = json.load(sys.stdin)
items = data if isinstance(data, list) else data.get('items', data.get('results', []))
pattern = re.compile(r'${pattern}', re.IGNORECASE)
for item in items:
    title = item.get('title', '') + ' ' + item.get('description', '')
    if pattern.search(title):
        print(item['id'])
        break
" 2>/dev/null || echo "")
        fi
        if [[ -n "$issue_id" ]]; then
            local elapsed=$(( SECONDS - start ))
            report_pass "HealthIssue found: ID=${issue_id} (${elapsed}s)"
            echo "$issue_id"
            return 0
        fi
        sleep 5
    done
    report_fail "Timed out waiting for HealthIssue matching '${pattern}'"
    return 1
}

# ---------------------------------------------------------------
# wait_for_status ISSUE_ID TARGET_STATUSES TIMEOUT_SECONDS
#   Poll GET /api/health-issues/{id} until status matches one of
#   the pipe-separated target statuses (e.g. "resolved|closed").
#   Returns the final status on stdout.
# ---------------------------------------------------------------
wait_for_status() {
    local issue_id="$1"
    local targets="$2"
    local timeout="${3:-300}"
    local start=$SECONDS
    local current_status=""

    report_info "Waiting for issue ${issue_id} to reach status '${targets}' (timeout ${timeout}s)..."
    while (( SECONDS - start < timeout )); do
        local body
        body=$(api_get "/api/health-issues/${issue_id}")
        if [[ -n "$body" ]]; then
            current_status=$(echo "$body" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
            if echo "$current_status" | grep -qiE "^(${targets})$"; then
                local elapsed=$(( SECONDS - start ))
                report_pass "Issue ${issue_id} reached status '${current_status}' (${elapsed}s)"
                echo "$current_status"
                return 0
            fi
            # Print progress every 30s
            if (( (SECONDS - start) % 30 < 5 )); then
                report_info "  Current status: ${current_status} ($(( SECONDS - start ))s elapsed)"
            fi
        fi
        sleep 5
    done
    report_fail "Timed out — issue ${issue_id} stuck at '${current_status}' (wanted '${targets}')"
    echo "$current_status"
    return 1
}

# ---------------------------------------------------------------
# get_fix_plan ISSUE_ID
#   Query fix plans for the given health issue.
#   Returns "plan_id|status|risk_level" or empty string.
# ---------------------------------------------------------------
get_fix_plan() {
    local issue_id="$1"
    local body
    body=$(api_get "/api/fix-plans?health_issue_id=${issue_id}")
    if [[ -n "$body" ]]; then
        echo "$body" | python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data if isinstance(data, list) else data.get('items', data.get('results', []))
if items:
    p = items[0]
    print(f\"{p['id']}|{p.get('status','')}|{p.get('risk_level','')}\")
" 2>/dev/null || echo ""
    fi
}

# ---------------------------------------------------------------
# restore_clean_state
#   Restore Online Boutique deployments from clean snapshot.
# ---------------------------------------------------------------
restore_clean_state() {
    local snapshot="${BASH_SOURCE[0]%/*}/.clean-state.yaml"
    if [[ -f "$snapshot" ]]; then
        report_info "Restoring clean state from snapshot..."
        kubectl apply -f "$snapshot" -n online-boutique 2>/dev/null || true
        kubectl rollout status deploy --all -n online-boutique --timeout=120s 2>/dev/null || true
        report_pass "Clean state restored"
    else
        report_info "No clean-state snapshot found — skipping restore"
    fi
}
