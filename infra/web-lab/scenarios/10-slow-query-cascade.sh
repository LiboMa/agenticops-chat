#!/bin/bash
# Scenario 10: Slow Query Cascade — long-running query blocks connection pool → timeout cascade
#
# Fault chain:
#   1. Create a large temporary table (100K rows) in MySQL
#   2. Run a slow cross-join query that takes ~30-60s per execution
#   3. Spawn 5 concurrent slow queries → exhaust RDS max_connections (db.t3.micro ≈ 66)
#   4. Flask app's new connections are queued/rejected → /health SELECT 1 times out
#   5. ALB → unhealthy → ALARM
#
# RCA challenge:
#   - Looks like "RDS connection exhaustion" (similar to Scenario 5)
#   - BUT root cause is different: no table lock, no flood — it's slow queries from a batch job
#   - Agent must check MySQL PROCESSLIST to find the slow queries
#   - Agent must distinguish from: (a) table lock, (b) connection flood, (c) SG block
#   - CloudTrail has NO relevant events (DB-level issue)
#   - Tests: depth of DB investigation, ability to identify query-level root cause
#
# Detection: CW rds-connections-high + unhealthy-hosts → ALARM
# Recovery: Kill the slow query sessions
#
# Usage: bash 10-slow-query-cascade.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

action="${1:-inject}"

case "$action" in
    inject)
        log "=== Scenario 10: Slow Query Cascade ==="
        log "Pre-check: health=$(check_health)"

        # Step 1: Create large temp table and spawn slow queries
        log "Creating temp data table + spawning slow queries..."
        SLOW_CMD='source /opt/weblab/.env && python3.11 -c "
import pymysql, os, sys, threading, time

DB = dict(
    host=os.environ[\"DB_HOST\"], port=3306,
    user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"],
    database=os.environ[\"DB_NAME\"], connect_timeout=10, read_timeout=300,
)

# Create temp table with 100K rows
sys.stdout.write(\"Creating temp data table...\\n\")
sys.stdout.flush()
conn = pymysql.connect(**DB)
cur = conn.cursor()
cur.execute(\"DROP TABLE IF EXISTS _slow_data\")
cur.execute(\"CREATE TABLE _slow_data (id INT AUTO_INCREMENT PRIMARY KEY, val VARCHAR(255), num FLOAT)\")
# Batch insert 100K rows
batch = []
for i in range(100000):
    batch.append(f\"(NULL, REPEAT(CHAR(65 + (i % 26)), 200), RAND())\")
    if len(batch) >= 5000:
        cur.execute(\"INSERT INTO _slow_data VALUES \" + \",\".join(batch))
        conn.commit()
        batch = []
if batch:
    cur.execute(\"INSERT INTO _slow_data VALUES \" + \",\".join(batch))
    conn.commit()
sys.stdout.write(\"100K rows created\\n\")
sys.stdout.flush()

# Spawn slow queries in threads
def slow_query(thread_id):
    try:
        c = pymysql.connect(**DB)
        cur = c.cursor()
        sys.stdout.write(f\"Thread {thread_id}: starting slow cross-join query\\n\")
        sys.stdout.flush()
        # This cross-join produces 100K * 100K = 10B rows (will run until timeout)
        cur.execute(\"SELECT COUNT(*) FROM _slow_data a, _slow_data b WHERE a.num > b.num LIMIT 1\")
        result = cur.fetchone()
        sys.stdout.write(f\"Thread {thread_id}: query returned {result}\\n\")
    except Exception as e:
        sys.stdout.write(f\"Thread {thread_id}: error — {e}\\n\")
    sys.stdout.flush()

threads = []
for i in range(10):
    t = threading.Thread(target=slow_query, args=(i,))
    t.daemon = True
    t.start()
    threads.append(t)
    time.sleep(1)  # stagger to show gradual exhaustion
    sys.stdout.write(f\"Spawned slow query thread {i}\\n\")
    sys.stdout.flush()

# Also open idle connections to fill pool faster
idle_conns = []
sys.stdout.write(\"Opening 40 idle connections...\\n\")
sys.stdout.flush()
for i in range(40):
    try:
        c = pymysql.connect(**DB)
        idle_conns.append(c)
    except Exception as e:
        sys.stdout.write(f\"Idle conn {i}: {e}\\n\")
        sys.stdout.flush()
        break
sys.stdout.write(f\"Opened {len(idle_conns)} idle connections\\n\")
sys.stdout.flush()

# Keep running for 10 minutes
sys.stdout.write(\"Holding connections for 600s...\\n\")
sys.stdout.flush()
time.sleep(600)

# Cleanup
for c in idle_conns:
    try: c.close()
    except: pass
sys.stdout.write(\"Done\\n\")
" > /tmp/weblab-slow-query.log 2>&1 &
echo "PID=$!"'
        ssm_run_wait "$SLOW_CMD" 120

        log "Slow queries spawned. Waiting 20s for connection exhaustion..."
        sleep 20

        log ""
        log "=== Symptom Verification ==="

        health_code=$(check_health)
        log "  /health            -> $health_code (expected: 503 — DB connections exhausted)"

        log ""
        log "  MySQL PROCESSLIST:"
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
try:
    conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=3)
    cur = conn.cursor()
    cur.execute(\"SHOW FULL PROCESSLIST\")
    total = 0
    query_count = 0
    sleep_count = 0
    for row in cur.fetchall():
        total += 1
        if row[4] == \"Query\":
            query_count += 1
            print(f\"  QUERY: ID={row[0]} Time={row[5]}s Info={str(row[7])[:60]}\")
        elif row[4] == \"Sleep\":
            sleep_count += 1
    print(f\"\\nTotal: {total} connections ({query_count} queries, {sleep_count} sleeping)\")
    conn.close()
except Exception as e:
    print(f\"Cannot connect to DB: {e}\")
" 2>/dev/null'

        log ""
        log "  CW Alarms:"
        aws cloudwatch describe-alarms --alarm-name-prefix "weblab-" \
            --region "$REGION" \
            --query 'MetricAlarms[*].[AlarmName,StateValue]' --output text | \
            while read name state; do
                log "    $name -> $state"
            done

        log ""
        log "=== Fault Active ==="
        log "10 slow cross-join queries + 40 idle connections exhausting RDS connection pool."
        log "No table lock, no flood, no SG change — pure slow query resource exhaustion."
        log "CloudTrail: NO relevant events. Agent must investigate PROCESSLIST."
        log ""
        log "Run: bash $0 recover"
        ;;

    verify)
        log "=== Verifying Scenario 10 ==="

        health_code=$(check_health)
        log "Health check: $health_code"

        log ""
        log "MySQL connections:"
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
try:
    conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=3)
    cur = conn.cursor()
    cur.execute(\"SHOW STATUS LIKE '\''Threads_connected'\''\")
    print(f\"Threads_connected: {cur.fetchone()[1]}\")
    cur.execute(\"SHOW VARIABLES LIKE '\''max_connections'\''\")
    print(f\"max_connections: {cur.fetchone()[1]}\")
    cur.execute(\"SHOW FULL PROCESSLIST\")
    for row in cur.fetchall():
        if row[4] == \"Query\" and int(row[5] or 0) > 5:
            print(f\"  SLOW: ID={row[0]} Time={row[5]}s Command={row[4]} Info={str(row[7])[:80]}\")
    conn.close()
except Exception as e:
    print(f\"Cannot connect: {e}\")
" 2>/dev/null'

        log ""
        log "Slow query log:"
        ssm_run_wait 'tail -20 /tmp/weblab-slow-query.log 2>/dev/null || echo "no log"'

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
        log "=== Recovering Scenario 10 ==="

        # Kill the Python process holding connections
        log "Killing slow query process..."
        ssm_run_wait 'pkill -f "slow_data" 2>/dev/null; pkill -f "_slow_data" 2>/dev/null; sleep 1; pkill -9 -f "slow" 2>/dev/null; rm -f /tmp/weblab-slow-query.log; echo "done"'

        # Kill stuck MySQL sessions
        log "Killing MySQL slow query sessions..."
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=10)
cur = conn.cursor()
cur.execute(\"SHOW FULL PROCESSLIST\")
killed = 0
for row in cur.fetchall():
    cid, user, cmd, time_val, info = row[0], row[1], row[4], int(row[5] or 0), str(row[7] or \"\")
    if user == os.environ[\"DB_USER\"] and (time_val > 5 or cmd == \"Sleep\" or \"_slow_data\" in info):
        try:
            cur.execute(\"KILL %s\", (cid,))
            killed += 1
        except: pass
print(f\"Killed {killed} sessions\")
conn.close()
" 2>/dev/null'

        # Drop temp table
        log "Dropping temp table..."
        ssm_run_wait 'source /opt/weblab/.env && python3.11 -c "
import pymysql, os
conn = pymysql.connect(host=os.environ[\"DB_HOST\"], port=3306, user=os.environ[\"DB_USER\"], password=os.environ[\"DB_PASS\"], database=os.environ[\"DB_NAME\"], connect_timeout=10)
cur = conn.cursor()
cur.execute(\"DROP TABLE IF EXISTS _slow_data\")
conn.commit()
print(\"Temp table dropped\")
conn.close()
" 2>/dev/null'

        log "Restarting weblab..."
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
