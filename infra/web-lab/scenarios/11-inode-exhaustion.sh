#!/bin/bash
# Scenario 11: Inode Exhaustion on 1GB EBS — Guaranteed Alarm Trigger
#
# Target: /mnt/weblab-data (1GB EBS gp3, ext4, ~65K inodes)
# Prerequisite: Run setup-ebs-volume.sh first to create/attach/mount the EBS volume
#
# Fault injection:
#   Simulate a "session cache cleanup gone haywire" — fills all inodes on the
#   app data EBS volume, then rotates logs + restarts gunicorn.
#   Gunicorn tries to create new log files → ENOSPC (no inodes) → fails to start.
#   ALB health check fails → weblab-unhealthy-hosts ALARM fires → SNS → Slack bot.
#
# Alert cascade:
#   T+0     Fill ~65,000 files on EBS → inodes 100%, disk space 1% used
#   T+0.5   15 POST /login → audit write fails → 500 errors → weblab-5xx-errors may fire
#   T+1     Rotate gunicorn logs + restart service
#   T+1.5   gunicorn fails to start (can't create log files) → service DOWN
#   T+3     ALB unhealthy threshold → weblab-unhealthy-hosts ALARM (guaranteed)
#   T+5     Canary fails → weblab-canary-failed ALARM
#
# What the agent sees:
#   - Alarm: "Unhealthy host count >= 1" — says NOTHING about inodes
#   - CW DiskSpaceUtilization: NORMAL (space is fine, no inode metric in CW)
#   - CloudTrail: NOTHING (OS-level issue)
#
# RCA investigation chain:
#   1. See weblab-unhealthy-hosts alarm → check ALB target health → all unhealthy
#   2. run_on_host: systemctl status weblab → "failed"
#   3. run_on_host: journalctl -u weblab → "No space left on device" opening log file
#   4. run_on_host: df -h /mnt/weblab-data → "1% used" ← MISLEADING! Space is fine!
#   5. KEY INSIGHT: df -i /mnt/weblab-data → "100% IUse" ← ROOT CAUSE
#   6. run_on_host: ls /mnt/weblab-data/.cache/session-tmp/ | wc -l → 65000+ files
#   7. Root cause: runaway process exhausted inodes on app data EBS volume
#
# Usage: bash 11-inode-exhaustion.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

# 1GB ext4 default: ~65,536 inodes. App uses ~20 → fill ~65,000 to exhaust.
FILL_COUNT=65000
FILL_DIR="/mnt/weblab-data/.cache/session-tmp"
MOUNT_POINT="/mnt/weblab-data"
LOG_DIR="${MOUNT_POINT}/logs"

case "$action" in
    inject)
        log "=== Scenario 11: Inode Exhaustion on 1GB EBS ==="
        log "Target: ${MOUNT_POINT} (1GB gp3 ext4, ~65K inodes)"
        log "Pre-check: health=$(check_health)"

        # --- Pre-checks ---
        log ""
        log "--- Pre-checks ---"
        log "EBS volume mount:"
        ssm_run_wait "mountpoint -q ${MOUNT_POINT} && echo 'Mounted OK' || { echo 'ERROR: ${MOUNT_POINT} not mounted! Run setup-ebs-volume.sh first.'; exit 1; }"
        log "Disk space (df -h):"
        ssm_run_wait "df -h ${MOUNT_POINT} | tail -1"
        log "Inodes (df -i):"
        ssm_run_wait "df -i ${MOUNT_POINT} | tail -1"
        log "gunicorn status:"
        ssm_run_wait 'systemctl is-active weblab 2>/dev/null; ps aux | grep gunicorn | grep -v grep | wc -l'
        log "Log files:"
        ssm_run_wait "ls -la ${LOG_DIR}/ 2>/dev/null || echo 'no log dir'"

        # === Phase 1: Fill all inodes on EBS ===
        log ""
        log "=== Phase 1: Filling inodes on EBS volume ==="
        log "Creating ${FILL_COUNT} empty files in ${FILL_DIR} ..."
        log "(Simulates: session cache cleanup cron gone haywire)"
        log "This will take 1-2 minutes..."

        INJECT_CMD="mkdir -p ${FILL_DIR} && cd ${FILL_DIR} && \
echo 'Creating files in batches...' && \
for batch in \$(seq 0 64); do \
  start=\$((batch * 1000 + 1)); \
  end=\$((batch * 1000 + 1000)); \
  seq \$start \$end | xargs -P 4 -I{} touch {} 2>/dev/null; \
  if [ \$((batch % 10)) -eq 0 ]; then echo \"  Batch \$batch done (\$end files)\"; fi; \
done && \
echo 'File creation complete' && \
echo \"Total files: \$(ls -1 ${FILL_DIR} | wc -l)\" && \
echo '' && echo 'Inodes after fill:' && \
df -i ${MOUNT_POINT} | tail -1 && \
echo '' && echo 'Disk space after fill:' && \
df -h ${MOUNT_POINT} | tail -1"

        cmd_id=$(ssm_run "$INJECT_CMD" 300)
        echo "  SSM command: $cmd_id (timeout: 300s)"
        status=$(ssm_wait "$cmd_id" 300)
        echo "  Status: $status"
        if [ "$status" = "Success" ]; then
            ssm_output "$cmd_id"
        else
            log "  WARNING: File creation may not have completed fully"
            log "  Checking inode status..."
        fi

        log ""
        log "--- Post-fill inode status ---"
        log "Disk space (should show ~1% used — MISLEADING):"
        ssm_run_wait "df -h ${MOUNT_POINT} | tail -1"
        log "Inodes (should show ~100% used — THE TRUTH):"
        ssm_run_wait "df -i ${MOUNT_POINT} | tail -1"

        # Confirm file creation fails
        log ""
        log "Test: can we create a file on EBS?"
        ssm_run_wait "touch ${MOUNT_POINT}/test-inode-check 2>&1 && echo 'CAN create (inodes not yet full)' && rm -f ${MOUNT_POINT}/test-inode-check || echo 'CONFIRMED: Cannot create files on EBS (inode exhaustion)'"

        # === Phase 2: Trigger 5xx errors (bonus alarm) ===
        log ""
        log "=== Phase 2: Triggering 500 errors via POST /login ==="
        log "Sending 15 login requests — audit write will fail → 500"
        for i in $(seq 1 15); do
            code=$(curl -sk -o /dev/null -w '%{http_code}' \
                -X POST "${APP_URL}/login" \
                -d "username=admin&password=admin123" \
                --connect-timeout 5 --max-time 10 2>/dev/null || echo "000")
            echo "  Request $i: HTTP $code"
        done

        # === Phase 3: Stop service, seal all inodes, restart → guaranteed crash ===
        # The mv-and-restart approach doesn't reliably exhaust inodes because
        # the initial fill may leave a few inodes free. Instead:
        # 1. Stop gunicorn (graceful)
        # 2. Delete log files (frees 2+ inodes)
        # 3. Fill those freed inodes with junk
        # 4. Start gunicorn → can't create log files → ENOSPC → crash
        log ""
        log "=== Phase 3: Stop service + seal inodes + restart → guaranteed crash ==="

        log "Stopping gunicorn..."
        ssm_run_wait 'systemctl stop weblab; echo "Stopped"'

        log "Deleting log files to free inodes, then filling them..."
        ssm_run_wait "rm -f ${LOG_DIR}/access.log ${LOG_DIR}/error.log ${LOG_DIR}/access.log.rotated ${LOG_DIR}/error.log.rotated 2>/dev/null; \
cd ${FILL_DIR} && i=70000; while touch \$i 2>/dev/null; do i=\$((i+1)); done; \
echo \"Filled to file \$((i-1))\"; \
df -i ${MOUNT_POINT} | tail -1; \
touch ${MOUNT_POINT}/verify-sealed 2>&1 || echo 'CONFIRMED: 0 free inodes'"

        log ""
        log "Starting weblab service..."
        log "gunicorn will try to create log files → ENOSPC → crash"
        ssm_run_wait "systemctl start weblab 2>&1; echo 'Exit code:' \$?"

        # Wait for systemd to retry and give up (RestartSec=5, StartLimitBurst=5)
        log "Waiting 30s for systemd restart retries to exhaust..."
        sleep 30

        log ""
        log "Service status after restart attempts:"
        ssm_run_wait 'systemctl status weblab --no-pager 2>&1 | head -20'
        ssm_run_wait 'journalctl -u weblab --no-pager -n 20 --since "2 min ago" 2>/dev/null | tail -15'

        # === Phase 4: Verify alarm will fire ===
        log ""
        log "=== Phase 4: Waiting for ALB to detect unhealthy target ==="
        log "ALB health check interval ~30s, unhealthy threshold ~2-3 checks"
        log "weblab-unhealthy-hosts alarm should fire within 3-5 minutes"

        health_code=$(check_health)
        log "  /health       -> $health_code (should be 000 or 5xx)"

        log ""
        log "  CW Alarms (initial — alarm may take 2-5 min to fire):"
        aws cloudwatch describe-alarms --alarm-name-prefix "weblab-" \
            --region "$REGION" \
            --query 'MetricAlarms[*].[AlarmName,StateValue]' --output text | \
            while read name state; do
                log "    $name -> $state"
            done

        log ""
        log "==========================================================="
        log "  INODE EXHAUSTION ACTIVE — GUARANTEED ALARM COMING"
        log "==========================================================="
        log ""
        log "  What happened:"
        log "    1. Filled ~${FILL_COUNT} files on ${MOUNT_POINT} → inodes 100%"
        log "    2. Rotated gunicorn logs → old handles still work"
        log "    3. Restarted gunicorn → can't create new log files → crash"
        log "    4. Service is DOWN → ALB sees 0 healthy targets"
        log ""
        log "  Expected alarms (within 3-5 min):"
        log "    weblab-unhealthy-hosts → ALARM (guaranteed: service is down)"
        log "    weblab-canary-failed   → ALARM (guaranteed: /health unreachable)"
        log "    weblab-5xx-errors      → ALARM (maybe: from Phase 2 login 500s)"
        log ""
        log "  The trap for the agent:"
        log "    Alarm says 'unhealthy targets' — no hint about inodes"
        log "    df -h ${MOUNT_POINT} shows ~1% used → 'disk looks fine'"
        log "    df -i ${MOUNT_POINT} shows 100% used → THE ROOT CAUSE"
        log "    CW DiskSpaceUtilization → NORMAL (no inode metric in CW!)"
        log "    CloudTrail → NOTHING (OS-level issue)"
        log "    Error: 'No space left on device' but there IS space"
        log ""
        log "  Monitor alarms: bash $0 verify"
        log "  Recover:        bash $0 recover"
        ;;

    verify)
        log "=== Verifying Scenario 11: Inode Exhaustion ==="

        health_code=$(check_health)
        log "Health check: $health_code"

        log ""
        log "--- The Key Diagnostic ---"
        log "Disk SPACE (looks normal — misleading):"
        ssm_run_wait "df -h ${MOUNT_POINT}"
        log ""
        log "Disk INODES (the real problem):"
        ssm_run_wait "df -i ${MOUNT_POINT}"

        log ""
        log "--- File Creation Test ---"
        ssm_run_wait "touch ${MOUNT_POINT}/test-verify 2>&1 && echo 'Can create files (NOT exhausted)' && rm -f ${MOUNT_POINT}/test-verify || echo 'CANNOT create files (inode exhaustion CONFIRMED)'"

        log ""
        log "--- Culprit Directory ---"
        ssm_run_wait "ls -d ${FILL_DIR} 2>/dev/null && echo 'Files: '\$(ls -1 ${FILL_DIR} 2>/dev/null | wc -l) || echo 'Directory not found'"

        log ""
        log "--- Application Status ---"
        ssm_run_wait 'systemctl status weblab --no-pager -l 2>/dev/null | head -15'
        ssm_run_wait 'echo "" && echo "gunicorn workers:" && ps aux | grep "gunicorn.*weblab" | grep -v grep || echo "no gunicorn running"'

        log ""
        log "--- Recent Errors ---"
        ssm_run_wait 'journalctl -u weblab --no-pager -n 20 --since "10 min ago" 2>/dev/null | grep -i "error\|space\|fail\|cannot\|ENOSPC" | tail -10 || echo "none"'

        log ""
        log "--- Log Files ---"
        ssm_run_wait "ls -la ${LOG_DIR}/ 2>/dev/null || echo 'log dir missing or inaccessible'"

        log ""
        log "--- CW Alarms ---"
        aws cloudwatch describe-alarms --alarm-name-prefix "weblab-" \
            --region "$REGION" \
            --query 'MetricAlarms[*].[AlarmName,StateValue]' --output text | \
            while read name state; do
                log "  $name -> $state"
            done

        log ""
        log "--- /status Endpoint ---"
        curl -sk "${APP_URL}/status" --connect-timeout 5 --max-time 15 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "(endpoint unreachable — service is down)"
        ;;

    recover)
        log "=== Recovering Scenario 11 ==="

        # Step 1: Remove junk files to free inodes
        log "Removing ${FILL_COUNT} files from ${FILL_DIR}..."
        log "  (This may take 1-2 minutes)"

        cmd_id=$(ssm_run "rm -rf ${FILL_DIR} && echo 'Junk files removed'" 300)
        echo "  SSM command: $cmd_id"
        status=$(ssm_wait "$cmd_id" 300)
        echo "  Status: $status"
        if [ "$status" = "Success" ]; then
            ssm_output "$cmd_id"
        fi

        log ""
        log "Post-cleanup inode status:"
        ssm_run_wait "df -i ${MOUNT_POINT} | tail -1"

        # Step 2: Recreate log files (inodes now available)
        log ""
        log "Recreating log files..."
        ssm_run_wait "rm -f ${LOG_DIR}/access.log.rotated ${LOG_DIR}/error.log.rotated; \
touch ${LOG_DIR}/access.log ${LOG_DIR}/error.log; \
ls -la ${LOG_DIR}/"

        # Step 3: Verify file creation works
        log ""
        log "File creation test:"
        ssm_run_wait "touch ${MOUNT_POINT}/test-recovery && echo 'File creation OK' && rm -f ${MOUNT_POINT}/test-recovery || echo 'STILL BLOCKED'"

        # Step 4: Reset systemd failure counter and restart weblab
        log ""
        log "Resetting systemd failure counter and restarting weblab..."
        ssm_run_wait 'systemctl reset-failed weblab 2>/dev/null; systemctl restart weblab'

        sleep 5
        wait_for_health 200 90

        log ""
        log "Post-recovery status:"
        ssm_run_wait 'systemctl status weblab --no-pager | head -10'

        log ""
        log "CW Alarms (should return to OK within ~5 min):"
        aws cloudwatch describe-alarms --alarm-name-prefix "weblab-" \
            --region "$REGION" \
            --query 'MetricAlarms[*].[AlarmName,StateValue]' --output text | \
            while read name state; do
                log "  $name -> $state"
            done

        log ""
        log "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
