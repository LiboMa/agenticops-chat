import { useState, useRef, useCallback } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { formatShortDate } from "@/lib/formatDate";
import { useLocale } from "@/i18n/LocaleContext";
import { useScanFocus } from "@/hooks/useScanFocus";
import { useSettings, useUpdateSettings } from "@/hooks/useSettings";
import { useExcludePatterns, useUpdateExcludePatterns } from "@/hooks/useExcludePatterns";
import { NotificationsTab } from "@/components/settings/NotificationsTab";
import { NotificationLogsTab } from "@/components/settings/NotificationLogsTab";
import { AuditTab } from "@/components/settings/AuditTab";
import { KBTab } from "@/components/settings/KBTab";
import { SkillsTab } from "@/components/settings/SkillsTab";
import {
  useAccounts,
  useCreateAccount,
  useUpdateAccount,
  useDeleteAccount,
} from "@/hooks/useAccounts";
import {
  useMcpServers,
  useUpsertMcpServer,
  useDeleteMcpServer,
  useReloadMcpServers,
  useImportMcpServers,
} from "@/hooks/useMcpServers";
import {
  useAgentMemories,
  useUpdateAgentMemory,
  useDeleteAgentMemory,
  type AgentMemory,
} from "@/hooks/useAgentMemory";
import {
  useImApps,
  useUpsertImApp,
  useDeleteImApp,
  useChannels,
  useUpsertChannel,
  useDeleteChannel,
  useToggleChannel,
} from "@/hooks/useImApps";
import type { ScanFocus, AgentModelConfig } from "@/api/types";
import type { Account, AccountCreate, AccountUpdate, CloudProvider, McpServerConfig } from "@/api/types";

/* ── Scan Focus section ─────────────────────────────────────────── */

const FOCUS_META: Record<ScanFocus, { label: string; services: string; icon: JSX.Element }> = {
  all:        { label: "All",       services: "All categories",                     icon: <IconAll /> },
  computing:  { label: "Compute",   services: "EC2, Lambda, ECS, EKS, AutoScaling", icon: <IconCompute /> },
  networking: { label: "Network",   services: "VPC, SG, ELB, Subnet, NAT GW, Route53",  icon: <IconNetwork /> },
  databases:  { label: "Database",  services: "RDS, DynamoDB, ElastiCache, OpenSearch",  icon: <IconDatabase /> },
  storage:    { label: "Storage",   services: "S3, EBS, EFS",                icon: <IconStorage /> },
  security:   { label: "Security",  services: "IAM Roles, KMS",            icon: <IconSecurity /> },
  billing:    { label: "Billing",   services: "Cost Explorer, Budgets, Quotas",      icon: <IconBilling /> },
};

function FocusToggle({
  label, description, icon, active, onClick,
}: {
  label: string; description: string; icon: JSX.Element; active: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`group flex items-start gap-3 p-3 rounded-lg border transition-all text-left ${
        active
          ? "bg-primary-50 border-primary-300 shadow-sm"
          : "bg-background border-border hover:border-border hover:bg-secondary"
      }`}
    >
      <div className={`mt-0.5 flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
        active ? "bg-primary-100 text-primary-600" : "bg-secondary text-muted-foreground group-hover:text-muted-foreground"
      }`}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${active ? "text-primary-700" : "text-foreground"}`}>
            {label}
          </span>
          <div className={`w-7 h-4 rounded-full transition-colors flex items-center ${
            active ? "bg-primary-500 justify-end" : "bg-muted-foreground/30 justify-start"
          }`}>
            <div className="w-3 h-3 mx-0.5 rounded-full bg-background shadow-sm" />
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 leading-tight">{description}</p>
      </div>
    </button>
  );
}

/* ── Pipeline toggle ────────────────────────────────────────────── */

function SettingToggle({
  label, description, enabled, onChange, saving,
}: {
  label: string; description: string; enabled: boolean; onChange: (v: boolean) => void; saving?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-border/50 last:border-b-0">
      <div>
        <span className="text-sm font-medium text-foreground">{label}</span>
        <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
      </div>
      <button
        onClick={() => onChange(!enabled)}
        disabled={saving}
        className={`relative w-10 h-5 rounded-full transition-colors ${
          enabled ? "bg-primary-500" : "bg-muted-foreground/30"
        } ${saving ? "opacity-50 cursor-not-allowed" : ""}`}
      >
        <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-background shadow-sm transition-transform ${
          enabled ? "translate-x-5" : "translate-x-0.5"
        }`} />
      </button>
    </div>
  );
}

/* ── Account form modal ────────────────────────────────────────── */

const PROVIDER_OPTIONS: { value: CloudProvider; label: string }[] = [
  { value: "aws", label: "AWS" },
  { value: "azure", label: "Azure" },
  { value: "gcp", label: "GCP" },
  { value: "alicloud", label: "Alicloud" },
];

const PROVIDER_FIELDS: Record<CloudProvider, { key: string; label: string; type?: string; placeholder: string }[]> = {
  aws: [
    { key: "role_arn", label: "Role ARN", placeholder: "arn:aws:iam::123456789012:role/AgenticOps" },
    { key: "external_id", label: "External ID", placeholder: "Optional" },
    { key: "account_id", label: "Account ID", placeholder: "123456789012" },
    { key: "profile_name", label: "Profile Name", placeholder: "default (from ~/.aws/credentials)" },
  ],
  azure: [
    { key: "subscription_id", label: "Subscription ID", placeholder: "00000000-0000-0000-0000-000000000000" },
    { key: "tenant_id", label: "Tenant ID", placeholder: "00000000-0000-0000-0000-000000000000" },
    { key: "client_id", label: "Client ID", placeholder: "Service Principal App ID" },
    { key: "client_secret", label: "Client Secret", type: "password", placeholder: "Service Principal Secret" },
  ],
  gcp: [
    { key: "project_id", label: "Project ID", placeholder: "my-gcp-project" },
    { key: "service_account_key", label: "Service Account Key (JSON)", type: "textarea", placeholder: '{"type": "service_account", ...}' },
  ],
  alicloud: [
    { key: "access_key_id", label: "Access Key ID", placeholder: "LTAI..." },
    { key: "access_key_secret", label: "Access Key Secret", type: "password", placeholder: "Secret" },
    { key: "account_id", label: "Account ID", placeholder: "1234567890" },
  ],
};

function AccountFormModal({
  initial, onClose, onSave, saving, error,
}: {
  initial?: Account | null; onClose: () => void;
  onSave: (data: AccountCreate | AccountUpdate) => void; saving: boolean;
  error?: string | null;
}) {
  const isEdit = !!initial;
  const [provider, setProvider] = useState<CloudProvider>(initial?.provider ?? "aws");
  const [name, setName] = useState(initial?.name ?? "");
  const [regions, setRegions] = useState(initial?.regions?.join(", ") ?? "");
  const [isEnabled, setIsEnabled] = useState(initial?.is_enabled ?? true);
  // Seed credential fields from existing account (edit mode)
  const initialCreds: Record<string, string> = {};
  if (initial?.credentials) {
    for (const [k, v] of Object.entries(initial.credentials)) {
      if (typeof v === "string" && v !== "***REDACTED***") {
        initialCreds[k] = v;
      } else if (typeof v === "object" && v !== null) {
        initialCreds[k] = JSON.stringify(v, null, 2);
      }
    }
  }
  const hasExplicitCreds = isEdit && Object.keys(initial?.credentials ?? {}).length > 0;
  const [useEnvDefaults, setUseEnvDefaults] = useState(isEdit ? !hasExplicitCreds : false);
  const [creds, setCreds] = useState<Record<string, string>>(initialCreds);

  const fields = PROVIDER_FIELDS[provider];

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const regionList = regions.split(",").map((r) => r.trim()).filter(Boolean);

    const credentials: Record<string, unknown> = {};
    if (!useEnvDefaults) {
      for (const f of fields) {
        const val = creds[f.key]?.trim();
        if (val) {
          credentials[f.key] = f.key === "service_account_key" ? JSON.parse(val) : val;
        }
      }
    }

    if (isEdit) {
      onSave({ name, credentials, regions: regionList, is_enabled: isEnabled } as AccountUpdate);
    } else {
      onSave({ name, provider, credentials, regions: regionList, is_enabled: isEnabled } as AccountCreate);
    }
  }

  const inputClass = "w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-semibold text-foreground mb-4">
          {isEdit ? "Edit Account" : "New Account"}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Provider</label>
            <select
              value={provider}
              onChange={(e) => { setProvider(e.target.value as CloudProvider); setCreds({}); }}
              disabled={isEdit}
              className={`${inputClass} disabled:bg-secondary`}
            >
              {PROVIDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Name</label>
            <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. aws-prod, azure-staging" className={inputClass} />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Regions (comma-separated)</label>
            <input value={regions} onChange={(e) => setRegions(e.target.value)} placeholder="us-east-1, us-west-2" className={inputClass} />
          </div>
          <div className="flex items-center gap-2">
            <input id="use-env" type="checkbox" checked={useEnvDefaults} onChange={(e) => setUseEnvDefaults(e.target.checked)} className="rounded border-border" />
            <label htmlFor="use-env" className="text-sm text-muted-foreground">Use environment / CLI defaults (no explicit credentials)</label>
          </div>
          {!useEnvDefaults && (
            <div className="space-y-3 border-t border-border pt-3">
              <p className="text-xs text-muted-foreground">{provider.toUpperCase()} Credentials — leave blank to use env defaults</p>
              {fields.map((f) => (
                <div key={f.key}>
                  <label className="block text-sm font-medium text-foreground mb-1">{f.label}</label>
                  {f.type === "textarea" ? (
                    <textarea
                      value={creds[f.key] ?? ""}
                      onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })}
                      placeholder={f.placeholder}
                      rows={4}
                      className={inputClass}
                    />
                  ) : (
                    <input
                      type={f.type ?? "text"}
                      value={creds[f.key] ?? ""}
                      onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })}
                      placeholder={f.placeholder}
                      className={inputClass}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2">
            <input id="is-enabled-settings" type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} className="rounded border-border" />
            <label htmlFor="is-enabled-settings" className="text-sm text-foreground">Enabled</label>
          </div>
          {error && (
            <div className="p-3 rounded-lg border bg-red-50 border-red-200 text-sm text-red-700">{error}</div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">Cancel</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50">{saving ? "Saving..." : "Save"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function DeleteModal({
  account, onClose, onConfirm, deleting,
}: {
  account: Account; onClose: () => void; onConfirm: () => void; deleting: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-sm p-6">
        <h3 className="text-lg font-semibold text-foreground mb-2">Delete Account</h3>
        <p className="text-sm text-muted-foreground mb-4">
          Are you sure you want to delete <strong>{account.name}</strong> ({account.provider.toUpperCase()})? This action cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">Cancel</button>
          <button onClick={onConfirm} disabled={deleting} className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-500 disabled:opacity-50">{deleting ? "Deleting..." : "Delete"}</button>
        </div>
      </div>
    </div>
  );
}

/* ── Accounts columns ───────────────────────────────────────────── */

const SETTINGS_PROVIDER_BADGE: Record<CloudProvider, string> = {
  aws: "bg-orange-100 text-orange-700",
  azure: "bg-blue-100 text-blue-700",
  gcp: "bg-green-100 text-green-700",
  alicloud: "bg-purple-100 text-purple-700",
};

const accountColumns: Column<Account>[] = [
  { key: "name", header: "Name", sortable: true, sortValue: (r) => r.name, render: (r) => <span className="font-medium text-foreground">{r.name}</span> },
  { key: "provider", header: "Provider", render: (r) => <Badge className={SETTINGS_PROVIDER_BADGE[r.provider]}>{r.provider.toUpperCase()}</Badge> },
  { key: "regions", header: "Regions", render: (r) => <div className="flex flex-wrap gap-1">{r.regions.map((reg) => <Badge key={reg} className="bg-secondary text-muted-foreground">{reg}</Badge>)}</div> },
  { key: "is_enabled", header: "Status", render: (r) => r.is_enabled ? <Badge className="bg-green-100 text-green-700">Enabled</Badge> : <Badge className="bg-secondary text-muted-foreground">Disabled</Badge> },
  { key: "last_scanned_at", header: "Last Scanned", sortable: true, sortValue: (r) => r.last_scanned_at ?? "", render: (r) => <span className="text-sm text-muted-foreground">{r.last_scanned_at ? formatShortDate(r.last_scanned_at) : "Never"}</span> },
];

/* ── MCP Server form modal ────────────────────────────────────────── */

function McpServerFormModal({
  initial, onClose, onSave, saving,
}: {
  initial: { name: string; config: McpServerConfig } | null;
  onClose: () => void;
  onSave: (name: string, config: McpServerConfig) => void;
  saving: boolean;
}) {
  const isEdit = !!initial;
  const [name, setName] = useState(initial?.name ?? "");
  const [command, setCommand] = useState(initial?.config.command ?? "");
  const [args, setArgs] = useState((initial?.config.args ?? []).join(" "));
  const [envText, setEnvText] = useState(
    Object.entries(initial?.config.env ?? {}).map(([k, v]) => `${k}=${v}`).join("\n"),
  );
  const [disabled, setDisabled] = useState(initial?.config.disabled ?? false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const argList = args.trim() ? args.trim().split(/\s+/) : [];
    const env: Record<string, string> = {};
    envText.split("\n").filter(Boolean).forEach((line) => {
      const eq = line.indexOf("=");
      if (eq > 0) env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
    });
    onSave(name, {
      command: command || undefined,
      args: argList.length ? argList : undefined,
      env: Object.keys(env).length ? env : undefined,
      disabled,
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-md p-6">
        <h3 className="text-lg font-semibold text-foreground mb-4">
          {isEdit ? "Edit MCP Server" : "New MCP Server"}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Server Name</label>
            <input required disabled={isEdit} value={name} onChange={(e) => setName(e.target.value)} placeholder="awslabs.aws-documentation-mcp-server" className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-secondary font-mono" />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Command</label>
            <input required value={command} onChange={(e) => setCommand(e.target.value)} placeholder="uvx" className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Args (space-separated)</label>
            <input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="awslabs.aws-documentation-mcp-server@latest" className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Environment (KEY=VALUE per line)</label>
            <textarea rows={3} value={envText} onChange={(e) => setEnvText(e.target.value)} placeholder={"FASTMCP_LOG_LEVEL=ERROR\nAWS_DOCUMENTATION_PARTITION=aws"} className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
          <div className="flex items-center gap-2">
            <input id="mcp-disabled" type="checkbox" checked={disabled} onChange={(e) => setDisabled(e.target.checked)} className="rounded border-border" />
            <label htmlFor="mcp-disabled" className="text-sm text-foreground">Disabled</label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">Cancel</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50">{saving ? "Saving..." : "Save"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ── MCP Import Dialog ──────────────────────────────────────────── */

interface McpValidationResult {
  valid: boolean;
  servers: string[];
  error?: string;
}

function validateMcpJson(text: string): McpValidationResult {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { valid: false, servers: [], error: "Invalid JSON syntax" };
  }
  if (!data || typeof data !== "object") {
    return { valid: false, servers: [], error: "Expected a JSON object" };
  }
  const obj = data as Record<string, unknown>;
  if (!obj.mcpServers || typeof obj.mcpServers !== "object" || Array.isArray(obj.mcpServers)) {
    return { valid: false, servers: [], error: 'Missing or invalid "mcpServers" key. Expected {"mcpServers": {...}}' };
  }
  const entries = Object.entries(obj.mcpServers as Record<string, unknown>);
  if (entries.length === 0) {
    return { valid: false, servers: [], error: "mcpServers is empty" };
  }
  const invalid: string[] = [];
  for (const [name, cfg] of entries) {
    if (!cfg || typeof cfg !== "object") {
      invalid.push(name);
      continue;
    }
    const c = cfg as Record<string, unknown>;
    if (!c.command && !c.url) {
      invalid.push(name);
    }
  }
  if (invalid.length > 0) {
    return { valid: false, servers: [], error: `Servers missing "command" or "url": ${invalid.join(", ")}` };
  }
  return { valid: true, servers: entries.map(([n]) => n) };
}

function McpImportDialog({
  onClose,
  onImport,
  importing,
}: {
  onClose: () => void;
  onImport: (data: unknown) => Promise<void>;
  importing: boolean;
}) {
  const [mode, setMode] = useState<"file" | "paste">("file");
  const [jsonText, setJsonText] = useState("");
  const [validation, setValidation] = useState<McpValidationResult | null>(null);
  const [importResult, setImportResult] = useState<{ success: boolean; servers: string[] } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const validate = useCallback((text: string) => {
    setJsonText(text);
    setImportResult(null);
    if (!text.trim()) {
      setValidation(null);
      return;
    }
    setValidation(validateMcpJson(text));
  }, []);

  function handleFileLoad(file: File) {
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      validate(text);
    };
    reader.readAsText(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".json")) handleFileLoad(file);
  }

  async function handleImport() {
    if (!validation?.valid) return;
    try {
      const data = JSON.parse(jsonText);
      await onImport(data);
      setImportResult({ success: true, servers: validation.servers });
      setTimeout(onClose, 2000);
    } catch (err) {
      setImportResult({ success: false, servers: [] });
      setValidation({ valid: false, servers: [], error: String(err) });
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-lg p-6">
        <h3 className="text-lg font-semibold text-foreground mb-4">Import MCP Servers</h3>

        {/* Mode tabs */}
        <div className="flex gap-1 mb-4 bg-secondary rounded-lg p-1">
          <button
            onClick={() => { setMode("file"); setJsonText(""); setValidation(null); setImportResult(null); }}
            className={`flex-1 px-3 py-1.5 text-sm rounded-md transition-colors ${mode === "file" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          >Upload File</button>
          <button
            onClick={() => { setMode("paste"); setJsonText(""); setValidation(null); setImportResult(null); }}
            className={`flex-1 px-3 py-1.5 text-sm rounded-md transition-colors ${mode === "paste" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          >Paste JSON</button>
        </div>

        {/* File upload zone */}
        {mode === "file" && (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              dragOver ? "border-primary-400 bg-primary-50" : "border-border hover:border-border hover:bg-secondary"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFileLoad(file);
                e.target.value = "";
              }}
            />
            <p className="text-sm text-muted-foreground">Drop a .json file here or click to browse</p>
            <p className="text-xs text-muted-foreground mt-1">{'Expected format: {"mcpServers": {...}}'}</p>
          </div>
        )}

        {/* Paste textarea */}
        {mode === "paste" && (
          <textarea
            rows={8}
            value={jsonText}
            onChange={(e) => validate(e.target.value)}
            placeholder={'{\n  "mcpServers": {\n    "my-server": {\n      "command": "uvx",\n      "args": ["my-mcp-server"]\n    }\n  }\n}'}
            className="w-full px-3 py-2 border border-border rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        )}

        {/* Validation result */}
        {validation && (
          <div className={`mt-3 p-3 rounded-lg border text-sm ${
            validation.valid
              ? "bg-green-50 border-green-200 text-green-700"
              : "bg-red-50 border-red-200 text-red-700"
          }`}>
            {validation.valid ? (
              <div>
                <span className="font-medium">{validation.servers.length} server{validation.servers.length > 1 ? "s" : ""} found</span>
                <ul className="mt-1 ml-4 list-disc text-xs">
                  {validation.servers.map((s) => <li key={s} className="font-mono">{s}</li>)}
                </ul>
              </div>
            ) : (
              <span>{validation.error}</span>
            )}
          </div>
        )}

        {/* Import success feedback */}
        {importResult?.success && (
          <div className="mt-3 p-3 rounded-lg border bg-green-50 border-green-200 text-sm text-green-700">
            Imported {importResult.servers.length} server{importResult.servers.length > 1 ? "s" : ""} successfully. Closing...
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">Cancel</button>
          <button
            onClick={handleImport}
            disabled={!validation?.valid || importing || !!importResult?.success}
            className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50"
          >{importing ? "Importing..." : "Import"}</button>
        </div>
      </div>
    </div>
  );
}

/* ── Exclude Patterns Card ──────────────────────────────────────── */

function ExcludePatternsCard() {
  const { t } = useLocale();
  const patternsQ = useExcludePatterns();
  const updateMut = useUpdateExcludePatterns();
  const [newPattern, setNewPattern] = useState("");
  const [localPatterns, setLocalPatterns] = useState<string[] | null>(null);
  const [dirty, setDirty] = useState(false);

  const patterns = localPatterns ?? patternsQ.data?.patterns ?? [];

  function handleAdd() {
    const trimmed = newPattern.trim();
    if (!trimmed || patterns.includes(trimmed)) return;
    const updated = [...patterns, trimmed];
    setLocalPatterns(updated);
    setNewPattern("");
    setDirty(true);
  }

  function handleRemove(idx: number) {
    const updated = patterns.filter((_, i) => i !== idx);
    setLocalPatterns(updated);
    setDirty(true);
  }

  function handleSave() {
    updateMut.mutate(patterns, {
      onSuccess: () => {
        setDirty(false);
        setLocalPatterns(null);
      },
    });
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <h2 className="text-lg font-semibold text-foreground">{t("settings.excludePatterns")}</h2>
          <span className="text-xs text-muted-foreground">{t("settings.excludePatternsDesc")}</span>
        </div>
      </CardHeader>
      <CardBody>
        {patternsQ.isLoading ? (
          <Spinner />
        ) : patternsQ.error ? (
          <ErrorBanner message={(patternsQ.error as Error).message} onRetry={() => patternsQ.refetch()} />
        ) : (
          <>
            <div className="space-y-2 mb-4">
              {patterns.length === 0 ? (
                <p className="text-sm text-muted-foreground">No exclude patterns configured.</p>
              ) : (
                patterns.map((p, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded-lg border border-border bg-background">
                    <span className="text-sm font-mono text-foreground">{p}</span>
                    <button
                      onClick={() => handleRemove(i)}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                ))
              )}
            </div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={newPattern}
                onChange={(e) => setNewPattern(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                placeholder="e.g. (?i)informational|advisory"
                className="flex-1 px-3 py-2 border border-border rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
              <button
                onClick={handleAdd}
                disabled={!newPattern.trim()}
                className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50"
              >
                Add
              </button>
            </div>
            {dirty && (
              <div className="flex justify-end mt-3">
                <button
                  onClick={handleSave}
                  disabled={updateMut.isPending}
                  className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50"
                >
                  {updateMut.isPending ? "Saving..." : "Save"}
                </button>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}

/* ── Agent Models Card ──────────────────────────────────────────── */

// MODEL_PRESETS loaded from GET /api/settings → s.model_presets (single source: config.py)
const MODEL_PRESETS_FALLBACK = [
  { label: "Opus 4.6", value: "global.anthropic.claude-opus-4-6-v1" },
  { label: "Sonnet 4.6", value: "global.anthropic.claude-sonnet-4-6" },
  { label: "Haiku 4.5", value: "global.anthropic.claude-haiku-4-5-20251001-v1:0" },
];

const AGENT_LABELS: Record<string, { label: string; tier: string }> = {
  main:     { label: "Main (Router)",  tier: "default" },
  scan:     { label: "Scan",           tier: "cheap" },
  detect:   { label: "Detect",         tier: "cheap" },
  rca:      { label: "RCA",            tier: "strong" },
  sre:      { label: "SRE",            tier: "strong" },
  executor: { label: "Executor",       tier: "default" },
  reporter: { label: "Reporter",       tier: "cheap" },
};

const TIER_COLORS: Record<string, string> = {
  default: "bg-blue-100 text-blue-700",
  cheap:   "bg-green-100 text-green-700",
  strong:  "bg-purple-100 text-purple-700",
};

function AgentModelsCard() {
  const settingsQ = useSettings();
  const updateMut = useUpdateSettings();
  const s = settingsQ.data;

  function handleModelChange(agentName: string, modelId: string) {
    updateMut.mutate({ agent_models: { [agentName]: { model_id: modelId } } });
  }

  function handleMaxTokensChange(agentName: string, maxTokens: number) {
    updateMut.mutate({ agent_models: { [agentName]: { max_tokens: maxTokens } } });
  }

  function handleWindowSizeChange(agentName: string, windowSize: number) {
    updateMut.mutate({ agent_models: { [agentName]: { window_size: windowSize } } });
  }

  function handleReset(agentName: string) {
    updateMut.mutate({ agent_models: { [agentName]: { model_id: "", max_tokens: 0, window_size: 0 } } });
  }

  if (settingsQ.isLoading) return <Card><CardBody><Spinner /></CardBody></Card>;
  if (settingsQ.error) return <Card><CardBody><ErrorBanner message={settingsQ.error.message} onRetry={() => settingsQ.refetch()} /></CardBody></Card>;
  if (!s) return null;

  const agents = s.agent_models ?? {};
  const presets = s.model_presets?.length ? s.model_presets : MODEL_PRESETS_FALLBACK;

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">Agent Models</h2>
        <span className="text-xs text-muted-foreground">Per-agent model & token configuration</span>
      </CardHeader>
      <CardBody>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                <th className="pb-2 pr-4">Agent</th>
                <th className="pb-2 pr-4">Tier</th>
                <th className="pb-2 pr-4">Model</th>
                <th className="pb-2 pr-4">Max Tokens</th>
                <th className="pb-2 pr-4">Window</th>
                <th className="pb-2"></th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(agents).map(([name, cfg]: [string, AgentModelConfig]) => {
                const meta = AGENT_LABELS[name] ?? { label: name, tier: "default" };
                const currentPreset = presets.find((p) => p.value === cfg.model_id);
                return (
                  <tr key={name} className="border-b border-border">
                    <td className="py-2.5 pr-4 font-medium text-foreground">{meta.label}</td>
                    <td className="py-2.5 pr-4">
                      <Badge className={TIER_COLORS[meta.tier] ?? "bg-secondary text-muted-foreground"}>
                        {meta.tier}
                      </Badge>
                    </td>
                    <td className="py-2.5 pr-4">
                      <select
                        value={cfg.model_id}
                        onChange={(e) => handleModelChange(name, e.target.value)}
                        disabled={updateMut.isPending}
                        className="px-2 py-1 border border-border rounded text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50 max-w-[260px]"
                      >
                        {presets.map((p) => (
                          <option key={p.value} value={p.value}>{p.label}</option>
                        ))}
                        {!currentPreset && <option value={cfg.model_id}>{cfg.model_id}</option>}
                      </select>
                    </td>
                    <td className="py-2.5 pr-4">
                      <input
                        type="number"
                        value={cfg.max_tokens}
                        onChange={(e) => handleMaxTokensChange(name, parseInt(e.target.value) || 0)}
                        disabled={updateMut.isPending}
                        className="w-24 px-2 py-1 border border-border rounded text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
                      />
                    </td>
                    <td className="py-2.5 pr-4">
                      <div className="flex items-center gap-2">
                        <select
                          value={cfg.window_size === -1 ? "-1" : cfg.window_size === 0 ? "0" : "custom"}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v === "-1" || v === "0") handleWindowSizeChange(name, parseInt(v));
                            else if (v === "custom") handleWindowSizeChange(name, 20);
                          }}
                          disabled={updateMut.isPending}
                          className="px-2 py-1 border border-border rounded text-xs focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
                        >
                          <option value="0">Auto</option>
                          <option value="-1">Full Context</option>
                          <option value="custom">Custom</option>
                        </select>
                        {cfg.window_size > 0 && (
                          <input
                            type="number"
                            value={cfg.window_size}
                            onChange={(e) => handleWindowSizeChange(name, Math.max(1, parseInt(e.target.value) || 1))}
                            disabled={updateMut.isPending}
                            className="w-20 px-2 py-1 border border-border rounded text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
                          />
                        )}
                        <Badge className={cfg.window_mode === "full" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}>
                          {cfg.window_mode === "full" ? "Full" : "Sliding"}
                        </Badge>
                      </div>
                    </td>
                    <td className="py-2.5">
                      <button
                        onClick={() => handleReset(name)}
                        disabled={updateMut.isPending}
                        className="text-xs text-muted-foreground hover:text-red-600 disabled:opacity-50"
                        title="Reset to tier default"
                      >Reset</button>
                    </td>
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

/* ── IM Connections (read-only) ─────────────────────────────────── */

function IMConnectionsCard({ feishuActive, slackActive }: { feishuActive: boolean; slackActive: boolean }) {
  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">IM Connections</h2>
        <span className="text-xs text-muted-foreground">Auto-detected from channels.yaml</span>
      </CardHeader>
      <CardBody>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">Feishu WebSocket</span>
            </div>
            <Badge className={feishuActive ? "bg-green-100 text-green-700" : "bg-secondary text-muted-foreground"}>
              {feishuActive ? "Active" : "Inactive"}
            </Badge>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">Slack Socket Mode</span>
            </div>
            <Badge className={slackActive ? "bg-green-100 text-green-700" : "bg-secondary text-muted-foreground"}>
              {slackActive ? "Active" : "Inactive"}
            </Badge>
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-3">
          Add an enabled feishu/slack channel in <code className="bg-secondary px-1 rounded">config/channels.yaml</code> to activate WebSocket connections.
        </p>
      </CardBody>
    </Card>
  );
}

/* ── Report Storage ────────────────────────────────────────────── */

function ReportStorageCard({
  settings: s,
  onSave,
  saving,
}: {
  settings: import("@/hooks/useSettings").AppSettings;
  onSave: (patch: Record<string, unknown>) => void;
  saving: boolean;
}) {
  const [storage, setStorage] = useState(s.report_storage);
  const [bucket, setBucket] = useState(s.report_s3_bucket);
  const [prefix, setPrefix] = useState(s.report_s3_prefix);
  const [region, setRegion] = useState(s.report_s3_region);
  const [expiry, setExpiry] = useState(s.report_presigned_url_expiry);

  const dirty =
    storage !== s.report_storage ||
    bucket !== s.report_s3_bucket ||
    prefix !== s.report_s3_prefix ||
    region !== s.report_s3_region ||
    expiry !== s.report_presigned_url_expiry;

  const handleSave = () => {
    onSave({
      report_storage: storage,
      report_s3_bucket: bucket,
      report_s3_prefix: prefix,
      report_s3_region: region,
      report_presigned_url_expiry: expiry,
    });
  };

  const inputClass = "w-full px-3 py-2 border border-border rounded-lg text-sm bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary-500";

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">Report Storage</h2>
        <span className="text-xs text-muted-foreground">Configure where reports are stored</span>
      </CardHeader>
      <CardBody>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Storage Backend</label>
            <select value={storage} onChange={(e) => setStorage(e.target.value)} className={inputClass}>
              <option value="local">Local Filesystem</option>
              <option value="s3">Amazon S3</option>
            </select>
          </div>

          {storage === "s3" && (
            <>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">S3 Bucket</label>
                <input value={bucket} onChange={(e) => setBucket(e.target.value)} placeholder="my-reports-bucket" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">S3 Prefix</label>
                <input value={prefix} onChange={(e) => setPrefix(e.target.value)} placeholder="reports/" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">S3 Region</label>
                <input value={region} onChange={(e) => setRegion(e.target.value)} placeholder="us-east-1" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Pre-signed URL Expiry (seconds)</label>
                <input type="number" value={expiry} onChange={(e) => setExpiry(Number(e.target.value))} min={60} className={inputClass} />
                <p className="text-xs text-muted-foreground mt-1">
                  Default: 604800 (7 days). URLs in reports/notifications expire after this.
                </p>
              </div>
            </>
          )}

          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </CardBody>
    </Card>
  );
}

/* ── IM Bots Tab ───────────────────────────────────────────────── */

const IM_PLATFORMS = ["feishu", "slack", "dingtalk", "wecom"] as const;
const IM_FIELDS: Record<string, { label: string; secret: boolean }[]> = {
  feishu: [{ label: "app_id", secret: false }, { label: "app_secret", secret: true }],
  slack: [{ label: "bot_token", secret: true }, { label: "app_token", secret: true }],
  dingtalk: [{ label: "app_key", secret: false }, { label: "app_secret", secret: true }],
  wecom: [{ label: "corp_id", secret: false }, { label: "agent_id", secret: false }, { label: "secret", secret: true }],
};

function ImBotsTab() {
  const appsQ = useImApps();
  const channelsQ = useChannels();
  const upsertApp = useUpsertImApp();
  const deleteApp = useDeleteImApp();
  const upsertChannel = useUpsertChannel();
  const deleteChannel = useDeleteChannel();
  const toggleChannel = useToggleChannel();

  const [showAppForm, setShowAppForm] = useState(false);
  const [appPlatform, setAppPlatform] = useState<string>("feishu");
  const [appName, setAppName] = useState("default");
  const [appFields, setAppFields] = useState<Record<string, string>>({});

  const [showChForm, setShowChForm] = useState(false);
  const [chName, setChName] = useState("");
  const [chType, setChType] = useState("feishu");
  const [chChatId, setChChatId] = useState("");
  const [chEnabled, setChEnabled] = useState(true);

  const handleSaveApp = () => {
    upsertApp.mutate({ platform: appPlatform, name: appName, config: appFields }, {
      onSuccess: () => { setShowAppForm(false); setAppFields({}); },
    });
  };

  const handleSaveChannel = () => {
    const data: Record<string, unknown> = { type: chType, enabled: chEnabled };
    if (chChatId) data.chat_id = chChatId;
    upsertChannel.mutate({ name: chName, data }, {
      onSuccess: () => { setShowChForm(false); setChName(""); setChChatId(""); },
    });
  };

  const inputCls = "w-full px-3 py-2 border border-border rounded-lg text-sm bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary-500";

  return (
    <>
      {/* IM Apps */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">IM Bot Apps</h2>
          <button onClick={() => setShowAppForm(true)} className="px-3 py-1.5 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500">
            Add App
          </button>
        </CardHeader>
        <CardBody>
          {appsQ.isLoading ? <Spinner /> : appsQ.error ? <ErrorBanner message="Failed to load" /> : (
            <div className="space-y-3">
              {Object.entries(appsQ.data || {}).map(([platform, apps]) =>
                Object.entries(apps).map(([name, cfg]) => (
                  <div key={`${platform}/${name}`} className="flex items-center justify-between p-3 bg-secondary/50 rounded-lg">
                    <div>
                      <span className="text-sm font-medium text-foreground">{platform}/{name}</span>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {Object.entries(cfg).map(([k, v]) => `${k}=${v}`).join(", ")}
                      </p>
                    </div>
                    <button onClick={() => deleteApp.mutate({ platform, name })} className="text-xs text-red-600 hover:underline">
                      Delete
                    </button>
                  </div>
                ))
              )}
              {!Object.keys(appsQ.data || {}).length && (
                <p className="text-sm text-muted-foreground">No IM apps configured.</p>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Channels */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">Notification Channels</h2>
          <button onClick={() => setShowChForm(true)} className="px-3 py-1.5 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500">
            Add Channel
          </button>
        </CardHeader>
        <CardBody>
          {channelsQ.isLoading ? <Spinner /> : (
            <div className="space-y-2">
              {(channelsQ.data || []).map((ch) => (
                <div key={ch.name} className="flex items-center justify-between p-3 bg-secondary/50 rounded-lg">
                  <div className="flex items-center gap-3">
                    <div
                      onClick={() => toggleChannel.mutate({ name: ch.name, enabled: !ch.enabled })}
                      className={`relative w-9 h-5 rounded-full cursor-pointer transition-colors ${ch.enabled ? "bg-primary-500" : "bg-muted-foreground/30"}`}
                    >
                      <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${ch.enabled ? "translate-x-[18px]" : "translate-x-0.5"}`} />
                    </div>
                    <div>
                      <span className="text-sm font-medium text-foreground">{ch.name}</span>
                      <span className="ml-2 text-xs text-muted-foreground">{ch.type} · {ch.role}</span>
                    </div>
                  </div>
                  <button onClick={() => deleteChannel.mutate(ch.name)} className="text-xs text-red-600 hover:underline">
                    Delete
                  </button>
                </div>
              ))}
              {!(channelsQ.data || []).length && (
                <p className="text-sm text-muted-foreground">No channels configured.</p>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Add App Modal */}
      {showAppForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background rounded-xl shadow-lg w-full max-w-md p-5 border border-border/50">
            <h3 className="text-base font-semibold mb-4">Add IM Bot App</h3>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Platform</label>
                  <select value={appPlatform} onChange={(e) => { setAppPlatform(e.target.value); setAppFields({}); }} className={inputCls}>
                    {IM_PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">App Name</label>
                  <input value={appName} onChange={(e) => setAppName(e.target.value)} className={inputCls} />
                </div>
              </div>
              {(IM_FIELDS[appPlatform] || []).map((f) => (
                <div key={f.label}>
                  <label className="block text-xs text-muted-foreground mb-1">{f.label}</label>
                  <input
                    type={f.secret ? "password" : "text"}
                    value={appFields[f.label] || ""}
                    onChange={(e) => setAppFields({ ...appFields, [f.label]: e.target.value })}
                    className={inputCls}
                  />
                </div>
              ))}
              <div className="flex justify-end gap-2 pt-2">
                <button onClick={() => setShowAppForm(false)} className="px-3 py-1.5 text-sm text-muted-foreground">Cancel</button>
                <button onClick={handleSaveApp} disabled={upsertApp.isPending} className="px-4 py-1.5 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50">
                  {upsertApp.isPending ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Add Channel Modal */}
      {showChForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background rounded-xl shadow-lg w-full max-w-md p-5 border border-border/50">
            <h3 className="text-base font-semibold mb-4">Add Channel</h3>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Name</label>
                  <input value={chName} onChange={(e) => setChName(e.target.value)} placeholder="feishu-ops" className={inputCls} />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Type</label>
                  <select value={chType} onChange={(e) => setChType(e.target.value)} className={inputCls}>
                    {["feishu", "slack", "dingtalk", "wecom", "email", "ses", "sns", "sns-report", "webhook"].map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Chat ID / Webhook URL</label>
                <input value={chChatId} onChange={(e) => setChChatId(e.target.value)} placeholder="oc_xxx or https://..." className={inputCls} />
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={chEnabled} onChange={(e) => setChEnabled(e.target.checked)} className="rounded border-border" />
                <span className="text-sm text-foreground">Enabled</span>
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button onClick={() => setShowChForm(false)} className="px-3 py-1.5 text-sm text-muted-foreground">Cancel</button>
                <button onClick={handleSaveChannel} disabled={!chName || upsertChannel.isPending} className="px-4 py-1.5 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50">
                  {upsertChannel.isPending ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/* ── Main Settings page ─────────────────────────────────────────── */

export default function Settings() {
  const { selected: focusSelected, toggle: toggleFocus, focusValue, ALL_CATEGORIES } = useScanFocus();
  const settingsQ = useSettings();
  const updateMut = useUpdateSettings();

  // Accounts
  const [filterProvider, setFilterProvider] = useState<string>("");
  const { data: accounts, isLoading: acctLoading, error: acctError } = useAccounts(filterProvider || undefined);
  const createMut = useCreateAccount();
  const updateAcctMut = useUpdateAccount();
  const deleteMut = useDeleteAccount();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);
  const [acctFormError, setAcctFormError] = useState<string | null>(null);

  // MCP Servers
  const mcpQ = useMcpServers();
  const upsertMcp = useUpsertMcpServer();
  const deleteMcp = useDeleteMcpServer();
  const reloadMcp = useReloadMcpServers();
  const importMcp = useImportMcpServers();
  const [mcpFormOpen, setMcpFormOpen] = useState(false);
  const [mcpEditing, setMcpEditing] = useState<{ name: string; config: McpServerConfig } | null>(null);
  const [mcpDeleting, setMcpDeleting] = useState<string | null>(null);
  const [mcpImportOpen, setMcpImportOpen] = useState(false);

  // Agent Memory
  const [memAgent, setMemAgent] = useState("");
  const [memStatus, setMemStatus] = useState("active");
  const memQ = useAgentMemories(memAgent, memStatus);
  const updateMemMut = useUpdateAgentMemory();
  const deleteMemMut = useDeleteAgentMemory();
  const [memEditing, setMemEditing] = useState<AgentMemory | null>(null);
  const [memEditConf, setMemEditConf] = useState(3);

  const s = settingsQ.data;

  function patchSetting(key: string, value: boolean) {
    updateMut.mutate({ [key]: value });
  }

  const { t } = useLocale();
  const tabTriggerClass = "px-4 py-2 text-sm font-medium border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:text-primary text-muted-foreground hover:text-foreground transition-colors";

  return (
    <div className="max-w-5xl">
      <h1 className="text-2xl font-semibold text-foreground mb-4">{t("settings.title")}</h1>

      <Tabs.Root defaultValue="general">
        <Tabs.List className="flex border-b border-border mb-6 gap-0 overflow-x-auto">
          <Tabs.Trigger value="general" className={tabTriggerClass}>{t("settings.general")}</Tabs.Trigger>
          <Tabs.Trigger value="accounts" className={tabTriggerClass}>{t("settings.accounts")}</Tabs.Trigger>
          <Tabs.Trigger value="notifications" className={tabTriggerClass}>{t("settings.notifications")}</Tabs.Trigger>
          <Tabs.Trigger value="audit" className={tabTriggerClass}>{t("settings.audit")}</Tabs.Trigger>
          <Tabs.Trigger value="kb" className={tabTriggerClass}>{t("settings.kb")}</Tabs.Trigger>
          <Tabs.Trigger value="skills" className={tabTriggerClass}>{t("settings.skills")}</Tabs.Trigger>
          <Tabs.Trigger value="im-bots" className={tabTriggerClass}>IM Bots</Tabs.Trigger>
          <Tabs.Trigger value="mcp" className={tabTriggerClass}>{t("settings.mcp")}</Tabs.Trigger>
          <Tabs.Trigger value="memory" className={tabTriggerClass}>Agent Memory</Tabs.Trigger>
        </Tabs.List>

        {/* ── General Tab ──────────────────────────────────────── */}
        <Tabs.Content value="general" className="space-y-6">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">Scan Focus</h2>
          <span className="text-xs text-muted-foreground">
            {focusValue === "all" ? "All categories" : focusValue.split(",").join(", ")}
          </span>
        </CardHeader>
        <CardBody>
          <p className="text-sm text-muted-foreground mb-4">
            Select which resource categories to focus on when scanning and detecting health issues.
            This applies globally to Chat, CLI, and agent dispatches.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            <FocusToggle
              label="All"
              description="All categories"
              icon={<IconAll />}
              active={focusSelected.has("all")}
              onClick={() => toggleFocus("all")}
            />
            {ALL_CATEGORIES.map((cat) => (
              <FocusToggle
                key={cat}
                label={FOCUS_META[cat].label}
                description={FOCUS_META[cat].services}
                icon={FOCUS_META[cat].icon}
                active={focusSelected.has("all") || focusSelected.has(cat)}
                onClick={() => toggleFocus(cat)}
              />
            ))}
          </div>
        </CardBody>
      </Card>

      {/* ── Pipeline & Automation ─────────────────────────────── */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">Pipeline & Automation</h2>
        </CardHeader>
        <CardBody>
          {settingsQ.isLoading ? (
            <Spinner />
          ) : settingsQ.error ? (
            <ErrorBanner message={settingsQ.error.message} onRetry={() => settingsQ.refetch()} />
          ) : s ? (
            <div>
              <SettingToggle
                label="Auto RCA"
                description="Automatically trigger root cause analysis when a new issue is created"
                enabled={s.auto_rca_enabled}
                onChange={(v) => patchSetting("auto_rca_enabled", v)}
                saving={updateMut.isPending}
              />
              <SettingToggle
                label="Auto Fix Pipeline"
                description="Automatically run RCA, SRE planning, approval, and execution pipeline"
                enabled={s.auto_fix_enabled}
                onChange={(v) => patchSetting("auto_fix_enabled", v)}
                saving={updateMut.isPending}
              />
              <SettingToggle
                label="Executor"
                description="Enable fix plan execution engine"
                enabled={s.executor_enabled}
                onChange={(v) => patchSetting("executor_enabled", v)}
                saving={updateMut.isPending}
              />
              <SettingToggle
                label="Auto-approve L0/L1"
                description="Automatically approve low-risk (L0) and minor (L1) fix plans"
                enabled={s.executor_auto_approve_l0_l1}
                onChange={(v) => patchSetting("executor_auto_approve_l0_l1", v)}
                saving={updateMut.isPending}
              />
              <SettingToggle
                label="Notifications"
                description="Send automatic notifications on pipeline events"
                enabled={s.notifications_enabled}
                onChange={(v) => patchSetting("notifications_enabled", v)}
                saving={updateMut.isPending}
              />
              <SettingToggle
                label="Consolidated Notifications"
                description="Send a single pipeline summary instead of per-stage notifications"
                enabled={s.notifications_consolidated}
                onChange={(v) => patchSetting("notifications_consolidated", v)}
                saving={updateMut.isPending}
              />
              <SettingToggle
                label="Prompt Caching"
                description="Enable Bedrock prompt caching on all agents (reduces latency & cost)"
                enabled={s.bedrock_cache_enabled}
                onChange={(v) => patchSetting("bedrock_cache_enabled", v)}
                saving={updateMut.isPending}
              />
              <SettingToggle
                label="Skill Auto-Improve"
                description="Enable agents and post-resolution pipeline to suggest skill improvements"
                enabled={s.skills_auto_improve_enabled}
                onChange={(v) => patchSetting("skills_auto_improve_enabled", v)}
                saving={updateMut.isPending}
              />
              <SettingToggle
                label="Post-Resolution Skill Review"
                description="Analyze skill gaps after each issue is resolved"
                enabled={s.skills_post_resolution_review}
                onChange={(v) => patchSetting("skills_post_resolution_review", v)}
                saving={updateMut.isPending}
              />
              <SettingToggle
                label="Skill Improvement Notify"
                description="Send notification when skill improvement drafts are created"
                enabled={s.skills_improvement_notify}
                onChange={(v) => patchSetting("skills_improvement_notify", v)}
                saving={updateMut.isPending}
              />
            </div>
          ) : null}
        </CardBody>
      </Card>

      {/* ── Exclude Patterns ─────────────────────────────────── */}
      <ExcludePatternsCard />

      {/* ── Agent Models ─────────────────────────────────────── */}
      <AgentModelsCard />

      {/* ── IM Connections (read-only status) ────────────────── */}
      {s && <IMConnectionsCard feishuActive={s.feishu_ws_active} slackActive={s.slack_ws_active} />}

      {/* ── Report Storage ───────────────────────────────────── */}
      {s && <ReportStorageCard settings={s} onSave={(patch) => updateMut.mutate(patch)} saving={updateMut.isPending} />}
        </Tabs.Content>

        {/* ── Accounts Tab ─────────────────────────────────────── */}
        <Tabs.Content value="accounts" className="space-y-6">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">Cloud Accounts</h2>
          <div className="flex items-center gap-3">
            <select
              value={filterProvider}
              onChange={(e) => setFilterProvider(e.target.value)}
              className="px-3 py-2 text-sm border border-border rounded-lg bg-background text-foreground"
            >
              <option value="">All Providers</option>
              {PROVIDER_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <button
              onClick={() => { setEditing(null); setFormOpen(true); }}
              className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500"
            >
              New Account
            </button>
          </div>
        </CardHeader>
        {acctLoading ? (
          <div className="p-6"><Spinner /></div>
        ) : acctError ? (
          <div className="p-6"><ErrorBanner message={(acctError as Error).message} /></div>
        ) : (
          <DataTable
            columns={[
              ...accountColumns,
              {
                key: "actions",
                header: "",
                render: (r) => (
                  <div className="flex gap-2">
                    <button onClick={(e) => { e.stopPropagation(); setEditing(r); setFormOpen(true); }} className="text-xs text-primary-600 hover:underline">Edit</button>
                    <button onClick={(e) => { e.stopPropagation(); setDeleting(r); }} className="text-xs text-red-600 hover:underline">Delete</button>
                  </div>
                ),
              },
            ]}
            data={accounts ?? []}
            rowKey={(r) => r.id}
            emptyMessage="No accounts configured."
          />
        )}
      </Card>

        </Tabs.Content>

        {/* ── Notifications Tab ────────────────────────────────── */}
        <Tabs.Content value="notifications" className="space-y-6">
          <NotificationsTab />
          <NotificationLogsTab />
        </Tabs.Content>

        {/* ── Audit Tab ────────────────────────────────────────── */}
        <Tabs.Content value="audit">
          <AuditTab />
        </Tabs.Content>

        {/* ── Knowledge Base Tab ───────────────────────────────── */}
        <Tabs.Content value="kb">
          <KBTab />
        </Tabs.Content>

        {/* ── Skills Tab ───────────────────────────────────────── */}
        <Tabs.Content value="skills">
          <SkillsTab />
        </Tabs.Content>

        {/* ── IM Bots Tab ─────────────────────────────────────── */}
        <Tabs.Content value="im-bots" className="space-y-6">
          <ImBotsTab />
        </Tabs.Content>

        {/* ── MCP Servers Tab ──────────────────────────────────── */}
        <Tabs.Content value="mcp" className="space-y-6">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">MCP Servers</h2>
          <div className="flex gap-2">
            <button
              onClick={() => setMcpImportOpen(true)}
              className="px-3 py-1.5 text-sm text-foreground border border-border rounded-lg hover:bg-secondary"
            >
              Import JSON
            </button>
            <button
              onClick={() => reloadMcp.mutate()}
              disabled={reloadMcp.isPending}
              className="px-3 py-1.5 text-sm text-foreground border border-border rounded-lg hover:bg-secondary disabled:opacity-50"
            >
              {reloadMcp.isPending ? "Reloading..." : "Reload"}
            </button>
            <button
              onClick={() => { setMcpEditing(null); setMcpFormOpen(true); }}
              className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500"
            >
              Add Server
            </button>
          </div>
        </CardHeader>
        <CardBody>
          {mcpQ.isLoading ? (
            <Spinner />
          ) : mcpQ.error ? (
            <ErrorBanner message={(mcpQ.error as Error).message} onRetry={() => mcpQ.refetch()} />
          ) : (
            <div className="space-y-2">
              {Object.keys(mcpQ.data ?? {}).length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">No MCP servers configured.</p>
              ) : (
                Object.entries(mcpQ.data ?? {}).map(([name, cfg]) => (
                  <div key={name} className="flex items-center justify-between p-3 rounded-lg border border-border bg-background">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-foreground">{name}</span>
                        {cfg.disabled ? (
                          <Badge className="bg-secondary text-muted-foreground">Disabled</Badge>
                        ) : (
                          <Badge className="bg-green-100 text-green-700">Active</Badge>
                        )}
                        <Badge className="bg-blue-50 text-blue-600">
                          {cfg.url ? "SSE" : "stdio"}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5 font-mono break-all">
                        {cfg.url ?? `${cfg.command ?? ""} ${(cfg.args ?? []).join(" ")}`}
                      </p>
                    </div>
                    <div className="flex gap-2 flex-shrink-0">
                      <button
                        onClick={() => { setMcpEditing({ name, config: cfg }); setMcpFormOpen(true); }}
                        className="text-xs text-primary-600 hover:underline"
                      >Edit</button>
                      <button
                        onClick={() => setMcpDeleting(name)}
                        className="text-xs text-red-600 hover:underline"
                      >Delete</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </CardBody>
      </Card>
        </Tabs.Content>

        {/* ── Agent Memory Tab ──────────────────────────────────── */}
        <Tabs.Content value="memory" className="space-y-6">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">Agent Memory</h2>
          <div className="flex items-center gap-2">
            <select
              value={memAgent}
              onChange={(e) => setMemAgent(e.target.value)}
              className="px-3 py-1.5 text-sm border border-border rounded-lg bg-background text-foreground"
            >
              <option value="">All Agents</option>
              {["detect", "rca", "sre", "executor", "reporter", "scan", "shared"].map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
            <select
              value={memStatus}
              onChange={(e) => setMemStatus(e.target.value)}
              className="px-3 py-1.5 text-sm border border-border rounded-lg bg-background text-foreground"
            >
              <option value="active">Active</option>
              <option value="archived">Archived</option>
              <option value="all">All</option>
            </select>
          </div>
        </CardHeader>
        <CardBody>
          {memQ.isLoading ? (
            <Spinner />
          ) : memQ.error ? (
            <ErrorBanner message={(memQ.error as Error).message} onRetry={() => memQ.refetch()} />
          ) : !memQ.data?.length ? (
            <p className="text-sm text-muted-foreground py-4 text-center">No memories found.</p>
          ) : (
            <div className="space-y-2">
              {memQ.data.map((m) => (
                <div key={`${m.agent}-${m.filename}`} className="flex items-center justify-between p-3 rounded-lg border border-border bg-background">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge className="bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400">{m.agent}</Badge>
                      <span className="text-sm font-medium text-foreground truncate">{m.filename}</span>
                      {m.status === "archived" && (
                        <Badge className="bg-secondary text-muted-foreground">Archived</Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-1 line-clamp-1">{m.summary}</p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-xs text-muted-foreground">
                        Confidence: <strong>{m.confidence}</strong>/5
                      </span>
                      <span className="text-xs text-muted-foreground">Source: {m.source}</span>
                      {m.resource_pattern && (
                        <span className="text-xs text-muted-foreground font-mono">{m.resource_pattern}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                    {/* Confidence editor */}
                    {memEditing?.filename === m.filename && memEditing?.agent === m.agent ? (
                      <div className="flex items-center gap-1">
                        {[1, 2, 3, 4, 5].map((n) => (
                          <button
                            key={n}
                            onClick={() => setMemEditConf(n)}
                            className={`w-6 h-6 rounded text-xs font-bold ${
                              n <= memEditConf
                                ? "bg-primary text-primary-foreground"
                                : "bg-secondary text-muted-foreground"
                            }`}
                          >
                            {n}
                          </button>
                        ))}
                        <button
                          onClick={() => {
                            updateMemMut.mutate(
                              { agent: m.agent, filename: m.filename, data: { confidence: memEditConf } },
                              { onSuccess: () => setMemEditing(null) },
                            );
                          }}
                          disabled={updateMemMut.isPending}
                          className="text-xs text-primary-600 hover:underline ml-1"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setMemEditing(null)}
                          className="text-xs text-muted-foreground hover:underline"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => { setMemEditing(m); setMemEditConf(m.confidence); }}
                        className="text-xs text-primary-600 hover:underline"
                      >
                        Edit
                      </button>
                    )}
                    {m.status === "active" && (
                      <button
                        onClick={() => deleteMemMut.mutate({ agent: m.agent, filename: m.filename })}
                        disabled={deleteMemMut.isPending}
                        className="text-xs text-red-600 hover:underline"
                      >
                        Archive
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
        </Tabs.Content>
      </Tabs.Root>

      {/* MCP Modals */}
      {mcpImportOpen && (
        <McpImportDialog
          importing={importMcp.isPending}
          onClose={() => setMcpImportOpen(false)}
          onImport={async (data) => { await importMcp.mutateAsync(data as { mcpServers: Record<string, McpServerConfig> }); }}
        />
      )}
      {mcpFormOpen && (
        <McpServerFormModal
          initial={mcpEditing}
          saving={upsertMcp.isPending}
          onClose={() => { setMcpFormOpen(false); setMcpEditing(null); }}
          onSave={async (name, config) => {
            await upsertMcp.mutateAsync({ name, config });
            setMcpFormOpen(false);
            setMcpEditing(null);
          }}
        />
      )}
      {mcpDeleting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background rounded-lg shadow-lg w-full max-w-sm p-6">
            <h3 className="text-lg font-semibold text-foreground mb-2">Delete MCP Server</h3>
            <p className="text-sm text-muted-foreground mb-4">
              Are you sure you want to delete <strong>{mcpDeleting}</strong>?
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setMcpDeleting(null)} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">Cancel</button>
              <button
                onClick={async () => { await deleteMcp.mutateAsync(mcpDeleting); setMcpDeleting(null); }}
                disabled={deleteMcp.isPending}
                className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-500 disabled:opacity-50"
              >{deleteMcp.isPending ? "Deleting..." : "Delete"}</button>
            </div>
          </div>
        </div>
      )}

      {/* Modals */}
      {formOpen && (
        <AccountFormModal
          initial={editing}
          saving={createMut.isPending || updateAcctMut.isPending}
          error={acctFormError}
          onClose={() => { setFormOpen(false); setEditing(null); setAcctFormError(null); }}
          onSave={async (data) => {
            setAcctFormError(null);
            try {
              if (editing) {
                await updateAcctMut.mutateAsync({ id: editing.id, data: data as AccountUpdate });
              } else {
                await createMut.mutateAsync(data as AccountCreate);
              }
              setFormOpen(false);
              setEditing(null);
            } catch (err) {
              setAcctFormError(err instanceof Error ? err.message : String(err));
            }
          }}
        />
      )}
      {deleting && (
        <DeleteModal
          account={deleting}
          deleting={deleteMut.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await deleteMut.mutateAsync(deleting.id);
            setDeleting(null);
          }}
        />
      )}
    </div>
  );
}

/* ── SVG Icons (16x16) ────────────────────────────────────────────── */

function IconAll() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  );
}
function IconCompute() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  );
}
function IconNetwork() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9" />
    </svg>
  );
}
function IconDatabase() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
    </svg>
  );
}
function IconStorage() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
    </svg>
  );
}
function IconSecurity() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    </svg>
  );
}
function IconBilling() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}
