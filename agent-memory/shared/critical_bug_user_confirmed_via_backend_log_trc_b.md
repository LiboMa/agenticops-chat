---
agent: shared
confidence: 5
created_at: '2026-06-12'
created_by: user
last_confirmed: '2026-06-15'
last_used: '2026-07-09'
resource_pattern: EC2/*
source: chat
status: active
type: feedback
---

CRITICAL BUG (user-confirmed via backend log TRC-bc600aa9): run_on_host(ssm) execution path did NOT inherit the active account's AssumeRole context — it silently fell back to the boto3 DEFAULT credential chain (env vars / local ~/.aws profile / instance metadata). Log signature: 'run_on_host(ssm) uses default credentials (no active account context)'. CONSEQUENCE: (1) functional — failed if no local default creds exist; (2) SECURITY — silently used local static keys (e.g. observed IAM user sa-malibo AKIA... from macOS), bypassing the designed AssumeRole isolation and violating no-local-profile requirement. CloudTrail SendCommand events attributed to a local IAM user may actually have BEEN the agent's run_on_host call, NOT a separate human.

ROOT CAUSE (verified): the implicit `_active_account_var` ContextVar (set by the assume_role tool) NEVER survived a Strands tool boundary — Strands runs sync @tool functions under `asyncio.to_thread` + `contextvars.copy_context()`, so the write was discarded on return and every later tool read None → silent ambient fallback. Same defect silently broke `_get_session` consumers (network/graph/eks/cloudwatch describe tools) which were fail-closed.

RESOLVED 2026-06-15: ContextVar machinery DELETED (`_active_account_var`, `_set_active_account`, `_get_active_account`, `get_account_subprocess_env`). Replaced with account-addressed resolution in `credentials/resolver.py`: every business tool resolves the account EXPLICITLY (explicit `account` param → inventory lookup by host/cluster id via `find_instance_account`/`find_cluster_account` → single-account `resolve_default_account`) and fails closed (`AccountResolutionError`, never ambient; the only legitimate local-chain path is a registered `environment`-source account, identity-validated). `run_on_host(method="auto")` now climbs an SSM→SSH ladder (classifies InvalidInstanceId/TargetNotConnected/AccessDenied, falls back to SSH using inventory IP) with a visible attempt trail. The log signature 'uses default credentials (no active account context)' no longer exists in the codebase (grep-verified). Tests: tests/test_account_resolver.py + updated cred/execution suites green.
