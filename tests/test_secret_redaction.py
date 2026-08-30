"""Tests for centralized secret redaction.

Owner mandate: AWS credentials / AK/SK / session tokens / passwords / private
keys must NEVER be written verbatim to Agent Memory, the DB, reports,
notifications, or logs. These tests pin that behavior.

No real credential is used here — only AWS-documentation example placeholders
(``AKIAIOSFODNN7EXAMPLE`` etc.), so this test file is itself leak-free.
"""
from __future__ import annotations

import json

import pytest

from agenticops.security.redaction import redact_secrets, redact_obj, contains_secret

# AWS-documented example values (public placeholders, safe to commit)
EXAMPLE_AKID = "AKIAIOSFODNN7EXAMPLE"
EXAMPLE_TEMP_AKID = "ASIAIOSFODNN7EXAMPLE"
EXAMPLE_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # 40-char shape


class TestAwsAccessKeyId:
    def test_akia_id_is_redacted(self):
        out = redact_secrets(f"the key is {EXAMPLE_AKID} in config")
        assert EXAMPLE_AKID not in out
        assert "REDACTED" in out

    def test_asia_temp_key_is_redacted(self):
        assert EXAMPLE_TEMP_AKID not in redact_secrets(f"token {EXAMPLE_TEMP_AKID}")

    def test_akid_inside_chinese_text_is_redacted(self):
        # Reproduces the real leak: key embedded in a Chinese memory sentence.
        s = f"IAM 服务账号 sa-malibo（密钥 {EXAMPLE_AKID}，账号 533267047935）合法运维"
        out = redact_secrets(s)
        assert EXAMPLE_AKID not in out
        # account id is NOT a secret and must survive
        assert "533267047935" in out


class TestSecretAccessKey:
    def test_labeled_secret_value_is_redacted(self):
        out = redact_secrets(f"aws_secret_access_key = {EXAMPLE_SECRET}")
        assert EXAMPLE_SECRET not in out

    def test_json_secretaccesskey_is_redacted(self):
        out = redact_secrets(f'"SecretAccessKey": "{EXAMPLE_SECRET}"')
        assert EXAMPLE_SECRET not in out


class TestSessionToken:
    def test_session_token_is_redacted(self):
        tok = "FwoGZXIvYXdzE" + "Ab3xample" * 15
        out = redact_secrets(f'"SessionToken": "{tok}"')
        assert tok not in out


class TestPassword:
    def test_bare_password_is_redacted(self):
        assert "hunter2secret" not in redact_secrets("password: hunter2secret")

    def test_prefixed_password_is_redacted(self):
        assert "hunter2secret" not in redact_secrets("db_password=hunter2secret extra")


class TestPemPrivateKey:
    def test_pem_block_is_redacted(self):
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEsecretkeymaterialABC123\n"
            "-----END RSA PRIVATE KEY-----"
        )
        out = redact_secrets(pem)
        assert "MIIEsecretkeymaterialABC123" not in out


class TestNoFalsePositives:
    def test_account_id_preserved(self):
        s = "arn:aws:iam::533267047935:role/app-role"
        assert redact_secrets(s) == s

    def test_plain_text_unchanged(self):
        s = "CPU usage was 92% on i-0abc123def in us-east-1 at 03:00 UTC."
        assert redact_secrets(s) == s

    def test_arn_and_resource_ids_unchanged(self):
        s = "arn:aws:ecr:us-east-1:533267047935:repository/mcp-aws sg-03a9be08e8acc3aad"
        assert redact_secrets(s) == s

    def test_secretsmanager_arn_preserved(self):
        # The ":secret:NAME" ARN segment is a resource REFERENCE, not a
        # credential — a bare "secret" preceded by ":" is a namespace
        # delimiter, not a key=value label. Scrubbing it corrupts inventory.
        s = "arn:aws:secretsmanager:us-west-2:533267047935:secret:prod/db-AbCdEf"
        assert redact_secrets(s) == s

    def test_ssm_parameter_arn_preserved(self):
        s = "arn:aws:ssm:us-east-1:533267047935:parameter/prod/token/refresh"
        assert redact_secrets(s) == s


class TestIdempotent:
    def test_double_redaction_is_stable(self):
        once = redact_secrets(f"{EXAMPLE_AKID} password: hunter2secret")
        twice = redact_secrets(once)
        assert once == twice
        assert EXAMPLE_AKID not in once


class TestRobustness:
    def test_empty_string(self):
        assert redact_secrets("") == ""

    def test_non_string_passthrough(self):
        assert redact_secrets(None) is None
        assert redact_secrets(123) == 123


class TestAwsNonSecretTokensPreserved:
    """AWS overloads ``*Token``/``*Secret`` for non-secrets that fill API
    responses. These MUST survive — masking them corrupts inventory data."""

    def test_client_token_preserved(self):
        s = '{"ClientToken": "abc123def456ghi789"}'
        assert redact_secrets(s) == s

    def test_creation_token_preserved(self):
        s = '"CreationToken": "myfs-creationtoken-001"'
        assert redact_secrets(s) == s

    def test_next_token_preserved(self):
        s = '{"NextToken": "abc123def456ghi789jkl"}'
        assert redact_secrets(s) == s

    def test_redact_obj_preserves_pagination_keys(self):
        p = {"NextToken": "abc123def456", "ClientToken": "xyz789ghi012", "items": []}
        assert redact_obj(p) == p

    def test_secret_id_and_string_keys_preserved(self):
        # SecretId / SecretName end in a non-secret word, not a bare "secret".
        p = {"SecretId": "arn:aws:secretsmanager:us-east-1:533267047935:secret:x", "SecretName": "prod"}
        assert redact_obj(p) == p


class TestBoundarySecretsStillRedacted:
    """The boundary rule must not create a hole for real secrets."""

    def test_bare_token_redacted(self):
        assert "supersecretvalue1" not in redact_secrets("token: supersecretvalue1")

    def test_delimited_db_secret_redacted(self):
        assert "supersecretvalue2" not in redact_secrets("db_secret: supersecretvalue2")

    def test_amz_security_token_redacted(self):
        assert "AbCdEf1234567890" not in redact_secrets("x-amz-security-token: AbCdEf1234567890")

    def test_camelcase_session_token_redacted(self):
        assert "FwoGZXIvExample99" not in redact_secrets('"SessionToken": "FwoGZXIvExample99"')


class TestRedactObj:
    """Structured (JSON) redaction: the label lives in the dict KEY, so the
    flat-text matcher never sees it next to the value."""

    def test_secret_named_key_value_masked(self):
        out = redact_obj({"aws_secret_access_key": EXAMPLE_SECRET, "region": "us-east-1"})
        assert out["aws_secret_access_key"] == "[REDACTED-SECRET]"
        assert out["region"] == "us-east-1"

    def test_session_token_key_masked(self):
        out = redact_obj({"SessionToken": "FwoGZXIvYXdzEExampleToken=="})
        assert "FwoGZXIvYXdzE" not in str(out)

    def test_nested_and_list_values_walked(self):
        out = redact_obj({"steps": [{"note": f"key {EXAMPLE_AKID}"}, {"password": "hunter2secret"}]})
        blob = str(out)
        assert EXAMPLE_AKID not in blob
        assert "hunter2secret" not in blob

    def test_non_secret_keys_and_account_id_preserved(self):
        payload = {"account_id": "533267047935", "resource": "arn:aws:iam::533267047935:role/x", "cpu": 91.2}
        assert redact_obj(payload) == payload

    def test_secretsmanager_arn_value_preserved(self):
        # Real inventory shape: a Lambda env var pointing AT a secret (the ARN),
        # not holding one. The ARN must survive for correlation.
        arn = "arn:aws:secretsmanager:us-west-2:533267047935:secret:prod/db-AbCdEf"
        out = redact_obj({"API_KEY_SECRET_ARN": arn, "region": "us-west-2"})
        assert out["API_KEY_SECRET_ARN"] == arn

    def test_real_bot_token_still_redacted_beside_arn(self):
        # Over-correction guard: the ARN survives, but a genuine bot_token in
        # the same payload is still masked.
        payload = {
            "API_KEY_SECRET_ARN": "arn:aws:secretsmanager:us-west-2:533267047935:secret:x",
            "bot_token": "xoxb-9999-realtokenvalue",
        }
        out = redact_obj(payload)
        assert out["API_KEY_SECRET_ARN"].endswith(":secret:x")
        assert "xoxb-9999-realtokenvalue" not in str(out)

    def test_non_secret_scalars_passthrough(self):
        assert redact_obj(123) == 123
        assert redact_obj(None) is None
        assert redact_obj({"token_count": 5, "input_tokens": 10}) == {"token_count": 5, "input_tokens": 10}

    def test_idempotent(self):
        once = redact_obj({"password": "hunter2secret", "note": f"{EXAMPLE_AKID}"})
        assert redact_obj(once) == once


class TestContainsSecret:
    def test_detects_akid(self):
        assert contains_secret(f"x {EXAMPLE_AKID} y") is True

    def test_clean_text_false(self):
        assert contains_secret("no secrets here, just account 533267047935") is False


class TestMemoryWriteIsScrubbed:
    """Integration: the path the owner named explicitly — writing Agent Memory."""

    def test_save_memory_file_scrubs_body(self, tmp_path, monkeypatch):
        from agenticops.memory import agent_memory

        monkeypatch.setattr(agent_memory, "AGENT_MEMORY_DIR", tmp_path)
        path = agent_memory.save_memory_file(
            "rca",
            "leak_probe.md",
            body=f"confirmed key {EXAMPLE_AKID} for sa-malibo account 533267047935",
            created_by="user",
        )
        content = path.read_text(encoding="utf-8")
        assert EXAMPLE_AKID not in content
        # account id survives; the memory is still useful
        assert "533267047935" in content

    def test_memory_index_scrubbed(self, tmp_path, monkeypatch):
        from agenticops.memory import agent_memory

        monkeypatch.setattr(agent_memory, "AGENT_MEMORY_DIR", tmp_path)
        agent_memory.save_memory_file(
            "rca",
            "leak_probe.md",
            body=f"key {EXAMPLE_AKID} here",
            created_by="user",
        )
        index = (tmp_path / "rca" / "MEMORY.md").read_text(encoding="utf-8")
        assert EXAMPLE_AKID not in index

    def test_memory_filename_slug_scrubbed(self, tmp_path, monkeypatch):
        """A key in the description must NOT leak into the FILENAME.

        Reproduces the original leak class: a memory filename built from text
        containing an access-key ID (e.g. ``iam_sa_malibo_<keyfragment>.md``).
        The slug lowercases the text, so content-redaction (which matches the
        uppercase key shape) can't catch it. The slug must be scrubbed BEFORE
        lowercasing, at the source.
        """
        from agenticops.memory import agent_memory
        from agenticops.tools import memory_tools

        monkeypatch.setattr(agent_memory, "AGENT_MEMORY_DIR", tmp_path)
        result = memory_tools.record_agent_feedback._tool_func(
            agent_name="rca",
            description=f"IAM sa-malibo key {EXAMPLE_AKID} is legitimate ops",
            confidence=5,
        )
        fname = json.loads(result)["file"]
        # neither the raw nor the lowercased key fragment may appear
        assert EXAMPLE_AKID not in fname
        assert EXAMPLE_AKID.lower() not in fname
        assert "akiaiosfodnn7example" not in fname
