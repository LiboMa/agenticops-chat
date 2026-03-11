#!/bin/bash
# Scenario 7: Memory Leak → OOM Kill — gradual memory exhaustion kills gunicorn
#
# Fault chain:
#   1. Spawn a background process that gradually consumes memory (~50MB/10s)
#   2. t3.micro has 1GB RAM → ~60-90s until memory pressure
#   3. Linux OOM killer targets gunicorn workers (high RSS, low oom_score_adj)
#   4. systemd restarts weblab, but OOM killer may strike again
#   5. Oscillating health: healthy → 502 → healthy → 502 (flapping)
#
# RCA challenge:
#   - Alarm may show intermittent unhealthy (flapping pattern)
#   - CloudTrail has NO relevant events
#   - CW EC2 MemoryUtilization is NOT available by default (needs CW Agent)
#   - Agent must correlate: (a) no API changes + (b) flapping health + (c) dmesg/syslog OOM entries
#   - Tests: host-level investigation, correlating OS logs with application symptoms
#
# Detection: ALB unhealthy-hosts flapping → ALARM
# Recovery: Kill the memory hog process
#
# Usage: bash 07-memory-leak-oom.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

case "$action" in
    inject)
        log "=== Scenario 7: Memory Leak -> OOM Kill ==="
        log "Pre-check: health=$(check_health)"

        # Check current memory
        log "Pre-check: memory usage..."
        ssm_run_wait 'free -m | head -2'

        log "Injecting fault: starting memory hog process (50MB every 10s)..."
        LEAK_CMD='nohup python3.11 -c "
import time, os, sys
chunks = []
sys.stdout.write(f\"PID={os.getpid()} starting memory leak\\n\")
sys.stdout.flush()
try:
    while True:
        # Allocate 50MB chunk and touch it to force physical allocation
        chunk = bytearray(50 * 1024 * 1024)
        for i in range(0, len(chunk), 4096):
            chunk[i] = 1
        chunks.append(chunk)
        total_mb = len(chunks) * 50
        sys.stdout.write(f\"Allocated {total_mb}MB total\\n\")
        sys.stdout.flush()
        time.sleep(10)
except MemoryError:
    sys.stdout.write(\"MemoryError reached\\n\")
    sys.stdout.flush()
    time.sleep(3600)
" > /tmp/weblab-memleak.log 2>&1 &
echo "PID=$!"'
        ssm_run_wait "$LEAK_CMD"

        log "Memory hog started. Waiting 30s for pressure to build..."
        sleep 30

        log ""
        log "=== Symptom Verification ==="

        log "Memory after 30s:"
        ssm_run_wait 'free -m | head -2'

        health_code=$(check_health)
        log "  /health            -> $health_code"

        log ""
        log "  dmesg (OOM killer, last 10):"
        ssm_run_wait 'dmesg -T 2>/dev/null | grep -i "oom\|killed\|out of memory" | tail -10 || echo "no OOM entries yet"'

        log ""
        log "  gunicorn processes:"
        ssm_run_wait 'ps aux | grep gunicorn | grep -v grep | awk "{print \$2, \$4\"%MEM\", \$6\"KB_RSS\", \$11}" || echo "not running"'

        log ""
        log "=== Fault Active ==="
        log "Memory pressure building. gunicorn workers will be OOM-killed."
        log "Expect flapping: healthy -> 502 -> healthy (systemd restart) -> 502 (OOM again)"
        log "CloudTrail: NO API events. Agent must check OS-level metrics."
        log "Key evidence: dmesg 'Out of memory: Killed process' entries"
        log ""
        log "Auto-escalation: ~60-90s to full OOM impact on t3.micro."
        log "Run: bash $0 recover"
        ;;

    verify)
        log "=== Verifying Scenario 7 ==="

        health_code=$(check_health)
        log "Health check: $health_code"

        log "Memory:"
        ssm_run_wait 'free -m'

        log ""
        log "Memory hog process:"
        ssm_run_wait 'ps aux | grep "memory leak" | grep -v grep || echo "memory hog not running (may have been OOM-killed)"'

        log ""
        log "OOM killer activity:"
        ssm_run_wait 'dmesg -T 2>/dev/null | grep -i "oom\|killed\|out of memory" | tail -20 || echo "no OOM entries"'

        log ""
        log "gunicorn status:"
        ssm_run_wait 'systemctl status weblab --no-pager -l 2>/dev/null | head -15'

        log ""
        log "Memory hog log:"
        ssm_run_wait 'cat /tmp/weblab-memleak.log 2>/dev/null || echo "no log"'

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
        log "=== Recovering Scenario 7 ==="

        log "Killing memory hog process..."
        ssm_run_wait 'pkill -f "memory leak" 2>/dev/null; sleep 1; pkill -9 -f "memory leak" 2>/dev/null; rm -f /tmp/weblab-memleak.log; echo "done"'

        log "Memory after cleanup:"
        ssm_run_wait 'free -m | head -2'

        log "Restarting weblab service..."
        ssm_run_wait 'systemctl restart weblab'

        sleep 5
        wait_for_health 200 90
        log "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
