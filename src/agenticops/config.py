"""Configuration management for AgenticOps.

Settings are loaded with the following priority (highest wins):
  1. Environment variables (AIOPS_* prefix)
  2. .env file
  3. config/settings.yaml
  4. Field defaults (bare-minimum fallbacks)
"""

import contextvars
import uuid
from pathlib import Path
from typing import Any, Optional, Tuple, Type

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Project root directory (where pyproject.toml is located)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

# Default YAML config path (can be overridden via AIOPS_CONFIG_FILE env var)
_YAML_CONFIG_PATH = Path(__import__("os").environ.get(
    "AIOPS_CONFIG_FILE",
    str(PROJECT_ROOT / "config" / "settings.yaml"),
))


class YamlSettingsSource(PydanticBaseSettingsSource):
    """Load settings from a YAML file."""

    def __init__(self, settings_cls: Type[BaseSettings]):
        super().__init__(settings_cls)
        self._yaml_data: dict[str, Any] = {}
        if _YAML_CONFIG_PATH.is_file():
            with open(_YAML_CONFIG_PATH) as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    self._yaml_data = data

    def get_field_value(self, field: Any, field_name: str) -> Tuple[Any, str, bool]:
        val = self._yaml_data.get(field_name)
        return val, field_name, val is not None

    def __call__(self) -> dict[str, Any]:
        return {k: v for k, v in self._yaml_data.items()}


class Settings(BaseSettings):
    """Application settings.

    Loaded from: env vars > .env > config/settings.yaml > Field defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AIOPS_",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlSettingsSource(settings_cls),
            file_secret_settings,
        )

    # Database - use absolute path based on project root
    database_url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT}/data/agenticops.db",
        description="SQLite database URL",
    )

    # AWS Bedrock — Three-Tier Model Configuration
    # Default (Sonnet 4.6) for main agent router and executor
    # Cheap (Haiku 4.5) for tool-orchestration agents (scan, detect, reporter)
    # Strong (Opus 4.6) for complex reasoning agents (RCA, SRE)
    bedrock_region: str = Field(
        default="us-east-1",
        description="AWS region for Bedrock",
    )
    bedrock_model_id: str = Field(
        default="global.anthropic.claude-sonnet-4-6",
        description="Bedrock model ID — default tier for main agent router and executor",
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

    # Model aliases — friendly names for /model command and Settings UI dropdowns
    # These are INDEPENDENT of tier defaults. Changing bedrock_model_id does NOT
    # change what "sonnet" means.
    model_aliases: dict[str, str] = Field(
        default={
            "opus": "global.anthropic.claude-opus-4-6-v1",
            "sonnet": "global.anthropic.claude-sonnet-4-6",
            "haiku": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        },
        description="Friendly name → model ID mapping for /model command and UI dropdowns",
    )

    # Per-agent model configuration (set explicitly in settings.yaml)
    agent_main_model_id: str = Field(default="", description="Model for main agent")
    agent_scan_model_id: str = Field(default="", description="Model for scan agent")
    agent_detect_model_id: str = Field(default="", description="Model for detect agent")
    agent_rca_model_id: str = Field(default="", description="Model for RCA agent")
    agent_sre_model_id: str = Field(default="", description="Model for SRE agent")
    agent_executor_model_id: str = Field(default="", description="Model for executor agent")
    agent_reporter_model_id: str = Field(default="", description="Model for reporter agent")

    # Per-agent max_tokens (0 = use bedrock_max_tokens)
    agent_main_max_tokens: int = Field(default=0, description="Max tokens for main agent (0 = bedrock_max_tokens)")
    agent_scan_max_tokens: int = Field(default=0, description="Max tokens for scan agent")
    agent_detect_max_tokens: int = Field(default=0, description="Max tokens for detect agent")
    agent_rca_max_tokens: int = Field(default=0, description="Max tokens for RCA agent")
    agent_sre_max_tokens: int = Field(default=0, description="Max tokens for SRE agent")
    agent_executor_max_tokens: int = Field(default=0, description="Max tokens for executor agent")
    agent_reporter_max_tokens: int = Field(default=0, description="Max tokens for reporter agent")

    # Prompt caching toggle
    bedrock_cache_enabled: bool = Field(default=True, description="Enable Bedrock prompt caching on all agents")

    # Notification consolidation
    notifications_consolidated: bool = Field(
        default=False,
        description="Send single pipeline summary instead of per-stage notifications",
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

    # Report storage backend
    report_storage: str = Field(
        default="local",
        description="Report storage backend: 'local' or 's3' (AIOPS_REPORT_STORAGE)",
    )
    report_s3_bucket: str = Field(
        default="",
        description="S3 bucket for report storage (AIOPS_REPORT_S3_BUCKET)",
    )
    report_s3_prefix: str = Field(
        default="reports/",
        description="S3 key prefix for reports (AIOPS_REPORT_S3_PREFIX)",
    )
    report_s3_region: str = Field(
        default="us-east-1",
        description="S3 region for report storage (AIOPS_REPORT_S3_REGION)",
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
    mcp_servers_config: Path = Field(
        default=PROJECT_ROOT / "config" / "mcp-servers.json",
        description="Path to MCP servers JSON config (standard mcpServers format)",
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
        description="Enable Feishu WebSocket long-connection (AIOPS_FEISHU_WS_ENABLED=true)",
    )
    slack_ws_enabled: bool = Field(
        default=False,
        description="Enable Slack Socket Mode (AIOPS_SLACK_WS_ENABLED=true)",
    )
    skills_draft_dir: Path = Field(
        default=PROJECT_ROOT / "skills" / "draft",
        description="Directory for draft/generated skills (AIOPS_SKILLS_DRAFT_DIR)",
    )
    skills_enabled: bool = Field(
        default=True,
        description="Enable Agent Skills integration (AIOPS_SKILLS_ENABLED=false to disable)",
    )
    clawhub_enabled: bool = Field(
        default=False,
        description="Enable ClawHub skill registry integration (AIOPS_CLAWHUB_ENABLED)",
    )
    clawhub_token: str = Field(
        default="",
        description="ClawHub API token for skill registry (AIOPS_CLAWHUB_TOKEN)",
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

    # Scan focus — resource category filter
    scan_focus: str = Field(
        default="all",
        description="Default resource focus for scan/detect: computing,networking,databases,storage,security,billing,all (AIOPS_SCAN_FOCUS)",
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

    # Resource-Based Dedup
    resource_dedup_enabled: bool = Field(
        default=True,
        description="Enable resource-based similar issue merging (AIOPS_RESOURCE_DEDUP_ENABLED)",
    )

    # Notifications
    notifications_enabled: bool = Field(
        default=True,
        description="Enable auto-notifications on pipeline events (AIOPS_NOTIFICATIONS_ENABLED=false to disable)",
    )

    # IM Alert Detection
    im_alert_detection_enabled: bool = Field(
        default=True,
        description="Enable channel-based alert detection in IM messages (AIOPS_IM_ALERT_DETECTION_ENABLED)",
    )
    im_alert_cooldown_seconds: int = Field(
        default=60,
        description="Cooldown window in seconds for IM alert dedup (AIOPS_IM_ALERT_COOLDOWN_SECONDS)",
    )
    alert_pipeline_mode: str = Field(
        default="both",
        description=(
            "Active alert pipeline mode: 'event_driven' (webhook only), "
            "'channel_driven' (IM Agent only), or 'both' (AIOPS_ALERT_PIPELINE_MODE)"
        ),
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

    # Graph Sync
    graph_sync_enabled: bool = Field(
        default=True,
        description="Enable background graph sync service (AIOPS_GRAPH_SYNC_ENABLED)",
    )
    graph_sync_interval_minutes: int = Field(
        default=15,
        description="Graph sync interval in minutes (AIOPS_GRAPH_SYNC_INTERVAL_MINUTES)",
    )
    graph_node_ttl_hours: int = Field(
        default=24,
        description="TTL in hours for stale graph node cleanup (AIOPS_GRAPH_NODE_TTL_HOURS)",
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

# ── Per-Agent Model Config ─────────────────────────────────────────

AGENT_NAMES = ("main", "scan", "detect", "rca", "sre", "executor", "reporter")

# Friendly name → model ID aliases (from settings.model_aliases, loaded via YAML)
# Independent of tier defaults — "sonnet" always means Sonnet regardless of bedrock_model_id
MODEL_ALIASES: dict[str, str] = dict(settings.model_aliases)

# Tier fallback — only used when agent_X_model_id is empty (safety net)
AGENT_TIER_DEFAULTS: dict[str, str] = {
    "main": "bedrock_model_id",
    "scan": "bedrock_model_id_cheap",
    "detect": "bedrock_model_id_cheap",
    "rca": "bedrock_model_id_strong",
    "sre": "bedrock_model_id_strong",
    "executor": "bedrock_model_id",
    "reporter": "bedrock_model_id_cheap",
}


def get_agent_model_config(agent_name: str) -> tuple[str, int]:
    """Return (model_id, max_tokens) for a given agent.

    Reads from agent_X_model_id (set in settings.yaml).
    Falls back to tier default only if the field is empty.
    """
    model_id = getattr(settings, f"agent_{agent_name}_model_id", "")
    if not model_id:
        tier_field = AGENT_TIER_DEFAULTS.get(agent_name, "bedrock_model_id")
        model_id = getattr(settings, tier_field)
    max_tokens = getattr(settings, f"agent_{agent_name}_max_tokens", 0)
    if max_tokens <= 0:
        max_tokens = settings.bedrock_max_tokens
    return model_id, max_tokens


def save_to_yaml(keys: dict[str, Any]) -> None:
    """Persist specific settings back to config/settings.yaml (CLI use only).

    Reads the existing YAML, merges the provided keys, and writes back.
    Web API should NOT call this — Web changes are session-level only.
    """
    yaml_path = _YAML_CONFIG_PATH
    data: dict[str, Any] = {}
    if yaml_path.is_file():
        with open(yaml_path) as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = loaded
    data.update(keys)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(yaml_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


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


# ── Scan Focus (resource category filter) ─────────────────────────────

VALID_SCAN_FOCUS = ("computing", "networking", "databases", "storage", "security", "billing", "all")

SCAN_FOCUS_SERVICES = {
    "computing": "EC2,Lambda,ECS,EKS,AutoScaling",
    "networking": "VPC,Subnet,SecurityGroup,RouteTable,NATGateway,TransitGateway,ELB,CloudFront,Route53",
    "databases": "RDS,DynamoDB,ElastiCache,Redshift,OpenSearch",
    "storage": "S3,EBS,EFS,Backup",
    "security": "security",
    "billing": "billing",
    "all": "all",
}

_scan_focus_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "scan_focus", default=settings.scan_focus
)


def get_scan_focus() -> str:
    """Get the current scan focus from context."""
    return _scan_focus_var.get()


def set_scan_focus(focus: str) -> contextvars.Token:
    """Set the scan focus in context.

    Args:
        focus: Comma-separated values from VALID_SCAN_FOCUS (e.g., 'computing,security').

    Returns:
        Token that can be used to reset to the previous value.

    Raises:
        ValueError: If any value is not valid.
    """
    parts = [p.strip() for p in focus.lower().split(",") if p.strip()]
    for p in parts:
        if p not in VALID_SCAN_FOCUS:
            raise ValueError(f"Invalid scan focus '{p}'. Must be one of: {', '.join(VALID_SCAN_FOCUS)}")
    normalised = ",".join(parts) if parts else "all"
    return _scan_focus_var.set(normalised)


def resolve_scan_services(focus: str) -> str:
    """Resolve a scan focus string to a comma-joined service list.

    Args:
        focus: Comma-separated focus categories (e.g., 'computing,databases').

    Returns:
        Comma-joined AWS service names.
    """
    parts = [p.strip() for p in focus.lower().split(",") if p.strip()]
    if not parts or "all" in parts:
        return "all"
    services: list[str] = []
    for p in parts:
        svc = SCAN_FOCUS_SERVICES.get(p)
        if svc and svc not in services:
            services.append(svc)
    return ",".join(services) if services else "all"


# ── IM Origin context (set by IM handlers, read by create_health_issue) ──

_im_origin_var: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "im_origin", default=None
)


def get_im_origin() -> Optional[dict]:
    """Get the current IM origin context (platform + chat_id)."""
    return _im_origin_var.get()


def set_im_origin(origin: Optional[dict]) -> contextvars.Token:
    """Set IM origin context for the current agent invocation.

    Args:
        origin: dict with 'platform' and 'chat_id' keys, or None to clear.
    """
    return _im_origin_var.set(origin)


# ── Pipeline Trace ID (set at alert entry, propagates through pipeline) ──

_trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "pipeline_trace_id", default=None
)


def generate_trace_id() -> str:
    """Generate a new pipeline trace ID (TRC-{8 hex chars})."""
    return f"TRC-{uuid.uuid4().hex[:8]}"


def get_trace_id() -> Optional[str]:
    """Get the current pipeline trace ID from context."""
    return _trace_id_var.get()


def set_trace_id(trace_id: Optional[str]) -> contextvars.Token:
    """Set the pipeline trace ID in context."""
    return _trace_id_var.set(trace_id)
