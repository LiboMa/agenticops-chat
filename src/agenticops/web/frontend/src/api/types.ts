export interface Stats {
  total_resources: number;
  open_anomalies: number;
  critical_anomalies: number;
  total_accounts: number;
}

export interface Resource {
  id: number;
  account_id: number;
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
}

export type ScanFocus = "computing" | "networking" | "databases" | "storage" | "security" | "billing" | "all";

export type IssueStatus =
  | "open"
  | "investigating"
  | "root_cause_identified"
  | "fix_planned"
  | "fix_approved"
  | "fix_executed"
  | "resolved"
  | "acknowledged"; // legacy fallback

export interface MergedAlert {
  timestamp: string;
  source: string;
  title: string;
  description: string;
  severity: string;
  fingerprint?: string;
}

export interface Anomaly {
  id: number;
  resource_id: string;
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
}

export interface RCAResult {
  id: number;
  anomaly_id: number;
  analysis_type: string;
  root_cause: string;
  confidence_score: number;
  contributing_factors: string[];
  recommendations: string[];
  related_resources: string[];
  llm_model: string;
  created_at: string;
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

export interface FixPlan {
  id: number;
  health_issue_id: number;
  rca_result_id: number;
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
  created_at: string;
}

export interface FixExecution {
  id: number;
  fix_plan_id: number;
  health_issue_id: number;
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
  created_at: string;
}

/* ------------------------------------------------------------------ */
/*  Account                                                            */
/* ------------------------------------------------------------------ */

export type CloudProvider = "aws" | "azure" | "gcp" | "alicloud";

export interface Account {
  id: number;
  name: string;
  provider: CloudProvider;
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
  credentials: Record<string, unknown>;
  regions: string[];
  labels?: Record<string, string>;
  is_enabled?: boolean;
}

export interface AccountUpdate {
  name?: string;
  credentials?: Record<string, unknown>;
  regions?: string[];
  labels?: Record<string, string>;
  is_enabled?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Audit                                                              */
/* ------------------------------------------------------------------ */

export interface AuditLogEntry {
  id: number;
  timestamp: string;
  user_id: number;
  user_email: string;
  action: string;
  entity_type: string;
  entity_id: string;
  entity_name: string | null;
  details: string | null;
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
}

export interface SkillDetail extends Skill {
  references: string[];
  body_markdown: string;
  metadata: Record<string, unknown>;
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

/* ------------------------------------------------------------------ */
/*  Schedules                                                          */
/* ------------------------------------------------------------------ */

export interface Schedule {
  id: number;
  name: string;
  pipeline_name: string;
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
  cron_expression: string;
  account_name?: string;
  is_enabled?: boolean;
  config?: Record<string, unknown>;
}

export interface ScheduleUpdate {
  name?: string;
  pipeline_name?: string;
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
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  tool_calls?: Array<{ name: string; status: string }>;
  token_usage?: { input: number; output: number };
  attachments?: Array<{ filename: string; size: number }>;
  created_at: string;
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatMessage[];
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
  entity_type: "issue" | "fix_plan" | "report" | "resource";
  status?: string;
  severity?: string;
  report_type?: string;
  updated_at?: string;
  created_at?: string;
}

export interface SearchResponse {
  query: string;
  results: {
    issues: SearchResultItem[];
    fix_plans: SearchResultItem[];
    reports: SearchResultItem[];
    resources: SearchResultItem[];
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
