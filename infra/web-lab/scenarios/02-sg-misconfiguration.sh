#!/bin/bash
# Scenario 2: Security Group Misconfiguration — revoke ALB→EC2 ingress
#
# Fault: Remove port 5000 ingress rule from EC2 security group
# Expected: ALB can't reach EC2 → unhealthy target → ALARM
#           → SNS → Lambda → Feishu alert → Agent → HealthIssue → RCA
# Recovery: Re-add the ingress rule (Agent should identify SG issue)
#
# Usage: bash 02-sg-misconfiguration.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

EC2_SG_ID=$(get_sg_id "EC2SecurityGroup")
ALB_SG_ID=$(get_sg_id "ALBSecurityGroup")
STATE_FILE="/tmp/weblab-sg-state.json"

log "EC2 SG: $EC2_SG_ID, ALB SG: $ALB_SG_ID"

case "$action" in
    inject)
        log "=== Scenario 2: Security Group Misconfiguration ==="
        log "Pre-check: $(check_health)"

        # Save current state for recovery
        echo "{\"ec2_sg\": \"$EC2_SG_ID\", \"alb_sg\": \"$ALB_SG_ID\"}" > "$STATE_FILE"

        log "Injecting fault: revoking ALB→EC2 ingress on port 5000..."
        aws ec2 revoke-security-group-ingress \
            --group-id "$EC2_SG_ID" \
            --protocol tcp \
            --port 5000 \
            --source-group "$ALB_SG_ID" \
            --region "$REGION"

        log "Verifying fault injection..."
        wait_for_unhealthy 90

        log "Fault injected. EC2 SG no longer allows ALB traffic on port 5000."
        log "CloudWatch alarm 'weblab-unhealthy-hosts' should fire within 2-3 minutes."
        ;;

    verify)
        log "=== Verifying Scenario 2 ==="
        code=$(check_health)
        log "App health: $code"

        alarm_state=$(aws cloudwatch describe-alarms \
            --alarm-names weblab-unhealthy-hosts \
            --region "$REGION" \
            --query 'MetricAlarms[0].StateValue' --output text)
        log "Alarm state: $alarm_state"

        # Check SG rules
        log "EC2 SG inbound rules:"
        aws ec2 describe-security-groups \
            --group-ids "$EC2_SG_ID" \
            --region "$REGION" \
            --query 'SecurityGroups[0].IpPermissions[*].{Proto:IpProtocol,FromPort:FromPort,ToPort:ToPort,Sources:UserIdGroupPairs[*].GroupId}' \
            --output table
        ;;

    recover)
        log "=== Recovering Scenario 2 ==="
        log "Re-adding ALB→EC2 ingress on port 5000..."
        aws ec2 authorize-security-group-ingress \
            --group-id "$EC2_SG_ID" \
            --protocol tcp \
            --port 5000 \
            --source-group "$ALB_SG_ID" \
            --region "$REGION" 2>/dev/null || log "  (rule may already exist)"

        wait_for_health 200 120
        log "Recovery complete."
        rm -f "$STATE_FILE"
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
