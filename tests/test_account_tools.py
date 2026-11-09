"""Tests for tools/account_tools — list, add, update, remove cloud accounts.

Covers: _mask_credentials, list_cloud_accounts, add_cloud_account,
update_cloud_account, remove_cloud_account.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.models import Base, CloudAccount, init_db
from agenticops.tools.account_tools import (
    _mask_credentials,
    _SENSITIVE_KEYS,
    _VALID_SOURCE_TYPES,
    add_cloud_account,
    list_cloud_accounts,
    remove_cloud_account,
    update_cloud_account,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _patch_db(db_session, monkeypatch):
    """Route DB lookups to the in-memory test session."""

    @contextmanager
    def fake_db():
        yield db_session

    monkeypatch.setattr("agenticops.models.get_db_session", fake_db)
    yield


@pytest.fixture(autouse=True)
def _patch_credential_store(monkeypatch):
    """A real store on the plaintext backend: an edit merges into the stored credentials (decrypt, merge, encrypt)."""
    from agenticops.credentials.store import CredentialStore, PlaintextBackend
    store = CredentialStore(PlaintextBackend())
    monkeypatch.setattr(
        "agenticops.credentials.store.get_credential_store",
        lambda: store,
    )
    yield store


@pytest.fixture(autouse=True)
def _patch_session_factory(monkeypatch):
    """Stub session factory invalidation."""
    factory = MagicMock()
    monkeypatch.setattr(
        "agenticops.credentials.session_factory.get_session_factory",
        lambda: factory,
    )
    yield factory


def _add_account(db, name="prod", provider="aws", regions=None, enabled=True, creds=None, source_type="environment"):
    a = CloudAccount(
        name=name,
        provider=provider,
        regions=regions or ["us-east-1"],
        is_enabled=enabled,
        credentials=creds or {},
        credential_source_type=source_type,
    )
    db.add(a)
    db.flush()
    return a


# ─── _mask_credentials ───────────────────────────────────────────────────────


class TestMaskCredentials:
    def test_masks_sensitive_keys(self):
        creds = {"access_key_id": "AKIA1234567890ABCDEF", "region": "us-east-1"}
        masked = _mask_credentials(creds)
        assert masked["access_key_id"].startswith("****")
        assert masked["access_key_id"].endswith("CDEF")
        assert masked["region"] == "us-east-1"

    def test_masks_key_containing_secret(self):
        creds = {"my_secret_value": "supersecret123"}
        masked = _mask_credentials(creds)
        assert masked["my_secret_value"] == "****t123"

    def test_masks_short_value(self):
        creds = {"secret_access_key": "ab"}
        masked = _mask_credentials(creds)
        assert masked["secret_access_key"] == "****"

    def test_masks_none_value(self):
        creds = {"session_token": None}
        masked = _mask_credentials(creds)
        assert masked["session_token"] == "****"

    def test_empty_dict(self):
        assert _mask_credentials({}) == {}


# ─── list_cloud_accounts ─────────────────────────────────────────────────────


class TestListCloudAccounts:
    def test_empty(self, db_session):
        result = list_cloud_accounts._tool_func()
        assert "No cloud accounts configured" in result

    def test_single_account(self, db_session):
        _add_account(db_session, "prod-us", "aws", ["us-east-1", "us-west-2"])
        result = list_cloud_accounts._tool_func()
        assert "prod-us" in result
        assert "aws" in result
        assert "us-east-1" in result
        assert "enabled" in result

    def test_disabled_account(self, db_session):
        _add_account(db_session, "staging", "azure", enabled=False)
        result = list_cloud_accounts._tool_func()
        assert "disabled" in result
        assert "○" in result

    def test_many_regions_truncated(self, db_session):
        _add_account(db_session, "big", "aws", ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"])
        result = list_cloud_accounts._tool_func()
        assert "(+1)" in result

    def test_credentials_masked_in_listing(self, db_session):
        _add_account(db_session, "cred-test", "aws", creds={"access_key_id": "AKIA1234567890ABCDEF"})
        result = list_cloud_accounts._tool_func()
        assert "AKIA1234567890ABCDEF" not in result
        assert "****" in result


# ─── add_cloud_account ───────────────────────────────────────────────────────


class TestAddCloudAccount:
    def test_add_with_role_arn(self, db_session):
        result = add_cloud_account._tool_func(
            name="new-account",
            provider="aws",
            credentials_json='{"role_arn": "arn:aws:iam::123:role/test"}',
        )
        assert "created" in result
        assert "assume_role" in result
        assert "new-account" in result

    def test_add_with_static_keys(self, db_session):
        result = add_cloud_account._tool_func(
            name="static-acc",
            provider="aws",
            credentials_json='{"access_key_id": "AKIATEST1234", "secret_access_key": "mysecret"}',
        )
        assert "static_keys" in result

    def test_add_with_profile(self, db_session):
        result = add_cloud_account._tool_func(
            name="profile-acc",
            provider="aws",
            credentials_json='{"profile_name": "dev"}',
        )
        assert "profile" in result

    def test_add_environment_default(self, db_session):
        result = add_cloud_account._tool_func(
            name="env-acc",
            provider="gcp",
            credentials_json='{"project_id": "my-project"}',
        )
        assert "environment" in result

    def test_add_invalid_provider(self, db_session):
        result = add_cloud_account._tool_func(
            name="bad",
            provider="oracle",
            credentials_json="{}",
        )
        assert "Invalid provider" in result

    def test_add_invalid_json(self, db_session):
        result = add_cloud_account._tool_func(
            name="bad",
            provider="aws",
            credentials_json="not-json{",
        )
        assert "Invalid credentials_json" in result

    def test_add_invalid_source_type(self, db_session):
        result = add_cloud_account._tool_func(
            name="bad",
            provider="aws",
            credentials_json="{}",
            credential_source_type="invalid_type",
        )
        assert "Invalid credential_source_type" in result

    def test_add_duplicate(self, db_session):
        _add_account(db_session, "existing")
        result = add_cloud_account._tool_func(
            name="existing",
            provider="aws",
            credentials_json="{}",
        )
        assert "already exists" in result

    def test_add_with_regions(self, db_session):
        result = add_cloud_account._tool_func(
            name="regional",
            provider="aws",
            credentials_json='{"role_arn": "arn:aws:iam::123:role/r"}',
            regions="us-east-1, eu-west-1",
        )
        assert "created" in result
        # Verify regions persisted
        acct = db_session.query(CloudAccount).filter_by(name="regional").first()
        assert acct.regions == ["us-east-1", "eu-west-1"]

    def test_add_explicit_source_type(self, db_session):
        result = add_cloud_account._tool_func(
            name="explicit",
            provider="aws",
            credentials_json='{"role_arn": "arn:aws:iam::123:role/r"}',
            credential_source_type="environment",
        )
        assert "environment" in result


# ─── update_cloud_account ────────────────────────────────────────────────────


class TestUpdateCloudAccount:
    def test_update_not_found(self, db_session):
        result = update_cloud_account._tool_func(name="ghost")
        assert "not found" in result

    def test_update_nothing(self, db_session):
        _add_account(db_session, "test-acc")
        result = update_cloud_account._tool_func(name="test-acc")
        assert "Nothing to update" in result

    def test_update_credentials(self, db_session, _patch_session_factory):
        _add_account(db_session, "up-cred")
        result = update_cloud_account._tool_func(
            name="up-cred",
            credentials_json='{"access_key_id": "NEWKEY123456789"}',
        )
        assert "credentials" in result
        _patch_session_factory.invalidate.assert_called_once_with("up-cred")

    def test_update_regions(self, db_session):
        _add_account(db_session, "up-reg")
        result = update_cloud_account._tool_func(name="up-reg", regions="ap-southeast-1,eu-central-1")
        assert "regions" in result
        acct = db_session.query(CloudAccount).filter_by(name="up-reg").first()
        assert "ap-southeast-1" in acct.regions

    def test_update_enabled(self, db_session):
        _add_account(db_session, "up-en", enabled=True)
        result = update_cloud_account._tool_func(name="up-en", enabled="false")
        assert "enabled" in result
        acct = db_session.query(CloudAccount).filter_by(name="up-en").first()
        assert acct.is_enabled is False

    def test_update_source_type(self, db_session):
        _add_account(db_session, "up-src")
        result = update_cloud_account._tool_func(name="up-src", credential_source_type="assume_role")
        assert "credential_source_type" in result

    def test_update_invalid_source_type(self, db_session):
        _add_account(db_session, "up-bad")
        result = update_cloud_account._tool_func(name="up-bad", credential_source_type="magic")
        assert "Invalid source type" in result

    def test_update_invalid_json(self, db_session):
        _add_account(db_session, "up-json")
        result = update_cloud_account._tool_func(name="up-json", credentials_json="{bad")
        assert "Invalid credentials_json" in result


# ─── remove_cloud_account ────────────────────────────────────────────────────


class TestRemoveCloudAccount:
    def test_remove_existing(self, db_session):
        _add_account(db_session, "to-remove")
        result = remove_cloud_account._tool_func(name="to-remove")
        assert "removed" in result
        assert db_session.query(CloudAccount).filter_by(name="to-remove").first() is None

    def test_remove_not_found(self, db_session):
        result = remove_cloud_account._tool_func(name="ghost")
        assert "not found" in result


# ─── An edit keeps the stored secrets; account changes are audited (2026-11-09) ─


def _stored_assume_role(store):
    return store.encrypt_credentials({"role_arn": "arn:aws:iam::1:role/R", "account_id": "1",
                                      "access_key_id": "AKIAOLD", "secret_access_key": "old-secret"})


def _creds(db, name):
    return db.query(CloudAccount).filter_by(name=name).one().credentials


class TestUpdateKeepsStoredSecrets:
    def test_a_role_only_edit_keeps_the_keys(self, db_session, _patch_credential_store):
        store = _patch_credential_store
        _add_account(db_session, "keep", creds=_stored_assume_role(store), source_type="assume_role")
        result = update_cloud_account._tool_func(name="keep", credentials_json='{"role_arn": "arn:aws:iam::1:role/R2"}')
        assert "credentials" in result
        assert store.decrypt_credentials(_creds(db_session, "keep")) == {
            "role_arn": "arn:aws:iam::1:role/R2", "account_id": "1",
            "access_key_id": "AKIAOLD", "secret_access_key": "old-secret"}

    def test_clear_secrets_removes_the_keys(self, db_session, _patch_credential_store):
        _add_account(db_session, "clr", creds=_stored_assume_role(_patch_credential_store), source_type="assume_role")
        result = update_cloud_account._tool_func(name="clr", clear_secrets="true")
        assert "credentials" in result
        assert _creds(db_session, "clr") == {"role_arn": "arn:aws:iam::1:role/R", "account_id": "1"}

    def test_switching_to_access_keys_drops_the_role(self, db_session, _patch_credential_store):
        store = _patch_credential_store
        _add_account(db_session, "sw", creds=_stored_assume_role(store), source_type="assume_role")
        update_cloud_account._tool_func(name="sw", credential_source_type="static_keys")
        assert store.decrypt_credentials(_creds(db_session, "sw")) == {
            "account_id": "1", "access_key_id": "AKIAOLD", "secret_access_key": "old-secret"}

    def test_an_invalid_source_type_changes_nothing(self, db_session, _patch_credential_store):
        stored = _stored_assume_role(_patch_credential_store)
        _add_account(db_session, "bad-src", creds=dict(stored), source_type="assume_role")
        result = update_cloud_account._tool_func(name="bad-src", credentials_json='{"external_id": "x"}',
                                                 credential_source_type="magic")
        assert "Invalid source type" in result
        assert _creds(db_session, "bad-src") == stored


class TestAccountToolsAudit:
    def _rows(self, db):
        from agenticops.audit.models import AuditLog
        return db.query(AuditLog).filter_by(entity_type="account").order_by(AuditLog.id).all()

    def test_add_update_remove_are_audited_without_a_secret(self, db_session):
        import json
        from agenticops.run_context import run_context
        with run_context(actor="user:alice@example.com", actor_user_id=7):
            add_cloud_account._tool_func(name="aud", provider="aws", credentials_json=json.dumps(
                {"role_arn": "arn:aws:iam::1:role/R", "access_key_id": "AKIAAUDIT", "secret_access_key": "audit-secret"}))
            update_cloud_account._tool_func(name="aud", regions="us-east-1,eu-west-1")
            remove_cloud_account._tool_func(name="aud")
        rows = self._rows(db_session)
        assert [r.action for r in rows] == ["create", "update", "delete"]
        assert {(r.actor, r.user_id, r.entity_name) for r in rows} == {("user:alice@example.com", 7, "aud")}
        assert [r.details for r in rows] == [{"via": "agent_tool", "secrets": "added"},
                                             {"via": "agent_tool", "secrets": "kept"}, {"via": "agent_tool"}]
        assert rows[1].new_values["regions"] == ["us-east-1", "eu-west-1"]
        text = json.dumps([[r.old_values, r.new_values, r.details] for r in rows])
        assert "AKIAAUDIT" not in text and "audit-secret" not in text

    def test_without_a_run_context_the_actor_is_an_agent(self, db_session):
        add_cloud_account._tool_func(name="no-ctx", provider="aws", credentials_json="{}")
        assert [r.actor for r in self._rows(db_session)] == ["agent:unattributed"]

    def test_a_refused_update_writes_no_row(self, db_session):
        _add_account(db_session, "quiet")
        update_cloud_account._tool_func(name="quiet")
        update_cloud_account._tool_func(name="quiet", credential_source_type="magic")
        assert self._rows(db_session) == []
