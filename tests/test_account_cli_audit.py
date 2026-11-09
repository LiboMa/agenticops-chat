"""CLI account writes (2026-11-09): `aiops create|update|delete account`, the chat's `/account`, and `aiops init`
re-registering an account each write one audit row as the CLI user — and a re-registration keeps the stored keys."""
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from agenticops.config import settings
from agenticops.models import Base, CloudAccount, get_session

FAKE_AK, FAKE_SK = "AKIACLIFAKE000000001", "cli-fake-secret-0001"


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401 — audit_logs
    import agenticops.models as models_mod
    from agenticops.credentials import store as store_mod

    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/cli.db")
    Base.metadata.create_all(models_mod.get_engine())
    store = store_mod.CredentialStore(store_mod.PlaintextBackend())
    monkeypatch.setattr(store_mod, "_store_instance", store)
    s = get_session()
    yield SimpleNamespace(session=s, store=store)
    s.close()
    models_mod.get_engine().dispose()


def _cli(*args):
    from agenticops.cli.main import app
    return CliRunner().invoke(app, list(args))


def _seed(db, name="lab", source="assume_role"):
    creds = db.store.encrypt_credentials({"account_id": "111122223333", "role_arn": "arn:aws:iam::111122223333:role/R",
                                          "access_key_id": FAKE_AK, "secret_access_key": FAKE_SK,
                                          "kubeconfigs": {"eks-a": "/etc/kube/eks-a"}})
    db.session.add(CloudAccount(name=name, provider="aws", credential_source_type=source, credentials=creds,
                                regions=["us-east-1"], is_enabled=True))
    db.session.commit()


def _account(db, name="lab"):
    db.session.expire_all()
    return db.session.query(CloudAccount).filter_by(name=name).first()


def _rows(db):
    from agenticops.audit.models import AuditLog
    db.session.expire_all()
    return db.session.query(AuditLog).filter_by(entity_type="account").order_by(AuditLog.id).all()


def _no_secret_in(rows):
    text = json.dumps([[r.old_values, r.new_values, r.details] for r in rows])
    return FAKE_AK not in text and FAKE_SK not in text


def test_create_update_delete_commands_are_audited(db):
    assert _cli("create", "account", "lab", "--account-id", "111122223333", "--role-arn",
                "arn:aws:iam::111122223333:role/R", "--no-activate").exit_code == 0
    assert _cli("update", "account", "lab", "--regions", "us-east-1,eu-west-1").exit_code == 0
    assert _cli("delete", "account", "lab", "--force").exit_code == 0
    rows = _rows(db)
    assert [r.action for r in rows] == ["create", "update", "delete"]
    assert all(r.actor.startswith("cli:") and r.details["via"] == "cli" and r.entity_name == "lab" for r in rows)
    assert (rows[1].old_values["regions"], rows[1].new_values["regions"]) == (["us-east-1", "us-west-2"],
                                                                            ["us-east-1", "eu-west-1"])


def test_update_command_keeps_the_stored_keys(db):
    _seed(db)
    assert _cli("update", "account", "lab", "--role-arn", "arn:aws:iam::111122223333:role/R2").exit_code == 0
    plain = db.store.decrypt_credentials(_account(db).credentials)
    assert (plain["access_key_id"], plain["secret_access_key"]) == (FAKE_AK, FAKE_SK)
    assert plain["role_arn"] == "arn:aws:iam::111122223333:role/R2"
    rows = _rows(db)
    assert [(r.action, r.details["secrets"]) for r in rows] == [("update", "kept")] and _no_secret_in(rows)


def test_chat_account_command_is_audited(db):
    from agenticops.cli.main import _slash_account
    _seed(db)
    ctx = SimpleNamespace(output_format="text")
    _slash_account(ctx, ["deactivate", "lab"])
    _slash_account(ctx, ["activate", "lab"])
    _slash_account(ctx, ["delete", "lab", "--force"])
    rows = _rows(db)
    assert [r.action for r in rows] == ["update", "update", "delete"]
    assert [(r.old_values["is_enabled"], r.new_values["is_enabled"]) for r in rows[:2]] == [(True, False),
                                                                                          (False, True)]
    assert all(r.actor.startswith("cli:") and r.details["via"] == "cli" for r in rows) and _no_secret_in(rows)


def test_init_re_registering_an_account_keeps_its_stored_keys(db):
    # `aiops init` on an existing account name used to replace its credentials with these three fields
    from agenticops.cli.init_helpers import _register_account
    _seed(db)
    _register_account({"name": "lab", "account_id": "111122223333", "role_arn": "arn:aws:iam::111122223333:role/R2",
                       "regions": ["us-east-1", "eu-west-1"]})
    account = _account(db)
    plain = db.store.decrypt_credentials(account.credentials)
    assert (plain["access_key_id"], plain["secret_access_key"]) == (FAKE_AK, FAKE_SK)
    assert plain["kubeconfigs"] == {"eks-a": "/etc/kube/eks-a"}
    assert plain["role_arn"] == "arn:aws:iam::111122223333:role/R2"
    assert account.regions == ["us-east-1", "eu-west-1"]
    rows = _rows(db)
    assert [(r.action, r.details["via"], r.details["secrets"]) for r in rows] == [("update", "cli", "kept")]
    assert _no_secret_in(rows)


def test_init_registering_a_new_account_is_audited(db):
    from agenticops.cli.init_helpers import _register_account
    _register_account({"name": "fresh", "account_id": "444455556666", "role_arn": "arn:aws:iam::444455556666:role/R",
                       "external_id": "ext", "regions": ["us-east-1"]})
    rows = _rows(db)
    assert [(r.action, r.entity_name, r.details["secrets"]) for r in rows] == [("create", "fresh", "none")]
    assert rows[0].new_values["credentials"] == {"account_id": "444455556666",
                                                 "role_arn": "arn:aws:iam::444455556666:role/R",
                                                 "external_id": "ext"}
