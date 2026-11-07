"""Live E2E: every direct (non-Strands) model call on the model it now runs on (2026-11-07 model-config fixes).

    AIOPS_TESTS_ALLOW_AWS=1 pytest --run-integration tests/integration/test_converse_live.py -v -s

Real, billed Bedrock Converse requests through the Bedrock session (settings.bedrock_profile / the default chain,
settings.bedrock_region) — well under $1 in all. What it proves against the live API, not a mock:
- temperature 0 is requested everywhere and only reaches the models that take it (Opus 5.5 answered 400 for it on
  every Galaxy build from 2026-11-06 07:00);
- replies of models that think by default (Opus / Sonnet 5.5) come back as text, not a reasoning block;
- a realistic 40-resource Galaxy batch completes on Opus 5.5 inside the 300 s read timeout;
- skill generation, case distillation, SOP writing and the legacy RCAEngine run on Main's model.
"""
import json
import time

import pytest
from botocore.exceptions import ClientError

from agenticops.config import settings

pytestmark = pytest.mark.integration

OPUS_55 = "global.anthropic.claude-opus-5-5"


@pytest.fixture
def main_on_opus_55(monkeypatch):
    monkeypatch.setattr(settings, "agent_main_model_id", OPUS_55)


@pytest.mark.parametrize("model_id", [
    OPUS_55,
    "global.anthropic.claude-sonnet-5-5",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.openai.gpt-6-astra",
])
def test_converse_text_requesting_temperature_0(model_id):
    from agenticops.agents.preamble import accepts_temperature, converse_text
    try:
        text, usage, stop = converse_text(model_id, "Reply with exactly one word: pong", max_tokens=2048,
                                          temperature=0, read_timeout=120, total_attempts=1)
    except ClientError as e:
        if "unsupported countries" in str(e):
            pytest.skip(f"{model_id} is geo-blocked from this network: {e}")
        raise
    print(f"\n{model_id}: temperature sent={accepts_temperature(model_id)} stop={stop} usage={usage} text={text!r}")
    assert "pong" in text.lower()
    assert stop == "end_turn" and usage["output"] > 0


def _inventory(n=40):
    """A small account the way Galaxy reads it: a VPC, subnets, security groups, instances behind a load balancer,
    a database and a function, cross-referencing each other by id in raw_data."""
    rows = [
        {"resource_type": "VPC", "name": "prod-vpc", "raw_data": {"VpcId": "vpc-0a1", "CidrBlock": "10.0.0.0/16"}},
        {"resource_type": "Subnet", "name": "prod-a", "raw_data": {"SubnetId": "subnet-0a1", "VpcId": "vpc-0a1"}},
        {"resource_type": "Subnet", "name": "prod-b", "raw_data": {"SubnetId": "subnet-0b1", "VpcId": "vpc-0a1"}},
        {"resource_type": "SecurityGroup", "name": "web-sg",
         "raw_data": {"GroupId": "sg-0web", "VpcId": "vpc-0a1", "IpPermissions": [{"FromPort": 443}]}},
        {"resource_type": "SecurityGroup", "name": "db-sg",
         "raw_data": {"GroupId": "sg-0db", "VpcId": "vpc-0a1",
                      "IpPermissions": [{"FromPort": 5432, "UserIdGroupPairs": [{"GroupId": "sg-0web"}]}]}},
        {"resource_type": "ELB", "name": "web-alb",
         "raw_data": {"LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/app/web/1",
                      "SecurityGroups": ["sg-0web"], "Subnets": ["subnet-0a1", "subnet-0b1"],
                      "Targets": [f"i-0web{i:02d}" for i in range(6)]}},
        {"resource_type": "RDS", "name": "orders-db",
         "raw_data": {"DBInstanceIdentifier": "orders-db", "VpcSecurityGroups": ["sg-0db"],
                      "DBSubnetGroup": {"Subnets": ["subnet-0a1", "subnet-0b1"]}}},
        {"resource_type": "Lambda", "name": "orders-worker",
         "raw_data": {"FunctionName": "orders-worker",
                      "Environment": {"DB_HOST": "orders-db.abc.us-east-1.rds.amazonaws.com"},
                      "VpcConfig": {"SubnetIds": ["subnet-0a1"], "SecurityGroupIds": ["sg-0web"]}}},
    ]
    i = 0
    while len(rows) < n:
        rows.append({"resource_type": "EC2", "name": f"web-{i:02d}",
                     "raw_data": {"InstanceId": f"i-0web{i:02d}", "SubnetId": "subnet-0a1" if i % 2 else "subnet-0b1",
                                  "SecurityGroups": [{"GroupId": "sg-0web"}],
                                  "UserData": "DB_HOST=orders-db.abc.us-east-1.rds.amazonaws.com"}})
        i += 1
    return [{"id": k + 1, "account_id": 1, "region": "us-east-1", "tags": {"env": "prod", "app": "orders"}, **r}
            for k, r in enumerate(rows)]


def test_a_40_resource_galaxy_batch_on_opus_5_5():
    from agenticops.galaxy import builder as B
    resources = _inventory(40)
    prompt = B._build_prompt(resources, B._compact_index(resources))
    started = time.monotonic()
    text, usage = B._call_bedrock(prompt, OPUS_55, settings.bedrock_max_tokens)   # raises on no text / cut at limit
    took = time.monotonic() - started
    edges = B._parse_llm_edges(text)
    print(f"\ngalaxy batch on {OPUS_55}: {took:.1f}s usage={usage} edges={len(edges)} sample={edges[:2]}")
    assert isinstance(edges, list)
    assert took < 300


def test_case_distillation_on_main(main_on_opus_55):
    from agenticops.tools.kb_tools import _llm_distill
    result = _llm_distill({
        "issue_id": 42, "title": "orders-db connection pool exhausted", "severity": "high",
        "symptoms": "API p99 latency 8s, 5xx on /orders", "root_cause": "a deploy raised worker concurrency 4x",
        "fix_steps": ["roll back the worker concurrency", "raise max_connections from 100 to 200"],
        "resolution": "latency back to 200ms after the rollback",
    })
    print(f"\ndistilled: {json.dumps(result)[:400] if result else result}")
    assert isinstance(result, dict) and result.get("title")


def test_sop_generation_on_main(main_on_opus_55):
    from agenticops.pipeline.sop_upgrader import generate_new_sop
    sop = generate_new_sop({"resource_type": "RDS", "issue_pattern": "connection pool exhausted", "severity": "high",
                            "title": "RDS connection exhaustion",
                            "root_cause": "client concurrency raised without raising max_connections",
                            "fix_steps": ["roll back concurrency", "raise max_connections"]})
    print(f"\nSOP head: {sop[:300]!r}")
    assert sop.lstrip().startswith("---") and "RDS" in sop


def test_skill_generation_on_main(main_on_opus_55):
    from agenticops.skills.evolution import generate_skill_from_description
    result = generate_skill_from_description("a skill for diagnosing Redis memory pressure and eviction storms")
    print(f"\nskill: { {k: (v[:80] if isinstance(v, str) else v) for k, v in result.items() if k != 'references'} }")
    assert "error" not in result, result
    assert result["name"] and result["content"].strip()


def test_legacy_rca_engine_on_main(main_on_opus_55):
    from agenticops.analyze.rca import BedrockLLM
    llm = BedrockLLM()
    assert llm.model_id == OPUS_55
    text = llm.invoke('Return only this JSON: {"root_cause": "disk full", "confidence_score": 0.9}')
    print(f"\nlegacy RCA reply: {text[:200]!r}")
    assert "disk full" in text
