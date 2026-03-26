import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { formatShortDate } from "@/lib/formatDate";
import {
  useSchedules,
  useCreateSchedule,
  useUpdateSchedule,
  useDeleteSchedule,
  useNotificationChannels,
} from "@/hooks/useSchedules";
import { useSkills } from "@/hooks/useSkills";
import type { Schedule, ScheduleCreate, ScheduleUpdate } from "@/api/types";
import { CronBuilder } from "@/components/ui/CronBuilder";

const PIPELINE_OPTIONS = ["FullScan", "Monitoring", "DailyReport", "HealthPatrol", "AgentChain"] as const;
const REPORT_TYPES = ["", "daily", "incident", "inventory"] as const;
const SCAN_SCOPES = ["all", "computing", "networking", "databases", "storage", "security", "billing"] as const;

export const PIPELINE_META: Record<string, { label: string; desc: string; badge: string }> = {
  FullScan: {
    label: "Full Scan",
    desc: "Scan all cloud resources and detect anomalies across your infrastructure.",
    badge: "bg-blue-100 text-blue-700",
  },
  Monitoring: {
    label: "Monitoring",
    desc: "Continuous monitoring of key metrics, alerts, and service health.",
    badge: "bg-emerald-100 text-emerald-700",
  },
  DailyReport: {
    label: "Daily Report",
    desc: "Generate a daily summary of infrastructure health, issues, and trends.",
    badge: "bg-amber-100 text-amber-700",
  },
  HealthPatrol: {
    label: "Health Patrol",
    desc: "Proactive health check — pulls alerts from monitoring providers and runs anomaly detection to find issues before they escalate.",
    badge: "bg-violet-100 text-violet-700",
  },
  AgentChain: {
    label: "Agent Chain",
    desc: "Custom multi-agent workflow driven by a natural language prompt.",
    badge: "bg-rose-100 text-rose-700",
  },
};

/* ------------------------------------------------------------------ */
/*  Schedule form modal                                                */
/* ------------------------------------------------------------------ */

interface FormModalProps {
  initial?: Schedule | null;
  onClose: () => void;
  onSave: (data: ScheduleCreate | ScheduleUpdate) => void;
  saving: boolean;
}

function ScheduleFormModal({ initial, onClose, onSave, saving }: FormModalProps) {
  const isEdit = !!initial;
  const [name, setName] = useState(initial?.name ?? "");
  const [pipelineName, setPipelineName] = useState(initial?.pipeline_name ?? "FullScan");
  const [cronExpression, setCronExpression] = useState(initial?.cron_expression ?? "");
  const [accountName, setAccountName] = useState(initial?.account_name ?? "");
  const [isEnabled, setIsEnabled] = useState(initial?.is_enabled ?? true);

  // AgentChain fields (stored in config)
  const initConfig = initial?.config ?? {};
  const [prompt, setPrompt] = useState((initConfig.prompt as string) ?? "");
  const [selectedSkills, setSelectedSkills] = useState<string[]>((initConfig.skills as string[]) ?? []);
  const [reportType, setReportType] = useState((initConfig.report_type as string) ?? "");
  const [selectedChannels, setSelectedChannels] = useState<string[]>((initConfig.notify_channels as string[]) ?? []);
  const [timeout, setTimeout] = useState((initConfig.timeout_seconds as number) ?? 300);
  // HealthPatrol fields
  const [hpScope, setHpScope] = useState((initConfig.scope as string) ?? "all");
  const [hpDeep, setHpDeep] = useState((initConfig.deep as boolean) ?? false);
  const [hpProviders, setHpProviders] = useState((initConfig.providers as string) ?? "all");

  const { data: skills } = useSkills();
  const { data: channels } = useNotificationChannels();

  const isAgentChain = pipelineName === "AgentChain";
  const isHealthPatrol = pipelineName === "HealthPatrol";

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const config: Record<string, unknown> = {};
    if (isAgentChain) {
      config.prompt = prompt;
      if (selectedSkills.length > 0) config.skills = selectedSkills;
      if (reportType) config.report_type = reportType;
      if (selectedChannels.length > 0) config.notify_channels = selectedChannels;
      if (timeout !== 300) config.timeout_seconds = timeout;
    }
    if (isHealthPatrol) {
      if (hpScope !== "all") config.scope = hpScope;
      if (hpDeep) config.deep = true;
      if (hpProviders !== "all") config.providers = hpProviders;
    }
    const base = {
      name,
      pipeline_name: pipelineName,
      cron_expression: cronExpression,
      account_name: accountName || undefined,
      is_enabled: isEnabled,
      config,
    };
    onSave(isEdit ? (base as ScheduleUpdate) : (base as ScheduleCreate));
  }

  function toggleItem(list: string[], item: string, setter: (v: string[]) => void) {
    setter(list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  }

  const inputCls = "w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 overflow-y-auto py-8">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-lg p-6">
        <h3 className="text-lg font-semibold text-foreground mb-4">
          {isEdit ? "Edit Schedule" : "New Schedule"}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Name</label>
            <input required value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Pipeline</label>
            <select value={pipelineName} onChange={(e) => setPipelineName(e.target.value)} className={inputCls}>
              {PIPELINE_OPTIONS.map((p) => (
                <option key={p} value={p}>{PIPELINE_META[p]?.label ?? p}</option>
              ))}
            </select>
            {PIPELINE_META[pipelineName]?.desc && (
              <p className="text-xs text-muted-foreground mt-1">{PIPELINE_META[pipelineName].desc}</p>
            )}
          </div>
          <CronBuilder value={cronExpression} onChange={setCronExpression} />
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Account Name (optional)</label>
            <input value={accountName} onChange={(e) => setAccountName(e.target.value)} className={inputCls} />
          </div>

          {/* HealthPatrol-specific fields */}
          {isHealthPatrol && (
            <div className="space-y-3 border-t border-border pt-3 mt-3">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Health Patrol Config</p>
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-foreground mb-1">Scope</label>
                  <select value={hpScope} onChange={(e) => setHpScope(e.target.value)} className={inputCls}>
                    {SCAN_SCOPES.map((sc) => (
                      <option key={sc} value={sc}>{sc}</option>
                    ))}
                  </select>
                </div>
                <div className="flex-1">
                  <label className="block text-sm font-medium text-foreground mb-1">Providers</label>
                  <input value={hpProviders} onChange={(e) => setHpProviders(e.target.value)} placeholder="all" className={inputCls} />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <input id="hp-deep" type="checkbox" checked={hpDeep} onChange={(e) => setHpDeep(e.target.checked)} className="rounded border-border" />
                <label htmlFor="hp-deep" className="text-sm text-foreground">Deep investigation</label>
                <span className="text-xs text-muted-foreground">(slower but more thorough)</span>
              </div>
            </div>
          )}

          {/* AgentChain-specific fields */}
          {isAgentChain && (
            <div className="space-y-3 border-t border-border pt-3 mt-3">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">AgentChain Config</p>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Prompt *</label>
                <textarea
                  required
                  rows={3}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Describe the task chain..."
                  className={inputCls}
                />
              </div>
              {skills && skills.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Skills</label>
                  <div className="flex flex-wrap gap-2">
                    {skills.map((s) => (
                      <label key={s.name} className="inline-flex items-center gap-1 text-xs bg-secondary px-2 py-1 rounded cursor-pointer hover:bg-secondary" title={s.description}>
                        <input type="checkbox" checked={selectedSkills.includes(s.name)} onChange={() => toggleItem(selectedSkills, s.name, setSelectedSkills)} className="rounded border-border" />
                        {s.name}
                      </label>
                    ))}
                  </div>
                </div>
              )}
              {channels && channels.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Notify Channels</label>
                  <div className="flex flex-wrap gap-2">
                    {channels.map((c) => (
                      <label key={c.name} className="inline-flex items-center gap-1 text-xs bg-secondary px-2 py-1 rounded cursor-pointer hover:bg-secondary">
                        <input type="checkbox" checked={selectedChannels.includes(c.name)} onChange={() => toggleItem(selectedChannels, c.name, setSelectedChannels)} className="rounded border-border" />
                        {c.name}
                      </label>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-foreground mb-1">Report Type</label>
                  <select value={reportType} onChange={(e) => setReportType(e.target.value)} className={inputCls}>
                    <option value="">None</option>
                    {REPORT_TYPES.filter(Boolean).map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>
                <div className="w-28">
                  <label className="block text-sm font-medium text-foreground mb-1">Timeout (s)</label>
                  <input type="number" min={30} max={3600} value={timeout} onChange={(e) => setTimeout(Number(e.target.value))} className={inputCls} />
                </div>
              </div>
            </div>
          )}

          <div className="flex items-center gap-2">
            <input id="schedule-enabled" type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} className="rounded border-border" />
            <label htmlFor="schedule-enabled" className="text-sm text-foreground">Enabled</label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">Cancel</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50">
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Delete confirmation modal                                          */
/* ------------------------------------------------------------------ */

function DeleteModal({
  schedule,
  onClose,
  onConfirm,
  deleting,
}: {
  schedule: Schedule;
  onClose: () => void;
  onConfirm: () => void;
  deleting: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-sm p-6">
        <h3 className="text-lg font-semibold text-foreground mb-2">Delete Schedule</h3>
        <p className="text-sm text-muted-foreground mb-4">
          Are you sure you want to delete <strong>{schedule.name}</strong>? This action
          cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={deleting}
            className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-500 disabled:opacity-50"
          >
            {deleting ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main page                                                          */
/* ------------------------------------------------------------------ */

const columns: Column<Schedule>[] = [
  {
    key: "name",
    header: "Name",
    sortable: true,
    sortValue: (r) => r.name,
    render: (r) => <span className="font-medium text-foreground">{r.name}</span>,
  },
  {
    key: "pipeline_name",
    header: "Pipeline",
    render: (r) => {
      const meta = PIPELINE_META[r.pipeline_name];
      return <Badge className={meta?.badge ?? "bg-blue-100 text-blue-700"}>{meta?.label ?? r.pipeline_name}</Badge>;
    },
  },
  {
    key: "cron_expression",
    header: "Cron",
    render: (r) => <span className="font-mono text-sm">{r.cron_expression}</span>,
  },
  {
    key: "is_enabled",
    header: "Enabled",
    render: (r) =>
      r.is_enabled ? (
        <Badge className="bg-green-100 text-green-700">Enabled</Badge>
      ) : (
        <Badge className="bg-secondary text-muted-foreground">Disabled</Badge>
      ),
  },
  {
    key: "last_run_at",
    header: "Last Run",
    sortable: true,
    sortValue: (r) => r.last_run_at ?? "",
    render: (r) => (
      <span className="text-sm text-muted-foreground">
        {r.last_run_at ? formatShortDate(r.last_run_at) : "Never"}
      </span>
    ),
  },
  {
    key: "next_run_at",
    header: "Next Run",
    render: (r) => (
      <span className="text-sm text-muted-foreground">
        {r.next_run_at ? formatShortDate(r.next_run_at) : "-"}
      </span>
    ),
  },
];

export default function Schedules() {
  const navigate = useNavigate();
  const { data: schedules, isLoading, error } = useSchedules();
  const createMut = useCreateSchedule();
  const updateMut = useUpdateSchedule();
  const deleteMut = useDeleteSchedule();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [deleting, setDeleting] = useState<Schedule | null>(null);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner message={(error as Error).message} />;

  return (
    <>
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">Schedules</h2>
          <button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
            className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500"
          >
            New Schedule
          </button>
        </CardHeader>
        <DataTable
          columns={[
            ...columns,
            {
              key: "actions",
              header: "",
              render: (r) => (
                <div className="flex gap-2">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditing(r);
                      setFormOpen(true);
                    }}
                    className="text-xs text-primary-600 hover:underline"
                  >
                    Edit
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleting(r);
                    }}
                    className="text-xs text-red-600 hover:underline"
                  >
                    Delete
                  </button>
                </div>
              ),
            },
          ]}
          data={schedules ?? []}
          rowKey={(r) => r.id}
          onRowClick={(r) => navigate(`/app/schedules/${r.id}`)}
          emptyMessage="No schedules configured."
        />
      </Card>

      {formOpen && (
        <ScheduleFormModal
          initial={editing}
          saving={createMut.isPending || updateMut.isPending}
          onClose={() => {
            setFormOpen(false);
            setEditing(null);
          }}
          onSave={async (data) => {
            if (editing) {
              await updateMut.mutateAsync({
                id: editing.id,
                data: data as ScheduleUpdate,
              });
            } else {
              await createMut.mutateAsync(data as ScheduleCreate);
            }
            setFormOpen(false);
            setEditing(null);
          }}
        />
      )}

      {deleting && (
        <DeleteModal
          schedule={deleting}
          deleting={deleteMut.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await deleteMut.mutateAsync(deleting.id);
            setDeleting(null);
          }}
        />
      )}
    </>
  );
}
