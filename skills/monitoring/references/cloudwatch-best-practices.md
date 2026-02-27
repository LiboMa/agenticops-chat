# CloudWatch Best Practices

## Alarm Configuration

### Evaluation Periods and Datapoints to Alarm

The distinction between evaluation periods and datapoints-to-alarm is critical for
reducing false positives while maintaining responsiveness.

```bash
# Create an alarm that triggers when CPU > 80% for 3 out of 5 consecutive 1-minute periods
aws cloudwatch put-metric-alarm \
  --alarm-name "high-cpu-prod-web" \
  --metric-name CPUUtilization \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 60 \
  --evaluation-periods 5 \
  --datapoints-to-alarm 3 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=InstanceId,Value=i-0123456789abcdef0 \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:ops-alerts \
  --ok-actions arn:aws:sns:us-east-1:123456789012:ops-resolved \
  --treat-missing-data notBreaching
```

**Recommended settings by severity**:

| Severity | Period | Eval Periods | Datapoints | Treat Missing |
|----------|--------|--------------|------------|---------------|
| Critical (page) | 60s | 3 | 3 | breaching |
| Warning (ticket) | 300s | 3 | 2 | notBreaching |
| Info (dashboard) | 300s | 5 | 3 | ignore |

### Treat Missing Data

- `breaching` — missing data counts as exceeding threshold (use for critical health checks)
- `notBreaching` — missing data counts as within threshold (default for most alarms)
- `ignore` — alarm state does not change during missing data (use for sporadic metrics)
- `missing` — alarm evaluates to INSUFFICIENT_DATA (avoid for operational alarms)

```bash
# Check how an alarm treats missing data
aws cloudwatch describe-alarms --alarm-names "my-alarm" \
  | jq '.MetricAlarms[0].TreatMissingData'
```

## Metric Math Expressions

### Error Rate Calculation

```bash
# Create alarm on error rate (errors / total requests * 100)
aws cloudwatch put-metric-alarm \
  --alarm-name "high-error-rate-api" \
  --metrics '[
    {"Id":"errors","MetricStat":{"Metric":{"Namespace":"AWS/ApplicationELB","MetricName":"HTTPCode_Target_5XX_Count","Dimensions":[{"Name":"LoadBalancer","Value":"app/my-alb/1234567890"}]},"Period":300,"Stat":"Sum"},"ReturnData":false},
    {"Id":"total","MetricStat":{"Metric":{"Namespace":"AWS/ApplicationELB","MetricName":"RequestCount","Dimensions":[{"Name":"LoadBalancer","Value":"app/my-alb/1234567890"}]},"Period":300,"Stat":"Sum"},"ReturnData":false},
    {"Id":"error_rate","Expression":"(errors/total)*100","Label":"Error Rate %","ReturnData":true}
  ]' \
  --evaluation-periods 3 \
  --datapoints-to-alarm 2 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:ops-alerts \
  --treat-missing-data notBreaching
```

### Cache Hit Ratio

```bash
# ElastiCache hit ratio: hits / (hits + misses) * 100
aws cloudwatch put-metric-alarm \
  --alarm-name "low-cache-hit-ratio" \
  --metrics '[
    {"Id":"hits","MetricStat":{"Metric":{"Namespace":"AWS/ElastiCache","MetricName":"CacheHits","Dimensions":[{"Name":"CacheClusterId","Value":"prod-cache"}]},"Period":300,"Stat":"Sum"},"ReturnData":false},
    {"Id":"misses","MetricStat":{"Metric":{"Namespace":"AWS/ElastiCache","MetricName":"CacheMisses","Dimensions":[{"Name":"CacheClusterId","Value":"prod-cache"}]},"Period":300,"Stat":"Sum"},"ReturnData":false},
    {"Id":"ratio","Expression":"(hits/(hits+misses))*100","Label":"Cache Hit %","ReturnData":true}
  ]' \
  --evaluation-periods 3 \
  --threshold 70 \
  --comparison-operator LessThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:ops-alerts
```

## Composite Alarms

Composite alarms combine multiple alarms with boolean logic to reduce noise
and create higher-fidelity signals.

```bash
# Create a composite alarm: triggers only when BOTH CPU is high AND error rate is high
aws cloudwatch put-composite-alarm \
  --alarm-name "service-degraded-prod-api" \
  --alarm-rule 'ALARM("high-cpu-prod-api") AND ALARM("high-error-rate-api")' \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:pager-duty-critical \
  --ok-actions arn:aws:sns:us-east-1:123456789012:ops-resolved \
  --alarm-description "Service degraded: both high CPU and elevated error rate"

# OR-based composite: any of the health checks failing
aws cloudwatch put-composite-alarm \
  --alarm-name "any-healthcheck-failing" \
  --alarm-rule 'ALARM("healthcheck-us-east-1") OR ALARM("healthcheck-us-west-2") OR ALARM("healthcheck-eu-west-1")' \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:ops-alerts

# Suppress during maintenance windows
aws cloudwatch put-composite-alarm \
  --alarm-name "prod-alerts-with-suppression" \
  --alarm-rule 'ALARM("high-error-rate-api") AND NOT ALARM("maintenance-window-active")' \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:ops-alerts
```

## Cross-Account Monitoring

```bash
# In monitoring account: create a cross-account dashboard
aws cloudwatch put-dashboard \
  --dashboard-name "multi-account-overview" \
  --dashboard-body '{
    "widgets": [
      {
        "type": "metric",
        "properties": {
          "metrics": [
            [{"expression":"SEARCH(\u0027{AWS/EC2,InstanceId} MetricName=\"CPUUtilization\"\u0027, \u0027Average\u0027, 300)","id":"e1","accountId":"111111111111","label":"Prod"}],
            [{"expression":"SEARCH(\u0027{AWS/EC2,InstanceId} MetricName=\"CPUUtilization\"\u0027, \u0027Average\u0027, 300)","id":"e2","accountId":"222222222222","label":"Staging"}]
          ],
          "period": 300,
          "title": "EC2 CPU - All Accounts"
        }
      }
    ]
  }'

# Set up cross-account role in source account
# Monitoring account assumes role in source accounts to read metrics
```

## CloudWatch Agent Configuration

### Standard Linux Configuration

```json
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "cwagent"
  },
  "metrics": {
    "namespace": "CWAgent",
    "append_dimensions": {
      "InstanceId": "${aws:InstanceId}",
      "AutoScalingGroupName": "${aws:AutoScalingGroupName}"
    },
    "aggregation_dimensions": [["AutoScalingGroupName"]],
    "metrics_collected": {
      "cpu": {
        "measurement": ["cpu_usage_idle", "cpu_usage_iowait", "cpu_usage_steal"],
        "metrics_collection_interval": 60,
        "totalcpu": true
      },
      "disk": {
        "measurement": ["used_percent", "inodes_free"],
        "metrics_collection_interval": 300,
        "resources": ["*"],
        "ignore_file_system_types": ["sysfs", "devtmpfs", "tmpfs"]
      },
      "diskio": {
        "measurement": ["io_time", "write_bytes", "read_bytes"],
        "metrics_collection_interval": 60,
        "resources": ["*"]
      },
      "mem": {
        "measurement": ["mem_used_percent", "mem_available_percent"],
        "metrics_collection_interval": 60
      },
      "netstat": {
        "measurement": ["tcp_established", "tcp_time_wait"],
        "metrics_collection_interval": 60
      },
      "processes": {
        "measurement": ["running", "sleeping", "zombies"]
      }
    }
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/messages",
            "log_group_name": "/ec2/system/messages",
            "log_stream_name": "{instance_id}",
            "retention_in_days": 30
          },
          {
            "file_path": "/var/log/application/*.log",
            "log_group_name": "/ec2/application",
            "log_stream_name": "{instance_id}/{file_name}",
            "retention_in_days": 14
          }
        ]
      }
    }
  }
}
```

### Process Monitoring (procstat)

```json
{
  "metrics": {
    "metrics_collected": {
      "procstat": [
        {
          "pattern": "nginx",
          "measurement": ["cpu_usage", "memory_rss", "read_bytes", "write_bytes", "pid_count"]
        },
        {
          "pattern": "java.*myapp",
          "measurement": ["cpu_usage", "memory_rss", "memory_vms", "pid_count"]
        }
      ]
    }
  }
}
```

## Embedded Metric Format (EMF) for Lambda

```python
# Python Lambda — emit structured metrics via stdout
import json

def handler(event, context):
    # Process request
    duration_ms = 42
    status_code = 200

    # EMF log line — CloudWatch automatically extracts metrics
    print(json.dumps({
        "_aws": {
            "Timestamp": 1234567890000,
            "CloudWatchMetrics": [{
                "Namespace": "MyApp",
                "Dimensions": [["FunctionName", "Environment"]],
                "Metrics": [
                    {"Name": "RequestDuration", "Unit": "Milliseconds"},
                    {"Name": "RequestCount", "Unit": "Count"}
                ]
            }]
        },
        "FunctionName": context.function_name,
        "Environment": "prod",
        "RequestDuration": duration_ms,
        "RequestCount": 1,
        "StatusCode": status_code,
        "message": f"Processed request in {duration_ms}ms"
    }))
```

## Dashboard Best Practices

- Group widgets by service or business domain, not by metric type
- Use annotations for deployment markers and incident timestamps
- Set default time range to 3 hours (balances detail vs overview)
- Include a text widget with runbook links at the top of operational dashboards
- Use SEARCH expressions to auto-discover new resources

## Cost Optimization

- Standard resolution (60s) metrics are free for AWS services
- High-resolution (1s) metrics cost $0.30/metric/month — use sparingly
- Custom metrics: $0.30/metric/month for the first 10,000
- Reduce custom metric count by using dimensions instead of separate metrics
- Use metric streams to S3 for long-term storage instead of extending retention
- Dashboard cost: first 3 dashboards free, then $3/dashboard/month
- Logs: $0.50/GB ingestion, $0.03/GB storage — set retention policies aggressively
