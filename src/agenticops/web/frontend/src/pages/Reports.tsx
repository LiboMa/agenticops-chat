import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useReports } from "@/hooks/useReports";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { Report } from "@/api/types";

const TYPE_COLORS: Record<string, string> = {
  daily: "bg-blue-100 text-blue-700",
  incident: "bg-red-100 text-red-700",
  inventory: "bg-emerald-100 text-emerald-700",
  weekly: "bg-purple-100 text-purple-700",
  conversation: "bg-violet-100 text-violet-700",
  anomaly: "bg-orange-100 text-orange-700",
  newsletter: "bg-amber-100 text-amber-700",
  "security-review": "bg-rose-100 text-rose-700",
};

/** Strip markdown noise (headings/emphasis/tables/rules) so raw report bodies read as prose. */
export function plainSummary(s: string): string {
  return s
    .replace(/^#+\s*/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/^\s*[-|=]{3,}\s*$/gm, " ")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 220);
}

/** Group reports by calendar day (local), newest day first; rows within a day newest first. */
export function groupByDay(reports: Report[]): { day: string; rows: Report[] }[] {
  const groups = new Map<string, Report[]>();
  const sorted = [...reports].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  for (const r of sorted) {
    const day = new Date(r.created_at).toLocaleDateString(undefined, {
      year: "numeric", month: "short", day: "numeric",
    });
    const bucket = groups.get(day);
    if (bucket) bucket.push(r);
    else groups.set(day, [r]);
  }
  return [...groups.entries()].map(([day, rows]) => ({ day, rows }));
}

export default function Reports() {
  const { data, isLoading, error, refetch } = useReports();
  const [search, setSearch] = useState("");
  const navigate = useNavigate();

  const groups = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    const filtered = q
      ? data.filter(
          (r) =>
            r.title.toLowerCase().includes(q) ||
            r.summary.toLowerCase().includes(q),
        )
      : data;
    return groupByDay(filtered);
  }, [data, search]);

  const total = groups.reduce((s, g) => s + g.rows.length, 0);

  if (isLoading) return <Spinner label="Loading reports..." />;
  if (error)
    return <ErrorBanner message={error.message} onRetry={() => refetch()} />;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">Reports</h2>
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Search reports..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="text-sm border border-border rounded-lg px-3 py-1.5 w-64 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
            <span className="text-sm text-muted-foreground">
              {total} reports
            </span>
          </div>
        </CardHeader>
        <CardBody className="p-0">
          {groups.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground text-sm">
              No reports found.
            </div>
          ) : (
            groups.map(({ day, rows }) => (
              <div key={day}>
                <div className="px-5 py-1.5 bg-muted/50 border-y border-border/50 text-[11px] font-medium text-muted-foreground uppercase tracking-[0.08em] sticky top-0">
                  {day}
                  <span className="ml-2 normal-case tracking-normal text-muted-foreground/60">{rows.length}</span>
                </div>
                {rows.map((r) => (
                  <div
                    key={r.id}
                    onClick={() => navigate(`/app/reports/${r.id}`)}
                    className="flex items-start gap-4 px-5 py-3 border-b border-border/50 cursor-pointer transition-colors hover:bg-accent"
                  >
                    <Badge
                      className={`mt-0.5 flex-shrink-0 ${TYPE_COLORS[r.report_type] ?? "bg-secondary text-muted-foreground"}`}
                    >
                      {r.report_type}
                    </Badge>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-foreground line-clamp-1">{r.title}</div>
                      <div className="text-sm text-muted-foreground line-clamp-2 mt-0.5">
                        {plainSummary(r.summary)}
                      </div>
                    </div>
                    <span className="text-xs text-muted-foreground whitespace-nowrap mt-1">
                      {new Date(r.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                ))}
              </div>
            ))
          )}
        </CardBody>
      </Card>
    </div>
  );
}
