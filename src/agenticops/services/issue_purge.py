"""Delete every issue and everything that hangs off it — `aiops delete issues --all` (the issue reset, 2026-11-23).

Why more than `DELETE FROM health_issues`:

- SQLite REUSES ids: once the table is empty the next issue is I#1 again. Any row left behind that is keyed by an old
  issue number — a diagnosis, a fix plan or its run, a timeline event, a signal, a recorded step, a «later», a chat
  bound to it, an ITSM link, a case record — would quietly belong to a new issue with that number.
- Old signals left behind make the first re-detected ones noise (three of one fingerprint inside 30 minutes).

Kept on purpose: change requests with their plans, runs and timeline; the two audit trails (audit_logs and the
command ledger — they record what really happened on real accounts); the inventory, the graph, security snapshots,
reports, accounts, users, schedules and settings. A chat bound to an issue stays, unbound from it (its account
binding stays: a chat is never widened).

Refused: without `yes` (a dry run needs none), on anything but SQLite, and while another AgenticOps process holds
`<data_dir>/.scheduler.lock` (web/app._acquire_instance_lock — the service). An online backup (the SQLite backup API;
the database runs in WAL mode, so the file alone is not a full copy) is taken and checked before anything is
deleted; the deletes run in ONE transaction.

A case or SOP record written from an issue goes in any case, and so does what would keep it findable (the owner,
2026-11-26 — review ④: its text names the old issue number, which the reset gives to a new issue): its vectors are
deleted in the same transaction and its file moves into `<backup>-knowledge/` (`MANIFEST.tsv` says where from) —
only a file inside the knowledge base's case / SOP folders is moved.

`move_knowledge` moves everything learned out of the way instead — not deleted: every case and SOP file of the
knowledge base (their records and vectors go from the database) and the agent-memory entries written from an issue
(`related_issue_id` in their front matter) or by the detect agent from a dismissed one (`detect/auto_*.md`).

The startup migrations (`init_db`) run only on a real run, after the refusals, the lock and the backup — a refused or
counted run changes nothing (review ⑤).
"""

from __future__ import annotations

import fcntl
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import inspect, text

_FIX_PLANS = "(select id from fix_plans where plan_kind = 'fix')"

# (label, table, where) — children first: the order PostgreSQL would need, and the subqueries on fix_plans run
# before the fix plans go
STEPS: tuple[tuple[str, str, str], ...] = (
    ("agent_steps (I…)", "agent_steps", "item like 'I%'"),
    ("attention_snoozes (I…)", "attention_snoozes", "item like 'I%'"),
    ("itsm_links (issues, fix plans)", "itsm_links",
     f"entity_type = 'health_issue' or (entity_type = 'fix_plan' and entity_id in {_FIX_PLANS})"),
    ("fix_executions (of fix plans)", "fix_executions", f"fix_plan_id in {_FIX_PLANS} or health_issue_id is not null"),
    ("fix_plans (fix)", "fix_plans", "plan_kind = 'fix'"),
    ("rca_results", "rca_results", "1 = 1"),
    ("pipeline_events (of issues)", "pipeline_events", "health_issue_id is not null"),
    ("alert_events", "alert_events", "1 = 1"),
    ("case_study_records (from issues)", "case_study_records", "source_issue_id is not null"),
    ("sop_records (from issues)", "sop_records", "source_issue_id is not null"),
    ("health_issues", "health_issues", "1 = 1"),
)
CURSORS = ("security_poll_cursors", "security_poll_cursors", "1 = 1")
# with move_knowledge every case and SOP file leaves, so their records and vectors go too
KNOWLEDGE_ROWS: tuple[tuple[str, str, str], ...] = (
    ("case_study_records (all)", "case_study_records", "1 = 1"),
    ("sop_records (all)", "sop_records", "1 = 1"),
    ("case_vectors", "case_vectors", "1 = 1"),
)
UNBIND_CHATS = ("update chat_sessions set context_entity_type = null, context_entity_id = null "
                "where context_entity_type = 'health_issue'")


class PurgeRefused(RuntimeError):
    """Nothing was done: the reason is the message."""


@dataclass
class PurgeReport:
    planned: list[tuple[str, int]]
    chats_unbound: int = 0
    deleted: list[tuple[str, int]] = field(default_factory=list)
    backup: Optional[str] = None
    knowledge_moved_to: Optional[str] = None
    moved_files: list[str] = field(default_factory=list)


def _steps(reset_poll_cursors: bool, move_knowledge: bool) -> list[tuple[str, str, str]]:
    steps = list(STEPS)
    if move_knowledge:
        records = [s for s in steps if s[1] not in ("case_study_records", "sop_records")]
        steps = records[:-1] + list(KNOWLEDGE_ROWS) + records[-1:]
    if reset_poll_cursors:
        steps.append(CURSORS)
    return steps


def _present(conn, steps):
    tables = set(inspect(conn).get_table_names())
    return [s for s in steps if s[1] in tables]


def _count(conn, table: str, where: str) -> int:
    return conn.execute(text(f"select count(*) from {table} where {where}")).scalar() or 0


def _database_path() -> Path:
    """The configured database's file — read from the setting, so nothing is opened before the check."""
    from sqlalchemy.engine import make_url
    from agenticops.config import settings
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise PurgeRefused("aiops delete issues works on SQLite only (the database is "
                           f"{url.get_backend_name()}); nothing was done")
    return Path(url.database).resolve()


def _take_lock(data_dir: Path):
    path = data_dir / ".scheduler.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fd.close()
        raise PurgeRefused(f"another AgenticOps process holds {path} — stop the service first; nothing was done")
    return fd


def _backup(db_path: Path, data_dir: Path, stamp: str) -> Path:
    dest = data_dir / "backups" / f"pre-delete-issues-{stamp}.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(db_path), timeout=30)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
        if dst.execute("pragma integrity_check").fetchone()[0] != "ok":
            raise PurgeRefused(f"the backup {dest} failed its integrity check; nothing was deleted")
        want = src.execute("select count(*) from health_issues").fetchone()[0]
        got = dst.execute("select count(*) from health_issues").fetchone()[0]
        if want != got:
            raise PurgeRefused(f"the backup {dest} holds {got} issues, the database {want}; nothing was deleted")
    finally:
        dst.close()
        src.close()
    return dest


def _delete_steps(conn, steps) -> list[tuple[str, int]]:
    done = []
    for label, table, where in steps:
        done.append((label, conn.execute(text(f"delete from {table} where {where}")).rowcount or 0))
    return done


def _from_an_issue(path: Path) -> bool:
    if path.parent.name == "detect" and path.name.startswith("auto_"):
        return True
    try:
        head = path.read_text(encoding="utf-8").split("\n---", 1)[0]
    except OSError:
        return False
    return head.startswith("---") and "\nrelated_issue_id:" in head


VECTORS_FROM_ISSUES = "case_vectors (from issues)"
FILES_FROM_ISSUES = "knowledge files from issues"


def _inside(path, root: Path) -> Optional[Path]:
    try:
        resolved = Path(path).resolve()
    except (OSError, TypeError, ValueError):
        return None
    return resolved if root in resolved.parents else None


def _issue_knowledge(conn) -> tuple[list[str], list[tuple[str, Path]]]:
    """The vector ids and the files of the case / SOP records written from an issue — the records the reset deletes.
    A case's vectors carry its `case_id`, an SOP's its file stem (pipeline/rag_pipeline.sop_vector_records); a file is
    the record's `file_path`, else where the knowledge base writes it, and only one inside its folder counts."""
    from agenticops.config import settings
    tables = set(inspect(conn).get_table_names())
    cases_dir, sops_dir = Path(settings.cases_dir).resolve(), Path(settings.sops_dir).resolve()
    ids: set[str] = set()
    files: list[tuple[str, Path]] = []
    if "case_study_records" in tables:
        for case_id, file_path in conn.execute(text(
                "select case_id, file_path from case_study_records where source_issue_id is not null")):
            ids.add(case_id)
            files.append(("cases", _inside(file_path or cases_dir / f"{case_id}.md", cases_dir)))
    if "sop_records" in tables:
        for filename, file_path in conn.execute(text(
                "select filename, file_path from sop_records where source_issue_id is not null")):
            ids.add(Path(filename).stem)
            files.append(("sops", _inside(file_path or sops_dir / filename, sops_dir)))
    return sorted(ids), [(kind, f) for kind, f in files if f is not None and f.is_file()]


def _vectors_of(conn, ids: list[str], *, delete: bool) -> int:
    if not ids or "case_vectors" not in set(inspect(conn).get_table_names()):
        return 0
    marks = ", ".join(f":v{n}" for n in range(len(ids)))
    params = {f"v{n}": v for n, v in enumerate(ids)}
    if delete:
        return conn.execute(text(f"delete from case_vectors where case_id in ({marks})"), params).rowcount or 0
    return conn.execute(text(f"select count(*) from case_vectors where case_id in ({marks})"), params).scalar() or 0


def _move_files(files: list[tuple[str, Path]], dest: Path) -> list[str]:
    moved, manifest = [], []
    for kind, path in files:
        target = dest / "knowledge_base" / kind / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        moved.append(str(target)); manifest.append(f"{path}\t{target}")
    if manifest:
        (dest / "MANIFEST.tsv").write_text("original\tmoved to\n" + "\n".join(manifest) + "\n", encoding="utf-8")
    return moved


def _move_knowledge(dest: Path, memory_dirs: list[Path]) -> list[str]:
    from agenticops.config import settings
    from agenticops.memory.agent_memory import update_memory_index
    moved: list[str] = []
    manifest: list[str] = []
    for kind, directory in (("cases", Path(settings.cases_dir)), ("sops", Path(settings.sops_dir))):
        if not directory.is_dir():
            continue
        for path in sorted(p for p in directory.iterdir() if p.is_file()):
            target = dest / "knowledge_base" / kind / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
            moved.append(str(target)); manifest.append(f"{path}\t{target}")
    for n, root in enumerate(memory_dirs):
        root = Path(root)
        name = "agent-memory" if n == 0 else f"agent-memory-{n + 1}"
        if not root.is_dir():
            continue
        for agent_dir in sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")):
            touched = False
            for path in sorted(agent_dir.glob("*.md")):
                if path.name == "MEMORY.md" or not _from_an_issue(path):
                    continue
                target = dest / name / agent_dir.name / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
                moved.append(str(target)); manifest.append(f"{path}\t{target}")
                touched = True
            if touched:
                update_memory_index(agent_dir.name, directory=agent_dir)
    if manifest:
        (dest / "MANIFEST.tsv").write_text("original\tmoved to\n" + "\n".join(manifest) + "\n", encoding="utf-8")
    return moved


def purge(*, yes: bool = False, dry_run: bool = False, reset_poll_cursors: bool = False, move_knowledge: bool = False,
          memory_dirs: Optional[list[Path]] = None) -> PurgeReport:
    """Count (dry_run) or delete every issue and what hangs off it. See the module docstring."""
    from agenticops.config import settings
    from agenticops.models import get_engine

    db_path = _database_path()
    if not dry_run and not yes:
        raise PurgeRefused("pass --yes to delete (or --dry-run to count); nothing was done")
    steps = _steps(reset_poll_cursors, move_knowledge)
    engine = get_engine()
    with engine.connect() as conn:
        steps = _present(conn, steps)
        planned = [(label, _count(conn, table, where)) for label, table, where in steps]
        if not move_knowledge:
            ids, files = _issue_knowledge(conn)
            planned += [(VECTORS_FROM_ISSUES, _vectors_of(conn, ids, delete=False)), (FILES_FROM_ISSUES, len(files))]
    report = PurgeReport(planned=planned)
    if dry_run:
        return report

    data_dir = Path(settings.data_dir)
    lock = _take_lock(data_dir)
    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report.backup = str(_backup(db_path, data_dir, stamp))
        from agenticops.models import init_db
        init_db()                                        # this version's migrations — only now, after the backup
        files: list[tuple[str, Path]] = []
        with engine.begin() as conn:                     # one transaction: an error rolls every delete back
            if "chat_sessions" in inspect(conn).get_table_names():
                report.chats_unbound = conn.execute(text(UNBIND_CHATS)).rowcount or 0
            if not move_knowledge:
                ids, files = _issue_knowledge(conn)      # read before their records go
                vectors = _vectors_of(conn, ids, delete=True)
            report.deleted = _delete_steps(conn, steps)
            if not move_knowledge:
                report.deleted.append((VECTORS_FROM_ISSUES, vectors))
        if files:
            dest = data_dir / "backups" / f"pre-delete-issues-{stamp}-knowledge"
            report.moved_files = _move_files(files, dest)
            report.knowledge_moved_to = str(dest)
        if not move_knowledge:
            report.deleted.append((FILES_FROM_ISSUES, len(report.moved_files)))    # moved aside, never deleted
        if move_knowledge:
            from agenticops.memory.agent_memory import AGENT_MEMORY_DIR
            dest = data_dir / "backups" / f"pre-delete-issues-{stamp}-knowledge"
            report.moved_files = _move_knowledge(dest, list(memory_dirs) if memory_dirs else [AGENT_MEMORY_DIR])
            report.knowledge_moved_to = str(dest)
    finally:
        lock.close()
    return report
