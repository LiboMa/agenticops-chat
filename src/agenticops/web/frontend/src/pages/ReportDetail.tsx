import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useReport } from "@/hooks/useReport";
import {
  useNotificationChannels,
  usePublishReport,
} from "@/hooks/useNotifications";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import ShareDialog from "@/components/ShareDialog";
import type { ReportPublishResponse } from "@/api/types";

const TYPE_COLORS: Record<string, string> = {
  daily: "bg-blue-100 text-blue-700",
  incident: "bg-red-100 text-red-700",
  inventory: "bg-emerald-100 text-emerald-700",
  weekly: "bg-purple-100 text-purple-700",
  newsletter: "bg-amber-100 text-amber-700",
};

const AVAILABLE_FORMATS = ["html", "pdf", "docx", "markdown"] as const;

export default function ReportDetail() {
  const { id } = useParams<{ id: string }>();
  const reportId = Number(id);
  const { data: report, isLoading, error, refetch } = useReport(reportId);

  // Publish state
  const [showPublish, setShowPublish] = useState(false);
  const [selectedChannel, setSelectedChannel] = useState("");
  const [selectedFormats, setSelectedFormats] = useState<string[]>(["html", "markdown"]);
  const [publishResult, setPublishResult] = useState<ReportPublishResponse | null>(null);

  const { data: channels } = useNotificationChannels();
  const publishMutation = usePublishReport(reportId);

  const [showShare, setShowShare] = useState(false);

  const publishableChannels = (channels ?? []).filter(
    (c) => (c.channel_type === "sns-report" || c.channel_type === "ses") && c.is_enabled,
  );

  const handlePublish = () => {
    if (!selectedChannel) return;
    publishMutation.mutate(
      {
        channel_name: selectedChannel,
        formats: selectedFormats.length > 0 ? selectedFormats : undefined,
      },
      {
        onSuccess: (data) => setPublishResult(data),
      },
    );
  };

  const toggleFormat = (fmt: string) => {
    setSelectedFormats((prev) =>
      prev.includes(fmt) ? prev.filter((f) => f !== fmt) : [...prev, fmt],
    );
  };

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
        className="inline-flex items-center text-sm text-slate-500 hover:text-slate-700 transition-colors"
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
                TYPE_COLORS[report.report_type] ?? "bg-slate-100 text-slate-600"
              }
            >
              {report.report_type}
            </Badge>
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl font-semibold text-slate-900 leading-tight">
                {report.title}
              </h1>
              <p className="mt-1 text-sm text-slate-500">
                Generated {formatFullDate(report.created_at)}
              </p>
            </div>

            {/* Publish + Share buttons */}
            <div className="flex items-center gap-2">
              {publishableChannels.length > 0 && (
                <button
                  onClick={() => setShowPublish(!showPublish)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                  </svg>
                  Publish
                </button>
              )}
              <button
                onClick={() => setShowShare(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
                </svg>
                Share
              </button>
            </div>
          </div>

          {/* Summary callout */}
          <div className="rounded-lg bg-slate-50 border border-slate-200 p-4">
            <h3 className="text-xs font-medium uppercase tracking-wider text-slate-400 mb-2">
              Summary
            </h3>
            <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-line">
              {report.summary}
            </p>
          </div>
        </CardBody>
      </Card>

      {/* Publish Panel */}
      {showPublish && (
        <Card>
          <CardBody>
            <h3 className="text-sm font-semibold text-slate-900 mb-3">
              Publish to Channel
            </h3>

            <div className="space-y-4">
              {/* Channel select */}
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">
                  Channel
                </label>
                <select
                  value={selectedChannel}
                  onChange={(e) => setSelectedChannel(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                >
                  <option value="">Select a channel...</option>
                  {publishableChannels.map((ch) => (
                    <option key={ch.name} value={ch.name}>
                      {ch.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Format checkboxes */}
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">
                  Formats
                </label>
                <div className="flex gap-3">
                  {AVAILABLE_FORMATS.map((fmt) => (
                    <label key={fmt} className="flex items-center gap-1.5 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={selectedFormats.includes(fmt)}
                        onChange={() => toggleFormat(fmt)}
                        className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                      />
                      {fmt.toUpperCase()}
                    </label>
                  ))}
                </div>
              </div>

              {/* Publish action */}
              <div className="flex items-center gap-3">
                <button
                  onClick={handlePublish}
                  disabled={!selectedChannel || publishMutation.isPending}
                  className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
                >
                  {publishMutation.isPending ? "Publishing..." : "Publish Report"}
                </button>
                {publishMutation.isError && (
                  <span className="text-sm text-red-600">
                    {(publishMutation.error as Error).message}
                  </span>
                )}
              </div>

              {/* Result */}
              {publishResult && (
                <div className="rounded-lg bg-green-50 border border-green-200 p-4">
                  <h4 className="text-sm font-medium text-green-800 mb-2">
                    Published successfully
                  </h4>
                  <p className="text-xs text-green-700 mb-2">
                    Formats: {publishResult.formats_generated.join(", ")}
                  </p>
                  <div className="space-y-1">
                    {Object.entries(publishResult.download_urls).map(([fmt, url]) => (
                      <a
                        key={fmt}
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-xs text-indigo-600 hover:text-indigo-800 underline"
                      >
                        Download {fmt.toUpperCase()}
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Report Body — rendered markdown */}
      <Card>
        <CardBody>
          <div
            className="report-content"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        </CardBody>
      </Card>

      {/* Share Dialog */}
      {showShare && (
        <ShareDialog
          defaultSubject={`Report: ${report.title}`}
          defaultBody={report.content_markdown || report.summary}
          onClose={() => setShowShare(false)}
        />
      )}
    </div>
  );
}
