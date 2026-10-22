/** Report publishing (MVP-2.7.0 S6): which channels can publish, and where a publish actually goes. Pure. */
import type { NotificationChannel } from "@/api/types";

export const publishableChannels = (channels: NotificationChannel[] | undefined) =>
  (channels ?? []).filter((c) => (c.channel_type === "sns-report" || c.channel_type === "ses") && c.is_enabled);

/** The real destination to show before sending: the SNS topic, or the SES recipients. */
export function destinationOf(c: Pick<NotificationChannel, "channel_type" | "config"> | undefined): string {
  if (!c) return "";
  const cfg = c.config ?? {};
  if (c.channel_type === "ses") {
    const r = cfg.recipients;
    return Array.isArray(r) ? r.map(String).join(", ") : typeof r === "string" ? r : "";
  }
  return typeof cfg.topic_arn === "string" ? cfg.topic_arn : "";
}
