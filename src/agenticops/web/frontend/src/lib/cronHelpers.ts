/** Cron expression helpers: presets, validation, human-readable descriptions. */

export interface CronPreset {
  label: string;
  cron: string;
  desc: string;
  icon: "clock" | "clock-6" | "moon" | "sun" | "sunrise" | "calendar" | "calendar-days";
}

export const CRON_PRESETS: CronPreset[] = [
  { label: "Hourly", cron: "0 * * * *", desc: "Every hour at :00", icon: "clock" },
  { label: "Every 6h", cron: "0 */6 * * *", desc: "Every 6 hours", icon: "clock-6" },
  { label: "Daily (midnight)", cron: "0 0 * * *", desc: "Every day at 00:00", icon: "moon" },
  { label: "Daily (9 AM)", cron: "0 9 * * *", desc: "Every day at 09:00", icon: "sun" },
  { label: "Twice daily", cron: "0 0,12 * * *", desc: "At 00:00 and 12:00", icon: "sunrise" },
  { label: "Weekly (Mon)", cron: "0 0 * * 1", desc: "Every Monday at 00:00", icon: "calendar" },
  { label: "Monthly", cron: "0 0 1 * *", desc: "1st of every month at 00:00", icon: "calendar-days" },
];

// Common dropdown options per field
export const MINUTE_OPTIONS = ["0", "15", "30", "*/5", "*/10", "*/15", "*/30", "*"];
export const HOUR_OPTIONS = ["0", "1", "6", "9", "12", "18", "*/2", "*/6", "*/12", "*"];
export const DOM_OPTIONS = ["1", "15", "*/2", "*"];
export const MONTH_OPTIONS = ["1", "*/2", "*/3", "*/6", "*"];
export const DOW_OPTIONS = [
  { value: "*", label: "Every day" },
  { value: "1-5", label: "Weekdays" },
  { value: "0,6", label: "Weekends" },
  { value: "1", label: "Monday" },
  { value: "2", label: "Tuesday" },
  { value: "3", label: "Wednesday" },
  { value: "4", label: "Thursday" },
  { value: "5", label: "Friday" },
  { value: "6", label: "Saturday" },
  { value: "0", label: "Sunday" },
];

const CRON_FIELD_RE = /^(\*|(\d+(-\d+)?(,\d+(-\d+)?)*)(\/\d+)?|\*\/\d+)$/;

export interface CronFields {
  minute: string;
  hour: string;
  dom: string;
  month: string;
  dow: string;
}

export function parseCronFields(expr: string): CronFields | null {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  return { minute: parts[0], hour: parts[1], dom: parts[2], month: parts[3], dow: parts[4] };
}

export function buildCron(f: CronFields): string {
  return `${f.minute} ${f.hour} ${f.dom} ${f.month} ${f.dow}`;
}

export function validateCron(expr: string): { valid: boolean; error?: string } {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return { valid: false, error: `Expected 5 fields, got ${parts.length}` };

  const names = ["Minute", "Hour", "Day of month", "Month", "Day of week"];
  const maxVals = [59, 23, 31, 12, 7];

  for (let i = 0; i < 5; i++) {
    if (!CRON_FIELD_RE.test(parts[i])) {
      return { valid: false, error: `${names[i]}: invalid syntax "${parts[i]}"` };
    }
    // Check numeric ranges
    const nums = parts[i].replace(/\*/g, "").split(/[,\-\/]/).filter(Boolean);
    for (const n of nums) {
      const v = parseInt(n, 10);
      if (!isNaN(v) && v > maxVals[i]) {
        return { valid: false, error: `${names[i]}: ${v} exceeds max ${maxVals[i]}` };
      }
    }
  }
  return { valid: true };
}

const DOW_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function describeCron(expr: string): string {
  const f = parseCronFields(expr);
  if (!f) return "Invalid expression";

  const parts: string[] = [];

  // Minute
  if (f.minute === "*") {
    parts.push("Every minute");
  } else if (f.minute.startsWith("*/")) {
    parts.push(`Every ${f.minute.slice(2)} minutes`);
  }

  // Hour
  if (f.hour === "*" && f.minute !== "*" && !f.minute.startsWith("*/")) {
    parts.push("every hour");
  } else if (f.hour.startsWith("*/")) {
    parts.push(`every ${f.hour.slice(2)} hours`);
  } else if (f.hour !== "*") {
    const hours = f.hour.split(",");
    if (hours.length === 1) {
      const hh = hours[0].padStart(2, "0");
      const mm = (f.minute === "*" ? "00" : f.minute).padStart(2, "0");
      parts.push(`at ${hh}:${mm}`);
    } else {
      parts.push(`at hours ${f.hour}`);
    }
  }

  // Day of month
  if (f.dom !== "*") {
    if (f.dom.startsWith("*/")) {
      parts.push(`every ${f.dom.slice(2)} days`);
    } else {
      parts.push(`on day ${f.dom}`);
    }
  }

  // Month
  if (f.month !== "*") {
    if (f.month.startsWith("*/")) {
      parts.push(`every ${f.month.slice(2)} months`);
    } else {
      const monthNames = f.month.split(",").map((m) => MONTH_NAMES[parseInt(m, 10)] || m);
      parts.push(`in ${monthNames.join(", ")}`);
    }
  }

  // Day of week
  if (f.dow !== "*") {
    if (f.dow === "1-5") {
      parts.push("on weekdays");
    } else if (f.dow === "0,6") {
      parts.push("on weekends");
    } else {
      const dayNames = f.dow.split(",").map((d) => DOW_NAMES[parseInt(d, 10)] || d);
      parts.push(`on ${dayNames.join(", ")}`);
    }
  }

  if (parts.length === 0) return "Every minute";

  // Capitalize first letter
  const s = parts.join(", ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
