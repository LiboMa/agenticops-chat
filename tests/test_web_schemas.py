"""Unit tests for web/schemas.py — schema validation, defaults, redaction."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

import sys
sys.path.insert(0, "src")

from agenticops.web.schemas import (
    AccountCreate,
    AccountUpdate,
    AccountResponse,
    ResourceResponse,
    ChatMessageCreate,
    ChatSessionCreate,
    ChatSessionUpdate,
    HealthIssueCreate,
    HealthIssueUpdate,
    FixPlanCreate,
    FixPlanUpdate,
    AnomalyStatusUpdate,
    LoginRequest,
    APIKeyCreate,
    REDACTED_KEYS,
)


# ---------- AccountCreate ----------


class TestAccountCreate:
    def test_valid_aws(self):
        a = AccountCreate(name="prod", provider="aws")
        assert a.provider == "aws"
        assert a.credential_source_type == "environment"
        assert a.regions == []
        assert a.is_enabled is True

    def test_valid_providers(self):
        for p in ("aws", "azure", "gcp", "alicloud"):
            a = AccountCreate(name="x", provider=p)
            assert a.provider == p

    def test_invalid_provider_rejected(self):
        with pytest.raises(ValidationError):
            AccountCreate(name="x", provider="oracle")

    def test_name_max_length(self):
        with pytest.raises(ValidationError):
            AccountCreate(name="x" * 101, provider="aws")

    def test_name_at_max_length(self):
        a = AccountCreate(name="x" * 100, provider="aws")
        assert len(a.name) == 100

    def test_invalid_credential_source_type(self):
        with pytest.raises(ValidationError):
            AccountCreate(name="x", provider="aws", credential_source_type="magic")

    def test_valid_credential_source_types(self):
        for cst in ("environment", "assume_role", "profile", "static_keys"):
            a = AccountCreate(name="x", provider="aws", credential_source_type=cst)
            assert a.credential_source_type == cst

    def test_custom_credentials_and_labels(self):
        a = AccountCreate(
            name="dev",
            provider="gcp",
            credentials={"project_id": "abc"},
            labels={"env": "dev"},
            regions=["us-east1"],
        )
        assert a.credentials == {"project_id": "abc"}
        assert a.labels == {"env": "dev"}
        assert a.regions == ["us-east1"]


# ---------- AccountUpdate ----------


class TestAccountUpdate:
    def test_all_none_by_default(self):
        u = AccountUpdate()
        assert u.name is None
        assert u.credential_source_type is None
        assert u.is_enabled is None

    def test_partial_update(self):
        u = AccountUpdate(name="new-name", is_enabled=False)
        assert u.name == "new-name"
        assert u.is_enabled is False


# ---------- AccountResponse + redaction ----------


class TestAccountResponse:
    def _make(self, creds=None):
        return AccountResponse(
            id=1,
            name="prod",
            provider="aws",
            credential_source_type="static_keys",
            credentials=creds or {},
            regions=["us-east-1"],
            labels={},
            is_enabled=True,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            last_scanned_at=None,
        )

    def test_secrets_redacted(self):
        creds = {"access_key_id": "AKIA...", "secret_access_key": "s3cr3t", "region": "us-east-1"}
        resp = self._make(creds)
        assert resp.credentials["access_key_id"] == "***REDACTED***"
        assert resp.credentials["secret_access_key"] == "***REDACTED***"
        assert resp.credentials["region"] == "us-east-1"

    def test_all_redacted_keys(self):
        creds = {k: "val" for k in REDACTED_KEYS}
        resp = self._make(creds)
        for k in REDACTED_KEYS:
            assert resp.credentials[k] == "***REDACTED***"

    def test_empty_credentials_ok(self):
        resp = self._make({})
        assert resp.credentials == {}


# ---------- ChatMessageCreate ----------


class TestChatMessageCreate:
    def test_basic(self):
        m = ChatMessageCreate(content="hello")
        assert m.content == "hello"

    def test_with_scan_focus(self):
        m = ChatMessageCreate(content="check", scan_focus="security")
        assert m.scan_focus == "security"


# ---------- ChatSessionCreate / Update ----------


class TestChatSession:
    def test_session_create(self):
        s = ChatSessionCreate(name="my-session")
        assert s.name == "my-session"

    def test_session_update_partial(self):
        u = ChatSessionUpdate(pinned=True)
        assert u.pinned is True
        assert u.name is None


# ---------- HealthIssueCreate ----------


class TestHealthIssueCreate:
    def test_required_fields(self):
        h = HealthIssueCreate(
            resource_id="i-12345",
            provider="aws",
            severity="high",
            source="detector",
            title="CPU spike",
            description="CPU > 95%",
        )
        assert h.severity == "high"


# ---------- AnomalyStatusUpdate ----------


class TestAnomalyStatusUpdate:
    def test_valid(self):
        a = AnomalyStatusUpdate(status="resolved", note="fixed")
        assert a.status == "resolved"


# ---------- LoginRequest ----------


class TestLoginRequest:
    def test_basic(self):
        lr = LoginRequest(email="a@b.com", password="secret")
        assert lr.email == "a@b.com"


# ---------- APIKeyCreate ----------


class TestAPIKeyCreate:
    def test_defaults(self):
        k = APIKeyCreate(name="ci-key")
        assert k.name == "ci-key"
