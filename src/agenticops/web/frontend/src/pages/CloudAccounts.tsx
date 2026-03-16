import { useState, useEffect } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { formatShortDate } from "@/lib/formatDate";
import type { CloudAccount } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Provider badge colors                                              */
/* ------------------------------------------------------------------ */

const PROVIDER_COLORS: Record<string, string> = {
  aws: "bg-orange-500/20 text-orange-300",
  azure: "bg-blue-500/20 text-blue-300",
  gcp: "bg-red-500/20 text-red-300",
  alicloud: "bg-yellow-500/20 text-yellow-300",
};

function ProviderBadge({ provider }: { provider: string }) {
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${
        PROVIDER_COLORS[provider] ?? "bg-gray-500/20 text-gray-300"
      }`}
    >
      {provider.toUpperCase()}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Cloud Accounts page                                                */
/* ------------------------------------------------------------------ */

export default function CloudAccounts() {
  const [accounts, setAccounts] = useState<CloudAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/cloud/accounts")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setAccounts)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const columns: Column<CloudAccount>[] = [
    {
      key: "name",
      header: "Name",
      render: (row) => (
        <span className="font-medium text-white">{row.name}</span>
      ),
    },
    {
      key: "provider",
      header: "Provider",
      render: (row) => <ProviderBadge provider={row.provider} />,
    },
    {
      key: "is_enabled",
      header: "Status",
      render: (row) => (
        <Badge variant={row.is_enabled ? "success" : "secondary"}>
          {row.is_enabled ? "Enabled" : "Disabled"}
        </Badge>
      ),
    },
    {
      key: "has_credentials",
      header: "Credentials",
      render: (row) => (
        <Badge variant={row.has_credentials ? "success" : "warning"}>
          {row.has_credentials ? "Configured" : "Missing"}
        </Badge>
      ),
    },
    {
      key: "regions",
      header: "Regions",
      render: (row) => (
        <span className="text-gray-400 text-sm">
          {row.regions?.length ? row.regions.join(", ") : "—"}
        </span>
      ),
    },
    {
      key: "last_scanned_at",
      header: "Last Scan",
      render: (row) => (
        <span className="text-gray-400 text-sm">
          {row.last_scanned_at ? formatShortDate(row.last_scanned_at) : "Never"}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Cloud Accounts</h1>
        <span className="text-sm text-gray-400">
          {accounts.length} account{accounts.length !== 1 ? "s" : ""}
        </span>
      </div>

      {error && <ErrorBanner message={error} />}

      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-white">
            Multi-Cloud Accounts
          </h2>
          <p className="text-sm text-gray-400">
            Manage AWS, Azure, GCP, and Alicloud accounts. Credentials are
            encrypted at rest and never exposed in the UI.
          </p>
        </CardHeader>
        {loading ? (
          <div className="flex justify-center p-8">
            <Spinner />
          </div>
        ) : (
          <DataTable columns={columns} data={accounts} emptyMessage="No cloud accounts configured" />
        )}
      </Card>
    </div>
  );
}
