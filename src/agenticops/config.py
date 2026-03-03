"""Configuration management for AgenticOps."""

import contextvars
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

    # AWS Bedrock — Tiered Model Configuration
    # Default (Opus 4.6) for main agent, RCA, SRE, executor agents
    # Cheap (Haiku 4.5) for tool-orchestration agents (scan, detect, reporter)
    # Strong (Opus 4.6) same as default; override via env for future stronger models
    bedrock_region: str = Field(
        default="us-east-1",
        description="AWS region for Bedrock",
    )
    bedrock_model_id: str = Field(
        default="global.anthropic.claude-opus-4-6-v1",
        description="Bedrock model ID — default tier for main agent and reasoning sub-agents",
    )
    bedrock_model_id_cheap: str = Field(
        default="global.anthropic.claude-haiku-4-5-20251001-v1:0",
        description="Bedrock model ID — economy tier (Haiku 4.5) for tool-orchestration agents",
    )
    bedrock_model_id_strong: str = Field(
        default="global.anthropic.claude-opus-4-6-v1",
        description="Bedrock model ID — strong tier (Opus 4.6) for complex reasoning",
    )
    bedrock_max_tokens: int = Field(
        default=16384,
        description="Max output tokens for Bedrock model responses",
    )
    bedrock_window_size: int = Field(
        default=40,
        description="Conversation manager sliding window size for agents",
    )

    # CORS
    cors_origins: str = Field(
        default="",
        description="Comma-separated allowed CORS origins (empty = dev-mode only)",
    )
    cors_max_age: int = Field(
        default=3600,
        description="CORS preflight cache duration in seconds",
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
    skills_dir: Path = Field(
        default=PROJECT_ROOT / "skills",
        description="Directory containing Agent Skills packages (SKILL.md format)",
    )
    im_apps_config: Path = Field(
        default=PROJECT_ROOT / "config" / "im-apps.yaml",
        description="Path to IM app credentials YAML (Feishu/DingTalk/WeCom)",
    )
    channels_config: Path = Field(
        default=PROJECT_ROOT / "config" / "channels.yaml",
        description="Path to notification channels YAML (sole source of truth)",
    )
    feishu_ws_enabled: bool = Field(
        default=True,
        description="Enable Feishu WebSocket long-connection (outbound, no public URL needed)",
    )
    skills_enabled: bool = Field(
        default=True,
        description="Enable Agent Skills integration (AIOPS_SKILLS_ENABLED=false to disable)",
    )
    skills_max_body_chars: int = Field(
        default=8000,
        description="Max characters for skill body content returned by activate_skill",
    )
    file_tools_admin_mode: bool = Field(
        default=True,
        description="Allow file tools to read admin paths (~/.ssh, ~/.aws, ~/.kube). "
        "Set AIOPS_FILE_TOOLS_ADMIN_MODE=false to lock down admin paths.",
    )

    # API Authentication
    api_auth_enabled: bool = Field(
        default=False,
        description="Enable API authentication (AIOPS_API_AUTH_ENABLED=true to enable)",
    )

    # Agent output detail level
    agent_output_detail: str = Field(
        default="medium",
        description="Default agent output detail level: concise, medium, or detailed",
    )

    # Executor settings (L4 Auto Operation)
    executor_enabled: bool = Field(
        #default=False,
        default=True,
        description="Enable fix execution (AIOPS_EXECUTOR_ENABLED=true to enable)",
    )
    executor_auto_approve_l0_l1: bool = Field(
        default=True,
        description="Auto-approve L0/L1 fix plans for execution",
    )
    executor_step_timeout: int = Field(
        default=300,
        description="Per-step execution timeout in seconds (default 5 min)",
    )
    executor_total_timeout: int = Field(
        default=1800,
        description="Total execution timeout in seconds (default 30 min)",
    )

    # Auto-RCA
    auto_rca_enabled: bool = Field(
        default=True,
        description="Automatically trigger RCA when a new HealthIssue is created",
    )

    # Auto-Fix Pipeline (RCA → SRE → Approve → Execute)
    auto_fix_enabled: bool = Field(
        default=True,
        description="Enable auto-fix pipeline: RCA → SRE → Approve(L0/L1) → Execute",
    )

    # Notifications
    notifications_enabled: bool = Field(
        default=True,
        description="Enable auto-notifications on pipeline events (AIOPS_NOTIFICATIONS_ENABLED=false to disable)",
    )

    # Distributed Tracing (Jaeger)
    jaeger_query_endpoint: str = Field(
        default="http://jaeger-query.monitoring:16686",
        description="Jaeger Query API endpoint for trace lookups (AIOPS_JAEGER_QUERY_ENDPOINT)",
    )
    jaeger_enabled: bool = Field(
        default=True,
        description="Enable distributed trace querying in RCA agent (AIOPS_JAEGER_ENABLED)",
    )
    jaeger_default_lookback: str = Field(
        default="1h",
        description="Default trace lookback window (AIOPS_JAEGER_DEFAULT_LOOKBACK)",
    )

    # Webhooks
    webhook_secret: str = Field(
        default="",
        description="HMAC secret for webhook signature verification (empty = disabled)",
    )
    webhook_auto_create_issue: bool = Field(
        default=True,
        description="Auto-create HealthIssue from inbound webhook alerts",
    )

    # Monitoring Providers
    monitoring_providers: str = Field(
        default="",
        description="Comma-separated active monitoring providers (e.g., 'cloudwatch,datadog')",
    )

    # Datadog Integration
    datadog_api_key: str = Field(
        default="",
        description="Datadog API key (AIOPS_DATADOG_API_KEY)",
    )
    datadog_app_key: str = Field(
        default="",
        description="Datadog Application key (AIOPS_DATADOG_APP_KEY)",
    )
    datadog_site: str = Field(
        default="datadoghq.com",
        description="Datadog site (e.g., datadoghq.com, datadoghq.eu, us5.datadoghq.com)",
    )

    # Metric Storage
    metric_storage_enabled: bool = Field(
        default=True,
        description="Auto-store queried metrics into MetricDataPoint table for trend analysis",
    )

    # RAG Pipeline
    rag_pipeline_enabled: bool = Field(
        default=True,
        description="Enable automated RAG pipeline for SOP generation/upgrade",
    )
    sop_similarity_threshold: float = Field(
        default=0.8,
        description="Similarity threshold for SOP matching (>=threshold = upgrade, <threshold = new SOP)",
    )

    # Executor Service (background polling)
    executor_poll_interval: int = Field(
        default=30,
        description="Executor service poll interval in seconds",
    )
    executor_auto_resolve: bool = Field(
        default=True,
        description="Auto-resolve HealthIssue after successful fix execution",
    )

    # Search Quality
    search_vector_weight: float = Field(
        default=0.6,
        description="Weight for vector similarity in hybrid search reranking (0-1)",
    )
    search_efficiency_weight: float = Field(
        default=0.2,
        description="Weight for efficiency score in hybrid search reranking (0-1)",
    )
    search_base_weight: float = Field(
        default=0.2,
        description="Base weight in hybrid search reranking (0-1)",
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

# ── Agent Detail Level ──────────────────────────────────────────────

VALID_DETAIL_LEVELS = ("concise", "medium", "detailed")

_detail_level_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_detail_level", default=settings.agent_output_detail
)


def get_detail_level() -> str:
    """Get the current agent output detail level from context."""
    return _detail_level_var.get()


def set_detail_level(level: str) -> contextvars.Token:
    """Set the agent output detail level in context.

    Args:
        level: One of 'concise', 'medium', or 'detailed'.

    Returns:
        Token that can be used to reset to the previous value.

    Raises:
        ValueError: If level is not valid.
    """
    if level not in VALID_DETAIL_LEVELS:
        raise ValueError(f"Invalid detail level '{level}'. Must be one of: {', '.join(VALID_DETAIL_LEVELS)}")
    return _detail_level_var.set(level)
