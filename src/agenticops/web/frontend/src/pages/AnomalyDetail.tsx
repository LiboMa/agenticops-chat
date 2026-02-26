import { useParams, Link } from "react-router-dom";
import { useAnomaly } from "@/hooks/useAnomaly";
import { useAnomalyRca } from "@/hooks/useAnomalyRca";
import { useFixPlans } from "@/hooks/useFixPlans";
import { Card, CardBody } from "@/components/ui/Card";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";

export default function AnomalyDetail() {
  const { id } = useParams<{ id: string }>();
  const anomalyId = Number(id);

  const anomaly = useAnomaly(anomalyId);
  const rca = useAnomalyRca(anomalyId);
  const fixPlans = useFixPlans({ health_issue_id: anomalyId });

  if (anomaly.isLoading) return <Spinner label="Loading anomaly..." />;
  if (anomaly.error)
    return (
      <ErrorBanner
        message={anomaly.error.message}
        onRetry={() => anomaly.refetch()}
      />
    );

  const a = anomaly.data!;

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        to="/app/anomalies"
        className="inline-flex items-center text-sm text-slate-500 hover:text-slate-700 transition-colors"
      >
        <svg className="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Back to Anomalies
      </Link>

      {/* Anomaly Header */}
      <Card>
        <CardBody>
          <div className="flex items-center gap-3 mb-4">
            <SeverityBadge severity={a.severity} />
            <h1 className="text-2xl font-semibold text-slate-900">{a.title}</h1>
          </div>
          <div
            className="text-slate-600 mb-6 report-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(a.description) }}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-slate-400 block">Resource</span>
              <span className="font-mono text-slate-700">{a.resource_id}</span>
            </div>
            <div>
              <span className="text-slate-400 block">Type</span>
              <span className="text-slate-700">{a.resource_type}</span>
            </div>
            <div>
              <span className="text-slate-400 block">Region</span>
              <span className="text-slate-700">{a.region}</span>
            </div>
            <div>
              <span className="text-slate-400 block">Status</span>
              <span
                className={
                  a.status === "open"
                    ? "text-red-600 font-medium"
                    : a.status === "acknowledged"
                      ? "text-amber-600 font-medium"
                      : "text-green-600 font-medium"
                }
              >
                {a.status}
              </span>
            </div>
          </div>

          {a.metric_name && (
            <div className="mt-6 p-4 bg-slate-50 rounded-lg border border-slate-100">
              <h3 className="font-semibold text-slate-900 mb-2">
                Metric Details
              </h3>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-slate-400">Metric:</span>{" "}
                  <span className="text-slate-700">{a.metric_name}</span>
                </div>
                <div>
                  <span className="text-slate-400">Expected:</span>{" "}
                  <span className="text-slate-700">{a.expected_value}</span>
                </div>
                <div>
                  <span className="text-slate-400">Actual:</span>{" "}
                  <span className="text-slate-700">{a.actual_value}</span>
                </div>
              </div>
            </div>
          )}

          <div className="mt-4 text-xs text-slate-400">
            Detected {formatFullDate(a.detected_at)}
            {a.resolved_at && ` | Resolved ${formatFullDate(a.resolved_at)}`}
          </div>
        </CardBody>
      </Card>

      {/* RCA Section */}
      {rca.isLoading ? (
        <Spinner label="Loading RCA..." />
      ) : rca.data ? (
        <Card>
          <CardBody>
            <h2 className="text-xl font-semibold text-slate-900 mb-4">
              Root Cause Analysis
            </h2>

            {/* Confidence bar */}
            <div className="mb-6">
              <div className="flex justify-between text-sm mb-1">
                <span className="text-slate-500">Confidence</span>
                <span className="font-medium text-slate-700">
                  {Math.round(rca.data.confidence_score * 100)}%
                </span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-2">
                <div
                  className="bg-primary-500 h-2 rounded-full transition-all"
                  style={{ width: `${rca.data.confidence_score * 100}%` }}
                />
              </div>
            </div>

            {/* Root Cause */}
            <div className="mb-6">
              <h3 className="font-semibold text-slate-900 mb-2">Root Cause</h3>
              <div
                className="text-slate-700 report-content"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(rca.data.root_cause) }}
              />
            </div>

            {/* Contributing Factors */}
            {rca.data.contributing_factors.length > 0 && (
              <div className="mb-6">
                <h3 className="font-semibold text-slate-900 mb-2">
                  Contributing Factors
                </h3>
                <ul className="list-disc list-inside text-slate-600 space-y-1">
                  {rca.data.contributing_factors.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recommendations */}
            {rca.data.recommendations.length > 0 && (
              <div>
                <h3 className="font-semibold text-slate-900 mb-2">
                  Recommendations
                </h3>
                <ol className="list-decimal list-inside text-slate-600 space-y-1">
                  {rca.data.recommendations.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ol>
              </div>
            )}

            <div className="mt-4 text-xs text-slate-400">
              Model: {rca.data.llm_model} | Analyzed{" "}
              {formatFullDate(rca.data.created_at)}
            </div>
          </CardBody>
        </Card>
      ) : null}

      {/* Fix Plans Section */}
      {fixPlans.data && fixPlans.data.length > 0 && (
        <Card>
          <CardBody>
            <h2 className="text-xl font-semibold text-slate-900 mb-4">
              Fix Plans
            </h2>
            <div className="space-y-3">
              {fixPlans.data.map((fp) => (
                <Link
                  key={fp.id}
                  to={`/app/fix-plans/${fp.id}`}
                  className="flex items-center justify-between p-3 rounded-lg border border-slate-200 hover:border-primary-300 hover:bg-slate-50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <RiskLevelBadge level={fp.risk_level} />
                    <span className="text-sm font-medium text-slate-900">
                      {fp.title}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <FixPlanStatusBadge status={fp.status} />
                    <svg
                      className="w-4 h-4 text-slate-400"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 5l7 7-7 7"
                      />
                    </svg>
                  </div>
                </Link>
              ))}
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
