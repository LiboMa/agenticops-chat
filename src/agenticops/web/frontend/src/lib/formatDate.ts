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

export function formatShortDate(date: string | Date | null | undefined): string {
  const d = parseApiDate(date);
  return d ? shortFormatter.format(d) : "-";
}

export function formatFullDate(date: string | Date | null | undefined): string {
  const d = parseApiDate(date);
  return d ? fullFormatter.format(d) : "-";
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
