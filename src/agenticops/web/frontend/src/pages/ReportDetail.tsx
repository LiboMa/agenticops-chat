import { useParams, Link } from "react-router-dom";
import { useReport } from "@/hooks/useReport";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";

const TYPE_COLORS: Record<string, string> = {
  daily: "bg-blue-100 text-blue-800",
  incident: "bg-red-100 text-red-800",
  inventory: "bg-emerald-100 text-emerald-800",
  weekly: "bg-purple-100 text-purple-800",
};

export default function ReportDetail() {
  const { id } = useParams<{ id: string }>();
  const reportId = Number(id);
  const { data: report, isLoading, error, refetch } = useReport(reportId);

  if (isLoading) return <Spinner label="Loading report..." />;
  if (error)
    return <ErrorBanner message={error.message} onRetry={() => refetch()} />;
  if (!report) return null;

  const html = renderMarkdown(report.content_markdown || report.summary);

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Back link */}
      <Link
        to="/app/reports"
        className="inline-flex items-center text-sm text-gray-500 hover:text-gray-700 transition-colors"
      >
        <svg
          className="h-4 w-4 mr-1"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 19l-7-7 7-7"
          />
        </svg>
        Back to Reports
      </Link>

      {/* Report Header */}
      <Card>
        <CardBody>
          <div className="flex items-start gap-3 mb-4">
            <Badge
              className={
                TYPE_COLORS[report.report_type] ?? "bg-gray-200 text-gray-700"
              }
            >
              {report.report_type}
            </Badge>
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl font-bold text-gray-900 leading-tight">
                {report.title}
              </h1>
              <p className="mt-1 text-sm text-gray-500">
                Generated {formatFullDate(report.created_at)}
              </p>
            </div>
          </div>

          {/* Summary callout */}
          <div className="rounded-lg bg-gray-50 border border-gray-200 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
              Summary
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">
              {report.summary}
            </p>
          </div>
        </CardBody>
      </Card>

      {/* Report Body — rendered markdown */}
      <Card>
        <CardBody>
          <div
            className="report-content"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        </CardBody>
      </Card>
    </div>
  );
}
