#!/usr/bin/env python3
"""Stop-the-bleed: scrub secrets already at rest in a SQLite DB.

The code-level fixes (agent-memory ``_atomic_write_text`` and the ORM
``before_flush`` listener) stop NEW leaks. This one-shot script cleans up rows
written BEFORE those fixes shipped — AWS keys / AK-SK / session tokens /
passwords / private keys that a past agent persisted verbatim.

It reuses the exact same redactor as the live code (``agenticops.security``),
so on-disk cleanup and runtime prevention can never diverge.

Safety:
* **Dry-run by default** — prints per-table counts only, NEVER the secret values.
* ``--apply`` makes a timestamped ``.bak`` copy first, then rewrites in one
  transaction.
* ``cloud_accounts.credentials`` (the encrypted at-rest credential store the
  platform authenticates with) is excluded — it must survive verbatim.

Usage:
    python scripts/scrub_db_secrets.py                     # dry-run, default DB
    python scripts/scrub_db_secrets.py --apply             # clean default DB
    python scripts/scrub_db_secrets.py path/to/other.db --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Ensure the package is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agenticops.security.redaction import redact_obj, redact_secrets  # noqa: E402

# (table, column) pairs never touched — the encrypted credential store.
EXCLUDED = {("cloud_accounts", "credentials")}


def _clean_value(raw: str) -> str:
    """Redact one stored TEXT cell. JSON payloads are parsed so secret-named
    keys are caught; everything else goes through the flat-text scrubber."""
    stripped = raw.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return redact_secrets(raw)
        cleaned = redact_obj(parsed)
        if cleaned == parsed:
            return raw
        # Preserve compact vs indented shape loosely; SQLAlchemy re-serializes
        # on next write anyway. Use separators matching typical json.dumps.
        return json.dumps(cleaned, ensure_ascii=False)
    return redact_secrets(raw)


def scrub_db(db_path: Path, apply: bool) -> int:
    if not db_path.exists():
        print(f"  ✗ not found: {db_path}")
        return 0

    if apply:
        bak = db_path.with_suffix(
            db_path.suffix + "." + datetime.now().strftime("%Y%m%d-%H%M%S") + ".bak"
        )
        shutil.copy2(db_path, bak)
        print(f"  backup → {bak.name}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    tables = [
        r[0]
        for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]

    total_cells = 0
    total_rows = 0
    for table in tables:
        cols_info = cur.execute(f'PRAGMA table_info("{table}")').fetchall()
        text_cols = [
            c["name"]
            for c in cols_info
            if (c["type"] or "").upper() in ("TEXT", "JSON", "", "CLOB", "VARCHAR")
            and (table, c["name"]) not in EXCLUDED
        ]
        if not text_cols:
            continue

        col_list = ", ".join(f'"{c}"' for c in text_cols)
        # Alias rowid to a collision-free name: these tables use ``id`` as an
        # INTEGER PRIMARY KEY (a rowid alias), so a bare ``SELECT rowid`` comes
        # back labeled ``id`` — Row["rowid"] would KeyError. The alias is unique.
        rows = cur.execute(
            f'SELECT rowid AS _scrub_rid, {col_list} FROM "{table}"'
        ).fetchall()
        table_cells = 0
        table_rows = 0
        for row in rows:
            changed = {}
            for col in text_cols:
                val = row[col]
                if not isinstance(val, str) or not val:
                    continue
                cleaned = _clean_value(val)
                if cleaned != val:
                    changed[col] = cleaned
            if changed:
                table_rows += 1
                table_cells += len(changed)
                if apply:
                    set_clause = ", ".join(f'"{c}" = ?' for c in changed)
                    cur.execute(
                        f'UPDATE "{table}" SET {set_clause} WHERE rowid = ?',
                        (*changed.values(), row["_scrub_rid"]),
                    )
        if table_cells:
            action = "scrubbed" if apply else "would scrub"
            print(f"  {table}: {action} {table_cells} cell(s) across {table_rows} row(s)")
            total_cells += table_cells
            total_rows += table_rows

    if apply:
        conn.commit()
    conn.close()

    if total_cells:
        verb = "Scrubbed" if apply else "Would scrub"
        print(f"  → {verb} {total_cells} cell(s) / {total_rows} row(s) total")
    else:
        print("  → clean (no secrets found)")
    return total_cells


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("db", nargs="?", default="data/agenticops.db", help="SQLite DB path")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {args.db}")
    scrub_db(Path(args.db), args.apply)
    if not args.apply:
        print("\n(dry-run — re-run with --apply to write changes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
