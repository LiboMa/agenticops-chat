#!/bin/bash
# Scenario 5: MySQL Table Lock — lock the users table causing timeouts
#
# Fault: Connect to MySQL via SSM → LOCK TABLE users WRITE (holds lock for 120s)
# Expected: Login/register/dashboard all hang → health check times out (read_timeout=10)
#           → ALB → unhealthy → ALARM → SNS → Lambda → Feishu → Agent → RCA
# Recovery: Kill the MySQL lock session (or wait for it to expire)
#
# Usage: bash 05-mysql-table-lock.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

case "$action" in
    inject)
        log "=== Scenario 5: MySQL Table Lock ==="
        log "Pre-check: $(check_health)"

        log "Injecting fault: locking users table for 120s via SSM..."
        # Run a MySQL session that locks the table, holds for 120s, then releases
        # This runs in background on the EC2 instance
        LOCK_CMD='source /opt/weblab/.env && python3.11 -c "
import pymysql, time, os
conn = pymysql.connect(
    host=os.environ[\"DB_HOST\"], port=3306,
    user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"],
    database=os.environ[\"DB_NAME\"],
)
cur = conn.cursor()
cur.execute(\"LOCK TABLE users WRITE\")
print(\"Table locked\")
time.sleep(120)
cur.execute(\"UNLOCK TABLES\")
print(\"Table unlocked\")
conn.close()
" &>/tmp/weblab-lock.log &
echo $!'
        ssm_run_wait "$LOCK_CMD"

        log "Waiting 10s for lock to take effect..."
        sleep 10

        log "Verifying fault..."
        code=$(check_health)
        log "App health: $code (expected: 503 or timeout due to locked table)"

        log "Fault injected. The users table is locked for ~120s."
        log "All queries to users table will hang until lock is released."
        log "The lock will auto-release after 120s, or use 'recover' to kill it."
        ;;

    verify)
        log "=== Verifying Scenario 5 ==="
        code=$(check_health)
        log "App health: $code"

        response=$(curl -sk "${APP_URL}/health" --connect-timeout 5 --max-time 15 2>/dev/null || echo '{"error":"timeout"}')
        log "Health response: $response"

        # Check lock status via SSM
        log "MySQL process list (checking for locks):"
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=5)
cur = conn.cursor()
cur.execute(\"SHOW PROCESSLIST\")
for row in cur.fetchall():
    print(row)
conn.close()
"'

        for alarm in weblab-unhealthy-hosts weblab-canary-failed; do
            alarm_state=$(aws cloudwatch describe-alarms \
                --alarm-names "$alarm" \
                --region "$REGION" \
                --query 'MetricAlarms[0].StateValue' --output text)
            log "Alarm $alarm: $alarm_state"
        done
        ;;

    recover)
        log "=== Recovering Scenario 5 ==="
        log "Killing lock process on EC2..."
        ssm_run_wait 'pkill -f "LOCK TABLE" 2>/dev/null; cat /tmp/weblab-lock.log 2>/dev/null || echo "no lock log"'

        # Also unlock via MySQL directly
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
try:
    conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=5)
    cur = conn.cursor()
    # Kill all sleeping/locked connections except our own
    cur.execute(\"SELECT ID FROM information_schema.PROCESSLIST WHERE USER=%s AND COMMAND != %s\", (os.environ[\"DB_USER\"], \"Query\"))
    for row in cur.fetchall():
        try: cur.execute(\"KILL %s\", (row[0],))
        except: pass
    conn.close()
    print(\"Cleaned up DB connections\")
except Exception as e:
    print(f\"Recovery note: {e}\")
"'

        wait_for_health 200 60
        log "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
