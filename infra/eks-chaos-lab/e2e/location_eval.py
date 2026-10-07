"""Root-cause location eval metrics (MVP-2.6.1 spec §3.C.6).

Pure: no network, no cluster, no clock — `test_e2e_location.py` collects, this scores. Run it on result files
to print the report tables:

    python location_eval.py results/location-<off>.json results/location-<on>.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

import yaml

E2E_DIR = Path(__file__).resolve().parent


def parse_k8s_id(resource_id) -> Optional[tuple]:
    """'<cluster>/<Kind>/<ns>/<name>' → (Kind, ns, name); '<cluster>/<Kind>/<name>' → (Kind, None, name)."""
    parts = resource_id.split("/") if isinstance(resource_id, str) else []
    if len(parts) not in (3, 4) or not all(parts):
        return None
    return (parts[1], parts[2], parts[3]) if len(parts) == 4 else (parts[1], None, parts[2])


def accept_keys(root_cause) -> set:
    return {(r["kind"], r.get("namespace"), r["name"]) for r in root_cause or []}


def dynamic_keys(case: dict, stdout: str, pod_nodes: dict) -> set:
    """The objects a case names only after its injection; a pattern that does not match adds nothing."""
    out = set()
    for d in case.get("root_cause_dynamic") or []:
        if "from_stdout" in d:
            m = re.search(d["from_stdout"], stdout or "")
            if m:
                out.add((d["kind"], None, m.group(1)))
        elif pod_nodes.get(d.get("from_pod_node")):
            out.add((d["kind"], None, pod_nodes[d["from_pod_node"]]))
    return out


def hit_rank(location, accept: set) -> Optional[int]:
    """The best rank among the stored candidates that are a root cause; None when none is."""
    ranks = [c["rank"] for c in (location or {}).get("candidates") or []
             if parse_k8s_id(c.get("resource_id")) in accept]
    return min(ranks) if ranks else None


def graph_recall(focus, ref_keys: dict, accept: set) -> bool:
    """Whether a root cause is within the focus neighbourhood; a truncated neighbourhood is a miss."""
    if not focus or focus.get("truncated"):
        return False
    return any(ref_keys.get(n["ref"]) in accept for n in focus.get("nodes") or [])


def load_cases(truth: list, scenarios: list) -> list:
    """The ground-truth entries with inject / restore / alert filled in from their scenario; the entry wins."""
    by_id = {s["id"]: s for s in scenarios}
    cases = []
    for entry in truth:
        case = dict(entry)
        if "scenario" in entry:
            if entry["scenario"] not in by_id:
                raise ValueError(f"{entry['id']}: no scenario {entry['scenario']!r}")
            s = by_id[entry["scenario"]]
            case.setdefault("inject", s["inject"])
            case.setdefault("restore", s["restore"])
            if "alert" not in case and "alert" in s.get("perceive", {}):
                case["alert"] = s["perceive"]["alert"]
        missing = [k for k in ("inject", "restore", "alert") if not case.get(k)]
        if missing or not (case.get("root_cause") or case.get("root_cause_dynamic")):
            raise ValueError(f"{entry['id']}: missing {', '.join(missing) or 'root_cause'}")
        cases.append(case)
    return cases


def load_default_cases() -> list:
    truth = yaml.safe_load((E2E_DIR / "ground_truth.yaml").read_text())
    scenarios = yaml.safe_load((E2E_DIR / "scenarios.yaml").read_text())
    return load_cases(truth, scenarios)


def summarize(runs: list) -> dict:
    """Per batch. Invalid runs (no new issue after every attempt) are counted but not scored; a rate is None
    when the batch has no valid run. `located`: the share whose stored location is valid or partial."""
    out = {}
    for batch in sorted({r["batch"] for r in runs}):
        mine = [r for r in runs if r["batch"] == batch]
        valid = [r for r in mine if r["valid"]]
        n = len(valid)

        def rate(hits):
            return round(hits / n, 4) if n else None

        out[batch] = {"runs": len(mine), "valid": n, "invalid": len(mine) - n,
                      "ac1": rate(sum(1 for r in valid if r["rank"] == 1)),
                      "ac3": rate(sum(1 for r in valid if r["rank"] is not None and r["rank"] <= 3)),
                      "mrr": rate(sum(1 / r["rank"] for r in valid if r["rank"])),
                      "located": rate(sum(1 for r in valid if r["location_status"] in ("valid", "partial"))),
                      "graph_recall": rate(sum(1 for r in valid if r["graph_recall"]))}
    return out


def _fmt(v) -> str:
    return "—" if v is None else f"{v:.2f}" if isinstance(v, float) else str(v)


def render(runs: list) -> str:
    batches = sorted({r["batch"] for r in runs})
    lines = ["| batch | runs | valid | invalid | AC@1 | AC@3 | MRR | located | graph recall |",
             "|---|---|---|---|---|---|---|---|---|"]
    for b, s in summarize(runs).items():
        lines.append(f"| {b} | {s['runs']} | {s['valid']} | {s['invalid']} | {_fmt(s['ac1'])} | {_fmt(s['ac3'])} | "
                     f"{_fmt(s['mrr'])} | {_fmt(s['located'])} | {_fmt(s['graph_recall'])} |")
    lines += ["", "| case | " + " | ".join(batches) + " |", "|---|" + "---|" * len(batches)]
    for case in dict.fromkeys(r["case"] for r in runs):
        cells = []
        for b in batches:
            r = next((r for r in runs if r["case"] == case and r["batch"] == b), None)
            cells.append("—" if r is None else "invalid" if not r["valid"]
                         else f"rank {_fmt(r['rank'])} · {r['location_status'] or 'no RCA'} · "
                              f"recall {'yes' if r['graph_recall'] else 'no'}")
        lines.append(f"| {case} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list) -> int:
    paths = argv or sorted(str(p) for p in (E2E_DIR / "results").glob("location-*.json"))
    runs = [r for p in paths for r in json.loads(Path(p).read_text())["runs"]]
    print(render(runs) if runs else "no location runs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
