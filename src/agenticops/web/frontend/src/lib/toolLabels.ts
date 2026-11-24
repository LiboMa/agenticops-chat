/** Steps people recognise by what they do; any other tool shows its own name (2026-11-07). */
const KNOWN = new Set([
  "scan_agent", "detect_agent", "rca_agent", "sre_agent", "sre_query", "executor_agent", "reporter_agent",
  "review_change", "enhanced_task", "run_kubectl", "run_aws_cli_readonly", "run_on_host",
]);

export function toolLabelKey(name: string): string | null {
  return KNOWN.has(name) ? `chat.tool.${name}` : null;
}
