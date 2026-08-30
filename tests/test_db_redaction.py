"""ORM-level secret redaction at the SQLAlchemy flush boundary.

Owner mandate: AWS credentials / AK/SK / session tokens / passwords / private
keys must NEVER be persisted verbatim — not to Agent Memory files, and not to
the DB. `test_secret_redaction.py` pins the pure scrubber and the memory-file
boundary; this file pins the *database* boundary: a single before_flush
listener scrubs every String/Text/JSON column of every model right before it
is written.

No real credential is used here — only AWS-documentation example placeholders
(``AKIAIOSFODNN7EXAMPLE`` etc.), so this test file is itself leak-free.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Importing models installs the global before_flush redaction listener.
from agenticops.models import (
    Base,
    HealthIssue,
    FixExecution,
    AlertEvent,
    RCAResult,
    CloudAccount,
)

EXAMPLE_AKID = "AKIAIOSFODNN7EXAMPLE"          # AWS-doc example access key id
EXAMPLE_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # AWS-doc example secret
ACCOUNT_ID = "533267047935"                    # NOT a secret — must survive


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_health_issue_text_columns_scrubbed(session):
    issue = HealthIssue(
        resource_id="i-0abc123def",
        severity="high",
        source="manual",
        title=f"leaked key {EXAMPLE_AKID}",
        description=f"on account {ACCOUNT_ID} the key {EXAMPLE_AKID} was seen",
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)
    assert EXAMPLE_AKID not in issue.title
    assert EXAMPLE_AKID not in issue.description
    # account id is not a secret and must remain intact
    assert ACCOUNT_ID in issue.description


def test_health_issue_json_columns_scrubbed(session):
    issue = HealthIssue(
        resource_id="i-0abc123def",
        severity="high",
        source="manual",
        title="t",
        description="d",
        metric_data={"note": f"key {EXAMPLE_AKID}", "cpu": 91.2},
        related_changes=[{"event": "PutObject", "cred": EXAMPLE_AKID}],
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)
    assert EXAMPLE_AKID not in str(issue.metric_data)
    assert EXAMPLE_AKID not in str(issue.related_changes)
    # non-secret payload survives
    assert issue.metric_data["cpu"] == 91.2


def test_fix_execution_step_results_scrubbed(session):
    """The primary real-world sink: executor step output with a labeled secret."""
    ex = FixExecution(
        fix_plan_id=1,
        health_issue_id=1,
        step_results=[
            {"cmd": "cat creds", "aws_secret_access_key": EXAMPLE_SECRET},
            {"note": f"used {EXAMPLE_AKID}"},
        ],
        error_message=f"failed with key {EXAMPLE_AKID}",
    )
    session.add(ex)
    session.commit()
    session.refresh(ex)
    blob = str(ex.step_results)
    assert EXAMPLE_SECRET not in blob
    assert EXAMPLE_AKID not in blob
    assert EXAMPLE_AKID not in (ex.error_message or "")


def test_alert_event_raw_payload_scrubbed(session):
    ev = AlertEvent(
        source="generic",
        external_id="x1",
        severity="high",
        title=f"alert {EXAMPLE_AKID}",
        raw_payload={"detail": {"key": EXAMPLE_AKID}, "account": ACCOUNT_ID},
        gate_evidence={"candidates": [f"key={EXAMPLE_AKID}"]},
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    assert EXAMPLE_AKID not in ev.title
    assert EXAMPLE_AKID not in str(ev.raw_payload)
    assert EXAMPLE_AKID not in str(ev.gate_evidence)
    # account id preserved inside the JSON blob
    assert ACCOUNT_ID in str(ev.raw_payload)


def test_rca_result_scrubbed(session):
    rca = RCAResult(
        health_issue_id=1,
        root_cause=f"the IAM key {EXAMPLE_AKID} was over-privileged",
        recommendations=[f"rotate {EXAMPLE_AKID}"],
    )
    session.add(rca)
    session.commit()
    session.refresh(rca)
    assert EXAMPLE_AKID not in rca.root_cause
    assert EXAMPLE_AKID not in str(rca.recommendations)


def test_cloud_account_credentials_preserved(session):
    """The encrypted credential store MUST survive verbatim — it is the ONE
    column excluded from redaction (the platform needs it to authenticate)."""
    acct = CloudAccount(
        name="prod-account",
        provider="aws",
        credential_source_type="static_keys",
        credentials={
            "aws_access_key_id": EXAMPLE_AKID,
            "aws_secret_access_key": EXAMPLE_SECRET,
        },
    )
    session.add(acct)
    session.commit()
    session.refresh(acct)
    assert acct.credentials["aws_access_key_id"] == EXAMPLE_AKID
    assert acct.credentials["aws_secret_access_key"] == EXAMPLE_SECRET


def test_update_path_scrubbed(session):
    """Secrets introduced on a later UPDATE (dirty object) are also scrubbed."""
    issue = HealthIssue(
        resource_id="i-0abc123def", severity="low", source="manual",
        title="clean", description="clean",
    )
    session.add(issue)
    session.commit()
    issue.description = f"now leaking {EXAMPLE_AKID}"
    session.commit()
    session.refresh(issue)
    assert EXAMPLE_AKID not in issue.description
