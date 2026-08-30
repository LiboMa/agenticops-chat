"""Security-side thin wrapper over graph.algorithms.internet_ingress_reachability.

Builds no security semantics into the graph algorithm — it only maps a network
posture finding to the (instance, subnet, SG[, NACL]) inputs and records the
three-state verdict + exposure path back onto the finding."""
from __future__ import annotations

from agenticops.graph.algorithms import internet_ingress_reachability
from agenticops.security.collectors import collect_network_acls

_CONTROL_PORT = {"cis-4.1": 22, "cis-4.2": 3389}


def port_for_control(control_id: str):
    return _CONTROL_PORT.get(control_id)


def _instances_for_sg(instances: dict, sg_id: str) -> list[dict]:
    """instances may be keyed by instance_id; return those whose SG list contains sg_id."""
    out = []
    for inst in instances.values():
        if sg_id in (inst.get("security_group_ids") or []):
            out.append(inst)
    return out


def annotate(findings, instances, subnets, security_groups, nacls=None):
    """Return [{finding, reachability, path, port}] — network findings evaluated,
    others marked 'n/a'. Conservative: no instance behind the SG -> 'undetermined'."""
    from agenticops.config import settings
    nacl_required = settings.security_reachability_nacl_enabled
    results = []
    for f in findings:
        port = port_for_control(f.control_id)
        if f.category != "network" or port is None:
            results.append({"finding": f, "reachability": "n/a", "path": [], "port": port})
            continue
        candidates = _instances_for_sg(instances, f.resource_id)
        if not candidates:
            results.append({"finding": f, "reachability": "undetermined",
                            "path": [], "port": port})
            continue
        best = None
        for inst in candidates:
            subnet = subnets.get(inst.get("subnet_id"))
            nacl = (nacls or {}).get(inst.get("subnet_id"))
            v = internet_ingress_reachability(
                instance=inst, subnet=subnet, security_groups=security_groups,
                port=port, nacl=nacl, nacl_required=nacl_required)
            # reachable dominates; else keep first undetermined over not_reachable
            if v.state == "reachable":
                best = v
                break
            if best is None or (best.state == "not_reachable" and v.state == "undetermined"):
                best = v
        results.append({"finding": f, "reachability": best.state,
                        "path": best.path, "port": port})
    return results


def annotate_account(findings, account, region, vpc_id, instances, subnets, security_groups):
    """Pull real NACLs for the account/vpc then delegate to annotate(). NACL fetch
    failure -> {} (annotate marks affected findings 'undetermined' under nacl_required)."""
    nacls = collect_network_acls(account, region, vpc_id)
    return annotate(findings, instances, subnets, security_groups, nacls=nacls)
