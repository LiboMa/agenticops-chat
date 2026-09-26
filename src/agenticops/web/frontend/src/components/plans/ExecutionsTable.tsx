import { useLocale } from "@/i18n/LocaleContext";
import { formatFullDate } from "@/lib/formatDate";
import type { FixExecution } from "@/api/types";

/** Shared execution-history table (fix + change). The Card, CardBody and heading stay in the caller. */
export function ExecutionsTable({ executions, onCancel, cancelPending = false }: {
  executions: FixExecution[];
  /** Given → pending/running rows get the Cancel button and the table an Actions column. Omitted → no cancel
   *  control and no Actions column (change executions, ruling F6c). */
  onCancel?: (id: number) => void;
  cancelPending?: boolean;
}) {
  const { t } = useLocale();
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">ID</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("plans.status")}</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("issues.executedBy")}</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("issues.duration")}</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("issues.started")}</th>
              {onCancel && (
                <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("issues.actions")}</th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {executions.map((ex) => (
              <tr key={ex.id} className="hover:bg-secondary transition-colors">
                <td className="px-4 py-2 text-sm font-mono text-muted-foreground">#{ex.id}</td>
                <td className="px-4 py-2">
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                      ex.status === "succeeded"
                        ? "bg-green-500/20 text-green-400"
                        : ex.status === "failed"
                          ? "bg-red-500/20 text-red-400"
                          : "bg-secondary text-muted-foreground"
                    }`}
                  >
                    {ex.status}
                  </span>
                </td>
                <td className="px-4 py-2 text-sm text-muted-foreground">{ex.executed_by}</td>
                <td className="px-4 py-2 text-sm text-muted-foreground">
                  {ex.duration_ms > 0 ? `${(ex.duration_ms / 1000).toFixed(1)}s` : "-"}
                </td>
                <td className="px-4 py-2 text-sm text-muted-foreground">
                  {ex.started_at ? formatFullDate(ex.started_at) : "-"}
                </td>
                {onCancel && (
                  <td className="px-4 py-2">
                    {(ex.status === "pending" || ex.status === "running") && (
                      <button
                        onClick={() => onCancel(ex.id)}
                        disabled={cancelPending}
                        className="px-3 py-1 text-xs font-medium text-red-500 border border-red-500/30 rounded-lg hover:bg-red-500/10 disabled:opacity-50 transition-colors"
                      >
                        {t("common.cancel")}
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {executions.some((ex) => ex.error_message) && (
        <div className="mt-4">
          {executions
            .filter((ex) => ex.error_message)
            .map((ex) => (
              <div
                key={ex.id}
                className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-400 mb-2"
              >
                <strong>#{ex.id} {t("issues.executionError")}:</strong> {ex.error_message}
              </div>
            ))}
        </div>
      )}
    </>
  );
}
