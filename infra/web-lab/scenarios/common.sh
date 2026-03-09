#!/bin/bash
# Shared helpers for web-lab scenario scripts
set -euo pipefail

REGION="ap-southeast-1"
INSTANCE_ID="i-0e09ff39942feb07d"
RDS_IDENTIFIER="weblab-mysql"
RDS_ENDPOINT="weblab-mysql.c7g64s2w4e6g.ap-southeast-1.rds.amazonaws.com"
APP_URL="https://agentic-ops.tinyboat.blog"
EC2_SG="$(aws cloudformation describe-stacks --stack-name weblab-stack --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`EC2InstanceId`].OutputValue' --output text 2>/dev/null || echo '')"

# Security group IDs (cached from stack)
_sg_cache=""
get_sg_ids() {
    if [ -z "$_sg_cache" ]; then
        _sg_cache=$(aws cloudformation describe-stack-resources \
            --stack-name weblab-stack --region "$REGION" \
            --query 'StackResources[?ResourceType==`AWS::EC2::SecurityGroup`].{Logical:LogicalResourceId,Physical:PhysicalResourceId}' \
            --output json 2>/dev/null)
    fi
    echo "$_sg_cache"
}

get_sg_id() {
    local logical_id="$1"
    get_sg_ids | python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data:
    if item['Logical'] == '$logical_id':
        print(item['Physical'])
        break
"
}

# Run command on EC2 via SSM
ssm_run() {
    local cmd="$1"
    local timeout="${2:-30}"
    aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters "commands=[\"$cmd\"]" \
        --timeout-seconds "$timeout" \
        --region "$REGION" \
        --query 'Command.CommandId' --output text
}

ssm_wait() {
    local cmd_id="$1"
    local max_wait="${2:-60}"
    local elapsed=0
    while [ $elapsed -lt $max_wait ]; do
        status=$(aws ssm get-command-invocation \
            --command-id "$cmd_id" \
            --instance-id "$INSTANCE_ID" \
            --region "$REGION" \
            --query 'Status' --output text 2>/dev/null || echo "Pending")
        if [ "$status" = "Success" ] || [ "$status" = "Failed" ]; then
            echo "$status"
            return
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    echo "Timeout"
}

ssm_output() {
    local cmd_id="$1"
    aws ssm get-command-invocation \
        --command-id "$cmd_id" \
        --instance-id "$INSTANCE_ID" \
        --region "$REGION" \
        --query 'StandardOutputContent' --output text 2>/dev/null
}

ssm_run_wait() {
    local cmd="$1"
    local cmd_id
    cmd_id=$(ssm_run "$cmd")
    echo "  SSM command: $cmd_id"
    local status
    status=$(ssm_wait "$cmd_id")
    echo "  Status: $status"
    if [ "$status" = "Success" ]; then
        ssm_output "$cmd_id"
    fi
}

# Check app health
check_health() {
    local code
    code=$(curl -sk -o /dev/null -w '%{http_code}' "${APP_URL}/health" --connect-timeout 5 --max-time 10 2>/dev/null || echo "000")
    echo "$code"
}

wait_for_health() {
    local expected="${1:-200}"
    local max_wait="${2:-120}"
    local elapsed=0
    echo -n "  Waiting for health=$expected "
    while [ $elapsed -lt $max_wait ]; do
        local code
        code=$(check_health)
        if [ "$code" = "$expected" ]; then
            echo " OK (${elapsed}s)"
            return 0
        fi
        echo -n "."
        sleep 5
        elapsed=$((elapsed + 5))
    done
    echo " TIMEOUT (${max_wait}s, last=$code)"
    return 1
}

wait_for_unhealthy() {
    local max_wait="${1:-120}"
    local elapsed=0
    echo -n "  Waiting for unhealthy "
    while [ $elapsed -lt $max_wait ]; do
        local code
        code=$(check_health)
        if [ "$code" != "200" ]; then
            echo " UNHEALTHY (${elapsed}s, code=$code)"
            return 0
        fi
        echo -n "."
        sleep 5
        elapsed=$((elapsed + 5))
    done
    echo " STILL HEALTHY (${max_wait}s)"
    return 1
}

log() {
    echo "[$(date +%H:%M:%S)] $*"
}
