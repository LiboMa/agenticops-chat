import { useState } from "react";
import type { RCAResult } from "@/api/types";
import { useRcaFeedback } from "@/hooks/useSignals";
import { useIssueFeedback } from "@/hooks/useAgentMemory";
import { useLocale } from "@/i18n/LocaleContext";
import {
  choiceAvailable, noteRequired, remainingRequests, VERDICT_CHOICES, verdictRequests, type VerdictChoice, type VerdictRequests,
} from "@/lib/verdict";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** "Your verdict" (P9): one choice and one submit, sent over the RCA-feedback endpoint and then the issue-feedback
 *  one. Once the RCA carries a human verdict the block only shows it, as before — with a retry of the issue
 *  feedback when that second call failed. A recorded location verdict is LocationSection's to show. */
export function VerdictBlock({ issueId, rca, onDone }: { issueId: number; rca: RCAResult | null | undefined; onDone?: () => void }) {
  const { t } = useLocale();
  const rcaFb = useRcaFeedback(issueId);
  const issueFb = useIssueFeedback();
  const [choice, setChoice] = useState<VerdictChoice | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<VerdictRequests | null>(null); // a half-saved submit's second part

  async function send(req: VerdictRequests) {
    setBusy(true);
    setError(null);
    try {
      if (req.rcaFeedback) await rcaFb.mutateAsync(req.rcaFeedback);
    } catch (e) {
      setError(message(e));
      setBusy(false);
      return;
    }
    try {
      if (req.issueFeedback) await issueFb.mutateAsync({ issueId, feedback: req.issueFeedback });
    } catch (e) {
      // the root-cause verdict already took effect and is not rolled back: only the rest is retried
      const rest = remainingRequests(req, "issueFeedback");
      setRemaining(rest);
      setError(rest ? `${t("verdict.partialSaved")} ${message(e)}` : message(e));
      setBusy(false);
      return;
    }
    setRemaining(null);
    setBusy(false);
    onDone?.();
  }
  const submit = () => { if (choice) void send(verdictRequests(choice, rca, note)); };

  const errorLine = error && <p className="text-sm text-destructive break-words">{error}</p>;
  const retryButton = remaining && (
    <button onClick={() => void send(remaining)} disabled={busy}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-primary/40 text-primary hover:bg-primary/10 disabled:opacity-50 transition-colors">
      {t("verdict.retryRemaining")}
    </button>
  );

  if (rca?.human_verdict) {
    return (
      <div className="rounded-lg border border-border p-4 space-y-2">
        <h4 className="font-semibold text-foreground">{t("verdict.title")}</h4>
        <p className="text-sm text-foreground">
          {t("verdict.recorded").replace("{verdict}", t(`location.verdict.${rca.human_verdict}`))}
        </p>
        {errorLine}
        {retryButton}
      </div>
    );
  }

  const needNote = choice !== null && noteRequired(choice);
  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div>
        <h4 className="font-semibold text-foreground">{t("verdict.title")}</h4>
        <p className="text-xs text-muted-foreground">{t("verdict.hint")}</p>
      </div>
      <div role="radiogroup" aria-label={t("verdict.title")} className="space-y-1.5">
        {VERDICT_CHOICES.map((c) => {
          const available = choiceAvailable(c, rca);
          return (
            <label key={c} className={`flex items-start gap-2 text-sm ${available ? "cursor-pointer text-foreground" : "text-muted-foreground"}`}>
              <input type="radio" name={`verdict-${issueId}`} value={c} checked={choice === c} disabled={!available || busy}
                     onChange={() => setChoice(c)} className="mt-0.5" />
              <span>
                {t(`verdict.choice.${c}`)}
                {!available && (
                  <span className="ml-2 text-xs text-muted-foreground">{t(rca ? "location.cannotJudge" : "verdict.needRca")}</span>
                )}
              </span>
            </label>
          );
        })}
      </div>
      {needNote && (
        <label className="block space-y-1">
          <span className="text-sm text-foreground">
            {t("verdict.note")} <span className="text-xs text-muted-foreground">· {t("verdict.noteRequired")}</span>
          </span>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} rows={3} required
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary" />
        </label>
      )}
      {/* half-saved and the RCA not refetched yet: retry the rest, never resubmit the saved verdict */}
      {retryButton ?? (
        <button
          onClick={submit}
          disabled={!choice || (noteRequired(choice) && !note.trim()) || busy}
          className="px-4 py-2 text-sm font-medium rounded-lg border border-primary/40 text-primary hover:bg-primary/10 disabled:opacity-50 transition-colors"
        >
          {t("verdict.submit")}
        </button>
      )}
      {errorLine}
    </div>
  );
}
