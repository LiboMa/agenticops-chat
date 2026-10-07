"""Fault-propagation direction registry (spec §3.A.2). upstream(x) = what x depends on (faults flow from
them to x, root-cause candidates); downstream(x) = what depends on x (blast radius). The old
'incoming edge = upstream' reading is gone — these tests pin the new one per relation type."""
from agenticops.graph import relations as R


def test_contains_parent_is_upstream_of_child():
    edges = [("subnet", "ec2", "contains")]
    assert R.upstream_of("ec2", edges) == {"subnet"}
    assert R.downstream_of("subnet", edges) == {"ec2"}
    assert R.upstream_of("subnet", edges) == set()


def test_secured_by_group_is_upstream_of_instance():
    edges = [("ec2", "sg", "secured_by")]
    assert R.upstream_of("ec2", edges) == {"sg"}
    assert R.downstream_of("sg", edges) == {"ec2"}
    assert R.downstream_of("ec2", edges) == set()


def test_routes_to_target_is_upstream_of_router():
    edges = [("service", "deployment", "routes_to")]
    assert R.upstream_of("service", edges) == {"deployment"}
    assert R.downstream_of("deployment", edges) == {"service"}


def test_uses_runs_on_restricts_attached_to():
    assert R.upstream_of("lambda", [("lambda", "role", "uses")]) == {"role"}
    assert R.upstream_of("deploy", [("deploy", "node", "runs_on")]) == {"node"}
    assert R.upstream_of("deploy", [("netpol", "deploy", "restricts")]) == {"netpol"}
    assert R.upstream_of("ec2", [("ebs", "ec2", "attached_to")]) == {"ebs"}


def test_manages_and_same_as_propagate_both_ways():
    for rtype in ("manages", "same_as"):
        edges = [("a", "b", rtype)]
        assert R.upstream_of("a", edges) == {"b"} and R.downstream_of("a", edges) == {"b"}
        assert R.upstream_of("b", edges) == {"a"} and R.downstream_of("b", edges) == {"a"}


def test_llm_only_and_unknown_types_do_not_propagate():
    for rtype in ("references", "inferred_group", "member_of", "no_such_type"):
        edges = [("a", "b", rtype)]
        assert R.upstream_of("a", edges) == set() == R.downstream_of("a", edges)
        assert R.propagation(rtype) == R.NONE
    assert R.RULE_RELATION_TYPES == frozenset(
        {"contains", "secured_by", "attached_to", "routes_to", "manages", "uses", "restricts", "runs_on", "same_as"}
    )


def test_step_is_relative_to_the_frontier_end():
    assert R.step("contains", frontier_is_src=True) == (True, False)   # child is downstream of parent
    assert R.step("contains", frontier_is_src=False) == (False, True)  # parent is upstream of child
    assert R.step("secured_by", frontier_is_src=True) == (False, True)
    assert R.step("manages", frontier_is_src=True) == (True, True)
    assert R.step("references", frontier_is_src=True) == (False, False)


def test_default_relations_by_issue_class():
    assert set(R.default_relations("network_flap")) == {"contains", "secured_by", "routes_to", "restricts", "uses"}
    assert set(R.default_relations("cpu_spike")) == {
        "contains", "secured_by", "routes_to", "restricts", "uses", "attached_to", "manages", "runs_on", "same_as"
    }
    assert set(R.default_relations("cpu_spike", anchor_type="RDS")) == {"contains", "secured_by", "uses"}
    assert set(R.default_relations("something_new")) == R.RULE_RELATION_TYPES
    assert set(R.default_relations(None)) == R.RULE_RELATION_TYPES


def test_llm_relation_types_keep_the_prompt_vocabulary():
    from agenticops.galaxy import rules

    assert rules.LLM_RELATION_TYPES == frozenset(
        {"contains", "references", "member_of", "attached_to", "secured_by", "routes_to", "inferred_group"}
    )
    assert not hasattr(rules, "RELATION_TYPES")
