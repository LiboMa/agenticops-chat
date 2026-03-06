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

report_pass() { echo -e "  ${GREEN}✓ PASS${NC} $*" >&2; }
report_fail() { echo -e "  ${RED}✗ FAIL${NC} $*" >&2; }
report_info() { echo -e "  ${BLUE}ℹ${NC} $*" >&2; }
report_time() { echo -e "  ${YELLOW}⏱${NC} $*" >&2; }

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
    local max_age="${3:-10}"  # only match issues created within last N minutes
    local start=$SECONDS
    local issue_id=""

    report_info "Waiting for HealthIssue matching '${pattern}' (timeout ${timeout}s, max_age ${max_age}m)..."
    while (( SECONDS - start < timeout )); do
        local body
        body=$(api_get "/api/health-issues?limit=20")
        if [[ -n "$body" ]]; then
            issue_id=$(echo "$body" | python3 -c "
import json, re, sys
from datetime import datetime, timedelta, timezone
data = json.load(sys.stdin)
items = data if isinstance(data, list) else data.get('items', data.get('results', []))
pattern = re.compile(r'${pattern}', re.IGNORECASE)
max_age_min = ${max_age}
cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_min)
for item in items:
    # Skip already-resolved issues
    if item.get('status') in ('resolved', 'closed'):
        continue
    # Time filter: only match recent issues
    detected = item.get('detected_at', '')
    try:
        dt = datetime.fromisoformat(detected.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < cutoff:
            continue
    except (ValueError, TypeError):
        pass
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

# ---------------------------------------------------------------
# cleanup_chaos_artifacts
#   Remove all resources labelled chaos-injected=true, plus
#   restore CoreDNS if it was scaled to 0.
# ---------------------------------------------------------------
cleanup_chaos_artifacts() {
    report_info "Cleaning up chaos artifacts (label: chaos-injected=true)..."

    # Delete labelled resources in the online-boutique namespace
    for kind in job pod deploy pvc networkpolicy hpa; do
        kubectl delete "$kind" -l chaos-injected=true -n online-boutique --ignore-not-found 2>/dev/null || true
    done

    # Restore CoreDNS if scaled to 0 (Case 7)
    local coredns_replicas
    coredns_replicas=$(kubectl get deploy coredns -n kube-system \
        -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "2")
    if [[ "$coredns_replicas" == "0" ]]; then
        report_info "CoreDNS has 0 replicas — restoring to 2..."
        kubectl scale deploy/coredns -n kube-system --replicas=2
        kubectl rollout status deploy/coredns -n kube-system --timeout=60s 2>/dev/null || true
    fi

    report_pass "Chaos artifacts cleaned up"
}

# ---------------------------------------------------------------
# collect_timing CASE_NAME ELAPSED STATUS
#   Append a row to .timing-results.csv in the scenarios directory.
#   Creates the CSV with a header if it does not exist.
# ---------------------------------------------------------------
collect_timing() {
    local case_name="$1"
    local elapsed="$2"
    local status="$3"
    local csv="${BASH_SOURCE[0]%/*}/.timing-results.csv"

    if [[ ! -f "$csv" ]]; then
        echo "case,elapsed_seconds,status,timestamp" > "$csv"
    fi
    echo "${case_name},${elapsed},${status},$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$csv"
}
