#!/bin/bash
# Scenario 5: MySQL Table Lock — Login Page Blank/Hanging
#
# Fault: LOCK TABLE users WRITE (holds 600s) — blocks all queries on `users`
#
# Effect:
#   - /health           → 200 OK (SELECT 1 doesn't touch `users`)
#   - /login GET        → 200 OK (just renders HTML template, no DB)
#   - /login POST       → HANGS → gunicorn 30s worker timeout → 502 blank page
#   - /dashboard        → HANGS → 502 (queries `users` table)
#   - CW alarms         → ALL STAY OK (ALB sees /health as healthy)
#   - Canary            → OK (only checks /health)
#
# Detection:
#   NOT from CloudWatch alarms — they all stay green.
#   User reports in Slack/Feishu IM channel:
#     "Login page shows blank after I submit. Everything else looks fine."
#   Agent investigates → finds MySQL table lock → creates HealthIssue → RCA
#
# Recovery: Kill the MySQL lock session
#
# Usage: bash 05-mysql-table-lock.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

case "$action" in
    inject)
        log "=== Scenario 5: MySQL Table Lock (Login Page Hanging) ==="
        log "Pre-check: health=$(check_health)"

        # Verify login works before injection
        log "Pre-check: testing login POST..."
        login_code=$(curl -sk -o /dev/null -w '%{http_code}' \
            -X POST "${APP_URL}/login" \
            -d "username=admin&password=wrong" \
            --connect-timeout 5 --max-time 15 2>/dev/null || echo "000")
        log "  Login POST returns: $login_code (expected: 200 with 'invalid password')"

        log "Injecting fault: LOCK TABLE users WRITE for 600s..."
        # Run Python lock script in background on EC2 via SSM
        LOCK_CMD='source /opt/weblab/.env && nohup python3.11 -c "
import pymysql, time, os, sys
conn = pymysql.connect(
    host=os.environ[\"DB_HOST\"], port=3306,
    user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"],
    database=os.environ[\"DB_NAME\"],
)
cur = conn.cursor()
cur.execute(\"LOCK TABLE users WRITE\")
sys.stdout.write(\"LOCKED\n\")
sys.stdout.flush()
time.sleep(600)
cur.execute(\"UNLOCK TABLES\")
sys.stdout.write(\"UNLOCKED\n\")
conn.close()
" > /tmp/weblab-lock.log 2>&1 &
echo "PID=$!"
sleep 2
cat /tmp/weblab-lock.log'
        ssm_run_wait "$LOCK_CMD"

        log "Waiting 5s for lock to stabilize..."
        sleep 5

        # === Verify the exact symptoms ===
        log ""
        log "=== Symptom Verification ==="

        # 1) Health check: should still be 200
        health_code=$(check_health)
        log "  /health            → $health_code (expected: 200 — SELECT 1 unaffected)"

        # 2) Login GET: should still render
        login_get=$(curl -sk -o /dev/null -w '%{http_code}' \
            "${APP_URL}/login" --connect-timeout 5 --max-time 10 2>/dev/null || echo "000")
        log "  /login GET         → $login_get (expected: 200 — no DB query)"

        # 3) Login POST: should hang then 502
        log "  /login POST        → testing (will hang up to 35s)..."
        login_post=$(curl -sk -o /dev/null -w '%{http_code}' \
            -X POST "${APP_URL}/login" \
            -d "username=admin&password=admin123" \
            --connect-timeout 5 --max-time 35 2>/dev/null || echo "TIMEOUT")
        log "  /login POST        → $login_post (expected: 502/TIMEOUT — users table locked)"

        # 4) CW alarms: should all be OK
        log ""
        log "  CloudWatch alarms:"
        aws cloudwatch describe-alarms --alarm-name-prefix "weblab-" \
            --region "$REGION" \
            --query 'MetricAlarms[*].[AlarmName,StateValue]' --output text | \
            while read name state; do
                log "    $name → $state"
            done

        log ""
        log "=== Fault Active ==="
        log "Login page form loads fine, but submitting credentials → blank page / 502."
        log "Health checks, alarms, all infrastructure monitoring → NORMAL."
        log "This simulates a user reporting: 'I can't log in, page goes blank.'"
        log ""
        log "Lock will auto-release in ~10 minutes, or run: bash $0 recover"
        ;;

    verify)
        log "=== Verifying Scenario 5 ==="

        health_code=$(check_health)
        log "Health check: $health_code"

        login_get=$(curl -sk -o /dev/null -w '%{http_code}' \
            "${APP_URL}/login" --connect-timeout 5 --max-time 10 2>/dev/null || echo "000")
        log "Login GET: $login_get"

        log "Login POST (will wait up to 35s):"
        login_post=$(curl -sk -o /dev/null -w '%{http_code}' \
            -X POST "${APP_URL}/login" \
            -d "username=admin&password=admin123" \
            --connect-timeout 5 --max-time 35 2>/dev/null || echo "TIMEOUT")
        log "Login POST: $login_post"

        # Check MySQL process list for locks
        log ""
        log "MySQL PROCESSLIST (lock check):"
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=5)
cur = conn.cursor()
cur.execute(\"SHOW FULL PROCESSLIST\")
for row in cur.fetchall():
    print(f\"  ID={row[0]} User={row[1]} Command={row[4]} Time={row[5]} State={row[6]} Info={str(row[7])[:80]}\")
conn.close()
"'

        log ""
        log "CW Alarms:"
        aws cloudwatch describe-alarms --alarm-name-prefix "weblab-" \
            --region "$REGION" \
            --query 'MetricAlarms[*].[AlarmName,StateValue]' --output text | \
            while read name state; do
                log "  $name → $state"
            done
        ;;

    recover)
        log "=== Recovering Scenario 5 ==="

        # Kill the Python lock process on EC2
        log "Killing lock process on EC2..."
        ssm_run_wait 'pkill -f "LOCK TABLE" 2>/dev/null || true; sleep 1; cat /tmp/weblab-lock.log 2>/dev/null; rm -f /tmp/weblab-lock.log'

        # Also kill any stuck MySQL sessions holding table locks
        log "Cleaning up MySQL lock sessions..."
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=5)
cur = conn.cursor()
cur.execute(\"SHOW FULL PROCESSLIST\")
killed = 0
for row in cur.fetchall():
    cid, user, cmd, state, info = row[0], row[1], row[4], row[6], str(row[7] or \"\")
    if user == os.environ[\"DB_USER\"] and (\"LOCK\" in info.upper() or \"Locked\" in str(state) or cmd == \"Sleep\"):
        try:
            cur.execute(\"KILL %s\", (cid,))
            killed += 1
        except: pass
print(f\"Killed {killed} lock/stale sessions\")
conn.close()
"'

        log "Verifying login recovery..."
        sleep 3
        login_post=$(curl -sk -o /dev/null -w '%{http_code}' \
            -X POST "${APP_URL}/login" \
            -d "username=admin&password=wrong" \
            --connect-timeout 5 --max-time 15 2>/dev/null || echo "000")
        log "Login POST: $login_post (expected: 200)"

        log "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
