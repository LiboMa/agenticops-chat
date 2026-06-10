"""Phase-2 Item2: AssumeRole sessions use botocore auto-refreshing credentials.

Replaces the hand-rolled `sts.assume_role()` + static boto3.Session (which
silently expired after ~1h) with DeferredRefreshableCredentials so long-running
SDK sessions transparently refresh. No network: DeferredRefreshableCredentials
is lazy (only refreshes when an access_key is actually read).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import boto3
from botocore.credentials import DeferredRefreshableCredentials

from agenticops.providers.aws import AWSProvider


def _provider(creds, regions=None):
    acct = SimpleNamespace(provider="aws", name="acct", credentials=creds,
                           regions=regions or ["us-east-1"], labels={})
    return AWSProvider(acct)


def test_assume_role_session_credentials_are_refreshable():
    creds = {"role_arn": "arn:aws:iam::111111111111:role/Ops"}
    p = _provider(creds)
    base = boto3.Session()  # default chain; deferred creds won't fetch yet
    sess = p._build_assume_role_session(base, creds["role_arn"], "us-east-1", creds)
    # The session's credentials must be auto-refreshing, not static.
    assert isinstance(sess.get_credentials(), DeferredRefreshableCredentials)


def test_sts_client_creator_pins_partition_region():
    # For cross-partition roles (China/GovCloud) the AssumeRole STS call must
    # target the partition's regional endpoint, not the global one.
    base_botocore = MagicMock()
    creator = AWSProvider._sts_client_creator(base_botocore, "cn-north-1")
    creator("sts")
    base_botocore.create_client.assert_called_once_with("sts", region_name="cn-north-1")


def test_sts_client_creator_no_region_when_none():
    base_botocore = MagicMock()
    creator = AWSProvider._sts_client_creator(base_botocore, None)
    creator("sts")
    base_botocore.create_client.assert_called_once_with("sts")
