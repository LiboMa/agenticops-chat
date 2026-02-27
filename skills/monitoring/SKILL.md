---
name: monitoring
description: "Monitoring and observability troubleshooting — covers CloudWatch alarms, metrics, dashboards, Prometheus/Grafana patterns, alert fatigue reduction, metric gap analysis, coverage assessment, SLI/SLO definitions, and anomaly detection strategies."
metadata:
  author: agenticops
  version: "1.0"
  domain: observability
---

# Monitoring Skill

## Quick Decision Trees

### Alarm Investigation
1. Check alarm state: `aws cloudwatch describe-alarms --alarm-names NAME`
2. "ALARM" state:
   - Check metric data: `aws cloudwatch get-metric-statistics` for the period
   - Verify threshold is appropriate (not too sensitive)
   - Check evaluation periods — single breach vs sustained
   - Missing data treatment: "breaching" vs "notBreaching" vs "missing"
3. "INSUFFICIENT_DATA":
   - Metric not being published → check agent, namespace, dimensions
   - Period too short for metric publishing frequency
   - New metric — needs time to accumulate data points
4. Flapping alarm (ALARM→OK→ALARM repeatedly):
   - Threshold too close to normal operating range
   - Add evaluation periods (e.g., 3 out of 5 instead of 1 out of 1)
   - Consider anomaly detection band instead of static threshold

### Metric Gaps
1. `aws cloudwatch list-metrics --namespace NS --metric-name NAME` — verify metric exists
2. Check dimensions match exactly (case-sensitive!)
3. CloudWatch agent: `systemctl status amazon-cloudwatch-agent`
4. Custom metrics: check PutMetricData calls in application logs
5. EC2 detailed monitoring: 1-min vs 5-min basic (default)
6. Lambda: check function is being invoked (no invocations = no metrics)

### Alert Fatigue
1. Audit alarm count: `aws cloudwatch describe-alarms --state-value ALARM | jq '.MetricAlarms | length'`
2. Classification:
   - **Critical**: immediate human action required (page)
   - **Warning**: investigate within hours (ticket)
   - **Info**: trend awareness (dashboard only)
3. Reduce noise:
   - Increase evaluation periods for non-critical alarms
   - Use composite alarms to combine related signals
   - Set OK actions to auto-resolve tickets
   - Use anomaly detection for variable workloads
4. Coverage gaps: compare monitored resources vs total resources per service

### SLI/SLO Setup
1. Define SLIs (Service Level Indicators):
   - Availability: successful requests / total requests
   - Latency: % requests under threshold (e.g., p99 < 500ms)
   - Throughput: requests per second at steady state
2. Set SLOs: target percentage over rolling window (e.g., 99.9% over 30 days)
3. Error budget: 100% - SLO = allowable downtime
4. CloudWatch math expressions for SLI calculation:
   - `m1/m2 * 100` where m1=success_count, m2=total_count

## Common Patterns

### CloudWatch Best Practices
- Use metric math for derived metrics (error rate, cache hit ratio)
- Composite alarms for multi-signal alerting
- Cross-account observability for multi-account setups
- Contributor Insights for top-N analysis
- Anomaly detection for seasonal/variable workloads

### Key Metrics by Service
- EC2: CPUUtilization, NetworkIn/Out, DiskReadOps/WriteOps, StatusCheckFailed
- RDS: CPUUtilization, FreeableMemory, ReadIOPS/WriteIOPS, DatabaseConnections, ReplicaLag
- Lambda: Invocations, Errors, Duration, Throttles, ConcurrentExecutions
- ALB: RequestCount, HTTPCode_Target_4XX/5XX, TargetResponseTime, HealthyHostCount
- ECS: CPUUtilization, MemoryUtilization (service and cluster level)
- DynamoDB: ConsumedRCU/WCU, ThrottledRequests, SystemErrors
