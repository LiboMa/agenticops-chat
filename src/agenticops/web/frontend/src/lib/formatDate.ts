const shortFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

const fullFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

const clockFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

// An ISO datetime that ends without "Z" or "±hh:mm": the backend's naive UTC.
const NAIVE_ISO_DATETIME = /T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

/** An API timestamp as a Date: an offset-less ISO datetime is UTC (the DB stores naive UTC).
 *  null for an empty, null or unparseable input; a valid Date is returned as is. */
export function parseApiDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? value : new Date(NAIVE_ISO_DATETIME.test(value) ? `${value}Z` : value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** A timestamp, always shown in UTC and labelled so (MVP-2.8.0 S1). "-" for nothing. */
export function formatShortDate(date: string | Date | null | undefined): string {
  const d = parseApiDate(date);
  return d ? `${shortFormatter.format(d)} UTC` : "-";
}

export function formatFullDate(date: string | Date | null | undefined): string {
  const d = parseApiDate(date);
  return d ? `${fullFormatter.format(d)} UTC` : "-";
}

/** The UTC calendar day of an instant, "YYYY-MM-DD" — day groupings and day filters use UTC days (MVP-2.8.0 S1).
 *  "" for nothing. */
export function utcDayKey(date: string | Date | null | undefined): string {
  const d = parseApiDate(date);
  return d ? d.toISOString().slice(0, 10) : "";
}

const dayFormatters: Record<"en" | "zh", Intl.DateTimeFormat> = {
  en: new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }),
  zh: new Intl.DateTimeFormat("zh-CN", { weekday: "short", month: "long", day: "numeric", year: "numeric", timeZone: "UTC" }),
};

/** A utcDayKey as a heading in the page language, labelled UTC. */
export function formatUtcDay(key: string, locale: "en" | "zh"): string {
  const d = new Date(`${key}T00:00:00Z`);
  if (!key || Number.isNaN(d.getTime())) return key;
  return locale === "zh" ? `${dayFormatters.zh.format(d)}（UTC）` : `${dayFormatters.en.format(d)} (UTC)`;
}

const timeFormatter = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

/** "HH:MM UTC" — a time of day, always in UTC and labelled (MVP-2.8.0 S1). "-" for nothing. */
export function formatUtcTime(date: string | Date | number | null | undefined): string {
  const d = typeof date === "number" ? new Date(date) : parseApiDate(date);
  return d && !Number.isNaN(d.getTime()) ? `${timeFormatter.format(d)} UTC` : "-";
}

export function formatUtcClock(date: Date): string {
  return clockFormatter.format(date) + " UTC";
}

/** A duration as "42s", "3m 05s" or "1h 02m"; a negative or non-finite one reads "0s". */
export function formatElapsed(ms: number): string {
  const s = Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : 0;
  const pad = (n: number) => String(n).padStart(2, "0");
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${pad(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${pad(Math.floor((s % 3600) / 60))}m`;
}
