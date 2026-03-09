#!/bin/bash
# Scenario 4: RDS Connection Blocked — revoke EC2→RDS ingress on port 3306
#
# Fault: Remove port 3306 ingress rule from RDS security group
# Expected: Flask /health returns 503 (DB connection fails) → ALB unhealthy
#           → canary fails → ALARM → SNS → Lambda → Feishu alert → Agent → RCA
# Recovery: Re-add the ingress rule
#
# Usage: bash 04-rds-connection-blocked.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

RDS_SG_ID=$(get_sg_id "RDSSecurityGroup")
EC2_SG_ID=$(get_sg_id "EC2SecurityGroup")

log "RDS SG: $RDS_SG_ID, EC2 SG: $EC2_SG_ID"

case "$action" in
    inject)
        log "=== Scenario 4: RDS Connection Blocked ==="
        log "Pre-check: $(check_health)"

        log "Injecting fault: revoking EC2→RDS ingress on port 3306..."
        aws ec2 revoke-security-group-ingress \
            --group-id "$RDS_SG_ID" \
            --protocol tcp \
            --port 3306 \
            --source-group "$EC2_SG_ID" \
            --region "$REGION"

        log "Waiting for DB connections to time out..."
        # Existing connections may persist; new health checks will fail
        # pymysql connect_timeout=5, so health check should fail within 5-10s
        sleep 15

        log "Verifying fault..."
        code=$(check_health)
        log "App health: $code (expected: 503 or connection timeout)"

        log "Fault injected. /health returns 503 because DB is unreachable."
        log "CloudWatch alarms should fire within 2-3 minutes."
        ;;

    verify)
        log "=== Verifying Scenario 4 ==="
        code=$(check_health)
        log "App health: $code"

        # Check full health response
        response=$(curl -sk "${APP_URL}/health" --connect-timeout 5 --max-time 10 2>/dev/null || echo '{"error":"timeout"}')
        log "Health response: $response"

        for alarm in weblab-unhealthy-hosts weblab-canary-failed; do
            alarm_state=$(aws cloudwatch describe-alarms \
                --alarm-names "$alarm" \
                --region "$REGION" \
                --query 'MetricAlarms[0].StateValue' --output text)
            log "Alarm $alarm: $alarm_state"
        done

        # Check RDS SG rules
        log "RDS SG inbound rules:"
        aws ec2 describe-security-groups \
            --group-ids "$RDS_SG_ID" \
            --region "$REGION" \
            --query 'SecurityGroups[0].IpPermissions' \
            --output json
        ;;

    recover)
        log "=== Recovering Scenario 4 ==="
        log "Re-adding EC2→RDS ingress on port 3306..."
        aws ec2 authorize-security-group-ingress \
            --group-id "$RDS_SG_ID" \
            --protocol tcp \
            --port 3306 \
            --source-group "$EC2_SG_ID" \
            --region "$REGION" 2>/dev/null || log "  (rule may already exist)"

        log "Waiting for health to recover..."
        wait_for_health 200 90
        log "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
