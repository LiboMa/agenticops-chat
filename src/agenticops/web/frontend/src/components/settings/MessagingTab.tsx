import { useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ConfigureModal } from "./ConfigureModal";
import { buildConfigPayload, channelFields, appFields } from "@/lib/messagingFields";
import {
  useMessagingSchema, useMessagingApps, useMessagingChannels, useMessagingLogs,
  useUpsertApp, useDeleteApp, useUpsertChannel, useDeleteChannel, useToggleChannel, useTestChannel,
  type ChannelInfo,
} from "@/hooks/useMessaging";

const APP_PLATFORMS = ["feishu", "slack", "dingtalk", "wecom"] as const;

function StatusBadge({ on, label }: { on: boolean; label: string }) {
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-md font-semibold inline-flex items-center gap-1 ${on ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" : "bg-secondary text-muted-foreground"}`}>
      {on && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}{label}
    </span>
  );
}

function Switch({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <div onClick={onClick} className={`relative w-9 h-5 rounded-full cursor-pointer transition-colors ${on ? "bg-primary-600" : "bg-muted-foreground/30"}`}>
      <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
    </div>
  );
}

function IconBtn({ title, onClick, children }: { title: string; onClick: () => void; children: React.ReactNode }) {
  return <button title={title} onClick={onClick} className="w-7 h-7 rounded-lg border border-border bg-background text-muted-foreground hover:text-foreground hover:bg-secondary flex items-center justify-center">{children}</button>;
}

const GearIcon = () => <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><circle cx="12" cy="12" r="3" /><path strokeLinecap="round" strokeLinejoin="round" d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-2.82 1.17V21a2 2 0 11-4 0v-.09A1.65 1.65 0 007.18 19.4l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 004.6 13.82 1.65 1.65 0 003 12.09V12a2 2 0 110-4h.09A1.65 1.65 0 004.6 6.18l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 3.6V3a2 2 0 114 0v.09a1.65 1.65 0 002.82 1.17l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0021 9.18V9a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 2z" /></svg>;
const BoltIcon = () => <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" /></svg>;

interface ModalState {
  mode: "app" | "channel";
  name?: string; type?: string; values?: Record<string, string>; enabled?: boolean; role?: string;
}

export function MessagingTab() {
  const schemaQ = useMessagingSchema();
  const appsQ = useMessagingApps();
  const channelsQ = useMessagingChannels();
  const logsQ = useMessagingLogs();
  const upsertApp = useUpsertApp();
  const deleteApp = useDeleteApp();
  const upsertChannel = useUpsertChannel();
  const deleteChannel = useDeleteChannel();
  const toggleChannel = useToggleChannel();
  const testChannel = useTestChannel();

  const [modal, setModal] = useState<ModalState | null>(null);
  const [restartHint, setRestartHint] = useState(false);

  const handleSave = (a: { name: string; type: string; enabled: boolean; role: string; values: Record<string, string> }) => {
    if (!modal) return;
    if (modal.mode === "app") {
      const fields = appFields(schemaQ.data, a.type);
      const config = buildConfigPayload(fields, a.values);
      upsertApp.mutate({ platform: a.type, name: a.name, config }, {
        onSuccess: () => { setModal(null); setRestartHint(true); },
      });
    } else {
      const fields = channelFields(schemaQ.data, a.type);
      const config = buildConfigPayload(fields, a.values);
      upsertChannel.mutate({ name: a.name, data: { type: a.type, enabled: a.enabled, role: a.role, config } }, {
        onSuccess: () => setModal(null),
      });
    }
  };

  return (
    <div className="space-y-5">
      {restartHint && (
        <div className="flex items-center gap-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 text-amber-800 dark:text-amber-300 rounded-lg px-3 py-2 text-xs">
          <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h16.9a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" /></svg>
          Bot credentials saved — restart the service (<code className="font-mono">aiops service restart</code>) for the IM gateway to pick them up.
          <button onClick={() => setRestartHint(false)} className="ml-auto text-amber-600">Dismiss</button>
        </div>
      )}

      {/* BOT APPS */}
      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold text-foreground">Bot Apps</h2>
          <button onClick={() => setModal({ mode: "app" })} className="px-2.5 py-1 text-xs font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700">+ Connect Bot</button>
        </CardHeader>
        <CardBody>
          {appsQ.isLoading ? <Spinner /> : appsQ.error ? <ErrorBanner message="Failed to load apps" /> : (
            <div className="space-y-2">
              {APP_PLATFORMS.flatMap((platform) =>
                Object.entries(appsQ.data?.[platform] ?? {}).map(([name, cfg]) => (
                  <div key={`${platform}/${name}`} className="flex items-center gap-3 p-2.5 border border-border rounded-lg">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-foreground flex items-center gap-2">{platform}/{name} <StatusBadge on label="Configured" /></div>
                      <div className="text-[11px] text-muted-foreground truncate">{Object.entries(cfg).map(([k, v]) => `${k}=${v}`).join("  ·  ")}</div>
                    </div>
                    <IconBtn title="Configure" onClick={() => setModal({ mode: "app", name, type: platform, values: cfg as Record<string, string> })}><GearIcon /></IconBtn>
                    <button onClick={() => deleteApp.mutate({ platform, name })} className="text-xs text-red-600 hover:underline">Delete</button>
                  </div>
                ))
              )}
              {APP_PLATFORMS.every((p) => !Object.keys(appsQ.data?.[p] ?? {}).length) && <p className="text-sm text-muted-foreground">No bot apps configured.</p>}
            </div>
          )}
        </CardBody>
      </Card>

      {/* CHANNELS */}
      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold text-foreground">Channels</h2>
          <button onClick={() => setModal({ mode: "channel" })} className="px-2.5 py-1 text-xs font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700">+ Add Channel</button>
        </CardHeader>
        <CardBody>
          {channelsQ.isLoading ? <Spinner /> : channelsQ.error ? <ErrorBanner message="Failed to load channels" /> : (
            <div className="space-y-2">
              {(channelsQ.data ?? []).map((ch: ChannelInfo) => (
                <div key={ch.name} className="flex items-center gap-3 p-2.5 border border-border rounded-lg">
                  <Switch on={ch.enabled} onClick={() => toggleChannel.mutate({ name: ch.name, enabled: !ch.enabled })} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground flex items-center gap-2">{ch.name} <StatusBadge on={ch.enabled} label={ch.enabled ? "Enabled" : "Disabled"} /></div>
                    <div className="text-[11px] text-muted-foreground">{ch.type} · role: {ch.role}</div>
                  </div>
                  <IconBtn title="Test" onClick={() => testChannel.mutate(ch.name)}><BoltIcon /></IconBtn>
                  <IconBtn title="Configure" onClick={() => setModal({ mode: "channel", name: ch.name, type: ch.type, enabled: ch.enabled, role: ch.role, values: ch.config as Record<string, string> })}><GearIcon /></IconBtn>
                  <button onClick={() => deleteChannel.mutate(ch.name)} className="text-xs text-red-600 hover:underline">Delete</button>
                </div>
              ))}
              {!(channelsQ.data ?? []).length && <p className="text-sm text-muted-foreground">No channels configured.</p>}
            </div>
          )}
        </CardBody>
      </Card>

      {/* DELIVERY LOGS */}
      <Card>
        <CardHeader><h2 className="text-base font-semibold text-foreground">Delivery Logs</h2></CardHeader>
        <CardBody>
          {logsQ.isLoading ? <Spinner /> : (
            <div className="space-y-1.5">
              {(logsQ.data ?? []).slice(0, 20).map((log) => (
                <div key={log.id} className="flex items-center gap-2 text-xs p-2 border border-border rounded-lg">
                  <span className={`px-1.5 py-0.5 rounded font-semibold ${log.status === "sent" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>{log.status}</span>
                  <span className="font-medium text-foreground">{log.channel_name}</span>
                  <span className="text-muted-foreground truncate flex-1">{log.subject}</span>
                  <span className="text-muted-foreground/60">{new Date(log.sent_at).toLocaleString()}</span>
                </div>
              ))}
              {!(logsQ.data ?? []).length && <p className="text-sm text-muted-foreground">No delivery logs yet.</p>}
            </div>
          )}
        </CardBody>
      </Card>

      {modal && (
        <ConfigureModal
          mode={modal.mode}
          schema={schemaQ.data}
          initialName={modal.name}
          initialType={modal.type}
          initialValues={modal.values}
          initialEnabled={modal.enabled}
          initialRole={modal.role}
          saving={upsertApp.isPending || upsertChannel.isPending}
          onClose={() => setModal(null)}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
