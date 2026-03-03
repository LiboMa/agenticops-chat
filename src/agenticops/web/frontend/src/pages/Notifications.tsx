import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { apiFetch } from "@/api/client";
import {
  useNotificationChannels,
  useCreateChannel,
  useUpdateChannel,
  useDeleteChannel,
  useTestChannel,
} from "@/hooks/useNotifications";
import type {
  NotificationChannel,
  NotificationChannelCreate,
  NotificationChannelUpdate,
  NotificationChannelType,
} from "@/api/types";

const CHANNEL_TYPES: NotificationChannelType[] = ["slack", "email", "sns", "feishu", "dingtalk", "wecom", "webhook"];
const SEVERITY_OPTIONS = ["critical", "high", "medium", "low"];

/* ------------------------------------------------------------------ */
/*  Channel form modal                                                 */
/* ------------------------------------------------------------------ */

interface FormModalProps {
  initial?: NotificationChannel | null;
  onClose: () => void;
  onSave: (data: NotificationChannelCreate | NotificationChannelUpdate) => void;
  saving: boolean;
}

function ChannelFormModal({ initial, onClose, onSave, saving }: FormModalProps) {
  const isEdit = !!initial;
  const [name, setName] = useState(initial?.name ?? "");
  const [channelType, setChannelType] = useState<NotificationChannelType>(
    initial?.channel_type ?? "slack",
  );
  const [configJson, setConfigJson] = useState(
    initial?.config ? JSON.stringify(initial.config, null, 2) : "{}",
  );
  const [severityFilter, setSeverityFilter] = useState<string[]>(
    initial?.severity_filter ?? [],
  );
  const [isEnabled, setIsEnabled] = useState(initial?.is_enabled ?? true);
  const [configError, setConfigError] = useState("");

  function toggleSeverity(s: string) {
    setSeverityFilter((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
    );
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    let parsedConfig: Record<string, unknown>;
    try {
      parsedConfig = JSON.parse(configJson);
      setConfigError("");
    } catch {
      setConfigError("Invalid JSON");
      return;
    }

    const payload = {
      name,
      channel_type: channelType,
      config: parsedConfig,
      severity_filter: severityFilter,
      is_enabled: isEnabled,
    };

    onSave(payload);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-lg w-full max-w-md p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-4">
          {isEdit ? "Edit Channel" : "New Channel"}
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
            <label className="block text-sm font-medium text-slate-700 mb-1">Type</label>
            <select
              value={channelType}
              onChange={(e) => setChannelType(e.target.value as NotificationChannelType)}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              {CHANNEL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Config (JSON)
            </label>
            <textarea
              value={configJson}
              onChange={(e) => setConfigJson(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            {configError && (
              <p className="text-xs text-red-600 mt-1">{configError}</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Severity Filter
            </label>
            <div className="flex gap-2">
              {SEVERITY_OPTIONS.map((s) => (
                <label key={s} className="flex items-center gap-1 text-sm">
                  <input
                    type="checkbox"
                    checked={severityFilter.includes(s)}
                    onChange={() => toggleSeverity(s)}
                    className="rounded border-slate-200"
                  />
                  {s}
                </label>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="channel-enabled"
              type="checkbox"
              checked={isEnabled}
              onChange={(e) => setIsEnabled(e.target.checked)}
              className="rounded border-slate-200"
            />
            <label htmlFor="channel-enabled" className="text-sm text-slate-700">
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
  channel,
  onClose,
  onConfirm,
  deleting,
}: {
  channel: NotificationChannel;
  onClose: () => void;
  onConfirm: () => void;
  deleting: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-lg w-full max-w-sm p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-2">Delete Channel</h3>
        <p className="text-sm text-slate-600 mb-4">
          Are you sure you want to delete <strong>{channel.name}</strong>? This action
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
/*  IM Bot status types + card                                         */
/* ------------------------------------------------------------------ */

interface IMBotStatus {
  platform: string;
  mode: string;
  apps: string[];
  status: string;
  active_sessions: number;
  ws_enabled?: boolean;
  ws_thread_alive?: boolean;
  callback_url?: string;
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    connected: "bg-green-100 text-green-700",
    ready: "bg-blue-100 text-blue-700",
    disconnected: "bg-red-100 text-red-700",
    not_configured: "bg-slate-100 text-slate-500",
  };
  const labels: Record<string, string> = {
    connected: "Connected",
    ready: "Ready",
    disconnected: "Disconnected",
    not_configured: "Not Configured",
  };
  return (
    <Badge className={styles[status] ?? "bg-slate-100 text-slate-500"}>
      {labels[status] ?? status}
    </Badge>
  );
}

function IMBotsCard() {
  const { data: bots, isLoading, error } = useQuery<IMBotStatus[]>({
    queryKey: ["im-bots"],
    queryFn: () => apiFetch("/api/im/bots"),
    refetchInterval: 30_000,
  });

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-slate-900">IM Bots</h2>
      </CardHeader>
      {isLoading ? (
        <div className="p-4"><Spinner /></div>
      ) : error ? (
        <div className="p-4"><ErrorBanner message={(error as Error).message} /></div>
      ) : (
        <div className="divide-y divide-slate-100">
          {(bots ?? []).map((bot) => (
            <div key={bot.platform} className="flex items-center justify-between px-6 py-3">
              <div className="flex items-center gap-3">
                <PlatformBadge platform={bot.platform} />
                <div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={bot.status} />
                    <span className="text-xs text-slate-400 uppercase">{bot.mode}</span>
                  </div>
                  {bot.apps.length > 0 && (
                    <p className="text-xs text-slate-500 mt-0.5">
                      Apps: {bot.apps.join(", ")}
                    </p>
                  )}
                </div>
              </div>
              <div className="text-right text-sm text-slate-500">
                {bot.active_sessions > 0 && (
                  <span>{bot.active_sessions} active session{bot.active_sessions !== 1 ? "s" : ""}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function PlatformBadge({ platform }: { platform: string }) {
  const colors: Record<string, string> = {
    feishu: "bg-teal-100 text-teal-700",
    dingtalk: "bg-sky-100 text-sky-700",
    wecom: "bg-emerald-100 text-emerald-700",
  };
  return <Badge className={colors[platform] ?? "bg-slate-100 text-slate-700"}>{platform}</Badge>;
}

/* ------------------------------------------------------------------ */
/*  Channel type badge colors                                          */
/* ------------------------------------------------------------------ */

function ChannelTypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    slack: "bg-purple-100 text-purple-700",
    email: "bg-blue-100 text-blue-700",
    sns: "bg-orange-100 text-orange-700",
    feishu: "bg-teal-100 text-teal-700",
    dingtalk: "bg-sky-100 text-sky-700",
    wecom: "bg-emerald-100 text-emerald-700",
    webhook: "bg-slate-100 text-slate-700",
  };
  return <Badge className={colors[type] ?? "bg-slate-100 text-slate-700"}>{type}</Badge>;
}

/* ------------------------------------------------------------------ */
/*  Main page                                                          */
/* ------------------------------------------------------------------ */

const columns: Column<NotificationChannel>[] = [
  {
    key: "name",
    header: "Name",
    sortable: true,
    sortValue: (r) => r.name,
    render: (r) => <span className="font-medium text-slate-900">{r.name}</span>,
  },
  {
    key: "channel_type",
    header: "Type",
    render: (r) => <ChannelTypeBadge type={r.channel_type} />,
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
    key: "severity_filter",
    header: "Severity Filter",
    render: (r) =>
      r.severity_filter.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {r.severity_filter.map((s) => (
            <Badge key={s} className="bg-slate-100 text-slate-600">
              {s}
            </Badge>
          ))}
        </div>
      ) : (
        <span className="text-sm text-slate-400">all</span>
      ),
  },
];

export default function Notifications() {
  const navigate = useNavigate();
  const { data: channels, isLoading, error } = useNotificationChannels();
  const createMut = useCreateChannel();
  const updateMut = useUpdateChannel();
  const deleteMut = useDeleteChannel();
  const testMut = useTestChannel();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<NotificationChannel | null>(null);
  const [deleting, setDeleting] = useState<NotificationChannel | null>(null);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner message={(error as Error).message} />;

  return (
    <div className="space-y-6">
      <IMBotsCard />

      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-slate-900">
              Notification Channels
            </h2>
            <button
              onClick={() => navigate("/app/notifications/logs")}
              className="px-3 py-1.5 text-xs text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
            >
              View Logs
            </button>
          </div>
          <button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
            className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500"
          >
            New Channel
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
                      testMut.mutate(r.name);
                    }}
                    disabled={testMut.isPending}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    Test
                  </button>
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
          data={channels ?? []}
          rowKey={(r) => r.name}
          emptyMessage="No notification channels configured."
        />
      </Card>

      {formOpen && (
        <ChannelFormModal
          initial={editing}
          saving={createMut.isPending || updateMut.isPending}
          onClose={() => {
            setFormOpen(false);
            setEditing(null);
          }}
          onSave={async (data) => {
            if (editing) {
              await updateMut.mutateAsync({
                name: editing.name,
                data: data as NotificationChannelUpdate,
              });
            } else {
              await createMut.mutateAsync(data as NotificationChannelCreate);
            }
            setFormOpen(false);
            setEditing(null);
          }}
        />
      )}

      {deleting && (
        <DeleteModal
          channel={deleting}
          deleting={deleteMut.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await deleteMut.mutateAsync(deleting.name);
            setDeleting(null);
          }}
        />
      )}
    </div>
  );
}
