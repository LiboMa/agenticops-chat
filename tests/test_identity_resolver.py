"""IdentityResolver (spec §3.A.1): one issue subject → one physical inventory row, or an honest
ambiguous / account_level / unanchored. Every lookup stays inside one account; an input that names an
account we do not manage is never searched for in the others."""
from datetime import datetime

import pytest

from agenticops.models import Base, CloudAccount, CloudResource, get_session
from agenticops.services import identity_resolver as ir

CN, GLOBAL = 1, 2
CLUSTER = "agenticops-chaos-lab"
ROLE = "AWSServiceRoleForSupport"


@pytest.fixture
def session(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/resolver.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    # Real local shape: no credentials.account_id, the account number lives only in role_arn.
    s.add_all([
        CloudAccount(id=CN, name="Agenticops-CN", provider="aws", is_enabled=True,
                     credential_source_type="assume_role",
                     credentials={"role_arn": "arn:aws-cn:iam::113506788061:role/AgenticOps-CN"}),
        CloudAccount(id=GLOBAL, name="Agenticops-Global", provider="aws", is_enabled=True,
                     credential_source_type="assume_role",
                     credentials={"role_arn": "arn:aws:iam::533267047935:role/AgenticOpsRole"}),
    ])
    s.flush()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _res(s, pk, account, rtype, rid, region="us-east-1", name=None, scanned_at=None, provider="aws"):
    s.add(CloudResource(id=pk, account_id=account, provider=provider, region=region, resource_type=rtype,
                        resource_id=rid, name=rid if name is None else name, tags={}, raw_data={},
                        scanned_at=scanned_at))
    s.flush()


def _k8s(s, pk, kind, name, ns=None):
    from agenticops.galaxy.rules import K8S_KIND_TYPES, k8s_resource_id

    _res(s, pk, GLOBAL, K8S_KIND_TYPES[kind], k8s_resource_id(CLUSTER, kind, name, ns), name=name,
         provider="kubernetes")


def _eks_lab(s):
    """ids 140 / 1177 / 1178 of the local database."""
    _res(s, 140, GLOBAL, "EKS", "agenticops-lab", region="ap-southeast-1", scanned_at=datetime(2026, 7, 1, 14, 6))
    _res(s, 1177, GLOBAL, "EKS_Cluster", "arn:aws:eks:us-west-2:533267047935:cluster/agenticops-lab",
         region="us-west-2", name="agenticops-lab", scanned_at=datetime(2026, 5, 29, 9, 44))
    _res(s, 1178, GLOBAL, "EKS_Cluster", "arn:aws:eks:ap-southeast-1:533267047935:cluster/agenticops-lab",
         region="ap-southeast-1", name="agenticops-lab", scanned_at=datetime(2026, 5, 29, 9, 45))


def _resolve(s, **kw):
    for key in ("account_id", "resource_id", "hints", "alarm_name"):
        kw.setdefault(key, None)
    kw.setdefault("provider", "aws")
    return ir.resolve(s, **kw)


# ── account_pk ────────────────────────────────────────────────────────


def test_account_pk_maps_pk_name_and_account_number(session):
    assert ir.account_pk(session, GLOBAL) == GLOBAL
    assert ir.account_pk(session, "2") == GLOBAL
    assert ir.account_pk(session, "Agenticops-CN") == CN
    assert ir.account_pk(session, "533267047935") == GLOBAL  # role_arn account segment
    assert ir.account_pk(session, "113506788061") == CN      # aws-cn partition
    session.add(CloudAccount(id=3, name="lab", provider="aws", is_enabled=False,
                             credential_source_type="environment", credentials={"account_id": "222222222222"}))
    session.flush()
    assert ir.account_pk(session, "222222222222") == 3        # credentials.account_id; disabled still counts


def test_account_pk_rejects_unknown_values(session):
    for value in (None, "", "  ", True, 99, "99", "999999999999", "no-such-account"):
        assert ir.account_pk(session, value) is None, value


# ── rules 1–4: inventory ids and names ────────────────────────────────


def test_exact_id(session):
    _res(session, 10, GLOBAL, "EC2", "i-0abc")
    a = _resolve(session, account_id=GLOBAL, resource_id="i-0abc")
    assert (a.status, a.resource_ref, a.account_id, a.rule) == (ir.ANCHORED, 10, GLOBAL, "resource_id")
    assert a.audit() == {"rule": "resource_id", "candidates": []}


def test_arn_input_matches_a_short_id_row_and_names_the_account(session):
    _res(session, 10, GLOBAL, "EC2", "i-0abc")
    a = _resolve(session, resource_id="arn:aws:ec2:us-east-1:533267047935:instance/i-0abc")
    assert (a.status, a.resource_ref, a.account_id) == (ir.ANCHORED, 10, GLOBAL)


def test_short_input_matches_an_arn_row(session):
    _res(session, 20, GLOBAL, "Lambda", "arn:aws:lambda:us-east-1:533267047935:function:resize", name="resize-fn")
    a = _resolve(session, account_id=GLOBAL, resource_id="resize")
    assert (a.status, a.resource_ref) == (ir.ANCHORED, 20)


def test_like_wildcards_in_ids_are_literal(session):
    _res(session, 21, GLOBAL, "DynamoDB", "arn:aws:dynamodb:us-east-1:533267047935:table/nexusXshares")
    assert _resolve(session, account_id=GLOBAL, resource_id="nexus_shares").status == ir.UNANCHORED


def test_same_physical_rows_anchor_the_newest_scan(session):
    _eks_lab(session)
    a = _resolve(session, account_id=GLOBAL, resource_id="agenticops-lab", hints={"region": "ap-southeast-1"})
    assert (a.status, a.resource_ref) == (ir.ANCHORED, 140)
    assert a.candidates == [{"ref": 1178, "account_id": GLOBAL, "reason": "duplicate_of", "of": 140}]


def test_cluster_arn_anchors_the_same_physical_resource(session):
    _eks_lab(session)
    a = _resolve(session, resource_id="arn:aws:eks:ap-southeast-1:533267047935:cluster/agenticops-lab")
    assert (a.status, a.resource_ref, a.account_id) == (ir.ANCHORED, 140, GLOBAL)


def test_same_name_in_two_regions_is_ambiguous(session):
    _eks_lab(session)
    a = _resolve(session, account_id=GLOBAL, resource_id="agenticops-lab")
    assert (a.status, a.resource_ref, a.account_id) == (ir.AMBIGUOUS, None, GLOBAL)
    assert [c["ref"] for c in a.candidates if c["reason"] != "duplicate_of"] == [140, 1177]


@pytest.mark.parametrize("rid", [
    "arn:aws:elasticloadbalancing:ap-southeast-1:533267047935:loadbalancer/app/weblab-alb/66331874f5a678e3",
    "arn:aws:elasticloadbalancing:ap-southeast-1:533267047935:listener/app/weblab-alb/66331874f5a678e3/0a1b2c3d4e5f6a7b",
    "app/weblab-alb/66331874f5a678e3",
])
def test_load_balancer_arn_forms_anchor_the_elb_row(session, rid):
    _res(session, 30, GLOBAL, "ELB", "weblab-alb", region="ap-southeast-1")
    a = _resolve(session, resource_id=rid)
    assert (a.status, a.resource_ref, a.account_id, a.rule) == (ir.ANCHORED, 30, GLOBAL, "elb_arn")


def test_unique_name(session):
    _res(session, 40, GLOBAL, "EC2", "i-0name", name="web-1")
    a = _resolve(session, account_id=GLOBAL, resource_id="web-1")
    assert (a.status, a.resource_ref, a.rule) == (ir.ANCHORED, 40, "name")


def test_name_shared_by_two_resources_is_ambiguous(session):
    _res(session, 40, GLOBAL, "EC2", "i-0name", name="web-1")
    _res(session, 41, GLOBAL, "EC2", "i-0other", name="web-1")
    a = _resolve(session, account_id=GLOBAL, resource_id="web-1")
    assert (a.status, [c["ref"] for c in a.candidates]) == (ir.AMBIGUOUS, [40, 41])


def test_arn_short_id_never_name_matches_unrelated_resource(session):
    """An ARN's last segment is not a name: '…/stages/default' must not anchor the one SG named 'default'."""
    _res(session, 80, GLOBAL, "SecurityGroup", "sg-0dflt", region="ap-southeast-1", name="default")
    stage = "arn:aws:apigateway:ap-southeast-1::/restapis/9xugufy4wh/stages/default"
    for kw in ({"account_id": GLOBAL}, {}):
        a = _resolve(session, resource_id=stage, **kw)
        assert (a.status, a.resource_ref) == (ir.UNANCHORED, None), kw
    assert _resolve(session, account_id=GLOBAL, resource_id="default").resource_ref == 80  # bare names unchanged


# ── rule 5: the account itself ────────────────────────────────────────


@pytest.mark.parametrize("rid", [
    "533267047935", "533267047935-root", "AWS::::Account:533267047935", "arn:aws:iam::533267047935:root",
    "account-533267047935", "aws-iam-533267047935",
    "arn:aws:ec2:us-west-2:533267047935:vpcblockpublicaccessoptions/533267047935",
])
def test_account_level_subjects(session, rid):
    a = _resolve(session, resource_id=rid)
    assert (a.status, a.resource_ref, a.account_id, a.rule) == (ir.ACCOUNT_LEVEL, None, GLOBAL, "account_level")


def test_cis_control_takes_the_account_from_the_input(session):
    assert _resolve(session, resource_id="CIS-UnauthorizedAPICalls").account_id is None
    a = _resolve(session, account_id="Agenticops-CN", resource_id="CIS-UnauthorizedAPICalls")
    assert (a.status, a.account_id) == (ir.ACCOUNT_LEVEL, CN)


# ── rules 6–7: K8s hints and alarm names ──────────────────────────────


def test_pod_hint_strips_the_replicaset_hash(session):
    _k8s(session, 50, "Deployment", "checkout", "shop")
    hints = {"cluster": CLUSTER, "namespace": "shop", "pod": "checkout-7d9f8b6c5-x2k4q"}
    a = _resolve(session, hints=hints)  # the alert says provider=aws; K8s rows are provider=kubernetes
    assert (a.status, a.resource_ref, a.account_id, a.rule) == (ir.ANCHORED, 50, GLOBAL, "k8s_hints")


def test_statefulset_ordinal_and_bare_pod(session):
    _k8s(session, 51, "StatefulSet", "redis", "db")
    _k8s(session, 52, "Pod", "stress-test", "default")
    assert _resolve(session, hints={"cluster": CLUSTER, "namespace": "db", "pod": "redis-0"}).resource_ref == 51
    assert _resolve(session, hints={"cluster": CLUSTER, "namespace": "default", "pod": "stress-test"}).resource_ref == 52


def test_namespace_then_cluster_fallbacks(session):
    _res(session, 1355, GLOBAL, "EKS", CLUSTER)
    _k8s(session, 53, "Namespace", "shop")
    assert _resolve(session, hints={"cluster": CLUSTER, "namespace": "shop", "pod": "gone-abcde"}).resource_ref == 53
    assert _resolve(session, hints={"cluster": CLUSTER}).resource_ref == 1355


def test_pod_matching_two_workloads_is_ambiguous(session):
    _k8s(session, 54, "Deployment", "my-app", "shop")
    _k8s(session, 55, "DaemonSet", "my-app-backend", "shop")
    a = _resolve(session, hints={"cluster": CLUSTER, "namespace": "shop", "pod": "my-app-backend-x7k2p"})
    assert (a.status, [c["ref"] for c in a.candidates]) == (ir.AMBIGUOUS, [54, 55])


def test_k8s_names_are_identities_only_inside_their_namespace(session):
    _k8s(session, 50, "Deployment", "checkout", "shop")
    _k8s(session, 56, "Service", "checkout", "shop")
    assert _resolve(session, resource_id="checkout").status == ir.UNANCHORED
    hints = {"cluster": CLUSTER, "namespace": "shop", "workload": "checkout"}
    a = _resolve(session, resource_id="checkout", hints=hints)
    assert (a.status, a.resource_ref, a.rule) == (ir.ANCHORED, 50, "k8s_hints")
    assert _resolve(session, resource_id=f"{CLUSTER}/Service/shop/checkout").resource_ref == 56


@pytest.mark.parametrize("alarm", [f"EKS-{CLUSTER}-PodRestarts-High", f"EKS-{CLUSTER}-Backend-Unreachable"])
def test_alarm_name_supplies_the_cluster(session, alarm):
    _res(session, 1355, GLOBAL, "EKS", CLUSTER)
    a = _resolve(session, resource_id="unknown", alarm_name=alarm)
    assert (a.status, a.resource_ref, a.rule) == (ir.ANCHORED, 1355, "alarm_name")


def test_alarm_cluster_missing_from_inventory_stays_unanchored(session):
    _res(session, 1355, GLOBAL, "EKS", CLUSTER)
    a = _resolve(session, alarm_name="EKS-ghost-cluster-CPU-High")
    assert (a.status, a.resource_ref) == (ir.UNANCHORED, None)


# ── account scope ─────────────────────────────────────────────────────


def test_cross_account_duplicate_id_never_crosses(session):
    """Review Focus 2: the local DB has 36 resource_ids present in both accounts (35 of them IAM roles)."""
    _res(session, 60, CN, "IAMRole", ROLE, region="global")
    _res(session, 61, GLOBAL, "IAMRole", ROLE, region="global")
    unknown = _resolve(session, resource_id=ROLE)
    assert (unknown.status, unknown.resource_ref, unknown.account_id) == (ir.AMBIGUOUS, None, None)
    assert sorted((c["ref"], c["account_id"]) for c in unknown.candidates) == [(60, CN), (61, GLOBAL)]
    assert _resolve(session, resource_id=f"arn:aws:iam::533267047935:role/{ROLE}").resource_ref == 61
    assert _resolve(session, resource_id=f"arn:aws-cn:iam::113506788061:role/{ROLE}").resource_ref == 60
    assert _resolve(session, account_id="Agenticops-CN", resource_id=ROLE).resource_ref == 60
    assert _resolve(session, account_id=GLOBAL, resource_id=ROLE).resource_ref == 61


def test_unknown_account_unique_hit_backfills_the_account(session):
    _res(session, 70, CN, "EC2", "i-0only", region="cn-north-1")
    a = _resolve(session, resource_id="i-0only")
    assert (a.status, a.resource_ref, a.account_id) == (ir.ANCHORED, 70, CN)


def test_disabled_accounts_are_not_searched_without_an_account(session):
    session.get(CloudAccount, CN).is_enabled = False
    session.flush()
    _res(session, 70, CN, "EC2", "i-0only", region="cn-north-1")
    assert _resolve(session, resource_id="i-0only").status == ir.UNANCHORED
    assert _resolve(session, account_id=CN, resource_id="i-0only").resource_ref == 70


@pytest.mark.parametrize("kw", [
    {"account_id": "999999999999", "resource_id": "i-0abc"},
    {"account_id": "no-such-account", "resource_id": "i-0abc"},
    {"hints": {"account": "999999999999"}, "resource_id": "i-0abc"},
    {"resource_id": "arn:aws:ec2:us-east-1:999999999999:instance/i-0abc"},
])
def test_an_account_we_do_not_manage_is_never_searched_elsewhere(session, kw):
    _res(session, 10, GLOBAL, "EC2", "i-0abc")
    a = _resolve(session, **kw)
    assert (a.status, a.resource_ref, a.account_id, a.rule) == (ir.UNANCHORED, None, None, "unknown_account")


def test_arn_account_conflicting_with_explicit_account_never_anchors(session):
    """The ARN names CN; a claimed GLOBAL (explicit pk, name, or hint) must not anchor GLOBAL's same-named role."""
    _res(session, 60, CN, "IAMRole", ROLE, region="global")
    _res(session, 61, GLOBAL, "IAMRole", ROLE, region="global")
    cn_arn = f"arn:aws-cn:iam::113506788061:role/{ROLE}"
    for kw in ({"account_id": GLOBAL}, {"account_id": "Agenticops-Global"}, {"hints": {"account": "533267047935"}}):
        a = _resolve(session, resource_id=cn_arn, **kw)
        assert (a.status, a.resource_ref, a.account_id, a.rule) == (ir.UNANCHORED, None, None, "account_conflict"), kw
    assert _resolve(session, account_id=GLOBAL, resource_id=cn_arn).candidates == [
        {"account": str(GLOBAL), "arn_account": "113506788061", "reason": "account_conflict"}]
    same = _resolve(session, account_id="Agenticops-CN", resource_id=cn_arn)  # segment agrees: still anchors
    assert (same.status, same.resource_ref, same.account_id) == (ir.ANCHORED, 60, CN)
    # The claimed account's own number is unknown (no account_id, no role_arn): no comparison is possible.
    session.add(CloudAccount(id=3, name="lab", provider="aws", is_enabled=True,
                             credential_source_type="environment", credentials={}))
    session.flush()
    _res(session, 62, 3, "IAMRole", ROLE, region="global")
    assert _resolve(session, account_id=3, resource_id=cn_arn).resource_ref == 62


def test_nothing_matches(session):
    for kw in ({"resource_id": "sa-malibo"}, {"resource_id": ""}, {"resource_id": "unknown"}, {}):
        a = _resolve(session, **kw)
        assert (a.status, a.resource_ref, a.rule) == (ir.UNANCHORED, None, "none"), kw


def test_a_named_account_is_kept_when_nothing_matches(session):
    a = _resolve(session, account_id="Agenticops-Global", resource_id="sa-malibo")
    assert (a.status, a.account_id) == (ir.UNANCHORED, GLOBAL)


# ── search_all_accounts=False: a retry whose signal's account is unknown (final review I-1) ──


def test_no_cross_account_search_when_the_caller_forbids_it(session):
    _res(session, 70, CN, "EC2", "i-0only", region="cn-north-1")
    a = _resolve(session, resource_id="i-0only", search_all_accounts=False)
    assert (a.status, a.resource_ref, a.account_id, a.rule, a.candidates) == (
        ir.UNANCHORED, None, None, "account_unknown", [])
    assert _resolve(session, resource_id="i-0only").resource_ref == 70  # the default still searches


@pytest.mark.parametrize("kw,expected", [
    ({"resource_id": "arn:aws:ec2:us-east-1:533267047935:instance/i-0abc"}, (ir.ANCHORED, 10, GLOBAL)),
    ({"resource_id": "533267047935-root"}, (ir.ACCOUNT_LEVEL, None, GLOBAL)),
    ({"resource_id": "i-0abc", "hints": {"account": "Agenticops-Global"}}, (ir.ANCHORED, 10, GLOBAL)),
    ({"resource_id": "i-0abc", "account_id": GLOBAL}, (ir.ANCHORED, 10, GLOBAL)),
])
def test_an_input_that_names_its_account_ignores_search_all_accounts(session, kw, expected):
    _res(session, 10, GLOBAL, "EC2", "i-0abc")
    a = _resolve(session, search_all_accounts=False, **kw)
    assert (a.status, a.resource_ref, a.account_id) == expected


# ── K8s: the cluster is disambiguated before any namespaced lookup (final review I-2) ──


def _twin_lab_clusters(s):
    """Two physical clusters named 'lab' in one account; K8s ids carry no region (spec §3.B.3)."""
    from agenticops.galaxy.rules import k8s_resource_id

    _res(s, 90, GLOBAL, "EKS_Cluster", "arn:aws:eks:us-east-1:533267047935:cluster/lab", region="us-east-1", name="lab")
    _res(s, 91, GLOBAL, "EKS", "lab", region="us-west-2")
    _res(s, 92, GLOBAL, "K8s_Deployment", k8s_resource_id("lab", "Deployment", "web", "default"), region="us-east-1",
         name="web", provider="kubernetes")


def test_same_named_clusters_make_a_namespaced_hint_ambiguous(session):
    _twin_lab_clusters(session)
    a = _resolve(session, hints={"cluster": "lab", "namespace": "default", "workload": "web"})
    assert (a.status, a.resource_ref, a.account_id, a.rule) == (ir.AMBIGUOUS, None, GLOBAL, "k8s_hints")
    assert [c["ref"] for c in a.candidates] == [90, 91]


def test_a_region_hint_singles_out_the_cluster(session):
    _twin_lab_clusters(session)
    a = _resolve(session, hints={"cluster": "lab", "namespace": "default", "workload": "web", "region": "us-east-1"})
    assert (a.status, a.resource_ref, a.account_id, a.rule) == (ir.ANCHORED, 92, GLOBAL, "k8s_hints")


def test_one_physical_cluster_in_two_rows_still_anchors_namespaced_objects(session):
    """The same cluster scanned as EKS and as EKS_Cluster is one physical cluster, not a twin."""
    _res(session, 1355, GLOBAL, "EKS", CLUSTER)
    _res(session, 1356, GLOBAL, "EKS_Cluster", f"arn:aws:eks:us-east-1:533267047935:cluster/{CLUSTER}", name=CLUSTER)
    _k8s(session, 50, "Deployment", "checkout", "shop")
    a = _resolve(session, hints={"cluster": CLUSTER, "namespace": "shop", "workload": "checkout"})
    assert (a.status, a.resource_ref) == (ir.ANCHORED, 50)
