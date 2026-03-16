"""Batch-replace datetime.utcnow with utc_now() using AST-aware import injection.

Usage:  python scripts/fix_utcnow.py [--dry-run]
"""

import ast
import re
import os
import sys

SRC_DIRS = ["src/", "tests/"]
SKIP_FILES = {"src/agenticops/utils/timeutils.py"}

IMPORT_LINE = "from agenticops.utils.timeutils import utc_now"

# Replacement patterns (applied via regex on source text)
REPLACEMENTS = [
    (re.compile(r'datetime\.utcnow\(\)'), 'utc_now()'),
    (re.compile(r'default_factory=datetime\.utcnow\b'), 'default_factory=utc_now'),
    (re.compile(r'default=datetime\.utcnow\b(?!\()'), 'default=utc_now'),
    (re.compile(r'onupdate=datetime\.utcnow\b(?!\()'), 'onupdate=utc_now'),
]

DRY_RUN = "--dry-run" in sys.argv


def find_import_insert_line(source: str) -> int:
    """Use AST to find the correct line to insert our import.
    
    Returns 1-indexed line number to insert AFTER.
    Strategy: insert after the last top-level import/from statement.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 1
    
    last_import_line = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_line = node.end_lineno or node.lineno
    
    return last_import_line


def process_file(fpath: str) -> bool:
    """Process a single file. Returns True if modified."""
    with open(fpath, 'r') as f:
        content = f.read()
    
    if 'datetime.utcnow' not in content:
        return False
    
    new_content = content
    for pattern, replacement in REPLACEMENTS:
        new_content = pattern.sub(replacement, new_content)
    
    if new_content == content:
        return False
    
    # Need to add import if not already present
    if IMPORT_LINE not in new_content:
        insert_after = find_import_insert_line(content)  # Use ORIGINAL source for AST
        lines = new_content.split('\n')
        lines.insert(insert_after, IMPORT_LINE)
        new_content = '\n'.join(lines)
    
    # Validate syntax of the result
    try:
        ast.parse(new_content, fpath)
    except SyntaxError as e:
        print(f"  ⚠️  SYNTAX ERROR after transform: {fpath}:{e.lineno} — SKIPPING")
        return False
    
    if DRY_RUN:
        print(f"  [dry-run] Would modify: {fpath}")
        return True
    
    with open(fpath, 'w') as f:
        f.write(new_content)
    return True


def main():
    changed = []
    for src_dir in SRC_DIRS:
        for root, dirs, files in os.walk(src_dir):
            for fname in sorted(files):
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                if fpath in SKIP_FILES:
                    continue
                if process_file(fpath):
                    changed.append(fpath)
    
    verb = "Would modify" if DRY_RUN else "Modified"
    print(f"\n{verb} {len(changed)} files:")
    for f in changed:
        print(f"  {f}")


if __name__ == "__main__":
    main()
