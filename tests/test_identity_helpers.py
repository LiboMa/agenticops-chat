"""Pure identity helpers in galaxy.rules (spec §3.A.1 'same physical resource')."""
from datetime import datetime, timezone

from agenticops.galaxy import rules as R

FAM = {"EKS": ["EKS", "EKS_Cluster"]}


def test_short_id_and_arn_region():
    assert R.short_id("arn:aws:ec2:us-east-1:533267047935:instance/i-0abc") == "i-0abc"
    assert R.short_id("arn:aws:rds:us-east-1:533267047935:db:database-demo") == "database-demo"
    assert R.short_id("arn:aws:lambda:ap-southeast-1:533267047935:function:resize") == "resize"
    assert R.short_id("arn:aws:iam::533267047935:role/service-role/AppRole") == "AppRole"
    assert R.short_id("arn:aws:s3:::my-bucket") == "my-bucket"
    assert R.short_id("arn:aws:dynamodb:us-west-2:533267047935:table/Music") == "Music"
    assert R.short_id("agenticops-lab") == "agenticops-lab"
    assert R.short_id("agenticops-lab/Deployment/shop/web") == "agenticops-lab/Deployment/shop/web"
    assert R.arn_region("arn:aws:eks:ap-southeast-1:533267047935:cluster/x") == "ap-southeast-1"
    assert R.arn_region("arn:aws-cn:ec2:cn-north-1:113506788061:instance/i-1") == "cn-north-1"
    assert R.arn_region("arn:aws:iam::533267047935:role/x") == ""
    assert R.arn_region("i-0abc") == ""


def test_type_family_and_physical_key():
    assert R.type_family("EKS_Cluster", FAM) == "EKS" == R.type_family("EKS", FAM)
    assert R.type_family("EC2", FAM) == "EC2"
    by_name = {"id": 140, "account_id": 2, "region": "ap-southeast-1", "resource_type": "EKS",
               "resource_id": "agenticops-lab"}
    by_arn = {"id": 1178, "account_id": 2, "region": "", "resource_type": "EKS_Cluster",
              "resource_id": "arn:aws:eks:ap-southeast-1:533267047935:cluster/agenticops-lab"}
    assert R.physical_key(by_name, FAM) == R.physical_key(by_arn, FAM) == (2, "ap-southeast-1", "agenticops-lab", "EKS")


def test_dedup_physical_keeps_the_newest_scan():
    old = {"id": 1, "account_id": 2, "region": "r", "resource_type": "EKS", "resource_id": "c",
           "scanned_at": datetime(2026, 5, 1)}
    new = dict(old, id=2, resource_type="EKS_Cluster", resource_id="arn:aws:eks:r:533267047935:cluster/c",
               scanned_at=datetime(2026, 7, 1, tzinfo=timezone.utc))  # aware and naive timestamps mix in practice
    never = dict(old, id=3, scanned_at=None)
    other_account = dict(old, id=4, account_id=1)
    canon, dups = R.dedup_physical([old, new, never, other_account], FAM)
    assert [r["id"] for r in canon] == [2, 4]
    assert [(d["id"], c["id"]) for d, c in dups] == [(1, 2), (3, 2)]


def test_dedup_tie_goes_to_the_higher_id():
    a = {"id": 5, "account_id": 1, "region": "r", "resource_type": "EC2", "resource_id": "i-1", "scanned_at": None}
    canon, dups = R.dedup_physical([a, dict(a, id=9)], FAM)
    assert [r["id"] for r in canon] == [9]
    assert [(d["id"], c["id"]) for d, c in dups] == [(5, 9)]


def test_k8s_ids_and_kind_types():
    assert R.k8s_resource_id("c", "Deployment", "web", "shop") == "c/Deployment/shop/web"
    assert R.k8s_resource_id("c", "Namespace", "shop") == "c/Namespace/shop"
    assert R.K8S_KIND_TYPES["PersistentVolumeClaim"] == "K8s_PVC"
    assert R.K8S_KIND_TYPES["PodDisruptionBudget"] == "K8s_PDB"
    assert len(R.K8S_KIND_TYPES) == 13
    assert {"K8s_Pod", "K8s_Node", "K8s_Namespace"} <= set(R.K8S_KIND_TYPES.values())
