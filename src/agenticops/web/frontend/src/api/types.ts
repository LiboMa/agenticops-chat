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

export type IssueStatus =
  | "open"
  | "investigating"
  | "root_cause_identified"
  | "fix_planned"
  | "fix_approved"
  | "fix_executed"
  | "resolved"
  | "acknowledged"; // legacy fallback

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
/*  Region Topology (multi-VPC view)                                   */
/* ------------------------------------------------------------------ */

export interface RegionVpc {
  vpc_id: string;
  name: string | null;
  cidr_block: string;
  state: string;
  is_default: boolean;
  subnet_count: number;
}

export interface RegionTgwAttachment {
  attachment_id: string;
  resource_type: string;
  resource_id: string;
  state: string;
}

export interface RegionTransitGateway {
  transit_gateway_id: string;
  name: string | null;
  state: string;
  attachments: RegionTgwAttachment[];
}

export interface RegionTopology {
  region: string;
  vpcs: RegionVpc[];
  transit_gateways: RegionTransitGateway[];
  peering_connections: VpcPeeringConnection[];
}

/* ------------------------------------------------------------------ */
/*  VPC List                                                           */
/* ------------------------------------------------------------------ */

export interface Vpc {
  VpcId: string;
  CidrBlock: string;
  Name: string | null;
  State: string;
  IsDefault: boolean;
  DhcpOptionsId?: string;
  InstanceTenancy?: string;
  CidrBlockAssociations?: string[];
  Tags?: Record<string, string>;
}

export interface VpcListResponse {
  region: string;
  vpcs: Vpc[];
}

export interface Subnet {
  subnet_id: string;
  name: string | null;
  az: string;
  cidr: string;
  type: "public" | "private";
  available_ips: number;
  route_table_id: string | null;
  default_route_target: string | null;
}

export interface RouteEntry {
  destination: string;
  state: string;
  target: string;
  origin: string;
}

export interface RouteTable {
  route_table_id: string;
  name: string | null;
  associated_subnets: string[];
  is_main: boolean;
  routes: RouteEntry[];
}

export interface NatGateway {
  nat_gateway_id: string;
  name: string | null;
  subnet_id: string;
  state: string;
  connectivity_type: string;
  az: string;
}

export interface InternetGateway {
  igw_id: string;
  name: string | null;
  attachments: { vpc_id: string; state: string }[];
}

export interface VpcPeeringConnection {
  pcx_id: string;
  status: string;
  requester_vpc: string;
  requester_cidr: string;
  requester_owner: string;
  accepter_vpc: string;
  accepter_cidr: string;
  accepter_owner: string;
}

export interface VpcEndpoint {
  endpoint_id: string;
  service_name: string;
  type: string;
  state: string;
  route_table_ids: string[];
  subnet_ids: string[];
}

export interface TransitGatewayAttachment {
  attachment_id: string;
  transit_gateway_id: string;
  resource_type: string;
  state: string;
}

export interface BlackholeRoute {
  route_table_id: string;
  destination: string;
  target: string;
  affected_subnets: string[];
}

export interface SgDependencyEntry {
  name: string;
  references: string[];
  referenced_by: string[];
}

/** Keyed by security group ID */
export type SgDependencyMap = Record<string, SgDependencyEntry>;

export interface ReachabilitySummary {
  has_internet_gateway: boolean;
  public_subnet_count: number;
  private_subnet_count: number;
  nat_gateway_count: number;
  transit_gateway_attachments: number;
  vpc_peering_count: number;
  vpc_endpoint_count: number;
  blackhole_route_count: number;
  issues: string[];
}

/* ------------------------------------------------------------------ */
/*  Account                                                            */
/* ------------------------------------------------------------------ */

export interface Account {
  id: number;
  name: string;
  account_id: string;
  role_arn: string;
  external_id: string | null;
  regions: string[];
  is_active: boolean;
  created_at: string;
  last_scanned_at: string | null;
}

export interface AccountCreate {
  name: string;
  account_id: string;
  role_arn: string;
  external_id?: string;
  regions?: string[];
  is_active?: boolean;
}

export interface AccountUpdate {
  name?: string;
  role_arn?: string;
  external_id?: string;
  regions?: string[];
  is_active?: boolean;
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
/*  VPC Topology                                                       */
/* ------------------------------------------------------------------ */

export interface VpcTopology {
  vpc_id: string;
  vpc_cidr: string;
  vpc_name: string | null;
  region: string;
  internet_gateways: InternetGateway[];
  vpc_peering_connections: VpcPeeringConnection[];
  vpc_endpoints: VpcEndpoint[];
  subnets: Subnet[];
  route_tables: RouteTable[];
  nat_gateways: NatGateway[];
  transit_gateway_attachments: TransitGatewayAttachment[];
  security_group_dependency_map: SgDependencyMap;
  blackhole_routes: BlackholeRoute[];
  reachability_summary: ReachabilitySummary;
}

/* ------------------------------------------------------------------ */
/*  Graph Engine (serialized from backend graph API)                   */
/* ------------------------------------------------------------------ */

export interface GraphNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  data: Record<string, unknown>;
}

export interface GraphMetadata {
  node_count: number;
  edge_count: number;
  node_type_counts: Record<string, number>;
  has_anomalies: boolean;
  anomaly_count: number;
}

export interface SerializedGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata: GraphMetadata;
}

export interface ReachabilityResult {
  subnet_id: string;
  can_reach_internet: boolean;
  path: string[];
  path_details: { id: string; type: string; label: string }[];
  blocking_reason: string | null;
}

export interface AnomalyItem {
  type: string;
  severity: string;
  node_id: string;
  node_type: string;
  description: string;
  details: Record<string, unknown>;
}

export interface AnomalyReport {
  total_anomalies: number;
  anomalies: AnomalyItem[];
  summary: string;
}

/* ------------------------------------------------------------------ */
/*  AWS Regions                                                        */
/* ------------------------------------------------------------------ */

export interface AwsRegion {
  code: string;
  name: string;
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

export type NotificationChannelType = "slack" | "email" | "sns" | "sns-report" | "feishu" | "dingtalk" | "wecom" | "webhook";

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
/*  SRE Analysis (graph engine results)                                */
/* ------------------------------------------------------------------ */

export interface DependencyNode {
  node_id: string;
  node_type: string;
  label: string;
  depth: number;
}

export interface DependencyChainResult {
  fault_node_id: string;
  fault_node_type: string;
  affected_nodes: DependencyNode[];
  depth_levels: Record<number, string[]>;
  total_affected: number;
  severity: string;
}

export interface SPOFItem {
  node_id: string;
  node_type: string;
  label: string;
  impact_description: string;
  affected_components: number;
  is_bridge: boolean;
}

export interface SPOFReport {
  total_spofs: number;
  articulation_points: SPOFItem[];
  bridges: { source: string; source_type: string; source_label: string; target: string; target_type: string; target_label: string }[];
  summary: string;
}

export interface CapacityRiskItem {
  node_id: string;
  node_type: string;
  label: string;
  metric: string;
  current: number;
  maximum: number;
  utilization_pct: number;
  risk_level: string;
}

export interface CapacityRiskReport {
  total_risks: number;
  items: CapacityRiskItem[];
  summary: string;
}

export interface ReachabilityDiff {
  node_id: string;
  could_reach_before: string[];
  can_reach_after: string[];
  lost: string[];
}

export interface ChangeSimulationResult {
  edge_source: string;
  edge_target: string;
  edge_existed: boolean;
  lost_reachability: ReachabilityDiff[];
  total_connections_lost: number;
  impact_summary: string;
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
