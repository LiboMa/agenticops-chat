import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { FactRow } from "@/lib/issueDetail";
import { Card, CardBody } from "@/components/ui/Card";
import { formatFullDate } from "@/lib/formatDate";
import { cn } from "@/lib/cn";

/** The right rail's key facts; the rows come already stripped of blank values (`factRows`). */
export function FactsRail({ title, rows, t, extra }: { title: string; rows: FactRow[]; t: (k: string) => string; extra?: React.ReactNode }) {
  const [copied, setCopied] = useState<number | null>(null); // the row just copied says so for a moment
  useEffect(() => {
    if (copied === null) return;
    const h = window.setTimeout(() => setCopied(null), 1500);
    return () => window.clearTimeout(h);
  }, [copied]);
  const copy = (i: number, value: string) =>
    navigator.clipboard?.writeText(value).then(() => setCopied(i), () => {});
  return (
    <Card>
      <CardBody className="space-y-3">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <dl className="space-y-2 text-sm">
          {rows.map((r, i) => {
            const value = r.kind === "date" ? formatFullDate(r.value) : r.value;
            const cls = cn("text-foreground", r.kind === "mono" && "font-mono text-xs break-all");
            return (
              <div key={`${r.labelKey}-${i}`} className="grid grid-cols-[6rem_1fr] gap-2">
                <dt className="text-muted-foreground">{t(r.labelKey)}</dt>
                <dd className="min-w-0 break-words">
                  {r.href && r.external
                    ? <a href={r.href} target="_blank" rel="noopener noreferrer" className={cn(cls, "text-primary hover:underline")}>{value} ↗</a>
                    : r.href ? <Link to={r.href} className={cn(cls, "text-primary hover:underline")}>{value}</Link>
                    : r.copy
                      ? <>
                          <button type="button" title={t("facts.copyHint")} onClick={() => copy(i, r.value)}
                                  className={cn(cls, "text-left hover:text-primary cursor-pointer")}>{value}</button>
                          {/* announced to a screen reader too */}
                          <span role="status" className="ml-2 text-xs text-emerald-600 dark:text-emerald-400">
                            {copied === i ? t("facts.copied") : ""}
                          </span>
                        </>
                    : <span className={cls}>{value}</span>}
                </dd>
              </div>
            );
          })}
        </dl>
        {extra}
      </CardBody>
    </Card>
  );
}
