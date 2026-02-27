# CloudWatch Logs Insights Query Library

## Overview

Copy-paste ready queries for common investigation scenarios across AWS services.
All queries assume CloudWatch Logs Insights syntax. Select the appropriate log group
before running each query.

## Lambda Function Queries

### Cold Starts

Log group: `/aws/lambda/FUNCTION_NAME`

```
filter @type = "REPORT"
| fields @requestId, @duration, @billedDuration, @memorySize, @maxMemoryUsed, @initDuration
| filter ispresent(@initDuration)
| stats count() as coldStarts,
        avg(@initDuration) as avgColdStart,
        max(@initDuration) as maxColdStart,
        pct(@initDuration, 95) as p95ColdStart
        by bin(1h)
| sort bin desc
```

### Error Analysis

```
filter @type = "REPORT" and @errors > 0
| fields @requestId, @duration, @billedDuration
| sort @timestamp desc
| limit 50
```

### Error Messages with Context

```
fields @timestamp, @requestId, @message
| filter @message like /(?i)(error|exception|traceback|fatal)/
| sort @timestamp desc
| limit 100
```

### Duration Percentiles Over Time

```
filter @type = "REPORT"
| stats avg(@duration) as avgDuration,
        pct(@duration, 50) as p50,
        pct(@duration, 95) as p95,
        pct(@duration, 99) as p99,
        max(@duration) as maxDuration,
        count() as invocations
        by bin(5m)
| sort bin desc
```

### Memory Utilization

```
filter @type = "REPORT"
| stats avg(@maxMemoryUsed/@memorySize * 100) as avgMemPct,
        max(@maxMemoryUsed/@memorySize * 100) as maxMemPct,
        count() as invocations
        by bin(1h)
| sort bin desc
```

### Timeout Detection

```
filter @type = "REPORT"
| filter @duration > 28000
| fields @requestId, @duration, @timestamp
| sort @timestamp desc
| limit 20
```

## ALB Access Log Queries

Log group: configured via ALB access log settings or forwarded to CloudWatch

### 5XX Errors by Target

```
fields @timestamp, elb_status_code, target_status_code, request_url, target_ip
| filter elb_status_code >= 500 or target_status_code >= 500
| stats count() as errors by target_ip, target_status_code
| sort errors desc
| limit 20
```

### Slow Requests (Response Time > 2s)

```
fields @timestamp, request_url, target_processing_time, elb_status_code
| filter target_processing_time > 2.0
| stats count() as slowCount,
        avg(target_processing_time) as avgTime,
        max(target_processing_time) as maxTime
        by request_url
| sort slowCount desc
| limit 20
```

### Request Distribution by Path

```
parse @message /\"(?:GET|POST|PUT|DELETE|PATCH) (?<path>[^ ?]+)/
| stats count() as requests,
        avg(target_processing_time) as avgLatency
        by path
| sort requests desc
| limit 30
```

### Error Rate Over Time

```
stats count() as total,
      sum(elb_status_code >= 500) as errors_5xx,
      sum(elb_status_code >= 400 and elb_status_code < 500) as errors_4xx
      by bin(5m)
| sort bin desc
```

## VPC Flow Log Queries

Log group: VPC flow log log group

### Rejected Connections

```
fields @timestamp, srcAddr, dstAddr, srcPort, dstPort, protocol, action
| filter action = "REJECT"
| stats count() as rejectedCount by srcAddr, dstAddr, dstPort
| sort rejectedCount desc
| limit 25
```

### Top Talkers (Most Data Transferred)

```
fields srcAddr, dstAddr, bytes
| stats sum(bytes) as totalBytes by srcAddr, dstAddr
| sort totalBytes desc
| limit 20
```

### Connections to Specific Port

```
fields @timestamp, srcAddr, dstAddr, srcPort, dstPort, action, protocol
| filter dstPort = 22
| stats count() as connectionCount by srcAddr, action
| sort connectionCount desc
| limit 20
```

### Rejected Connections by Security Group (Inbound)

```
filter action = "REJECT" and dstPort != 443 and dstPort != 80
| stats count() as rejections by dstAddr, dstPort
| sort rejections desc
| limit 20
```

### Traffic Volume Over Time

```
stats sum(bytes) as totalBytes, count() as flowCount by bin(5m)
| sort bin desc
```

### Cross-AZ Traffic Detection

```
fields srcAddr, dstAddr, bytes, az_id
| filter srcAddr like /10\./ and dstAddr like /10\./
| stats sum(bytes) as crossAZBytes by srcAddr, dstAddr
| sort crossAZBytes desc
| limit 20
```

## CloudTrail Queries

Log group: CloudTrail log group

### Unauthorized API Calls

```
filter errorCode like /Unauthorized|AccessDenied|Forbidden/
| fields @timestamp, userIdentity.arn, eventName, errorCode, errorMessage, sourceIPAddress
| sort @timestamp desc
| limit 50
```

### Root Account Usage

```
filter userIdentity.type = "Root"
| fields @timestamp, eventName, sourceIPAddress, userAgent, errorCode
| sort @timestamp desc
| limit 50
```

### Security Group Changes

```
filter eventName like /SecurityGroup/
| fields @timestamp, userIdentity.arn, eventName, requestParameters.groupId,
         requestParameters.ipPermissions, responseElements
| sort @timestamp desc
| limit 50
```

### IAM Changes

```
filter eventSource = "iam.amazonaws.com"
| filter eventName like /Create|Delete|Attach|Detach|Put|Update|Add|Remove/
| fields @timestamp, userIdentity.arn, eventName, requestParameters
| sort @timestamp desc
| limit 50
```

### Console Logins

```
filter eventName = "ConsoleLogin"
| fields @timestamp, userIdentity.arn, sourceIPAddress,
         responseElements.ConsoleLogin, additionalEventData.MFAUsed
| sort @timestamp desc
| limit 50
```

### Resource Deletion Events

```
filter eventName like /^Delete|^Terminate|^Remove/
| fields @timestamp, userIdentity.arn, eventName, requestParameters, errorCode
| sort @timestamp desc
| limit 50
```

### API Call Frequency by User

```
stats count() as apiCalls by userIdentity.arn, eventName
| sort apiCalls desc
| limit 30
```

## API Gateway Queries

Log group: `/aws/apigateway/API_NAME` or execution log group

### Latency by Resource and Method

```
fields @timestamp, httpMethod, resourcePath, status, latency, integrationLatency
| stats avg(latency) as avgLatency,
        pct(latency, 95) as p95Latency,
        pct(latency, 99) as p99Latency,
        count() as requests
        by httpMethod, resourcePath
| sort p99Latency desc
| limit 20
```

### Error Responses

```
fields @timestamp, httpMethod, resourcePath, status, errorMessage
| filter status >= 400
| stats count() as errorCount by status, resourcePath, httpMethod
| sort errorCount desc
| limit 20
```

### Throttled Requests

```
filter status = 429
| fields @timestamp, httpMethod, resourcePath, ip
| stats count() as throttled by ip, resourcePath
| sort throttled desc
| limit 20
```

## ECS Container Queries

Log group: `/ecs/CLUSTER_NAME/SERVICE_NAME` or configured log driver group

### Container Errors

```
fields @timestamp, @message, @logStream
| filter @message like /(?i)(error|exception|fatal|panic|killed|oom)/
| sort @timestamp desc
| limit 50
```

### OOM Kills

```
fields @timestamp, @message, @logStream
| filter @message like /(?i)(out of memory|oom|killed process|memory cgroup)/
| sort @timestamp desc
| limit 20
```

### Health Check Failures

```
fields @timestamp, @message
| filter @message like /(?i)(health.?check|unhealthy|failed.*health)/
| sort @timestamp desc
| limit 30
```

### Container Start/Stop Events

```
fields @timestamp, @message
| filter @message like /(?i)(starting|started|stopping|stopped|exited|terminated)/
| sort @timestamp desc
| limit 50
```

## Cross-Service Correlation

### Error Spike Timeline (Multi-Log-Group)

Select multiple log groups and run:

```
fields @timestamp, @message, @logStream, @log
| filter @message like /(?i)(error|exception|fatal)/
| stats count() as errorCount by bin(1m), @log
| sort bin desc
```

### Trace a Request Across Services

```
fields @timestamp, @message, @log
| filter @message like /TRACE_ID_OR_REQUEST_ID/
| sort @timestamp asc
```

### Deployment Correlation

Run after identifying an error spike start time:

```
# In CloudTrail log group
filter eventName like /UpdateService|UpdateFunctionCode|CreateDeployment|RegisterTaskDefinition/
| filter @timestamp > "2024-01-15T10:00:00"
| filter @timestamp < "2024-01-15T11:00:00"
| fields @timestamp, userIdentity.arn, eventName, requestParameters
| sort @timestamp asc
```

## Cost Optimization Queries

### Log Volume by Stream

```
fields @logStream
| stats count() as lineCount by @logStream
| sort lineCount desc
| limit 20
```

### Identify Debug/Verbose Logging

```
fields @message
| filter @message like /(?i)(debug|trace|verbose)/
| stats count() as debugLines
```

### Estimate Monthly Cost

```
# Run over 1 hour, then multiply by 720 for monthly estimate
stats count() as lines, sum(strlen(@message)) as totalBytes
```
