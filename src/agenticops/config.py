"""Configuration management for AgenticOps."""

from pathlib import Path
from typing import Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root directory (where pyproject.toml is located)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AIOPS_",
        case_sensitive=False,
    )

    # Database - use absolute path based on project root
    database_url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT}/data/agenticops.db",
        description="SQLite database URL",
    )

    # AWS Bedrock
    bedrock_region: str = Field(
        default="us-east-1",
        description="AWS region for Bedrock",
    )
    bedrock_model_id: str = Field(
        default="global.anthropic.claude-opus-4-6-v1",
        description="Bedrock model ID for LLM (Claude Ops 4.6)",
    )

    # Embedding (Titan V2)
    embedding_model_id: str = Field(
        default="amazon.titan-embed-text-v2:0",
        description="Bedrock model ID for text embeddings",
    )
    embedding_dimension: int = Field(
        default=1024,
        description="Embedding vector dimension (Titan V2 = 1024)",
    )
    embedding_enabled: bool = Field(
        default=True,
        description="Enable vector embeddings (set AIOPS_EMBEDDING_ENABLED=false to disable)",
    )

    # Monitoring
    default_metrics_period: int = Field(
        default=300,
        description="Default CloudWatch metrics period in seconds",
    )
    anomaly_detection_window: int = Field(
        default=3600,
        description="Time window for anomaly detection in seconds",
    )

    # Query Limits
    default_list_limit: int = Field(
        default=50,
        description="Default limit for list queries (resources, anomalies, etc.)",
    )
    max_list_limit: int = Field(
        default=500,
        description="Maximum allowed limit for list queries",
    )
    agent_list_limit: int = Field(
        default=50,
        description="Default limit for agent tool list operations",
    )

    # Paths - use absolute paths based on project root
    data_dir: Path = Field(
        default=PROJECT_ROOT / "data",
        description="Directory for data storage",
    )
    reports_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "reports",
        description="Directory for generated reports",
    )
    knowledge_base_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "knowledge_base",
        description="Directory for RCA knowledge base",
    )
    sops_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "knowledge_base" / "sops",
        description="Directory for Standard Operating Procedures",
    )
    cases_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "knowledge_base" / "cases",
        description="Directory for case studies",
    )
    patterns_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "knowledge_base" / "patterns",
        description="Directory for abstracted failure patterns",
    )
    sessions_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "sessions",
        description="Directory for Strands session files",
    )

    def ensure_dirs(self) -> None:
        """Ensure all required directories exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_base_dir.mkdir(parents=True, exist_ok=True)
        self.sops_dir.mkdir(parents=True, exist_ok=True)
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self.patterns_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
