import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSignals, usePromoteSignal } from "@/hooks/useSignals";
import { useLocale } from "@/i18n/LocaleContext";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { formatShortDate } from "@/lib/formatDate";
import type { Signal } from "@/api/types";

const DISPOSITION_STYLES: Record<string, string> = {
  promoted: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  merged: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  noise: "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  error: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

const DISPOSITION_ICONS: Record<string, string> = {
  promoted: "＋",
  merged: "⇥",
  noise: "🔇",
  error: "⚠",
};

/** Signals ledger — every gated event with its disposition, reason, and recovery path. */
export function SignalsPanel() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [dispositionFilter, setDispositionFilter] = useState<string>("");
  const signals = useSignals(dispositionFilter ? { disposition: dispositionFilter } : {});
  const promote = usePromoteSignal();

  if (signals.isLoading) return <Spinner />;
  if (signals.error) {
    return <ErrorBanner message={(signals.error as Error).message} onRetry={() => signals.refetch()} />;
  }
  const rows = signals.data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {["", "promoted", "merged", "noise"].map((d) => (
          <button
            key={d || "all"}
            onClick={() => setDispositionFilter(d)}
            className={`px-3 py-1 text-sm font-medium rounded-lg transition-colors ${
              dispositionFilter === d
                ? "bg-primary text-primary-foreground"
                : "bg-secondary text-muted-foreground hover:text-foreground"
            }`}
          >
            {d ? t(`signals.${d}`) : t("signals.all")}
          </button>
        ))}
        <span className="text-xs text-muted-foreground ml-auto">
          {t("signals.hint")}
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="text-sm text-muted-foreground py-8 text-center">
          {t("signals.empty")}
        </div>
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden divide-y divide-border">
          {rows.map((signal) => (
            <SignalRow
              key={signal.id}
              signal={signal}
              onOpenIssue={(id) => navigate(`/app/issues/${id}`)}
              onPromote={(id) => promote.mutate(id)}
              promoting={promote.isPending}
              t={t}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SignalRow({
  signal,
  onOpenIssue,
  onPromote,
  promoting,
  t,
}: {
  signal: Signal;
  onOpenIssue: (issueId: number) => void;
  onPromote: (signalId: number) => void;
  promoting: boolean;
  t: (key: string) => string;
}) {
  const disposition = signal.disposition ?? "error";
  const canPromote = disposition === "noise" || disposition === "merged";
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 text-sm">
      <span className="text-xs text-muted-foreground w-28 shrink-0">
        {formatShortDate(signal.received_at)}
      </span>
      <span
        className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full shrink-0 ${DISPOSITION_STYLES[disposition]}`}
        title={signal.disposition_reason}
      >
        {DISPOSITION_ICONS[disposition]} {t(`signals.${disposition}`)}
      </span>
      <SeverityBadge severity={signal.severity as never} />
      <span className="truncate flex-1 text-foreground" title={signal.title}>
        {signal.title}
      </span>
      <span className="text-xs text-muted-foreground shrink-0 hidden md:inline">
        {signal.issue_type} · {signal.disposition_reason}
      </span>
      {signal.health_issue_id ? (
        <button
          onClick={() => onOpenIssue(signal.health_issue_id!)}
          className="text-xs text-primary hover:underline shrink-0"
        >
          I#{signal.health_issue_id}
        </button>
      ) : canPromote ? (
        <button
          onClick={() => onPromote(signal.id)}
          disabled={promoting}
          className="text-xs px-2 py-1 rounded-md bg-secondary text-muted-foreground hover:text-foreground hover:bg-accent transition-colors shrink-0 disabled:opacity-50"
        >
          {t("signals.promote")}
        </button>
      ) : null}
    </div>
  );
}
