# tests/test_post_check_binding.py
"""Post-check results bind one to one to the plan's declared checks by check_id (MVP-2.7.0 S1a).

A declared check's id is its position, pc-1 … pc-n: the checks are part of the content hash, so they are
frozen once approved and the position is stable for the run. A result counts only for the check it names;
a duplicate, a missing, an undeclared or an id-less result can never make a run pass."""
import json

import pytest

from agenticops.services import verification as vf
from agenticops.services.verification import FAILED, PASSED, PENDING, evaluate

A = {"check": "rollout ready", "command": "kubectl rollout status deploy/web"}
B = {"check": "http health", "command": "curl -fsS http://web/healthz"}


def ok(cid):
    return {"check_id": cid, "status": "passed", "output": "ok"}


def test_september_counterexample_a_repeated_result_cannot_cover_a_missing_check():
    """docs/research/2026-10-05-mvp-2.6.1-assessment.md: declared A, B; reported A passed twice → was `passed`."""
    verdict, reason = evaluate("succeeded", [A, B], [ok("pc-1"), ok("pc-1")])
    assert verdict == PENDING
    assert reason == "no result for post-check pc-2; post-check pc-1 reported more than once"


def test_check_ids_are_positional_and_distinct_for_identical_checks():
    assert vf.check_ids([A, A, "x"]) == ["pc-1", "pc-2", "pc-3"]
    assert vf.check_ids([]) == []


def test_each_declared_check_bound_once_passes_in_any_order():
    assert evaluate("succeeded", [A, B], [ok("pc-2"), ok("pc-1")]) == (PASSED, "all post-checks passed")


def test_identical_declared_checks_each_need_their_own_result():
    assert evaluate("succeeded", [A, A], [ok("pc-1"), ok("pc-2")]) == (PASSED, "all post-checks passed")
    assert evaluate("succeeded", [A, A], [ok("pc-1")]) == (PENDING, "no result for post-check pc-2")


@pytest.mark.parametrize("results,reason", [
    ([ok("pc-1")], "no result for post-check pc-2"),
    ([ok("pc-1"), ok("pc-1"), ok("pc-2")], "post-check pc-1 reported more than once"),
    ([ok("pc-1"), ok("pc-2"), ok("pc-9")], "result for undeclared check pc-9"),
    ([ok("pc-1"), {"check": "http health", "status": "passed"}],
     "no result for post-check pc-2; 1 result without a check_id"),
    ([ok("pc-1"), {"check_id": "pc-2"}], "post-check pc-2 reported no status"),
    ([ok("pc-1"), {"check_id": " PC-2 ", "status": "ok"}], None),  # ids compare trimmed, case-insensitive
])
def test_a_binding_problem_names_the_check(results, reason):
    expected = (PASSED, "all post-checks passed") if reason is None else (PENDING, reason)
    assert evaluate("succeeded", [A, B], results) == expected


def test_id_less_results_never_pass_even_when_the_count_matches():
    assert evaluate("succeeded", [A, B], [{"status": "passed"}, {"status": "passed"}]) == (
        PENDING, "no result for post-check pc-1, pc-2; 2 results without a check_id")


def test_a_failure_fails_whatever_it_is_bound_to():
    assert evaluate("succeeded", [A, B], [ok("pc-1"), {"check_id": "pc-2", "status": "failed"}]) == (
        FAILED, "post-check pc-2 failed")
    assert evaluate("succeeded", [A, B], [ok("pc-1"), {"status": "failed"}]) == (FAILED, "post-check 2 failed")
    assert evaluate("succeeded", [A], [ok("pc-1"), {"check_id": "pc-7", "status": "error"}]) == (
        FAILED, "post-check pc-7 failed")


def test_a_warning_names_its_check():
    assert evaluate("succeeded", [A, B], [ok("pc-1"), {"check_id": "pc-2", "status": "warning"}]) == (
        PENDING, "post-check pc-2 reported a warning")


def test_a_changed_plan_cannot_vouch_for_the_run():
    assert evaluate("succeeded", [A], [ok("pc-1")], plan_changed=True) == (
        PENDING, "the plan changed after approval; its post-checks cannot vouch for this run")
    # a failure still fails
    assert evaluate("succeeded", [A], [{"check_id": "pc-1", "status": "failed"}], plan_changed=True)[0] == FAILED


@pytest.mark.parametrize("post_checks,ids", [
    ([A, B], ["pc-1", "pc-2"]),
    (A, ["pc-1"]),                                   # a dict is one check
    (json.dumps([A, B]), ["pc-1", "pc-2"]),          # a legacy JSON string
    (json.dumps(json.dumps([A])), ["pc-1"]),         # double-encoded, as FixPlanResponse decodes it
    ("verify the service answers", ["pc-1"]),        # plain text is one check, as the UI shows it
    (None, []),
    ("[]", []),
])
def test_declared_checks_is_the_one_reading_of_post_checks(post_checks, ids):
    assert vf.check_ids(post_checks) == ids


def test_the_api_reading_of_post_checks_is_the_same_function():
    from agenticops.web.schemas import FixPlanResponse
    for raw in (json.dumps(json.dumps([A])), "verify the service answers", A, None):
        assert FixPlanResponse._decode_legacy_json.__func__  # the validator exists
        assert vf.declared_checks(raw) == vf.decode_legacy_json(raw, list)


def test_annotated_checks_carry_their_id_and_keep_their_fields():
    assert vf.annotated_checks([A, "x", 3]) == [
        {"check_id": "pc-1", **A},
        {"check_id": "pc-2", "check": "x"},
        {"check_id": "pc-3", "check": "3"},
    ]


def test_bind_results_one_row_per_declared_check_then_strays():
    rows = vf.bind_results([A, B], [ok("pc-1"), ok("pc-1"), ok("pc-9"), {"status": "passed"}])
    assert [(r["check_id"], r["problem"]) for r in rows] == [
        ("pc-1", "duplicate"), ("pc-2", "missing"), ("pc-9", "undeclared"), (None, "unbound")]
    assert rows[0]["check"] == "rollout ready" and rows[0]["result_status"] == "pass"
    assert rows[1]["result_status"] is None
