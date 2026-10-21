#!/usr/bin/env python3
"""Build the development progress dashboard (docs/progress/dashboard.html) from docs/progress/tracker.yaml.

The page is a pure function of files in the repo — the tracker, the docs it points at and the sources under
src/agenticops — so committing it never makes ``--check`` fail elsewhere: no clock, no HEAD, no branch, no live
``git log``. git facts (does an evidence SHA exist, does its date agree) are ``--verify``'s, printed to stdout only.

Stand-alone on purpose: stdlib + PyYAML, never ``import agenticops`` (the CI job installs pyyaml + pytest only);
code-module dependencies come from parsing the sources with ``ast``.

Usage:
    build_dashboard.py [--root DIR]                 write docs/progress/dashboard.html
    build_dashboard.py --check                      exit 1 when the committed page is stale
    build_dashboard.py --verify [--strict]          git consistency report (stdout; --strict exits 1 on problems)
    build_dashboard.py --watch [--live --out PATH]  rebuild whenever the tracker, docs or sources change
    build_dashboard.py --live [--out PATH]          a self-refreshing copy outside the repo (never the committed page)

Exit codes: 0 ok · 1 stale (--check) / problems (--verify --strict) · 2 tracker validation failed (nothing written).
"""

from __future__ import annotations

import argparse
import ast
import difflib
import html
import math
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

TRACKER_REL = Path("docs/progress/tracker.yaml")
OUTPUT_REL = Path("docs/progress/dashboard.html")
PKG_REL = Path("src/agenticops")
DEFAULT_LIVE_OUT = Path("/tmp/agenticops-progress-dashboard.html")

RELEASE_STATUSES = ("released", "in_progress", "planned")
ITEM_STATUSES = ("done", "in_progress", "todo", "blocked", "moved", "dropped")
OPEN_STATUSES = ("in_progress", "todo", "blocked")  # an item that can be waiting on someone

STATUS_LABEL = {
    "done": "已完成", "in_progress": "进行中", "todo": "待做", "blocked": "阻塞", "moved": "已移出",
    "dropped": "已放弃", "released": "已发布", "planned": "计划中",
}
KIND_LABEL = {
    "plan_unchecked": "计划仍有未勾选",
    "plan_missing": "计划文件不存在",
    "release_mismatch": "与 RELEASE 阶段表矛盾",
    "release_unknown": "无法比对",
    "blocked": "被谁卡住",
    "no_evidence": "done 无证据",
    "evidence_missing": "证据文件不存在",
}


class TrackerError(Exception):
    """The tracker failed validation; ``errors`` names each location."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


# --------------------------------------------------------------------------------------------- tracker

def load_tracker(root: Path) -> dict:
    path = root / TRACKER_REL
    if not path.is_file():
        raise TrackerError([f"{TRACKER_REL}: file not found"])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TrackerError([f"{TRACKER_REL}: YAML error: {exc}"]) from exc
    if not isinstance(data, dict):
        raise TrackerError([f"{TRACKER_REL}: top level must be a mapping"])
    return data


def iter_items(tracker: dict):
    """(release, item) pairs in tracker order; tolerant of malformed shapes (validation reports those)."""
    for rel in tracker.get("releases") or []:
        if not isinstance(rel, dict):
            continue
        for it in rel.get("items") or []:
            if isinstance(it, dict):
                yield rel, it


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def module_exists(root: Path, module: str) -> bool:
    """A module path relative to src/agenticops: a directory, a ``.py`` file, or a module with ``.py`` omitted."""
    rel = str(module).strip().strip("/")
    if not rel or ".." in Path(rel).parts:
        return False
    base = root / PKG_REL / rel
    return base.is_dir() or (base.is_file() and base.suffix == ".py") or base.with_name(base.name + ".py").is_file()


def find_cycles(graph: dict) -> list[list[str]]:
    """Strongly connected components that are cycles (size > 1, or a node that points at itself); deterministic."""
    nodes = sorted(set(graph) | {d for deps in graph.values() for d in deps})
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0

    for start in nodes:
        if start in index:
            continue
        # iterative Tarjan: (node, iterator over its successors)
        work = [(start, iter(sorted(set(graph.get(start, ())))))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, succ = work[-1]
            advanced = False
            for nxt in succ:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(set(graph.get(nxt, ()))))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    top = stack.pop()
                    on_stack.discard(top)
                    comp.append(top)
                    if top == node:
                        break
                if len(comp) > 1 or node in graph.get(node, ()):
                    out.append(sorted(comp))
    return sorted(out)


def validate_tracker(tracker: dict, root: Path) -> list[str]:
    """Every problem that makes the tracker unusable, one message each, naming the item id and field."""
    errors: list[str] = []
    if not isinstance(tracker, dict):
        return ["tracker: top level must be a mapping"]
    if tracker.get("schema") != 1:
        errors.append(f"schema: expected 1, got {tracker.get('schema')!r}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(tracker.get("updated", ""))):
        errors.append(f"updated: expected \"YYYY-MM-DD\", got {tracker.get('updated')!r}")
    releases = tracker.get("releases")
    if not isinstance(releases, list) or not releases:
        return errors + ["releases: must be a non-empty list"]

    seen_releases: set[str] = set()
    ids: dict[str, str] = {}  # item id -> location of its first definition
    for ri, rel in enumerate(releases):
        loc = f"releases[{ri}]"
        if not isinstance(rel, dict):
            errors.append(f"{loc}: must be a mapping")
            continue
        rid = str(rel.get("id", ""))
        loc = f"{loc} (release {rid})"
        if not rid:
            errors.append(f"{loc}.id: missing")
        elif rid in seen_releases:
            errors.append(f"{loc}.id: duplicate release id {rid}")
        seen_releases.add(rid)
        if rel.get("status") not in RELEASE_STATUSES:
            errors.append(f"{loc}.status: {rel.get('status')!r} not in {list(RELEASE_STATUSES)}")
        items = rel.get("items")
        if not isinstance(items, list):
            errors.append(f"{loc}.items: must be a list")
            continue
        for ii, it in enumerate(items):
            iloc = f"releases[{ri}].items[{ii}]"
            if not isinstance(it, dict):
                errors.append(f"{iloc}: must be a mapping")
                continue
            iid = str(it.get("id", ""))
            iloc = f"{iloc} (item {iid})"
            if not iid:
                errors.append(f"{iloc}.id: missing")
            elif iid in ids:
                errors.append(f"{iloc}.id: duplicate id {iid} (first defined at {ids[iid]})")
            else:
                ids[iid] = iloc
            if not it.get("title"):
                errors.append(f"{iloc}.title: missing")
            status = it.get("status")
            if status not in ITEM_STATUSES:
                errors.append(f"{iloc}.status: {status!r} not in {list(ITEM_STATUSES)}")
            if status == "moved" and not it.get("moved_to"):
                errors.append(f"{iloc}.moved_to: required when status is moved")
            for mod in _as_list(it.get("modules")):
                if not module_exists(root, mod):
                    errors.append(f"{iloc}.modules: {mod} does not exist under {PKG_REL.as_posix()}")
            evidence = it.get("evidence") or {}
            if not isinstance(evidence, dict):
                errors.append(f"{iloc}.evidence: must be a mapping")
            else:
                for ci, c in enumerate(_as_list(evidence.get("commits"))):
                    if not isinstance(c, dict) or not c.get("sha") or not c.get("date"):
                        errors.append(f"{iloc}.evidence.commits[{ci}]: needs sha and date")
                    elif not re.fullmatch(r"[0-9a-fA-F]{7,40}", str(c["sha"])):
                        errors.append(f"{iloc}.evidence.commits[{ci}].sha: {c['sha']!r} is not a commit SHA")
                    elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c["date"])):
                        errors.append(f"{iloc}.evidence.commits[{ci}].date: {c['date']!r} is not YYYY-MM-DD")

    graph: dict[str, list[str]] = {}
    for _rel, it in iter_items(tracker):
        iid = str(it.get("id", ""))
        deps = [str(d) for d in _as_list(it.get("depends_on"))]
        for dep in deps:
            if dep not in ids:
                errors.append(f"{ids.get(iid, iid)}.depends_on: {dep} does not exist")
        graph.setdefault(iid, []).extend(d for d in deps if d in ids)
        moved_to = it.get("moved_to")
        if moved_to and str(moved_to) not in ids:
            errors.append(f"{ids.get(iid, iid)}.moved_to: {moved_to} does not exist")
    for cycle in find_cycles(graph):
        errors.append("depends_on: dependency cycle among " + ", ".join(f"{ids[c]}" for c in cycle))
    return errors


def blocked_by(tracker: dict) -> dict[str, list[str]]:
    """Open items (in_progress / todo / blocked) → their upstreams that are not done."""
    status = {str(it.get("id")): it.get("status") for _r, it in iter_items(tracker)}
    out: dict[str, list[str]] = {}
    for _rel, it in iter_items(tracker):
        if it.get("status") not in OPEN_STATUSES:
            continue
        waiting = [str(d) for d in _as_list(it.get("depends_on")) if status.get(str(d)) != "done"]
        if waiting:
            out[str(it["id"])] = waiting
    return out


# --------------------------------------------------------------------------------------------- reconciliation

CHECKBOX = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[([ xX])\]", re.MULTILINE)


def checkbox_stats(text: str) -> dict:
    marks = CHECKBOX.findall(text)
    checked = sum(1 for m in marks if m in "xX")
    return {"checked": checked, "unchecked": len(marks) - checked}


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _plain(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.replace("**", "").replace("__", "")).strip()


STAGE_KEY = re.compile(r"^([A-Z]+\d+)(?![\w.])")


def parse_stage_table(text: str) -> dict[str, str]:
    """A RELEASE doc's stage table (a header naming 阶段 and 状态): stage key (``S1``) → plain status cell.

    The first row for a key wins; rows whose first cell does not start with a stage key are skipped."""
    lines = text.splitlines()
    table: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*",
                                                                                  lines[i + 1]):
            header = [_plain(c) for c in _cells(line)]
            stage_col = next((n for n, h in enumerate(header) if "阶段" in h), None)
            status_col = next((n for n, h in enumerate(header) if "状态" in h), None)
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                if stage_col is not None and status_col is not None:
                    cells = _cells(lines[i])
                    if len(cells) > max(stage_col, status_col):
                        m = STAGE_KEY.match(_plain(cells[stage_col]))
                        if m and m.group(1) not in table:
                            table[m.group(1)] = _plain(cells[status_col])
                i += 1
            continue
        i += 1
    return table


def doc_status_class(doc_status: str) -> str | None:
    """The tracker status a RELEASE doc's wording means, or None when it cannot be read without guessing."""
    if "移至" in doc_status:
        return "moved"
    if any(w in doc_status for w in ("已验收", "已完成", "已发布")):
        return "done"
    if "未开始" in doc_status:
        return "todo"
    if "进行中" in doc_status:
        return "in_progress"
    return None


def compare_status(tracker_status: str, doc_status: str) -> str:
    cls = doc_status_class(doc_status)
    if cls is None:
        return "unknown"
    return "match" if cls == tracker_status else "mismatch"


def _read(root: Path, rel: str) -> str | None:
    path = root / rel
    if not rel or ".." in Path(rel).parts or not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def find_inconsistencies(tracker: dict, root: Path) -> list[dict]:
    """Non-blocking findings, in tracker order. Never rewrites the tracker."""
    found: list[dict] = []
    stage_tables: dict[str, dict] = {}
    blocked = blocked_by(tracker)
    for rel, it in iter_items(tracker):
        iid = str(it.get("id"))
        status = it.get("status")
        plan = it.get("plan")
        if plan:
            text = _read(root, str(plan))
            if text is None:
                found.append({"item": iid, "kind": "plan_missing", "detail": f"{plan} 不在仓库中"})
            elif status == "done":
                stats = checkbox_stats(text)
                if stats["checked"] and stats["unchecked"]:  # a plan that ticks no box does not track with them
                    found.append({"item": iid, "kind": "plan_unchecked", "plan": str(plan), **stats,
                                  "detail": f"{plan}：已勾选 {stats['checked']}，未勾选 {stats['unchecked']}"})
        doc = rel.get("doc")
        if doc:
            if doc not in stage_tables:
                text = _read(root, str(doc))
                stage_tables[doc] = parse_stage_table(text) if text is not None else {}
            key = iid.rsplit("/", 1)[-1]
            doc_status = stage_tables[doc].get(key)
            if doc_status is not None:
                verdict = compare_status(str(status), doc_status)
                if verdict == "mismatch":
                    found.append({"item": iid, "kind": "release_mismatch", "doc": str(doc), "doc_status": doc_status,
                                  "detail": f"tracker {status}，{doc} 写「{doc_status}」"})
                elif verdict == "unknown":
                    found.append({"item": iid, "kind": "release_unknown", "doc": str(doc), "doc_status": doc_status,
                                  "detail": f"tracker {status}，{doc} 写「{doc_status}」（无法比对）"})
        if iid in blocked:
            found.append({"item": iid, "kind": "blocked", "upstream": blocked[iid],
                          "detail": "等待 " + "、".join(blocked[iid])})
        evidence = it.get("evidence") or {}
        docs = [str(d) for d in _as_list(evidence.get("docs"))]
        commits = _as_list(evidence.get("commits"))
        if status == "done" and not docs and not commits:
            found.append({"item": iid, "kind": "no_evidence", "detail": "状态 done，但没有任何证据（docs / commits）"})
        for d in docs:
            if _read(root, d) is None and not (root / d).is_dir():
                found.append({"item": iid, "kind": "evidence_missing", "detail": f"{d} 不在仓库中"})
    return found


# --------------------------------------------------------------------------------------------- code modules

def top_level_nodes(pkg_dir: Path) -> list[str]:
    """Top-level packages (directories holding Python) and modules (``models.py``) of the package."""
    nodes = []
    for child in sorted(pkg_dir.iterdir()):
        if child.name.startswith((".", "__pycache__")):
            continue
        if child.is_dir() and any(child.rglob("*.py")):
            nodes.append(child.name)
        elif child.is_file() and child.suffix == ".py":
            nodes.append(child.name)
    return nodes


def _top_of(pkg_dir: Path, parts: list[str]) -> str | None:
    """``["services", "a"]`` → ``services``; ``["models"]`` → ``models.py``."""
    if not parts:
        return None
    head = parts[0]
    if (pkg_dir / head).is_dir():
        return head
    if (pkg_dir / f"{head}.py").is_file():
        return f"{head}.py"
    return None


class _ImportCollector(ast.NodeVisitor):
    def __init__(self):
        self.found: list[tuple[ast.stmt, bool]] = []
        self._depth = 0

    def _function(self, node):
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _function

    def visit_Import(self, node):
        self.found.append((node, self._depth > 0))

    def visit_ImportFrom(self, node):
        self.found.append((node, self._depth > 0))


def _targets(stmt, pkg_name: str, module_parts: list[str], is_init: bool) -> list[list[str]]:
    """Dotted paths below the package root that one import statement reaches."""
    out: list[list[str]] = []
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            parts = alias.name.split(".")
            if parts[0] == pkg_name and len(parts) > 1:
                out.append(parts[1:])
        return out
    if stmt.level:
        package = module_parts if is_init else module_parts[:-1]  # parts below the root
        up = stmt.level - 1
        if up > len(package):
            return out  # beyond the root
        base = package[:len(package) - up] if up else list(package)
        mod = stmt.module.split(".") if stmt.module else []
        full = base + mod
    else:
        if not stmt.module:
            return out
        parts = stmt.module.split(".")
        if parts[0] != pkg_name:
            return out
        full = parts[1:]
    if full:
        out.append(full)
    else:  # `from agenticops import config` / `from . import x` at the root: each name is a module
        out.extend([alias.name] for alias in stmt.names if alias.name != "*")
    return out


def module_dependencies(pkg_dir: Path, unparsed: list[str] | None = None) -> list[dict]:
    """Import edges between top-level packages / modules: ``{"src", "dst", "count", "lazy"}``, sorted.

    ``count`` = import statements (absolute, relative, inside functions), ``lazy`` = how many of them sit in a
    function body. A statement naming several modules of one destination counts once; self-edges are dropped.
    A file ``ast`` cannot parse adds no edges; its path (relative to ``pkg_dir``) is appended to ``unparsed`` so
    the page says so instead of silently drawing a smaller graph."""
    pkg_dir = Path(pkg_dir)
    pkg_name = pkg_dir.name
    edges: dict[tuple[str, str], dict] = {}
    for path in sorted(pkg_dir.rglob("*.py")):
        rel = path.relative_to(pkg_dir)
        if any(p.startswith(".") or p == "__pycache__" for p in rel.parts):
            continue
        src = rel.parts[0] if len(rel.parts) > 1 else rel.name
        module_parts = list(rel.with_suffix("").parts)
        is_init = module_parts[-1] == "__init__"
        if is_init:
            module_parts = module_parts[:-1]
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except (SyntaxError, ValueError):  # ValueError: a NUL byte in the source
            if unparsed is not None:
                unparsed.append(rel.as_posix())
            continue
        collector = _ImportCollector()
        collector.visit(tree)
        for stmt, lazy in collector.found:
            dsts = {_top_of(pkg_dir, t) for t in _targets(stmt, pkg_name, module_parts, is_init)}
            for dst in sorted(d for d in dsts if d and d != src):
                e = edges.setdefault((src, dst), {"src": src, "dst": dst, "count": 0, "lazy": 0})
                e["count"] += 1
                e["lazy"] += int(lazy)
    return [edges[k] for k in sorted(edges)]


# --------------------------------------------------------------------------------------------- HTML

def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def esc_text(value) -> str:
    """Free text from the tracker: escaped, and ``/`` as an entity so no URL in it can read as a reference."""
    return esc(value).replace("/", "&#47;")


def link(path: str) -> str:
    """A repo-relative path as a link from docs/progress/dashboard.html."""
    path = str(path)
    return f'<a href="../../{esc(path)}"><code>{esc(path)}</code></a>'


def badge(status: str) -> str:
    return f'<span class="badge st-{esc(status)}">{esc(STATUS_LABEL.get(status, status))}</span>'


CSS = """
:root{--primary:#2563EB;--bg:#F8FAFC;--text:#0F172A;--muted:#64748B;--line:#E2E8F0;--card:#FFFFFF;
--done:#16A34A;--prog:#2563EB;--todo:#94A3B8;--blocked:#DC2626;--moved:#A855F7;--dropped:#CBD5E1}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);
font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",
"Source Han Sans SC","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;font-size:15px;line-height:1.55}
header{background:var(--card);border-bottom:1px solid var(--line);padding:16px 32px;display:flex;flex-wrap:wrap;
align-items:baseline;gap:8px 24px}
header h1{font-size:22px;margin:0;color:var(--text)}
header .meta{color:var(--muted);font-size:14px}
nav.toc{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:14px}
nav.toc a{color:var(--primary);text-decoration:none}
main{max-width:1840px;margin:0 auto;padding:20px 32px 48px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 22px;margin:0 0 20px;
min-width:0}
section h2{font-size:18px;margin:0 0 12px}
.muted{color:var(--muted)}
a{color:var(--primary)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;word-break:break-all}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{border:1px solid var(--line);border-radius:8px;padding:12px 14px;background:var(--bg);cursor:pointer;
transition:border-color .15s}
.card:hover,.card:focus{border-color:var(--primary);outline:none}
.card h3{font-size:15px;margin:0 0 4px;display:flex;justify-content:space-between;gap:8px}
.card .t{font-size:13px;color:var(--muted);margin:0 0 8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--line);margin:6px 0}
.bar span{display:block;height:100%}
.counts{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:13px;color:var(--muted)}
.badge{display:inline-block;font-size:12px;line-height:18px;padding:0 7px;border-radius:9px;color:#fff;
white-space:nowrap;font-weight:600}
.st-done,.st-released{background:var(--done)}.st-in_progress{background:var(--prog)}
.st-todo,.st-planned{background:var(--todo)}.st-blocked{background:var(--blocked)}
.st-moved{background:var(--moved)}.st-dropped{background:var(--dropped);color:var(--text)}
.filters{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;margin:0 0 12px;font-size:14px}
.filters select,.filters button{font:inherit;font-size:14px;padding:4px 8px;border:1px solid var(--line);
border-radius:6px;background:#fff;color:var(--text)}
.filters button{cursor:pointer;color:var(--primary)}
.release-group{margin:0 0 14px}
.release-group h3{font-size:16px;margin:10px 0 6px}
table{border-collapse:collapse;width:100%;table-layout:fixed}
th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top;font-size:14px;
overflow-wrap:anywhere}
th{color:var(--muted);font-weight:600;font-size:13px;background:var(--bg)}
tr.blocked-row td:first-child{box-shadow:inset 3px 0 0 var(--blocked)}
.dep-wait{color:var(--blocked);font-weight:600}
.notes{color:var(--muted);font-size:13px}
ul.plain{margin:0;padding-left:16px}
.graph-wrap{width:100%;overflow:hidden;border:1px solid var(--line);border-radius:8px;background:var(--bg)}
.graph-wrap svg{display:block;width:100%;height:auto}
svg text{font-family:inherit}
.wnode rect{stroke-width:1.5;cursor:pointer}
.wnode text{font-size:13px;fill:var(--text);pointer-events:none}
.wnode .sub{font-size:11px;fill:var(--muted)}
.wedge{fill:none;stroke:#94A3B8;stroke-width:1.4}
.wedge.wait{stroke:var(--blocked);stroke-dasharray:5 3}
.dim{opacity:.18}
.hl rect{stroke:var(--text)!important;stroke-width:3}
.wedge.hl{stroke:var(--text);stroke-width:2.4;opacity:1}
.mnode circle{stroke:#fff;stroke-width:2;cursor:pointer}
.mnode text{font-size:13px;fill:var(--text);pointer-events:none}
.mnode .cnt{font-size:11px;fill:#fff;font-weight:700}
.medge{fill:none;stroke:#94A3B8;stroke-opacity:.35}
.medge.cyc{stroke:var(--blocked);stroke-opacity:.55}
.medge.on{stroke:var(--primary);stroke-opacity:.95}
.medge.on.cyc{stroke:var(--blocked);stroke-opacity:1}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--muted);margin:8px 0 0}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:4px;vertical-align:-1px}
.two{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:18px}
.modview[hidden]{display:none}
.toggle{font-size:13px;cursor:pointer}
.side{font-size:13px}
.kind{font-weight:600}
.kind-release_unknown{color:var(--muted)}.kind-blocked,.kind-release_mismatch{color:var(--blocked)}
@media (max-width:1100px){.two{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
"""

JS = r"""
(function(){
  var rows=[].slice.call(document.querySelectorAll('#tasks tr[data-item]'));
  var groups=[].slice.call(document.querySelectorAll('#tasks .release-group'));
  var fr=document.getElementById('f-release'),fs=document.getElementById('f-status'),fm=document.getElementById('f-module');
  function apply(){
    var r=fr.value,s=fs.value,m=fm.value;
    rows.forEach(function(tr){
      var ok=(!r||tr.getAttribute('data-release')===r)&&(!s||tr.getAttribute('data-status')===s)&&
        (!m||(' '+tr.getAttribute('data-modules')+' ').indexOf(' '+m+' ')>=0);
      tr.hidden=!ok;
    });
    groups.forEach(function(g){g.hidden=!g.querySelector('tr[data-item]:not([hidden])');});
    var n=rows.filter(function(tr){return !tr.hidden;}).length;
    document.getElementById('f-count').textContent='显示 '+n+' / '+rows.length+' 条'+(n?'':'：没有符合筛选的条目');
  }
  [fr,fs,fm].forEach(function(el){el.addEventListener('change',apply);});
  document.getElementById('f-reset').addEventListener('click',function(){fr.value='';fs.value='';fm.value='';apply();});
  function jump(){document.getElementById('tasks').scrollIntoView();}
  [].slice.call(document.querySelectorAll('.card[data-release]')).forEach(function(c){
    function go(){fr.value=c.getAttribute('data-release');fs.value='';fm.value='';apply();jump();}
    c.addEventListener('click',go);
    c.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});
  });
  // work-item DAG: highlight a node and everything upstream of it
  var wnodes=[].slice.call(document.querySelectorAll('.wnode')),wedges=[].slice.call(document.querySelectorAll('.wedge'));
  var deps={};wnodes.forEach(function(n){var d=n.getAttribute('data-deps');deps[n.getAttribute('data-id')]=d?d.split(' '):[];});
  var picked=null;
  function upstream(id,acc){(deps[id]||[]).forEach(function(d){if(!acc[d]){acc[d]=1;upstream(d,acc);}});return acc;}
  function showW(id){
    if(!id){wnodes.concat(wedges).forEach(function(e){e.classList.remove('dim','hl');});return;}
    var up=upstream(id,{});up[id]=1;
    wnodes.forEach(function(n){var on=up[n.getAttribute('data-id')];n.classList.toggle('dim',!on);n.classList.toggle('hl',!!on);});
    wedges.forEach(function(e){var on=up[e.getAttribute('data-from')]&&up[e.getAttribute('data-to')];
      e.classList.toggle('dim',!on);e.classList.toggle('hl',!!on);});
  }
  wnodes.forEach(function(n){
    var id=n.getAttribute('data-id');
    n.addEventListener('mouseenter',function(){if(!picked)showW(id);});
    n.addEventListener('mouseleave',function(){if(!picked)showW(null);});
    n.addEventListener('click',function(){picked=(picked===id)?null:id;showW(picked);});
  });
  // module graph: highlight a node's edges within its view; click filters the task list to the items on it
  [].slice.call(document.querySelectorAll('.modview')).forEach(function(view){
    var mnodes=[].slice.call(view.querySelectorAll('.mnode')),medges=[].slice.call(view.querySelectorAll('.medge'));
    function showM(id){
      medges.forEach(function(e){var on=id&&(e.getAttribute('data-from')===id||e.getAttribute('data-to')===id);
        e.classList.toggle('on',!!on);e.classList.toggle('dim',!!id&&!on);});
      mnodes.forEach(function(n){var me=n.getAttribute('data-id');var on=!id||me===id||medges.some(function(e){
        return e.classList.contains('on')&&(e.getAttribute('data-from')===me||e.getAttribute('data-to')===me);});
        n.classList.toggle('dim',!on);});
    }
    mnodes.forEach(function(n){
      var id=n.getAttribute('data-id');
      n.addEventListener('mouseenter',function(){showM(id);});
      n.addEventListener('mouseleave',function(){showM(null);});
      n.addEventListener('click',function(){fm.value=id;fr.value='';fs.value='';apply();jump();});
    });
  });
  // the lazy-import toggle picks the view; read on load too, since a reload may restore the checkbox
  var ml=document.getElementById('m-lazy');
  function modView(){document.getElementById('mod-top').hidden=ml.checked;document.getElementById('mod-all').hidden=!ml.checked;}
  ml.addEventListener('change',modView);
  modView();
  apply();
})();
"""


def _status_counts(items: list[dict]) -> dict:
    counts = {s: 0 for s in ITEM_STATUSES}
    for it in items:
        if it.get("status") in counts:
            counts[it["status"]] += 1
    return counts


def _overview(tracker: dict) -> str:
    colors = {"done": "var(--done)", "in_progress": "var(--prog)", "todo": "var(--todo)",
              "blocked": "var(--blocked)", "moved": "var(--moved)", "dropped": "var(--dropped)"}
    cards = []
    total_counts = {s: 0 for s in ITEM_STATUSES}
    for rel in tracker["releases"]:
        items = rel.get("items") or []
        counts = _status_counts(items)
        for s, n in counts.items():
            total_counts[s] += n
        scope = len(items) - counts["moved"] - counts["dropped"]
        pct = round(100 * counts["done"] / scope) if scope else 0
        bar = "".join(f'<span style="width:{100 * counts[s] / len(items):.2f}%;background:{colors[s]}"></span>'
                      for s in ITEM_STATUSES if items and counts[s])
        tally = "".join(f"<span>{STATUS_LABEL[s]} {counts[s]}</span>" for s in ITEM_STATUSES if counts[s])
        cards.append(
            f'<div class="card" tabindex="0" role="button" data-release="{esc(rel["id"])}" '
            f'title="筛出 {esc(rel["id"])} 的任务">'
            f'<h3><span>{esc(rel["id"])}</span>{badge(rel["status"])}</h3>'
            f'<p class="t" title="{esc_text(rel.get("title"))}">{esc_text(rel.get("title"))}</p>'
            f'<div class="bar" aria-hidden="true">{bar}</div>'
            f'<div class="counts"><span><b>{pct}%</b> 完成（{counts["done"]}/{scope}）</span>{tally}</div></div>')
    totals = "、".join(f"{STATUS_LABEL[s]} {n}" for s, n in total_counts.items() if n)
    return (f'<section id="overview"><h2>① 总览</h2><p class="muted">全部 {sum(total_counts.values())} 个条目：'
            f'{totals}。完成率 = 已完成 / (总数 − 已移出 − 已放弃)。点击版本卡片筛出它的任务。</p>'
            f'<div class="cards">{"".join(cards)}</div></section>')


def _item_row(rel: dict, it: dict, status_of: dict, blocked: dict, tops: dict) -> str:
    iid = str(it["id"])
    deps = []
    for d in _as_list(it.get("depends_on")):
        d = str(d)
        cls = ' class="dep-wait"' if d in blocked.get(iid, []) else ""
        deps.append(f'<li{cls}><code>{esc(d)}</code> {badge(status_of.get(d, ""))}</li>')
    dep_html = f'<ul class="plain">{"".join(deps)}</ul>' if deps else '<span class="muted">—</span>'
    if iid in blocked:
        dep_html += f'<div class="dep-wait">被 {esc("、".join(blocked[iid]))} 卡住</div>'
    mods = _as_list(it.get("modules"))
    mod_html = "<br>".join(f"<code>{esc(m)}</code>" for m in mods) or '<span class="muted">—</span>'
    ev = it.get("evidence") or {}
    ev_parts = []
    if it.get("plan"):
        ev_parts.append("计划 " + link(it["plan"]))
    ev_parts += [link(d) for d in _as_list(ev.get("docs"))]
    for c in _as_list(ev.get("commits")):
        ev_parts.append(f'<code>{esc(c.get("sha"))}</code> {esc(c.get("date"))} '
                        f'<span class="notes">{esc_text(c.get("title"))}</span>')
    ev_html = "<br>".join(ev_parts) or '<span class="muted">—</span>'
    notes = []
    if it.get("moved_to"):
        notes.append(f'移至 <code>{esc(it["moved_to"])}</code>')
    if it.get("notes"):
        notes.append(esc_text(it["notes"]))
    module_keys = " ".join(sorted({tops.get(str(m), str(m)) for m in mods}))
    row_cls = ' class="blocked-row"' if iid in blocked or it.get("status") == "blocked" else ""
    return (f'<tr data-item="{esc(iid)}" data-release="{esc(rel["id"])}" data-status="{esc(it.get("status"))}" '
            f'data-modules="{esc(module_keys)}"{row_cls}>'
            f'<td><code>{esc(iid)}</code><br>{esc_text(it.get("title"))}</td><td>{badge(it.get("status"))}</td>'
            f'<td>{dep_html}</td><td>{mod_html}</td><td>{ev_html}</td>'
            f'<td class="notes">{"<br>".join(notes) or "—"}</td></tr>')


def _tasks(tracker: dict, blocked: dict, tops: dict, nodes: list[str] = ()) -> str:
    status_of = {str(it["id"]): it.get("status") for _r, it in iter_items(tracker)}
    groups = []
    for rel in tracker["releases"]:
        rows = "".join(_item_row(rel, it, status_of, blocked, tops) for it in rel.get("items") or [])
        meta = [badge(rel["status"])]
        if rel.get("branch"):
            meta.append(f'分支 <code>{esc(rel["branch"])}</code>')
        if rel.get("tag"):
            meta.append(f'tag <code>{esc(rel["tag"])}</code>')
        if rel.get("doc"):
            meta.append(link(rel["doc"]))
        if rel.get("notes"):
            meta.append(f'<span class="notes">{esc_text(rel["notes"])}</span>')
        groups.append(
            f'<div class="release-group" data-release="{esc(rel["id"])}"><h3>{esc(rel["id"])} '
            f'{esc_text(rel.get("title"))}</h3><div class="counts">{" · ".join(meta)}</div>'
            '<table><colgroup><col style="width:19%"><col style="width:7%"><col style="width:15%">'
            '<col style="width:15%"><col style="width:26%"><col style="width:18%"></colgroup>'
            '<thead><tr><th>条目</th><th>状态</th><th>依赖</th><th>模块</th><th>证据</th><th>备注</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')
    rel_opts = "".join(f'<option value="{esc(r["id"])}">{esc(r["id"])}</option>' for r in tracker["releases"])
    st_opts = "".join(f'<option value="{s}">{STATUS_LABEL[s]}（{s}）</option>' for s in ITEM_STATUSES)
    # every module node is an option (a click on a node with no items must show none, not everything)
    attached: dict[str, int] = {}
    for _r, it in iter_items(tracker):
        for m in sorted({tops.get(str(m), str(m)) for m in _as_list(it.get("modules"))}):
            attached[m] = attached.get(m, 0) + 1
    mod_opts = "".join(f'<option value="{esc(m)}">{esc(m)}（{attached.get(m, 0)}）</option>'
                       for m in sorted(set(nodes) | set(attached)))
    return ('<section id="tasks"><h2>② 版本 → 阶段 → 任务</h2><div class="filters">'
            f'<label>版本 <select id="f-release"><option value="">全部</option>{rel_opts}</select></label>'
            f'<label>状态 <select id="f-status"><option value="">全部</option>{st_opts}</select></label>'
            f'<label>模块 <select id="f-module"><option value="">全部</option>{mod_opts}</select></label>'
            '<button type="button" id="f-reset">清除筛选</button><span id="f-count" class="muted"></span></div>'
            f'{"".join(groups)}</section>')


STATUS_FILL = {"done": "#DCFCE7", "in_progress": "#DBEAFE", "todo": "#F1F5F9", "blocked": "#FEE2E2",
               "moved": "#F3E8FF", "dropped": "#F8FAFC"}
STATUS_STROKE = {"done": "#16A34A", "in_progress": "#2563EB", "todo": "#94A3B8", "blocked": "#DC2626",
                 "moved": "#A855F7", "dropped": "#CBD5E1"}


def _clip(text: str, n: int) -> str:
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "…"


def _work_graph(tracker: dict, blocked: dict) -> str:
    # columns: a release with several items is its own column; consecutive single-item releases share one
    columns: list[list[dict]] = []
    labels: list[str] = []
    run: list[dict] = []
    run_ids: list[str] = []

    def flush():
        if run:
            columns.append(list(run))
            labels.append(run_ids[0] if len(run_ids) == 1 else f"{run_ids[0]} – {run_ids[-1]}")
            run.clear()
            run_ids.clear()

    for rel in tracker["releases"]:
        items = rel.get("items") or []
        if len(items) <= 1:
            run.extend(items)
            run_ids.append(str(rel["id"]))
        else:
            flush()
            columns.append(list(items))
            labels.append(str(rel["id"]))
    flush()
    nw, nh, gx, gy, top, left = 210, 44, 64, 14, 40, 16
    pos = {}
    for ci, col in enumerate(columns):
        for ri, it in enumerate(col):
            pos[str(it["id"])] = (left + ci * (nw + gx), top + ri * (nh + gy))
    width = left * 2 + len(columns) * nw + (len(columns) - 1) * gx
    height = top + max(len(c) for c in columns) * (nh + gy) + 10
    parts = []
    for ci, label in enumerate(labels):
        parts.append(f'<text x="{left + ci * (nw + gx) + nw / 2:.0f}" y="22" text-anchor="middle" '
                     f'font-size="14" font-weight="600" fill="#64748B">{esc(label)}</text>')
    right = 0.0  # rightmost control point: a same-column arc of the last column bulges past the nodes
    for _rel, it in iter_items(tracker):
        iid = str(it["id"])
        for dep in _as_list(it.get("depends_on")):
            dep = str(dep)
            if dep not in pos:
                continue
            (x1, y1), (x2, y2) = pos[dep], pos[iid]
            wait = dep in blocked.get(iid, [])
            if x1 == x2:  # same column: arc on the right side
                sx, sy, ex, ey = x1 + nw, y1 + nh / 2, x2 + nw, y2 + nh / 2
                bend = 28 + abs(ey - sy) * 0.12
                right = max(right, sx + bend)
                d = f"M{sx:.1f},{sy:.1f} C{sx + bend:.1f},{sy:.1f} {ex + bend:.1f},{ey:.1f} {ex + 2:.1f},{ey:.1f}"
            else:
                sx, sy, ex, ey = x1 + nw, y1 + nh / 2, x2, y2 + nh / 2
                mx = (sx + ex) / 2
                d = f"M{sx:.1f},{sy:.1f} C{mx:.1f},{sy:.1f} {mx:.1f},{ey:.1f} {ex - 1:.1f},{ey:.1f}"
            cls = "wedge wait" if wait else "wedge"
            marker = "arrw" if wait else "arr"
            parts.append(f'<path class="{cls}" data-from="{esc(dep)}" data-to="{esc(iid)}" d="{d}" '
                         f'marker-end="url(#{marker})"/>')
    for _rel, it in iter_items(tracker):
        iid = str(it["id"])
        x, y = pos[iid]
        st = it.get("status", "todo")
        stroke = "#DC2626" if iid in blocked else STATUS_STROKE.get(st, "#94A3B8")
        deps = " ".join(str(d) for d in _as_list(it.get("depends_on")) if str(d) in pos)
        tip = f'{iid} {it.get("title", "")} · {STATUS_LABEL.get(st, st)}'
        if iid in blocked:
            tip += " · 被 " + "、".join(blocked[iid]) + " 卡住"
        parts.append(
            f'<g class="wnode" data-id="{esc(iid)}" data-deps="{esc(deps)}"><title>{esc_text(tip)}</title>'
            f'<rect x="{x}" y="{y}" width="{nw}" height="{nh}" rx="7" fill="{STATUS_FILL.get(st, "#fff")}" '
            f'stroke="{stroke}"/>'
            f'<text x="{x + 10}" y="{y + 18}">{esc(_clip(iid, 26))}</text>'
            f'<text class="sub" x="{x + 10}" y="{y + 35}">{esc_text(_clip(it.get("title"), 17))}</text></g>')
    width = max(width, math.ceil(right) + 8)
    parts.insert(0, f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="工作项依赖图">'
                    '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                    'orient="auto"><path d="M0,0L10,5L0,10z" fill="#94A3B8"/></marker>'
                    '<marker id="arrw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                    'orient="auto"><path d="M0,0L10,5L0,10z" fill="#DC2626"/></marker></defs>')
    parts.append("</svg>")
    legend = "".join(f'<span><i style="background:{STATUS_FILL[s]};border:1.5px solid {STATUS_STROKE[s]}"></i>'
                     f'{STATUS_LABEL[s]}</span>' for s in ITEM_STATUSES)
    legend += ('<span><i style="background:#fff;border:2px dashed #DC2626"></i>红框 / 红色虚线 = 被阻塞的条目与'
               '卡住它的上游</span>')
    return ('<section id="workgraph"><h2>③ 工作项依赖图</h2><p class="muted">箭头从上游指向依赖它的条目。'
            '悬停或点击一个条目，高亮它和它的全部上游；再点一次取消。</p>'
            f'<div class="graph-wrap">{"".join(parts)}</div><div class="legend">{legend}</div></section>')


MOD_SIZE = 900          # module graph viewBox (square)
MOD_LABEL_PX = 13       # .mnode text font-size
MOD_LABEL_GAP = 18      # node centre → label start, along the radius
MOD_CHAR_PX = 7.6       # generous average advance of one label character at MOD_LABEL_PX


def module_layout(nodes: list[str]) -> tuple[float, dict]:
    """Ring layout of the module graph: ``(radius, {node: (x, y, angle)})``.

    Labels run along their node's radius, outward, so two labels are as far apart as their rays — never stacked
    the way horizontal labels collide near the top and bottom of the ring. The radius leaves room for the
    longest label inside the viewBox."""
    longest = max((len(n) for n in nodes), default=0)
    radius = MOD_SIZE / 2 - MOD_LABEL_GAP - longest * MOD_CHAR_PX - 8
    c = MOD_SIZE / 2
    pos = {}
    for i, n in enumerate(nodes):
        a = -math.pi / 2 + 2 * math.pi * i / max(len(nodes), 1)
        pos[n] = (c + radius * math.cos(a), c + radius * math.sin(a), a)
    return radius, pos


def _module_view(view: str, nodes: list[str], edges: list[dict], open_counts: dict, cycles: list[list[str]]) -> str:
    """One view of the module graph. ``view`` is ``top`` (top-level imports only: an edge weighs ``count - lazy``,
    one with none is not drawn) or ``all`` (every import: an edge weighs ``count``). Cycles are the view's own."""
    lazy_view = view == "all"
    weight = {(e["src"], e["dst"]): e["count"] if lazy_view else e["count"] - e["lazy"] for e in edges}
    edges = [e for e in edges if weight[(e["src"], e["dst"])]]
    in_cycle = {n: ci for ci, comp in enumerate(cycles) for n in comp}
    size = MOD_SIZE
    cx = cy = size / 2
    _radius, pos = module_layout(nodes)
    max_w = max(weight.values(), default=1) or 1
    label = "代码模块依赖图：" + ("含延迟导入" if lazy_view else "顶层导入")
    parts = [f'<svg viewBox="0 0 {size} {size}" role="img" aria-label="{label}">']
    for e in edges:
        x1, y1, _ = pos[e["src"]]
        x2, y2, _ = pos[e["dst"]]
        cyc = e["src"] in in_cycle and in_cycle.get(e["src"]) == in_cycle.get(e["dst"])
        n = weight[(e["src"], e["dst"])]
        w = 0.8 + 3.2 * math.sqrt(n / max_w)
        qx, qy = cx + (x1 + x2 - 2 * cx) * 0.18, cy + (y1 + y2 - 2 * cy) * 0.18
        if lazy_view:
            tip = f'{e["src"]} → {e["dst"]}：{e["count"]} 条 import' + (f'（其中 {e["lazy"]} 条延迟导入）'
                                                                       if e["lazy"] else "")
        else:
            tip = f'{e["src"]} → {e["dst"]}：{n} 条顶层 import' + (f'（另有 {e["lazy"]} 条延迟导入未画）'
                                                                 if e["lazy"] else "")
        parts.append(f'<path class="medge{" cyc" if cyc else ""}" data-from="{esc(e["src"])}" '
                     f'data-to="{esc(e["dst"])}" stroke-width="{w:.2f}" '
                     f'd="M{x1:.1f},{y1:.1f} Q{qx:.1f},{qy:.1f} {x2:.1f},{y2:.1f}"><title>{esc(tip)}</title></path>')
    for n in nodes:
        x, y, a = pos[n]
        cnt = open_counts.get(n, 0)
        fill = "#DC2626" if n in in_cycle else "#2563EB"
        r = 13 if cnt else 9
        lx, ly = x + MOD_LABEL_GAP * math.cos(a), y + MOD_LABEL_GAP * math.sin(a)
        deg = math.degrees(a)
        if math.cos(a) < -1e-9:  # left half: flip so the text never reads upside down
            deg, anchor = deg + 180, "end"
        else:
            anchor = "start"
        outs = sum(weight[(e["src"], e["dst"])] for e in edges if e["src"] == n)
        ins = sum(weight[(e["src"], e["dst"])] for e in edges if e["dst"] == n)
        tip = f"{n}：导出依赖 {outs} 条 import，被依赖 {ins} 条；挂在它上面的未完成条目 {cnt} 个"
        if n in in_cycle:
            tip += "；在依赖环里"
        parts.append(f'<g class="mnode" data-id="{esc(n)}"><title>{esc(tip)}</title>'
                     f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}"/>'
                     + (f'<text class="cnt" x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle">{cnt}</text>'
                        if cnt else "")
                     + f'<text x="{lx:.1f}" y="{ly:.1f}" dy="0.35em" text-anchor="{anchor}" '
                       f'transform="rotate({deg:.1f} {lx:.1f} {ly:.1f})">{esc(n)}</text></g>')
    parts.append("</svg>")
    if cycles:
        cyc_html = "".join(f"<li>{len(c)} 个节点：{esc('、'.join(c))}</li>" for c in cycles)
    else:
        cyc_html = "<li>无</li>"
    top_edges = sorted(edges, key=lambda e: (-weight[(e["src"], e["dst"])], e["src"], e["dst"]))[:15]
    rows = "".join(f'<tr><td><code>{esc(e["src"])}</code> → <code>{esc(e["dst"])}</code></td>'
                   f'<td>{e["count"] - e["lazy"]}</td><td>{e["lazy"]}</td></tr>' for e in top_edges)
    total = sum(weight.values())
    if lazy_view:
        what = f"全部 {total} 条 import 语句（含函数体内的延迟导入），{len(edges)} 条跨模块依赖边。"
    else:
        what = f"模块加载时执行的顶层 import {total} 条，{len(edges)} 条跨模块依赖边。"
    side = (f'<div class="side"><p class="muted">{len(nodes)} 个顶层包 / 模块；{what}'
            '圆点内数字 = 挂在该模块上的未完成条目数；红色节点与红色边 = 在本视图的 import 环里。'
            '悬停看边，点击节点筛出它的任务。</p>'
            f'<h3>依赖环（强连通分量）</h3><ul class="plain">{cyc_html}</ul>'
            '<h3>最重的 15 条边</h3><table><thead><tr><th>边</th><th>顶层</th><th>延迟</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')
    hidden = " hidden" if lazy_view else ""
    return (f'<div class="modview two" id="mod-{view}"{hidden}>'
            f'<div class="graph-wrap">{"".join(parts)}</div>{side}</div>')


def _module_graph(nodes: list[str], edges: list[dict], open_counts: dict, cycles_top: list[list[str]],
                  cycles_all: list[list[str]], unparsed: list[str] | None = None) -> str:
    lazy_total = sum(e["lazy"] for e in edges)
    note = (f'<p class="dep-wait">{len(unparsed)} 个文件 <code>ast</code> 无法解析，未计入：'
            + "、".join(f"<code>{esc(u)}</code>" for u in unparsed) + "</p>") if unparsed else ""
    return ('<section id="modgraph"><h2>④ 代码模块依赖图</h2><p class="muted">由 <code>ast</code> 解析 '
            '<code>src/agenticops/**/*.py</code> 的绝对 / 相对 / 函数内导入，聚合到顶层包与顶层模块；'
            '边粗细 = import 语句数。默认只画模块加载时执行的顶层导入——函数体内的延迟导入要到调用时才执行，'
            '不构成加载环；勾选下面的开关看全部导入，环与最重的边随视图重算。</p>'
            f'<p><label class="toggle"><input type="checkbox" id="m-lazy"> 含函数体内的延迟导入'
            f'（{lazy_total} 条）</label></p>{note}'
            + _module_view("top", nodes, edges, open_counts, cycles_top)
            + _module_view("all", nodes, edges, open_counts, cycles_all)
            + '</section>')


PLAN_NOTE = "计划文件一个框都没勾时视为不用勾选框记进度，不报「计划未勾完」。"


def _inconsistency_panel(found: list[dict]) -> str:
    if not found:
        body = f'<p class="muted">没有发现不一致。{PLAN_NOTE}</p>'
    else:
        tally = {}
        for f in found:
            tally[f["kind"]] = tally.get(f["kind"], 0) + 1
        summary = "、".join(f"{KIND_LABEL.get(k, k)} {n}" for k, n in tally.items())
        rows = "".join(f'<tr><td><code>{esc(f["item"])}</code></td>'
                       f'<td class="kind kind-{esc(f["kind"])}">{esc(KIND_LABEL.get(f["kind"], f["kind"]))}'
                       f'<br><span class="muted"><code>{esc(f["kind"])}</code></span></td>'
                       f'<td>{esc(f.get("detail", ""))}</td></tr>' for f in found)
        body = (f'<p class="muted">共 {len(found)} 项：{esc(summary)}。这些只是列出，生成器不会改写 tracker；'
                f'「无法比对」= RELEASE 文档的状态文字读不出确定含义，不作猜测。{PLAN_NOTE}</p>'
                '<table><colgroup><col style="width:14%"><col style="width:18%"><col></colgroup>'
                '<thead><tr><th>条目</th><th>类型</th><th>详情</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>')
    return f'<section id="inconsistencies"><h2>⑤ 不一致</h2>{body}</section>'


def _recent(tracker: dict, limit: int = 15) -> str:
    rows = []
    for _rel, it in iter_items(tracker):
        for c in _as_list((it.get("evidence") or {}).get("commits")):
            rows.append((str(c.get("date")), str(c.get("sha")), str(it["id"]), c.get("title", ""), it.get("status")))
    rows.sort(key=lambda r: (r[0], r[2], r[1]), reverse=True)
    if not rows:
        return '<section id="recent"><h2>⑥ 最近完成</h2><p class="muted">tracker 里还没有提交证据。</p></section>'
    body = "".join(f'<tr><td>{esc(d)}</td><td><code>{esc(s)}</code></td><td><code>{esc(i)}</code> {badge(st)}</td>'
                   f'<td>{esc_text(t)}</td></tr>' for d, s, i, t, st in rows[:limit])
    return ('<section id="recent"><h2>⑥ 最近完成</h2><p class="muted">取自 tracker 证据里记录的提交，按记录的日期倒序'
            f'（共 {len(rows)} 条，显示前 {min(limit, len(rows))} 条；不现查 git）。</p>'
            '<table><colgroup><col style="width:11%"><col style="width:10%"><col style="width:20%"><col></colgroup>'
            '<thead><tr><th>日期</th><th>提交</th><th>条目</th><th>标题</th></tr></thead>'
            f'<tbody>{body}</tbody></table></section>')


def render(root: Path, live: bool = False) -> str:
    """The dashboard HTML — a pure function of the repo's files. Raises TrackerError when the tracker is invalid."""
    root = Path(root)
    tracker = load_tracker(root)
    errors = validate_tracker(tracker, root)
    if errors:
        raise TrackerError(errors)
    blocked = blocked_by(tracker)
    found = find_inconsistencies(tracker, root)
    pkg = root / PKG_REL
    nodes = top_level_nodes(pkg) if pkg.is_dir() else []
    unparsed: list[str] = []
    edges = module_dependencies(pkg, unparsed) if pkg.is_dir() else []
    graph_all: dict[str, list[str]] = {}
    graph_top: dict[str, list[str]] = {}
    for e in edges:
        graph_all.setdefault(e["src"], []).append(e["dst"])
        if e["count"] > e["lazy"]:
            graph_top.setdefault(e["src"], []).append(e["dst"])
    cycles_top, cycles_all = find_cycles(graph_top), find_cycles(graph_all)

    tops: dict[str, str] = {}
    for _r, it in iter_items(tracker):
        for m in _as_list(it.get("modules")):
            head = str(m).strip().strip("/").split("/", 1)[0]
            if head not in nodes and f"{head}.py" in nodes:
                head = f"{head}.py"
            tops[str(m)] = head
    open_counts: dict[str, int] = {}
    for _r, it in iter_items(tracker):
        if it.get("status") in OPEN_STATUSES:
            for top in sorted({tops[str(m)] for m in _as_list(it.get("modules"))}):
                open_counts[top] = open_counts.get(top, 0) + 1

    refresh = '<meta http-equiv="refresh" content="5">\n' if live else ""
    live_note = '<span class="meta">本地实时预览：每 5 秒刷新</span>' if live else ""
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<link rel=\"icon\" href=\"data:,\">\n"
        f"{refresh}<title>AgenticOps 开发进度</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        "<header><h1>AgenticOps 开发进度</h1>"
        f'<span class="meta">tracker 更新于 <b>{esc(tracker["updated"])}</b> · 由 '
        "<code>scripts/progress/build_dashboard.py</code> 从 <code>docs/progress/tracker.yaml</code> 生成</span>"
        f"{live_note}"
        '<nav class="toc"><a href="#overview">总览</a><a href="#tasks">任务</a><a href="#workgraph">工作项依赖</a>'
        '<a href="#modgraph">模块依赖</a><a href="#inconsistencies">不一致</a><a href="#recent">最近完成</a></nav>'
        "</header>\n<main>\n"
        + _overview(tracker) + "\n"
        + _tasks(tracker, blocked, tops, nodes) + "\n"
        + _work_graph(tracker, blocked) + "\n"
        + _module_graph(nodes, edges, open_counts, cycles_top, cycles_all, unparsed) + "\n"
        + _inconsistency_panel(found) + "\n"
        + _recent(tracker) + "\n"
        + f"</main>\n<script>{JS}</script>\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------------------------- --verify

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def verify(root: Path) -> list[str]:
    """git consistency problems: missing SHAs, commit dates / titles that disagree, done items without evidence."""
    tracker = load_tracker(root)
    errors = validate_tracker(tracker, root)
    if errors:
        raise TrackerError(errors)
    problems: list[str] = []
    try:
        has_git = _git(root, "rev-parse", "--git-dir").returncode == 0
    except FileNotFoundError:
        has_git = False
    if not has_git:
        problems.append("git: not a git repository (or git missing) — commit evidence cannot be checked")
    shallow = has_git and _git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    if shallow:
        problems.append("git: shallow clone — a missing SHA may only be outside the fetched history (fetch-depth: 0)")
    for _rel, it in iter_items(tracker):
        iid = str(it["id"])
        ev = it.get("evidence") or {}
        commits = _as_list(ev.get("commits"))
        if it.get("status") == "done" and not commits and not _as_list(ev.get("docs")):
            problems.append(f"{iid}: status done but no evidence (docs / commits)")
        if not has_git:
            continue
        for c in commits:
            sha, date = str(c.get("sha")), str(c.get("date"))
            proc = _git(root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
            if proc.returncode != 0:
                problems.append(f"{iid}: commit {sha} not found in git")
                continue
            # %cs = committer date (the 提交日期 the tracker records), %s = subject; one line each
            git_date, _, git_title = _git(root, "log", "-1", "--format=%cs%n%s", sha).stdout.rstrip("\n").partition("\n")
            if date != git_date:
                problems.append(f"{iid}: commit {sha} tracker date {date} != git commit date {git_date or '?'}")
            title = c.get("title")
            if title and str(title) != git_title:
                problems.append(f"{iid}: commit {sha} tracker title {str(title)!r} != git subject {git_title!r}")
    return problems


# --------------------------------------------------------------------------------------------- CLI

def build(root: Path, out: Path | None = None, live: bool = False) -> Path:
    page = render(root, live=live)
    out = out or root / OUTPUT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8", newline="\n")
    return out


def check(root: Path) -> int:
    out = root / OUTPUT_REL
    page = render(root)
    if not out.is_file():
        print(f"{OUTPUT_REL} does not exist — run scripts/progress/build_dashboard.py and commit it")
        return 1
    current = out.read_text(encoding="utf-8")
    if current == page:
        print(f"{OUTPUT_REL} is up to date")
        return 0
    diff = list(difflib.unified_diff(current.splitlines(), page.splitlines(), "committed", "regenerated",
                                     n=0, lineterm=""))
    changed = sum(1 for d in diff if d[:1] in "+-" and not d.startswith(("+++", "---")))
    print(f"{OUTPUT_REL} is stale: {changed} line(s) differ — run scripts/progress/build_dashboard.py and commit it")
    for line in diff[:40]:
        print(line[:200])
    if len(diff) > 40:
        print(f"... {len(diff) - 40} more diff line(s)")
    return 1


def _inputs_signature(root: Path) -> tuple:
    files = [root / TRACKER_REL]
    files += sorted((root / "docs").rglob("*.md")) if (root / "docs").is_dir() else []
    files += sorted((root / PKG_REL).rglob("*.py")) if (root / PKG_REL).is_dir() else []
    sig = []
    for f in files:
        try:
            st = f.stat()
            sig.append((str(f), st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((str(f), None, None))
    return tuple(sig)


def watch(root: Path, out: Path | None, live: bool, interval: float = 1.0) -> int:
    target = out or root / OUTPUT_REL
    print(f"watching {TRACKER_REL}, docs/**/*.md, {PKG_REL.as_posix()}/**/*.py → {target} (Ctrl-C to stop)")
    last = None
    try:
        while True:
            sig = _inputs_signature(root)
            if sig != last:
                last = sig
                try:
                    build(root, out, live)
                    print(f"[rebuilt] {target}", flush=True)
                except TrackerError as exc:
                    print("tracker validation failed (page not rewritten):", file=sys.stderr)
                    for e in exc.errors:
                        print(f"  {e}", file=sys.stderr)
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2],
                        help="repository root (default: the repo this script lives in)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 when the committed dashboard.html is stale")
    mode.add_argument("--verify", action="store_true", help="git consistency report on stdout")
    parser.add_argument("--strict", action="store_true", help="with --verify: exit 1 when there are problems")
    parser.add_argument("--watch", action="store_true", help="rebuild whenever the inputs change")
    parser.add_argument("--live", action="store_true", help="self-refreshing copy written outside the repo")
    parser.add_argument("--out", type=Path, help=f"output for --live (default {DEFAULT_LIVE_OUT})")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.strict and not args.verify:
        parser.error("--strict only applies to --verify")
    if args.out and not args.live:
        parser.error("--out only applies to --live (the committed page is always docs/progress/dashboard.html)")
    if args.watch and (args.check or args.verify):
        parser.error("--watch cannot be combined with --check / --verify")
    out = None
    if args.live:
        if args.check or args.verify:
            parser.error("--live cannot be combined with --check / --verify")
        out = (args.out or DEFAULT_LIVE_OUT).resolve()
        if _inside(out, root):
            print(f"--out {out} is inside the repository; the live page must be written outside it", file=sys.stderr)
            return 2

    try:
        if args.check:
            return check(root)
        if args.verify:
            problems = verify(root)
            print("## Progress tracker — git consistency (`--verify`)\n")
            if problems:
                print(f"{len(problems)} problem(s){' (strict: failing)' if args.strict else ' (warning only)'}:\n")
                for p in problems:
                    print(f"- {p}")
            else:
                print("No problems: every evidence commit exists with its recorded commit date and title; "
                      "every done item has evidence.")
            return 1 if problems and args.strict else 0
        if args.watch:
            return watch(root, out, args.live)
        target = build(root, out, args.live)
        print(f"wrote {target}")
        return 0
    except TrackerError as exc:
        print(f"{TRACKER_REL}: validation failed — nothing written:", file=sys.stderr)
        for e in exc.errors:
            print(f"  {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
