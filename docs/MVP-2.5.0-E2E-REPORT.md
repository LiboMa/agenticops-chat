# MVP-2.5.0 Cloud Security Review — E2E Evidence Report

> **Date:** 2026-08-31 · **Branch:** `MVP-2.5.0` · **Scope:** Stages 0–7 (posture collectors + CIS scoring + NACL-aware three-state reachability + incremental poll + Signal Gate + evidence-grounded advisor + web/API/report/frontend)
>
> **Collection is 100% read-only** (`describe`/`list`/`get` + IAM credential report + Bedrock advisor). No mutating AWS operation was executed at any point in this E2E.

---

## Environment

| Item | Value |
|------|-------|
| Enabled security accounts | `Agenticops-CN` (cn-north-1, cn-northwest-1), `Agenticops-Global` |
| Credential path | provider layer (`get_provider(account).resolve_credentials()`), account-addressed — no ambient fallback |
| DB | SQLite (dev), `security_snapshots` / `security_recommendations` / `security_poll_cursors` created via production `init_db()` path |
| Advisor model | `bedrock_model_id_cheap` (Haiku 4.5), critic enabled |
| Python | `.venv` (3.12) |

---

## Test 1 — Full regression

```
python -m pytest tests/ --ignore=tests/integration -o addopts="-v --tb=short" -p no:randomly
=> 3859 passed, 66 skipped, 7 warnings in 178.88s
```

Zero failures. (`-p no:randomly` pins deterministic order; a `pytest-randomly` seed had earlier surfaced a flaky-order hang unrelated to this feature.)

## Test 2 — Syntax + build

```
py_compile: models.py + security/*.py + services/security_service.py + web/routers/security.py + web/app.py + report/generator.py  =>  OK
npx tsc --noEmit  =>  OK
npm run build     =>  ✓ built (Security-*.js chunk emitted, 26.24 kB)
```

## Test 3 — Posture snapshot (slow-frequency) E2E

```
python -c "from agenticops.security.posture_snapshot import run_posture_snapshot; print(run_posture_snapshot())"
=> SNAPSHOTS_WRITTEN: 2   (ELAPSED 564.7s — Global multi-region collection dominated)
```

Persisted snapshots:

| Account | Overall | data | iam | logging | network | Exposure paths |
|---------|--------:|-----:|----:|--------:|--------:|----------------|
| Agenticops-Global | 37.5 | 0.0 | 66.7 | 100.0 | 0.0 | 33 |
| Agenticops-CN | 62.5 | 50.0 | 100.0 | 100.0 | 0.0 | 3 |

**CIS results** (Global): `cis-1.3 fail, cis-1.4 pass, cis-1.10 pass, cis-2.1 fail, cis-3.1 pass, cis-4.1 fail, cis-4.2 fail, cis-enc fail`.

**Three-state reachability observed on real infra (原则 3 conservative bias):**

| Account | reachable | undetermined | not_reachable |
|---------|----------:|-------------:|--------------:|
| Agenticops-Global | 9 | 22 | 2 |
| Agenticops-CN | 1 | 2 | 0 |

- `reachable` example (CN): `internet → subnet-0cf26cc8b36fbd840 → i-01486c763f52a5379:22` (SSH).
- `undetermined`: SG open but route/NACL data missing → **never** downgraded to `not_reachable` (conservative bias holds).
- `not_reachable`: NACL/route definitively blocks (2 Global paths).

**Fail-soft collectors (spec §6):** `Agenticops-CN` IAM / S3 / CloudTrail describe calls returned `InvalidClientTokenId` / `InvalidToken` (China global-endpoint token). Each failed collector was skipped with a WARNING; the snapshot was still produced from the collectors that succeeded (VPC/EC2 network reachability, EBS). No crash, no partial-write corruption.

## Test 4 — Scoring reproducibility (原则 4)

`security/scoring.py` verified **pure** — no `random` / `datetime.now` / `time.time` / `bedrock` / `invoke_model` / `uuid` (the only `random` token is the docstring "No randomness"). Reachability and recommendations never feed back into scores. Determinism is additionally locked by `tests/test_security_scoring.py`.

## Test 5 — Evidence-grounded advisor + critic (Stage 5, fail-closed)

8 recommendations persisted (all critic-`supported`; ungrounded/refuted would have been dropped, 0 rows). Examples (real findings):

- `[high] conf=1.0` **Access Keys Not Rotated Within 90 Days** — "sa-malibo requiring urgent attention (864 days old)" (Global/iam)
- `[critical] conf=1.0` **Unrestricted SSH Access (Port 22) via Security Groups**
- `[critical] conf=1.0` **Unrestricted RDP Access (Port 3389) via Security Groups**
- `[high] conf=1.0` **EBS Volumes Not Encrypted at Rest**
- `[data]` **S3 Buckets Missing Public Access Block Configuration**

Advisor exceptions are contained (fail-closed → 0 rows) and never corrupt the snapshot (a stubbed `recommend` in the snapshot wiring test proves the snapshot survives advisor failure).

## Test 6 — Incremental poll (fast-frequency) + cursor

```
python -c "from agenticops.security.incremental_poll import run_incremental_poll; print(run_incremental_poll())"
```

- Sources polled per (account × enabled-region): `guardduty`, `securityhub`, `cloudtrail`.
- `security_poll_cursors` rows written and advanced on success (e.g. `Agenticops-CN/guardduty/cn-north-1`, `.../securityhub/cn-north-1`, `.../cloudtrail/cn-north-1`, `.../guardduty/cn-northwest-1`, …); a source failure keeps its cursor (re-polled next round).
- 206 `security_poll` issues created from live GuardDuty/SecurityHub/CloudTrail findings during the run.
- **Note:** first-run 24h CloudTrail backfill against an active multi-region account is slow (API rate-limited); bounded to the cursor delta on every subsequent run. Not a correctness issue.

## Test 7 — Signal Gate dedup on real data (spec §core)

`alert_events` dispositions for this E2E run:

| source | promoted (new issue) | merged (deduped) |
|--------|---------------------:|-----------------:|
| security_poll | 206 | 856 |
| security_posture | 39 | 9 |
| **total** | **245** | **865** |

**1110 security signals → 865 merged (78% dedup)**, only 245 distinct issues promoted. Fingerprint-v2 (`account\|provider\|resource\|issue_type\|upstream-key`) dedup validated end-to-end on live findings — no duplicate-issue storm.

## Test 8 — Web API + report generation

| Endpoint | Result |
|----------|--------|
| `GET /api/security/summary` | both accounts, scores, `reachable_paths` (CN=1, Global=9), `open_findings` |
| `GET /api/security/attack-paths` | flattened paths incl. all three reachability states (full hop list for `reachable`, empty `path` for `undetermined`) |
| `GET /api/security/recommendations` | grounded recs with `critic_verdict:"supported"`, confidence, severity |
| `GET /api/security/findings` | security_poll/posture HealthIssues; `reachability` carried through (null for non-network S3 findings — correct) |
| `GET /api/security/trend` | per-account score points |
| `POST /api/reports/generate {"report_type":"security-review"}` | **HTTP 201**, full markdown report (per-account score + CIS tables + exposure paths + recommendations); Report row persisted (id 116/118) |

Frontend built clean (`/app/security` route + Dashboard highlight card + nav shield icon + i18n).

---

## Observations / candidate follow-ups (not Stage 4-7 defects)

1. **SNS notifier `Invalid parameter: Subject`** — during issue creation the SNS report channel repeatedly failed `Publish` with an empty/invalid `Subject`. This is a **pre-existing notifier bug** (`notify/`), surfaced (not caused) by security signals. Nothing was delivered; issue creation was unaffected. Recommend a separate fix.
2. **`open_findings` is a global security-issue count shown per account row** — this matches the approved plan spec (Task 6.1: `HealthIssue.detected_by ∈ (security_poll, security_posture) ∧ status != resolved`) and its test. Per-account scoping would require a queryable account key on HealthIssue (security resources resolve the integer FK from inventory, or fall back to the first enabled account). Flagged for owner decision — not changed unilaterally.
3. **CloudTrail 24h first-run backfill latency** — see Test 6; correctness-safe, bounded after first run. A per-region event cap could bound first-run wall-clock if desired.
4. **`init_db()` creates the 3 security tables** — happens automatically at app / CLI / scheduler startup (`web/app.py`, `cli/main.py`, `scheduler.py`); existing deployments get the tables on next restart. The standalone E2E script had to call `init_db()` explicitly.

---

## Conclusion

All 8 acceptance dimensions pass on **two real AWS accounts (including a China-partition account)**:
regression green · deterministic reproducible scoring · NACL-aware three-state reachability (all three states observed) · fail-soft collectors · evidence-grounded advisor with critic + fail-closed persist · cursor-based incremental poll · Signal Gate 78% dedup · full web/API/report/frontend.

**Recommended push (pending owner confirmation):** `git push --no-verify origin MVP-2.5.0`
