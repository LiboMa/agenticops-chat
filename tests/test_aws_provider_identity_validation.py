"""Phase-2 Item5: resolve_credentials validates resolved identity == expected account_id.

Defense-in-depth: when the account's credentials carry an explicit `account_id`,
the resolved STS GetCallerIdentity().Account MUST match it, else fail closed.
When no account_id is configured, behavior is unchanged (no validation).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from agenticops.providers.aws import AWSProvider


def _account(creds, regions=None):
    return SimpleNamespace(provider="aws", name="acct", credentials=creds,
                           regions=regions or ["us-east-1"], labels={})


def _patch_boto3(monkeypatch, identity_account):
    """Wire a static-keys path whose GetCallerIdentity returns identity_account."""
    sess = MagicMock()
    sess.client.return_value.get_caller_identity.return_value = {
        "Account": identity_account, "Arn": f"arn:aws:iam::{identity_account}:user/x"
    }
    mock_boto3 = MagicMock()
    mock_boto3.Session.return_value = sess
    monkeypatch.setattr("agenticops.providers.aws.boto3", mock_boto3)
    return sess


def test_identity_mismatch_fails_closed(monkeypatch):
    _patch_boto3(monkeypatch, identity_account="999999999999")  # wrong account
    acct = _account({"access_key_id": "AK", "secret_access_key": "SK",
                     "account_id": "111111111111"})  # expected
    assert AWSProvider(acct).resolve_credentials() is False


def test_identity_match_succeeds(monkeypatch):
    _patch_boto3(monkeypatch, identity_account="111111111111")
    acct = _account({"access_key_id": "AK", "secret_access_key": "SK",
                     "account_id": "111111111111"})
    assert AWSProvider(acct).resolve_credentials() is True


def test_no_expected_account_id_skips_validation(monkeypatch):
    # No account_id configured → unchanged behavior, any identity passes.
    _patch_boto3(monkeypatch, identity_account="777777777777")
    acct = _account({"access_key_id": "AK", "secret_access_key": "SK"})
    assert AWSProvider(acct).resolve_credentials() is True
