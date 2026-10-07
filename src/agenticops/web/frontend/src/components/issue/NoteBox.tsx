import { useState } from "react";
import { useAddIssueNote } from "@/hooks/useIssueTimeline";

export const NOTE_MAX = 8000;

/** Add a note to the issue's activity (MVP-2.7.0 S4): append-only, as you, kept exactly as written. */
export function NoteBox({ issueId, t }: { issueId: number; t: (k: string) => string }) {
  const [text, setText] = useState("");
  const add = useAddIssueNote(issueId);
  const empty = !text.trim();
  const save = () => {
    if (empty || add.isPending) return;
    add.mutate(text, { onSuccess: () => setText("") });
  };
  return (
    <div className="space-y-1.5">
      <label htmlFor={`note-${issueId}`} className="sr-only">{t("notes.label")}</label>
      <textarea id={`note-${issueId}`} value={text} maxLength={NOTE_MAX} rows={3}
                onChange={(e) => { setText(e.target.value); if (add.error) add.reset(); }}
                placeholder={t("notes.placeholder")}
                className="w-full resize-y rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground placeholder:text-muted-foreground" />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">{t("notes.hint")}</span>
        <button type="button" onClick={save} disabled={empty || add.isPending}
                className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
          {add.isPending ? t("notes.saving") : t("notes.save")}
        </button>
      </div>
      {add.error && <p role="alert" className="text-xs text-red-600 dark:text-red-400">{t("notes.failed").replace("{error}", add.error.message)}</p>}
    </div>
  );
}
