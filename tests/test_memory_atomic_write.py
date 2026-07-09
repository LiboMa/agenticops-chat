"""Regression: concurrent touch_last_used on the same memory file must not raise.

Repro for the FileNotFoundError seen in production when multiple agents build
concurrently and all touch the same shared/ memory: the atomic writer used a
FIXED tmp name (.{name}.tmp), so parallel writers clobbered each other's tmp and
os.replace hit a vanished tmp -> FileNotFoundError.
"""

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from agenticops.memory.agent_memory import (
    save_memory_file,
    touch_last_used,
    parse_frontmatter,
    _atomic_write_text,
    _serialize_frontmatter,
)


@pytest.fixture
def tmp_memory_dir(tmp_path):
    mem_dir = tmp_path / "agent-memory"
    for agent in ("sre", "shared"):
        (mem_dir / agent).mkdir(parents=True)
        (mem_dir / agent / "MEMORY.md").write_text(f"# {agent} memory\n")
    with patch("agenticops.memory.agent_memory.AGENT_MEMORY_DIR", mem_dir):
        yield mem_dir


def test_concurrent_touch_same_file_no_error(tmp_memory_dir):
    save_memory_file("shared", "hot.md", body="shared hot memory", confidence=5)

    errors: list[Exception] = []

    def worker():
        for _ in range(25):
            try:
                touch_last_used("shared", "hot.md")
            except Exception as e:  # noqa: BLE001 — the whole point is to catch the race
                errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent touch raised: {errors[:3]}"
    # file survived intact and is still valid frontmatter
    fp = tmp_memory_dir / "shared" / "hot.md"
    assert fp.exists()
    fm, body = parse_frontmatter(fp.read_text(encoding="utf-8"))
    assert "shared hot memory" in body
    assert fm.get("last_used")


def test_concurrent_atomic_write_leaves_valid_content(tmp_memory_dir):
    """Hammer _atomic_write_text directly from many threads -> file always readable."""
    target = tmp_memory_dir / "shared" / "x.md"
    target.write_text("seed")
    errors: list[Exception] = []

    def worker(i: int):
        for _ in range(30):
            try:
                _atomic_write_text(target, _serialize_frontmatter({"n": i}, f"body {i}"))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"atomic write raced: {errors[:3]}"
    # a fully-formed file remains (one writer's content, never a half/empty file)
    fm, body = parse_frontmatter(target.read_text(encoding="utf-8"))
    assert "body" in body
    # no leftover tmp files
    leftovers = list((tmp_memory_dir / "shared").glob(".*.tmp"))
    assert not leftovers, f"leftover tmp files: {leftovers}"
