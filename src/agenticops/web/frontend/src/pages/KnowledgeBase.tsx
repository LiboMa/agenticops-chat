import { useState } from "react";
import {
  useKBStats,
  useKBSops,
  useKBSop,
  useKBCases,
  useApproveSop,
  useRejectSop,
  useDeprecateSop,
} from "@/hooks/useKnowledgeBase";
import { StatCard } from "@/components/ui/StatCard";
import { Card, CardBody } from "@/components/ui/Card";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";

type Tab = "review" | "active" | "cases";

function QualityBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color =
    pct >= 70 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-2 bg-slate-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500">{pct}%</span>
    </div>
  );
}

function SOPStatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    draft: "bg-slate-100 text-slate-600",
    review: "bg-amber-100 text-amber-700",
    active: "bg-emerald-100 text-emerald-700",
    deprecated: "bg-orange-100 text-orange-700",
    archived: "bg-slate-100 text-slate-400",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${styles[status] || styles.draft}`}
    >
      {status}
    </span>
  );
}

function SOPDetailPanel({
  sopId,
  onClose,
}: {
  sopId: number;
  onClose: () => void;
}) {
  const { data: sop, isLoading } = useKBSop(sopId);
  const approveMut = useApproveSop();
  const rejectMut = useRejectSop();
  const [approverName, setApproverName] = useState("");
  const [showApproveForm, setShowApproveForm] = useState(false);
  const [actionError, setActionError] = useState("");

  if (isLoading) return <Spinner label="Loading SOP..." />;
  if (!sop) return null;

  const canApprove = sop.status === "review" || sop.status === "draft";
  const canReject = sop.status === "review" || sop.status === "draft";
  const contentHtml = sop.content ? renderMarkdown(sop.content) : "";

  const handleApprove = () => {
    if (!approverName.trim()) return;
    setActionError("");
    approveMut.mutate(
      { id: sopId, approved_by: approverName.trim() },
      {
        onSuccess: () => {
          setShowApproveForm(false);
          onClose();
        },
        onError: (err) => setActionError(err.message),
      },
    );
  };

  const handleReject = () => {
    setActionError("");
    rejectMut.mutate(sopId, {
      onSuccess: () => onClose(),
      onError: (err) => setActionError(err.message),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative ml-auto w-full max-w-2xl bg-white shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between z-10">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {sop.filename}
            </h2>
            <div className="flex items-center gap-3 mt-1">
              <SOPStatusBadge status={sop.status} />
              <QualityBar score={sop.quality_score} />
              <SeverityBadge severity={sop.severity as "critical" | "high" | "medium" | "low"} />
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          {/* Metadata */}
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-slate-400 block">Resource Type</span>
              <span className="text-slate-700">{sop.resource_type || "N/A"}</span>
            </div>
            <div>
              <span className="text-slate-400 block">Issue Pattern</span>
              <span className="text-slate-700 truncate block">
                {sop.issue_pattern || "N/A"}
              </span>
            </div>
            {sop.source_issue_id && (
              <div>
                <span className="text-slate-400 block">Source Issue</span>
                <span className="text-slate-700">I#{sop.source_issue_id}</span>
              </div>
            )}
            <div>
              <span className="text-slate-400 block">Created</span>
              <span className="text-slate-700">
                {sop.created_at ? formatShortDate(sop.created_at) : "N/A"}
              </span>
            </div>
            {sop.approved_by && (
              <div>
                <span className="text-slate-400 block">Approved By</span>
                <span className="font-medium text-slate-700">{sop.approved_by}</span>
              </div>
            )}
          </div>

          {/* SOP Content */}
          {contentHtml && (
            <div
              className="prose prose-sm max-w-none text-slate-700 border-t border-slate-100 pt-4"
              dangerouslySetInnerHTML={{ __html: contentHtml }}
            />
          )}

          {actionError && (
            <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">
              {actionError}
            </div>
          )}

          {/* Actions */}
          {(canApprove || canReject) && (
            <div className="border-t border-slate-200 pt-4 space-y-3">
              {showApproveForm ? (
                <div className="flex items-end gap-2">
                  <div className="flex-1">
                    <label className="text-xs text-slate-500 mb-1 block">
                      Your name
                    </label>
                    <input
                      type="text"
                      className="w-full border border-slate-300 rounded-md px-3 py-1.5 text-sm focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none"
                      placeholder="e.g. alice"
                      value={approverName}
                      onChange={(e) => setApproverName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleApprove()}
                    />
                  </div>
                  <button
                    onClick={handleApprove}
                    disabled={!approverName.trim() || approveMut.isPending}
                    className="px-4 py-1.5 text-sm font-medium rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                  >
                    {approveMut.isPending ? "Approving..." : "Confirm"}
                  </button>
                  <button
                    onClick={() => setShowApproveForm(false)}
                    className="px-3 py-1.5 text-sm text-slate-500 hover:text-slate-700"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex gap-2">
                  {canApprove && (
                    <button
                      onClick={() => setShowApproveForm(true)}
                      className="px-4 py-1.5 text-sm font-medium rounded-md bg-emerald-600 text-white hover:bg-emerald-700"
                    >
                      Approve
                    </button>
                  )}
                  {canReject && (
                    <button
                      onClick={handleReject}
                      disabled={rejectMut.isPending}
                      className="px-4 py-1.5 text-sm font-medium rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                    >
                      {rejectMut.isPending ? "Rejecting..." : "Reject"}
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function KnowledgeBase() {
  const [tab, setTab] = useState<Tab>("review");
  const [selectedSopId, setSelectedSopId] = useState<number | null>(null);

  const stats = useKBStats();
  const reviewSops = useKBSops();
  const activeSops = useKBSops("active");
  const cases = useKBCases();
  const deprecateMut = useDeprecateSop();

  if (stats.isLoading) return <Spinner label="Loading knowledge base..." />;
  if (stats.error)
    return (
      <ErrorBanner
        message={stats.error.message}
        onRetry={() => stats.refetch()}
      />
    );

  const s = stats.data!;
  const byStatus = s.sop_by_status || {};

  // Filter review queue: draft + review statuses
  const reviewQueue = (reviewSops.data?.sops || []).filter(
    (sop) => sop.status === "review" || sop.status === "draft",
  );

  const tabDefs: { key: Tab; label: string; count?: number }[] = [
    { key: "review", label: "Review Queue", count: (byStatus.review || 0) + (byStatus.draft || 0) },
    { key: "active", label: "Active SOPs", count: byStatus.active || 0 },
    { key: "cases", label: "All Cases", count: s.case_count },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Knowledge Base</h1>

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard
          label="Review Queue"
          value={(byStatus.review || 0) + (byStatus.draft || 0)}
          colorClass="text-amber-600"
        />
        <StatCard
          label="Active SOPs"
          value={byStatus.active || 0}
          colorClass="text-emerald-600"
        />
        <StatCard
          label="Total Cases"
          value={s.case_count}
          colorClass="text-primary-600"
        />
        <StatCard
          label="Vectors"
          value={s.vector_count}
          colorClass="text-slate-500"
        />
      </div>

      {/* Tab Switcher */}
      <div className="flex gap-1 bg-slate-100 p-1 rounded-lg w-fit">
        {tabDefs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
              tab === t.key
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t.label}
            {t.count !== undefined && (
              <span className="ml-1.5 text-xs text-slate-400">({t.count})</span>
            )}
          </button>
        ))}
      </div>

      {/* Review Queue Tab */}
      {tab === "review" && (
        <Card>
          <CardBody className="p-0">
            {reviewSops.isLoading ? (
              <Spinner />
            ) : reviewQueue.length > 0 ? (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Quality
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Resource Type
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Issue Pattern
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Severity
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Created
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {reviewQueue.map((sop) => (
                    <tr key={sop.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-6 py-3">
                        <QualityBar score={sop.quality_score} />
                      </td>
                      <td className="px-6 py-3">
                        <SOPStatusBadge status={sop.status} />
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-600">
                        {sop.resource_type}
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-600 max-w-xs truncate">
                        {sop.issue_pattern}
                      </td>
                      <td className="px-6 py-3">
                        <SeverityBadge severity={sop.severity as "critical" | "high" | "medium" | "low"} />
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-500">
                        {sop.created_at ? formatShortDate(sop.created_at) : ""}
                      </td>
                      <td className="px-6 py-3 text-right">
                        <button
                          onClick={() => setSelectedSopId(sop.id)}
                          className="px-3 py-1 text-sm font-medium text-primary-600 hover:text-primary-800 hover:bg-primary-50 rounded-md transition-colors"
                        >
                          Review
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-8 text-center text-slate-400 text-sm">
                No SOPs pending review. SOPs are generated when health issues are resolved.
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* Active SOPs Tab */}
      {tab === "active" && (
        <Card>
          <CardBody className="p-0">
            {activeSops.isLoading ? (
              <Spinner />
            ) : activeSops.data && activeSops.data.sops.length > 0 ? (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Filename
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Resource Type
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Severity
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Applied
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Approved By
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Updated
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {activeSops.data.sops.map((sop) => (
                    <tr key={sop.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-6 py-3 text-sm font-mono text-slate-700">
                        <button
                          onClick={() => setSelectedSopId(sop.id)}
                          className="hover:text-primary-600 hover:underline"
                        >
                          {sop.filename}
                        </button>
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-600">
                        {sop.resource_type}
                      </td>
                      <td className="px-6 py-3">
                        <SeverityBadge severity={sop.severity as "critical" | "high" | "medium" | "low"} />
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-600">
                        {sop.application_count}
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-600">
                        {sop.approved_by || "-"}
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-500">
                        {sop.updated_at ? formatShortDate(sop.updated_at) : ""}
                      </td>
                      <td className="px-6 py-3 text-right">
                        <button
                          onClick={() => deprecateMut.mutate(sop.id)}
                          disabled={deprecateMut.isPending}
                          className="px-3 py-1 text-sm font-medium text-orange-600 hover:text-orange-800 hover:bg-orange-50 rounded-md transition-colors disabled:opacity-50"
                        >
                          Deprecate
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-8 text-center text-slate-400 text-sm">
                No active SOPs. Approve SOPs from the Review Queue to activate them.
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* Cases Tab */}
      {tab === "cases" && (
        <Card>
          <CardBody className="p-0">
            {cases.isLoading ? (
              <Spinner />
            ) : cases.data && cases.data.cases.length > 0 ? (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Case ID
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Resource Type
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Severity
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Created
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Preview
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {cases.data.cases.map((c, idx) => (
                    <tr key={idx} className="hover:bg-slate-50 transition-colors">
                      <td className="px-6 py-3 text-sm font-mono text-slate-600">
                        {c.case_id}
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-600">
                        {c.resource_type}
                      </td>
                      <td className="px-6 py-3">
                        <SeverityBadge severity={c.severity as "critical" | "high" | "medium" | "low"} />
                      </td>
                      <td className="px-6 py-3">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            c.status === "resolved"
                              ? "bg-green-100 text-green-700"
                              : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {c.status}
                        </span>
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-500">
                        {formatShortDate(c.created_at)}
                      </td>
                      <td className="px-6 py-3 text-sm text-slate-500 max-w-xs truncate">
                        {c.preview && c.preview.length > 80
                          ? c.preview.slice(0, 80) + "..."
                          : c.preview}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-8 text-center text-slate-400 text-sm">
                No cases found. Resolve health issues to populate the knowledge base.
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* SOP Detail Slide-over */}
      {selectedSopId !== null && (
        <SOPDetailPanel
          sopId={selectedSopId}
          onClose={() => setSelectedSopId(null)}
        />
      )}
    </div>
  );
}
