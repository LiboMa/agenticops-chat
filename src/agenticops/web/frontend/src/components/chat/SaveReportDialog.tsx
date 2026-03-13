import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateReportFromSession } from "@/hooks/useReports";
import type { Report } from "@/api/types";

interface Props {
  sessionId: string;
  sessionName: string;
  onClose: () => void;
}

export default function SaveReportDialog({ sessionId, sessionName, onClose }: Props) {
  const navigate = useNavigate();
  const mutation = useCreateReportFromSession();

  const [title, setTitle] = useState(sessionName);
  const [summary, setSummary] = useState("");
  const [format, setFormat] = useState("markdown");
  const [savedReport, setSavedReport] = useState<Report | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate(
      {
        session_id: sessionId,
        title,
        summary: summary || undefined,
        format,
      },
      {
        onSuccess: (data) => setSavedReport(data),
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center">
      <div className="bg-background rounded-xl shadow-2xl w-full max-w-md mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-lg font-semibold text-foreground">Save as Report</h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {savedReport ? (
            <>
              <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-700">
                Report saved successfully
              </div>
              <button
                onClick={() => navigate(`/app/reports/${savedReport.id}`)}
                className="text-sm font-medium text-primary-600 hover:text-primary-700 transition-colors"
              >
                View Report
              </button>
            </>
          ) : (
            <form onSubmit={handleSubmit} id="save-report-form" className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Title</label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">
                  Summary (optional)
                </label>
                <textarea
                  rows={3}
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  placeholder="Brief summary of the conversation..."
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Format</label>
                <select
                  value={format}
                  onChange={(e) => setFormat(e.target.value)}
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
                >
                  <option value="markdown">Markdown</option>
                  <option value="html">HTML</option>
                  <option value="pdf">PDF</option>
                  <option value="docx">DOCX</option>
                </select>
              </div>
              {mutation.isError && (
                <p className="text-sm text-destructive">
                  {(mutation.error as Error).message}
                </p>
              )}
            </form>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-border">
          {savedReport ? (
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-foreground bg-secondary hover:bg-muted rounded-lg transition-colors"
            >
              Done
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-foreground bg-secondary hover:bg-muted rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                form="save-report-form"
                disabled={mutation.isPending}
                className="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
              >
                {mutation.isPending ? "Saving..." : "Save Report"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
