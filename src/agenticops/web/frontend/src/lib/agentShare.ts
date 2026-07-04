/** per-agent 调用占比(按 calls 降序;总数 0 → 空)。 */
export function agentShare(
  perAgent: Record<string, { calls: number }>,
): { name: string; calls: number; pct: number }[] {
  const entries = Object.entries(perAgent).filter(([, v]) => v.calls > 0);
  const total = entries.reduce((s, [, v]) => s + v.calls, 0);
  if (total === 0) return [];
  return entries
    .map(([name, v]) => ({ name, calls: v.calls, pct: Math.round((v.calls / total) * 100) }))
    .sort((a, b) => b.calls - a.calls);
}
