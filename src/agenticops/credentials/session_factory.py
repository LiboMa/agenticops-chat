"""SessionFactory — unified session creation with environment auto-detection and caching.

Provides a single entry point for all cloud API calls:
- get_session(account_name) → authenticated boto3.Session
- get_bedrock_session() → Session for Bedrock model invocation
- get_env_for_subprocess(account_name) → env dict for AWS CLI subprocess
- detect_environment() → what kind of runtime we're in
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EnvironmentType(str, Enum):
    """Detected deployment environment."""

    EKS = "eks"          # IRSA (AWS_WEB_IDENTITY_TOKEN_FILE present)
    ECS = "ecs"          # ECS Task Role (AWS_CONTAINER_CREDENTIALS_RELATIVE_URI)
    EC2 = "ec2"          # EC2 Instance Profile (IMDSv2 reachable)
    LOCAL = "local"      # Local development (~/.aws/ or env vars)
    UNKNOWN = "unknown"


class CredentialSourceType(str, Enum):
    """How credentials are obtained for an account."""

    ENVIRONMENT = "environment"        # Use default boto3 credential chain
    ASSUME_ROLE = "assume_role"        # AssumeRole from base session
    PROFILE = "profile"                # Named AWS profile
    STATIC_KEYS = "static_keys"        # Encrypted AK/SK in DB


@dataclass
class CachedSession:
    """A cached session with TTL."""

    session: Any
    created_at: float
    ttl: float = 3600.0  # 1 hour default

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl


class SessionFactory:
    """Singleton factory for authenticated cloud sessions."""

    _instance: SessionFactory | None = None
    _lock = threading.Lock()

    def __init__(self):
        self._cache: dict[str, CachedSession] = {}
        self._environment: EnvironmentType | None = None
        self._cache_lock = threading.Lock()

    @classmethod
    def instance(cls) -> SessionFactory:
        """Get or create the singleton SessionFactory."""
        if cls._instance is not None:
            return cls._instance
        with cls._lock:
            if cls._instance is not None:
                return cls._instance
            cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def detect_environment(self) -> EnvironmentType:
        """Detect the current deployment environment.

        Priority: EKS > ECS > EC2 > LOCAL
        """
        if self._environment is not None:
            return self._environment

        # EKS: IRSA injects this env var
        if os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE"):
            self._environment = EnvironmentType.EKS
        # ECS: Task Role metadata endpoint
        elif os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
            self._environment = EnvironmentType.ECS
        # EC2: Try IMDSv2 (quick check, don't block)
        elif self._check_imdsv2():
            self._environment = EnvironmentType.EC2
        else:
            self._environment = EnvironmentType.LOCAL

        logger.info("Detected environment: %s", self._environment.value)
        return self._environment

    def get_session(
        self,
        account_name: str = "default",
        region: str | None = None,
    ) -> Any:
        """Get an authenticated boto3 Session for the given account.

        Args:
            account_name: Registered account name.
            region: Optional region override.

        Returns:
            boto3.Session configured for the account.
        """
        import boto3

        cache_key = f"{account_name}:{region or 'default'}"

        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and not cached.is_expired:
                return cached.session

        # Load account from DB
        account = self._load_account(account_name)
        if not account:
            # Fallback to default session
            logger.warning("Account '%s' not found, using default session", account_name)
            session = boto3.Session(region_name=region)
            self._cache_session(cache_key, session)
            return session

        # Resolve based on credential_source_type
        source_type = self._get_source_type(account)
        creds = account.credentials or {}

        if source_type == CredentialSourceType.ENVIRONMENT:
            session = boto3.Session(region_name=region)

        elif source_type == CredentialSourceType.PROFILE:
            profile_name = creds.get("profile_name", "default")
            session = boto3.Session(profile_name=profile_name, region_name=region)

        elif source_type == CredentialSourceType.STATIC_KEYS:
            # Decrypt credentials
            from agenticops.credentials.store import get_credential_store
            store = get_credential_store()
            plaintext = store.decrypt_credentials(creds)
            session = boto3.Session(
                aws_access_key_id=plaintext.get("access_key_id"),
                aws_secret_access_key=plaintext.get("secret_access_key"),
                aws_session_token=plaintext.get("session_token"),
                region_name=region,
            )

        elif source_type == CredentialSourceType.ASSUME_ROLE:
            # Decrypt credentials before passing to assume_role
            from agenticops.credentials.store import get_credential_store, _ENCRYPTED_KEY
            if _ENCRYPTED_KEY in creds:
                store = get_credential_store()
                creds = store.decrypt_credentials(creds)
            session = self._assume_role_session(creds, region)

        else:
            session = boto3.Session(region_name=region)

        self._cache_session(cache_key, session)
        return session

    def get_bedrock_session(self) -> Any:
        """Get a Session configured for Bedrock API calls (Layer 1).

        Credential resolution order:
        1. AIOPS_BEDROCK_ROLE_ARN → AssumeRole (cross-account Bedrock)
        2. AIOPS_BEDROCK_ACCESS_KEY_ID + SECRET → explicit static keys
        3. AIOPS_BEDROCK_PROFILE → named AWS profile
        4. Default credential chain (env vars, IRSA, Task Role, Instance Profile, ~/.aws/)
        """
        import boto3
        from agenticops.config import settings

        cache_key = f"__bedrock__:{settings.bedrock_region}"

        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and not cached.is_expired:
                return cached.session

        bedrock_role = os.environ.get("AIOPS_BEDROCK_ROLE_ARN")
        if bedrock_role:
            # Cross-account Bedrock: assume role
            session = self._assume_role_session(
                {"role_arn": bedrock_role},
                settings.bedrock_region,
            )
        elif settings.bedrock_access_key_id and settings.bedrock_secret_access_key:
            # Explicit static keys for Bedrock
            session = boto3.Session(
                aws_access_key_id=settings.bedrock_access_key_id,
                aws_secret_access_key=settings.bedrock_secret_access_key,
                region_name=settings.bedrock_region,
            )
        elif settings.bedrock_profile:
            # Named profile for Bedrock — bypass AWS_CONFIG_FILE/AWS_SHARED_CREDENTIALS_FILE
            # overrides that may block profile resolution
            import botocore.exceptions
            import botocore.session
            bc_session = botocore.session.Session()
            # Force real config paths if env vars point to /dev/null
            real_creds = str(Path.home() / ".aws" / "credentials")
            real_config = str(Path.home() / ".aws" / "config")
            if os.environ.get("AWS_SHARED_CREDENTIALS_FILE") in ("/dev/null", ""):
                bc_session.set_config_variable("credentials_file", real_creds)
            if os.environ.get("AWS_CONFIG_FILE") in ("/dev/null", ""):
                bc_session.set_config_variable("config_file", real_config)
            bc_session.set_config_variable("profile", settings.bedrock_profile)
            try:
                session = boto3.Session(
                    botocore_session=bc_session,
                    region_name=settings.bedrock_region,
                )
                # Force profile resolution now so we can fall back if it's missing
                # (e.g. on EC2 where the instance role should be used instead).
                session.get_credentials()
            except botocore.exceptions.ProfileNotFound:
                logger.warning(
                    "Bedrock profile %r not found; falling back to default "
                    "credential chain (env/IRSA/ECS/EC2 instance role).",
                    settings.bedrock_profile,
                )
                session = boto3.Session(region_name=settings.bedrock_region)
        else:
            # Default credential chain
            session = boto3.Session(region_name=settings.bedrock_region)

        self._cache_session(cache_key, session)
        return session

    def get_env_for_subprocess(self, account_name: str, region: str | None = None) -> dict[str, str]:
        """Get environment variables for AWS CLI subprocess calls.

        Args:
            account_name: Account to get credentials for.
            region: Optional region override.

        Returns:
            Dict of env vars including AWS_ACCESS_KEY_ID, etc.
        """
        session = self.get_session(account_name, region)
        env = os.environ.copy()

        try:
            frozen = session.get_credentials().get_frozen_credentials()
            env["AWS_ACCESS_KEY_ID"] = frozen.access_key
            env["AWS_SECRET_ACCESS_KEY"] = frozen.secret_key
            if frozen.token:
                env["AWS_SESSION_TOKEN"] = frozen.token
            if region:
                env["AWS_DEFAULT_REGION"] = region
        except Exception as e:
            logger.warning("Failed to extract credentials for subprocess: %s", e)

        # Remove profile to avoid conflicts
        env.pop("AWS_PROFILE", None)
        return env

    def invalidate(self, account_name: str | None = None) -> None:
        """Invalidate cached sessions.

        Args:
            account_name: Specific account to invalidate. None = clear all.
        """
        with self._cache_lock:
            if account_name is None:
                self._cache.clear()
            else:
                keys_to_remove = [k for k in self._cache if k.startswith(f"{account_name}:")]
                for k in keys_to_remove:
                    del self._cache[k]

    def list_available_profiles(self) -> list[str]:
        """List AWS profiles available on the server.

        Reads ~/.aws/credentials and ~/.aws/config to find profile names.
        """
        from pathlib import Path
        import configparser

        profiles: set[str] = set()
        aws_dir = Path.home() / ".aws"

        for filename in ["credentials", "config"]:
            filepath = aws_dir / filename
            if not filepath.exists():
                continue
            try:
                parser = configparser.ConfigParser()
                parser.read(str(filepath))
                for section in parser.sections():
                    # In config file, profiles are "profile xxx" (except default)
                    name = section.replace("profile ", "") if section.startswith("profile ") else section
                    profiles.add(name)
            except Exception as e:
                logger.warning("Failed to parse %s: %s", filepath, e)

        return sorted(profiles)

    def test_connection(self, account_name: str) -> dict[str, Any]:
        """Test connectivity for an account.

        Returns:
            {"success": bool, "identity": str|None, "error": str|None}
        """
        try:
            # Use the account's first configured region as STS endpoint
            account = self._load_account(account_name)
            sts_region = (account.regions[0] if account and account.regions else None)

            session = self.get_session(account_name, region=sts_region)
            sts_kwargs: dict[str, str] = {"region_name": sts_region} if sts_region else {}
            sts = session.client("sts", **sts_kwargs)
            identity = sts.get_caller_identity()
            return {
                "success": True,
                "identity": identity["Arn"],
                "account_id": identity["Account"],
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "identity": None,
                "account_id": None,
                "error": str(e),
            }

    # ── Private helpers ────────────────────────────────────────────────

    def _assume_role_session(self, creds: dict, region: str | None = None) -> Any:
        """Create a session by assuming a role."""
        import boto3

        role_arn = creds.get("role_arn", "")
        external_id = creds.get("external_id", "")
        base_profile = creds.get("base_profile")

        # STS region: caller passes the account's configured region
        sts_region = region

        # Build base session: AK/SK from creds > profile > default chain
        ak = creds.get("access_key_id")
        sk = creds.get("secret_access_key")
        if ak and sk:
            base = boto3.Session(
                aws_access_key_id=ak,
                aws_secret_access_key=sk,
                aws_session_token=creds.get("session_token"),
            )
        elif base_profile:
            base = boto3.Session(profile_name=base_profile)
        else:
            base = boto3.Session()

        # AssumeRole
        sts_kwargs: dict = {}
        if sts_region:
            sts_kwargs["region_name"] = sts_region

        sts = base.client("sts", **sts_kwargs)
        assume_kwargs: dict = {
            "RoleArn": role_arn,
            "RoleSessionName": "agenticops-session",
        }
        if external_id:
            assume_kwargs["ExternalId"] = external_id

        resp = sts.assume_role(**assume_kwargs)
        assumed = resp["Credentials"]

        return boto3.Session(
            aws_access_key_id=assumed["AccessKeyId"],
            aws_secret_access_key=assumed["SecretAccessKey"],
            aws_session_token=assumed["SessionToken"],
            region_name=region,
        )

    def _cache_session(self, key: str, session: Any) -> None:
        """Cache a session with TTL."""
        with self._cache_lock:
            self._cache[key] = CachedSession(
                session=session,
                created_at=time.time(),
            )

    def _load_account(self, account_name: str) -> Any | None:
        """Load a CloudAccount from DB by name."""
        try:
            from agenticops.models import CloudAccount, get_db_session

            with get_db_session() as db:
                account = db.query(CloudAccount).filter_by(name=account_name).first()
                if account:
                    # Detach to avoid session issues
                    from types import SimpleNamespace
                    return SimpleNamespace(
                        id=account.id,
                        name=account.name,
                        provider=account.provider,
                        credentials=dict(account.credentials or {}),
                        regions=list(account.regions or []),
                        credential_source_type=getattr(account, "credential_source_type", "environment"),
                    )
            return None
        except Exception as e:
            logger.warning("Failed to load account '%s': %s", account_name, e)
            return None

    def _get_source_type(self, account: Any) -> CredentialSourceType:
        """Determine credential source type from account."""
        # Explicit type field
        source_type = getattr(account, "credential_source_type", None)
        if source_type:
            try:
                return CredentialSourceType(source_type)
            except ValueError:
                pass

        # Infer from credentials content (backwards compatibility)
        creds = account.credentials or {}
        if creds.get("_encrypted"):
            return CredentialSourceType.STATIC_KEYS
        if creds.get("role_arn"):
            return CredentialSourceType.ASSUME_ROLE
        if creds.get("profile_name"):
            return CredentialSourceType.PROFILE
        if creds.get("access_key_id"):
            return CredentialSourceType.STATIC_KEYS
        return CredentialSourceType.ENVIRONMENT

    @staticmethod
    def _check_imdsv2() -> bool:
        """Quick check if EC2 IMDSv2 is reachable (1s timeout)."""
        import urllib.request

        try:
            req = urllib.request.Request(
                "http://169.254.169.254/latest/api/token",
                method="PUT",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "5"},
            )
            urllib.request.urlopen(req, timeout=1)
            return True
        except Exception:
            return False


# ── Module-level accessor ──────────────────────────────────────────────

def get_session_factory() -> SessionFactory:
    """Get the SessionFactory singleton."""
    return SessionFactory.instance()
