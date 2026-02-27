---
name: log-analysis
description: "Log analysis and troubleshooting — covers CloudWatch Logs Insights queries, Kubernetes pod logs, system logs (journald, syslog), application log patterns, error correlation, and log-based metrics. Includes query templates for common investigation scenarios."
metadata:
  author: agenticops
  version: "1.0"
  domain: observability
---

# Log Analysis Skill

## Quick Decision Trees

### Finding Errors
1. CloudWatch Logs Insights — quick error scan:
   ```
   fields @timestamp, @message
   | filter @message like /(?i)(error|exception|fatal|critical)/
   | sort @timestamp desc
   | limit 50
   ```
2. Pod logs: `kubectl logs POD -c CONTAINER --since=1h | grep -i error`
3. System logs: `journalctl -p err --since "1 hour ago" --no-pager`
4. Multi-container: `kubectl logs POD --all-containers --since=1h`

### Error Correlation
1. Get timestamp of the error
2. Check other services at same timestamp +/- 5 minutes
3. CloudWatch Insights cross-log-group query:
   ```
   fields @timestamp, @message, @logStream
   | filter @timestamp > ago(1h)
   | filter @message like /error|exception/i
   | stats count() by bin(5m)
   ```
4. Correlate with CloudTrail for recent changes
5. Correlate with deployment events

### Log Volume Spike
1. Check ingestion rate: `aws cloudwatch get-metric-statistics --namespace AWS/Logs --metric-name IncomingBytes`
2. Find chatty log streams:
   ```
   fields @logStream
   | stats count() as cnt by @logStream
   | sort cnt desc
   | limit 10
   ```
3. Common causes: debug logging left on, retry loops, error cascades
4. Cost impact: estimate GB/month at current rate

### CloudWatch Logs Insights Patterns
1. **Parse structured logs**:
   ```
   parse @message "[*] * - *" as level, module, msg
   | filter level = "ERROR"
   | stats count() by module
   | sort count desc
   ```
2. **JSON logs**:
   ```
   fields @timestamp, @message
   | filter ispresent(errorCode)
   | stats count() by errorCode
   | sort count desc
   ```
3. **Latency percentiles**:
   ```
   filter @message like /duration/
   | parse @message "duration=* ms" as duration
   | stats avg(duration), pct(duration, 50), pct(duration, 95), pct(duration, 99) by bin(5m)
   ```
4. **Request tracing**:
   ```
   fields @timestamp, @message
   | filter @message like /REQUEST_ID/
   | sort @timestamp asc
   ```

## Common Patterns

### Kubernetes Log Patterns
- Follow logs: `kubectl logs -f POD -c CONTAINER`
- Previous crash: `kubectl logs POD --previous`
- All pods in deployment: `kubectl logs -l app=NAME --all-containers --since=1h`
- Stern (multi-pod): `stern DEPLOYMENT -n NAMESPACE --since 1h`

### System Log Analysis
- Boot issues: `journalctl -b -p err --no-pager`
- Service-specific: `journalctl -u nginx --since "2 hours ago" --no-pager`
- Kernel: `dmesg -T --level=err,crit,alert,emerg`
- Auth: `journalctl -u sshd | grep -c "Failed password"` (count brute force)

### Application Log Patterns
- Stack trace grouping: group by first line of stack trace
- Error rate: errors per minute as percentage of total log lines
- Slow request pattern: parse response time, alert on p99 > threshold
- Connection pool exhaustion: look for "connection timeout" or "pool exhausted"
