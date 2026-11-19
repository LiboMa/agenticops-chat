from agenticops.security.collectors import PostureFinding
from agenticops.security.scoring import CIS_CONTROLS, score


def _f(control_id, cat="iam"):
    return PostureFinding(cat, control_id, "r", "t", "check")


class TestScoring:
    def test_clean_posture_scores_100(self):
        r = score([])
        assert r.overall_score == 100.0
        assert all(v == "pass" for v in r.cis_results.values())

    def test_each_failing_control_lowers_overall(self):
        total = len(CIS_CONTROLS)
        r = score([_f("cis-1.3")])
        assert r.cis_results["cis-1.3"] == "fail"
        assert round(r.overall_score, 4) == round((total - 1) / total * 100, 4)

    def test_category_score_isolated(self):
        # one of 3 iam controls fails -> iam category = 2/3, others 100
        r = score([_f("cis-1.3", "iam")])
        assert round(r.category_scores["iam"], 1) == round(2 / 3 * 100, 1)
        assert r.category_scores["network"] == 100.0

    def test_reproducible(self):
        findings = [_f("cis-1.3"), _f("cis-4.1", "network")]
        assert score(findings).overall_score == score(findings).overall_score
        assert score(findings).cis_results == score(findings).cis_results

    def test_duplicate_findings_same_control_count_once(self):
        r = score([_f("cis-1.3"), _f("cis-1.3")])
        assert r.cis_results["cis-1.3"] == "fail"
        # metrics counts raw findings; cis_results is pass/fail per control
        assert r.metrics.get("iam", 0) == 2


class TestCollectionHealth:
    """MVP-2.9.0 N20 (2.8.0 S3): a control whose source could not be read is not a pass, and a score that no
    source stands behind is not a number."""

    def test_every_control_has_a_source(self):
        from agenticops.security.scoring import CIS_CONTROLS, CONTROL_SOURCE, SOURCES
        assert set(CONTROL_SOURCE) == set(CIS_CONTROLS)
        assert set(CONTROL_SOURCE.values()) == set(SOURCES)

    def test_a_failed_source_makes_its_controls_undetermined(self):
        r = score([], failed_sources={"iam"})
        assert {c: v for c, v in r.cis_results.items() if v != "pass"} == {
            "cis-1.3": "undetermined", "cis-1.4": "undetermined", "cis-1.10": "undetermined"}
        assert r.overall_score == 62.5            # 5 of 8 known to pass — an unread control is not a pass
        assert r.category_scores["iam"] is None   # nothing was read for it: no number at all
        assert r.category_scores["network"] == 100.0

    def test_a_violation_that_was_seen_is_a_fail_even_when_its_source_then_failed(self):
        r = score([_f("cis-enc", "data")], failed_sources={"ebs"})
        assert r.cis_results["cis-enc"] == "fail"

    def test_a_category_with_one_source_left_is_scored(self):
        r = score([], failed_sources={"s3"})
        assert (r.cis_results["cis-2.1"], r.cis_results["cis-enc"]) == ("undetermined", "pass")
        assert r.category_scores["data"] == 50.0

    def test_no_score_when_every_source_failed(self):
        from agenticops.security.scoring import SOURCES
        r = score([], failed_sources=SOURCES)
        assert r.overall_score is None
        assert set(r.category_scores.values()) == {None}
        assert set(r.cis_results.values()) == {"undetermined"}

    def test_every_source_failed_with_one_violation_seen_is_still_no_score(self):
        from agenticops.security.scoring import SOURCES
        r = score([_f("cis-enc", "data")], failed_sources=SOURCES)
        assert r.overall_score is None and r.category_scores["data"] is None
        assert r.cis_results["cis-enc"] == "fail"

    def test_missing_data_never_raises_a_score(self):
        from itertools import combinations

        from agenticops.security.scoring import CIS_CONTROLS, SOURCES
        findings = [_f(cid, cat) for cid, (cat, _) in list(CIS_CONTROLS.items())[::2]]
        whole = score(findings)
        for n in range(1, len(SOURCES)):
            for failed in combinations(sorted(SOURCES), n):
                part = score(findings, failed_sources=failed)
                assert part.overall_score <= whole.overall_score, failed
                for cat, value in part.category_scores.items():
                    assert value is None or value <= whole.category_scores[cat], (failed, cat)

    def test_reproducible_with_failures(self):
        a = score([_f("cis-4.1", "network")], failed_sources=["iam", "s3"])
        b = score([_f("cis-4.1", "network")], failed_sources={"s3", "iam"})
        assert a == b

    def test_an_unknown_source_name_is_refused(self):
        import pytest
        with pytest.raises(ValueError):
            score([], failed_sources={"dns"})
