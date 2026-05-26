import { useState, useRef, useCallback, useEffect } from "react";
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

function ScheduleFormModal({ initial, onClose, onSave, saving, defaultType }: FormModalProps & { defaultType?: "recurring" | "one_time" }) {
  const isEdit = !!initial;
  const [name, setName] = useState(initial?.name ?? "");
  const [scheduleType, setScheduleType] = useState<"recurring" | "one_time">(initial?.schedule_type ?? defaultType ?? "recurring");
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
  const [timeout, setTimeout] = useState((initConfig.timeout_seconds as number) ?? 0);
  const [maxRetries, setMaxRetries] = useState((initConfig.max_retries as number) ?? 0);
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
      if (timeout > 0) config.timeout_seconds = timeout;
      if (maxRetries > 0) config.max_retries = maxRetries;
    }
    if (isHealthPatrol) {
      if (hpScope !== "all") config.scope = hpScope;
      if (hpDeep) config.deep = true;
      if (hpProviders !== "all") config.providers = hpProviders;
    }
    const base = {
      name,
      pipeline_name: pipelineName,
      schedule_type: scheduleType,
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

  // Drag & resize state
  const modalRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [size, setSize] = useState({ w: 540, h: 0 }); // h=0 means auto
  const [dragging, setDragging] = useState(false);
  const [resizing, setResizing] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, px: 0, py: 0 });
  const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0 });

  const onDragDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, px: pos.x, py: pos.y };
  }, [pos]);

  const onResizeDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setResizing(true);
    const rect = modalRef.current?.getBoundingClientRect();
    resizeStart.current = { x: e.clientX, y: e.clientY, w: rect?.width ?? 540, h: rect?.height ?? 400 };
  }, []);

  useEffect(() => {
    if (!dragging && !resizing) return;
    const onMove = (e: MouseEvent) => {
      if (dragging) {
        setPos({
          x: dragStart.current.px + (e.clientX - dragStart.current.x),
          y: dragStart.current.py + (e.clientY - dragStart.current.y),
        });
      }
      if (resizing) {
        setSize({
          w: Math.max(380, resizeStart.current.w + (e.clientX - resizeStart.current.x)),
          h: Math.max(200, resizeStart.current.h + (e.clientY - resizeStart.current.y)),
        });
      }
    };
    const onUp = () => { setDragging(false); setResizing(false); };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, [dragging, resizing]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div
        ref={modalRef}
        className="relative bg-background rounded-xl shadow-2xl border border-border/50 flex flex-col"
        style={{
          width: size.w,
          height: size.h > 0 ? size.h : "auto",
          maxHeight: "90vh",
          transform: `translate(${pos.x}px, ${pos.y}px)`,
          overflow: "hidden",
        }}
      >
        {/* Draggable header */}
        <div
          onMouseDown={onDragDown}
          className="flex items-center justify-between px-5 pt-4 pb-3 cursor-move select-none border-b border-border/30"
        >
          <h3 className="text-base font-semibold text-foreground">
            {isEdit ? "Edit Task" : "New Task"}
          </h3>
          {!isEdit && (
            <div className="flex bg-secondary rounded-lg p-0.5">
              <button
                type="button"
                onClick={() => setScheduleType("recurring")}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                  scheduleType === "recurring"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Recurring
              </button>
              <button
                type="button"
                onClick={() => setScheduleType("one_time")}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                  scheduleType === "one_time"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                One-time
              </button>
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-5 py-3 space-y-3">
          {/* Row 1: Name + Pipeline */}
          <div className="grid grid-cols-5 gap-2">
            <div className="col-span-3">
              <label className="block text-xs font-medium text-muted-foreground mb-1">Name</label>
              <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="daily-health-check" className={inputCls} />
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-medium text-muted-foreground mb-1">Pipeline</label>
              <select value={pipelineName} onChange={(e) => setPipelineName(e.target.value)} className={inputCls}>
                {PIPELINE_OPTIONS.map((p) => (
                  <option key={p} value={p}>{PIPELINE_META[p]?.label ?? p}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Schedule expression */}
          <CronBuilder value={cronExpression} onChange={setCronExpression} />

          {/* Row 2: Account + Enabled toggle */}
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label className="block text-xs font-medium text-muted-foreground mb-1">Account</label>
              <input value={accountName} onChange={(e) => setAccountName(e.target.value)} placeholder="optional" className={inputCls} />
            </div>
            <label className="flex items-center gap-2 pb-2 cursor-pointer select-none">
              <div
                onClick={() => setIsEnabled(!isEnabled)}
                className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${isEnabled ? "bg-primary-500" : "bg-muted-foreground/30"}`}
              >
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${isEnabled ? "translate-x-[18px]" : "translate-x-0.5"}`} />
              </div>
              <span className="text-xs text-muted-foreground">{isEnabled ? "On" : "Off"}</span>
            </label>
          </div>

          {/* HealthPatrol config — compact */}
          {isHealthPatrol && (
            <div className="bg-secondary/50 rounded-lg p-3 space-y-2">
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">Patrol Config</p>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs text-muted-foreground mb-0.5">Scope</label>
                  <select value={hpScope} onChange={(e) => setHpScope(e.target.value)} className={inputCls}>
                    {SCAN_SCOPES.map((sc) => <option key={sc} value={sc}>{sc}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-0.5">Providers</label>
                  <input value={hpProviders} onChange={(e) => setHpProviders(e.target.value)} placeholder="all" className={inputCls} />
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <div
                  onClick={() => setHpDeep(!hpDeep)}
                  className={`relative w-8 h-4 rounded-full transition-colors cursor-pointer ${hpDeep ? "bg-primary-500" : "bg-muted-foreground/30"}`}
                >
                  <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${hpDeep ? "translate-x-[14px]" : "translate-x-0.5"}`} />
                </div>
                <span className="text-xs text-foreground">Deep investigation</span>
              </label>
            </div>
          )}

          {/* AgentChain config — focus on Prompt + Notify */}
          {isAgentChain && (
            <div className="space-y-2.5">
              <textarea
                required
                rows={3}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe what the agent should do..."
                className={`${inputCls} resize-none`}
              />
              {/* Notify channels — primary action */}
              {channels && channels.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] font-medium text-muted-foreground uppercase">Notify:</span>
                  {channels.map((c) => (
                    <button
                      key={c.name}
                      type="button"
                      onClick={() => toggleItem(selectedChannels, c.name, setSelectedChannels)}
                      className={`px-2 py-0.5 text-[11px] rounded-full border transition-colors ${
                        selectedChannels.includes(c.name)
                          ? "bg-emerald-50 border-emerald-300 text-emerald-700"
                          : "bg-background border-border text-muted-foreground hover:border-emerald-200"
                      }`}
                    >
                      {c.name}
                    </button>
                  ))}
                </div>
              )}
              {/* Collapsed options row */}
              <div className="flex items-center gap-3 text-[11px]">
                {skills && skills.length > 0 && (
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-muted-foreground">Skills:</span>
                    {skills.map((s) => (
                      <button
                        key={s.name}
                        type="button"
                        onClick={() => toggleItem(selectedSkills, s.name, setSelectedSkills)}
                        title={s.description}
                        className={`px-1.5 py-px rounded border transition-colors ${
                          selectedSkills.includes(s.name)
                            ? "bg-primary-50 border-primary-300 text-primary-700"
                            : "border-border text-muted-foreground hover:border-primary-200"
                        }`}
                      >
                        {s.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {/* Secondary options inline */}
              <div className="flex gap-2 items-center">
                <select value={reportType} onChange={(e) => setReportType(e.target.value)} className="px-2 py-1 border border-border rounded text-xs bg-background text-foreground">
                  <option value="">No report</option>
                  {REPORT_TYPES.filter(Boolean).map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <div className="flex items-center gap-1">
                  <span className="text-[10px] text-muted-foreground">Timeout:</span>
                  <input type="number" min={0} value={timeout} onChange={(e) => setTimeout(Number(e.target.value))} className="w-14 px-1.5 py-1 border border-border rounded text-xs bg-background" />
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-[10px] text-muted-foreground">Retry:</span>
                  <input type="number" min={0} max={5} value={maxRetries} onChange={(e) => setMaxRetries(Number(e.target.value))} className="w-12 px-1.5 py-1 border border-border rounded text-xs bg-background" />
                </div>
              </div>
            </div>
          )}

          {/* Footer */}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">
              Cancel
            </button>
            <button type="submit" disabled={saving} className="px-4 py-1.5 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50 transition-colors">
              {saving ? "Saving..." : scheduleType === "one_time" ? "Create & Run" : "Save"}
            </button>
          </div>
        </form>
        {/* Resize handle */}
        <div
          onMouseDown={onResizeDown}
          className="absolute bottom-0 right-0 w-4 h-4 cursor-se-resize"
          style={{ background: "linear-gradient(135deg, transparent 50%, var(--color-border) 50%)" }}
        />
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
    header: "Type / Cron",
    render: (r) =>
      r.cron_expression === "@once" ? (
        <Badge className={r.is_enabled ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700"}>
          {r.is_enabled ? "Running" : "Completed"}
        </Badge>
      ) : (
        <span className="font-mono text-sm">{r.cron_expression}</span>
      ),
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

type TabFilter = "all" | "recurring" | "one_shot";

const PAGE_SIZE = 10;

export default function Schedules() {
  const navigate = useNavigate();
  const { data: schedules, isLoading, error } = useSchedules();
  const createMut = useCreateSchedule();
  const updateMut = useUpdateSchedule();
  const deleteMut = useDeleteSchedule();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [deleting, setDeleting] = useState<Schedule | null>(null);
  const [tab, setTab] = useState<TabFilter>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  const filtered = (schedules ?? []).filter((s) => {
    const isOneTime = s.schedule_type === "one_time" || s.cron_expression === "@once";
    if (tab === "recurring") return !isOneTime;
    if (tab === "one_shot") return isOneTime;
    return true;
  }).filter((s) =>
    !search || s.name.toLowerCase().includes(search.toLowerCase()) || s.pipeline_name.toLowerCase().includes(search.toLowerCase())
  );

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner message={(error as Error).message} />;

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold text-foreground">Schedules</h2>
            <div className="flex gap-1 bg-secondary rounded-lg p-0.5">
              {(["all", "recurring", "one_shot"] as TabFilter[]).map((t) => (
                <button
                  key={t}
                  onClick={() => { setTab(t); setPage(0); }}
                  className={`px-3 py-1 text-xs rounded-md transition-colors ${
                    tab === t
                      ? "bg-background text-foreground shadow-sm font-medium"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t === "all" ? `All (${schedules?.length ?? 0})` : t === "recurring" ? "Recurring" : "One-shot"}
                </button>
              ))}
            </div>
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0); }}
              placeholder="Search..."
              className="px-3 py-1.5 text-sm border border-border rounded-lg bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary-500 w-40"
            />
          </div>
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
            {
              key: "_index",
              header: "#",
              render: (r) => <span className="text-xs text-muted-foreground font-mono">{page * PAGE_SIZE + paginated.indexOf(r) + 1}</span>,
            },
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
          data={paginated}
          rowKey={(r) => r.id}
          onRowClick={(r) => navigate(`/app/schedules/${r.id}`)}
          emptyMessage={search ? "No matching tasks." : tab === "one_shot" ? "No one-shot tasks yet." : "No schedules configured."}
        />
        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-border">
            <span className="text-xs text-muted-foreground">
              {filtered.length} total &middot; Page {page + 1}/{totalPages}
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
                className="px-2 py-1 text-xs border border-border rounded hover:bg-secondary disabled:opacity-30"
              >
                Prev
              </button>
              <button
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                disabled={page >= totalPages - 1}
                className="px-2 py-1 text-xs border border-border rounded hover:bg-secondary disabled:opacity-30"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </Card>

      {formOpen && (
        <ScheduleFormModal
          initial={editing}
          defaultType={tab === "one_shot" ? "one_time" : "recurring"}
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
