import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useAnomalies } from "@/hooks/useAnomalies";
import { useLocale } from "@/i18n/LocaleContext";
import { IssueRow } from "@/components/ui/IssueRow";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { Anomaly } from "@/api/types";

type Phase = "all" | "open" | "in_progress" | "resolved";

const OPEN_STATUSES = new Set(["open"]);
const IN_PROGRESS_STATUSES = new Set([
  "investigating",
  "acknowledged",
  "root_cause_identified",
  "fix_planned",
  "fix_approved",
  "fix_executing",
  "fix_executed",
]);
const RESOLVED_STATUSES = new Set(["resolved"]);

function getPhase(status: string): Phase {
  if (OPEN_STATUSES.has(status)) return "open";
  if (IN_PROGRESS_STATUSES.has(status)) return "in_progress";
  if (RESOLVED_STATUSES.has(status)) return "resolved";
  return "all";
}

function matchesSearch(issue: Anomaly, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    issue.title.toLowerCase().includes(q) ||
    issue.resource_id.toLowerCase().includes(q) ||
    issue.region.toLowerCase().includes(q)
  );
}

export default function IssuesAndPlans() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("all");
  const [search, setSearch] = useState("");

  const { data, isLoading, error, refetch } = useAnomalies();

  const allIssues = data ?? [];

  const counts = useMemo(() => {
    const c = { all: 0, open: 0, in_progress: 0, resolved: 0 };
    for (const issue of allIssues) {
      c.all++;
      const p = getPhase(issue.status);
      if (p === "open") c.open++;
      else if (p === "in_progress") c.in_progress++;
      else if (p === "resolved") c.resolved++;
    }
    return c;
  }, [allIssues]);

  const filtered = useMemo(() => {
    return allIssues.filter((issue) => {
      if (phase !== "all" && getPhase(issue.status) !== phase) return false;
      if (!matchesSearch(issue, search)) return false;
      return true;
    });
  }, [allIssues, phase, search]);

  const chips: { key: Phase; label: string; count: number }[] = [
    { key: "all", label: t("issues.all"), count: counts.all },
    { key: "open", label: t("issues.open"), count: counts.open },
    { key: "in_progress", label: t("issues.inProgress"), count: counts.in_progress },
    { key: "resolved", label: t("issues.resolved"), count: counts.resolved },
  ];

  return (
    <div className="space-y-4">
      {/* Page title */}
      <h1 className="text-xl font-semibold text-foreground">
        {t("issues.title")}
      </h1>

      {error && (
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
      )}

      {/* Filter bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          {chips.map((chip) => (
            <button
              key={chip.key}
              onClick={() => setPhase(chip.key)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                phase === chip.key
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-muted-foreground hover:text-foreground hover:bg-accent"
              }`}
            >
              {chip.label}
              <span
                className={`inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 text-xs rounded-full ${
                  phase === chip.key
                    ? "bg-primary-foreground/20 text-primary-foreground"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                {chip.count}
              </span>
            </button>
          ))}
        </div>

        <div className="relative">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("issues.search")}
            className="pl-9 pr-3 py-1.5 text-sm rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 w-64"
          />
        </div>
      </div>

      {/* Issue list */}
      {isLoading ? (
        <Spinner />
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <svg
            className="h-12 w-12 mb-3 opacity-30"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <p className="text-sm">{t("issues.noIssues")}</p>
        </div>
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          {filtered.map((issue) => (
            <IssueRow
              key={issue.id}
              issue={issue}
              onClick={() => navigate(`/app/issues/${issue.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
