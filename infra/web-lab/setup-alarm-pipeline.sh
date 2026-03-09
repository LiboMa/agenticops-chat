#!/bin/bash
# Setup: CloudWatch Alarm → SNS → Lambda → Feishu alert group
# Usage: bash setup-alarm-pipeline.sh [create|delete|status]
set -euo pipefail

REGION="ap-southeast-1"
ACCOUNT_ID="533267047935"
SNS_TOPIC_NAME="weblab-alarms"
LAMBDA_NAME="weblab-cw-to-feishu"
LAMBDA_ROLE_NAME="weblab-lambda-feishu-role"

# Feishu config (from im-apps.yaml + channels.yaml)
FEISHU_APP_ID="cli_a92e41f3baba5bdf"
FEISHU_APP_SECRET="UtwiosQqgHKfQMInb2RFwcQQvP5Xnp7t"
FEISHU_CHAT_ID="oc_aa7c42972267ca070bf3977ec8e222bd"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/lambda"

action="${1:-create}"

create_lambda_role() {
    echo "==> Creating Lambda execution role..."
    aws iam create-role \
        --role-name "$LAMBDA_ROLE_NAME" \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }' \
        --region "$REGION" 2>/dev/null || echo "    (role exists)"

    aws iam attach-role-policy \
        --role-name "$LAMBDA_ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
        2>/dev/null || true

    echo "    Waiting 10s for role propagation..."
    sleep 10
}

create_lambda() {
    echo "==> Packaging Lambda..."
    cd "$LAMBDA_DIR"
    zip -j /tmp/weblab-lambda.zip cw_to_feishu.py

    echo "==> Creating Lambda function..."
    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${LAMBDA_ROLE_NAME}"

    # Try create, fall back to update
    if aws lambda get-function --function-name "$LAMBDA_NAME" --region "$REGION" &>/dev/null; then
        echo "    Lambda exists, updating code..."
        aws lambda update-function-code \
            --function-name "$LAMBDA_NAME" \
            --zip-file fileb:///tmp/weblab-lambda.zip \
            --region "$REGION" > /dev/null

        aws lambda update-function-configuration \
            --function-name "$LAMBDA_NAME" \
            --environment "Variables={FEISHU_APP_ID=${FEISHU_APP_ID},FEISHU_APP_SECRET=${FEISHU_APP_SECRET},FEISHU_CHAT_ID=${FEISHU_CHAT_ID}}" \
            --region "$REGION" > /dev/null
    else
        aws lambda create-function \
            --function-name "$LAMBDA_NAME" \
            --runtime python3.12 \
            --handler cw_to_feishu.handler \
            --role "$ROLE_ARN" \
            --zip-file fileb:///tmp/weblab-lambda.zip \
            --timeout 30 \
            --memory-size 128 \
            --environment "Variables={FEISHU_APP_ID=${FEISHU_APP_ID},FEISHU_APP_SECRET=${FEISHU_APP_SECRET},FEISHU_CHAT_ID=${FEISHU_CHAT_ID}}" \
            --region "$REGION" > /dev/null
    fi
    echo "    Lambda: ${LAMBDA_NAME}"
    rm -f /tmp/weblab-lambda.zip
}

create_sns_topic() {
    echo "==> Creating SNS topic..."
    TOPIC_ARN=$(aws sns create-topic \
        --name "$SNS_TOPIC_NAME" \
        --region "$REGION" \
        --query 'TopicArn' --output text)
    echo "    Topic: ${TOPIC_ARN}"

    # Subscribe Lambda to SNS
    LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${LAMBDA_NAME}"

    echo "==> Adding SNS invoke permission to Lambda..."
    aws lambda add-permission \
        --function-name "$LAMBDA_NAME" \
        --statement-id sns-invoke \
        --action lambda:InvokeFunction \
        --principal sns.amazonaws.com \
        --source-arn "$TOPIC_ARN" \
        --region "$REGION" 2>/dev/null || echo "    (permission exists)"

    echo "==> Subscribing Lambda to SNS..."
    aws sns subscribe \
        --topic-arn "$TOPIC_ARN" \
        --protocol lambda \
        --notification-endpoint "$LAMBDA_ARN" \
        --region "$REGION" > /dev/null
    echo "    Subscribed."
}

wire_alarms() {
    TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:${SNS_TOPIC_NAME}"

    echo "==> Wiring CloudWatch alarms to SNS topic..."
    for ALARM in weblab-canary-failed weblab-unhealthy-hosts weblab-5xx-errors; do
        echo "    ${ALARM} → ${TOPIC_ARN}"
        # Get current alarm config and add alarm action
        aws cloudwatch describe-alarms \
            --alarm-names "$ALARM" \
            --region "$REGION" \
            --query 'MetricAlarms[0]' --output json | \
        python3 -c "
import sys, json
a = json.load(sys.stdin)
if not a:
    print(f'  Alarm not found: $ALARM', file=sys.stderr)
    sys.exit(0)
# Build put-metric-alarm args
args = {
    'AlarmName': a['AlarmName'],
    'AlarmDescription': a.get('AlarmDescription', ''),
    'ActionsEnabled': True,
    'AlarmActions': list(set(a.get('AlarmActions', []) + ['$TOPIC_ARN'])),
    'OKActions': list(set(a.get('OKActions', []) + ['$TOPIC_ARN'])),
    'MetricName': a['MetricName'],
    'Namespace': a['Namespace'],
    'Statistic': a.get('Statistic', 'Average'),
    'Period': a['Period'],
    'EvaluationPeriods': a['EvaluationPeriods'],
    'Threshold': a['Threshold'],
    'ComparisonOperator': a['ComparisonOperator'],
    'TreatMissingData': a.get('TreatMissingData', 'missing'),
}
if a.get('Dimensions'):
    args['Dimensions'] = a['Dimensions']
json.dump(args, sys.stdout)
" | aws cloudwatch put-metric-alarm \
            --cli-input-json file:///dev/stdin \
            --region "$REGION"
    done
    echo "    Done."
}

case "$action" in
    create)
        create_lambda_role
        create_lambda
        create_sns_topic
        wire_alarms
        echo ""
        echo "=== Pipeline ready ==="
        echo "CloudWatch Alarm → SNS (${SNS_TOPIC_NAME}) → Lambda (${LAMBDA_NAME}) → Feishu (${FEISHU_CHAT_ID})"
        echo ""
        echo "Test with: aws sns publish --topic-arn arn:aws:sns:${REGION}:${ACCOUNT_ID}:${SNS_TOPIC_NAME} --message 'test' --region ${REGION}"
        ;;

    delete)
        echo "==> Removing alarm actions..."
        for ALARM in weblab-canary-failed weblab-unhealthy-hosts weblab-5xx-errors; do
            aws cloudwatch describe-alarms --alarm-names "$ALARM" --region "$REGION" \
                --query 'MetricAlarms[0]' --output json 2>/dev/null | \
            python3 -c "
import sys, json
a = json.load(sys.stdin)
if not a: sys.exit(0)
args = {
    'AlarmName': a['AlarmName'],
    'AlarmDescription': a.get('AlarmDescription', ''),
    'ActionsEnabled': True,
    'AlarmActions': [],
    'OKActions': [],
    'MetricName': a['MetricName'],
    'Namespace': a['Namespace'],
    'Statistic': a.get('Statistic', 'Average'),
    'Period': a['Period'],
    'EvaluationPeriods': a['EvaluationPeriods'],
    'Threshold': a['Threshold'],
    'ComparisonOperator': a['ComparisonOperator'],
    'TreatMissingData': a.get('TreatMissingData', 'missing'),
}
if a.get('Dimensions'): args['Dimensions'] = a['Dimensions']
json.dump(args, sys.stdout)
" | aws cloudwatch put-metric-alarm --cli-input-json file:///dev/stdin --region "$REGION" 2>/dev/null || true
        done

        echo "==> Deleting Lambda..."
        aws lambda delete-function --function-name "$LAMBDA_NAME" --region "$REGION" 2>/dev/null || true

        echo "==> Deleting SNS topic..."
        aws sns delete-topic --topic-arn "arn:aws:sns:${REGION}:${ACCOUNT_ID}:${SNS_TOPIC_NAME}" --region "$REGION" 2>/dev/null || true

        echo "==> Deleting IAM role..."
        aws iam detach-role-policy --role-name "$LAMBDA_ROLE_NAME" \
            --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true
        aws iam delete-role --role-name "$LAMBDA_ROLE_NAME" 2>/dev/null || true

        echo "==> Deleted."
        ;;

    status)
        echo "=== SNS Topic ==="
        aws sns get-topic-attributes \
            --topic-arn "arn:aws:sns:${REGION}:${ACCOUNT_ID}:${SNS_TOPIC_NAME}" \
            --region "$REGION" --query 'Attributes.{Subscriptions:SubscriptionsConfirmed,Pending:SubscriptionsPending}' \
            --output table 2>/dev/null || echo "Topic not found."

        echo ""
        echo "=== Lambda ==="
        aws lambda get-function \
            --function-name "$LAMBDA_NAME" \
            --region "$REGION" \
            --query 'Configuration.{State:State,Runtime:Runtime,LastModified:LastModified}' \
            --output table 2>/dev/null || echo "Lambda not found."

        echo ""
        echo "=== Alarm Actions ==="
        aws cloudwatch describe-alarms \
            --alarm-names weblab-canary-failed weblab-unhealthy-hosts weblab-5xx-errors \
            --region "$REGION" \
            --query 'MetricAlarms[*].{Name:AlarmName,State:StateValue,Actions:AlarmActions}' \
            --output table 2>/dev/null || true
        ;;

    test)
        echo "==> Sending test SNS message..."
        TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:${SNS_TOPIC_NAME}"
        # Simulate a CloudWatch ALARM notification
        MSG=$(cat <<'ALARMEOF'
{
    "AlarmName": "weblab-test-alarm",
    "AlarmDescription": "Test alarm from setup script",
    "NewStateValue": "ALARM",
    "NewStateReason": "Manual test trigger",
    "Region": "ap-southeast-1",
    "Trigger": {
        "MetricName": "TestMetric",
        "Namespace": "WebLab/Test",
        "Dimensions": [{"name": "InstanceId", "value": "i-0e09ff39942feb07d"}]
    }
}
ALARMEOF
        )
        aws sns publish \
            --topic-arn "$TOPIC_ARN" \
            --message "$MSG" \
            --region "$REGION"
        echo "==> Sent. Check Feishu alert group for the message."
        ;;

    *)
        echo "Usage: $0 [create|delete|status|test]"
        exit 1
        ;;
esac
