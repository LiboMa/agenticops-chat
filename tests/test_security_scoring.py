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
