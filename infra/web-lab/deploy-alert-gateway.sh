#!/bin/bash
# Deploy alert_gateway.py to Lambda (replaces old cw_to_feishu Lambda).
#
# Usage:
#   bash deploy-alert-gateway.sh [deploy|test-cw|test-prom|test-slack|status]
#
# Prerequisites:
#   - aws CLI configured with ap-southeast-1 credentials
#   - SNS topic weblab-alarms already exists
#   - alert-targets.json configured
set -euo pipefail

REGION="ap-southeast-1"
ACCOUNT_ID="533267047935"
LAMBDA_NAME="weblab-cw-to-feishu"  # reuse existing Lambda name
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:weblab-alarms"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/lambda"
TARGETS_FILE="${LAMBDA_DIR}/alert-targets.json"

action="${1:-deploy}"

deploy() {
    echo "==> Packaging alert_gateway.py..."
    cd "$LAMBDA_DIR"
    zip -j /tmp/alert-gateway.zip alert_gateway.py
    echo "    Created /tmp/alert-gateway.zip"

    echo "==> Updating Lambda code..."
    aws lambda update-function-code \
        --function-name "$LAMBDA_NAME" \
        --zip-file fileb:///tmp/alert-gateway.zip \
        --region "$REGION" \
        --query 'FunctionArn' --output text

    echo "==> Waiting for function update..."
    aws lambda wait function-updated \
        --function-name "$LAMBDA_NAME" \
        --region "$REGION"

    echo "==> Updating Lambda config (handler + env)..."
    # Read targets JSON, escape for env var
    TARGETS_JSON=$(cat "$TARGETS_FILE")
    aws lambda update-function-configuration \
        --function-name "$LAMBDA_NAME" \
        --handler "alert_gateway.handler" \
        --timeout 30 \
        --environment "{\"Variables\":{\"ALERT_TARGETS\":$(echo "$TARGETS_JSON" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')}}" \
        --region "$REGION" \
        --query '{Handler:Handler,LastModified:LastModified}' --output table

    echo ""
    echo "=== Deployed ==="
    echo "Lambda: ${LAMBDA_NAME} (handler: alert_gateway.handler)"
    echo "SNS: ${SNS_TOPIC_ARN}"
    echo ""
    echo "Test: bash $0 test-cw"
    rm -f /tmp/alert-gateway.zip
}

test_cloudwatch() {
    echo "==> Sending simulated CloudWatch ALARM via SNS..."
    MSG=$(cat <<'EOF'
{
    "AlarmName": "weblab-test-high-cpu",
    "AlarmDescription": "EC2 instance CPU utilization exceeded 90% for 5 minutes",
    "NewStateValue": "ALARM",
    "NewStateReason": "Threshold Crossed: 1 datapoint [95.2 (08/03/26 10:30:00)] was greater than the threshold (90.0).",
    "Region": "ap-southeast-1",
    "Trigger": {
        "MetricName": "CPUUtilization",
        "Namespace": "AWS/EC2",
        "Dimensions": [{"name": "InstanceId", "value": "i-0e09ff39942feb07d"}],
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 90.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "Statistic": "Average"
    }
}
EOF
    )
    MSGID=$(aws sns publish \
        --topic-arn "$SNS_TOPIC_ARN" \
        --message "$MSG" \
        --region "$REGION" \
        --query 'MessageId' --output text)
    echo "    MessageId: ${MSGID}"
    echo "    Check Slack #agents-ops-alerts and Feishu alert group."
}

test_prometheus() {
    echo "==> Sending simulated Prometheus alert via SNS..."
    MSG=$(cat <<'EOF'
{
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "KubePodCrashLooping",
                "severity": "critical",
                "namespace": "production",
                "pod": "api-server-7d8f9b6c4-x2k9p",
                "container": "api-server"
            },
            "annotations": {
                "summary": "Pod production/api-server-7d8f9b6c4-x2k9p is crash looping",
                "description": "Pod has restarted 5 times in the last 10 minutes"
            }
        }
    ]
}
EOF
    )
    MSGID=$(aws sns publish \
        --topic-arn "$SNS_TOPIC_ARN" \
        --message "$MSG" \
        --region "$REGION" \
        --query 'MessageId' --output text)
    echo "    MessageId: ${MSGID}"
    echo "    Check Slack #agents-ops-alerts and Feishu alert group."
}

test_slack_only() {
    echo "==> Invoking Lambda directly with Slack-targeted CW alarm..."
    PAYLOAD=$(cat <<'EOF'
{
    "Records": [{
        "Sns": {
            "Message": "{\"AlarmName\":\"weblab-direct-test\",\"AlarmDescription\":\"Direct Lambda invoke test\",\"NewStateValue\":\"ALARM\",\"NewStateReason\":\"Manual test\",\"Region\":\"ap-southeast-1\",\"Trigger\":{\"MetricName\":\"StatusCheckFailed\",\"Namespace\":\"AWS/EC2\",\"Dimensions\":[{\"name\":\"InstanceId\",\"value\":\"i-0e09ff39942feb07d\"}]}}"
        }
    }]
}
EOF
    )
    aws lambda invoke \
        --function-name "$LAMBDA_NAME" \
        --payload "$(echo "$PAYLOAD" | base64)" \
        --cli-binary-format raw-in-base64-out \
        --region "$REGION" \
        --query 'StatusCode' \
        /tmp/lambda-response.json
    echo "    Response:"
    cat /tmp/lambda-response.json
    echo ""
    rm -f /tmp/lambda-response.json
}

status() {
    echo "=== Lambda ==="
    aws lambda get-function-configuration \
        --function-name "$LAMBDA_NAME" \
        --region "$REGION" \
        --query '{Handler:Handler,Runtime:Runtime,Timeout:Timeout,LastModified:LastModified,State:State}' \
        --output table 2>/dev/null || echo "Lambda not found."

    echo ""
    echo "=== SNS Subscriptions ==="
    aws sns list-subscriptions-by-topic \
        --topic-arn "$SNS_TOPIC_ARN" \
        --region "$REGION" \
        --query 'Subscriptions[*].{Protocol:Protocol,Endpoint:Endpoint}' \
        --output table 2>/dev/null || echo "Topic not found."

    echo ""
    echo "=== CloudWatch Alarms ==="
    aws cloudwatch describe-alarms \
        --alarm-name-prefix "weblab-" \
        --region "$REGION" \
        --query 'MetricAlarms[*].{Name:AlarmName,State:StateValue,Actions:AlarmActions[0]}' \
        --output table 2>/dev/null || true

    echo ""
    echo "=== Recent Lambda Logs (last 5 min) ==="
    aws logs filter-log-events \
        --log-group-name "/aws/lambda/${LAMBDA_NAME}" \
        --start-time "$(python3 -c 'import time; print(int((time.time()-300)*1000))')" \
        --region "$REGION" \
        --query 'events[*].message' \
        --output text 2>/dev/null | head -30 || echo "No recent logs."
}

case "$action" in
    deploy)     deploy ;;
    test-cw)    test_cloudwatch ;;
    test-prom)  test_prometheus ;;
    test-slack) test_slack_only ;;
    status)     status ;;
    *)
        echo "Usage: $0 [deploy|test-cw|test-prom|test-slack|status]"
        exit 1
        ;;
esac
