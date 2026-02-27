# Metric Selection Guide — Per-Service Thresholds

## Overview

This guide provides recommended metrics and threshold values for AWS services.
Thresholds are categorized as Warning (investigate within hours) and Critical
(immediate action required). Adjust based on your workload characteristics.

## EC2 Instances

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| CPUUtilization | Average | 5m | > 80% | > 95% | Sustained high CPU degrades response time |
| StatusCheckFailed | Maximum | 1m | — | > 0 | Any failure is critical; indicates host or instance issue |
| StatusCheckFailed_System | Maximum | 1m | — | > 0 | Underlying hardware failure; stop/start to migrate |
| StatusCheckFailed_Instance | Maximum | 1m | — | > 0 | OS-level failure; reboot or investigate |
| NetworkIn/NetworkOut | Sum | 5m | > 80% baseline | > 95% baseline | Compare against instance type network capacity |
| EBSIOBalance% | Average | 5m | < 30% | < 10% | Burst credit exhaustion imminent |
| EBSByteBalance% | Average | 5m | < 30% | < 10% | Throughput burst credits running low |

```bash
# Check current CPU across all instances
aws cloudwatch get-metric-data \
  --metric-data-queries '[
    {"Id":"cpu","MetricStat":{"Metric":{"Namespace":"AWS/EC2","MetricName":"CPUUtilization"},"Period":300,"Stat":"Average"},"ReturnData":true}
  ]' \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S)

# Get status check failures
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 \
  --metric-name StatusCheckFailed \
  --dimensions Name=InstanceId,Value=i-0123456789abcdef0 \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Maximum
```

## RDS Instances

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| CPUUtilization | Average | 5m | > 75% | > 90% | Scale up instance class or optimize queries |
| FreeableMemory | Average | 5m | < 512MB | < 256MB | Swap usage increases latency; scale instance |
| DatabaseConnections | Average | 5m | > 80% of max | > 90% of max | Max varies by instance class; use connection pooling |
| ReadIOPS / WriteIOPS | Average | 5m | > 80% provisioned | > 95% provisioned | For provisioned IOPS; gp3 has baseline 3000 |
| FreeStorageSpace | Average | 5m | < 20% total | < 10% total | Enable storage autoscaling or increase manually |
| ReplicaLag | Average | 1m | > 30s | > 120s | Network issue or replica under-provisioned |
| SwapUsage | Average | 5m | > 128MB | > 512MB | Indicates memory pressure |
| DiskQueueDepth | Average | 1m | > 5 | > 20 | IO bottleneck; consider provisioned IOPS |

```bash
# Check database connections vs max
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name DatabaseConnections \
  --dimensions Name=DBInstanceIdentifier,Value=prod-db \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average

# Check replica lag
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name ReplicaLag \
  --dimensions Name=DBInstanceIdentifier,Value=prod-db-replica \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average

# Max connections by instance class (approximate)
# db.t3.micro: 66, db.t3.small: 150, db.t3.medium: 500
# db.r5.large: 1700, db.r5.xlarge: 3400, db.r5.2xlarge: 5000
```

## Lambda Functions

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| Errors | Sum | 5m | errors/invocations > 1% | errors/invocations > 5% | Use metric math for error rate |
| Duration | p99 | 5m | > timeout * 0.8 | > timeout * 0.95 | Close to timeout = eventual failures |
| Throttles | Sum | 5m | > 0 | > 10/period | Request concurrency limit increase |
| ConcurrentExecutions | Maximum | 1m | > 80% of limit | > 90% of limit | Default limit: 1000 per region |
| IteratorAge | Maximum | 1m | > 60000 ms | > 300000 ms | Kinesis/DynamoDB stream processing lag |

```bash
# Error rate for a function over the last hour
aws cloudwatch get-metric-data \
  --metric-data-queries '[
    {"Id":"errors","MetricStat":{"Metric":{"Namespace":"AWS/Lambda","MetricName":"Errors","Dimensions":[{"Name":"FunctionName","Value":"my-function"}]},"Period":300,"Stat":"Sum"},"ReturnData":false},
    {"Id":"invocations","MetricStat":{"Metric":{"Namespace":"AWS/Lambda","MetricName":"Invocations","Dimensions":[{"Name":"FunctionName","Value":"my-function"}]},"Period":300,"Stat":"Sum"},"ReturnData":false},
    {"Id":"error_rate","Expression":"IF(invocations > 0, (errors/invocations)*100, 0)","Label":"Error Rate %","ReturnData":true}
  ]' \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S)

# Duration percentiles
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=my-function \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --extended-statistics p50 p95 p99
```

## ALB (Application Load Balancer)

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| HTTPCode_Target_5XX_Count | Sum | 5m | > 1% of requests | > 5% of requests | Backend errors; check target health |
| HTTPCode_ELB_5XX_Count | Sum | 5m | > 0 sustained | > 10/period | ALB itself failing; capacity issue |
| TargetResponseTime | p99 | 5m | > 2s | > 5s | Slow backends; check target CPU/memory |
| HealthyHostCount | Minimum | 1m | < desired count | < 2 | Targets failing health checks |
| UnHealthyHostCount | Maximum | 1m | > 0 | > 50% of targets | Check target health check path |
| ActiveConnectionCount | Sum | 1m | > 80% baseline | > 95% baseline | Connection exhaustion risk |
| RejectedConnectionCount | Sum | 1m | > 0 | > 10/period | ALB at max connections |

```bash
# 5XX error rate for ALB
aws cloudwatch get-metric-data \
  --metric-data-queries '[
    {"Id":"e5xx","MetricStat":{"Metric":{"Namespace":"AWS/ApplicationELB","MetricName":"HTTPCode_Target_5XX_Count","Dimensions":[{"Name":"LoadBalancer","Value":"app/my-alb/1234567890"}]},"Period":300,"Stat":"Sum"},"ReturnData":false},
    {"Id":"total","MetricStat":{"Metric":{"Namespace":"AWS/ApplicationELB","MetricName":"RequestCount","Dimensions":[{"Name":"LoadBalancer","Value":"app/my-alb/1234567890"}]},"Period":300,"Stat":"Sum"},"ReturnData":false},
    {"Id":"rate","Expression":"IF(total > 0, (e5xx/total)*100, 0)","Label":"5XX Rate %","ReturnData":true}
  ]' \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S)
```

## ECS (Elastic Container Service)

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| CPUUtilization (service) | Average | 5m | > 75% | > 90% | Scale out service task count |
| MemoryUtilization (service) | Average | 5m | > 80% | > 90% | Increase task memory or scale out |
| CPUUtilization (cluster) | Average | 5m | > 75% | > 85% | Add EC2 capacity (EC2 launch type) |
| RunningTaskCount | Average | 1m | < desired | < desired for 5m | Tasks failing to start; check events |

```bash
# ECS service CPU and memory
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ClusterName,Value=prod-cluster Name=ServiceName,Value=api-service \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average
```

## DynamoDB

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| ConsumedReadCapacityUnits | Sum | 5m | > 80% provisioned | > 90% provisioned | Scale up or switch to on-demand |
| ConsumedWriteCapacityUnits | Sum | 5m | > 80% provisioned | > 90% provisioned | Scale up or switch to on-demand |
| ThrottledRequests | Sum | 5m | > 0 sustained | > 10/period | Capacity insufficient for workload |
| SystemErrors | Sum | 5m | > 0 | > 5/period | DynamoDB internal errors (rare) |
| UserErrors | Sum | 5m | > baseline * 2 | > baseline * 5 | Application-side issues (validation, etc.) |
| ReplicationLatency | Average | 1m | > 200ms | > 1000ms | Global tables replication delay |
| SuccessfulRequestLatency | p99 | 5m | > 20ms | > 50ms | For single-item operations |

## ElastiCache (Redis)

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| CPUUtilization | Average | 5m | > 65% | > 80% | Redis is single-threaded; scale up |
| EngineCPUUtilization | Average | 5m | > 80% | > 90% | Redis engine CPU (more accurate) |
| DatabaseMemoryUsagePercentage | Average | 5m | > 75% | > 85% | Evictions start at maxmemory |
| CurrConnections | Average | 5m | > 50000 | > 60000 | Default max: 65000 |
| Evictions | Sum | 5m | > 0 sustained | > 100/period | Memory pressure causing data loss |
| ReplicationLag | Average | 1m | > 1s | > 5s | Read replica falling behind |
| CacheHitRate | Average | 5m | < 80% | < 60% | Low hit rate = cache not effective |

## API Gateway

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| 5XXError | Sum | 5m | > 1% of requests | > 5% of requests | Backend integration errors |
| 4XXError | Sum | 5m | > 10% of requests | > 25% of requests | Client errors (may indicate misconfiguration) |
| Latency | p99 | 5m | > 3s | > 10s | Close to 29s hard timeout |
| IntegrationLatency | p99 | 5m | > 2s | > 8s | Backend processing time |
| Count | Sum | 1m | > 80% throttle limit | > 90% throttle limit | Default: 10,000 rps per region |

## SQS

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| ApproximateAgeOfOldestMessage | Maximum | 5m | > 300s | > 3600s | Consumer falling behind |
| ApproximateNumberOfMessagesVisible | Average | 5m | > 10000 | > 100000 | Queue depth growing (scale consumers) |
| NumberOfMessagesSent | Sum | 5m | = 0 for 15m | = 0 for 1h | Producer may be down |
| NumberOfMessagesDeleted | Sum | 5m | = 0 for 15m | = 0 for 1h | Consumer may be down |
| ApproximateNumberOfMessagesNotVisible | Average | 5m | > expected inflight | > maxReceiveCount * queue depth | Messages stuck in processing |

## SNS

| Metric | Statistic | Period | Warning | Critical | Notes |
|--------|-----------|--------|---------|----------|-------|
| NumberOfNotificationsFailed | Sum | 5m | > 0 sustained | > 10/period | Delivery failures to subscribers |
| NumberOfNotificationsDelivered | Sum | 5m | = 0 for 15m | = 0 for 1h | No messages flowing |
| PublishSize | Average | 5m | > 200KB | > 256KB | Approaching 256KB max message size |

## General Recommendations

1. **Start with AWS defaults**: Many services publish basic metrics at no extra cost
2. **Add CWAgent for OS-level**: disk, memory, processes are not available without the agent
3. **Use anomaly detection** for metrics with natural variation (request count, latency)
4. **Create composite alarms** to reduce noise — "CPU high AND error rate high" is more actionable than either alone
5. **Review alarms quarterly**: remove stale alarms, adjust thresholds based on new baselines
6. **Tag alarms**: use tags to track ownership, environment, and severity
7. **Document runbooks**: every critical alarm should link to a runbook in its description
