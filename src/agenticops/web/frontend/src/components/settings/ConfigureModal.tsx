import { useMemo, useState } from "react";
import { channelFields, appFields, missingRequired, type MessagingSchema, type FieldDescriptor } from "@/lib/messagingFields";

interface Props {
  mode: "app" | "channel";
  schema: MessagingSchema | undefined;
  initialName?: string;
  initialType?: string;            // channel type OR app platform
  initialValues?: Record<string, string>;
  initialEnabled?: boolean;
  initialRole?: string;
  onClose: () => void;
  onSave: (args: { name: string; type: string; enabled: boolean; role: string; values: Record<string, string> }) => void;
  saving?: boolean;
}

const inputCls = "w-full px-3 py-2 border border-border rounded-lg text-sm bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary-500";

export function ConfigureModal({ mode, schema, initialName, initialType, initialValues, initialEnabled, initialRole, onClose, onSave, saving }: Props) {
  const isApp = mode === "app";
  const types = (isApp ? schema?.app_platforms : schema?.channel_types) ?? [];
  const [type, setType] = useState(initialType ?? (isApp ? "feishu" : "slack"));
  const [name, setName] = useState(initialName ?? (isApp ? "default" : ""));
  const [enabled] = useState(initialEnabled ?? true);  // no UI toggle; always passed through
  const [role, setRole] = useState(initialRole ?? "alert");
  const [values, setValues] = useState<Record<string, string>>(initialValues ?? {});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [err, setErr] = useState<string[]>([]);

  const fields: FieldDescriptor[] = useMemo(
    () => (isApp ? appFields(schema, type) : channelFields(schema, type)),
    [isApp, schema, type],
  );

  const handleSave = () => {
    const missing = missingRequired(fields, values);
    if (!name.trim()) missing.unshift("name");
    if (missing.length) { setErr(missing); return; }
    onSave({ name: name.trim(), type, enabled, role, values });
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-card border border-border rounded-xl shadow-xl w-[380px] max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <h3 className="font-semibold text-foreground text-sm">{isApp ? "Configure Bot App" : "Configure Channel"}</h3>
          <button onClick={onClose} className="ml-auto text-muted-foreground hover:text-foreground">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        <div className="px-4 py-3 space-y-3">
          {/* Type tiles */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground">Type</label>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {types.map((tp) => {
                const key = (isApp ? tp.platform : tp.type) as string;
                const active = key === type;
                return (
                  <button key={key} onClick={() => setType(key)}
                    className={`px-2.5 py-1.5 rounded-lg text-xs border transition-colors ${active ? "border-primary-500 bg-primary-50 text-primary-700 font-semibold" : "border-border text-muted-foreground hover:bg-secondary"}`}>
                    {tp.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Name */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground">{isApp ? "App name" : "Channel name"} <span className="text-red-500">*</span></label>
            <input className={inputCls} value={name} disabled={!!initialName} onChange={(e) => setName(e.target.value)} placeholder={isApp ? "default" : "e.g. feishu-alert"} />
          </div>

          {/* Channel-only: role */}
          {!isApp && (
            <div>
              <label className="text-xs font-semibold text-muted-foreground">Role</label>
              <select className={inputCls} value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="alert">alert — 告警/报告投递</option>
                <option value="chat">chat — 双向对话</option>
              </select>
            </div>
          )}

          {/* Dynamic fields */}
          {fields.map((f) => (
            <div key={f.key}>
              <label className="text-xs font-semibold text-muted-foreground">{f.label} {f.required && <span className="text-red-500">*</span>}</label>
              <div className="relative">
                <input
                  className={`${inputCls} ${f.secret ? "pr-9 font-mono" : ""}`}
                  type={f.secret && !revealed[f.key] ? "password" : f.type === "number" ? "number" : "text"}
                  value={values[f.key] ?? ""}
                  placeholder={f.secret && initialName ? "•••• (leave blank to keep)" : ""}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
                {f.secret && (
                  <button type="button" onClick={() => setRevealed((r) => ({ ...r, [f.key]: !r[f.key] }))}
                    className="absolute right-2 top-2.5 text-muted-foreground hover:text-foreground">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></svg>
                  </button>
                )}
              </div>
              {f.secret && <p className="text-[10px] text-muted-foreground mt-0.5">Encrypted at rest</p>}
            </div>
          ))}

          {err.length > 0 && <p className="text-xs text-red-500">Required: {err.join(", ")}</p>}
        </div>

        <div className="flex items-center gap-2 px-4 py-3 border-t border-border">
          <span className="text-[11px] text-muted-foreground mr-auto">{isApp ? "Inbound bot credentials" : "Outbound routing"}</span>
          <button onClick={onClose} className="px-3 py-1.5 text-sm border border-border rounded-lg text-foreground hover:bg-secondary">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="px-3 py-1.5 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-700 disabled:opacity-50">
            {saving ? "Saving…" : "Save & enable"}
          </button>
        </div>
      </div>
    </div>
  );
}
