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
        className="inline-flex items-center text-sm text-[#9b9b9b] hover:text-[#ececec] transition-colors"
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
              <h1 className="text-2xl font-semibold text-[#ececec]">{s.name}</h1>
              {s.is_enabled ? (
                <Badge className="bg-green-100 text-green-700">Enabled</Badge>
              ) : (
                <Badge className="bg-[#383838] text-[#9b9b9b]">Disabled</Badge>
              )}
            </div>
            <button
              onClick={() => runMut.mutate(scheduleId)}
              disabled={runMut.isPending}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {runMut.isPending ? "Running..." : "Run Now"}
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-[#9b9b9b] block">Pipeline</span>
              <Badge className="bg-blue-100 text-blue-700">{s.pipeline_name}</Badge>
            </div>
            <div>
              <span className="text-[#9b9b9b] block">Cron</span>
              <span className="font-mono">{s.cron_expression}</span>
            </div>
            <div>
              <span className="text-[#9b9b9b] block">Account</span>
              <span>{s.account_name || "-"}</span>
            </div>
            <div>
              <span className="text-[#9b9b9b] block">Created</span>
              <span>{formatFullDate(s.created_at)}</span>
            </div>
            <div>
              <span className="text-[#9b9b9b] block">Last Run</span>
              <span>{s.last_run_at ? formatFullDate(s.last_run_at) : "Never"}</span>
            </div>
            <div>
              <span className="text-[#9b9b9b] block">Next Run</span>
              <span>{s.next_run_at ? formatFullDate(s.next_run_at) : "-"}</span>
            </div>
          </div>

          {Object.keys(s.config).length > 0 && (
            <div className="mt-4">
              <span className="text-[#9b9b9b] block text-sm mb-1">Config</span>
              <pre className="bg-[#383838] rounded-lg p-4 text-sm text-[#ececec] overflow-x-auto">
                {JSON.stringify(s.config, null, 2)}
              </pre>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Execution history */}
      <Card>
        <CardBody>
          <h2 className="text-xl font-semibold text-[#ececec] mb-4">
            Execution History
          </h2>
          {executions.isLoading ? (
            <Spinner label="Loading executions..." />
          ) : executions.data && executions.data.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-[#383838] border-b border-[#424242]">
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase">
                      ID
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase">
                      Status
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase">
                      Started
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase">
                      Duration
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase">
                      Error
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#424242]/50">
                  {executions.data.map((ex) => (
                    <tr key={ex.id} className="hover:bg-[#383838]">
                      <td className="px-4 py-2 text-sm font-mono">#{ex.id}</td>
                      <td className="px-4 py-2">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            ex.status === "succeeded"
                              ? "bg-green-100 text-green-800"
                              : ex.status === "failed"
                                ? "bg-red-100 text-red-800"
                                : ex.status === "running"
                                  ? "bg-blue-100 text-blue-800"
                                  : "bg-[#383838] text-[#ececec]"
                          }`}
                        >
                          {ex.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-sm text-[#9b9b9b]">
                        {formatFullDate(ex.started_at)}
                      </td>
                      <td className="px-4 py-2 text-sm text-[#9b9b9b]">
                        {ex.duration_ms != null && ex.duration_ms > 0
                          ? `${(ex.duration_ms / 1000).toFixed(1)}s`
                          : "-"}
                      </td>
                      <td className="px-4 py-2 text-sm text-red-600 max-w-xs truncate">
                        {ex.error || "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-[#9b9b9b] text-sm">No executions yet.</p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
