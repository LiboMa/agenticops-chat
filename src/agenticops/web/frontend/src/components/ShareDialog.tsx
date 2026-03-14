import { useState } from "react";
import {
  useNotificationChannels,
  useShareContent,
} from "@/hooks/useNotifications";
import type { ShareContentResponse } from "@/api/types";

interface ShareDialogProps {
  defaultSubject?: string;
  defaultBody?: string;
  onClose: () => void;
}

export default function ShareDialog({
  defaultSubject = "",
  defaultBody = "",
  onClose,
}: ShareDialogProps) {
  const [subject, setSubject] = useState(defaultSubject);
  const [body, setBody] = useState(defaultBody);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [uploadToS3, setUploadToS3] = useState(defaultBody.length > 4000);
  const [expiryHours, setExpiryHours] = useState(72);
  const [result, setResult] = useState<ShareContentResponse | null>(null);

  const { data: channels } = useNotificationChannels();
  const shareMutation = useShareContent();

  const enabledChannels = (channels ?? []).filter((c) => c.is_enabled);

  const toggleChannel = (name: string) => {
    setSelectedChannels((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const handleShare = () => {
    if (!subject || !body) return;
    shareMutation.mutate(
      {
        subject,
        body,
        channel_names: selectedChannels.length > 0 ? selectedChannels : undefined,
        upload_to_s3: uploadToS3,
        expiry_hours: expiryHours,
      },
      {
        onSuccess: (data) => setResult(data),
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-lg font-semibold text-foreground">Share Content</h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-muted-foreground transition-colors"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {/* Subject */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Subject</label>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>

          {/* Body preview */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Content ({body.length.toLocaleString()} chars)
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={6}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 resize-y"
            />
          </div>

          {/* Channel selection */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-2">
              Channels {selectedChannels.length === 0 && "(all enabled)"}
            </label>
            <div className="max-h-40 overflow-y-auto space-y-1 border border-border rounded-lg p-2">
              {enabledChannels.map((ch) => (
                <label
                  key={ch.name}
                  className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-secondary cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedChannels.includes(ch.name)}
                    onChange={() => toggleChannel(ch.name)}
                    className="rounded border-border text-primary-600 focus:ring-primary-500"
                  />
                  <span className="text-sm text-foreground">{ch.name}</span>
                  <span className="text-xs text-muted-foreground ml-auto">{ch.channel_type}</span>
                </label>
              ))}
              {enabledChannels.length === 0 && (
                <p className="text-xs text-muted-foreground px-2 py-1">No enabled channels</p>
              )}
            </div>
          </div>

          {/* S3 upload toggle */}
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={uploadToS3}
                onChange={(e) => setUploadToS3(e.target.checked)}
                className="rounded border-border text-primary-600 focus:ring-primary-500"
              />
              Upload to S3
              {body.length > 4000 && (
                <span className="text-xs text-amber-600">(recommended for large content)</span>
              )}
            </label>
            {uploadToS3 && (
              <select
                value={expiryHours}
                onChange={(e) => setExpiryHours(Number(e.target.value))}
                className="px-2 py-1 border border-border rounded text-xs focus:outline-none focus:ring-2 focus:ring-primary-500"
              >
                <option value={24}>24h</option>
                <option value={72}>3 days</option>
                <option value={168}>7 days</option>
              </select>
            )}
          </div>

          {/* Result */}
          {result && (
            <div
              className={`rounded-lg p-3 ${
                result.success
                  ? "bg-primary-50 border border-primary-200"
                  : "bg-destructive/10 border border-destructive/20"
              }`}
            >
              <p className={`text-sm font-medium ${result.success ? "text-primary-800" : "text-destructive"}`}>
                {result.success ? "Shared successfully" : "Share failed"}
              </p>
              {result.channels_sent.length > 0 && (
                <p className="text-xs text-primary-700 mt-1">
                  Sent: {result.channels_sent.join(", ")}
                </p>
              )}
              {result.channels_failed.length > 0 && (
                <p className="text-xs text-destructive mt-1">
                  Failed: {result.channels_failed.join(", ")}
                </p>
              )}
              {result.presigned_url && (
                <a
                  href={result.presigned_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block text-xs text-primary-600 hover:text-primary-800 underline mt-1"
                >
                  Download link
                </a>
              )}
            </div>
          )}

          {shareMutation.isError && (
            <p className="text-sm text-destructive">
              {(shareMutation.error as Error).message}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-border">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-foreground bg-secondary hover:bg-muted rounded-lg transition-colors"
          >
            Close
          </button>
          <button
            onClick={handleShare}
            disabled={!subject || !body || shareMutation.isPending}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
          >
            {shareMutation.isPending ? "Sending..." : "Share"}
          </button>
        </div>
      </div>
    </div>
  );
}
