#!/bin/bash
# Scenario 1: Flask Service Crash — stop gunicorn → ALB health check fails
#
# Fault: systemctl stop weblab (kills gunicorn process)
# Expected: ALB → unhealthy target → weblab-unhealthy-hosts ALARM
#           → SNS → Lambda → Feishu alert → Agent → HealthIssue → RCA
# Recovery: systemctl start weblab (Agent should identify and fix via SSM)
#
# Usage: bash 01-flask-crash.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

case "$action" in
    inject)
        log "=== Scenario 1: Flask Service Crash ==="
        log "Pre-check: $(check_health)"

        log "Injecting fault: stopping weblab service..."
        ssm_run_wait "systemctl stop weblab"

        log "Verifying fault injection..."
        wait_for_unhealthy 90

        log "Fault injected. ALB should detect unhealthy target within 60-90s."
        log "CloudWatch alarm 'weblab-unhealthy-hosts' should fire within 2-3 minutes."
        log ""
        log "Monitor: aws cloudwatch describe-alarms --alarm-names weblab-unhealthy-hosts --region $REGION --query 'MetricAlarms[0].StateValue' --output text"
        ;;

    verify)
        log "=== Verifying Scenario 1 ==="
        code=$(check_health)
        log "App health: $code"

        alarm_state=$(aws cloudwatch describe-alarms \
            --alarm-names weblab-unhealthy-hosts \
            --region "$REGION" \
            --query 'MetricAlarms[0].StateValue' --output text)
        log "Alarm state: $alarm_state"

        svc_status=$(ssm_run_wait "systemctl is-active weblab 2>/dev/null || echo inactive")
        log "Service status: $svc_status"
        ;;

    recover)
        log "=== Recovering Scenario 1 ==="
        log "Starting weblab service..."
        ssm_run_wait "systemctl start weblab"

        wait_for_health 200 90
        log "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
