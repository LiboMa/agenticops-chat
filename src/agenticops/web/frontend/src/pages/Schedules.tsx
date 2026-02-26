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
} from "@/hooks/useSchedules";
import type { Schedule, ScheduleCreate, ScheduleUpdate } from "@/api/types";

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
  const [pipelineName, setPipelineName] = useState(initial?.pipeline_name ?? "");
  const [cronExpression, setCronExpression] = useState(initial?.cron_expression ?? "");
  const [accountName, setAccountName] = useState(initial?.account_name ?? "");
  const [isEnabled, setIsEnabled] = useState(initial?.is_enabled ?? true);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (isEdit) {
      const data: ScheduleUpdate = {
        name,
        pipeline_name: pipelineName,
        cron_expression: cronExpression,
        account_name: accountName || undefined,
        is_enabled: isEnabled,
      };
      onSave(data);
    } else {
      const data: ScheduleCreate = {
        name,
        pipeline_name: pipelineName,
        cron_expression: cronExpression,
        account_name: accountName || undefined,
        is_enabled: isEnabled,
      };
      onSave(data);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-lg w-full max-w-md p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-4">
          {isEdit ? "Edit Schedule" : "New Schedule"}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Name</label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Pipeline</label>
            <input
              required
              value={pipelineName}
              onChange={(e) => setPipelineName(e.target.value)}
              placeholder="scan, detect, report"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Cron Expression
            </label>
            <input
              required
              value={cronExpression}
              onChange={(e) => setCronExpression(e.target.value)}
              placeholder="0 */6 * * *"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Account Name (optional)
            </label>
            <input
              value={accountName}
              onChange={(e) => setAccountName(e.target.value)}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              id="schedule-enabled"
              type="checkbox"
              checked={isEnabled}
              onChange={(e) => setIsEnabled(e.target.checked)}
              className="rounded border-slate-200"
            />
            <label htmlFor="schedule-enabled" className="text-sm text-slate-700">
              Enabled
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50"
            >
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
      <div className="bg-white rounded-lg shadow-lg w-full max-w-sm p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-2">Delete Schedule</h3>
        <p className="text-sm text-slate-600 mb-4">
          Are you sure you want to delete <strong>{schedule.name}</strong>? This action
          cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50"
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
    render: (r) => <span className="font-medium text-slate-900">{r.name}</span>,
  },
  {
    key: "pipeline_name",
    header: "Pipeline",
    render: (r) => (
      <Badge className="bg-blue-100 text-blue-700">{r.pipeline_name}</Badge>
    ),
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
        <Badge className="bg-slate-100 text-slate-500">Disabled</Badge>
      ),
  },
  {
    key: "last_run_at",
    header: "Last Run",
    sortable: true,
    sortValue: (r) => r.last_run_at ?? "",
    render: (r) => (
      <span className="text-sm text-slate-500">
        {r.last_run_at ? formatShortDate(r.last_run_at) : "Never"}
      </span>
    ),
  },
  {
    key: "next_run_at",
    header: "Next Run",
    render: (r) => (
      <span className="text-sm text-slate-500">
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
          <h2 className="text-lg font-semibold text-slate-900">Schedules</h2>
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
