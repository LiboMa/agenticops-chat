"""Every place that creates a Report also queues its other language (MVP-2.7.0 S6): a scan of src/, so a new
report path cannot silently skip translation."""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agenticops"


def test_every_report_constructor_queues_a_translation():
    missing = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?<![A-Za-z_.])Report\((?!Base)", text) and "enqueue_other_language" not in text:
            missing.append(str(path.relative_to(SRC)))
    assert missing == [], f"Report() created without enqueue_other_language in: {missing}"
