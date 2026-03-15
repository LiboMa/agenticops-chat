import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { formatShortDate } from "@/lib/formatDate";
import {
  useAccounts,
  useCreateAccount,
  useUpdateAccount,
  useDeleteAccount,
} from "@/hooks/useAccounts";
import type { Account, AccountCreate, AccountUpdate, CloudProvider } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Provider constants                                                  */
/* ------------------------------------------------------------------ */

const PROVIDER_OPTIONS: { value: CloudProvider; label: string }[] = [
  { value: "aws", label: "AWS" },
  { value: "azure", label: "Azure" },
  { value: "gcp", label: "GCP" },
  { value: "alicloud", label: "Alicloud" },
];

const PROVIDER_BADGE_CLASSES: Record<CloudProvider, string> = {
  aws: "bg-orange-100 text-orange-700",
  azure: "bg-blue-100 text-blue-700",
  gcp: "bg-green-100 text-green-700",
  alicloud: "bg-purple-100 text-purple-700",
};

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

/* ------------------------------------------------------------------ */
/*  Account form modal                                                  */
/* ------------------------------------------------------------------ */

interface FormModalProps {
  initial?: Account | null;
  onClose: () => void;
  onSave: (data: AccountCreate | AccountUpdate) => void;
  saving: boolean;
}

function AccountFormModal({ initial, onClose, onSave, saving }: FormModalProps) {
  const isEdit = !!initial;
  const [provider, setProvider] = useState<CloudProvider>(initial?.provider ?? "aws");
  const [name, setName] = useState(initial?.name ?? "");
  const [regions, setRegions] = useState(initial?.regions?.join(", ") ?? "");
  const [isEnabled, setIsEnabled] = useState(initial?.is_enabled ?? true);
  const [useEnvDefaults, setUseEnvDefaults] = useState(false);
  const [creds, setCreds] = useState<Record<string, string>>({});

  const fields = PROVIDER_FIELDS[provider];

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const regionList = regions
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);

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
      const data: AccountUpdate = {
        name,
        credentials,
        regions: regionList,
        is_enabled: isEnabled,
      };
      onSave(data);
    } else {
      const data: AccountCreate = {
        name,
        provider,
        credentials,
        regions: regionList,
        is_enabled: isEnabled,
      };
      onSave(data);
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
              onChange={(e) => {
                setProvider(e.target.value as CloudProvider);
                setCreds({});
              }}
              disabled={isEdit}
              className={`${inputClass} disabled:bg-secondary`}
            >
              {PROVIDER_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Name</label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. aws-prod, azure-staging"
              className={inputClass}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Regions (comma-separated)
            </label>
            <input
              value={regions}
              onChange={(e) => setRegions(e.target.value)}
              placeholder="us-east-1, us-west-2"
              className={inputClass}
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              id="use-env"
              type="checkbox"
              checked={useEnvDefaults}
              onChange={(e) => setUseEnvDefaults(e.target.checked)}
              className="rounded border-border"
            />
            <label htmlFor="use-env" className="text-sm text-muted-foreground">
              Use environment / CLI defaults (no explicit credentials)
            </label>
          </div>
          {!useEnvDefaults && (
            <div className="space-y-3 border-t border-border pt-3">
              <p className="text-xs text-muted-foreground">
                {provider.toUpperCase()} Credentials — leave blank to use env defaults
              </p>
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
            <input
              id="is-enabled"
              type="checkbox"
              checked={isEnabled}
              onChange={(e) => setIsEnabled(e.target.checked)}
              className="rounded border-border"
            />
            <label htmlFor="is-enabled" className="text-sm text-foreground">
              Enabled
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary"
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
  account,
  onClose,
  onConfirm,
  deleting,
}: {
  account: Account;
  onClose: () => void;
  onConfirm: () => void;
  deleting: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-sm p-6">
        <h3 className="text-lg font-semibold text-foreground mb-2">Delete Account</h3>
        <p className="text-sm text-muted-foreground mb-4">
          Are you sure you want to delete <strong>{account.name}</strong> (
          {account.provider.toUpperCase()})? This action cannot be undone.
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

const columns: Column<Account>[] = [
  {
    key: "name",
    header: "Name",
    sortable: true,
    sortValue: (r) => r.name,
    render: (r) => <span className="font-medium text-foreground">{r.name}</span>,
  },
  {
    key: "provider",
    header: "Provider",
    render: (r) => (
      <Badge className={PROVIDER_BADGE_CLASSES[r.provider]}>
        {r.provider.toUpperCase()}
      </Badge>
    ),
  },
  {
    key: "regions",
    header: "Regions",
    render: (r) => (
      <div className="flex flex-wrap gap-1">
        {r.regions.map((reg) => (
          <Badge key={reg} className="bg-secondary text-muted-foreground">
            {reg}
          </Badge>
        ))}
      </div>
    ),
  },
  {
    key: "is_enabled",
    header: "Status",
    render: (r) =>
      r.is_enabled ? (
        <Badge className="bg-green-100 text-green-700">Enabled</Badge>
      ) : (
        <Badge className="bg-secondary text-muted-foreground">Disabled</Badge>
      ),
  },
  {
    key: "last_scanned_at",
    header: "Last Scanned",
    sortable: true,
    sortValue: (r) => r.last_scanned_at ?? "",
    render: (r) => (
      <span className="text-sm text-muted-foreground">
        {r.last_scanned_at ? formatShortDate(r.last_scanned_at) : "Never"}
      </span>
    ),
  },
];

export default function Accounts() {
  const [filterProvider, setFilterProvider] = useState<string>("");
  const { data: accounts, isLoading, error } = useAccounts(filterProvider || undefined);
  const createMut = useCreateAccount();
  const updateMut = useUpdateAccount();
  const deleteMut = useDeleteAccount();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner message={(error as Error).message} />;

  return (
    <>
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
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
              className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500"
            >
              New Account
            </button>
          </div>
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
          data={accounts ?? []}
          rowKey={(r) => r.id}
          emptyMessage="No accounts configured."
        />
      </Card>

      {formOpen && (
        <AccountFormModal
          initial={editing}
          saving={createMut.isPending || updateMut.isPending}
          onClose={() => {
            setFormOpen(false);
            setEditing(null);
          }}
          onSave={async (data) => {
            if (editing) {
              await updateMut.mutateAsync({ id: editing.id, data: data as AccountUpdate });
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
    </>
  );
}
