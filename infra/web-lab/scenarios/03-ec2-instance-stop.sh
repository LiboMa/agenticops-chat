#!/bin/bash
# Scenario 3: EC2 Instance Stop — stop the entire EC2 instance
#
# Fault: aws ec2 stop-instances
# Expected: ALB → all targets unhealthy → ALARM + canary failure
#           → SNS → Lambda → Feishu alert → Agent → HealthIssue → RCA
# Recovery: aws ec2 start-instances (Agent should identify stopped instance)
#
# Usage: bash 03-ec2-instance-stop.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

case "$action" in
    inject)
        log "=== Scenario 3: EC2 Instance Stop ==="
        log "Pre-check: $(check_health)"

        log "Injecting fault: stopping EC2 instance $INSTANCE_ID..."
        aws ec2 stop-instances \
            --instance-ids "$INSTANCE_ID" \
            --region "$REGION" \
            --query 'StoppingInstances[0].CurrentState.Name' --output text

        log "Waiting for instance to stop..."
        aws ec2 wait instance-stopped \
            --instance-ids "$INSTANCE_ID" \
            --region "$REGION"
        log "Instance stopped."

        log "Fault injected. Both weblab-unhealthy-hosts and weblab-canary-failed alarms should fire."
        ;;

    verify)
        log "=== Verifying Scenario 3 ==="
        state=$(aws ec2 describe-instances \
            --instance-ids "$INSTANCE_ID" \
            --region "$REGION" \
            --query 'Reservations[0].Instances[0].State.Name' --output text)
        log "Instance state: $state"

        code=$(check_health)
        log "App health: $code"

        for alarm in weblab-unhealthy-hosts weblab-canary-failed; do
            alarm_state=$(aws cloudwatch describe-alarms \
                --alarm-names "$alarm" \
                --region "$REGION" \
                --query 'MetricAlarms[0].StateValue' --output text)
            log "Alarm $alarm: $alarm_state"
        done
        ;;

    recover)
        log "=== Recovering Scenario 3 ==="
        log "Starting EC2 instance $INSTANCE_ID..."
        aws ec2 start-instances \
            --instance-ids "$INSTANCE_ID" \
            --region "$REGION" \
            --query 'StartingInstances[0].CurrentState.Name' --output text

        log "Waiting for instance to run..."
        aws ec2 wait instance-running \
            --instance-ids "$INSTANCE_ID" \
            --region "$REGION"
        log "Instance running. Waiting for app to come up..."

        # App takes ~30-60s after instance start (userdata service)
        wait_for_health 200 180
        log "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
