#!/bin/bash
# Scenario 8: Route Table Blackhole — break NAT Gateway route → EC2 loses internet + RDS DNS
#
# Fault chain:
#   1. Replace the private subnet's default route (0.0.0.0/0 → NAT GW) with a blackhole
#   2. EC2 can still reach RDS via VPC internal routing (same VPC, private IPs)
#   3. BUT: EC2 loses internet access → can't reach external services
#   4. More subtly: if app depends on any external DNS/API calls, those fail
#   5. ALB → EC2 still works (ALB is in public subnet, routes to EC2 private IP directly within VPC)
#   6. /health → 200 (DB still reachable via VPC internal)
#   7. BUT: any operation requiring outbound internet fails silently
#
# RCA challenge:
#   - Health checks pass! ALB sees healthy target
#   - No CW alarm fires (unless canary checks an external dependency)
#   - CloudTrail DOES show ReplaceRoute / CreateRoute API call → this is the key evidence
#   - Agent must correlate: route table change + connectivity symptom
#   - Tests: Network investigation path, route table analysis, VPC topology understanding
#
# Variation: if the app's /health tries to resolve an external endpoint, it will timeout
#
# Detection: May not trigger CW alarm at all — user reports "can't download files" or similar
# Recovery: Restore the NAT Gateway route
#
# Usage: bash 08-route-table-blackhole.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

# Find the private subnet's route table
PRIVATE_SUBNET="subnet-0634feb8477a666fa"
RTB_ID=""
NAT_GW_ID=""

get_route_info() {
    RTB_ID=$(aws ec2 describe-route-tables \
        --filters "Name=association.subnet-id,Values=$PRIVATE_SUBNET" \
        --region "$REGION" \
        --query 'RouteTables[0].RouteTableId' --output text)

    if [ "$RTB_ID" = "None" ] || [ -z "$RTB_ID" ]; then
        # Subnet uses main route table
        local vpc_id="vpc-028fe79b3785c1aba"
        RTB_ID=$(aws ec2 describe-route-tables \
            --filters "Name=vpc-id,Values=$vpc_id" "Name=association.main,Values=true" \
            --region "$REGION" \
            --query 'RouteTables[0].RouteTableId' --output text)
    fi

    NAT_GW_ID=$(aws ec2 describe-route-tables \
        --route-table-ids "$RTB_ID" \
        --region "$REGION" \
        --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`].NatGatewayId | [0]' \
        --output text 2>/dev/null || echo "")

    log "Route Table: $RTB_ID"
    log "NAT Gateway: $NAT_GW_ID"
}

case "$action" in
    inject)
        log "=== Scenario 8: Route Table Blackhole ==="
        log "Pre-check: health=$(check_health)"

        get_route_info

        if [ -z "$NAT_GW_ID" ] || [ "$NAT_GW_ID" = "None" ]; then
            log "ERROR: No NAT Gateway route found in $RTB_ID for 0.0.0.0/0"
            log "Cannot inject — private subnet may not have NAT route"
            exit 1
        fi

        # Save state for recovery
        echo "{\"rtb_id\": \"$RTB_ID\", \"nat_gw_id\": \"$NAT_GW_ID\"}" > /tmp/weblab-route-state.json
        log "Saved route state: RTB=$RTB_ID, NAT=$NAT_GW_ID"

        log "Injecting fault: replacing NAT GW route with blackhole..."
        aws ec2 replace-route \
            --route-table-id "$RTB_ID" \
            --destination-cidr-block "0.0.0.0/0" \
            --instance-id "$INSTANCE_ID" \
            --region "$REGION" 2>/dev/null || \
        aws ec2 delete-route \
            --route-table-id "$RTB_ID" \
            --destination-cidr-block "0.0.0.0/0" \
            --region "$REGION"

        log "Waiting 10s for route change to propagate..."
        sleep 10

        log ""
        log "=== Symptom Verification ==="

        health_code=$(check_health)
        log "  /health            -> $health_code (likely still 200 — DB via VPC internal)"

        log ""
        log "  EC2 outbound internet test:"
        ssm_run_wait 'curl -s --connect-timeout 5 --max-time 10 http://checkip.amazonaws.com 2>/dev/null || echo "TIMEOUT — no internet"'

        log ""
        log "  EC2 → RDS connectivity test:"
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "import pymysql,os; c=pymysql.connect(host=os.environ[\"DB_HOST\"],port=3306,user=os.environ[\"DB_USER\"],password=os.environ[\"DB_PASS\"],database=os.environ[\"DB_NAME\"],connect_timeout=5); print(\"DB OK\"); c.close()" 2>/dev/null || echo "DB FAILED"'

        log ""
        log "  Current route table:"
        aws ec2 describe-route-tables \
            --route-table-ids "$RTB_ID" \
            --region "$REGION" \
            --query 'RouteTables[0].Routes[*].{Dest:DestinationCidrBlock,GW:GatewayId,NAT:NatGatewayId,Instance:InstanceId,State:State}' \
            --output table

        log ""
        log "=== Fault Active ==="
        log "Private subnet lost outbound internet. App still serves requests via ALB (VPC internal)."
        log "DB still reachable (same VPC). But any external dependency will fail."
        log "CloudTrail WILL show ReplaceRoute/DeleteRoute → key evidence for RCA."
        log "CW alarms likely stay OK — this is a silent network degradation."
        log ""
        log "Run: bash $0 recover"
        ;;

    verify)
        log "=== Verifying Scenario 8 ==="

        get_route_info

        health_code=$(check_health)
        log "Health check: $health_code"

        log ""
        log "Route table $RTB_ID:"
        aws ec2 describe-route-tables \
            --route-table-ids "$RTB_ID" \
            --region "$REGION" \
            --query 'RouteTables[0].Routes[*].{Dest:DestinationCidrBlock,GW:GatewayId,NAT:NatGatewayId,Instance:InstanceId,State:State}' \
            --output table

        log ""
        log "EC2 outbound test:"
        ssm_run_wait 'curl -s --connect-timeout 5 --max-time 10 http://checkip.amazonaws.com 2>/dev/null || echo "TIMEOUT"'

        log ""
        log "CloudTrail route changes (last 1h):"
        aws cloudtrail lookup-events \
            --lookup-attributes "AttributeKey=EventName,AttributeValue=ReplaceRoute" \
            --start-time "$(date -u -v-1H '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')" \
            --region "$REGION" \
            --query 'Events[*].{Time:EventTime,Name:EventName,User:Username}' \
            --output table 2>/dev/null || log "  (no ReplaceRoute events found)"

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
        log "=== Recovering Scenario 8 ==="

        # Read saved state
        if [ -f /tmp/weblab-route-state.json ]; then
            RTB_ID=$(python3 -c "import json; print(json.load(open('/tmp/weblab-route-state.json'))['rtb_id'])")
            NAT_GW_ID=$(python3 -c "import json; print(json.load(open('/tmp/weblab-route-state.json'))['nat_gw_id'])")
        else
            get_route_info
            log "WARNING: No saved state, using discovered values"
        fi

        log "Restoring NAT Gateway route: $RTB_ID → 0.0.0.0/0 via $NAT_GW_ID..."

        # Try to create (if deleted) or replace (if pointing elsewhere)
        aws ec2 create-route \
            --route-table-id "$RTB_ID" \
            --destination-cidr-block "0.0.0.0/0" \
            --nat-gateway-id "$NAT_GW_ID" \
            --region "$REGION" 2>/dev/null || \
        aws ec2 replace-route \
            --route-table-id "$RTB_ID" \
            --destination-cidr-block "0.0.0.0/0" \
            --nat-gateway-id "$NAT_GW_ID" \
            --region "$REGION"

        log "Waiting 10s for route propagation..."
        sleep 10

        log "EC2 outbound test:"
        ssm_run_wait 'curl -s --connect-timeout 5 --max-time 10 http://checkip.amazonaws.com 2>/dev/null || echo "STILL NO INTERNET"'

        wait_for_health 200 60
        rm -f /tmp/weblab-route-state.json
        log "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
