import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useFixPlans } from "@/hooks/useFixPlans";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import type { FixPlan, RiskLevel, FixPlanStatus } from "@/api/types";

const RISK_OPTIONS: RiskLevel[] = ["L0", "L1", "L2", "L3"];
const STATUS_OPTIONS: FixPlanStatus[] = [
  "draft",
  "pending_approval",
  "approved",
  "executing",
  "executed",
  "failed",
  "rejected",
];

const columns: Column<FixPlan>[] = [
  {
    key: "risk_level",
    header: "Risk",
    render: (r) => <RiskLevelBadge level={r.risk_level} />,
    className: "w-20",
  },
  {
    key: "title",
    header: "Title",
    render: (r) => (
      <span className="text-sm font-medium text-slate-900">{r.title}</span>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: (r) => <FixPlanStatusBadge status={r.status} />,
  },
  {
    key: "health_issue_id",
    header: "Issue #",
    render: (r) => (
      <span className="text-sm text-slate-500 font-mono">
        #{r.health_issue_id}
      </span>
    ),
  },
  {
    key: "approved_by",
    header: "Approved By",
    render: (r) => (
      <span className="text-sm text-slate-500">{r.approved_by ?? "-"}</span>
    ),
  },
  {
    key: "created_at",
    header: "Created",
    sortable: true,
    sortValue: (r) => new Date(r.created_at).getTime(),
    render: (r) => (
      <span className="text-sm text-slate-500">
        {formatShortDate(r.created_at)}
      </span>
    ),
  },
];

export default function FixPlans() {
  const [statusFilter, setStatusFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const navigate = useNavigate();

  const filters = useMemo(
    () => ({
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(riskFilter ? { risk_level: riskFilter } : {}),
    }),
    [statusFilter, riskFilter],
  );

  const { data, isLoading, error, refetch } = useFixPlans(filters);

  if (isLoading) return <Spinner label="Loading fix plans..." />;
  if (error)
    return <ErrorBanner message={error.message} onRetry={() => refetch()} />;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-slate-900">Fix Plans</h2>
          <div className="flex items-center gap-3">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="">All Statuses</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, " ")}
                </option>
              ))}
            </select>
            <select
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="">All Risk Levels</option>
              {RISK_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <span className="text-sm text-slate-400">
              {data?.length ?? 0} plans
            </span>
          </div>
        </CardHeader>
        <CardBody className="p-0">
          <DataTable
            columns={columns}
            data={data ?? []}
            rowKey={(r) => r.id}
            onRowClick={(r) => navigate(`/app/fix-plans/${r.id}`)}
            emptyMessage="No fix plans found."
          />
        </CardBody>
      </Card>
    </div>
  );
}
