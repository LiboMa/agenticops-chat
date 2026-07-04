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

# Project root directory — env var takes priority, then auto-detect from source tree
PROJECT_ROOT = Path(
    __import__("os").environ.get("AIOPS_PROJECT_ROOT", "")
    or str(Path(__file__).parent.parent.parent.resolve())
)

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
    bedrock_profile: str = Field(
        default="",
        description="AWS profile name for Bedrock access (Layer 1). Empty = use default credential chain.",
    )
    bedrock_access_key_id: str = Field(
        default="",
        description="Explicit AWS Access Key for Bedrock (Layer 1). Takes priority over profile/default chain.",
    )
    bedrock_secret_access_key: str = Field(
        default="",
        description="Explicit AWS Secret Key for Bedrock (Layer 1).",
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
    custom_models: list[dict] = Field(
        default_factory=list,
        description="Additional models for presets (list of {model_id, label, context_window})",
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

    # Per-agent sliding window size (0 = use bedrock_window_size)
    agent_main_window_size: int = Field(default=0, description="Window size for main agent (0 = bedrock_window_size)")
    agent_scan_window_size: int = Field(default=0, description="Window size for scan agent")
    agent_detect_window_size: int = Field(default=0, description="Window size for detect agent")
    agent_rca_window_size: int = Field(default=0, description="RCA agent window — larger for deep investigations")
    agent_sre_window_size: int = Field(default=0, description="SRE agent window — larger for referencing RCA findings")
    agent_executor_window_size: int = Field(default=0, description="Executor agent window")
    agent_reporter_window_size: int = Field(default=0, description="Reporter agent window")

    # Prompt caching toggle
    bedrock_cache_enabled: bool = Field(default=True, description="Enable Bedrock prompt caching on all agents")

    # CLI tool output limit (0 = unlimited)
    cli_max_output_chars: int = Field(default=0, description="Max chars for CLI tool output (0 = no limit)")

    # Notification consolidation
    notifications_consolidated: bool = Field(
        default=True,
        description="Suppress per-issue notifications during Scan/Detect/RCA — only final report is sent. Set False for dev/debug to see every notification.",
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
    report_presigned_url_expiry: int = Field(
        default=604800,
        description="Presigned URL expiry in seconds for report download links (default 7 days)",
    )

    # Deployment profile
    deployment_profile: str = Field(
        default="local",
        description="Deployment profile: 'local' or 'cloud'",
    )

    # Vector store backend
    vector_storage: str = Field(
        default="sqlite",
        description="Vector storage backend: 'sqlite', 'rds', or 's3'",
    )
    vector_rds_url: str = Field(
        default="",
        description="PostgreSQL URL for vector storage (when vector_storage=rds)",
    )
    vector_s3_bucket: str = Field(
        default="",
        description="S3 bucket for vector storage",
    )
    vector_s3_prefix: str = Field(
        default="vectors/",
        description="S3 key prefix for vector storage",
    )
    vector_s3_region: str = Field(
        default="us-east-1",
        description="S3 region for vector storage",
    )

    # Knowledge base storage backend
    kb_storage: str = Field(
        default="local",
        description="KB storage backend: 'local' or 's3'",
    )
    kb_s3_bucket: str = Field(
        default="",
        description="S3 bucket for KB storage",
    )
    kb_s3_prefix: str = Field(
        default="knowledge_base/",
        description="S3 key prefix for KB storage",
    )
    kb_s3_region: str = Field(
        default="us-east-1",
        description="S3 region for KB storage",
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
        default=False,
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
    skills_auto_improve_enabled: bool = Field(
        default=True,
        description="Master switch for skill self-improvement features (AIOPS_SKILLS_AUTO_IMPROVE_ENABLED)",
    )
    skills_post_resolution_review: bool = Field(
        default=True,
        description="Auto-review skills after issue resolution for gaps (AIOPS_SKILLS_POST_RESOLUTION_REVIEW)",
    )
    skills_improvement_notify: bool = Field(
        default=True,
        description="Notify when skill improvement drafts are created (AIOPS_SKILLS_IMPROVEMENT_NOTIFY)",
    )
    skills_autonomous_write: bool = Field(
        default=True,
        description="Allow agents to self-create/improve skills via skill_manage (drafts only) (AIOPS_SKILLS_AUTONOMOUS_WRITE)",
    )
    skills_curator_enabled: bool = Field(
        default=True,
        description="Enable the skills Curator lifecycle (agent drafts stale/archive; human skills pinned) (AIOPS_SKILLS_CURATOR_ENABLED)",
    )
    skills_draft_stale_days: int = Field(
        default=30,
        description="Days an unused agent draft stays before becoming stale (AIOPS_SKILLS_DRAFT_STALE_DAYS)",
    )
    skills_draft_archive_days: int = Field(
        default=60,
        description="Additional days after stale before an agent draft is archived (AIOPS_SKILLS_DRAFT_ARCHIVE_DAYS)",
    )
    skills_security_scan_on_promote: bool = Field(
        default=True,
        description="Security-scan a skill before promoting draft->published (blocks dangerous run_on_host) (AIOPS_SKILLS_SECURITY_SCAN_ON_PROMOTE)",
    )

    # ── ACP Enhanced Backend (MVP-1.3.0, optional) ─────────────────
    acp_enhanced_enabled: bool = Field(
        default=False,
        description="Enable the optional ACP enhanced-task backend (delegates complex tasks to Claude Code/Kiro) (AIOPS_ACP_ENHANCED_ENABLED)",
    )
    acp_enhanced_backend: str = Field(
        default="claude-code",
        description="Default enhanced backend provider name (AIOPS_ACP_ENHANCED_BACKEND)",
    )
    acp_claude_command: str = Field(
        default="npx",
        description="Launch command for the Claude Code ACP agent (AIOPS_ACP_CLAUDE_COMMAND)",
    )
    acp_claude_args: list[str] = Field(
        default_factory=lambda: ["-y", "@agentclientprotocol/claude-agent-acp"],
        description="Args for the Claude Code ACP agent launch; -y auto-confirms npx install (AIOPS_ACP_CLAUDE_ARGS)",
    )
    acp_use_bedrock: bool = Field(
        default=True,
        description="Run the enhanced backend on Bedrock (CLAUDE_CODE_USE_BEDROCK=1) (AIOPS_ACP_USE_BEDROCK)",
    )
    acp_timeout_seconds: int = Field(
        default=300,
        description="Per-turn timeout for an enhanced-backend subprocess (AIOPS_ACP_TIMEOUT_SECONDS)",
    )
    acp_auto_approve_permissions: bool = Field(
        default=True,
        description="Auto-approve the backend's permission requests (allow_once) this round (AIOPS_ACP_AUTO_APPROVE_PERMISSIONS)",
    )
    acp_kiro_command: str = Field(
        default="kiro-cli",
        description="Launch command for the Kiro CLI ACP agent (AIOPS_ACP_KIRO_COMMAND)",
    )
    acp_kiro_args: list[str] = Field(
        default_factory=lambda: ["acp", "--trust-all-tools"],
        description="Args for the Kiro CLI ACP agent launch; --trust-all-tools auto-approves (AIOPS_ACP_KIRO_ARGS)",
    )
    acp_codex_command: str = Field(
        default="npx",
        description="Launch command for the Codex ACP agent (AIOPS_ACP_CODEX_COMMAND)",
    )
    acp_codex_args: list[str] = Field(
        default_factory=lambda: ["-y", "@zed-industries/codex-acp"],
        description="Args for the Codex ACP agent launch; needs OPENAI_API_KEY (AIOPS_ACP_CODEX_ARGS)",
    )

    file_tools_admin_mode: bool = Field(
        default=True,
        description="Allow file tools to read admin paths (~/.ssh, ~/.aws, ~/.kube). "
        "Set AIOPS_FILE_TOOLS_ADMIN_MODE=false to lock down admin paths.",
    )

    # ── Agent Memory (cycle② self-optimizing) ──────────────────────
    memory_max_active: int = Field(
        default=15,
        description="Max active memories per agent before size-cap forces merge (AIOPS_MEMORY_MAX_ACTIVE)",
    )
    memory_stale_days: int = Field(
        default=30,
        description="Days since last_used before a memory becomes 'stale' (not injected) (AIOPS_MEMORY_STALE_DAYS)",
    )
    memory_archive_days: int = Field(
        default=60,
        description="Additional days after stale before a memory is archived (AIOPS_MEMORY_ARCHIVE_DAYS)",
    )
    memory_autonomous_write: bool = Field(
        default=True,
        description="Allow agents to self-create/patch memories via memory_manage (AIOPS_MEMORY_AUTONOMOUS_WRITE)",
    )
    memory_curator_enabled: bool = Field(
        default=True,
        description="Enable the background Curator lifecycle (stale/archive/reactivate) (AIOPS_MEMORY_CURATOR_ENABLED)",
    )

    # API Authentication
    api_auth_enabled: bool = Field(
        default=False,
        description="Enable API authentication (AIOPS_API_AUTH_ENABLED=true to enable)",
    )
    admin_password: str = Field(
        default="aiops2026",
        description="Default admin password for initial seed",
    )

    # Issue exclude patterns — regex patterns to suppress issue creation
    issue_exclude_patterns: list[str] = Field(default_factory=list)

    # Scan focus — resource category filter
    scan_focus: str = Field(
        default="all",
        description="Default resource focus for scan/detect: computing,networking,databases,storage,security,billing,all (AIOPS_SCAN_FOCUS)",
    )

    # Executor settings (L4 Auto Operation)
    executor_enabled: bool = Field(
        default=True,
        description="Enable fix execution (AIOPS_EXECUTOR_ENABLED=true to enable)",
    )
    executor_smart_model: bool = Field(
        default=True,
        description="Use cheaper model for L0/L1 fixes (AIOPS_EXECUTOR_SMART_MODEL)",
    )
    executor_simple_model_id: str = Field(
        default="global.anthropic.claude-sonnet-4-6",
        description="Model for L0/L1 executor when executor_smart_model=True",
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

    # Host access ladder (SSM → SSH fallback for run_on_host method="auto")
    ssh_default_user: str = Field(
        default="",
        description="Default SSH username for run_on_host SSH fallback (AIOPS_SSH_DEFAULT_USER)",
    )
    ssh_default_key_path: str = Field(
        default="",
        description="Default SSH private key path for run_on_host SSH fallback (AIOPS_SSH_DEFAULT_KEY_PATH)",
    )
    ssh_bastion_host: str = Field(
        default="",
        description="Optional ProxyJump bastion (e.g. user@bastion) for SSH fallback (AIOPS_SSH_BASTION_HOST)",
    )

    # Auto-RCA
    auto_rca_enabled: bool = Field(
        default=True,
        description="Automatically trigger RCA when a new HealthIssue is created",
    )

    # ── Prevention (graph-based proactive checks) ────────────────────
    patrol_graph_checks_enabled: bool = Field(
        default=True,
        description="Run SPOF + capacity-risk graph analysis during health patrol "
        "(AIOPS_PATROL_GRAPH_CHECKS_ENABLED)",
    )
    rca_topology_context_enabled: bool = Field(
        default=True,
        description="Inject topology context (neighbors, blast radius, recent graph "
        "changes) into RCA invocations (AIOPS_RCA_TOPOLOGY_CONTEXT_ENABLED)",
    )

    # Auto-Fix Pipeline (RCA → SRE → Approve → Execute)
    auto_fix_enabled: bool = Field(
        default=True,
        description="Enable auto-fix pipeline: RCA → SRE → Approve(L0/L1) → Execute",
    )

    # ── Governed Autonomy (MVP-2.0.0) ───────────────────────────────
    policy_engine_enabled: bool = Field(
        default=True,
        description="Use the declarative policy engine for fix-plan approval decisions; "
        "false = legacy hardcoded L0/L1 auto-approve (AIOPS_POLICY_ENGINE_ENABLED)",
    )
    policy_file: str = Field(
        default="config/policies.yaml",
        description="Path to the governed-autonomy policy file (AIOPS_POLICY_FILE)",
    )

    # ── ITSM Bridge (MVP-2.0.0) ─────────────────────────────────────
    itsm_enabled: bool = Field(
        default=False,
        description="Mirror issue/fix lifecycle into ITSM (ServiceNow/Jira) (AIOPS_ITSM_ENABLED)",
    )
    itsm_dry_run: bool = Field(
        default=True,
        description="Log intended ITSM API calls instead of sending them (AIOPS_ITSM_DRY_RUN)",
    )
    itsm_servicenow_url: str = Field(
        default="",
        description="ServiceNow instance URL, e.g. https://acme.service-now.com (AIOPS_ITSM_SERVICENOW_URL)",
    )
    itsm_servicenow_user: str = Field(
        default="",
        description="ServiceNow integration user (AIOPS_ITSM_SERVICENOW_USER)",
    )
    itsm_servicenow_password: str = Field(
        default="",
        description="ServiceNow integration password — prefer env var (AIOPS_ITSM_SERVICENOW_PASSWORD)",
    )
    itsm_jira_url: str = Field(
        default="",
        description="Jira site URL, e.g. https://acme.atlassian.net (AIOPS_ITSM_JIRA_URL)",
    )
    itsm_jira_email: str = Field(
        default="",
        description="Jira account email for Basic auth (AIOPS_ITSM_JIRA_EMAIL)",
    )
    itsm_jira_api_token: str = Field(
        default="",
        description="Jira API token — prefer env var (AIOPS_ITSM_JIRA_API_TOKEN)",
    )
    itsm_jira_project_key: str = Field(
        default="OPS",
        description="Jira project key for incidents/changes (AIOPS_ITSM_JIRA_PROJECT_KEY)",
    )

    # Resource-Based Dedup
    resource_dedup_enabled: bool = Field(
        default=True,
        description="Enable resource-based similar issue merging (AIOPS_RESOURCE_DEDUP_ENABLED)",
    )
    dedup_resolved_cooldown_minutes: int = Field(
        default=60,
        description="Minutes after issue resolution before same fingerprint can create new issue (AIOPS_DEDUP_RESOLVED_COOLDOWN_MINUTES)",
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

    # Session TTL
    session_ttl_minutes: int = Field(
        default=30,
        description="Agent instance TTL in minutes before cleanup",
    )

    # Session history restoration
    session_history_depth: int = Field(
        default=20,
        description="Number of recent message turns to restore when recreating a chat session agent",
    )

    # Token cost rates per 1M tokens by model family
    token_cost_table: dict[str, dict[str, float]] = Field(
        default={
            "claude-opus-4-8":   {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
            "claude-opus-4-6":   {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
            "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
            "claude-haiku-4-5":  {"input": 0.80, "output": 4.0,  "cache_read": 0.08, "cache_write": 1.00},
        },
        description="Token cost rates per 1M tokens by model family",
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

    # Web base URL (for CLI reference links)
    web_base_url: str = Field(default="http://localhost:8000")

    # Default regions per cloud provider (for account creation UI)
    default_regions: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Default regions per cloud provider for account creation UI",
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

# Sentinel: use NullConversationManager (keep full context, no sliding window)
FULL_CONTEXT = -1

# Per-model-family window size defaults (used when agent_X_window_size == 0)
MODEL_WINDOW_DEFAULTS: dict[str, dict[str, int]] = {
    "claude-opus-4-6": {
        "main": 200, "scan": 120, "detect": 120,
        "rca": FULL_CONTEXT, "sre": FULL_CONTEXT,
        "executor": 20, "reporter": 120,
    },
    "claude-sonnet-4-6": {
        "main": 100, "scan": 80, "detect": 80,
        "rca": 200, "sre": 200,
        "executor": 20, "reporter": 80,
    },
    "claude-haiku-4-5": {
        "main": 60, "scan": 40, "detect": 40,
        "rca": 80, "sre": 80,
        "executor": 20, "reporter": 40,
    },
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


def validate_agent_model_ids() -> list[str]:
    """Warn about agent model IDs that don't match any known model family.

    An unmatched ID silently falls back to bedrock_window_size in
    get_agent_window_size (losing the per-agent window tuning) and may be
    rejected by Bedrock at invocation time. Returns the list of warning
    strings (also logged) so callers/tests can assert on drift.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    warnings: list[str] = []
    for agent_name in AGENT_NAMES:
        model_id, _ = get_agent_model_config(agent_name)
        if not any(family in model_id for family in MODEL_WINDOW_DEFAULTS):
            msg = (
                f"agent_{agent_name}_model_id={model_id!r} matches no known model "
                f"family {list(MODEL_WINDOW_DEFAULTS)} — window falls back to "
                f"bedrock_window_size={settings.bedrock_window_size}; check settings.yaml"
            )
            warnings.append(msg)
            _log.warning(msg)
    return warnings


def get_bedrock_boto_session():
    """Return a boto3 Session configured for Bedrock API calls.

    Uses SessionFactory which handles:
    - AIOPS_BEDROCK_ROLE_ARN → cross-account AssumeRole
    - Default credential chain (env vars, IRSA, Task Role, Instance Profile, local profile)

    This session is ONLY for Bedrock model invocation (Layer 1).
    Target account scanning uses separate credentials (Layer 2).
    """
    from agenticops.credentials.session_factory import get_session_factory
    return get_session_factory().get_bedrock_session()


def get_agent_window_size(agent_name: str) -> int:
    """Return the window size for a given agent.

    Priority:
    1. Explicit override (agent_X_window_size != 0) -> use it
       - Positive: custom sliding window size
       - FULL_CONTEXT (-1): NullConversationManager (no trimming)
    2. Auto (agent_X_window_size == 0) -> look up MODEL_WINDOW_DEFAULTS by model family
    3. Fallback -> bedrock_window_size
    """
    override = getattr(settings, f"agent_{agent_name}_window_size", 0)
    if override != 0:
        return override

    # Auto mode: resolve from model family defaults
    model_id, _ = get_agent_model_config(agent_name)
    for family, defaults in MODEL_WINDOW_DEFAULTS.items():
        if family in model_id:
            return defaults.get(agent_name, settings.bedrock_window_size)
    return settings.bedrock_window_size


def get_agent_conversation_manager(agent_name: str):
    """Return the appropriate conversation manager for an agent.

    Returns NullConversationManager for FULL_CONTEXT agents (no trimming),
    or SlidingWindowConversationManager for bounded window agents.
    """
    from strands.agent.conversation_manager import (
        NullConversationManager,
        SlidingWindowConversationManager,
    )
    ws = get_agent_window_size(agent_name)
    if ws == FULL_CONTEXT:
        return NullConversationManager()
    return SlidingWindowConversationManager(window_size=ws, per_turn=True)


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


# ── Scan Focus (resource category filter) ─────────────────────────────

VALID_SCAN_FOCUS = ("computing", "networking", "databases", "storage", "security", "billing", "all")

SCAN_FOCUS_SERVICES = {
    "computing": "EC2,Lambda,ECS,EKS,AutoScaling",
    "networking": "VPC,Subnet,SecurityGroup,NATGateway,ELB,Route53",
    "databases": "RDS,DynamoDB,ElastiCache,OpenSearch",
    "storage": "S3,EBS,EFS",
    "security": "IAMRole,KMS",
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
