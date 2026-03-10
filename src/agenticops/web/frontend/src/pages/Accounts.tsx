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
import type { Account, AccountCreate, AccountUpdate } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Account form modal                                                 */
/* ------------------------------------------------------------------ */

interface FormModalProps {
  initial?: Account | null;
  onClose: () => void;
  onSave: (data: AccountCreate | AccountUpdate) => void;
  saving: boolean;
}

function AccountFormModal({ initial, onClose, onSave, saving }: FormModalProps) {
  const isEdit = !!initial;
  const [name, setName] = useState(initial?.name ?? "");
  const [accountId, setAccountId] = useState(initial?.account_id ?? "");
  const [roleArn, setRoleArn] = useState(initial?.role_arn ?? "");
  const [externalId, setExternalId] = useState(initial?.external_id ?? "");
  const [regions, setRegions] = useState(initial?.regions?.join(", ") ?? "");
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const regionList = regions
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);

    if (isEdit) {
      const data: AccountUpdate = {
        name,
        role_arn: roleArn,
        external_id: externalId || undefined,
        regions: regionList.length ? regionList : undefined,
        is_active: isActive,
      };
      onSave(data);
    } else {
      const data: AccountCreate = {
        name,
        account_id: accountId,
        role_arn: roleArn,
        external_id: externalId || undefined,
        regions: regionList.length ? regionList : undefined,
        is_active: isActive,
      };
      onSave(data);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-[#2f2f2f] rounded-lg  w-full max-w-md p-6">
        <h3 className="text-lg font-semibold text-[#ececec] mb-4">
          {isEdit ? "Edit Account" : "New Account"}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-[#ececec] mb-1">Name</label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border border-[#424242] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[#ececec] mb-1">Account ID</label>
            <input
              required
              disabled={isEdit}
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              className="w-full px-3 py-2 border border-[#424242] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-[#383838]"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[#ececec] mb-1">Role ARN</label>
            <input
              required
              value={roleArn}
              onChange={(e) => setRoleArn(e.target.value)}
              className="w-full px-3 py-2 border border-[#424242] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[#ececec] mb-1">
              External ID (optional)
            </label>
            <input
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
              className="w-full px-3 py-2 border border-[#424242] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[#ececec] mb-1">
              Regions (comma-separated)
            </label>
            <input
              value={regions}
              onChange={(e) => setRegions(e.target.value)}
              placeholder="us-east-1, us-west-2"
              className="w-full px-3 py-2 border border-[#424242] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              id="is-active"
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="rounded border-[#424242]"
            />
            <label htmlFor="is-active" className="text-sm text-[#ececec]">
              Active
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-[#ececec] border border-[#424242] rounded-lg hover:bg-[#383838]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-500 disabled:opacity-50"
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
      <div className="bg-[#2f2f2f] rounded-lg  w-full max-w-sm p-6">
        <h3 className="text-lg font-semibold text-[#ececec] mb-2">Delete Account</h3>
        <p className="text-sm text-[#9b9b9b] mb-4">
          Are you sure you want to delete <strong>{account.name}</strong> (
          {account.account_id})? This action cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-[#ececec] border border-[#424242] rounded-lg hover:bg-[#383838]"
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
    render: (r) => <span className="font-medium text-[#ececec]">{r.name}</span>,
  },
  {
    key: "account_id",
    header: "Account ID",
    render: (r) => <span className="font-mono text-sm">{r.account_id}</span>,
  },
  {
    key: "role_arn",
    header: "Role ARN",
    render: (r) => (
      <span className="font-mono text-xs text-[#9b9b9b] truncate max-w-[200px] block">
        {r.role_arn}
      </span>
    ),
  },
  {
    key: "regions",
    header: "Regions",
    render: (r) => (
      <div className="flex flex-wrap gap-1">
        {r.regions.map((reg) => (
          <Badge key={reg} className="bg-[#383838] text-[#9b9b9b]">
            {reg}
          </Badge>
        ))}
      </div>
    ),
  },
  {
    key: "is_active",
    header: "Status",
    render: (r) =>
      r.is_active ? (
        <Badge className="bg-green-100 text-green-700">Active</Badge>
      ) : (
        <Badge className="bg-[#383838] text-[#9b9b9b]">Inactive</Badge>
      ),
  },
  {
    key: "last_scanned_at",
    header: "Last Scanned",
    sortable: true,
    sortValue: (r) => r.last_scanned_at ?? "",
    render: (r) => (
      <span className="text-sm text-[#9b9b9b]">
        {r.last_scanned_at ? formatShortDate(r.last_scanned_at) : "Never"}
      </span>
    ),
  },
];

export default function Accounts() {
  const { data: accounts, isLoading, error } = useAccounts();
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
          <h2 className="text-lg font-semibold text-[#ececec]">AWS Accounts</h2>
          <button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
            className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-500"
          >
            New Account
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
                    className="text-xs text-blue-400 hover:underline"
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
