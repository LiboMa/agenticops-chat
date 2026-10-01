# tests/test_issue_status_writes.py
"""HealthIssue.status has one write path: services/issue_state.transition_issue (MVP-2.6.1 Plan D).

An AST scan of src/agenticops for any other write — `x.status = …` on a name bound to a HealthIssue,
`setattr(issue, <dynamic or "status">, …)`, a bulk `query(HealthIssue)…update({"status": …})`, or raw
`UPDATE health_issues SET status`. The scanner is tested on small sources first so a green scan means something.
"""
import ast
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agenticops"
ALLOWED = {"services/issue_state.py"}
ISSUE_NAMES = {"issue", "health_issue"}
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_RAW_SQL = re.compile(r"update\s+health_issues\s+set\b[^;]*\bstatus\s*=", re.I | re.S)


def _own(scope):
    """The nodes of `scope` itself, not of the functions/classes nested in it (those are scanned on their own)."""
    todo = list(ast.iter_child_nodes(scope))
    while todo:
        n = todo.pop()
        yield n
        if not isinstance(n, _SCOPES):
            todo.extend(ast.iter_child_nodes(n))


def _mentions_issue(expr) -> bool:
    src = ast.unparse(expr)
    return "HealthIssue" in src or ".health_issue" in src


def _issue_names(scope) -> set:
    names = set(ISSUE_NAMES)
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for a in scope.args.args + scope.args.kwonlyargs:
            if a.annotation is not None and "HealthIssue" in ast.unparse(a.annotation):
                names.add(a.arg)
    for n in _own(scope):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None and _mentions_issue(n.value):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                names |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
        elif isinstance(n, (ast.For, ast.comprehension)) and _mentions_issue(n.iter):
            names |= {x.id for x in ast.walk(n.target) if isinstance(x, ast.Name)}
    return names


def _status_popped(scope) -> set:
    """Dict names D with a `D.pop("status", …)` in this scope: a `for k, v in D.items(): setattr(…)` over them is
    the remaining, status-free fields."""
    return {n.func.value.id for n in _own(scope)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "pop"
            and isinstance(n.func.value, ast.Name) and n.args
            and isinstance(n.args[0], ast.Constant) and n.args[0].value == "status"}


def _popped_loop_setattrs(scope, popped) -> set:
    """ids of `setattr(x, k, v)` calls that sit in `for k, v in D.items()` with D in `popped`."""
    ok = set()
    for n in _own(scope):
        if (isinstance(n, ast.For) and isinstance(n.iter, ast.Call) and isinstance(n.iter.func, ast.Attribute)
                and n.iter.func.attr == "items" and isinstance(n.iter.func.value, ast.Name)
                and n.iter.func.value.id in popped and isinstance(n.target, ast.Tuple) and n.target.elts
                and isinstance(n.target.elts[0], ast.Name)):
            key = n.target.elts[0].id
            for c in ast.walk(n):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "setattr"
                        and len(c.args) >= 2 and isinstance(c.args[1], ast.Name) and c.args[1].id == key):
                    ok.add(id(c))
    return ok


def _dict_keys(scope, values):
    """The keys `values` can hold: a dict literal's keys, or — for a name — the keys of the dict literals it is
    assigned in this scope plus every `name[key] = …`. None when that is unknown: a name bound to anything but a
    dict literal (or not bound here at all), or a key that is not a plain string."""
    if isinstance(values, ast.Dict):
        exprs = list(values.keys)
    elif isinstance(values, ast.Name):
        exprs, bound = [], False
        for n in _own(scope):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == values.id:
                        if not isinstance(n.value, ast.Dict):
                            return None
                        exprs += n.value.keys
                        bound = True
                    elif (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                          and t.value.id == values.id):
                        exprs.append(t.slice)
        if not bound:
            return None
    else:
        return None
    if not all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in exprs):
        return None
    return {k.value for k in exprs}


def _is_issue_query_update(scope, call) -> bool:
    """`<… query(HealthIssue) …>.update(<values that can hold "status">)`."""
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "update" and call.args):
        return False
    if "query(HealthIssue" not in ast.unparse(call.func.value):
        return False
    keys = _dict_keys(scope, call.args[0])
    return keys is None or "status" in keys


def status_writes(source: str) -> list:
    """(line, code) for every HealthIssue.status write in `source`."""
    tree = ast.parse(source)
    out = set()
    for scope in [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        names = _issue_names(scope)
        exempt = _popped_loop_setattrs(scope, _status_popped(scope))
        for n in _own(scope):
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    for y in ast.walk(t):
                        if (isinstance(y, ast.Attribute) and y.attr == "status" and isinstance(y.ctx, ast.Store)
                                and isinstance(y.value, ast.Name) and y.value.id in names):
                            out.add((n.lineno, ast.unparse(t)))
            elif isinstance(n, ast.Call):
                if (isinstance(n.func, ast.Name) and n.func.id == "setattr" and len(n.args) >= 2
                        and isinstance(n.args[0], ast.Name) and n.args[0].id in names and id(n) not in exempt):
                    key = n.args[1]
                    if not (isinstance(key, ast.Constant) and key.value != "status"):
                        out.add((n.lineno, ast.unparse(n)))
                elif _is_issue_query_update(scope, n):
                    out.add((n.lineno, ast.unparse(n)))
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and _RAW_SQL.search(n.value):
                out.add((n.lineno, n.value[:80]))
    return sorted(out)


# ── the scanner itself ─────────────────────────────────────────────────────

def _lines(src):
    return [ln for ln, _ in status_writes(src)]


def test_the_scanner_sees_a_direct_assignment():
    assert _lines("def f(s):\n    issue = s.get(HealthIssue, 1)\n    issue.status = 'resolved'\n") == [3]


def test_the_scanner_follows_what_a_name_is_bound_to():
    src = ("def f(s, plan):\n"
           "    hi = plan.health_issue\n"
           "    hi.status = 'fix_approved'\n"
           "    for row in s.query(HealthIssue).all():\n"
           "        row.status = 'open'\n"
           "    plan.status = 'approved'\n")
    assert _lines(src) == [3, 5]


def test_the_scanner_sees_an_annotated_parameter():
    assert _lines("def f(target: HealthIssue):\n    target.status = 'open'\n") == [2]


def test_the_scanner_sees_setattr_with_a_dynamic_or_status_key():
    src = ("def f(issue, k, v):\n"
           "    setattr(issue, k, v)\n"
           "    setattr(issue, 'status', v)\n"
           "    setattr(issue, 'title', v)\n")
    assert _lines(src) == [2, 3]


def test_the_scanner_exempts_a_loop_over_fields_whose_status_was_popped():
    src = ("def f(issue, data):\n"
           "    d = data.model_dump()\n"
           "    d.pop('status', None)\n"
           "    for key, value in d.items():\n"
           "        setattr(issue, key, value)\n"
           "    for key, value in data.items():\n"
           "        setattr(issue, key, value)\n")
    assert _lines(src) == [7]


def test_the_scanner_sees_bulk_updates_and_raw_sql():
    src = ("def f(s, v):\n"
           "    s.query(HealthIssue).filter(HealthIssue.id == 1).update({'status': 'open'})\n"
           "    s.query(HealthIssue).filter(HealthIssue.id == 1).update({HealthIssue.status: 'open'})\n"
           "    s.query(HealthIssue).filter(HealthIssue.id == 1).update(v)\n"
           "    s.query(HealthIssue).filter(HealthIssue.id == 1).update({'title': 'x'})\n"
           "    s.execute(text(\"UPDATE health_issues SET status = 'open' WHERE id = 1\"))\n"
           "    s.execute(text(\"UPDATE health_issues SET provider = 'aws'\"))\n"
           "    w = {'title': 'x'}\n"
           "    s.query(HealthIssue).filter(HealthIssue.id == 1).update(w)\n"
           "    w['status'] = 'open'\n")
    assert _lines(src) == [2, 3, 4, 6, 9]


def test_the_scanner_reads_the_keys_of_a_values_dict():
    src = ("def f(s, row):\n"
           "    values = {'resource_ref': 1}\n"
           "    if row:\n"
           "        values['account_id'] = 2\n"
           "    s.query(HealthIssue).filter(HealthIssue.id == 1).update(values)\n")
    assert _lines(src) == []


def test_the_scanner_keeps_nested_scopes_apart():
    src = ("def outer(s):\n"
           "    plan = s.query(HealthIssue).first()\n"
           "    def inner(plan, k, v):\n"
           "        setattr(plan, k, v)\n"
           "    return inner\n")
    assert _lines(src) == []


# ── the code base ──────────────────────────────────────────────────────────

def test_only_transition_issue_writes_a_health_issue_status():
    found = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in ALLOWED:
            continue
        found += [f"{rel}:{ln}: {code}" for ln, code in status_writes(path.read_text())]
    assert found == [], "write HealthIssue.status through services.issue_state.transition_issue:\n" + "\n".join(found)
