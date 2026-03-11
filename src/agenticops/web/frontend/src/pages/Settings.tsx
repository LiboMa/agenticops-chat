import { useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { formatShortDate } from "@/lib/formatDate";
import { useScanFocus } from "@/hooks/useScanFocus";
import { useSettings, useUpdateSettings } from "@/hooks/useSettings";
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
} from "@/hooks/useMcpServers";
import type { ScanFocus } from "@/api/types";
import type { Account, AccountCreate, AccountUpdate, McpServerConfig } from "@/api/types";

/* ── Scan Focus section ─────────────────────────────────────────── */

const FOCUS_META: Record<ScanFocus, { label: string; services: string; icon: JSX.Element }> = {
  all:        { label: "All",       services: "All categories",                     icon: <IconAll /> },
  computing:  { label: "Compute",   services: "EC2, Lambda, ECS, EKS, AutoScaling", icon: <IconCompute /> },
  networking: { label: "Network",   services: "VPC, SG, ELB, CloudFront, Route53",  icon: <IconNetwork /> },
  databases:  { label: "Database",  services: "RDS, DynamoDB, ElastiCache",          icon: <IconDatabase /> },
  storage:    { label: "Storage",   services: "S3, EBS, EFS, Backup",                icon: <IconStorage /> },
  security:   { label: "Security",  services: "IAM, GuardDuty, WAF, KMS",            icon: <IconSecurity /> },
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
          : "bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50"
      }`}
    >
      <div className={`mt-0.5 flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
        active ? "bg-primary-100 text-primary-600" : "bg-slate-100 text-slate-400 group-hover:text-slate-500"
      }`}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${active ? "text-primary-700" : "text-slate-700"}`}>
            {label}
          </span>
          <div className={`w-7 h-4 rounded-full transition-colors flex items-center ${
            active ? "bg-primary-500 justify-end" : "bg-slate-300 justify-start"
          }`}>
            <div className="w-3 h-3 mx-0.5 rounded-full bg-white shadow-sm" />
          </div>
        </div>
        <p className="text-xs text-slate-400 mt-0.5 leading-tight">{description}</p>
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
    <div className="flex items-center justify-between py-3 border-b border-slate-100 last:border-b-0">
      <div>
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <p className="text-xs text-slate-400 mt-0.5">{description}</p>
      </div>
      <button
        onClick={() => onChange(!enabled)}
        disabled={saving}
        className={`relative w-10 h-5 rounded-full transition-colors ${
          enabled ? "bg-primary-500" : "bg-slate-300"
        } ${saving ? "opacity-50 cursor-not-allowed" : ""}`}
      >
        <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
          enabled ? "translate-x-5" : "translate-x-0.5"
        }`} />
      </button>
    </div>
  );
}

/* ── Account form modal (reused from Accounts page) ─────────────── */

function AccountFormModal({
  initial, onClose, onSave, saving,
}: {
  initial?: Account | null; onClose: () => void;
  onSave: (data: AccountCreate | AccountUpdate) => void; saving: boolean;
}) {
  const isEdit = !!initial;
  const [name, setName] = useState(initial?.name ?? "");
  const [accountId, setAccountId] = useState(initial?.account_id ?? "");
  const [roleArn, setRoleArn] = useState(initial?.role_arn ?? "");
  const [externalId, setExternalId] = useState(initial?.external_id ?? "");
  const [regions, setRegions] = useState(initial?.regions?.join(", ") ?? "");
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const regionList = regions.split(",").map((r) => r.trim()).filter(Boolean);
    if (isEdit) {
      onSave({ name, role_arn: roleArn, external_id: externalId || undefined, regions: regionList.length ? regionList : undefined, is_active: isActive } as AccountUpdate);
    } else {
      onSave({ name, account_id: accountId, role_arn: roleArn, external_id: externalId || undefined, regions: regionList.length ? regionList : undefined, is_active: isActive } as AccountCreate);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-lg w-full max-w-md p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-4">
          {isEdit ? "Edit Account" : "New Account"}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Name</label>
            <input required value={name} onChange={(e) => setName(e.target.value)} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Account ID</label>
            <input required disabled={isEdit} value={accountId} onChange={(e) => setAccountId(e.target.value)} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Role ARN</label>
            <input required value={roleArn} onChange={(e) => setRoleArn(e.target.value)} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">External ID (optional)</label>
            <input value={externalId} onChange={(e) => setExternalId(e.target.value)} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Regions (comma-separated)</label>
            <input value={regions} onChange={(e) => setRegions(e.target.value)} placeholder="us-east-1, us-west-2" className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div className="flex items-center gap-2">
            <input id="is-active" type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="rounded border-slate-200" />
            <label htmlFor="is-active" className="text-sm text-slate-700">Active</label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
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
      <div className="bg-white rounded-lg shadow-lg w-full max-w-sm p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-2">Delete Account</h3>
        <p className="text-sm text-slate-600 mb-4">
          Are you sure you want to delete <strong>{account.name}</strong> ({account.account_id})? This action cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
          <button onClick={onConfirm} disabled={deleting} className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-500 disabled:opacity-50">{deleting ? "Deleting..." : "Delete"}</button>
        </div>
      </div>
    </div>
  );
}

/* ── Accounts columns ───────────────────────────────────────────── */

const accountColumns: Column<Account>[] = [
  { key: "name", header: "Name", sortable: true, sortValue: (r) => r.name, render: (r) => <span className="font-medium text-slate-900">{r.name}</span> },
  { key: "account_id", header: "Account ID", render: (r) => <span className="font-mono text-sm">{r.account_id}</span> },
  { key: "role_arn", header: "Role ARN", render: (r) => <span className="font-mono text-xs text-slate-500 truncate max-w-[200px] block">{r.role_arn}</span> },
  { key: "regions", header: "Regions", render: (r) => <div className="flex flex-wrap gap-1">{r.regions.map((reg) => <Badge key={reg} className="bg-slate-100 text-slate-600">{reg}</Badge>)}</div> },
  { key: "is_active", header: "Status", render: (r) => r.is_active ? <Badge className="bg-green-100 text-green-700">Active</Badge> : <Badge className="bg-slate-100 text-slate-500">Inactive</Badge> },
  { key: "last_scanned_at", header: "Last Scanned", sortable: true, sortValue: (r) => r.last_scanned_at ?? "", render: (r) => <span className="text-sm text-slate-500">{r.last_scanned_at ? formatShortDate(r.last_scanned_at) : "Never"}</span> },
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
      <div className="bg-white rounded-lg shadow-lg w-full max-w-md p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-4">
          {isEdit ? "Edit MCP Server" : "New MCP Server"}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Server Name</label>
            <input required disabled={isEdit} value={name} onChange={(e) => setName(e.target.value)} placeholder="awslabs.aws-documentation-mcp-server" className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 font-mono" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Command</label>
            <input required value={command} onChange={(e) => setCommand(e.target.value)} placeholder="uvx" className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Args (space-separated)</label>
            <input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="awslabs.aws-documentation-mcp-server@latest" className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Environment (KEY=VALUE per line)</label>
            <textarea rows={3} value={envText} onChange={(e) => setEnvText(e.target.value)} placeholder={"FASTMCP_LOG_LEVEL=ERROR\nAWS_DOCUMENTATION_PARTITION=aws"} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
          <div className="flex items-center gap-2">
            <input id="mcp-disabled" type="checkbox" checked={disabled} onChange={(e) => setDisabled(e.target.checked)} className="rounded border-slate-200" />
            <label htmlFor="mcp-disabled" className="text-sm text-slate-700">Disabled</label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50">{saving ? "Saving..." : "Save"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ── Main Settings page ─────────────────────────────────────────── */

export default function Settings() {
  const { selected: focusSelected, toggle: toggleFocus, focusValue, ALL_CATEGORIES } = useScanFocus();
  const settingsQ = useSettings();
  const updateMut = useUpdateSettings();

  // Accounts
  const { data: accounts, isLoading: acctLoading, error: acctError } = useAccounts();
  const createMut = useCreateAccount();
  const updateAcctMut = useUpdateAccount();
  const deleteMut = useDeleteAccount();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);

  // MCP Servers
  const mcpQ = useMcpServers();
  const upsertMcp = useUpsertMcpServer();
  const deleteMcp = useDeleteMcpServer();
  const reloadMcp = useReloadMcpServers();
  const [mcpFormOpen, setMcpFormOpen] = useState(false);
  const [mcpEditing, setMcpEditing] = useState<{ name: string; config: McpServerConfig } | null>(null);
  const [mcpDeleting, setMcpDeleting] = useState<string | null>(null);

  const s = settingsQ.data;

  function patchSetting(key: string, value: boolean) {
    updateMut.mutate({ [key]: value });
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>

      {/* ── Scan Focus ────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-slate-900">Scan Focus</h2>
          <span className="text-xs text-slate-400">
            {focusValue === "all" ? "All categories" : focusValue.split(",").join(", ")}
          </span>
        </CardHeader>
        <CardBody>
          <p className="text-sm text-slate-500 mb-4">
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
          <h2 className="text-lg font-semibold text-slate-900">Pipeline & Automation</h2>
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
            </div>
          ) : null}
        </CardBody>
      </Card>

      {/* ── Accounts ──────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-slate-900">AWS Accounts</h2>
          <button
            onClick={() => { setEditing(null); setFormOpen(true); }}
            className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500"
          >
            New Account
          </button>
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

      {/* ── MCP Servers ─────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-slate-900">MCP Servers</h2>
          <div className="flex gap-2">
            <button
              onClick={() => reloadMcp.mutate()}
              disabled={reloadMcp.isPending}
              className="px-3 py-1.5 text-sm text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50"
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
                <p className="text-sm text-slate-400 py-4 text-center">No MCP servers configured.</p>
              ) : (
                Object.entries(mcpQ.data ?? {}).map(([name, cfg]) => (
                  <div key={name} className="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-white">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-slate-900">{name}</span>
                        {cfg.disabled ? (
                          <Badge className="bg-slate-100 text-slate-500">Disabled</Badge>
                        ) : (
                          <Badge className="bg-green-100 text-green-700">Active</Badge>
                        )}
                        <Badge className="bg-blue-50 text-blue-600">
                          {cfg.url ? "SSE" : "stdio"}
                        </Badge>
                      </div>
                      <p className="text-xs text-slate-400 mt-0.5 font-mono truncate max-w-[400px]">
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

      {/* MCP Modals */}
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
          <div className="bg-white rounded-lg shadow-lg w-full max-w-sm p-6">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">Delete MCP Server</h3>
            <p className="text-sm text-slate-600 mb-4">
              Are you sure you want to delete <strong>{mcpDeleting}</strong>?
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setMcpDeleting(null)} className="px-4 py-2 text-sm text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
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
          onClose={() => { setFormOpen(false); setEditing(null); }}
          onSave={async (data) => {
            if (editing) {
              await updateAcctMut.mutateAsync({ id: editing.id, data: data as AccountUpdate });
            } else {
              await createMut.mutateAsync(data as AccountCreate);
            }
            setFormOpen(false);
            setEditing(null);
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
