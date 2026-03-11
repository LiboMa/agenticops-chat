#!/bin/bash
# Scenario 9: Red Herring — CPU spike + real root cause is RDS parameter change
#
# Fault chain (TWO simultaneous faults, one is a distraction):
#   1. [RED HERRING] Spawn a CPU-intensive process on EC2 → CPU spikes to ~95%
#   2. [REAL CAUSE] Change RDS max_connections to 1 via parameter group
#      → After ~30s, existing connections close, new connections get "Too many connections"
#      → /health fails (can't connect to DB) → ALB unhealthy
#
# RCA challenge:
#   - Agent sees TWO signals: (a) high EC2 CPU and (b) DB connection failure
#   - The CPU spike is a RED HERRING — it's not causing the outage
#   - Real cause: RDS parameter change (max_connections=1) visible in CloudTrail
#   - Tests: Agent's ability to differentiate correlation from causation
#   - Tests: Agent checking RDS events/parameters, not just EC2 metrics
#
# Note: Changing RDS parameter group requires a reboot to take effect for static params.
#       max_connections is a dynamic parameter in MySQL/RDS → takes effect on new connections.
#       We'll use a simpler approach: revoke DB user permissions (no reboot needed).
#
# Actual implementation:
#   1. [RED HERRING] CPU stress on EC2
#   2. [REAL CAUSE] Revoke SELECT privilege from weblab user on weblab database
#      → /health's "SELECT 1" still works (basic privilege), but app queries fail
#      → Actually: REVOKE ALL on weblab.users → login/dashboard broken, /health may survive
#
# Usage: bash 09-red-herring-cpu-spike.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

case "$action" in
    inject)
        log "=== Scenario 9: Red Herring CPU Spike + Real DB Permission Revoke ==="
        log "Pre-check: health=$(check_health)"

        # === Inject RED HERRING: CPU stress ===
        log "[RED HERRING] Starting CPU stress process on EC2..."
        ssm_run_wait 'nohup python3.11 -c "
import multiprocessing, time, os, sys
def burn():
    while True:
        sum(i*i for i in range(10000))
sys.stdout.write(f\"PID={os.getpid()} starting CPU burn on {multiprocessing.cpu_count()} cores\\n\")
sys.stdout.flush()
procs = [multiprocessing.Process(target=burn) for _ in range(multiprocessing.cpu_count())]
for p in procs:
    p.start()
    sys.stdout.write(f\"  worker PID={p.pid}\\n\")
sys.stdout.flush()
for p in procs:
    p.join()
" > /tmp/weblab-cpu-burn.log 2>&1 &
echo "CPU burn started"
sleep 2
cat /tmp/weblab-cpu-burn.log'

        log "CPU stress running. Waiting 10s..."
        sleep 10

        # === Inject REAL CAUSE: Revoke DB permissions ===
        log "[REAL CAUSE] Revoking SELECT on weblab.users from weblab user..."
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
conn = pymysql.connect(
    host=os.environ[\"DB_HOST\"], port=3306,
    user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"],
    database=os.environ[\"DB_NAME\"], connect_timeout=5
)
cur = conn.cursor()
# Revoke table-level SELECT on users table
cur.execute(\"REVOKE SELECT, INSERT, UPDATE ON weblab.users FROM '\''weblab'\''@'\''%'\''\")
conn.commit()
print(\"Revoked permissions on weblab.users\")

# Verify: try SELECT from users
try:
    cur.execute(\"SELECT 1 FROM users LIMIT 1\")
    print(\"WARNING: SELECT still works (cached grant?)\")
except Exception as e:
    print(f\"Confirmed: SELECT blocked — {e}\")
conn.close()
"'

        log "Waiting 10s for connections to cycle..."
        sleep 10

        log ""
        log "=== Symptom Verification ==="

        health_code=$(check_health)
        log "  /health            -> $health_code (may still be 200 — SELECT 1 doesn't touch users)"

        login_post=$(curl -sk -o /dev/null -w '%{http_code}' \
            -X POST "${APP_URL}/login" \
            -d "username=admin&password=admin123" \
            --connect-timeout 5 --max-time 15 2>/dev/null || echo "TIMEOUT")
        log "  /login POST        -> $login_post (expected: 500 — can't SELECT from users)"

        dashboard=$(curl -sk -o /dev/null -w '%{http_code}' \
            "${APP_URL}/dashboard" \
            --connect-timeout 5 --max-time 10 2>/dev/null || echo "000")
        log "  /dashboard         -> $dashboard"

        log ""
        log "  EC2 CPU (top 5 processes):"
        ssm_run_wait 'ps aux --sort=-%cpu | head -6'

        log ""
        log "  Flask error log:"
        ssm_run_wait 'tail -5 /var/log/weblab-error.log 2>/dev/null || echo "no errors"'

        log ""
        log "=== Fault Active ==="
        log "TWO faults active:"
        log "  1. [RED HERRING] CPU at ~95% — looks alarming but NOT causing outage"
        log "  2. [REAL CAUSE]  DB permission revoked on users table — login/dashboard broken"
        log ""
        log "Agent challenge: distinguish CPU noise from DB permission change."
        log "Key evidence: application error logs show 'SELECT command denied'"
        log "CloudTrail may NOT show this (MySQL REVOKE is DB-level, not AWS API)."
        log "Agent must check application logs + DB permissions to find real cause."
        log ""
        log "Run: bash $0 recover"
        ;;

    verify)
        log "=== Verifying Scenario 9 ==="

        health_code=$(check_health)
        log "Health check: $health_code"

        log ""
        log "CPU status:"
        ssm_run_wait 'uptime && echo "---" && ps aux --sort=-%cpu | head -6'

        log ""
        log "DB permission check:"
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=5)
cur = conn.cursor()
cur.execute(\"SHOW GRANTS FOR CURRENT_USER()\")
for row in cur.fetchall():
    print(f\"  {row[0]}\")
try:
    cur.execute(\"SELECT 1 FROM users LIMIT 1\")
    print(\"  SELECT on users: OK\")
except Exception as e:
    print(f\"  SELECT on users: BLOCKED — {e}\")
conn.close()
"'

        log ""
        log "Login test:"
        login_post=$(curl -sk -o /dev/null -w '%{http_code}' \
            -X POST "${APP_URL}/login" \
            -d "username=admin&password=admin123" \
            --connect-timeout 5 --max-time 15 2>/dev/null || echo "TIMEOUT")
        log "  Login POST: $login_post"

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
        log "=== Recovering Scenario 9 ==="

        # 1. Kill CPU stress
        log "Killing CPU stress process..."
        ssm_run_wait 'pkill -f "CPU burn" 2>/dev/null; pkill -f "sum(i" 2>/dev/null; pkill -9 -f "burn" 2>/dev/null; rm -f /tmp/weblab-cpu-burn.log; echo "CPU stress killed"'

        # 2. Restore DB permissions
        log "Restoring DB permissions..."
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=5)
cur = conn.cursor()
cur.execute(\"GRANT ALL PRIVILEGES ON weblab.* TO '\''weblab'\''@'\''%'\''\")
cur.execute(\"FLUSH PRIVILEGES\")
conn.commit()
print(\"Permissions restored\")
conn.close()
"'

        log "Restarting weblab..."
        ssm_run_wait 'systemctl restart weblab'

        sleep 5
        wait_for_health 200 60

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
