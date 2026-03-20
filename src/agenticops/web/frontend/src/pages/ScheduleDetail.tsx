import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { useSchedule, useScheduleExecutions, useRunSchedule } from "@/hooks/useSchedules";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";

export default function ScheduleDetail() {
  const { id } = useParams<{ id: string }>();
  const scheduleId = Number(id);

  const schedule = useSchedule(scheduleId);
  const executions = useScheduleExecutions(scheduleId);
  const runMut = useRunSchedule();
  const [expandedExec, setExpandedExec] = useState<number | null>(null);
  const [runSuccess, setRunSuccess] = useState(false);

  // Auto-clear success state after 3s and refresh executions
  useEffect(() => {
    if (runSuccess) {
      executions.refetch();
      const t = setTimeout(() => setRunSuccess(false), 3000);
      return () => clearTimeout(t);
    }
  }, [runSuccess]);

  if (schedule.isLoading) return <Spinner label="Loading schedule..." />;
  if (schedule.error)
    return (
      <ErrorBanner
        message={schedule.error.message}
        onRetry={() => schedule.refetch()}
      />
    );

  const s = schedule.data!;

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Back link */}
      <Link
        to="/app/schedules"
        className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <svg
          className="h-4 w-4 mr-1"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 19l-7-7 7-7"
          />
        </svg>
        Back to Schedules
      </Link>

      {/* Header card */}
      <Card>
        <CardBody>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-semibold text-foreground">{s.name}</h1>
              {s.is_enabled ? (
                <Badge className="bg-green-100 text-green-700">Enabled</Badge>
              ) : (
                <Badge className="bg-secondary text-muted-foreground">Disabled</Badge>
              )}
            </div>
            <div className="flex items-center gap-2">
              {runSuccess && (
                <span className="text-sm text-primary-600 font-medium flex items-center gap-1 duo-fade">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  Triggered
                </span>
              )}
              {runMut.isError && (
                <span className="text-sm text-destructive">Failed</span>
              )}
              <button
                onClick={() => {
                  setRunSuccess(false);
                  runMut.mutate(scheduleId, {
                    onSuccess: () => setRunSuccess(true),
                  });
                }}
                disabled={runMut.isPending}
                className="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 disabled:opacity-70 disabled:cursor-wait transition-colors"
              >
                {runMut.isPending && (
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                )}
                {runMut.isPending ? "Running..." : "Run Now"}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground block">Pipeline</span>
              <Badge className="bg-blue-100 text-blue-700">{s.pipeline_name}</Badge>
            </div>
            <div>
              <span className="text-muted-foreground block">Cron</span>
              <span className="font-mono">{s.cron_expression}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">Account</span>
              <span>{s.account_name || "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">Created</span>
              <span>{formatFullDate(s.created_at)}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">Last Run</span>
              <span>{s.last_run_at ? formatFullDate(s.last_run_at) : "Never"}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">Next Run</span>
              <span>{s.next_run_at ? formatFullDate(s.next_run_at) : "-"}</span>
            </div>
          </div>

          {Object.keys(s.config).length > 0 && (
            <div className="mt-4">
              <span className="text-muted-foreground block text-sm mb-1">Config</span>
              {s.pipeline_name === "AgentChain" ? (
                (() => {
                  const cfg = s.config as Record<string, unknown>;
                  const prompt = cfg.prompt as string | undefined;
                  const skills = Array.isArray(cfg.skills) ? (cfg.skills as string[]) : [];
                  const channels = Array.isArray(cfg.notify_channels) ? (cfg.notify_channels as string[]) : [];
                  const reportType = cfg.report_type as string | undefined;
                  const timeout = cfg.timeout_seconds as number | undefined;
                  return (
                    <div className="bg-secondary rounded-lg p-4 space-y-2 text-sm">
                      {prompt && (
                        <div>
                          <span className="font-medium text-foreground">Prompt:</span>
                          <p className="mt-1 text-muted-foreground whitespace-pre-wrap">{prompt}</p>
                        </div>
                      )}
                      {skills.length > 0 && (
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-foreground">Skills:</span>
                          {skills.map((sk) => (
                            <Badge key={sk} className="bg-purple-100 text-purple-700">{sk}</Badge>
                          ))}
                        </div>
                      )}
                      {channels.length > 0 && (
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-foreground">Channels:</span>
                          {channels.map((ch) => (
                            <Badge key={ch} className="bg-blue-100 text-blue-700">{ch}</Badge>
                          ))}
                        </div>
                      )}
                      {reportType && (
                        <div>
                          <span className="font-medium text-foreground">Report Type:</span>{" "}
                          <span className="text-muted-foreground">{reportType}</span>
                        </div>
                      )}
                      {timeout && (
                        <div>
                          <span className="font-medium text-foreground">Timeout:</span>{" "}
                          <span className="text-muted-foreground">{timeout}s</span>
                        </div>
                      )}
                    </div>
                  );
                })()
              ) : (
                <pre className="bg-secondary rounded-lg p-4 text-sm text-foreground overflow-x-auto">
                  {JSON.stringify(s.config, null, 2)}
                </pre>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Execution history */}
      <Card>
        <CardBody>
          <h2 className="text-xl font-semibold text-foreground mb-4">
            Execution History
          </h2>
          {executions.isLoading ? (
            <Spinner label="Loading executions..." />
          ) : executions.data && executions.data.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-secondary border-b border-border">
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                      ID
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                      Status
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                      Started
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                      Duration
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                      Error
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                      Output
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {executions.data.map((ex) => {
                    const agentOutput = (ex.result as Record<string, unknown>)?.agent_output as string | undefined;
                    const isExpanded = expandedExec === ex.id;
                    return (
                      <tr key={ex.id} className="hover:bg-secondary align-top">
                        <td className="px-4 py-2 text-sm font-mono">#{ex.id}</td>
                        <td className="px-4 py-2">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                              ex.status === "completed" || ex.status === "succeeded"
                                ? "bg-green-100 text-green-800"
                                : ex.status === "failed"
                                  ? "bg-red-100 text-red-800"
                                  : ex.status === "running"
                                    ? "bg-blue-100 text-blue-800"
                                    : "bg-secondary text-foreground"
                            }`}
                          >
                            {ex.status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-sm text-muted-foreground">
                          {formatFullDate(ex.started_at)}
                        </td>
                        <td className="px-4 py-2 text-sm text-muted-foreground">
                          {ex.duration_ms != null && ex.duration_ms > 0
                            ? `${(ex.duration_ms / 1000).toFixed(1)}s`
                            : "-"}
                        </td>
                        <td className="px-4 py-2 text-sm text-red-600">
                          {ex.error || "-"}
                        </td>
                        <td className="px-4 py-2 text-sm">
                          {agentOutput ? (
                            <button
                              onClick={() => setExpandedExec(isExpanded ? null : ex.id)}
                              className="text-primary-600 hover:underline text-xs"
                            >
                              {isExpanded ? "Hide" : "Show"}
                            </button>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                          {isExpanded && agentOutput && (
                            <pre className="mt-2 bg-secondary rounded p-3 text-xs text-foreground whitespace-pre-wrap max-h-64 overflow-y-auto">
                              {agentOutput}
                            </pre>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">No executions yet.</p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
