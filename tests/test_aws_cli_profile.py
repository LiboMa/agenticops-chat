"""G12 — --profile refusal + interleave/abbreviation-robust blocked matching (MVP-2.6.0).

A caller must not reach another account (`--profile`, honoured by aws even with frozen creds injected)
nor slip a blocked verb past the substring block by interleaving a global option
(`aws sts --region x get-session-token`) or abbreviating a flag (`--with-decrypt`).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import Base, CommandAudit, get_session
from agenticops.tools.aws_cli_tool import (
    BLOCKED_PATTERNS,
    _classify_command,
    blocked_pattern_match,
    profile_flag_token,
    run_aws_cli,
    run_aws_cli_readonly,
)

REFUSAL = "--profile is not allowed"


@pytest.fixture(autouse=True)
def _stub_account_resolution(monkeypatch):
    """Drive credential resolution to a single mock account so an execution-path test never
    touches the DB / ambient creds (a refusal must return BEFORE this is ever consulted)."""
    from types import SimpleNamespace
    from agenticops.credentials import resolver

    snap = SimpleNamespace(id=1, name="acct", provider="aws",
                           credentials={"account_id": "111111111111"}, regions=["us-east-1"], labels={},
                           credential_source_type="assume_role")
    monkeypatch.setattr(resolver, "resolve_default_account", lambda provider="aws": snap)
    monkeypatch.setattr(resolver, "get_subprocess_env_for_account",
                        lambda target, region=None: {"AWS_ACCESS_KEY_ID": "K", "AWS_SECRET_ACCESS_KEY": "S"})


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cmd.db"
    monkeypatch.setattr(settings, "command_audit_enabled", True)
    monkeypatch.setattr(settings, "change_management_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _rows(db):
    db.expire_all()
    return db.query(CommandAudit).order_by(CommandAudit.id).all()


class TestProfileFlagToken:
    """argparse abbreviation accepts every >=3-char prefix of --profile, even glued (`--prof=x`)."""

    @pytest.mark.parametrize("cmd,expected", [
        ("aws ec2 describe-instances --profile x", "--profile"),
        ("aws ec2 describe-instances --profile=x", "--profile=x"),
        ("aws ec2 describe-instances --prof x", "--prof"),
        ("aws ec2 describe-instances --pro x", "--pro"),
        ("aws ec2 describe-instances --pr x", "--pr"),
        ("aws ec2 describe-instances --p x", "--p"),
        ("aws sts --profile p assume-role --role-arn arn:aws:iam::1:role/r", "--profile"),  # even after the subcommand
    ])
    def test_detects_profile_and_abbreviations(self, cmd, expected):
        assert profile_flag_token(cmd) == expected

    @pytest.mark.parametrize("cmd", [
        "aws ec2 describe-instances --profile-name foo",              # longer than --profile
        "aws iam list-policies --policy-arn arn:aws:iam::aws:policy/X",
        "aws ec2 describe-instances --region us-east-1",
        "aws ec2 describe-instances -p x",                            # single-dash, name len 2 < 3
    ])
    def test_no_false_positive(self, cmd):
        assert profile_flag_token(cmd) is None


class TestRunAwsCliProfileRefusal:
    """run_aws_cli / run_aws_cli_readonly refuse --profile before classification, no subprocess, ledgered."""

    @pytest.mark.parametrize("cmd", [
        "aws ec2 describe-instances --profile x",
        "aws ec2 describe-instances --profile=x",
        "aws ec2 describe-instances --prof x",
    ])
    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_run_aws_cli_refuses_profile(self, mock_run, cmd, db):
        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        out = run_aws_cli._tool_func(command=cmd)
        assert REFUSAL in out
        assert not mock_run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.reason) == ("run_aws_cli", "blocked", "blocked", "profile_flag")

    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_run_aws_cli_readonly_refuses_profile(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        out = run_aws_cli_readonly._tool_func(command="aws ec2 describe-instances --pro x")
        assert REFUSAL in out
        assert not mock_run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.reason) == \
               ("run_aws_cli_readonly", "blocked", "blocked", "profile_flag")

    @pytest.mark.parametrize("cmd", [
        "aws ec2 describe-instances --profile-name foo",
        "aws iam list-policies --policy-arn arn:aws:iam::aws:policy/X",
    ])
    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_no_false_positive_executes(self, mock_run, cmd, db):
        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        out = run_aws_cli._tool_func(command=cmd)
        assert REFUSAL not in out
        assert mock_run.called

    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_execute_aws_cli_refuses_profile_defensively(self, mock_run):
        """The attach_target / describe path reaches _execute_aws_cli without going through run_aws_cli;
        it must refuse a --profile before building the subprocess."""
        from agenticops.tools.aws_cli_tool import _execute_aws_cli
        out = _execute_aws_cli("aws ec2 describe-instances --profile x")
        assert REFUSAL in out
        assert not mock_run.called


class TestBlockedPatternMatching:
    """Interleaved global options and argparse abbreviations must not defeat the block."""

    @pytest.mark.parametrize("cmd", [
        "aws sts --region us-east-1 get-session-token",
        "aws ec2 --region x terminate-instances --instance-ids i-1",
        "aws --region x configure get default.region",
        "aws configure export-credentials",
        "aws sts --output json assume-role --role-arn arn:aws:iam::1:role/r --role-session-name s",
    ])
    def test_interleaved_globals_are_blocked(self, cmd):
        assert _classify_command(cmd) == "blocked"

    def test_abbreviated_with_decryption_is_blocked(self):
        assert _classify_command("aws ssm get-parameter --name x --with-decrypt") == "blocked"

    @pytest.mark.parametrize("cmd", [
        "aws ec2 describe-instances --filters Name=tag:Name,Values=terminate-instances",
        "aws iam list-attached-role-policies --role-name x",
        "aws lambda invoke --function-name update-inventory out.json",
        "aws s3 ls s3://b --recursive",
        "aws configservice describe-config-rules",
    ])
    def test_no_false_positive_blocks(self, cmd):
        assert _classify_command(cmd) != "blocked"

    def test_new_blocked_patterns_present(self):
        assert "aws configure" in BLOCKED_PATTERNS
        assert "sts assume-role" in BLOCKED_PATTERNS

    def test_blocked_pattern_match_substring_pass_still_flags_prose(self):
        # pass 1 (raw substring) is unchanged: a pattern quoted in prose still flags
        assert blocked_pattern_match("please run ec2 terminate-instances now") == "ec2 terminate-instances"


class TestPatternTokenMatch:
    """The public token-half of matching, shared by change_required and blocked matching."""

    def test_word_only_parity(self):
        from agenticops.services.policy_engine import pattern_token_match
        pats = ["ec2 terminate-instances", "iam create-user"]
        assert pattern_token_match("aws ec2 --region x terminate-instances", pats) == "ec2 terminate-instances"
        assert pattern_token_match("aws ec2 describe-instances", pats) is None

    def test_flag_only_matches_by_abbreviation(self):
        from agenticops.services.policy_engine import pattern_token_match
        assert pattern_token_match("aws ssm get-parameter --with-decrypt", ["--with-decryption"]) == "--with-decryption"
        assert pattern_token_match("aws ssm get-parameter --name x", ["--with-decryption"]) is None

    def test_word_and_flag_both_required(self):
        from agenticops.services.policy_engine import pattern_token_match
        assert pattern_token_match("aws s3 rm s3://b --recurs", ["s3 rm --recursive"]) == "s3 rm --recursive"
        assert pattern_token_match("aws s3 ls s3://b --recursive", ["s3 rm --recursive"]) is None  # no 'rm'
