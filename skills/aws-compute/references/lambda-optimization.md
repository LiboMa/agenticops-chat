# Lambda Optimization Deep Dive

## Cold Start Reduction

Cold starts occur when Lambda creates a new execution environment. The time includes:
downloading code, starting the runtime, running initialization code.

### Provisioned Concurrency

Pre-initializes execution environments so they are always warm:

```bash
# Set provisioned concurrency on an alias
aws lambda put-provisioned-concurrency-config \
  --function-name my-function \
  --qualifier production \
  --provisioned-concurrent-executions 50

# Check status
aws lambda get-provisioned-concurrency-config \
  --function-name my-function --qualifier production

# Auto-scale provisioned concurrency with Application Auto Scaling
aws application-autoscaling register-scalable-target \
  --service-namespace lambda \
  --resource-id function:my-function:production \
  --scalable-dimension lambda:function:ProvisionedConcurrency \
  --min-capacity 10 --max-capacity 100

aws application-autoscaling put-scaling-policy \
  --service-namespace lambda \
  --resource-id function:my-function:production \
  --scalable-dimension lambda:function:ProvisionedConcurrency \
  --policy-name target-tracking \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 0.7,
    "PredefinedMetricSpecification": {
      "PredefinedMetricType": "LambdaProvisionedConcurrencyUtilization"
    }
  }'
```

Cost: you pay for provisioned concurrency even when idle. Use scheduled scaling
for predictable traffic patterns.

### SnapStart (Java only)

Snapshots the initialized execution environment after init, restores from snapshot:

```bash
aws lambda update-function-configuration \
  --function-name my-java-function \
  --snap-start ApplyOn=PublishedVersions

# Publish a version to trigger snapshot
aws lambda publish-version --function-name my-java-function
```

Reduces Java cold starts from 5-10s to < 200ms. Caveats:
- Must publish a version (not $LATEST)
- Some state must be re-initialized (uniqueness, connections) using runtime hooks
- Not compatible with provisioned concurrency, EFS, ephemeral storage > 512MB

### Smaller Deployment Packages

Cold start time correlates with package size:

```bash
# Check current package size
aws lambda get-function --function-name my-function \
  --query 'Configuration.{CodeSize:CodeSize,Layers:Layers}'

# Python: use slim packages, exclude tests and dev deps
pip install --target ./package --only-binary=:all: -r requirements.txt
# Exclude: __pycache__, *.pyc, tests/, docs/, *.dist-info

# Node.js: use esbuild/webpack to tree-shake and bundle
npx esbuild handler.ts --bundle --platform=node --target=node20 \
  --outfile=dist/handler.js --minify --external:@aws-sdk/*

# Note: @aws-sdk v3 is included in the Lambda runtime for Node.js 18+
# Do NOT bundle it -- exclude to reduce package size

# Container images: use multi-stage builds
# FROM public.ecr.aws/lambda/python:3.12 as build
# ... install deps ...
# FROM public.ecr.aws/lambda/python:3.12
# COPY --from=build /app /app
```

### Lazy Initialization

Initialize expensive resources outside the handler but defer heavy operations:

```python
import boto3
import os

# Module-level: initialized once per execution environment (cold start)
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['TABLE_NAME'])

# Do NOT do heavy work at module level (e.g., loading ML models)
# Instead, use lazy loading:
_model = None

def get_model():
    global _model
    if _model is None:
        import torch  # deferred import
        _model = torch.load('/opt/model.pt')
    return _model

def handler(event, context):
    # Handler code -- reuses warm connections
    model = get_model()  # only loads on first invocation
    result = table.get_item(Key={'id': event['id']})
    return {'statusCode': 200, 'body': result}
```

## Memory-CPU Scaling

Lambda allocates CPU proportionally to memory:

| Memory (MB) | Approx vCPU | Notes |
|-------------|-------------|-------|
| 128         | 0.08        | Minimum, very limited CPU |
| 256         | 0.15        | Light processing |
| 512         | 0.30        | Moderate workloads |
| 1024        | 0.58        | |
| 1769        | 1.00        | First full vCPU |
| 3538        | 2.00        | Two vCPUs, can use multi-threading |
| 5307        | 3.00        | |
| 7076        | 4.00        | |
| 8845        | 5.00        | |
| 10240       | 6.00        | Maximum memory and CPU |

Key insight: doubling memory doubles CPU and halves execution time for CPU-bound
workloads, at the same cost. Memory-bound workloads benefit directly.

Network bandwidth also scales with memory -- important for S3 downloads, API calls.

## Lambda Power Tuning

AWS Lambda Power Tuning is a Step Functions state machine that tests your function
at multiple memory settings and reports cost/duration:

```bash
# Deploy via SAR (Serverless Application Repository)
aws serverlessrepo create-cloud-formation-change-set \
  --application-id arn:aws:serverlessrepo:us-east-1:451282441545:applications/aws-lambda-power-tuning \
  --stack-name power-tuning

# Or deploy via SAM/CDK/Terraform

# Execute tuning
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:powerTuningStateMachine \
  --input '{
    "lambdaARN": "arn:aws:lambda:us-east-1:123456789012:function:my-function",
    "powerValues": [128, 256, 512, 1024, 1769, 3008],
    "num": 20,
    "payload": {"key": "value"},
    "parallelInvocation": true,
    "strategy": "balanced"
  }'

# Strategies: "cost" (cheapest), "speed" (fastest), "balanced" (best value)
# Output: URL to visualization showing cost vs duration at each memory level
```

## Lambda Layers

Shared code/dependencies packaged separately from function code:

```bash
# Create a layer with common dependencies
mkdir -p layer/python
pip install requests boto3-stubs -t layer/python
cd layer && zip -r ../my-layer.zip python

aws lambda publish-layer-version --layer-name common-deps \
  --zip-file fileb://my-layer.zip \
  --compatible-runtimes python3.11 python3.12 \
  --compatible-architectures x86_64 arm64

# Attach layer to function (up to 5 layers)
aws lambda update-function-configuration \
  --function-name my-function \
  --layers arn:aws:lambda:us-east-1:123456789012:layer:common-deps:3

# Layer paths by runtime:
# Python: /opt/python/ or /opt/python/lib/python3.x/site-packages/
# Node.js: /opt/nodejs/node_modules/
# Java: /opt/java/lib/
# Custom runtime: /opt/bin/ (executables), /opt/lib/ (shared libs)
```

Layer limits:
- Max 5 layers per function
- Total unzipped size (function + all layers): 250 MB
- Layer .zip max: 50 MB (direct upload) or 250 MB (S3)

## Extensions

Lambda extensions run as companion processes in the execution environment:

```bash
# Internal extensions: run in-process (e.g., APM agents)
# External extensions: run as separate processes (e.g., log collectors)

# Register extension in layer under /opt/extensions/
# Extension binary must be executable and handle lifecycle events:
# INVOKE, SHUTDOWN

# Common extensions:
# - AWS Parameters and Secrets Lambda Extension (caches SSM/Secrets Manager)
# - CloudWatch Lambda Insights (enhanced monitoring)
# - Datadog/New Relic APM extensions
# - Custom log forwarding extensions
```

## Destinations and DLQ

### Destinations (preferred over DLQ)

```bash
# Configure destinations for async invocations
aws lambda put-function-event-invoke-config \
  --function-name my-function \
  --destination-config '{
    "OnSuccess": {
      "Destination": "arn:aws:sqs:us-east-1:123456789012:success-queue"
    },
    "OnFailure": {
      "Destination": "arn:aws:sqs:us-east-1:123456789012:failure-queue"
    }
  }' \
  --maximum-retry-attempts 2 \
  --maximum-event-age-in-seconds 3600

# Destination types: SQS, SNS, Lambda, EventBridge
# Destination payload includes: requestContext, requestPayload, responseContext, responsePayload
```

### Dead Letter Queue (DLQ)

```bash
# Configure DLQ (SQS or SNS)
aws lambda update-function-configuration \
  --function-name my-function \
  --dead-letter-config TargetArn=arn:aws:sqs:us-east-1:123456789012:my-dlq

# DLQ only captures failures (no success path)
# DLQ only gets the event payload (no execution context)
# Destinations are preferred -- more flexible, include context
```

## Reserved vs Provisioned Concurrency

These are different concepts that are often confused:

### Reserved Concurrency
- **Guarantees** a maximum number of concurrent executions for a function
- **Limits** the function to that number (throttles above it)
- **Subtracts** from account-level concurrent execution pool
- **No additional cost**
- Use to: prevent a function from consuming all account concurrency, or to throttle

```bash
aws lambda put-function-concurrency \
  --function-name my-function \
  --reserved-concurrent-executions 100

# This function: max 100 concurrent, guaranteed 100 from account pool
# Account pool: reduced by 100 for other functions
# Setting to 0: effectively disables the function (all invocations throttled)
```

### Provisioned Concurrency
- **Pre-warms** execution environments (eliminates cold starts)
- Does NOT limit maximum concurrency (can still scale beyond provisioned)
- **Additional cost**: pay for provisioned environments even when idle
- Requires a published version or alias (not $LATEST)

```bash
aws lambda put-provisioned-concurrency-config \
  --function-name my-function \
  --qualifier my-alias \
  --provisioned-concurrent-executions 50

# 50 environments always warm
# If traffic exceeds 50, Lambda still scales (with cold starts for overflow)
```

### Combining Both

```bash
# Reserve 200 max concurrent, pre-warm 50
aws lambda put-function-concurrency \
  --function-name my-function \
  --reserved-concurrent-executions 200

aws lambda put-provisioned-concurrency-config \
  --function-name my-function \
  --qualifier prod \
  --provisioned-concurrent-executions 50

# Result:
# 0-50 concurrent: all warm (provisioned)
# 51-200 concurrent: new environments created (cold starts)
# >200: throttled (reserved concurrency limit)
```

## Monitoring and Debugging

```bash
# Key CloudWatch metrics
aws cloudwatch get-metric-statistics --namespace AWS/Lambda \
  --metric-name Duration --dimensions Name=FunctionName,Value=my-function \
  --start-time 2024-01-01T00:00:00Z --end-time 2024-01-02T00:00:00Z \
  --period 300 --statistics Average Maximum p99

# Important metrics:
# Duration: execution time (p99 for tail latency)
# Errors: invocation errors (function code failures)
# Throttles: throttled invocation attempts
# ConcurrentExecutions: concurrent environments in use
# IteratorAge: age of last record processed (for stream sources)
# MaxMemoryUsed: (in CloudWatch Logs REPORT line)

# Enable X-Ray tracing
aws lambda update-function-configuration \
  --function-name my-function \
  --tracing-config Mode=Active

# Parse REPORT lines from CloudWatch Logs for memory analysis
# REPORT RequestId: xxx Duration: 45.23 ms Billed Duration: 46 ms
#   Memory Size: 512 MB Max Memory Used: 234 MB Init Duration: 312.45 ms
```

## Architecture Selection

```bash
# Compare x86_64 vs arm64 (Graviton2)
# arm64: up to 34% better price-performance for most workloads

aws lambda update-function-configuration \
  --function-name my-function \
  --architectures arm64

# Caveats:
# - Native compiled dependencies must be built for arm64
# - Container images must be built for arm64 (or multi-arch)
# - Lambda layers must be compatible with arm64
# - Some runtimes/libraries may not yet support arm64
```
