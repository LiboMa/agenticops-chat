#!/bin/bash
# Scenario 6: Disk Full Cascade — /var fills up → log rotation fails → gunicorn can't write → 502
#
# Fault chain:
#   1. Fill /var/log with a 900MB dummy file (t3.micro has ~1GB /var free)
#   2. gunicorn access-log writes fail → worker error → intermittent 502
#   3. /health may still return 200 initially (DB SELECT 1 works)
#   4. As gunicorn workers restart on error, they can't write PID file → service degrades
#   5. Eventually: systemd restarts fail → full outage
#
# RCA challenge:
#   - CW alarm triggers on unhealthy-hosts or 5xx, but root cause is DISK, not app/DB
#   - CloudTrail has NO relevant events (no API calls caused this)
#   - Agent must check OS-level metrics (disk usage) or use run_on_host/SSM
#   - Tests the agent's ability to go beyond CloudWatch into host-level investigation
#
# Detection: ALB 5xx → ALARM → Agent
# Recovery: Remove the dummy file
#
# Usage: bash 06-disk-full-cascade.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

case "$action" in
    inject)
        log "=== Scenario 6: Disk Full Cascade ==="
        log "Pre-check: health=$(check_health)"

        # Check current disk usage
        log "Pre-check: disk usage on /var..."
        ssm_run_wait 'df -h /var | tail -1'

        log "Injecting fault: filling /var/log with 900MB dummy file..."
        ssm_run_wait 'dd if=/dev/zero of=/var/log/weblab-dummy-fill.dat bs=1M count=900 2>&1 || echo "dd completed (disk may be full)"'

        log "Waiting 5s for effects to propagate..."
        sleep 5

        # Trigger log writes by sending requests
        log "Sending traffic to trigger log write failures..."
        for i in $(seq 1 20); do
            curl -sk "${APP_URL}/health" --connect-timeout 3 --max-time 5 > /dev/null 2>&1 &
        done
        wait

        log ""
        log "=== Symptom Verification ==="

        health_code=$(check_health)
        log "  /health            -> $health_code"

        login_get=$(curl -sk -o /dev/null -w '%{http_code}' \
            "${APP_URL}/login" --connect-timeout 5 --max-time 10 2>/dev/null || echo "000")
        log "  /login GET         -> $login_get"

        log ""
        log "  Disk usage after fill:"
        ssm_run_wait 'df -h /var | tail -1'

        log ""
        log "  gunicorn error log (last 10 lines):"
        ssm_run_wait 'tail -10 /var/log/weblab-error.log 2>/dev/null || echo "cannot read error log"'

        log ""
        log "  systemd journal (weblab, last 20 lines):"
        ssm_run_wait 'journalctl -u weblab --no-pager -n 20 2>/dev/null || echo "cannot read journal"'

        log ""
        log "=== Fault Active ==="
        log "Disk is full. gunicorn may fail intermittently due to log write errors."
        log "CloudTrail will show NO relevant API changes — this is a host-level issue."
        log "Agent must investigate OS-level metrics or use SSM to diagnose."
        log ""
        log "Run: bash $0 recover"
        ;;

    verify)
        log "=== Verifying Scenario 6 ==="

        health_code=$(check_health)
        log "Health check: $health_code"

        log "Disk usage:"
        ssm_run_wait 'df -h / /var 2>/dev/null || df -h /'

        log ""
        log "Dummy file exists?"
        ssm_run_wait 'ls -lh /var/log/weblab-dummy-fill.dat 2>/dev/null || echo "NOT FOUND"'

        log ""
        log "gunicorn process:"
        ssm_run_wait 'ps aux | grep gunicorn | grep -v grep || echo "gunicorn not running"'

        log ""
        log "weblab service status:"
        ssm_run_wait 'systemctl status weblab --no-pager -l 2>/dev/null | head -20'

        log ""
        log "Recent errors:"
        ssm_run_wait 'tail -20 /var/log/weblab-error.log 2>/dev/null || echo "no error log"'

        log ""
        log "CW Alarms:"
        aws cloudwatch describe-alarms --alarm-name-prefix "weblab-" \
            --region "$REGION" \
            --query 'MetricAlarms[*].[AlarmName,StateValue]' --output text | \
            while read name state; do
                log "  $name -> $state"
            done
        ;;

    recover)
        log "=== Recovering Scenario 6 ==="

        log "Removing dummy fill file..."
        ssm_run_wait 'rm -f /var/log/weblab-dummy-fill.dat && echo "removed"'

        log "Disk after cleanup:"
        ssm_run_wait 'df -h /var | tail -1'

        log "Restarting weblab service..."
        ssm_run_wait 'systemctl restart weblab'

        sleep 5
        wait_for_health 200 90
        log "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
