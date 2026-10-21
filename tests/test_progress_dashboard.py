"""Progress dashboard generator (scripts/progress/build_dashboard.py).

The generator is a stand-alone script (stdlib + PyYAML, never imports agenticops), so these tests load
it from its file path and drive it two ways: its pure functions, and its CLI against a tiny fake repo
built under tmp_path. Run with ``--noconftest``: the root tests/conftest.py imports botocore and
agenticops, which the dashboard CI job (pyyaml + pytest only) does not install.

Contract these tests pin (the generator's public surface):

* CLI: ``build_dashboard.py [--root DIR] [--check | --verify [--strict] | --watch | --live --out PATH]``.
  ``--root`` defaults to the repo the script lives in; inputs are ``<root>/docs/progress/tracker.yaml``,
  docs under ``<root>/docs`` and ``<root>/src/agenticops``; output ``<root>/docs/progress/dashboard.html``.
  Exit codes: 0 ok, 1 ``--check`` stale / ``--verify --strict`` problems, 2 tracker validation failure
  (nothing written, the location named on stdout/stderr).
* ``validate_tracker(tracker: dict, root: Path) -> list[str]`` — one message per problem, naming the item id
  and the field.
* ``find_cycles(graph: dict[str, list[str]]) -> list[list[str]]`` — generic, for work items and modules.
* ``blocked_by(tracker: dict) -> dict[str, list[str]]`` — in_progress / todo items → their not-done upstreams.
* ``checkbox_stats(text: str) -> dict`` with ``checked`` / ``unchecked`` counts of markdown task boxes.
* ``parse_stage_table(text: str) -> dict[str, str]`` — a RELEASE doc's ``| 阶段 | … | 状态 |`` table, keyed by the
  stage's leading token (``S1``, ``A1``), value the status cell without markdown emphasis.
* ``compare_status(tracker_status: str, doc_status: str) -> "match" | "mismatch" | "unknown"`` —
  已验收 / 已完成 / 已发布 ≈ done, 未开始 ≈ todo, 移至 … ≈ moved; wording it cannot read is ``unknown``.
* ``find_inconsistencies(tracker: dict, root: Path) -> list[dict]`` — each ``{"item", "kind", …}``, kind one of
  ``plan_unchecked`` / ``release_mismatch`` / ``release_unknown`` / ``blocked`` / ``no_evidence``.
* ``module_dependencies(pkg_dir: Path) -> list[dict]`` — ``{"src", "dst", "count", "lazy"}`` aggregated to top-level
  packages (``services``) and modules (``models.py``); ``count`` = import statements, ``lazy`` = how many of
  them sit inside a function body.
* ``render(root: Path, live: bool = False) -> str`` — the HTML, a pure function of the repo's files.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "progress" / "build_dashboard.py"


@pytest.fixture(scope="module")
def bd():
    assert SCRIPT.is_file(), f"generator missing: {SCRIPT}"
    spec = importlib.util.spec_from_file_location("build_dashboard", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_dashboard"] = mod
    spec.loader.exec_module(mod)
    return mod


def run_cli(root: Path | None, *args: str, cwd: Path | None = None, env: dict | None = None):
    cmd = [sys.executable, str(SCRIPT)]
    if root is not None:
        cmd += ["--root", str(root)]
    cmd += list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                          cwd=str(cwd or REPO), env=env)
    proc.output = proc.stdout + proc.stderr
    return proc


# --------------------------------------------------------------------------------------------- fake repo

RELEASE_DOC = textwrap.dedent("""\
    # MVP-9.9.0

    | 阶段 | 内容 | 状态 |
    |---|---|---|
    | **S1 第一阶段** | 甲 | **已验收（2026-01-02）** |
    | S2 第二阶段 | 乙 | 未开始 |
    | S3 第三阶段 | 丙 | 正在和主人商量要不要做 |
    | S4 第四阶段 | 丁 | 未开始 |
    | A1 能力轨 | 戊 | 移至 MVP-9.9.1 |
    """)

PLAN_DOC = textwrap.dedent("""\
    # S1 plan

    - [x] step one
    - [X] step two
      - [ ] nested step left open
    - [ ] step three left open
    """)


def base_tracker() -> dict:
    return {
        "schema": 1,
        "updated": "2026-01-03",
        "releases": [
            {
                "id": "9.8.0", "title": "旧版本", "status": "released", "branch": "MVP-9.8.0", "tag": "v9.8.0",
                "doc": "docs/MVP-9.8.0-RELEASE.md",
                "items": [
                    {"id": "9.8.0/ALL", "title": "汇总", "status": "done", "depends_on": [],
                     "modules": ["models.py"], "evidence": {"docs": ["docs/MVP-9.8.0-RELEASE.md"]}},
                ],
            },
            {
                "id": "9.9.0", "title": "当前版本", "status": "in_progress", "branch": "MVP-9.9.0", "tag": "",
                "doc": "docs/MVP-9.9.0-RELEASE.md",
                "items": [
                    {"id": "9.9.0/S1", "title": "第一阶段", "status": "done", "depends_on": ["9.8.0/ALL"],
                     "modules": ["services/a", "web"], "plan": "docs/plans/s1.md",
                     "evidence": {"docs": ["docs/MVP-9.9.0-RELEASE.md"],
                                  "commits": [{"sha": "abc1234", "date": "2026-01-02", "title": "s1"}]}},
                    {"id": "9.9.0/S2", "title": "第二阶段", "status": "todo", "depends_on": ["9.9.0/S3"],
                     "modules": ["web"]},
                    {"id": "9.9.0/S3", "title": "第三阶段", "status": "in_progress", "depends_on": ["9.9.0/S1"],
                     "modules": ["services"]},
                    {"id": "9.9.0/S4", "title": "第四阶段", "status": "done", "depends_on": [],
                     "modules": ["models.py"]},
                    {"id": "9.9.0/A1", "title": "能力轨", "status": "moved", "moved_to": "9.9.1/A1",
                     "depends_on": [], "modules": []},
                ],
            },
            {
                "id": "9.9.1", "title": "下一版本", "status": "planned", "branch": "", "tag": "", "doc": "",
                "items": [
                    {"id": "9.9.1/A1", "title": "能力轨", "status": "todo", "depends_on": [], "modules": [],
                     "notes": "未从文档确认"},
                ],
            },
        ],
    }


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_pkg(src: Path, cyclic: bool = True) -> Path:
    """A small ``agenticops`` package: absolute, relative and lazy imports; services <-> web is the cycle."""
    pkg = src / "agenticops"
    write(pkg / "__init__.py", "")
    write(pkg / "models.py", "import os\nimport yaml\n")
    write(pkg / "config.py", "")
    write(pkg / "graph" / "__init__.py", "")
    write(pkg / "graph" / "engine.py", "from ..models import Base\n")
    write(pkg / "services" / "__init__.py", "")
    write(pkg / "services" / "b.py", "")
    write(pkg / "services" / "a.py", textwrap.dedent("""\
        import json
        import agenticops.models
        from ..models import HealthIssue
        from agenticops.config import settings
        from . import b
        from .b import thing
        from agenticops.web import app


        def later():
            from agenticops.graph import engine
            return engine
        """))
    write(pkg / "web" / "__init__.py", "")
    write(pkg / "web" / "app.py", "from agenticops.services.a import later\n" if cyclic else "import os\n")
    return pkg


def make_repo(root: Path, tracker: dict | None = None) -> Path:
    write(root / "docs" / "MVP-9.8.0-RELEASE.md", "# MVP-9.8.0\n\n已发布。\n")
    write(root / "docs" / "MVP-9.9.0-RELEASE.md", RELEASE_DOC)
    write(root / "docs" / "plans" / "s1.md", PLAN_DOC)
    make_pkg(root / "src")
    write_tracker(root, tracker if tracker is not None else base_tracker())
    return root


def write_tracker(root: Path, tracker: dict) -> None:
    write(root / "docs" / "progress" / "tracker.yaml", yaml.safe_dump(tracker, allow_unicode=True, sort_keys=False))


def item(tracker: dict, item_id: str) -> dict:
    for rel in tracker["releases"]:
        for it in rel["items"]:
            if it["id"] == item_id:
                return it
    raise KeyError(item_id)


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------------------------- script hygiene

def test_generator_uses_only_stdlib_and_pyyaml():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert "agenticops" not in roots
    allowed = set(sys.stdlib_module_names) | {"yaml", "__future__"}
    assert roots <= allowed, f"non-stdlib imports: {sorted(roots - allowed)}"


# --------------------------------------------------------------------------------------------- validation

def test_valid_tracker_has_no_errors(bd, repo):
    assert bd.validate_tracker(base_tracker(), repo) == []


def _mutations():
    def unknown_status(t):
        item(t, "9.9.0/S2")["status"] = "finished"
        return ["9.9.0/S2", "finished"]

    def unknown_release_status(t):
        t["releases"][1]["status"] = "shipping"
        return ["9.9.0", "shipping"]

    def missing_dep(t):
        item(t, "9.9.0/S2")["depends_on"] = ["9.9.0/S99"]
        return ["9.9.0/S2", "9.9.0/S99"]

    def cycle(t):
        item(t, "9.9.0/S1")["depends_on"] = ["9.9.0/S2"]  # S1 -> S2 -> S3 -> S1
        return ["9.9.0/S1", "9.9.0/S2", "9.9.0/S3"]

    def self_cycle(t):
        item(t, "9.9.0/S4")["depends_on"] = ["9.9.0/S4"]
        return ["9.9.0/S4"]

    def missing_module(t):
        item(t, "9.9.0/S3")["modules"] = ["services/nope"]
        return ["9.9.0/S3", "services/nope"]

    def moved_without_target(t):
        del item(t, "9.9.0/A1")["moved_to"]
        return ["9.9.0/A1", "moved_to"]

    def duplicate_id(t):
        t["releases"][2]["items"].append(dict(item(t, "9.9.0/S4")))
        return ["9.9.0/S4"]

    return {f.__name__: f for f in (unknown_status, unknown_release_status, missing_dep, cycle, self_cycle,
                                    missing_module, moved_without_target, duplicate_id)}


MUTATIONS = _mutations()


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_validate_tracker_names_the_problem(bd, repo, name):
    tracker = base_tracker()
    expected = MUTATIONS[name](tracker)
    errors = bd.validate_tracker(tracker, repo)
    assert errors, f"{name}: no error reported"
    joined = "\n".join(errors)
    for token in expected:
        assert token in joined, f"{name}: {token!r} not named in {errors!r}"


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_cli_fails_closed_with_exit_2_and_writes_nothing(repo, name):
    out = repo / "docs" / "progress" / "dashboard.html"
    assert run_cli(repo).returncode == 0
    before = out.read_bytes()
    tracker = base_tracker()
    expected = MUTATIONS[name](tracker)
    write_tracker(repo, tracker)
    proc = run_cli(repo)
    assert proc.returncode == 2, proc.output
    for token in expected:
        assert token in proc.output, f"{name}: {token!r} not named in output:\n{proc.output}"
    assert out.read_bytes() == before, "a failed validation must not rewrite dashboard.html"
    assert run_cli(repo, "--check").returncode == 2


def test_module_path_may_be_a_package_dir_or_a_module_file(bd, repo):
    tracker = base_tracker()
    item(tracker, "9.9.0/S3")["modules"] = ["services", "services/a", "graph/engine", "models.py", "config.py"]
    assert bd.validate_tracker(tracker, repo) == []


# --------------------------------------------------------------------------------------------- cycles / blocked

def test_find_cycles_detects_and_clears(bd):
    assert bd.find_cycles({"a": ["b"], "b": ["c"], "c": []}) == []
    cycles = bd.find_cycles({"a": ["b"], "b": ["c"], "c": ["a"], "d": ["a"]})
    assert any(set(c) == {"a", "b", "c"} for c in cycles), cycles
    assert not any("d" in c for c in cycles)
    assert any(set(c) == {"x"} for c in bd.find_cycles({"x": ["x"]}))


def test_blocked_by(bd):
    blocked = bd.blocked_by(base_tracker())
    assert blocked.get("9.9.0/S2") == ["9.9.0/S3"]  # todo, upstream in_progress
    assert "9.9.0/S3" not in blocked  # in_progress, upstream done
    assert "9.9.0/S1" not in blocked  # done items are never "blocked"


def test_blocked_by_lists_only_not_done_upstreams(bd):
    tracker = base_tracker()
    item(tracker, "9.9.0/S2")["depends_on"] = ["9.9.0/S1", "9.9.0/S3", "9.9.1/A1"]
    assert sorted(bd.blocked_by(tracker)["9.9.0/S2"]) == ["9.9.0/S3", "9.9.1/A1"]


# --------------------------------------------------------------------------------------------- reconciliation

def test_checkbox_stats(bd):
    stats = bd.checkbox_stats(PLAN_DOC)
    assert (stats["checked"], stats["unchecked"]) == (2, 2)
    empty = bd.checkbox_stats("# no boxes\n\n- plain bullet\n- [link](x)\n")
    assert (empty["checked"], empty["unchecked"]) == (0, 0)


def test_parse_stage_table(bd):
    table = bd.parse_stage_table(RELEASE_DOC)
    assert set(table) == {"S1", "S2", "S3", "S4", "A1"}
    assert "已验收" in table["S1"] and "**" not in table["S1"]
    assert table["S2"] == "未开始"


def test_parse_stage_table_without_a_table(bd):
    assert bd.parse_stage_table("# 没有阶段表\n\n正文。\n") == {}


@pytest.mark.parametrize("tracker_status, doc_status, verdict", [
    ("done", "已验收（2026-10-05）", "match"),
    ("done", "未开始", "mismatch"),
    ("todo", "已验收（2026-10-05）", "mismatch"),
    ("todo", "未开始", "match"),
    ("moved", "移至 MVP-2.7.1", "match"),
    ("done", "移至 MVP-2.7.1", "mismatch"),
    ("done", "正在和主人商量要不要做", "unknown"),
])
def test_compare_status(bd, tracker_status, doc_status, verdict):
    assert bd.compare_status(tracker_status, doc_status) == verdict


def _kinds(found):
    return {(f["item"], f["kind"]) for f in found}


def test_find_inconsistencies(bd, repo):
    kinds = _kinds(bd.find_inconsistencies(base_tracker(), repo))
    assert ("9.9.0/S1", "plan_unchecked") in kinds  # done, plan still has 2 open boxes
    assert ("9.9.0/S4", "release_mismatch") in kinds  # tracker done, doc 未开始
    assert ("9.9.0/S3", "release_unknown") in kinds  # doc wording unreadable → 无法比对, not a guess
    assert ("9.9.0/S2", "blocked") in kinds
    assert ("9.9.0/S4", "no_evidence") in kinds
    for clean in ("9.9.0/S1", "9.9.0/S2", "9.9.0/A1"):
        assert (clean, "release_mismatch") not in kinds and (clean, "release_unknown") not in kinds
    assert ("9.9.0/S1", "no_evidence") not in kinds
    assert ("9.8.0/ALL", "no_evidence") not in kinds


def test_inconsistencies_do_not_rewrite_tracker(repo):
    tracker_path = repo / "docs" / "progress" / "tracker.yaml"
    before = tracker_path.read_bytes()
    assert run_cli(repo).returncode == 0
    assert tracker_path.read_bytes() == before


def test_done_plan_with_all_boxes_ticked_is_clean(bd, repo):
    write(repo / "docs" / "plans" / "s1.md", "- [x] one\n- [x] two\n")
    assert ("9.9.0/S1", "plan_unchecked") not in _kinds(bd.find_inconsistencies(base_tracker(), repo))


def test_done_plan_that_never_ticks_a_box_is_not_flagged(bd, repo):
    """A plan whose boxes are all open does not track progress with them (13 of 23 findings on the real tracker
    were such plans); only a plan that ticks at least one box and leaves others open is flagged."""
    write(repo / "docs" / "plans" / "s1.md", "- [ ] one\n- [ ] two\n")
    assert ("9.9.0/S1", "plan_unchecked") not in _kinds(bd.find_inconsistencies(base_tracker(), repo))
    assert "一个框都没勾" in bd.render(repo)  # the page says why such a plan is not checked


# --------------------------------------------------------------------------------------------- code deps

def _edges(bd, pkg):
    return {(e["src"], e["dst"]): e for e in bd.module_dependencies(pkg)}


def test_module_dependencies(bd, tmp_path):
    edges = _edges(bd, make_pkg(tmp_path / "src"))
    # absolute `import agenticops.models` + relative `from ..models import` = two statements
    assert edges[("services", "models.py")]["count"] == 2
    assert not edges[("services", "models.py")]["lazy"]
    assert edges[("services", "config.py")]["count"] == 1  # from agenticops.config import
    assert edges[("services", "web")]["count"] == 1
    assert edges[("graph", "models.py")]["count"] == 1  # relative from a subpackage
    lazy = edges[("services", "graph")]
    assert lazy["count"] == 1 and lazy["lazy"] >= 1
    assert edges[("web", "services")]["count"] == 1
    names = {n for pair in edges for n in pair}
    assert not names & {"os", "json", "yaml"}, "only agenticops imports are edges"


def test_module_dependency_cycle(bd, tmp_path):
    def cross_graph(pkg):
        graph = {}
        for e in bd.module_dependencies(pkg):
            if e["src"] != e["dst"]:
                graph.setdefault(e["src"], []).append(e["dst"])
        return graph

    cycles = bd.find_cycles(cross_graph(make_pkg(tmp_path / "cyc" / "src")))
    assert any(set(c) == {"services", "web"} for c in cycles), cycles
    assert bd.find_cycles(cross_graph(make_pkg(tmp_path / "acyc" / "src", cyclic=False))) == []


def test_unparsable_file_is_listed_not_silently_dropped(bd, repo):
    pkg = repo / "src" / "agenticops"
    write(pkg / "services" / "broken.py", "def oops(:\n    from agenticops.web import app\n")
    unparsed = []
    edges = {(e["src"], e["dst"]): e for e in bd.module_dependencies(pkg, unparsed)}
    assert unparsed == ["services/broken.py"]
    assert edges[("services", "web")]["count"] == 1  # the broken file's import is not counted
    assert "<code>services/broken.py</code>" in bd.render(repo)


def test_module_labels_run_along_rays_and_fit(bd):
    """Adjacent labels are as far apart as their rays, and the longest label stays inside the viewBox."""
    real = bd.top_level_nodes(REPO / "src" / "agenticops")
    for nodes in (real, [f"module_{i:03d}.py" for i in range(80)]):
        radius, pos = bd.module_layout(nodes)
        step = 2 * math.pi / len(nodes)
        start = radius + bd.MOD_LABEL_GAP
        assert start * math.sin(step) >= bd.MOD_LABEL_PX + 2, (len(nodes), start * math.sin(step))
        longest = max(len(n) for n in nodes) * bd.MOD_CHAR_PX
        assert start + longest <= bd.MOD_SIZE / 2, (start, longest)
        for x, y, _a in pos.values():
            assert 0 < x < bd.MOD_SIZE and 0 < y < bd.MOD_SIZE


def _mod_views(html: str) -> tuple[str, str]:
    """The module graph's two views: top-level imports only (default) and with the lazy ones."""
    section = re.search(r'<section id="modgraph">(.*?)</section>', html, re.S).group(1)
    top, rest = section.split('id="mod-top"', 1)[1].split('id="mod-all"', 1)
    return top, rest


def _drawn(view: str) -> set:
    return set(re.findall(r'<path class="medge[^"]*" data-from="([^"]+)" data-to="([^"]+)"', view))


def test_module_graph_draws_top_level_imports_by_default(bd, repo):
    html = bd.render(repo)
    assert re.search(r'<input type="checkbox" id="m-lazy">', html)  # the toggle, off
    assert re.search(r'<div class="modview two" id="mod-top">', html)
    assert re.search(r'<div class="modview two" id="mod-all" hidden>', html)
    top, everything = _mod_views(html)
    assert ("services", "graph") not in _drawn(top)  # the fake package's one lazy-only import
    assert ("services", "graph") in _drawn(everything)
    assert ("services", "models.py") in _drawn(top) and ("services", "models.py") in _drawn(everything)
    assert ".modview[hidden]{display:none}" in html  # .two's display:grid would otherwise beat [hidden]


def test_module_graph_cycles_follow_the_view(bd, repo):
    """A cycle closed only by a function-body import is no load-time cycle: the default view draws no ring, the
    lazy view does — nodes, edges and the SCC list alike."""
    write(repo / "src" / "agenticops" / "web" / "app.py",
          "def handler():\n    from agenticops.services.a import later\n    return later\n")
    top, everything = _mod_views(bd.render(repo))
    assert "<li>无</li>" in top and 'class="medge cyc"' not in top
    assert 'fill="#DC2626"' not in top
    assert "services、web" in everything and 'class="medge cyc"' in everything
    assert re.search(r'<g class="mnode" data-id="web"><title>[^<]*</title><circle [^>]*fill="#DC2626"', everything)


def test_module_dependencies_on_the_real_package(bd):
    edges = _edges(bd, REPO / "src" / "agenticops")
    assert ("services", "models.py") in edges
    assert all(e["count"] >= 1 for e in edges.values())


# --------------------------------------------------------------------------------------------- render / CLI

def test_render_is_deterministic(bd, repo):
    assert bd.render(repo) == bd.render(repo)


def test_cli_build_is_byte_identical_across_runs_cwd_and_tz(repo, tmp_path):
    out = repo / "docs" / "progress" / "dashboard.html"
    assert run_cli(repo).returncode == 0
    first = sha256(out)
    env = dict(os.environ, TZ="Asia/Shanghai")
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    assert run_cli(repo, cwd=other_cwd, env=env).returncode == 0
    assert sha256(out) == first


def test_render_content(bd, repo):
    html = bd.render(repo)
    tracker = base_tracker()
    assert "2026-01-03" in html  # tracker.updated
    for rel in tracker["releases"]:
        for it in rel["items"]:
            assert it["id"] in html
    assert "无法比对" in html
    assert "docs/plans/s1.md" in html
    assert "未从文档确认" in html  # notes are shown
    assert "prefers-reduced-motion" in html
    assert 'http-equiv="refresh"' not in html
    assert '<link rel="icon" href="data:,">' in html  # no /favicon.ico request when the page is served


def test_every_module_node_is_a_filter_option(bd, repo):
    """A click on a module node sets the module filter to it; a node no item names must still be an option, so
    the list shows 0 rows instead of silently falling back to all of them."""
    html = bd.render(repo)
    nodes = set(re.findall(r'<g class="mnode" data-id="([^"]+)"', html))
    select = re.search(r'<select id="f-module">(.*?)</select>', html).group(1)
    options = set(re.findall(r'<option value="([^"]+)"', select))
    assert "config.py" in nodes and "graph" in nodes  # no item of the fake tracker names these
    assert nodes <= options, sorted(nodes - options)
    assert "fm.value=id;" in html


def test_work_graph_arcs_stay_inside_the_viewbox(bd, repo):
    """A same-column dependency arcs out to the right of its column; in the last column that must not be cut
    off by the viewBox (the 2.7.1 A1 → A2 / A3 / A4 waits are exactly such arcs)."""
    tracker = base_tracker()
    tracker["releases"][2]["items"].append({"id": "9.9.1/A2", "title": "下一步", "status": "todo",
                                            "depends_on": ["9.9.1/A1"], "modules": []})
    write_tracker(repo, tracker)
    html = bd.render(repo)
    svg = re.search(r'<svg viewBox="0 0 (\d+) (\d+)" role="img" aria-label="工作项依赖图">(.*?)</svg>', html, re.S)
    width = int(svg.group(1))
    paths = re.findall(r'<path class="wedge[^"]*" data-from="9.9.1/A1" data-to="9.9.1/A2" d="([^"]+)"', svg.group(3))
    assert paths, "the same-column edge is drawn"
    xs = [float(x) for x in re.findall(r"(-?\d+(?:\.\d+)?),", paths[0])]
    assert max(xs) <= width, (max(xs), width)


EXTERNAL_REF = re.compile(
    r"""(?:\b(?:src|href)\s*=\s*["']?\s*https?://)"""
    r"""|(?:url\(\s*["']?\s*https?://)"""
    r"""|(?:@import\s+(?:url\()?\s*["']?\s*https?://)""",
    re.IGNORECASE,
)


def _assert_self_contained(html: str) -> None:
    assert not EXTERNAL_REF.search(html), EXTERNAL_REF.search(html).group(0)
    assert not re.search(r"<script[^>]*\bsrc\s*=", html, re.IGNORECASE)
    assert not re.search(r"<link[^>]*rel\s*=\s*[\"']?stylesheet", html, re.IGNORECASE)
    for api in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert api not in html, api


def test_html_is_self_contained(bd, repo):
    # the pattern itself must catch every reference form it claims to
    for bad in ('<img src="https://x/y.png">', "<a href='http://x'>", "background: url(https://x/f.woff)",
                '@import "https://fonts.example/css";', "@import url(http://x.css);"):
        assert EXTERNAL_REF.search(bad), bad
    assert not EXTERNAL_REF.search('<a href="docs/MVP-2.7.0-RELEASE.md">')

    _assert_self_contained(bd.render(repo))
    tracker = base_tracker()
    item(tracker, "9.9.0/S3")["notes"] = 'see <img src="https://evil.example/x.png">'
    write_tracker(repo, tracker)
    _assert_self_contained(bd.render(repo))  # tracker text is escaped, never a live reference


def test_check_exit_codes(repo):
    out = repo / "docs" / "progress" / "dashboard.html"
    assert not out.exists()
    assert run_cli(repo, "--check").returncode == 1  # never built
    assert run_cli(repo).returncode == 0
    fresh = run_cli(repo, "--check")
    assert fresh.returncode == 0, fresh.output

    tracker = base_tracker()
    item(tracker, "9.9.0/S2")["title"] = "第二阶段（改名）"
    write_tracker(repo, tracker)
    stale = run_cli(repo, "--check")
    assert stale.returncode == 1, stale.output
    assert stale.output.strip(), "--check prints a diff summary"

    assert run_cli(repo).returncode == 0
    assert run_cli(repo, "--check").returncode == 0


def test_check_notices_source_and_doc_changes(repo):
    assert run_cli(repo).returncode == 0
    write(repo / "src" / "agenticops" / "config.py", "from agenticops.graph import engine\n")
    assert run_cli(repo, "--check").returncode == 1
    assert run_cli(repo).returncode == 0
    write(repo / "docs" / "plans" / "s1.md", "- [x] all done\n")
    assert run_cli(repo, "--check").returncode == 1


def test_check_does_not_write(repo):
    out = repo / "docs" / "progress" / "dashboard.html"
    assert run_cli(repo).returncode == 0
    write_tracker(repo, {**base_tracker(), "updated": "2026-01-04"})
    before = out.read_bytes()
    assert run_cli(repo, "--check").returncode == 1
    assert out.read_bytes() == before


def test_live_output_refreshes_and_leaves_committed_page_alone(repo, tmp_path):
    out = repo / "docs" / "progress" / "dashboard.html"
    assert run_cli(repo).returncode == 0
    before = out.read_bytes()
    live = tmp_path / "live" / "dash.html"
    live.parent.mkdir()
    proc = run_cli(repo, "--live", "--out", str(live))
    assert proc.returncode == 0, proc.output
    text = live.read_text(encoding="utf-8")
    assert re.search(r'<meta\s+http-equiv="refresh"\s+content="5"', text)
    assert out.read_bytes() == before
    assert 'http-equiv="refresh"' not in out.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------- --verify (git)

def _git(root: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True,
                          env=env).stdout.strip()


@pytest.fixture
def git_repo(repo):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e", GIT_AUTHOR_DATE="2026-01-02T12:00:00+00:00",
               GIT_COMMITTER_DATE="2026-01-02T12:00:00+00:00")
    _git(repo, "init", "-q", env=env)
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "s1", env=env)
    sha = _git(repo, "rev-parse", "--short=7", "HEAD")
    tracker = base_tracker()
    item(tracker, "9.9.0/S1")["evidence"]["commits"] = [
        {"sha": sha, "date": "2026-01-02", "title": "s1"},
        {"sha": "0000000", "date": "2026-01-02", "title": "never made"},
    ]
    item(tracker, "9.8.0/ALL")["evidence"]["commits"] = [{"sha": sha, "date": "2025-12-31", "title": "s1"}]
    write_tracker(repo, tracker)
    return repo, sha


def _snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def test_verify_reports_and_only_warns(git_repo):
    repo, sha = git_repo
    before = _snapshot(repo)
    proc = run_cli(repo, "--verify")
    assert proc.returncode == 0, proc.output
    assert "0000000" in proc.output  # a SHA that does not exist
    assert "2025-12-31" in proc.output  # tracker date disagrees with the commit date
    assert "9.9.0/S4" in proc.output  # done without evidence
    assert _snapshot(repo) == before, "--verify must not write any file"


def test_verify_uses_the_committer_date_and_checks_titles(git_repo):
    """The tracker records the 提交日期 (committer date): an author date that differs is a problem, and so is a
    title that is not the commit's subject."""
    repo, _ = git_repo
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e", GIT_AUTHOR_DATE="2025-11-30T12:00:00+00:00",
               GIT_COMMITTER_DATE="2026-01-05T12:00:00+00:00")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "rebased later", env=env)
    sha = _git(repo, "rev-parse", "--short=7", "HEAD")
    tracker = base_tracker()
    for it_id in ("9.9.0/S1", "9.8.0/ALL", "9.9.0/S4"):
        item(tracker, it_id).setdefault("evidence", {})["commits"] = [
            {"sha": sha, "date": "2026-01-05", "title": "rebased later"}]
    write_tracker(repo, tracker)
    clean = run_cli(repo, "--verify", "--strict")
    assert clean.returncode == 0, clean.output

    item(tracker, "9.9.0/S1")["evidence"]["commits"] = [{"sha": sha, "date": "2025-11-30", "title": "rebased later"}]
    item(tracker, "9.9.0/S4")["evidence"]["commits"] = [{"sha": sha, "date": "2026-01-05", "title": "rebased"}]
    write_tracker(repo, tracker)
    proc = run_cli(repo, "--verify", "--strict")
    assert proc.returncode == 1
    assert "9.9.0/S1" in proc.output and "2025-11-30" in proc.output  # the author date is not the commit date
    assert "9.9.0/S4" in proc.output and "'rebased'" in proc.output  # truncated title


def test_verify_strict_fails_on_problems(git_repo):
    repo, _ = git_repo
    assert run_cli(repo, "--verify", "--strict").returncode == 1


def test_verify_strict_passes_when_clean(git_repo):
    repo, sha = git_repo
    tracker = base_tracker()
    for it_id in ("9.9.0/S1", "9.8.0/ALL", "9.9.0/S4"):
        item(tracker, it_id).setdefault("evidence", {})["commits"] = [{"sha": sha, "date": "2026-01-02",
                                                                      "title": "s1"}]
    write_tracker(repo, tracker)
    proc = run_cli(repo, "--verify", "--strict")
    assert proc.returncode == 0, proc.output


def test_html_does_not_depend_on_git(bd, git_repo):
    """git facts (does a SHA exist, HEAD, branch) belong to --verify only: the page is the same with or without
    the history, so committing it never makes --check fail on a clone that fetched other commits."""
    repo, _ = git_repo
    with_git = bd.render(repo)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "later",
         env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                  GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e"))
    assert bd.render(repo) == with_git
    shutil.rmtree(repo / ".git")
    assert bd.render(repo) == with_git


# --------------------------------------------------------------------------------------------- the real repo

REAL_TRACKER = REPO / "docs" / "progress" / "tracker.yaml"


@pytest.fixture(scope="module")
def real_tracker():
    assert REAL_TRACKER.is_file(), f"missing {REAL_TRACKER}"
    return yaml.safe_load(REAL_TRACKER.read_text(encoding="utf-8"))


def _real_items(tracker):
    return {it["id"]: it for rel in tracker["releases"] for it in rel["items"]}


def test_real_tracker_validates(bd, real_tracker):
    assert real_tracker["schema"] == 1
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(real_tracker["updated"]))
    assert bd.validate_tracker(real_tracker, REPO) == []


def test_real_tracker_covers_every_release_doc(real_tracker):
    releases = {r["id"]: r for r in real_tracker["releases"]}
    docs = sorted((REPO / "docs").glob("MVP-*-RELEASE.md"))
    assert docs
    for doc in docs:
        version = re.match(r"MVP-(.+)-RELEASE\.md", doc.name).group(1)
        assert version in releases, f"{doc.name} has no release in tracker"
        assert releases[version]["items"], version


def test_real_tracker_2_6_1_is_split_by_plan(real_tracker):
    rel = next(r for r in real_tracker["releases"] if r["id"] == "2.6.1")
    plans = {it.get("plan") for it in rel["items"]}
    for p in sorted((REPO / "docs" / "superpowers" / "plans").glob("2026-09-28-mvp-2.6.1-plan-*.md")):
        assert p.relative_to(REPO).as_posix() in plans, p.name


def test_real_tracker_2_7_0_and_2_7_1(real_tracker):
    items = _real_items(real_tracker)
    releases = {r["id"]: r for r in real_tracker["releases"]}
    assert releases["2.7.0"]["status"] == "released"
    assert releases["2.7.0"].get("tag") == "v2.7.0"
    for s in range(1, 8):
        assert items[f"2.7.0/S{s}"]["status"] == "done", f"S{s}"
    for a in range(1, 5):
        moved = items[f"2.7.0/A{a}"]
        assert moved["status"] == "moved" and moved["moved_to"] == f"2.7.1/A{a}"
    assert releases["2.7.1"]["status"] == "in_progress"
    assert sorted(it["id"] for it in releases["2.7.1"]["items"]) == [f"2.7.1/A{a}" for a in range(1, 5)]
    assert all(it["status"] == "todo" for it in releases["2.7.1"]["items"])
    deps = {it["id"]: set(it.get("depends_on") or []) for it in releases["2.7.1"]["items"]}
    assert {"2.7.1/A1"} <= deps["2.7.1/A2"]
    assert {"2.7.1/A1"} <= deps["2.7.1/A3"]
    assert {"2.7.1/A1", "2.7.1/A2", "2.7.1/A3"} <= deps["2.7.1/A4"]


def _is_full_clone() -> bool:
    if shutil.which("git") is None:
        return False
    try:
        return _git(REPO, "rev-parse", "--is-shallow-repository") == "false"
    except subprocess.CalledProcessError:
        return False


@pytest.mark.skipif(not _is_full_clone(), reason="needs a full git clone (CI: fetch-depth 0)")
def test_real_tracker_commits_exist_with_their_dates(real_tracker):
    for it in _real_items(real_tracker).values():
        for c in (it.get("evidence") or {}).get("commits") or []:
            sha = str(c["sha"])
            ok = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=REPO,
                                capture_output=True).returncode == 0
            assert ok, f"{it['id']}: commit {sha} not in git"
            date, subject = _git(REPO, "log", "-1", "--format=%cs%n%s", sha).split("\n", 1)
            assert str(c["date"]) == date, f"{it['id']}: {sha} date {c['date']} vs git commit date {date}"
            if c.get("title"):
                assert str(c["title"]) == subject, f"{it['id']}: {sha} title vs git subject {subject!r}"


def test_real_dashboard_is_current_and_self_contained():
    proc = run_cli(None, "--check")
    assert proc.returncode == 0, proc.output
    html = (REPO / "docs" / "progress" / "dashboard.html").read_text(encoding="utf-8")
    _assert_self_contained(html)
    assert 'http-equiv="refresh"' not in html
