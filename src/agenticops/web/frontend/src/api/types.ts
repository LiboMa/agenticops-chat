export interface Stats {
  total_resources: number;
  open_anomalies: number;
  critical_anomalies: number;
  total_accounts: number;
}

export interface Resource {
  id: number;
  account_id: number;
  provider: string;
  resource_id: string;
  resource_arn: string | null;
  resource_type: string;
  resource_name: string | null;
  region: string;
  status: string;
  resource_metadata: Record<string, unknown>;
  tags: Record<string, string>;
  created_at: string;
  updated_at: string;
  scanned_at?: string | null;
  absent_since?: string | null; // set when the latest complete scan no longer saw it
}

export interface PaginatedResources {
  total: number;
  items: Resource[];
}

export type ScanFocus = "computing" | "networking" | "databases" | "storage" | "security" | "billing" | "all";

export type IssueStatus =
  | "open"
  | "investigating"
  | "root_cause_identified"
  | "fix_planned"
  | "fix_approved"
  | "fix_executing"
  | "fix_executed"
  | "resolved"
  | "acknowledged" // legacy fallback
  | "dismissed";

export interface MergedAlert {
  timestamp: string;
  source: string;
  title: string;
  description: string;
  severity: string;
  fingerprint?: string;
}

export interface Signal {
  id: number;
  received_at: string;
  kind: "alert" | "detection" | "resolution" | "manual";
  source: string;
  title: string;
  severity: string;
  issue_type: string;
  resource_id: string;
  disposition: "promoted" | "merged" | "noise" | "error" | null;
  disposition_reason: string;
  gate_evidence: Record<string, unknown>;
  health_issue_id: number | null;
  trace_id: string | null;
}

export interface Anomaly {
  id: number;
  resource_id: string;
  provider?: string;
  resource_type: string;
  region: string;
  anomaly_type: string;
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  description: string;
  metric_name: string | null;
  expected_value: number | null;
  actual_value: number | null;
  deviation_percent: number | null;
  status: IssueStatus;
  detected_at: string;
  resolved_at: string | null;
  trace_id: string | null;
  occurrence_count?: number;
  merged_alerts?: MergedAlert[];
  account_id: number | null;
  account_name: string | null;
  issue_type?: string;
}

/** GET /api/health-issues/{id} (HealthIssueResponse) — IssueDetail's source; the legacy /issues shape drops
 *  trace_id and merged_alerts. */
export interface HealthIssue {
  id: number;
  resource_id: string;
  provider: string | null;
  severity: Anomaly["severity"];
  source: string;
  title: string;
  description: string;
  alarm_name: string | null;
  metric_data: Record<string, unknown>;
  related_changes: unknown[];
  status: IssueStatus;
  detected_at: string;
  detected_by: string;
  resolved_at: string | null;
  trace_id: string | null;
  occurrence_count: number;
  merged_alerts: MergedAlert[];
  account_id: number | null;
  account_name: string | null;
  issue_type: string;
  // The anchor (MVP-2.6.1): the resource it resolved to, or why not; all null before the resolver reaches it
  resource_ref: number | null;
  anchor_status: AnchorStatus | null;
  anchor_candidates: { rule?: string | null; candidates?: { ref: number; account_id: number; reason: string }[] } | null;
  observed_at: string | null;
}

/** RCA root-cause location (MVP-2.6.1): ranked candidates, each cited by evidence ids, and the causal path. */
export interface RcaLocationCandidate {
  ref: number;
  rank: number;
  type: string | null;
  name: string | null;
  resource_id: string | null;
  supporting: string[];
  refuting: string[];
}

export interface RcaLocation {
  candidates: RcaLocationCandidate[];
  path: (LocationPathEdge & { src_name?: string | null; dst_name?: string | null; provenance?: string })[];
  dropped: string[];
}

export type LocationStatus = "valid" | "partial" | "invalid" | "absent";
export type LocationVerdict = "correct" | "partial" | "incorrect";

export interface RCAResult {
  id: number;
  anomaly_id: number;
  analysis_type: string;
  root_cause: string;
  /** API field is `confidence` (0-1); was mis-typed confidence_score → NaN% in UI */
  confidence: number;
  contributing_factors: string[];
  recommendations: string[];
  related_resources: string[];
  model_id: string;
  created_at: string;
  // RCA quality (MVP-2.2.0)
  evidence?: { type: string; ref: string; summary: string }[];
  evidence_verified?: boolean | null;
  critic_verdict?: string | null;
  critic_notes?: string | null;
  human_verdict?: "correct" | "incorrect" | null;
  // Root-cause location (MVP-2.6.1); a location verdict is accepted only while the status is valid or partial
  location?: RcaLocation | null;
  location_status?: LocationStatus | null;
  location_build_id?: number | null;
  location_verdict?: LocationVerdict | null;
  location_verdict_by?: string | null;
  location_verdict_at?: string | null;
}

export interface Report {
  id: number;
  report_type: string;
  title: string;
  summary: string;
  content_markdown: string;
  content_html: string | null;
  file_path: string | null;
  report_metadata: Record<string, unknown>;
  created_at: string;
}

export interface ReportFromSessionRequest {
  session_id: string;
  title?: string;
  summary?: string;
  message_ids?: number[];
  format?: string;
}

/* ------------------------------------------------------------------ */
/*  Fix Plans & Executions                                             */
/* ------------------------------------------------------------------ */

export type RiskLevel = "L0" | "L1" | "L2" | "L3";

export type FixPlanStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "executing"
  | "executed"
  | "failed"
  | "rejected";

export type PlanKind = "fix" | "change";

export interface FixPlan {
  id: number;
  plan_kind: PlanKind;
  health_issue_id: number | null;
  rca_result_id: number | null;
  change_request_id: number | null;
  risk_level: RiskLevel;
  title: string;
  summary: string;
  steps: unknown[];
  rollback_plan: Record<string, unknown>;
  estimated_impact: string;
  pre_checks: unknown[];
  post_checks: unknown[];
  status: FixPlanStatus;
  approved_by: string | null;
  approved_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string | null;
  account_id: number | null;
  // Content identity (MVP-2.6.1): an approval sends content_hash back and is refused (409) if the plan changed
  plan_version: number;
  content_hash: string | null;
  approved_hash: string | null;
  approved_version: number | null;
}

export interface FixExecution {
  id: number;
  fix_plan_id: number;
  health_issue_id: number | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  executed_by: string;
  pre_check_results: unknown[];
  step_results: unknown[];
  post_check_results: unknown[];
  rollback_results: unknown[];
  error_message: string | null;
  duration_ms: number;
  // Verification (MVP-2.6.1): passed | failed | pending_acceptance; null = the run closed without a verdict
  verification_status: VerificationStatus | null;
  verification_reason: string | null;
  accepted_by: string | null;
  accepted_at: string | null;
  acceptance_note: string | null;
  created_at: string;
}

export type VerificationStatus = "passed" | "failed" | "pending_acceptance";

/* ------------------------------------------------------------------ */
/*  Account                                                            */
/* ------------------------------------------------------------------ */

export type CloudProvider = "aws" | "azure" | "gcp" | "alicloud";
export type CredentialSourceType = "environment" | "assume_role" | "profile" | "static_keys";

export interface Account {
  id: number;
  name: string;
  provider: CloudProvider;
  credential_source_type: CredentialSourceType;
  credentials: Record<string, unknown>;
  regions: string[];
  labels: Record<string, string>;
  is_enabled: boolean;
  created_at: string;
  last_scanned_at: string | null;
}

export interface AccountCreate {
  name: string;
  provider: CloudProvider;
  credential_source_type: CredentialSourceType;
  credentials: Record<string, unknown>;
  regions: string[];
  labels?: Record<string, string>;
  is_enabled?: boolean;
}

export interface AccountUpdate {
  name?: string;
  credential_source_type?: CredentialSourceType;
  credentials?: Record<string, unknown>;
  regions?: string[];
  labels?: Record<string, string>;
  is_enabled?: boolean;
}

export interface AvailableProfiles {
  available: boolean;
  profiles: string[];
}

export interface EnvironmentInfo {
  environment: string;
  credential_backend: string;
  profiles_available: boolean;
}

export interface ConnectionTestResult {
  success: boolean;
  identity?: string | null;
  account_id?: string | null;
  error?: string | null;
  provider: string;
  name: string;
}

/* ------------------------------------------------------------------ */
/*  Audit                                                              */
/* ------------------------------------------------------------------ */

export interface AuditLogEntry {
  id: number;
  timestamp: string;
  user_id: number | null;
  user_email: string | null;
  actor: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  entity_name: string | null;
  details: Record<string, unknown> | null;
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  ip_address: string | null;
}

export interface AuditStats {
  period_hours: number;
  total_events: number;
  creates: number;
  updates: number;
  deletes: number;
  logins: number;
  login_failures: number;
}

/* ------------------------------------------------------------------ */
/*  AWS Regions                                                        */
/* ------------------------------------------------------------------ */

export interface AwsRegion {
  code: string;
  name: string;
}

/* ------------------------------------------------------------------ */
/*  Skills                                                             */
/* ------------------------------------------------------------------ */

export interface Skill {
  name: string;
  description: string;
  is_draft: boolean;
  domain: string;
  tools: string[];
  ref_count: number;
  /** "user" (hand-written, pinned) | "agent" (self-created draft) | "imported" (URL/git/zip). */
  created_by: string;
  /** Where an imported skill came from; null unless created_by === "imported". */
  source_uri: string | null;
}

export interface SkillDetail extends Skill {
  references: string[];
  body_markdown: string;
  metadata: Record<string, unknown>;
  /** git commit sha / archive sha256 / url — provenance only, never a pin. */
  source_ref: string | null;
  imported_at: string | null;
}

/** POST /api/skills/import-source — import from URL / git repo / zip. Everything lands as a draft. */
export interface SkillImportSourceRequest {
  uri: string;
  names?: string[];
}

export interface SkillImportSourceResult {
  source_uri: string;
  source_ref: string;
  installed: { name: string; path: string; files: number; bytes: number }[];
  skipped: { name: string; reason: string }[];
  rejected: { name: string; reason: string }[];
}

export interface SkillGenerateRequest {
  description: string;
}

export interface SkillGenerateResponse {
  name: string;
  description: string;
  body_preview: string;
  full_content: string;
  references: Record<string, string>;
}

export interface SkillDraftRequest {
  name: string;
  description: string;
  content: string;
  references?: Record<string, string>;
}

export interface SkillReviewData {
  name: string;
  draft_content: string;
  published_content: string | null;
  diff_summary: string;
  is_new: boolean;
}

export interface SkillUpdateRequest {
  content: string;
}

export interface SkillImproveRequest {
  improvement: string;
}

export interface SkillImproveResponse {
  record_id: string;
  skill_name: string;
  trigger: string;
  status: string;
  draft_path: string;
}

export interface SkillImprovementRecord {
  id: string;
  skill_name: string;
  improvement: string;
  source: string;
  trigger: string;
  status: string;
  confidence?: number;
  result: Record<string, unknown> | null;
  created_at: string;
  completed_at: string | null;
}

/* ------------------------------------------------------------------ */
/*  Schedules                                                          */
/* ------------------------------------------------------------------ */

export type ScheduleType = "recurring" | "one_time";

export interface Schedule {
  id: number;
  name: string;
  pipeline_name: string;
  schedule_type: ScheduleType;
  cron_expression: string;
  account_name: string | null;
  is_enabled: boolean;
  config: Record<string, unknown>;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleCreate {
  name: string;
  pipeline_name: string;
  schedule_type?: ScheduleType;
  cron_expression: string;
  account_name?: string;
  is_enabled?: boolean;
  config?: Record<string, unknown>;
}

export interface ScheduleUpdate {
  name?: string;
  pipeline_name?: string;
  schedule_type?: ScheduleType;
  cron_expression?: string;
  account_name?: string;
  is_enabled?: boolean;
  config?: Record<string, unknown>;
}

export interface ScheduleExecution {
  id: number;
  schedule_id: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  result: Record<string, unknown>;
  error: string | null;
}

/* ------------------------------------------------------------------ */
/*  Notification Channels & Logs                                       */
/* ------------------------------------------------------------------ */

export type NotificationChannelType = "slack" | "email" | "ses" | "sns" | "sns-report" | "feishu" | "dingtalk" | "wecom" | "webhook";

export interface NotificationChannel {
  name: string;
  channel_type: NotificationChannelType;
  config: Record<string, unknown>;
  severity_filter: string[];
  is_enabled: boolean;
}

export interface NotificationChannelCreate {
  name: string;
  channel_type: NotificationChannelType;
  config?: Record<string, unknown>;
  severity_filter?: string[];
  is_enabled?: boolean;
}

export interface NotificationChannelUpdate {
  channel_type?: NotificationChannelType;
  config?: Record<string, unknown>;
  severity_filter?: string[];
  is_enabled?: boolean;
}

export interface NotificationLog {
  id: number;
  channel_name: string;
  subject: string;
  body: string;
  severity: string | null;
  status: string;
  error: string | null;
  sent_at: string;
}

export interface ShareContentRequest {
  subject: string;
  body: string;
  channel_names?: string[];
  upload_to_s3?: boolean;
  expiry_hours?: number;
}

export interface ShareContentResponse {
  success: boolean;
  channels_sent: string[];
  channels_failed: string[];
  presigned_url?: string;
}

/* ------------------------------------------------------------------ */
/*  SOP Lifecycle                                                      */
/* ------------------------------------------------------------------ */

export type SOPStatus = "draft" | "review" | "active" | "deprecated" | "archived";

export interface SOPRecord {
  id: number;
  filename: string;
  resource_type: string;
  issue_pattern: string;
  severity: string;
  status: SOPStatus;
  quality_score: number;
  application_count: number;
  success_count: number;
  source_issue_id: number | null;
  approved_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  reviewed_at: string | null;
  preview?: string;
  content?: string;
}

export interface KBStats {
  sop_count: number;
  case_count: number;
  vector_count: number;
  embedding_status: string;
  rag_pipeline_enabled: boolean;
  sop_similarity_threshold?: number;
  sop_by_status: Record<SOPStatus, number>;
  review_queue_count: number;
}

/* ------------------------------------------------------------------ */
/*  MCP Servers                                                        */
/* ------------------------------------------------------------------ */

export interface McpServerConfig {
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  disabled?: boolean;
  autoApprove?: string[];
}

export type McpServersMap = Record<string, McpServerConfig>;

/* ------------------------------------------------------------------ */
/*  Agent Model Config                                                  */
/* ------------------------------------------------------------------ */

export interface AgentModelConfig {
  model_id: string;
  max_tokens: number;
  window_size: number;      // -1 = full, 0 = auto, >0 = manual
  window_mode: "full" | "sliding";
}

/* ------------------------------------------------------------------ */
/*  Agent Logs & Metrics                                               */
/* ------------------------------------------------------------------ */

export interface AgentLogEntry {
  id: number;
  trace_id: string | null;
  parent_agent: string | null;
  agent_name: string;
  action: string;
  input_summary: string;
  output_summary: string;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  duration_ms: number;
  model_id: string;
  status: string;
  error: string | null;
  created_at: string;
}

export interface AgentLogTimeline {
  trace_id: string;
  calls: Array<{
    id: number;
    agent_name: string;
    action: string;
    parent_agent: string | null;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cost_usd: number | null;
    tool_calls: number;
    duration_ms: number;
    status: string;
    error: string | null;
    model_id: string | null;
    created_at: string;
  }>;
  totals: {
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cost_usd: number;
    duration_ms: number;
    call_count: number;
  };
}

export interface AgentLogSummary {
  hours: number;
  per_agent: Record<string, {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    total_duration_ms: number;
    errors: number;
    tool_calls: number;
  }>;
  per_model: Record<string, {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    total_duration_ms: number;
  }>;
  total_input_tokens: number;
  total_output_tokens: number;
}

/* ------------------------------------------------------------------ */
/*  Chat                                                               */
/* ------------------------------------------------------------------ */

export interface ChatSession {
  id: number;
  session_id: string;
  name: string;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  message_count: number;
  pinned: boolean;
  starred: boolean;
  archived: boolean;
  /** Per-session main-agent model override; null = Auto (follow global config) */
  model_id: string | null;
  /** Per-session effort (thinking) override: off|standard|deep; null = Auto */
  effort?: string | null;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  tool_calls?: Array<{ name: string; status: string }>;
  token_usage?: {
    input: number;
    output: number;
    cache_read?: number;
    cache_write?: number;
    cost_usd?: number;
    model?: string;
    error?: string; // persisted when the stream failed (e.g. model unavailable)
  };
  trace_id?: string;
  cost_usd?: number;
  /** Follow-up suggestion chips from the reply tail; only rendered on the last assistant message */
  suggestions?: string[];
  attachments?: Array<{ filename: string; size: number }>;
  created_at: string;
}

export interface ChatSessionDetail extends ChatSession {
  /** @deprecated History now comes from GET /sessions/{id}/messages. Always []. */
  messages?: ChatMessage[];
}

export interface ChatMessagesPage {
  messages: ChatMessage[];
  has_more: boolean;
  next_cursor: number | null;
}

/* ------------------------------------------------------------------ */
/*  Pipeline Event Timeline                                            */
/* ------------------------------------------------------------------ */

export interface PipelineEvent {
  id: number;
  event_type: string;
  stage: string;
  status: string;
  detail: Record<string, unknown> | null;
  actor: string;
  duration_ms: number | null;
  created_at: string;
  trace_id: string | null;
}

/* ------------------------------------------------------------------ */
/*  Report Publishing & Subscriptions                                  */
/* ------------------------------------------------------------------ */

export interface ReportPublishRequest {
  channel_name: string;
  formats?: string[];
}

export interface ReportPublishResponse {
  report_id: number;
  channel_name: string;
  formats_generated: string[];
  download_urls: Record<string, string>;
  sns_message_id: string | null;
}

export interface ReportSubscription {
  subscription_arn: string;
  protocol: string;
  endpoint: string;
  status: string;
}

/* ------------------------------------------------------------------ */
/*  Global Search                                                      */
/* ------------------------------------------------------------------ */

export interface SearchResultItem {
  id: number;
  title: string;
  subtitle: string;
  entity_type: "issue" | "fix_plan" | "report" | "resource" | "change_request" | "change_plan";
  status?: string;
  severity?: string;
  report_type?: string;
  // For a change_plan item, parent_id is the owning change request id.
  parent_id?: number;
  updated_at?: string;
  created_at?: string;
}

export interface SearchResponse {
  query: string;
  results: {
    issues: SearchResultItem[];
    // A change plan arrives in the fix_plans group as entity_type "change_plan"
    // (with parent_id = change request id); ordinary plans stay "fix_plan".
    fix_plans: SearchResultItem[];
    reports: SearchResultItem[];
    resources: SearchResultItem[];
    // Only present when the backend's change-search flag is on.
    change_requests?: SearchResultItem[];
  };
}

/* ------------------------------------------------------------------ */
/*  Dashboard Trends                                                   */
/* ------------------------------------------------------------------ */

export interface TrendDay {
  date: string;
  opened?: number;
  resolved?: number;
}

export interface SeverityDay {
  date: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface ResourceDay {
  date: string;
  added: number;
}

export interface MttrDay {
  date: string;
  avg_hours: number;
}

export interface FixRateDay {
  date: string;
  total: number;
  succeeded: number;
  rate: number;
}

export interface TrendSummary {
  issues_opened: number;
  issues_resolved: number;
  resource_net_change: number;
  mttr_avg_hours: number;
  mttr_trend: "up" | "down" | "flat";
  fix_rate_pct: number;
  fix_rate_trend: "up" | "down" | "flat";
}

export interface DashboardTrends {
  issues: TrendDay[];
  severity: SeverityDay[];
  resources: ResourceDay[];
  mttr: MttrDay[];
  fix_rate: FixRateDay[];
  summary: TrendSummary;
}

/* ------------------------------------------------------------------ */
/*  Resource Detail — Related Resources                                */
/* ------------------------------------------------------------------ */

export interface RelatedResourceItem {
  id: number | null;
  resource_id: string;
  resource_type: string;
  resource_name: string | null;
  status: string | null;
  detail: string | null;
}

export interface RelatedResources {
  network: RelatedResourceItem[];
  contains: RelatedResourceItem[];
}

/* ------------------------------------------------------------------ */
/*  Fix Plan with Executions (Resource Detail)                         */
/* ------------------------------------------------------------------ */

export interface FixPlanWithExecutions {
  id: number;
  health_issue_id: number;
  rca_result_id: number;
  risk_level: string;
  title: string;
  summary: string;
  steps: unknown[];
  status: string;
  approved_by: string | null;
  created_at: string;
  executions: FixExecution[];
}

// Four values, worst open issue first; `unknown` = no open issue (not "healthy"). See lib/galaxyHealth.ts.
export type GalaxyHealth = "unknown" | "notice" | "warning" | "critical";

export interface GalaxyBuildInfo {
  id: number;
  status: "running" | "completed" | "failed";
  trigger: string;
  full: boolean;
  started_at: string | null;
  finished_at: string | null;
  node_count: number;
  edge_count: number;
  dropped_edge_count: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  error: string | null;
}

export interface GalaxyStatus {
  build: GalaxyBuildInfo | null;
  next_check_minutes: number;
}

// Full starfield payload (slim). Node/edge keys are shortened server-side.
export interface GalaxyGraphNode {
  id: string;
  kind: "account" | "group" | "resource";
  name: string;
  type: string;
  acct?: number | null;
  health?: GalaxyHealth;
  absent?: boolean; // resource nodes: the latest scan no longer saw it
  members?: number;
}
export interface GalaxyGraphEdge {
  s: string;
  t: string;
  r: string;
  p: "rule" | "llm";
  ev?: string;
  c?: number;
}
export interface GalaxyGraph {
  nodes: GalaxyGraphNode[];
  edges: GalaxyGraphEdge[];
  build_id: number | null;
}

// ── Security review (MVP-2.5.0) ────────────────────────────────
export interface SecurityAccountScore {
  account_id: string;
  overall_score: number;
  category_scores: Record<string, number>;
  created_at: string | null;
  reachable_paths: number;
  open_findings: number;
}

export interface SecuritySummary {
  accounts: SecurityAccountScore[];
  generated_at: string;
}

export interface SecurityTrendPoint {
  account_id: string;
  created_at: string | null;
  overall_score: number;
}

export interface SecurityFindingItem {
  id: number;
  title: string;
  severity: string;
  status: string;
  resource_id: string;
  issue_type: string;
  detected_by: string;
  last_seen: string | null;
  reachability: string | null;
}

export interface SecurityRecommendationItem {
  id: number;
  account_id: string;
  category: string;
  title: string;
  detail: string;
  severity: string;
  critic_verdict: string;
  confidence: number;
  status: string;
  created_at: string | null;
}

export interface AttackPathItem {
  account_id: string;
  resource_id: string;
  port: number | null;
  path: string[];
  reachability: string;
}

/* ------------------------------------------------------------------ */
/*  Change Management (MVP-2.6.0)                                      */
/* ------------------------------------------------------------------ */

export type ChangeStatus =
  | "draft" | "under_review" | "needs_clarification" | "planned" | "approved"
  | "executing" | "needs_review" | "completed" | "failed" | "rolled_back" | "rejected" | "cancelled";

export type ChangeType = "standard" | "normal" | "emergency";

export interface ChangeTarget {
  resource_id: string;
  resource_type: string;
  db_id: number | null;
  region: string | null;
  evidence: string | { command: string; excerpt: string };
  hint?: string;
}

export interface ChangeRequest {
  id: number;
  title: string;
  description: string;
  justification: string;
  source: string;
  requested_by: string;
  requester_user_id: number | null;
  requested_at: string | null;
  account_id: number | null;
  target_hints: string[];
  target_resources: ChangeTarget[];
  requested_change_type: "normal" | "emergency";
  effective_change_type: ChangeType | null;
  risk_level: RiskLevel | null;
  action_type: string | null;
  status: ChangeStatus;
  review_verdict: string | null;
  review_reasons: string[];
  reviewed_by: string | null;
  reviewed_at: string | null;
  policy_rule: string | null;
  policy_action: string | null;
  approved_by: string | null;
  approver_user_id: number | null;
  approved_at: string | null;
  approval_reason: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  closed_at: string | null;
  trace_id: string | null;
  chat_session_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  proposed_steps: ChangeProposedStep[] | null; // the requester's own steps (MVP-2.6.1)
  external_ref: ChangeExternalRef | null; // the ticket in another system it came from
  steps_diff: ChangeStepsDiff | null; // the plan against proposed_steps (services/change_steps.diff_steps)
  needs_review_reason: string | null; // why it waits for a human verdict
}

export interface ChangeProposedStep {
  action: string;
  command: string;
}

export interface ChangeExternalRef {
  system: string;
  ticket_id: string;
  url?: string | null;
  requested_by?: string | null;
}

/** Step numbers are 1-based; commands are whitespace-normalized. */
export interface ChangeStepsDiff {
  added: { plan_step: number; command: string }[];
  removed: { proposed_step: number; command: string }[];
  modified: { proposed_step: number; plan_step: number; proposed: string; plan: string }[];
  unchanged: number;
}

export interface ChangeRequestDetail extends ChangeRequest {
  plans: FixPlan[];
  executions: FixExecution[];
  policy_decision: Record<string, unknown> | null;
}

export interface ChangeTimelineEntry {
  ts: string | null;
  kind: "event" | "audit";
  type: string;
  actor: string | null;
  status: string | null;
  stage: string | null;
  detail: unknown;
}

export interface ChangeRequestCreate {
  title: string;
  description: string;
  account_name?: string;
  targets: string[];
  requested_change_type: "normal" | "emergency";
  justification?: string;
  proposed_steps?: ChangeProposedStep[];
  external_ref?: ChangeExternalRef;
}

export interface PlanStats {
  period: { start: string; end: string; bucket: string };
  kind: string;
  totals: { by_kind_status: Record<string, Record<string, number>>; open: number };
  approvals: { auto: number; human: number; rejected: number; authz_denied: number; authz_denied_shadow: number };
  lead_time: {
    request_to_approve_p50_s: number | null; request_to_approve_p90_s: number | null;
    approve_to_start_p50_s: number | null; exec_duration_p50_s: number | null;
  };
  outcomes: { success_rate: number | null; rollbacks: number; needs_review: number };
  breakdown: {
    by_actor: { requesters: { actor: string; count: number }[]; approvers: { actor: string; count: number }[]; executors: { actor: string; count: number }[] };
    by_risk: Record<string, number>; by_change_type: Record<string, number>; by_action_type: Record<string, number>; by_account: Record<string, number>;
  };
  series: { bucket: string; created: number; completed: number; failed: number }[];
  commands: { by_outcome: Record<string, number>; by_tool: Record<string, number> };
}

export interface CommandAudit {
  id: number;
  created_at: string;
  actor: string;
  on_behalf_of: string | null;
  agent_name: string | null;
  tool: string;
  tier: string;
  account: string;
  region: string;
  target: string;
  command: string;
  outcome: "executed" | "refused" | "blocked" | "error";
  reason: string | null;
  exit_code: number | null;
  output_excerpt: string;
  duration_ms: number;
  trace_id: string | null;
  fix_plan_id: number | null;
  change_request_id: number | null;
}

// ── Local graph: GET /api/graph/focus (MVP-2.6.1 spec §3.E.3) ──

export type AnchorStatus = "anchored" | "ambiguous" | "account_level" | "unanchored";

export interface FocusNode {
  ref: number;
  type: string;
  name: string;
  account_id: number;
  region: string | null;
  absent: boolean;
  hops: number;
  health: GalaxyHealth;
  issue_ids: number[];
  anomalous: boolean;
  signal_at: string | null;
}

export interface FocusEdge {
  src: number;
  dst: number;
  relation_type: string;
  provenance: string; // rule | llm
  evidence: string;
  direction_label: "downstream" | "upstream" | "both" | "none";
  observed_at: string | null;
}

// Another resource whose signals the Signal Gate merged into the issue
export interface FocusMerged {
  resource_id: string;
  ref: number | null;
  type: string | null;
  name: string | null;
  anchor_status: AnchorStatus;
  signals: number;
  last_at: string | null;
}

// Another open issue within 2 structural hops whose signal falls in the window
export interface FocusCandidate {
  issue_id: number;
  ref: number;
  hops: number;
  severity: string;
  title: string;
  status: string;
  signal_at: string;
}

export interface GraphFocus {
  build_id: number | null;
  nodes: FocusNode[];
  edges: FocusEdge[];
  truncated: boolean;
  truncated_reason: string | null;
  depth: number;
  anchor: {
    kind: "issue" | "resource" | "change_request";
    id: number;
    status: AnchorStatus;
    rule: string | null;
    candidates: Record<string, unknown>[];
    refs: number[];
  };
  blast: { structural: number; potential: number; observed: number; truncated: boolean };
  window: { start: string; end: string };
  related: { merged: FocusMerged[]; candidates: FocusCandidate[]; truncated: boolean };
}

// One edge of an RCA result's location.path (services/rca_location._path)
export interface LocationPathEdge {
  src_ref: number;
  dst_ref: number;
  relation_type: string;
  src_name?: string;
  dst_name?: string;
  provenance?: string;
}

// ── Pull connectors (GET /api/connectors, MVP-2.6.1 spec §3.B.6) ──
export type ConnectorRunStatus = "complete" | "partial" | "failed";

export interface ConnectorRun {
  id: number;
  account: string | null;
  scope: string; // e.g. the cluster name
  trigger: "schedule" | "manual" | "rca";
  status: ConnectorRunStatus;
  started_at: string | null;
  finished_at: string | null;
  counts: Record<string, number>; // created / updated / absent / returned / signals / signal_errors
  error: string | null;
}

export interface ConnectorStatus {
  name: string;
  enabled: boolean;
  running: boolean;
  schedule: { name: string; cron_expression: string; is_enabled: boolean } | null;
  recent_runs: ConnectorRun[];
}

// ── RCA location stats (GET /api/rca/location-stats, spec §3.C.4) ──
export interface RcaLocationStats {
  days: number;
  top1: number | null; // correct / judged; null when nothing is judged
  judged: number;
  anchoring_rate: number | null; // (anchored + account_level) / issues naming a resource_id
  issues_with_resource_id: number;
  anchor_status_counts: Record<AnchorStatus, number>;
  location_status_counts: Record<LocationStatus, number>;
}
