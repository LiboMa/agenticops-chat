import { useState, useEffect, useCallback, useRef } from "react";
import { cn } from "@/lib/cn";
import {
  CRON_PRESETS,
  MINUTE_OPTIONS,
  HOUR_OPTIONS,
  DOM_OPTIONS,
  MONTH_OPTIONS,
  DOW_OPTIONS,
  validateCron,
  describeCron,
  parseCronFields,
  buildCron,
  type CronFields,
  type CronPreset,
} from "@/lib/cronHelpers";
import { apiFetch } from "@/api/client";
import {
  Clock,
  Moon,
  Sun,
  Sunrise,
  Calendar,
  CalendarDays,
  ChevronDown,
  Check,
  X,
  Timer,
  type LucideIcon,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CronBuilderProps {
  value: string;
  onChange: (cron: string) => void;
}

interface CronPreviewResponse {
  valid: boolean;
  next_runs?: string[];
  error?: string;
}

/* ------------------------------------------------------------------ */
/*  Preset icon map                                                    */
/* ------------------------------------------------------------------ */

const PRESET_ICONS: Record<CronPreset["icon"], LucideIcon> = {
  clock: Clock,
  "clock-6": Clock,
  moon: Moon,
  sun: Sun,
  sunrise: Sunrise,
  calendar: Calendar,
  "calendar-days": CalendarDays,
};

/* ------------------------------------------------------------------ */
/*  Relative time helper                                               */
/* ------------------------------------------------------------------ */

function relativeTime(iso: string): string {
  const d = new Date(iso + "Z");
  const now = new Date();
  const diffMs = d.getTime() - now.getTime();
  if (diffMs < 0) return "now";
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 60) return `in ${mins}m`;
  const hrs = Math.floor(mins / 60);
  const rm = mins % 60;
  if (hrs < 24) return rm > 0 ? `in ${hrs}h ${rm}m` : `in ${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `in ${days}d`;
}

/* ------------------------------------------------------------------ */
/*  Field selector sub-component                                       */
/* ------------------------------------------------------------------ */

interface FieldSelectorProps {
  label: string;
  value: string;
  options: string[] | { value: string; label: string }[];
  onChange: (val: string) => void;
}

function FieldSelector({ label, value, options, onChange }: FieldSelectorProps) {
  const isObjectOptions = options.length > 0 && typeof options[0] === "object";
  const currentInOptions = isObjectOptions
    ? (options as { value: string }[]).some((o) => o.value === value)
    : (options as string[]).includes(value);

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
        {label}
      </span>
      <select
        value={currentInOptions ? value : "__custom"}
        onChange={(e) => {
          if (e.target.value !== "__custom") onChange(e.target.value);
        }}
        className={cn(
          "h-9 rounded-lg border border-border bg-background px-2.5 text-sm font-mono",
          "text-foreground transition-all duration-150",
          "hover:border-primary-400 focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20",
        )}
      >
        {isObjectOptions
          ? (options as { value: string; label: string }[]).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))
          : (options as string[]).map((o) => (
              <option key={o} value={o}>
                {o === "*" ? "Every" : o}
              </option>
            ))}
        {!currentInOptions && <option value="__custom">{value}</option>}
      </select>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main CronBuilder                                                   */
/* ------------------------------------------------------------------ */

export function CronBuilder({ value, onChange }: CronBuilderProps) {
  const [showCustom, setShowCustom] = useState(false);
  const [fields, setFields] = useState<CronFields>(
    () => parseCronFields(value) ?? { minute: "0", hour: "*", dom: "*", month: "*", dow: "*" },
  );
  const [preview, setPreview] = useState<CronPreviewResponse | null>(null);
  const [rawInput, setRawInput] = useState("");
  const [showRaw, setShowRaw] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const validation = validateCron(value);

  // Sync fields when value changes externally
  useEffect(() => {
    const parsed = parseCronFields(value);
    if (parsed) setFields(parsed);
  }, [value]);

  // Debounced backend preview
  const fetchPreview = useCallback((expr: string) => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      if (!validateCron(expr).valid) {
        setPreview(null);
        return;
      }
      try {
        const res = await apiFetch<CronPreviewResponse>(
          `/schedules/cron-preview?expr=${encodeURIComponent(expr)}`,
        );
        setPreview(res);
      } catch {
        setPreview(null);
      }
    }, 400);
  }, []);

  useEffect(() => {
    fetchPreview(value);
    return () => clearTimeout(debounceRef.current);
  }, [value, fetchPreview]);

  const handleFieldChange = (field: keyof CronFields, val: string) => {
    const next = { ...fields, [field]: val };
    setFields(next);
    onChange(buildCron(next));
  };

  const handleRawCommit = () => {
    const trimmed = rawInput.trim();
    if (trimmed && validateCron(trimmed).valid) {
      onChange(trimmed);
      setRawInput("");
    }
  };

  return (
    <div className="space-y-4">
      {/* Section label */}
      <label className="block text-sm font-semibold text-foreground">Schedule</label>

      {/* ── Preset cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {CRON_PRESETS.map((p) => {
          const active = value.trim() === p.cron;
          const Icon = PRESET_ICONS[p.icon];
          return (
            <button
              key={p.cron}
              type="button"
              onClick={() => {
                onChange(p.cron);
                setShowCustom(false);
              }}
              className={cn(
                "group relative flex items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left",
                "transition-all duration-200 ease-out",
                active
                  ? "border-primary-500 bg-primary-50 dark:bg-primary-950/40 shadow-sm shadow-primary-500/10"
                  : "border-border bg-background hover:border-primary-300 hover:bg-secondary/60 dark:hover:bg-secondary/40",
              )}
            >
              {/* Icon */}
              <div
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors duration-200",
                  active
                    ? "bg-primary-500 text-white dark:bg-primary-600"
                    : "bg-secondary text-muted-foreground group-hover:bg-primary-100 group-hover:text-primary-600 dark:group-hover:bg-primary-900 dark:group-hover:text-primary-400",
                )}
              >
                <Icon className="h-4 w-4" strokeWidth={2} />
              </div>

              {/* Text */}
              <div className="flex-1 min-w-0">
                <div
                  className={cn(
                    "text-sm font-medium leading-tight",
                    active ? "text-primary-700 dark:text-primary-300" : "text-foreground",
                  )}
                >
                  {p.label}
                </div>
                <div className="text-[11px] text-muted-foreground leading-tight mt-0.5 truncate">
                  {p.desc}
                </div>
              </div>

              {/* Active check */}
              {active && (
                <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary-500 text-white dark:bg-primary-400 dark:text-primary-950">
                  <Check className="h-3 w-3" strokeWidth={3} />
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* ── Custom expression toggle ── */}
      <button
        type="button"
        onClick={() => setShowCustom(!showCustom)}
        className={cn(
          "flex items-center gap-1.5 text-xs font-medium transition-colors duration-150",
          showCustom
            ? "text-primary-600 dark:text-primary-400"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 transition-transform duration-200",
            showCustom && "rotate-180",
          )}
        />
        {showCustom ? "Hide custom editor" : "Custom expression"}
      </button>

      {/* ── Custom field editors ── */}
      <div
        className={cn(
          "grid transition-all duration-300 ease-out",
          showCustom ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="overflow-hidden">
          <div className="rounded-xl border border-border bg-secondary/30 p-4 space-y-4">
            {/* 5-field grid */}
            <div className="grid grid-cols-5 gap-3">
              <FieldSelector
                label="Minute"
                value={fields.minute}
                options={MINUTE_OPTIONS}
                onChange={(v) => handleFieldChange("minute", v)}
              />
              <FieldSelector
                label="Hour"
                value={fields.hour}
                options={HOUR_OPTIONS}
                onChange={(v) => handleFieldChange("hour", v)}
              />
              <FieldSelector
                label="Day"
                value={fields.dom}
                options={DOM_OPTIONS}
                onChange={(v) => handleFieldChange("dom", v)}
              />
              <FieldSelector
                label="Month"
                value={fields.month}
                options={MONTH_OPTIONS}
                onChange={(v) => handleFieldChange("month", v)}
              />
              <FieldSelector
                label="Weekday"
                value={fields.dow}
                options={DOW_OPTIONS}
                onChange={(v) => handleFieldChange("dow", v)}
              />
            </div>

            {/* Raw expression input (power-user toggle) */}
            <div className="border-t border-border/60 pt-3">
              <button
                type="button"
                onClick={() => setShowRaw(!showRaw)}
                className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
              >
                {showRaw ? "Hide raw input" : "Or type raw cron expression..."}
              </button>
              {showRaw && (
                <div className="flex gap-2 mt-2">
                  <input
                    type="text"
                    value={rawInput}
                    onChange={(e) => setRawInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleRawCommit())}
                    placeholder="e.g. */15 9-17 * * 1-5"
                    className={cn(
                      "flex-1 h-8 rounded-lg border border-border bg-background px-3 text-xs font-mono",
                      "placeholder:text-muted-foreground/50",
                      "focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20",
                    )}
                  />
                  <button
                    type="button"
                    onClick={handleRawCommit}
                    disabled={!rawInput.trim() || !validateCron(rawInput.trim()).valid}
                    className={cn(
                      "h-8 px-3 rounded-lg text-xs font-medium transition-colors",
                      "bg-primary-600 text-white hover:bg-primary-500",
                      "disabled:opacity-40 disabled:cursor-not-allowed",
                    )}
                  >
                    Apply
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Preview card ── */}
      {value.trim() && (
        <div
          className={cn(
            "rounded-xl border p-4 space-y-3 transition-colors duration-200",
            validation.valid
              ? "border-primary-200 bg-gradient-to-br from-primary-50/80 to-background dark:border-primary-800/40 dark:from-primary-950/30 dark:to-background"
              : "border-red-200 bg-gradient-to-br from-red-50/80 to-background dark:border-red-800/40 dark:from-red-950/30 dark:to-background",
          )}
        >
          {/* Expression + badge */}
          <div className="flex items-center justify-between gap-3">
            <code className="font-mono text-sm font-semibold text-foreground tracking-wide">
              {value}
            </code>
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                validation.valid
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400"
                  : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
              )}
            >
              {validation.valid ? (
                <>
                  <Check className="h-3 w-3" strokeWidth={3} />
                  Valid
                </>
              ) : (
                <>
                  <X className="h-3 w-3" strokeWidth={3} />
                  Invalid
                </>
              )}
            </span>
          </div>

          {/* Human-readable description */}
          {validation.valid && (
            <p className="text-sm text-muted-foreground leading-relaxed">
              {describeCron(value)}
            </p>
          )}

          {/* Validation error */}
          {!validation.valid && validation.error && (
            <p className="text-xs text-red-600 dark:text-red-400">{validation.error}</p>
          )}

          {/* Next runs timeline */}
          {preview?.valid && preview.next_runs && preview.next_runs.length > 0 && (
            <div className="flex items-start gap-2 pt-1">
              <Timer className="h-3.5 w-3.5 text-muted-foreground mt-0.5 shrink-0" />
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {preview.next_runs.map((r, i) => {
                  const d = new Date(r + "Z");
                  const fmt = new Intl.DateTimeFormat(undefined, {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                  });
                  return (
                    <span key={i} className="text-xs text-muted-foreground whitespace-nowrap">
                      <span className="font-medium text-foreground">{fmt.format(d)}</span>
                      <span className="ml-1 text-[10px] opacity-60">({relativeTime(r)})</span>
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
