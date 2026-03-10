"""Automated tests for cloud initialization (init_helpers.py).

Tests the JSON config loading, cloud deployment profile, auto-detect,
and all helper functions without interactive prompts.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ============================================================================
# Test JSON Config Loading (load_config_file)
# ============================================================================

class TestLoadConfigFile:
    """Test load_config_file() — zero-prompt JSON path."""

    def test_local_profile_minimal(self, tmp_path):
        """Minimal local config produces correct env vars."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {
            "bedrock": {"region": "us-west-2", "model": "sonnet"},
            "profile": "local",
        }
        config_file = tmp_path / "setup.json"
        config_file.write_text(json.dumps(cfg))

        env = load_config_file(config_file)

        assert env["AIOPS_BEDROCK_REGION"] == "us-west-2"
        assert "sonnet" in env["AIOPS_BEDROCK_MODEL_ID"]
        assert env["AIOPS_DEPLOYMENT_PROFILE"] == "local"
        assert "AIOPS_DATABASE_URL" not in env  # local doesn't set DB URL

    def test_cloud_profile_rds(self, tmp_path):
        """Cloud profile with RDS produces correct PostgreSQL URL."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {
            "bedrock": {"region": "us-east-1", "model": "haiku"},
            "profile": "cloud",
            "cloud": {
                "database": "rds",
                "rds_host": "db.example.com",
                "rds_port": 5432,
                "rds_name": "agenticops",
                "rds_user": "admin",
                "rds_password": "secret123",
                "vector_storage": "rds",
                "s3_bucket": "my-bucket",
                "s3_region": "us-east-1",
            },
        }
        config_file = tmp_path / "setup.json"
        config_file.write_text(json.dumps(cfg))

        env = load_config_file(config_file)

        assert env["AIOPS_DEPLOYMENT_PROFILE"] == "cloud"
        assert env["AIOPS_DATABASE_URL"] == "postgresql+psycopg2://admin:secret123@db.example.com:5432/agenticops"
        assert env["AIOPS_VECTOR_STORAGE"] == "rds"
        assert env["AIOPS_VECTOR_RDS_URL"] == env["AIOPS_DATABASE_URL"]
        assert env["AIOPS_REPORT_STORAGE"] == "s3"
        assert env["AIOPS_REPORT_S3_BUCKET"] == "my-bucket"
        assert env["AIOPS_KB_STORAGE"] == "s3"
        assert env["AIOPS_KB_S3_BUCKET"] == "my-bucket"

    def test_cloud_profile_sqlite_efs(self, tmp_path):
        """Cloud profile with SQLite-on-EFS."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {
            "bedrock": {"region": "us-east-1", "model": "sonnet"},
            "profile": "cloud",
            "cloud": {
                "database": "sqlite-efs",
                "efs_path": "/mnt/efs/agenticops",
                "vector_storage": "s3",
                "s3_bucket": "my-bucket",
                "s3_region": "us-east-1",
            },
        }
        config_file = tmp_path / "setup.json"
        config_file.write_text(json.dumps(cfg))

        env = load_config_file(config_file)

        assert env["AIOPS_DATABASE_URL"] == "sqlite:////mnt/efs/agenticops/agenticops.db"
        assert env["AIOPS_DATA_DIR"] == "/mnt/efs/agenticops"
        assert env["AIOPS_VECTOR_STORAGE"] == "s3"
        assert env["AIOPS_VECTOR_S3_BUCKET"] == "my-bucket"

    def test_cloud_rds_no_host_skips_db_url(self, tmp_path):
        """If rds_host is empty, DATABASE_URL is not set."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {
            "profile": "cloud",
            "cloud": {"database": "rds", "rds_host": ""},
        }
        config_file = tmp_path / "setup.json"
        config_file.write_text(json.dumps(cfg))

        env = load_config_file(config_file)
        assert "AIOPS_DATABASE_URL" not in env

    def test_model_shortcuts(self, tmp_path):
        """Model shortcuts resolve to full Bedrock model IDs."""
        from agenticops.cli.init_helpers import load_config_file, _OPUS_ID, _SONNET_ID, _HAIKU_ID

        for shortcut, expected_id in [("opus", _OPUS_ID), ("sonnet", _SONNET_ID), ("haiku", _HAIKU_ID)]:
            cfg = {"bedrock": {"model": shortcut}}
            f = tmp_path / f"setup_{shortcut}.json"
            f.write_text(json.dumps(cfg))
            env = load_config_file(f)
            assert env["AIOPS_BEDROCK_MODEL_ID"] == expected_id, f"Failed for {shortcut}"

    def test_custom_model_id(self, tmp_path):
        """Full model ID passes through unchanged."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {"bedrock": {"model": "us.anthropic.custom-model-v1"}}
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))
        env = load_config_file(f)
        assert env["AIOPS_BEDROCK_MODEL_ID"] == "us.anthropic.custom-model-v1"

    def test_haiku_model_sets_sonnet_as_strong(self, tmp_path):
        """When primary model is haiku, strong should be sonnet (not opus)."""
        from agenticops.cli.init_helpers import load_config_file, _SONNET_ID

        cfg = {"bedrock": {"model": "haiku"}}
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))
        env = load_config_file(f)
        assert env["AIOPS_BEDROCK_MODEL_ID_STRONG"] == _SONNET_ID

    def test_pipeline_defaults(self, tmp_path):
        """Pipeline defaults are true when not specified."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {}
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))
        env = load_config_file(f)
        assert env["AIOPS_AUTO_FIX_ENABLED"] == "true"
        assert env["AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1"] == "true"
        assert env["AIOPS_NOTIFICATIONS_ENABLED"] == "true"

    def test_pipeline_overrides(self, tmp_path):
        """Pipeline settings can be overridden."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {"pipeline": {"auto_fix": False, "notifications": False}}
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))
        env = load_config_file(f)
        assert env["AIOPS_AUTO_FIX_ENABLED"] == "false"
        assert env["AIOPS_NOTIFICATIONS_ENABLED"] == "false"

    def test_s3_vector_with_bucket(self, tmp_path):
        """S3 vector storage sets bucket and region."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {
            "profile": "cloud",
            "cloud": {
                "database": "sqlite-efs",
                "efs_path": "/data",
                "vector_storage": "s3",
                "s3_bucket": "my-vectors",
                "s3_region": "eu-west-1",
            },
        }
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))
        env = load_config_file(f)
        assert env["AIOPS_VECTOR_STORAGE"] == "s3"
        assert env["AIOPS_VECTOR_S3_BUCKET"] == "my-vectors"
        assert env["AIOPS_VECTOR_S3_REGION"] == "eu-west-1"

    def test_datadog_integration(self, tmp_path):
        """Datadog integration settings are extracted."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {
            "integrations": {
                "datadog": {
                    "enabled": True,
                    "api_key": "abc123",
                    "app_key": "def456",
                    "site": "us5.datadoghq.com",
                }
            }
        }
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))
        env = load_config_file(f)
        assert env["AIOPS_MONITORING_PROVIDERS"] == "datadog"
        assert env["AIOPS_DATADOG_API_KEY"] == "abc123"
        assert env["AIOPS_DATADOG_SITE"] == "us5.datadoghq.com"

    def test_accounts_registered(self, tmp_path):
        """Accounts in config are registered via _register_account."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {
            "accounts": [
                {"name": "prod", "account_id": "123456789012", "role_arn": "", "regions": ["us-east-1"]},
            ],
        }
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))

        with patch("agenticops.cli.init_helpers._register_account") as mock_reg:
            env = load_config_file(f)
            mock_reg.assert_called_once()
            call_args = mock_reg.call_args[0][0]
            assert call_args["account_id"] == "123456789012"

    def test_channels_saved(self, tmp_path):
        """Channels in config are saved via save_channel."""
        from agenticops.cli.init_helpers import load_config_file

        cfg = {
            "channels": [
                {"name": "slack-ops", "type": "slack", "webhook_url": "https://hooks.slack.com/xxx"},
            ],
        }
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))

        # save_channel is imported inside the function via from agenticops.notify.im_config import save_channel
        with patch("agenticops.notify.im_config.save_channel") as mock_save:
            env = load_config_file(f)
            mock_save.assert_called_once()
            saved_name = mock_save.call_args[0][0]
            assert saved_name == "slack-ops"


# ============================================================================
# Test Generate Config Template
# ============================================================================

class TestGenerateConfigTemplate:
    def test_generates_valid_json(self, tmp_path):
        from agenticops.cli.init_helpers import generate_config_template

        output = tmp_path / "test-template.json"
        generate_config_template(output)

        assert output.exists()
        cfg = json.loads(output.read_text())
        assert "bedrock" in cfg
        assert "profile" in cfg
        assert "cloud" in cfg
        assert "accounts" in cfg
        assert "pipeline" in cfg
        assert "channels" in cfg


# ============================================================================
# Test Auto-Detect Helpers
# ============================================================================

class TestAutoDetect:
    def test_detect_aws_context_success(self):
        from agenticops.cli.init_helpers import _detect_aws_context

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/testuser",
        }

        with patch("boto3.client", return_value=mock_sts):
            ctx = _detect_aws_context("us-east-1")

        assert ctx["ok"] is True
        assert ctx["account_id"] == "123456789012"

    def test_detect_aws_context_failure(self):
        from agenticops.cli.init_helpers import _detect_aws_context

        with patch("boto3.client", side_effect=Exception("No credentials")):
            ctx = _detect_aws_context("us-east-1")

        assert ctx["ok"] is False
        assert "error" in ctx

    def test_propose_s3_bucket(self):
        from agenticops.cli.init_helpers import _propose_s3_bucket

        assert _propose_s3_bucket("123456789012") == "agenticops-123456789012"


# ============================================================================
# Test Dependency Check
# ============================================================================

class TestDependencyCheck:
    def test_check_dependencies_returns_dict(self):
        from agenticops.cli.init_helpers import check_dependencies

        results = check_dependencies(verbose=False)
        assert isinstance(results, dict)
        assert "python" in results
        assert "pip_packages" in results
        assert results["python"] is True  # We're running on Python 3.11+

    def test_check_python_version(self):
        from agenticops.cli.init_helpers import _check_python_version

        ok, ver = _check_python_version()
        assert ok is True
        assert "." in ver

    def test_check_pip_packages(self):
        from agenticops.cli.init_helpers import _check_pip_packages

        ok, missing = _check_pip_packages()
        # Most core deps should be installed; strands_agents may fail in some envs
        if not ok:
            # Only strands_agents is acceptable to be missing
            assert missing == ["strands_agents"], f"Unexpected missing packages: {missing}"

    def test_check_binary(self):
        from agenticops.cli.init_helpers import _check_binary

        assert _check_binary("python3") is True
        assert _check_binary("nonexistent_binary_xyz") is False


# ============================================================================
# Test Cloud Profile Helpers
# ============================================================================

class TestCloudHelpers:
    def test_create_s3_bucket_exists(self):
        """Existing bucket is not re-created."""
        from agenticops.cli.init_helpers import _create_s3_bucket_if_needed

        mock_s3 = MagicMock()
        mock_s3.head_bucket.return_value = {}  # bucket exists

        with patch("boto3.client", return_value=mock_s3):
            result = _create_s3_bucket_if_needed("my-bucket", "us-east-1")

        assert result is True
        mock_s3.create_bucket.assert_not_called()

    def test_create_s3_bucket_new(self):
        """New bucket is created with tagging."""
        from agenticops.cli.init_helpers import _create_s3_bucket_if_needed

        mock_s3 = MagicMock()
        mock_s3.head_bucket.side_effect = Exception("Not found")
        mock_s3.create_bucket.return_value = {}
        mock_s3.put_bucket_tagging.return_value = {}

        with patch("boto3.client", return_value=mock_s3):
            result = _create_s3_bucket_if_needed("new-bucket", "us-east-1")

        assert result is True
        mock_s3.create_bucket.assert_called_once_with(Bucket="new-bucket")

    def test_create_s3_bucket_non_us_east_1_has_location(self):
        """Non us-east-1 buckets include LocationConstraint."""
        from agenticops.cli.init_helpers import _create_s3_bucket_if_needed

        mock_s3 = MagicMock()
        mock_s3.head_bucket.side_effect = Exception("Not found")

        with patch("boto3.client", return_value=mock_s3):
            _create_s3_bucket_if_needed("eu-bucket", "eu-west-1")

        call_kwargs = mock_s3.create_bucket.call_args
        assert "CreateBucketConfiguration" in call_kwargs.kwargs or \
               (len(call_kwargs.args) == 0 and "CreateBucketConfiguration" in call_kwargs[1])

    def test_test_rds_connection_failure(self):
        """RDS test returns False on connection failure."""
        from agenticops.cli.init_helpers import _test_rds_connection

        result = _test_rds_connection("postgresql+psycopg2://bad:bad@nonexistent:5432/db")
        assert result is False

    def test_test_pgvector_failure(self):
        """pgvector test returns False on failure."""
        from agenticops.cli.init_helpers import _test_pgvector

        result = _test_pgvector("postgresql+psycopg2://bad:bad@nonexistent:5432/db")
        assert result is False


# ============================================================================
# Test run_init_wizard with --yes (non-interactive)
# ============================================================================

class TestRunInitWizardYes:
    def _mock_deps(self):
        """Return mock for check_dependencies that passes all checks."""
        return {"python": True, "pip_packages": True, "aws": True, "npm": True, "git": True, "aws_credentials": True}

    def test_yes_local_returns_env_vars(self):
        """--yes mode produces valid local env vars without prompts."""
        from agenticops.cli.init_helpers import run_init_wizard

        with patch("agenticops.cli.init_helpers.check_dependencies", return_value=self._mock_deps()):
            with patch("agenticops.cli.init_helpers._auto_register_caller", return_value=0):
                env = run_init_wizard(yes=True, profile="local")

        assert isinstance(env, dict)
        assert env.get("AIOPS_BEDROCK_REGION")
        assert "AIOPS_BEDROCK_MODEL_ID" in env
        assert env.get("AIOPS_DEPLOYMENT_PROFILE") == "local"
        assert env.get("AIOPS_AUTO_FIX_ENABLED") == "true"

    def test_yes_local_sets_sonnet_default(self):
        """--yes mode uses Sonnet as default model."""
        from agenticops.cli.init_helpers import run_init_wizard, _SONNET_ID

        with patch("agenticops.cli.init_helpers.check_dependencies", return_value=self._mock_deps()):
            with patch("agenticops.cli.init_helpers._auto_register_caller", return_value=0):
                env = run_init_wizard(yes=True, profile="local")

        assert env["AIOPS_BEDROCK_MODEL_ID"] == _SONNET_ID


# ============================================================================
# Test run_init_wizard with --config
# ============================================================================

class TestRunInitWizardConfig:
    def test_config_path_bypasses_wizard(self, tmp_path):
        """--config flag loads JSON and returns env vars without wizard."""
        from agenticops.cli.init_helpers import run_init_wizard

        cfg = {
            "bedrock": {"region": "ap-northeast-1", "model": "opus"},
            "profile": "local",
        }
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))

        env = run_init_wizard(config_path=f)

        assert env["AIOPS_BEDROCK_REGION"] == "ap-northeast-1"
        assert "opus" in env["AIOPS_BEDROCK_MODEL_ID"]
        assert env["AIOPS_DEPLOYMENT_PROFILE"] == "local"

    def test_config_cloud_rds_full(self, tmp_path):
        """Full cloud RDS config produces all expected env vars."""
        from agenticops.cli.init_helpers import run_init_wizard

        cfg = {
            "bedrock": {"region": "us-east-1", "model": "sonnet"},
            "profile": "cloud",
            "cloud": {
                "database": "rds",
                "rds_host": "mydb.cluster.us-east-1.rds.amazonaws.com",
                "rds_port": 5432,
                "rds_name": "agenticops",
                "rds_user": "admin",
                "rds_password": "pw123",
                "vector_storage": "rds",
                "s3_bucket": "agenticops-123456789012",
                "s3_region": "us-east-1",
            },
            "pipeline": {"auto_fix": True, "auto_approve_l0_l1": True, "notifications": True},
        }
        f = tmp_path / "setup.json"
        f.write_text(json.dumps(cfg))

        env = run_init_wizard(config_path=f)

        # Verify all cloud settings
        assert env["AIOPS_DEPLOYMENT_PROFILE"] == "cloud"
        assert "postgresql+psycopg2://" in env["AIOPS_DATABASE_URL"]
        assert "mydb.cluster" in env["AIOPS_DATABASE_URL"]
        assert env["AIOPS_VECTOR_STORAGE"] == "rds"
        assert env["AIOPS_VECTOR_RDS_URL"] == env["AIOPS_DATABASE_URL"]
        assert env["AIOPS_REPORT_STORAGE"] == "s3"
        assert env["AIOPS_REPORT_S3_BUCKET"] == "agenticops-123456789012"
        assert env["AIOPS_KB_STORAGE"] == "s3"
        assert env["AIOPS_KB_S3_BUCKET"] == "agenticops-123456789012"
        assert env["AIOPS_KB_S3_PREFIX"] == "knowledge_base/"
        assert env["AIOPS_REPORT_S3_PREFIX"] == "reports/"


# ============================================================================
# Test DynamoDB Table Definitions
# ============================================================================

class TestDynamoDBTables:
    def test_create_dynamodb_tables(self):
        """DynamoDB table creation calls are correct."""
        from agenticops.cli.init_helpers import _create_dynamodb_tables

        mock_ddb = MagicMock()
        mock_ddb.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_ddb.describe_table.side_effect = mock_ddb.exceptions.ResourceNotFoundException("nope")
        mock_waiter = MagicMock()
        mock_ddb.get_waiter.return_value = mock_waiter

        with patch("boto3.client", return_value=mock_ddb):
            _create_dynamodb_tables("us-east-1")

        # Should create 10 tables
        assert mock_ddb.create_table.call_count == 10

        # Check table names
        created_names = [
            call.kwargs.get("TableName") or call[1].get("TableName")
            for call in mock_ddb.create_table.call_args_list
        ]
        assert "agenticops-accounts" in created_names
        assert "agenticops-resources" in created_names
        assert "agenticops-issues" in created_names
        assert "agenticops-fixplans" in created_names
        assert "agenticops-chat-sessions" in created_names
        assert "agenticops-alert-events" in created_names

    def test_create_dynamodb_tables_skips_existing(self):
        """Existing tables are skipped."""
        from agenticops.cli.init_helpers import _create_dynamodb_tables

        mock_ddb = MagicMock()
        mock_ddb.exceptions.ResourceNotFoundException = type("RNF", (Exception,), {})
        mock_ddb.describe_table.return_value = {"Table": {"TableStatus": "ACTIVE"}}
        mock_waiter = MagicMock()
        mock_ddb.get_waiter.return_value = mock_waiter

        with patch("boto3.client", return_value=mock_ddb):
            _create_dynamodb_tables("us-east-1")

        mock_ddb.create_table.assert_not_called()


# ============================================================================
# Test Vector Store Backends
# ============================================================================

class TestVectorStoreFactory:
    def _reset_store(self):
        import agenticops.kb.vector_store as vs
        vs._vector_store = None

    def test_sqlite_default(self):
        """Default vector storage is SQLite."""
        from agenticops.kb.vector_store import SQLiteVectorStore, get_vector_store
        from agenticops.config import settings

        self._reset_store()
        orig = settings.vector_storage
        try:
            settings.vector_storage = "sqlite"
            store = get_vector_store()
            assert isinstance(store, SQLiteVectorStore)
        finally:
            settings.vector_storage = orig
            self._reset_store()

    def test_factory_rds_creates_postgres(self):
        """RDS vector storage creates PostgresVectorStore."""
        from agenticops.kb.vector_store import PostgresVectorStore, get_vector_store
        from agenticops.config import settings

        self._reset_store()
        orig_vs = settings.vector_storage
        orig_url = settings.vector_rds_url
        try:
            settings.vector_storage = "rds"
            settings.vector_rds_url = "postgresql+psycopg2://u:p@host:5432/db"
            store = get_vector_store()
            assert isinstance(store, PostgresVectorStore)
        finally:
            settings.vector_storage = orig_vs
            settings.vector_rds_url = orig_url
            self._reset_store()

    def test_factory_s3_creates_s3store(self):
        """S3 vector storage creates S3VectorStore."""
        from agenticops.kb.vector_store import S3VectorStore, get_vector_store
        from agenticops.config import settings

        self._reset_store()
        orig_vs = settings.vector_storage
        orig_bucket = settings.vector_s3_bucket
        orig_prefix = settings.vector_s3_prefix
        orig_region = settings.vector_s3_region
        try:
            settings.vector_storage = "s3"
            settings.vector_s3_bucket = "my-vectors"
            settings.vector_s3_prefix = "vectors/"
            settings.vector_s3_region = "us-east-1"
            store = get_vector_store()
            assert isinstance(store, S3VectorStore)
        finally:
            settings.vector_storage = orig_vs
            settings.vector_s3_bucket = orig_bucket
            settings.vector_s3_prefix = orig_prefix
            settings.vector_s3_region = orig_region
            self._reset_store()


# ============================================================================
# Test KB Backend Factory
# ============================================================================

class TestKBBackendFactory:
    def _reset(self):
        import agenticops.storage.backend as sb
        sb._kb_backend = None

    def test_local_default(self):
        """Default KB storage is local."""
        from agenticops.storage.backend import get_kb_backend, LocalBackend
        from agenticops.config import settings

        self._reset()
        orig = settings.kb_storage
        try:
            settings.kb_storage = "local"
            backend = get_kb_backend()
            assert isinstance(backend, LocalBackend)
        finally:
            settings.kb_storage = orig
            self._reset()

    def test_s3_backend(self):
        """S3 KB storage creates S3Backend."""
        from agenticops.storage.backend import get_kb_backend, S3Backend
        from agenticops.config import settings

        self._reset()
        orig_ks = settings.kb_storage
        orig_bucket = settings.kb_s3_bucket
        orig_prefix = settings.kb_s3_prefix
        orig_region = settings.kb_s3_region
        try:
            settings.kb_storage = "s3"
            settings.kb_s3_bucket = "my-kb"
            settings.kb_s3_prefix = "knowledge_base/"
            settings.kb_s3_region = "us-east-1"
            backend = get_kb_backend()
            assert isinstance(backend, S3Backend)
        finally:
            settings.kb_storage = orig_ks
            settings.kb_s3_bucket = orig_bucket
            settings.kb_s3_prefix = orig_prefix
            settings.kb_s3_region = orig_region
            self._reset()


# ============================================================================
# Test Config Settings
# ============================================================================

class TestConfigSettings:
    def test_new_settings_exist(self):
        """All new cloud/vector/KB settings exist in config."""
        from agenticops.config import settings

        assert hasattr(settings, "deployment_profile")
        assert hasattr(settings, "vector_storage")
        assert hasattr(settings, "vector_rds_url")
        assert hasattr(settings, "vector_s3_bucket")
        assert hasattr(settings, "vector_s3_prefix")
        assert hasattr(settings, "vector_s3_region")
        assert hasattr(settings, "kb_storage")
        assert hasattr(settings, "kb_s3_bucket")
        assert hasattr(settings, "kb_s3_prefix")
        assert hasattr(settings, "kb_s3_region")

    def test_default_values(self):
        """Default values for new settings are sensible."""
        from agenticops.config import settings

        assert settings.deployment_profile == "local"
        assert settings.vector_storage == "sqlite"
        assert settings.kb_storage == "local"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
