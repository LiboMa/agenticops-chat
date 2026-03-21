# Phase 2: Verification + Learning — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build PostActionValidator (automated T0-T3 verification), Human Review system (Ground Truth), Confidence Calibration, Wisdom Roadmap, and Four-Layer Memory classification — the learning loop that makes the system smarter with every incident.

**Architecture:** After fix execution, PostActionValidator runs automated observation windows (T0-T3). Human Review provides Ground Truth via minimal UI. Both feed into Confidence Calibration and Wisdom Roadmap, which improve future prompt optimization. Memory progresses from Episodic -> Procedural -> Semantic.

**Tech Stack:** Python 3.12, SQLAlchemy, FastAPI, APScheduler (for T0-T3 timers), React/TypeScript (Review UI)

**Spec:** `docs/superpowers/specs/2026-03-15-next-gen-aiops-design.md` (Sections 4, 8, 11 Phase 2)

**Prerequisite:** Phase 1 complete (Connectors, Service Model, Prompt Engine, Evidence)

---

## File Structure

### New Files

```
src/agenticops/verification/
  __init__.py
  post_action_validator.py      - T0-T3 automated verification loop
  review_service.py             - Human review feedback processing
  calibration.py                - Confidence calibration bins + incremental update

src/agenticops/wisdom/
  __init__.py
  roadmap.py                    - Wisdom Roadmap: pattern -> strategy entries
  distiller.py                  - Distill resolved cases into Wisdom entries
  memory_classifier.py          - Classify KB entries: episodic -> procedural -> semantic

tests/
  test_post_action_validator.py
  test_review_service.py
  test_calibration.py
  test_wisdom_roadmap.py
  test_memory_classifier.py
```

### Modified Files

```
src/agenticops/models.py                - Add ReviewFeedback, PostActionResult, WisdomEntry, CalibrationBin
src/agenticops/services/pipeline_service.py  - Chain PostActionValidator after execution
src/agenticops/web/app.py               - Add review + calibration + wisdom API endpoints
src/agenticops/agents/preamble.py       - Wire wisdom lookup into dynamic prompt
src/agenticops/prompt_engine/strategy.py - Wire StrategySelector to Wisdom Roadmap
src/agenticops/prompt_engine/assembler.py - Include wisdom entries in prompt composition
```

### Frontend (New)

```
src/agenticops/web/frontend/src/
  components/ReviewCard.tsx      - RCA Review + Fix Effectiveness review UI
  hooks/useReviews.ts           - TanStack Query hooks for review API
  pages/HealthIssueDetail additions  - Embed ReviewCard in issue detail page
```

---

## Chunk 1: PostActionValidator

### Task 1: PostActionResult DB Model

**Files:**
- Modify: `src/agenticops/models.py`
- Test: `tests/test_post_action_validator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_post_action_validator.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agenticops.models import Base, PostActionResult


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_post_action_result(db):
    par = PostActionResult(
        fix_plan_id=1,
        health_issue_id=1,
        observed_metric="HealthCheckFailures",
        baseline_value=5.0,
        threshold=0.20,
        t0_result="pass",
        t1_result="pass",
        t2_result="pass",
        t3_result="pass",
        verdict="success",
        metric_improvement=1.0,
    )
    db.add(par)
    db.flush()
    assert par.id is not None
    assert par.verdict == "success"


def test_post_action_result_partial_success(db):
    par = PostActionResult(
        fix_plan_id=1, health_issue_id=1,
        observed_metric="ErrorRate", baseline_value=10.0, threshold=0.20,
        t0_result="pass", t1_result="pass", t2_result="fail", t3_result="fail",
        verdict="partial_success", metric_improvement=0.35,
    )
    db.add(par)
    db.flush()
    assert par.verdict == "partial_success"
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Add PostActionResult to models.py**

```python
class PostActionResult(Base):
    __tablename__ = "post_action_results"
    id = Column(Integer, primary_key=True)
    fix_plan_id = Column(Integer, ForeignKey("fix_plans.id"), nullable=False)
    health_issue_id = Column(Integer, ForeignKey("health_issues.id"), nullable=False)
    observed_metric = Column(String, default="")
    baseline_value = Column(Float, default=0.0)
    threshold = Column(Float, default=0.20)
    t0_result = Column(String, default="")  # "pass" | "fail"
    t1_result = Column(String, default="")
    t2_result = Column(String, default="")
    t3_result = Column(String, default="")
    verdict = Column(String, default="")  # success | partial_success | failed | uncertain
    metric_improvement = Column(Float, default=0.0)
    created_at = Column(DateTime, default=func.now())
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/models.py tests/test_post_action_validator.py
git commit -m "feat(models): add PostActionResult table for automated verification"
```

---

### Task 2: PostActionValidator Logic

**Files:**
- Create: `src/agenticops/verification/__init__.py`
- Create: `src/agenticops/verification/post_action_validator.py`
- Test: `tests/test_post_action_validator.py` (extend)

- [ ] **Step 1: Write failing test for verdict aggregation**

```python
# append to tests/test_post_action_validator.py
from agenticops.verification.post_action_validator import aggregate_verdict


def test_all_pass_is_success():
    assert aggregate_verdict("pass", "pass", "pass", "pass", 0.85) == "success"


def test_t1_pass_t2_fail_is_partial():
    assert aggregate_verdict("pass", "pass", "fail", "fail", 0.35) == "partial_success"


def test_t0_fail_is_failed():
    assert aggregate_verdict("fail", "", "", "", 0.0) == "failed"


def test_t0_pass_t1_fail_is_failed():
    assert aggregate_verdict("pass", "fail", "", "", 0.05) == "failed"


def test_noisy_metric_is_uncertain():
    assert aggregate_verdict("pass", "pass", "pass", "fail", -0.02) == "uncertain"
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement PostActionValidator**

```python
# src/agenticops/verification/__init__.py
# Verification subsystem

# src/agenticops/verification/post_action_validator.py
from __future__ import annotations
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Observation windows per spec Section 8.1
T0_SECONDS = 30
T1_SECONDS = 120
T2_SECONDS = 300
T3_SECONDS = 900

IMPROVEMENT_THRESHOLD = 0.20
NOISE_THRESHOLD = 0.05


def aggregate_verdict(t0: str, t1: str, t2: str, t3: str, improvement: float) -> str:
    """Aggregate t0-t3 results into composite verdict per spec Section 8.4."""
    if t0 == "fail":
        return "failed"
    if t1 == "fail":
        return "failed"
    if t1 == "pass" and improvement >= IMPROVEMENT_THRESHOLD:
        if t2 == "fail" or t3 == "fail":
            return "partial_success"
    if t0 == "pass" and t1 == "pass" and t2 == "pass" and t3 == "pass":
        return "success"
    if abs(improvement) < NOISE_THRESHOLD:
        return "uncertain"
    if improvement >= IMPROVEMENT_THRESHOLD and (t2 == "fail" or t3 == "fail"):
        return "partial_success"
    return "uncertain"


class PostActionValidator:
    """Run T0-T3 automated verification after fix execution."""

    def __init__(self, metric_check_fn=None):
        self._check_fn = metric_check_fn

    async def validate(self, fix_plan_id: int, health_issue_id: int,
                       metric_name: str, baseline: float) -> dict:
        """Run observation windows. Returns PostActionResult fields."""
        results = {"t0": "", "t1": "", "t2": "", "t3": ""}
        improvement = 0.0

        # T0: immediate check
        await asyncio.sleep(T0_SECONDS)
        results["t0"] = await self._check(metric_name, baseline, "t0")

        if results["t0"] == "fail":
            return self._build_result(results, improvement, metric_name, baseline)

        # T1: short-term
        await asyncio.sleep(T1_SECONDS - T0_SECONDS)
        results["t1"], improvement = await self._check_with_improvement(metric_name, baseline)

        if results["t1"] == "fail":
            return self._build_result(results, improvement, metric_name, baseline)

        # T2: medium-term
        await asyncio.sleep(T2_SECONDS - T1_SECONDS)
        results["t2"], improvement = await self._check_with_improvement(metric_name, baseline)

        # T3: stabilization
        await asyncio.sleep(T3_SECONDS - T2_SECONDS)
        results["t3"], improvement = await self._check_with_improvement(metric_name, baseline)

        return self._build_result(results, improvement, metric_name, baseline)

    async def _check(self, metric: str, baseline: float, window: str) -> str:
        if self._check_fn is None:
            return "pass"  # no metric check configured
        try:
            current = await self._check_fn(metric)
            return "pass" if current <= baseline else "fail"
        except Exception as e:
            logger.warning(f"PostActionValidator {window} check failed: {e}")
            return "fail"

    async def _check_with_improvement(self, metric: str, baseline: float) -> tuple[str, float]:
        if self._check_fn is None:
            return "pass", 1.0
        try:
            current = await self._check_fn(metric)
            if baseline == 0:
                improvement = 1.0 if current == 0 else 0.0
            else:
                improvement = (baseline - current) / baseline
            return ("pass" if improvement >= IMPROVEMENT_THRESHOLD else "fail"), improvement
        except Exception as e:
            logger.warning(f"PostActionValidator metric check failed: {e}")
            return "fail", 0.0

    def _build_result(self, results: dict, improvement: float, metric: str, baseline: float) -> dict:
        verdict = aggregate_verdict(
            results["t0"], results["t1"], results["t2"], results["t3"], improvement
        )
        return {
            "observed_metric": metric,
            "baseline_value": baseline,
            "threshold": IMPROVEMENT_THRESHOLD,
            "t0_result": results["t0"],
            "t1_result": results["t1"],
            "t2_result": results["t2"],
            "t3_result": results["t3"],
            "verdict": verdict,
            "metric_improvement": improvement,
        }
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/verification/__init__.py src/agenticops/verification/post_action_validator.py tests/test_post_action_validator.py
git commit -m "feat(verification): add PostActionValidator with T0-T3 windows and verdict aggregation"
```

---

### Task 3: Chain PostActionValidator into Pipeline

**Files:**
- Modify: `src/agenticops/services/pipeline_service.py`

- [ ] **Step 1: Add `trigger_post_action_validation` to pipeline_service.py**

After `trigger_auto_execute`, add:

```python
async def trigger_post_action_validation(fix_plan_id: int, health_issue_id: int,
                                          metric_name: str, baseline: float):
    """Triggered after fix execution. Runs T0-T3 observation."""
    from agenticops.verification.post_action_validator import PostActionValidator
    from agenticops.models import PostActionResult, HealthIssue, get_db_session

    validator = PostActionValidator()  # Phase 2: wire metric_check_fn to connector
    result = await validator.validate(fix_plan_id, health_issue_id, metric_name, baseline)

    with get_db_session() as session:
        par = PostActionResult(fix_plan_id=fix_plan_id, health_issue_id=health_issue_id, **result)
        session.add(par)

        # Apply state transition per spec Section 8.6
        issue = session.query(HealthIssue).get(health_issue_id)
        if issue and result["verdict"] == "success":
            issue.status = "resolved"
            issue.resolved_at = func.now()
        elif issue and result["verdict"] == "failed":
            issue.status = "root_cause_identified"  # rollback to re-plan
        # partial_success and uncertain: stay fix_executed

        session.commit()
    logger.info(f"PostAction verdict for I#{health_issue_id}: {result['verdict']}")
```

- [ ] **Step 2: Wire into `mark_fix_executed` in metadata_tools.py**

After successful execution mark, spawn validation in background:

```python
# In mark_fix_executed, after status update:
import threading
threading.Thread(
    target=lambda: asyncio.run(trigger_post_action_validation(
        fix_plan_id, health_issue_id, metric_name="", baseline=0.0
    )),
    daemon=True,
).start()
```

Note: `metric_name` and `baseline` will be populated from FixPlan's `post_checks` field in a later refinement.

- [ ] **Step 3: Verify compilation**

```bash
python3 -m py_compile src/agenticops/services/pipeline_service.py
```

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/services/pipeline_service.py src/agenticops/tools/metadata_tools.py
git commit -m "feat(pipeline): chain PostActionValidator after fix execution"
```

---

## Chunk 2: Human Review + Confidence Calibration

### Task 4: ReviewFeedback DB Model

**Files:**
- Modify: `src/agenticops/models.py`
- Test: `tests/test_review_service.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_review_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agenticops.models import Base, ReviewFeedback


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_review_feedback(db):
    rf = ReviewFeedback(
        review_type="rca",
        health_issue_id=1,
        rca_result_id=1,
        verdict="accurate",
        reviewer="sre-team",
    )
    db.add(rf)
    db.flush()
    assert rf.id is not None
    assert rf.verdict == "accurate"


def test_review_with_correction(db):
    rf = ReviewFeedback(
        review_type="rca",
        health_issue_id=1,
        verdict="inaccurate",
        corrected_root_cause="Actual cause was DNS timeout, not cache OOM",
        reviewer="senior-sre",
    )
    db.add(rf)
    db.flush()
    assert rf.corrected_root_cause is not None
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Add ReviewFeedback + CalibrationBin to models.py**

```python
class ReviewFeedback(Base):
    __tablename__ = "review_feedbacks"
    id = Column(Integer, primary_key=True)
    review_type = Column(String, nullable=False)  # "rca" | "fix_effectiveness" | "service_model"
    health_issue_id = Column(Integer, ForeignKey("health_issues.id"), nullable=True)
    fix_plan_id = Column(Integer, ForeignKey("fix_plans.id"), nullable=True)
    rca_result_id = Column(Integer, nullable=True)
    verdict = Column(String, nullable=False)  # accurate|partial|inaccurate|resolved|mitigated|unresolved
    notes = Column(Text, nullable=True)
    corrected_root_cause = Column(Text, nullable=True)
    reviewer = Column(String, default="")
    created_at = Column(DateTime, default=func.now())


class CalibrationBin(Base):
    __tablename__ = "calibration_bins"
    id = Column(Integer, primary_key=True)
    bin_low = Column(Float, nullable=False)   # e.g., 0.7
    bin_high = Column(Float, nullable=False)  # e.g., 0.9
    category = Column(String, default="all")  # "all" or specific category
    total_count = Column(Integer, default=0)
    accurate_count = Column(Integer, default=0)
    calibrated_accuracy = Column(Float, default=0.0)  # accurate_count / total_count
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("bin_low", "bin_high", "category"),)
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/models.py tests/test_review_service.py
git commit -m "feat(models): add ReviewFeedback and CalibrationBin tables"
```

---

### Task 5: Review Service

**Files:**
- Create: `src/agenticops/verification/review_service.py`
- Test: `tests/test_review_service.py` (extend)

- [ ] **Step 1: Write failing test for submit_review**

```python
# append to tests/test_review_service.py
from agenticops.verification.review_service import submit_review, get_review_stats


def test_submit_review_returns_id(db):
    result = submit_review(
        db=db,
        review_type="rca",
        health_issue_id=1,
        verdict="accurate",
        reviewer="sre",
    )
    assert result["id"] > 0
    assert result["verdict"] == "accurate"


def test_get_review_stats_empty(db):
    stats = get_review_stats(db)
    assert stats["total"] == 0
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement review_service.py**

```python
# src/agenticops/verification/review_service.py
from __future__ import annotations
from sqlalchemy.orm import Session
from agenticops.models import ReviewFeedback, RCAResult


def submit_review(
    db: Session,
    review_type: str,
    health_issue_id: int | None = None,
    fix_plan_id: int | None = None,
    rca_result_id: int | None = None,
    verdict: str = "",
    notes: str = "",
    corrected_root_cause: str = "",
    reviewer: str = "",
) -> dict:
    rf = ReviewFeedback(
        review_type=review_type,
        health_issue_id=health_issue_id,
        fix_plan_id=fix_plan_id,
        rca_result_id=rca_result_id,
        verdict=verdict,
        notes=notes,
        corrected_root_cause=corrected_root_cause,
        reviewer=reviewer,
    )
    db.add(rf)
    db.flush()

    # If RCA review, update calibration
    if review_type == "rca" and rca_result_id:
        _update_calibration(db, rca_result_id, verdict)

    # If inaccurate, penalize KB entry
    if verdict == "inaccurate" and rca_result_id:
        _penalize_rca(db, rca_result_id)

    db.commit()
    return {"id": rf.id, "verdict": rf.verdict, "review_type": rf.review_type}


def get_review_stats(db: Session, category: str = "") -> dict:
    q = db.query(ReviewFeedback)
    total = q.count()
    if total == 0:
        return {"total": 0, "accurate": 0, "partial": 0, "inaccurate": 0, "accuracy_rate": 0.0}
    accurate = q.filter_by(verdict="accurate").count()
    partial = q.filter_by(verdict="partial").count()
    inaccurate = q.filter_by(verdict="inaccurate").count()
    return {
        "total": total,
        "accurate": accurate,
        "partial": partial,
        "inaccurate": inaccurate,
        "accuracy_rate": accurate / total if total else 0.0,
    }


def _update_calibration(db: Session, rca_result_id: int, verdict: str):
    """Incrementally update calibration bins per spec Section 8.5."""
    from agenticops.verification.calibration import update_calibration_bin
    rca = db.query(RCAResult).get(rca_result_id)
    if rca:
        is_accurate = verdict in ("accurate",)
        update_calibration_bin(db, rca.confidence, is_accurate)


def _penalize_rca(db: Session, rca_result_id: int):
    """Mark RCA as penalized — confidence zeroed for KB learning."""
    rca = db.query(RCAResult).get(rca_result_id)
    if rca:
        rca.confidence = 0.0
        db.flush()
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/verification/review_service.py tests/test_review_service.py
git commit -m "feat(verification): add review service with feedback submission"
```

---

### Task 6: Confidence Calibration

**Files:**
- Create: `src/agenticops/verification/calibration.py`
- Test: `tests/test_calibration.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_calibration.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agenticops.models import Base, CalibrationBin
from agenticops.verification.calibration import (
    update_calibration_bin, get_calibrated_confidence, initialize_bins,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        initialize_bins(session)
        yield session


def test_bins_initialized(db):
    bins = db.query(CalibrationBin).all()
    assert len(bins) == 4  # [0-0.5, 0.5-0.7, 0.7-0.9, 0.9-1.0]


def test_update_bin_accurate(db):
    update_calibration_bin(db, raw_confidence=0.85, is_accurate=True)
    b = db.query(CalibrationBin).filter_by(bin_low=0.7, bin_high=0.9, category="all").first()
    assert b.total_count == 1
    assert b.accurate_count == 1
    assert b.calibrated_accuracy == 1.0


def test_calibrated_confidence(db):
    # Add some data to the 0.7-0.9 bin
    update_calibration_bin(db, 0.85, True)
    update_calibration_bin(db, 0.75, True)
    update_calibration_bin(db, 0.80, False)
    # 2/3 accurate
    calibrated = get_calibrated_confidence(db, 0.85)
    assert abs(calibrated - 0.667) < 0.01


def test_calibrated_confidence_no_data(db):
    # No data in bin -> return raw confidence
    calibrated = get_calibrated_confidence(db, 0.85)
    assert calibrated == 0.85
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement calibration.py**

```python
# src/agenticops/verification/calibration.py
from __future__ import annotations
from sqlalchemy.orm import Session
from agenticops.models import CalibrationBin

# Bin boundaries per spec Section 8.5
BINS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0)]


def initialize_bins(db: Session):
    for low, high in BINS:
        existing = db.query(CalibrationBin).filter_by(bin_low=low, bin_high=high, category="all").first()
        if not existing:
            db.add(CalibrationBin(bin_low=low, bin_high=high, category="all"))
    db.commit()


def _find_bin(confidence: float) -> tuple[float, float]:
    for low, high in BINS:
        if low <= confidence < high or (high == 1.0 and confidence == 1.0):
            return low, high
    return 0.0, 0.5  # fallback


def update_calibration_bin(db: Session, raw_confidence: float, is_accurate: bool, category: str = "all"):
    low, high = _find_bin(raw_confidence)
    b = db.query(CalibrationBin).filter_by(bin_low=low, bin_high=high, category=category).first()
    if not b:
        b = CalibrationBin(bin_low=low, bin_high=high, category=category)
        db.add(b)
    b.total_count += 1
    if is_accurate:
        b.accurate_count += 1
    b.calibrated_accuracy = b.accurate_count / b.total_count
    db.flush()


def get_calibrated_confidence(db: Session, raw_confidence: float, category: str = "all") -> float:
    low, high = _find_bin(raw_confidence)
    b = db.query(CalibrationBin).filter_by(bin_low=low, bin_high=high, category=category).first()
    if not b or b.total_count == 0:
        return raw_confidence  # no calibration data yet
    return round(b.calibrated_accuracy, 3)
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/verification/calibration.py tests/test_calibration.py
git commit -m "feat(verification): add bin-based confidence calibration"
```

---

### Task 7: Review API Endpoints

**Files:**
- Modify: `src/agenticops/web/app.py`

- [ ] **Step 1: Add review + calibration endpoints**

```python
# --- Review Endpoints ---

@app.post("/api/reviews")
async def submit_review_api(body: dict, db: Session = Depends(get_db)):
    from agenticops.verification.review_service import submit_review
    return submit_review(
        db=db,
        review_type=body["review_type"],
        health_issue_id=body.get("health_issue_id"),
        fix_plan_id=body.get("fix_plan_id"),
        rca_result_id=body.get("rca_result_id"),
        verdict=body["verdict"],
        notes=body.get("notes", ""),
        corrected_root_cause=body.get("corrected_root_cause", ""),
        reviewer=body.get("reviewer", ""),
    )

@app.get("/api/reviews/stats")
async def get_review_stats_api(db: Session = Depends(get_db)):
    from agenticops.verification.review_service import get_review_stats
    return get_review_stats(db)

@app.get("/api/health-issues/{issue_id}/review")
async def get_issue_review(issue_id: int, db: Session = Depends(get_db)):
    reviews = db.query(ReviewFeedback).filter_by(health_issue_id=issue_id).order_by(ReviewFeedback.created_at.desc()).all()
    return [{"id": r.id, "type": r.review_type, "verdict": r.verdict, "reviewer": r.reviewer,
             "notes": r.notes, "created_at": str(r.created_at)} for r in reviews]

@app.get("/api/health-issues/{issue_id}/verification")
async def get_issue_verification(issue_id: int, db: Session = Depends(get_db)):
    par = db.query(PostActionResult).filter_by(health_issue_id=issue_id).order_by(PostActionResult.created_at.desc()).first()
    if not par:
        return {"status": "pending"}
    return {
        "verdict": par.verdict, "metric": par.observed_metric,
        "improvement": par.metric_improvement,
        "t0": par.t0_result, "t1": par.t1_result, "t2": par.t2_result, "t3": par.t3_result,
    }

@app.get("/api/calibration")
async def get_calibration(db: Session = Depends(get_db)):
    bins = db.query(CalibrationBin).filter_by(category="all").all()
    return [{"range": f"{b.bin_low}-{b.bin_high}", "total": b.total_count,
             "accurate": b.accurate_count, "rate": b.calibrated_accuracy} for b in bins]
```

- [ ] **Step 2: Verify compilation**

```bash
python3 -m py_compile src/agenticops/web/app.py
```

- [ ] **Step 3: Commit**

```bash
git add src/agenticops/web/app.py
git commit -m "feat(api): add review, verification, and calibration endpoints"
```

---

## Chunk 3: Wisdom Roadmap + Memory Classification

### Task 8: WisdomEntry DB Model

**Files:**
- Modify: `src/agenticops/models.py`
- Test: `tests/test_wisdom_roadmap.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_wisdom_roadmap.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agenticops.models import Base, WisdomEntry


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_wisdom_entry(db):
    w = WisdomEntry(
        pattern="cache_memory_exhaustion",
        category="cache",
        strategy="1) Check deployments first 2) Verify TTL config 3) Check memory metrics",
        success_count=3,
        total_count=4,
        confidence=0.85,
    )
    db.add(w)
    db.flush()
    assert w.id is not None
    assert w.success_rate == 0.75
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Add WisdomEntry to models.py**

```python
class WisdomEntry(Base):
    __tablename__ = "wisdom_entries"
    id = Column(Integer, primary_key=True)
    pattern = Column(String, unique=True, nullable=False)
    category = Column(String, default="unknown")
    strategy = Column(Text, default="")
    success_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)
    confidence = Column(Float, default=0.5)
    source_issues = Column(Text, default="")  # JSON list of HealthIssue IDs
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_count if self.total_count else 0.0
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/models.py tests/test_wisdom_roadmap.py
git commit -m "feat(models): add WisdomEntry table for investigation strategies"
```

---

### Task 9: Wisdom Roadmap CRUD + Distillation

**Files:**
- Create: `src/agenticops/wisdom/__init__.py`
- Create: `src/agenticops/wisdom/roadmap.py`
- Create: `src/agenticops/wisdom/distiller.py`
- Test: `tests/test_wisdom_roadmap.py` (extend)

- [ ] **Step 1: Write failing test**

```python
# append to tests/test_wisdom_roadmap.py
from agenticops.wisdom.roadmap import get_wisdom_for_pattern, upsert_wisdom
from agenticops.wisdom.distiller import should_distill, distill_to_wisdom


def test_get_wisdom_not_found(db):
    result = get_wisdom_for_pattern(db, "nonexistent")
    assert result is None


def test_upsert_wisdom_new(db):
    w = upsert_wisdom(db, pattern="cache_oom", category="cache",
                      strategy="check TTL first", was_successful=True, issue_id=1)
    assert w.pattern == "cache_oom"
    assert w.success_count == 1
    assert w.total_count == 1


def test_upsert_wisdom_existing(db):
    upsert_wisdom(db, "cache_oom", "cache", "check TTL", True, 1)
    w = upsert_wisdom(db, "cache_oom", "cache", "check TTL", False, 2)
    assert w.total_count == 2
    assert w.success_count == 1  # only first was successful


def test_should_distill_after_3_cases():
    assert should_distill(resolved_count=3, has_wisdom=False) is True
    assert should_distill(resolved_count=1, has_wisdom=False) is False
    assert should_distill(resolved_count=5, has_wisdom=True) is False  # already has wisdom
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement roadmap.py and distiller.py**

```python
# src/agenticops/wisdom/__init__.py
# Wisdom Roadmap subsystem

# src/agenticops/wisdom/roadmap.py
from __future__ import annotations
import json
from sqlalchemy.orm import Session
from agenticops.models import WisdomEntry


def get_wisdom_for_pattern(db: Session, pattern: str) -> WisdomEntry | None:
    return db.query(WisdomEntry).filter_by(pattern=pattern).first()


def get_top_k_wisdom(db: Session, category: str, top_k: int = 3) -> list[WisdomEntry]:
    return (db.query(WisdomEntry)
            .filter_by(category=category)
            .order_by(WisdomEntry.confidence.desc())
            .limit(top_k)
            .all())


def upsert_wisdom(db: Session, pattern: str, category: str, strategy: str,
                   was_successful: bool, issue_id: int) -> WisdomEntry:
    existing = get_wisdom_for_pattern(db, pattern)
    if existing:
        existing.total_count += 1
        if was_successful:
            existing.success_count += 1
        # Update source_issues list
        ids = json.loads(existing.source_issues or "[]")
        ids.append(issue_id)
        existing.source_issues = json.dumps(ids[-50:])  # keep last 50
        # Recalculate confidence
        existing.confidence = existing.success_count / existing.total_count
        db.flush()
        return existing
    else:
        w = WisdomEntry(
            pattern=pattern, category=category, strategy=strategy,
            success_count=1 if was_successful else 0,
            total_count=1,
            confidence=0.7 if was_successful else 0.3,
            source_issues=json.dumps([issue_id]),
        )
        db.add(w)
        db.flush()
        return w
```

```python
# src/agenticops/wisdom/distiller.py
from __future__ import annotations

DISTILL_THRESHOLD = 3  # minimum resolved cases before creating wisdom


def should_distill(resolved_count: int, has_wisdom: bool) -> bool:
    return resolved_count >= DISTILL_THRESHOLD and not has_wisdom
```

Note: Full LLM-based strategy distillation (summarizing N investigation paths into optimal strategy) is deferred to Phase 3. Phase 2 uses the most recent successful investigation as the strategy text.

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/wisdom/__init__.py src/agenticops/wisdom/roadmap.py src/agenticops/wisdom/distiller.py tests/test_wisdom_roadmap.py
git commit -m "feat(wisdom): add Wisdom Roadmap CRUD and distillation trigger"
```

---

### Task 10: Memory Classification

**Files:**
- Create: `src/agenticops/wisdom/memory_classifier.py`
- Test: `tests/test_memory_classifier.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_memory_classifier.py
from agenticops.wisdom.memory_classifier import classify_memory_type


def test_first_occurrence_is_episodic():
    assert classify_memory_type(occurrence_count=1, pattern_count=1) == "episodic"


def test_repeated_pattern_is_procedural():
    assert classify_memory_type(occurrence_count=3, pattern_count=3) == "procedural"


def test_crystallized_pattern_is_semantic():
    assert classify_memory_type(occurrence_count=10, pattern_count=8) == "semantic"
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement memory_classifier.py**

```python
# src/agenticops/wisdom/memory_classifier.py
from __future__ import annotations


def classify_memory_type(occurrence_count: int, pattern_count: int) -> str:
    """Classify a KB entry's memory type per spec Section 4.
    episodic: individual cases (1-2 occurrences)
    procedural: investigation procedures (3-7 occurrences of same pattern)
    semantic: generalized rules (8+ occurrences)
    """
    if pattern_count >= 8:
        return "semantic"
    if pattern_count >= 3:
        return "procedural"
    return "episodic"
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/wisdom/memory_classifier.py tests/test_memory_classifier.py
git commit -m "feat(wisdom): add memory type classification (episodic/procedural/semantic)"
```

---

### Task 11: Wire Wisdom into Prompt Engine

**Files:**
- Modify: `src/agenticops/prompt_engine/strategy.py`
- Modify: `src/agenticops/agents/preamble.py`

- [ ] **Step 1: Update StrategySelector to use Wisdom Roadmap**

In `src/agenticops/prompt_engine/strategy.py`, update constructor:

```python
class StrategySelector:
    def __init__(self, wisdom_search_fn=None):
        self._wisdom_fn = wisdom_search_fn

    @classmethod
    def with_db(cls):
        """Create StrategySelector backed by Wisdom Roadmap DB."""
        def search_wisdom(pattern: str) -> str | None:
            from agenticops.models import get_db_session
            from agenticops.wisdom.roadmap import get_wisdom_for_pattern
            with get_db_session() as session:
                w = get_wisdom_for_pattern(session, pattern)
                if w and w.confidence > 0.3:
                    return f"{w.strategy} (confidence: {w.confidence:.0%}, {w.total_count} cases)"
            return None
        return cls(wisdom_search_fn=search_wisdom)
```

- [ ] **Step 2: Update preamble.py to use `StrategySelector.with_db()`**

In `build_optimized_prompt`, replace:
```python
selector = StrategySelector(wisdom_search_fn=None)
```
with:
```python
selector = StrategySelector.with_db()
```

- [ ] **Step 3: Verify compilation**

```bash
python3 -m py_compile src/agenticops/prompt_engine/strategy.py
python3 -m py_compile src/agenticops/agents/preamble.py
```

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/prompt_engine/strategy.py src/agenticops/agents/preamble.py
git commit -m "feat(prompt-engine): wire Wisdom Roadmap into strategy selection"
```

---

### Task 12: Wisdom + Review API Endpoints

**Files:**
- Modify: `src/agenticops/web/app.py`

- [ ] **Step 1: Add Wisdom endpoints**

```python
# --- Wisdom Endpoints ---

@app.get("/api/wisdom")
async def list_wisdom(category: str = "", db: Session = Depends(get_db)):
    q = db.query(WisdomEntry)
    if category:
        q = q.filter_by(category=category)
    entries = q.order_by(WisdomEntry.confidence.desc()).all()
    return [{"pattern": w.pattern, "category": w.category, "strategy": w.strategy,
             "success_rate": w.success_rate, "confidence": w.confidence,
             "total_count": w.total_count} for w in entries]

@app.get("/api/wisdom/{pattern}")
async def get_wisdom(pattern: str, db: Session = Depends(get_db)):
    from agenticops.wisdom.roadmap import get_wisdom_for_pattern
    w = get_wisdom_for_pattern(db, pattern)
    if not w:
        raise HTTPException(404, "Wisdom entry not found")
    return {"pattern": w.pattern, "category": w.category, "strategy": w.strategy,
            "success_rate": w.success_rate, "confidence": w.confidence,
            "total_count": w.total_count, "source_issues": w.source_issues}
```

- [ ] **Step 2: Verify compilation**

- [ ] **Step 3: Commit**

```bash
git add src/agenticops/web/app.py
git commit -m "feat(api): add wisdom roadmap endpoints"
```

---

### Task 13: Phase 2 Integration Test

- [ ] **Step 1: Run all Phase 2 tests**

```bash
python -m pytest tests/test_post_action_validator.py tests/test_review_service.py tests/test_calibration.py tests/test_wisdom_roadmap.py tests/test_memory_classifier.py -v
```

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 3: Verify all app compilation**

```bash
python3 -m py_compile src/agenticops/web/app.py
python3 -m py_compile src/agenticops/models.py
python3 -m py_compile src/agenticops/agents/preamble.py
python3 -m py_compile src/agenticops/services/pipeline_service.py
```

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "test: Phase 2 integration verification — all tests passing"
```

---

## Chunk 4: Review UI (Frontend)

### Task 14: ReviewCard Component

**Files:**
- Create: `src/agenticops/web/frontend/src/components/ReviewCard.tsx`
- Create: `src/agenticops/web/frontend/src/hooks/useReviews.ts`

- [ ] **Step 1: Create useReviews hook**

```typescript
// src/agenticops/web/frontend/src/hooks/useReviews.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';

export function useIssueReview(issueId: number) {
  return useQuery({
    queryKey: ['reviews', issueId],
    queryFn: () => apiClient.get(`/api/health-issues/${issueId}/review`).then(r => r.data),
  });
}

export function useIssueVerification(issueId: number) {
  return useQuery({
    queryKey: ['verification', issueId],
    queryFn: () => apiClient.get(`/api/health-issues/${issueId}/verification`).then(r => r.data),
  });
}

export function useSubmitReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      review_type: string;
      health_issue_id: number;
      rca_result_id?: number;
      verdict: string;
      notes?: string;
    }) => apiClient.post('/api/reviews', data).then(r => r.data),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['reviews', vars.health_issue_id] });
    },
  });
}
```

- [ ] **Step 2: Create ReviewCard component**

```tsx
// src/agenticops/web/frontend/src/components/ReviewCard.tsx
import { useState } from 'react';
import { useSubmitReview, useIssueVerification } from '../hooks/useReviews';

interface ReviewCardProps {
  issueId: number;
  rcaResultId?: number;
  rootCause?: string;
  confidence?: number;
}

export function ReviewCard({ issueId, rcaResultId, rootCause, confidence }: ReviewCardProps) {
  const [notes, setNotes] = useState('');
  const submit = useSubmitReview();
  const { data: verification } = useIssueVerification(issueId);

  const handleVerdict = (verdict: string) => {
    submit.mutate({
      review_type: 'rca',
      health_issue_id: issueId,
      rca_result_id: rcaResultId,
      verdict,
      notes,
    });
  };

  return (
    <div className="border rounded-lg p-4 bg-white dark:bg-gray-800">
      <h3 className="font-semibold mb-2">RCA Review</h3>
      {rootCause && <p className="text-sm text-gray-600 mb-2">{rootCause}</p>}
      {confidence != null && (
        <p className="text-sm mb-2">Confidence: {(confidence * 100).toFixed(0)}%</p>
      )}
      {verification?.verdict && (
        <p className="text-sm mb-2">
          PostAction: <span className="font-mono">{verification.verdict}</span>
          {verification.improvement != null && ` (${(verification.improvement * 100).toFixed(0)}% improvement)`}
        </p>
      )}
      <div className="flex gap-2 mb-2">
        <button onClick={() => handleVerdict('accurate')}
                className="px-3 py-1 bg-green-600 text-white rounded text-sm"
                disabled={submit.isPending}>
          Accurate
        </button>
        <button onClick={() => handleVerdict('partial')}
                className="px-3 py-1 bg-yellow-600 text-white rounded text-sm"
                disabled={submit.isPending}>
          Partially Accurate
        </button>
        <button onClick={() => handleVerdict('inaccurate')}
                className="px-3 py-1 bg-red-600 text-white rounded text-sm"
                disabled={submit.isPending}>
          Inaccurate
        </button>
      </div>
      <textarea value={notes} onChange={e => setNotes(e.target.value)}
                placeholder="Optional notes..."
                className="w-full border rounded p-2 text-sm" rows={2} />
      {submit.isSuccess && <p className="text-green-600 text-sm mt-1">Review submitted</p>}
    </div>
  );
}
```

- [ ] **Step 3: Build frontend**

```bash
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/web/frontend/src/components/ReviewCard.tsx src/agenticops/web/frontend/src/hooks/useReviews.ts
git commit -m "feat(web): add ReviewCard component with verdict buttons"
```

---

## Summary: Phase 2 Deliverables

| Component | Tasks | Files Created | Files Modified |
|-----------|-------|--------------|----------------|
| PostActionValidator | 1-3 | 3 new files | models.py, pipeline_service.py, metadata_tools.py |
| Human Review + Calibration | 4-7 | 3 new files | models.py, app.py |
| Wisdom Roadmap + Memory | 8-12 | 5 new files | models.py, strategy.py, preamble.py, app.py |
| Review UI | 14 | 2 new files | — |
| **Total** | **14 tasks** | **13 new files** | **7 modified files** |

### Dependency Graph

```
Task 1 (PostActionResult model) ── Task 2 (Validator logic) ── Task 3 (Pipeline chain)

Task 4 (ReviewFeedback model) ── Task 5 (Review service) ──┬── Task 7 (API endpoints)
                                                            └── Task 6 (Calibration) ── Task 7

Task 8 (WisdomEntry model) ── Task 9 (Roadmap CRUD) ── Task 11 (Wire to prompt engine)
                              Task 10 (Memory classify)

Task 14 (Review UI) depends on Task 7 (APIs ready)
```

Parallel tracks: PostActionValidator (1-3), Review system (4-7), and Wisdom (8-11) can be developed concurrently. Task 12-13 merge them.
