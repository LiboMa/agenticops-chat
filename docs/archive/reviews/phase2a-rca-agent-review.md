# Phase 2a RCA Agent -- Implementation Review

**Reviewer**: Claude Opus 4.6 (automated)
**Date**: 2026-02-14
**Phase**: 2a -- RCA Agent MVP
**Conclusion**: **PASS** (all issues resolved in fix round)

---

## Executive Summary

The Phase 2a RCA Agent implementation is architecturally sound. The model layer, agent
structure, system prompt, migration logic, and tool design all follow established patterns
correctly. However, **4 out of 15 tests fail** due to a test infrastructure bug (shared
singleton engine across test files), and one tool (`get_rca_result`) is defined but never
wired into any agent's tool list. The implementation cannot be marked PASS until the test
failures are resolved and the missing wiring is addressed.

---

## Check Items

### 1. rca_agent.py follows detect_agent.py pattern exactly

**Result**: PASS

| Aspect | detect_agent.py | rca_agent.py | Match |
|--------|----------------|--------------|-------|
| Decorator | `@tool` | `@tool` | Yes |
| Model | `BedrockModel(model_id=..., region_name=...)` | Same | Yes |
| callback_handler | `None` | `None` | Yes |
| Agent construction | `Agent(system_prompt=..., model=..., tools=[...])` | Same | Yes |
| Error handling | `try/except` + `logger.exception` + return string | Same | Yes |
| Return | `str(result)` | `str(result)` | Yes |

The agent structure at `/Users/malibo/MyDev/AgenticOps/src/agenticops/agents/rca_agent.py`
lines 75-118 mirrors the detect_agent pattern exactly. The system prompt is well-structured
with a clear 8-step investigation protocol, confidence scoring rubric, and fix risk levels.

### 2. RCAResult.health_issue_id FK points to health_issues.id

**Result**: PASS

From `/Users/malibo/MyDev/AgenticOps/src/agenticops/models.py`, line 257:

```python
health_issue_id: Mapped[int] = mapped_column(ForeignKey("health_issues.id"))
```

The bidirectional relationship is correctly defined:
- `RCAResult.health_issue` (line 270): `relationship(back_populates="health_issue")`
- `HealthIssue.rca_results` (line 305): `relationship(back_populates="health_issue")`

The model tests at `/Users/malibo/MyDev/AgenticOps/tests/test_models.py` lines 155-219
verify both the FK constraint and the reverse relationship, and these tests **all pass**.

### 3. save_rca_result handles JSONDecodeError gracefully

**Result**: PASS

From `/Users/malibo/MyDev/AgenticOps/src/agenticops/tools/metadata_tools.py`, lines 440-458:

```python
try:
    factors_parsed = json.loads(contributing_factors) ...
except json.JSONDecodeError:
    factors_parsed = [contributing_factors]  # Wraps raw string in a list

try:
    recs_parsed = json.loads(recommendations) ...
except json.JSONDecodeError:
    recs_parsed = [recommendations]  # Same fallback

try:
    plan_parsed = json.loads(fix_plan) ...
except json.JSONDecodeError:
    plan_parsed = {}  # Falls back to empty dict

try:
    cases_parsed = json.loads(similar_cases) ...
except json.JSONDecodeError:
    cases_parsed = []  # Falls back to empty list
```

All four JSON parameters have `try/except JSONDecodeError` with sensible fallbacks.
The outer `try/except Exception` block (line 488) additionally catches any database errors
and returns a string message rather than raising.

Additional defensive measures observed:
- Confidence is clamped to `[0.0, 1.0]` via `max(0.0, min(1.0, confidence))` (line 469).
- `sop_used` converts empty string to `None` (line 474).
- Health issue existence is validated before creating the RCA record (line 462-463).

### 4. init_db() migration logic is safe

**Result**: PASS (with advisory note)

From `/Users/malibo/MyDev/AgenticOps/src/agenticops/models.py`, lines 358-375:

```python
def init_db():
    engine = get_engine()
    insp = inspect(engine)
    if insp.has_table("rca_results"):
        columns = {col["name"] for col in insp.get_columns("rca_results")}
        if "anomaly_id" in columns and "health_issue_id" not in columns:
            RCAResult.__table__.drop(engine, checkfirst=True)
    Base.metadata.create_all(engine)
```

The migration logic:
- Only fires if the `rca_results` table exists AND has the old `anomaly_id` column AND
  lacks the new `health_issue_id` column.
- Uses `checkfirst=True` on `drop()` for safety.
- `create_all()` then recreates the table with the new schema.
- Is idempotent: running it multiple times on a new schema is a no-op.

**Advisory**: This DROP-and-recreate approach destroys existing RCA data. For a production
system, an ALTER TABLE migration (via Alembic) would be preferable. Acceptable for MVP.

### 5. main_agent.py system prompt dispatches rca_agent for analyze/investigate/RCA keywords

**Result**: PASS

From `/Users/malibo/MyDev/AgenticOps/src/agenticops/agents/main_agent.py`, line 50:

```
8. When the user asks to "analyze", "investigate", "RCA", or "root cause" an issue,
   dispatch to rca_agent with the issue_id.
```

The `rca_agent` is registered in the tools list (line 77) and described in the system
prompt header (line 32): `rca_agent: Performs Root Cause Analysis on a HealthIssue.
Call with issue_id.`

### 6. Test execution: pytest tests/test_models.py tests/test_rca_tools.py -v

**Result**: FAIL (4 failures out of 15 tests)

```
tests/test_models.py    7/7  PASSED
tests/test_rca_tools.py 4/7  PASSED, 3 FAILED (+ 1 more FAILED)
```

**Failing tests and root cause analysis:**

All 4 failures stem from the **same underlying bug**: the `db_session` fixture in
`test_rca_tools.py` does NOT reset the module-level `_engine` singleton in
`models.py`. When `test_models.py` runs first, it creates the engine pointing to
its own `tmp_path`. When `test_rca_tools.py` runs next, it updates
`settings.database_url` but `get_engine()` returns the stale singleton. As a result:

- The `save_rca_result` tool (which internally calls `get_session()`) operates on
  the **same database** as test_models.py.
- The fixture's `db_session` also uses the same stale engine.
- Data from test_models.py bleeds into test_rca_tools.py assertions.

| Test | Expected | Actual | Cause |
|------|----------|--------|-------|
| `test_save_basic_rca` | `rca.health_issue_id == health_issue.id` | `2 != 4` | health_issue.id is 4 (not 1) because models.py tests already inserted rows |
| `test_save_full_rca` | `rca.fix_risk_level == "low"` | `"medium"` | Query returns the RCA from the previous test, not the one just created |
| `test_save_rca_invalid_json_factors` | `factors == ["not valid json"]` | `["No memory limits set", ...]` | Same cross-contamination: query returns the wrong RCA row |
| `test_confidence_clamped` | `rca.confidence == 1.0` | `0.85` | Same: `query(RCAResult).first()` picks up an older row |

**Fix required**: The `db_session` fixture must reset `agenticops.models._engine = None`
before creating a new engine, so each test file gets its own isolated database. Example:

```python
@pytest.fixture
def db_session(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    # Reset singleton engine for test isolation
    models_mod._engine = None

    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    engine = models_mod.get_engine()
    models_mod.Base.metadata.create_all(engine)

    session = models_mod.get_session()
    yield session
    session.close()

    # Clean up for the next test file
    models_mod._engine = None
```

Ideally this fixture should live in a shared `tests/conftest.py`.

### 7. py_compile on all modified files

**Result**: PASS (all 7 files compile cleanly)

| File | Status |
|------|--------|
| `src/agenticops/models.py` | OK |
| `src/agenticops/tools/metadata_tools.py` | OK |
| `src/agenticops/agents/rca_agent.py` | OK |
| `src/agenticops/agents/main_agent.py` | OK |
| `src/agenticops/agents/__init__.py` | OK |
| `tests/test_models.py` | OK |
| `tests/test_rca_tools.py` | OK |

---

## Additional Findings

### BUG-1: get_rca_result tool not wired into any agent (Severity: Medium)

`get_rca_result` is defined in
`/Users/malibo/MyDev/AgenticOps/src/agenticops/tools/metadata_tools.py` (line 496)
and is tested in `tests/test_rca_tools.py`, but it is **not imported or registered** in
either `rca_agent.py` or `main_agent.py`. This means:

- The main_agent cannot show the user the results of an RCA after it completes.
- The rca_agent cannot review previous RCA results for the same issue.

**Recommended fix**: Add `get_rca_result` to `main_agent.py`'s tool list and update
the system prompt to mention it.

### BUG-2: Test fixture session isolation (Severity: High)

As detailed in Check Item 6, the `db_session` fixture in both test files fails to
reset the `_engine` singleton. This is the root cause of all 4 test failures. The
same bug also exists in `tests/test_models.py` but is masked because that file runs
first.

### ADVISORY-1: datetime.utcnow() deprecation warnings (Severity: Low)

The test run produces 26 deprecation warnings:

```
DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled
for removal in a future version. Use timezone-aware objects to represent
datetimes in UTC: datetime.datetime.now(datetime.UTC)
```

This affects multiple model default values in `models.py`. Not a blocker, but
should be addressed to maintain Python 3.12+ compatibility.

### ADVISORY-2: save_rca_result truncates root_cause in return message (Severity: Low)

Line 485 of `metadata_tools.py`:

```python
f"Root cause: {root_cause[:100]}..."
```

The trailing `...` is always appended, even if `root_cause` is shorter than 100
characters. Minor cosmetic issue.

---

## Code Quality Assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Architecture | Good | Follows agents-as-tools pattern consistently |
| System Prompt | Good | Clear protocol, scoring rubric, risk levels |
| Error Handling | Good | All JSON params have JSONDecodeError fallbacks |
| Model Design | Good | Clean FK, bidirectional relationship, new fields |
| Migration | Acceptable | DROP+recreate is fine for MVP, not for production |
| Test Coverage | Good | 15 tests covering happy path, edge cases, relationships |
| Test Infrastructure | Poor | Singleton engine leak causes 4 failures |
| Documentation | Good | Design doc matches implementation |

---

## Metrics Summary

| Metric | Value |
|--------|-------|
| Total tests | 15 |
| Passed | 11 |
| Failed | 4 |
| Skipped | 0 |
| Pass rate | 73.3% |
| py_compile pass rate | 100% (7/7) |
| Check items passed | 5/7 |

---

## Recommended Actions (Priority Order)

1. **P0 -- Fix test fixture isolation**: Reset `_engine = None` in `db_session` fixture.
   Move to `tests/conftest.py` for single source of truth. This will resolve all 4 test
   failures.

2. **P1 -- Wire get_rca_result into main_agent**: Import and add to the tools list so
   users can query RCA results through the chat interface.

3. **P2 -- Replace datetime.utcnow()**: Use `datetime.now(datetime.UTC)` across all
   model defaults to eliminate deprecation warnings.

4. **P3 -- Fix truncation ellipsis**: Only append `...` when `len(root_cause) > 100`.

---

## Conclusion

**PASS** -- All issues from the initial review have been resolved:
- P0 (test fixture isolation): Fixed by resetting `_engine = None` in both test files' fixtures.
- P1 (get_rca_result wiring): Added to main_agent.py imports, tools list, and system prompt.
- All 15 tests now pass. All 7 files pass py_compile.
- Implementation is ready for commit.
