import { useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { useLocale } from "@/i18n/LocaleContext";
import { useAgentLogs, useAgentTimeline, useAgentLogSummary } from "@/hooks/useAgentLogs";
import { useCostSummary } from "@/hooks/useCostSummary";
import type { AgentLogEntry } from "@/api/types";
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis,
  Tooltip, Legend, PieChart, Pie, Cell,
} from "recharts";

/* ── Time range options ─────────────────────────────────────────── */

const TIME_RANGES = [
  { label: "1h", hours: 1 },
  { label: "6h", hours: 6 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
];

const AGENT_NAMES = ["main", "scan", "detect", "rca", "sre", "executor", "reporter"];

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

function formatTokens(n: number): string {
  if (n < 1_000) return String(n);
  if (n < 1_000_000) return `${(n / 1_000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/* ── Token Summary Section ──────────────────────────────────────── */

function TokenSummary({ hours, onHoursChange }: { hours: number; onHoursChange: (h: number) => void }) {
  const summaryQ = useAgentLogSummary(hours);

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">Token Summary</h2>
        <div className="flex gap-1 bg-secondary rounded-lg p-1">
          {TIME_RANGES.map((r) => (
            <button
              key={r.hours}
              onClick={() => onHoursChange(r.hours)}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                hours === r.hours
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardBody>
        {summaryQ.isLoading ? (
          <Spinner />
        ) : summaryQ.error ? (
          <ErrorBanner message={(summaryQ.error as Error).message} onRetry={() => summaryQ.refetch()} />
        ) : summaryQ.data ? (
          <>
            <div className="flex gap-4 mb-4">
              <div className="px-3 py-2 rounded-lg bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800">
                <span className="text-xs text-muted-foreground">Total Input</span>
                <p className="text-lg font-semibold text-blue-700 dark:text-blue-300">{formatTokens(summaryQ.data.total_input_tokens)}</p>
              </div>
              <div className="px-3 py-2 rounded-lg bg-purple-50 dark:bg-purple-950 border border-purple-200 dark:border-purple-800">
                <span className="text-xs text-muted-foreground">Total Output</span>
                <p className="text-lg font-semibold text-purple-700 dark:text-purple-300">{formatTokens(summaryQ.data.total_output_tokens)}</p>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                    <th className="pb-2 pr-4">Agent</th>
                    <th className="pb-2 pr-4">Calls</th>
                    <th className="pb-2 pr-4">Input Tokens</th>
                    <th className="pb-2 pr-4">Output Tokens</th>
                    <th className="pb-2 pr-4">Cache Read</th>
                    <th className="pb-2 pr-4">Duration</th>
                    <th className="pb-2">Errors</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summaryQ.data.per_agent).map(([agent, stats]) => {
                    const maxTokens = Math.max(
                      ...Object.values(summaryQ.data!.per_agent).map((s) => s.input_tokens + s.output_tokens),
                      1,
                    );
                    const pct = ((stats.input_tokens + stats.output_tokens) / maxTokens) * 100;
                    return (
                      <tr key={agent} className="border-b border-border">
                        <td className="py-2.5 pr-4 font-medium text-foreground">{agent}</td>
                        <td className="py-2.5 pr-4 font-mono">{stats.calls}</td>
                        <td className="py-2.5 pr-4">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs">{formatTokens(stats.input_tokens)}</span>
                            <div className="flex-1 h-2 bg-secondary rounded-full max-w-[80px]">
                              <div className="h-2 bg-blue-500 rounded-full" style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        </td>
                        <td className="py-2.5 pr-4 font-mono text-xs">{formatTokens(stats.output_tokens)}</td>
                        <td className="py-2.5 pr-4 font-mono text-xs">{formatTokens(stats.cache_read_tokens)}</td>
                        <td className="py-2.5 pr-4 font-mono text-xs">{formatDuration(stats.total_duration_ms)}</td>
                        <td className="py-2.5">
                          {stats.errors > 0 ? (
                            <Badge className="bg-red-100 text-red-700">{stats.errors}</Badge>
                          ) : (
                            <span className="text-muted-foreground">0</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

/* ── Model Summary Section ─────────────────────────────────────── */

function ModelSummary({ hours }: { hours: number }) {
  const summaryQ = useAgentLogSummary(hours);

  if (summaryQ.isLoading || summaryQ.error || !summaryQ.data?.per_model) return null;

  const models = Object.entries(summaryQ.data.per_model);
  if (models.length === 0) return null;

  // Shorten model ID for display: "global.anthropic.claude-sonnet-4-6" -> "claude-sonnet-4-6"
  const shortName = (id: string) => {
    const parts = id.split(".");
    return parts.length > 2 ? parts.slice(2).join(".") : id;
  };

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">Model Usage</h2>
      </CardHeader>
      <CardBody>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                <th className="pb-2 pr-4">Model</th>
                <th className="pb-2 pr-4">Calls</th>
                <th className="pb-2 pr-4">Input Tokens</th>
                <th className="pb-2 pr-4">Output Tokens</th>
                <th className="pb-2 pr-4">Cache Read</th>
                <th className="pb-2">Duration</th>
              </tr>
            </thead>
            <tbody>
              {models
                .sort(([, a], [, b]) => (b.input_tokens + b.output_tokens) - (a.input_tokens + a.output_tokens))
                .map(([model, stats]) => {
                  const maxTokens = Math.max(...models.map(([, s]) => s.input_tokens + s.output_tokens), 1);
                  const pct = ((stats.input_tokens + stats.output_tokens) / maxTokens) * 100;
                  return (
                    <tr key={model} className="border-b border-border">
                      <td className="py-2.5 pr-4 font-medium text-foreground">
                        <span className="text-xs font-mono">{shortName(model)}</span>
                      </td>
                      <td className="py-2.5 pr-4 font-mono">{stats.calls}</td>
                      <td className="py-2.5 pr-4">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs">{formatTokens(stats.input_tokens)}</span>
                          <div className="flex-1 h-2 bg-secondary rounded-full max-w-[80px]">
                            <div className="h-2 bg-green-500 rounded-full" style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      </td>
                      <td className="py-2.5 pr-4 font-mono text-xs">{formatTokens(stats.output_tokens)}</td>
                      <td className="py-2.5 pr-4 font-mono text-xs">{formatTokens(stats.cache_read_tokens)}</td>
                      <td className="py-2.5 font-mono text-xs">{formatDuration(stats.total_duration_ms)}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </CardBody>
    </Card>
  );
}

/* ── Agent Call Log Section ──────────────────────────────────────── */

function AgentCallLog({ onSelectTrace }: { onSelectTrace: (traceId: string) => void }) {
  const [agentFilter, setAgentFilter] = useState("");
  const logsQ = useAgentLogs(agentFilter ? { agent_name: agentFilter, limit: 50 } : { limit: 50 });

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">Agent Call Log</h2>
        <select
          value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
          className="px-3 py-1.5 text-sm border border-border rounded-lg bg-background text-foreground"
        >
          <option value="">All Agents</option>
          {AGENT_NAMES.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
      </CardHeader>
      <CardBody>
        {logsQ.isLoading ? (
          <Spinner />
        ) : logsQ.error ? (
          <ErrorBanner message={(logsQ.error as Error).message} onRetry={() => logsQ.refetch()} />
        ) : !logsQ.data?.length ? (
          <p className="text-sm text-muted-foreground py-4 text-center">No agent logs found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                  <th className="pb-2 pr-4">Time</th>
                  <th className="pb-2 pr-4">Trace ID</th>
                  <th className="pb-2 pr-4">Agent</th>
                  <th className="pb-2 pr-4">Action</th>
                  <th className="pb-2 pr-4">Input</th>
                  <th className="pb-2 pr-4">Output</th>
                  <th className="pb-2 pr-4">Duration</th>
                  <th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {logsQ.data.map((entry: AgentLogEntry) => (
                  <tr key={entry.id} className="border-b border-border hover:bg-secondary/50">
                    <td className="py-2 pr-4 text-xs text-muted-foreground whitespace-nowrap">{formatTime(entry.created_at)}</td>
                    <td className="py-2 pr-4">
                      {entry.trace_id ? (
                        <button
                          onClick={() => onSelectTrace(entry.trace_id!)}
                          className="text-xs font-mono text-primary-600 hover:underline"
                        >
                          {entry.trace_id.slice(0, 12)}
                        </button>
                      ) : (
                        <span className="text-xs text-muted-foreground">--</span>
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge className="bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400">{entry.agent_name}</Badge>
                    </td>
                    <td className="py-2 pr-4 text-xs max-w-[200px] truncate">{entry.action}</td>
                    <td className="py-2 pr-4 font-mono text-xs">{formatTokens(entry.input_tokens)}</td>
                    <td className="py-2 pr-4 font-mono text-xs">{formatTokens(entry.output_tokens)}</td>
                    <td className="py-2 pr-4 font-mono text-xs">{formatDuration(entry.duration_ms)}</td>
                    <td className="py-2">
                      <Badge className={entry.status === "success" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}>
                        {entry.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

/* ── Timeline Drawer ────────────────────────────────────────────── */

function TimelineDrawer({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const timelineQ = useAgentTimeline(traceId);

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-full max-w-lg bg-background border-l border-border shadow-xl flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Trace Timeline</h3>
          <span className="text-xs font-mono text-muted-foreground">{traceId}</span>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-sm">Close</button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {timelineQ.isLoading ? (
          <Spinner />
        ) : timelineQ.error ? (
          <ErrorBanner message={(timelineQ.error as Error).message} onRetry={() => timelineQ.refetch()} />
        ) : timelineQ.data ? (
          <>
            <div className="flex gap-3 mb-4 text-xs">
              <div className="px-2 py-1 rounded bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300">
                Input: <strong>{formatTokens(timelineQ.data.totals.input_tokens)}</strong>
              </div>
              <div className="px-2 py-1 rounded bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300">
                Output: <strong>{formatTokens(timelineQ.data.totals.output_tokens)}</strong>
              </div>
              <div className="px-2 py-1 rounded bg-secondary text-muted-foreground">
                Duration: <strong>{formatDuration(timelineQ.data.totals.duration_ms)}</strong>
              </div>
              {timelineQ.data.totals.cost_usd > 0 && (
                <div className="px-2 py-1 rounded bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-300">
                  Cost: <strong>${timelineQ.data.totals.cost_usd.toFixed(4)}</strong>
                </div>
              )}
            </div>
            <div className="space-y-0">
              {timelineQ.data.calls.map((entry, i) => {
                const isChild = !!entry.parent_agent;
                const maxDur = Math.max(...timelineQ.data!.calls.map((e) => e.duration_ms), 1);
                const barPct = Math.max((entry.duration_ms / maxDur) * 100, 4);
                return (
                  <div
                    key={entry.id}
                    className={`relative flex gap-3 ${isChild ? "ml-6" : ""} ${i > 0 ? "mt-0" : ""}`}
                  >
                    {/* Vertical line */}
                    <div className="flex flex-col items-center w-4 flex-shrink-0">
                      <div className={`w-2.5 h-2.5 rounded-full border-2 ${
                        entry.status === "success"
                          ? "border-green-500 bg-green-100"
                          : "border-red-500 bg-red-100"
                      }`} />
                      {i < timelineQ.data!.calls.length - 1 && (
                        <div className="w-px flex-1 bg-border" />
                      )}
                    </div>
                    {/* Content */}
                    <div className="flex-1 pb-4">
                      <div className="flex items-center gap-2">
                        <Badge className="bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400 text-xs">{entry.agent_name}</Badge>
                        <span className="text-xs text-muted-foreground">{entry.action}</span>
                        <Badge className={entry.status === "success" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}>
                          {entry.status}
                        </Badge>
                      </div>
                      {/* Duration bar */}
                      <div className="mt-1.5 flex items-center gap-2">
                        <div className="h-2 bg-secondary rounded-full flex-1 max-w-[200px]">
                          <div
                            className={`h-2 rounded-full ${entry.status === "success" ? "bg-primary-500" : "bg-red-400"}`}
                            style={{ width: `${barPct}%` }}
                          />
                        </div>
                        <span className="text-xs font-mono text-muted-foreground">{formatDuration(entry.duration_ms)}</span>
                      </div>
                      <div className="flex gap-3 mt-1 text-xs text-muted-foreground">
                        <span>In: {formatTokens(entry.input_tokens)}</span>
                        <span>Out: {formatTokens(entry.output_tokens)}</span>
                        {entry.cache_read_tokens > 0 && <span>Cache: {formatTokens(entry.cache_read_tokens)}</span>}
                        {entry.tool_calls > 0 && <span>Tools: {entry.tool_calls}</span>}
                      </div>
                      {entry.error && (
                        <p className="mt-1 text-xs text-red-600 line-clamp-2">{entry.error}</p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

/* ── Cost Dashboard ────────────────────────────────────────────── */

const COST_PERIODS = [
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
  { label: "Month", value: "month" },
  { label: "Year", value: "year" },
];

const GROUP_BY_OPTIONS = [
  { label: "Agent", value: "agent" },
  { label: "Actor", value: "actor" },
  { label: "Model", value: "model" },
];

const COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#6366f1", "#ec4899"];

function CostDashboard() {
  const [period, setPeriod] = useState("30d");
  const [groupBy, setGroupBy] = useState("agent");
  const costQ = useCostSummary({ period, groupBy });

  if (costQ.isLoading) return <Card><CardBody><Spinner /></CardBody></Card>;
  if (costQ.error) return <ErrorBanner message={(costQ.error as Error).message} onRetry={() => costQ.refetch()} />;
  if (!costQ.data) return null;

  const { totals, series, breakdown } = costQ.data;

  const chartData = series.map((s) => {
    const entry: Record<string, string | number> = { bucket: s.bucket, tokens: s.total_tokens };
    for (const [k, v] of Object.entries(s.by)) {
      entry[k] = v.cost_usd;
    }
    return entry;
  });

  const dimensionKeys = [...new Set(breakdown.map((b) => b.key))];

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">Cost & Tokens</h2>
        <div className="flex gap-2">
          <div className="flex gap-1 bg-secondary rounded-lg p-1">
            {COST_PERIODS.map((p) => (
              <button
                key={p.value}
                onClick={() => setPeriod(p.value)}
                className={`px-2 py-1 text-xs rounded ${period === p.value ? "bg-background shadow text-foreground" : "text-muted-foreground"}`}
              >{p.label}</button>
            ))}
          </div>
          <select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value)}
            className="text-xs border rounded px-2 py-1 bg-background"
          >
            {GROUP_BY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </CardHeader>
      <CardBody>
        {/* KPI scorecards */}
        <div className="grid grid-cols-4 gap-3 mb-4">
          <div className="p-3 rounded-lg bg-green-50 dark:bg-green-950">
            <div className="text-xs text-muted-foreground">Total Cost</div>
            <div className="text-xl font-bold text-green-700 dark:text-green-300">${totals.cost_usd.toFixed(4)}</div>
          </div>
          <div className="p-3 rounded-lg bg-blue-50 dark:bg-blue-950">
            <div className="text-xs text-muted-foreground">Total Tokens</div>
            <div className="text-xl font-bold text-blue-700 dark:text-blue-300">{formatTokens(totals.total_tokens)}</div>
          </div>
          <div className="p-3 rounded-lg bg-purple-50 dark:bg-purple-950">
            <div className="text-xs text-muted-foreground">Cache Hit %</div>
            <div className="text-xl font-bold text-purple-700 dark:text-purple-300">{totals.cache_hit_pct.toFixed(0)}%</div>
          </div>
          <div className="p-3 rounded-lg bg-secondary">
            <div className="text-xs text-muted-foreground">Calls</div>
            <div className="text-xl font-bold text-foreground">{totals.call_count}</div>
          </div>
        </div>

        {/* Stacked bar (cost) + line (tokens) chart */}
        {chartData.length > 0 && (
          <div className="h-64 mb-4">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData}>
                <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="cost" tick={{ fontSize: 11 }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
                <YAxis yAxisId="tokens" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(v: number) => formatTokens(v)} />
                <Tooltip />
                <Legend />
                {dimensionKeys.map((k, i) => (
                  <Bar key={k} dataKey={k} stackId="cost" yAxisId="cost" fill={COLORS[i % COLORS.length]} />
                ))}
                <Line type="monotone" dataKey="tokens" yAxisId="tokens" stroke="#6b7280" dot={false} strokeDasharray="4 2" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Breakdown + donut */}
        <div className="grid grid-cols-2 gap-4">
          {/* Breakdown table */}
          <div>
            <h3 className="text-sm font-medium mb-2">Breakdown by {groupBy}</h3>
            <div className="space-y-1">
              {breakdown.slice(0, 8).map((b, i) => (
                <div key={b.key} className="flex items-center gap-2 text-xs">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                  <span className="flex-1 truncate">{b.key}</span>
                  <span className="tabular-nums text-muted-foreground">{b.calls} calls</span>
                  <span className="tabular-nums text-muted-foreground">{formatTokens(b.tokens)}</span>
                  <span className="tabular-nums font-medium text-green-600 dark:text-green-400">${b.cost_usd.toFixed(4)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Donut chart */}
          {breakdown.length > 0 && (
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={breakdown.slice(0, 7)}
                    dataKey="cost_usd"
                    nameKey="key"
                    innerRadius="50%"
                    outerRadius="80%"
                    paddingAngle={2}
                  >
                    {breakdown.slice(0, 7).map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v) => `$${Number(v).toFixed(4)}`} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

/* ── Main Page ──────────────────────────────────────────────────── */

export default function AgentMetrics() {
  const { t } = useLocale();
  const [hours, setHours] = useState(24);
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null);

  return (
    <div className="max-w-6xl">
      <h1 className="text-2xl font-semibold text-foreground mb-4">{t("nav.agentMetrics")}</h1>

      <div className="space-y-6">
        <CostDashboard />
        <TokenSummary hours={hours} onHoursChange={setHours} />
        <ModelSummary hours={hours} />
        <AgentCallLog onSelectTrace={setSelectedTrace} />
      </div>

      {selectedTrace && (
        <TimelineDrawer traceId={selectedTrace} onClose={() => setSelectedTrace(null)} />
      )}
    </div>
  );
}
