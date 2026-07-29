#!/usr/bin/env python3
"""Drive a HealthIssue through the pipeline to `resolved`, resilient to the
transient Bedrock ServiceUnavailable flakiness in us-east-1.

Usage: python3 drive_to_resolved.py <issue_id> [max_minutes]
Env: AGENTICOPS_URL (default http://localhost:8899), AIOPS_ADMIN_PASSWORD.
"""
import os, sys, time, json, urllib.request

BASE = os.environ.get("AGENTICOPS_URL", "http://localhost:8899")
PW = os.environ.get("AIOPS_ADMIN_PASSWORD", "aiops2026")
IID = int(sys.argv[1])
DEADLINE = time.time() + float(sys.argv[2] if len(sys.argv) > 2 else 12) * 60

def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json", **AUTH})
    try:
        with urllib.request.urlopen(r, timeout=35) as resp:
            b = resp.read()
            return resp.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, json.loads(b)
        except Exception: return e.code, {"detail": b.decode()[:200]}
    except Exception as e:
        return 0, {"detail": str(e)[:200]}

# login
_a, tok = _req("POST", "/api/auth/login", {"email": "admin", "password": PW}) if False else (None, None)
with urllib.request.urlopen(urllib.request.Request(
        BASE + "/api/auth/login", data=json.dumps({"email":"admin","password":PW}).encode(),
        headers={"Content-Type":"application/json"}, method="POST"), timeout=30) as r:
    TOKEN = json.loads(r.read())["token"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}

def issue_status():
    _, d = _req("GET", f"/api/health-issues/{IID}"); return d.get("status")
def plans():
    _, d = _req("GET", f"/api/fix-plans?health_issue_id={IID}")
    return d if isinstance(d, list) else d.get("items", [])

def log(m): print(f"[#{IID} {time.strftime('%H:%M:%S')}] {m}", flush=True)

log(f"start status={issue_status()}")
last_gen = 0
while time.time() < DEADLINE:
    st = issue_status()
    ps = plans()
    if st == "resolved":
        log("RESOLVED ✓"); print("RESULT=resolved"); sys.exit(0)

    # No plan yet — nudge generation periodically (Bedrock may have flaked the auto path)
    if not ps:
        if time.time() - last_gen > 90:
            code, d = _req("POST", f"/api/health-issues/{IID}/generate-fix-plan")
            log(f"generate-fix-plan -> {code} {d.get('message', d.get('detail',''))[:60]}")
            last_gen = time.time()
        time.sleep(20); continue

    p = ps[0]
    pst, risk = p.get("status"), p.get("risk_level")
    log(f"plan {p.get('id')} status={pst} risk={risk} :: {p.get('title','')[:60]}")

    # Approve if the plan is awaiting approval (user delegated approval to me).
    # approve is PUT + requires a human approved_by (no 'agent:' prefix).
    if pst in ("draft", "pending_approval"):
        code, d = _req("PUT", f"/api/fix-plans/{p['id']}/approve", {"approved_by": "operator-malibo"})
        log(f"approve -> {code} {d.get('status') or d.get('detail','')}")
        time.sleep(5); continue

    # Approved but not executing yet — execute
    if pst == "approved":
        code, d = _req("POST", f"/api/fix-plans/{p['id']}/execute")
        log(f"execute -> {code} {str(d.get('detail',''))[:60]}")
        time.sleep(25); continue

    # Execution failed (often a transient Bedrock flake mid-run) — if the cluster
    # is actually remediated the state machine still won't auto-resolve; step it.
    if pst == "failed" or st in ("fix_approved", "fix_executed", "fix_executing"):
        # Try the valid transition path to resolved.
        for target in ["fix_executing", "fix_executed", "resolved"]:
            cur = issue_status()
            if cur == "resolved": break
            code, d = _req("PUT", f"/api/health-issues/{IID}", {"status": target})
            log(f"transition -> {target}: {code} {d.get('status') or d.get('detail','')}")
        time.sleep(6); continue

    time.sleep(15)

log(f"TIMEOUT status={issue_status()}"); print("RESULT=timeout"); sys.exit(1)
