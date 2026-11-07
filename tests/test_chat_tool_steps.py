"""Tool-step facts for the chat work log (2026-11-07): a one-line input summary, a short result preview, and a
display-only redaction stricter than the shared DB scrubber (which stays precision-biased)."""
import time

import pytest

from agenticops.chat.tool_steps import (PREVIEW_MAX, SUMMARY_MAX, redact_for_display, result_preview,
                                        summarize_input)

M = "[REDACTED-SECRET]"


def test_command_field_wins():
    assert summarize_input({"command": "kubectl get pods -A", "account": "prod"}) == "kubectl get pods -A"


def test_single_string_field_is_the_summary():
    assert summarize_input({"query": "list RDS instances\nin prod"}) == "list RDS instances in prod"


def test_scalars_join_as_key_value():
    assert summarize_input({"issue_id": 12, "rerun": True, "nested": {"a": 1}}) == "issue_id=12 rerun=True"


def test_string_input_and_empty():
    assert summarize_input("raw text") == "raw text"
    assert summarize_input(None) == ""
    assert summarize_input({}) == ""


def test_summary_is_one_line_and_bounded():
    s = summarize_input({"command": "x" * 500})
    assert "\n" not in s and len(s) == SUMMARY_MAX and s.endswith("…")


@pytest.mark.parametrize("raw,leak", [
    ("aws configure set aws_secret_access_key wJalrXUtnFEMI/K7MDENG", "wJalrXUtnFEMI"),
    ("mysql --password hunter2secret -h db", "hunter2secret"),
    ("mysql --password=hunter2secret", "hunter2secret"),
    ("curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def' https://x", "eyJhbGciOiJIUzI1NiJ9"),
    ("psql postgresql://admin:S3cretPass@db:5432/app", "S3cretPass"),
    ("kubectl get ns --token=abcdef123456", "abcdef123456"),
    ("export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG", "wJalrXUtnFEMI"),
])
def test_display_redaction_masks_the_common_shapes(raw, leak):
    out = redact_for_display(raw)
    assert leak not in out and M in out
    assert leak not in summarize_input({"command": raw})
    assert leak not in result_preview(raw)


def test_display_redaction_keeps_ordinary_text():
    assert redact_for_display("kubectl get pods -n orders") == "kubectl get pods -n orders"
    assert redact_for_display("postgresql://db:5432/app") == "postgresql://db:5432/app"
    # a resource reference is not a credential (the shared scrubber keeps ARNs too)
    arn = "aws secretsmanager describe-secret --secret-id arn:aws:secretsmanager:us-east-1:1:secret:db-pass"
    assert redact_for_display(arn) == arn
    assert redact_for_display("why does the secret rotation fail") == "why does the secret rotation fail"
    assert redact_for_display("token: abc123") == "token: " + M


def test_preview_collapses_whitespace_and_truncates():
    p = result_preview("line1\n\n  line2\t" + "y" * 400)
    assert p.startswith("line1 line2 ") and len(p) == PREVIEW_MAX and p.endswith("…")
    assert result_preview(None) == "" and result_preview("") == ""


def test_preview_of_a_huge_result_is_bounded():
    t = time.monotonic()
    p = result_preview("A" * 5_000_000)
    assert len(p) <= PREVIEW_MAX and time.monotonic() - t < 0.5


def test_a_secret_passed_as_the_only_text_field_is_never_the_summary():
    for inp, leak in [({"password": "hunter2xyz"}, "hunter2xyz"), ({"secret": "S3cr3tValue99", "ttl": 30}, "S3cr3tValue99")]:
        out = summarize_input(inp)
        assert leak not in out and M in out


def test_the_display_patterns_cost_stays_linear_on_hostile_input():
    for raw in ["a." * 2000, "a." * 10_000, "A_b-" * 10_000]:
        t = time.monotonic()
        summarize_input({"command": raw})
        result_preview(raw)
        assert time.monotonic() - t < 0.5, len(raw)
