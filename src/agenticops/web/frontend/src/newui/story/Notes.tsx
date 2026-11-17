import { useState } from "react";
import type { PipelineEvent } from "@/api/types";
import { useAuth } from "@/hooks/useAuth";
import { useAddIssueNote } from "@/hooks/useIssueTimeline";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { shouldSend } from "@/lib/composerKeys";
import { errorText } from "../decide/briefs/briefContext";
import { useNfT } from "../i18n";
import { whoText } from "../lib/activity";
import { notesOf } from "../lib/story";
import { utcStamp } from "../lib/time";

const MAX = 8000;      // services/issue_notes.MAX_NOTE_CHARS

/** What people wrote on the issue, oldest first, and the box to add one. A note is kept as written: it is never
 *  edited or deleted, and it does not move the issue. */
export function Notes({ issueId, events, canNote, now }: { issueId: number; events: PipelineEvent[] | undefined; canNote: boolean; now: number }) {
  const t = useNfT();
  const { user } = useAuth();
  const add = useAddIssueNote(issueId);
  const coarse = useMediaQuery("(pointer: coarse)");      // on a touch screen Enter is a new line; the button sends
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const notes = notesOf(events);
  const send = async () => {
    const text = value.trim();
    if (!text || add.isPending) return;
    setError(null);
    try { await add.mutateAsync(text); setValue(""); }
    catch (e) { setError(t("note.failed", { msg: errorText(e) })); }
  };
  return (
    <>
      <h2>{t("story.notes")}</h2>
      {notes.length > 0 ? (
        <ul className="notes">
          {notes.map((n) => <li key={n.id}>{n.text}<small>{t("note.cite", { by: whoText(n.by, user?.email, t), t: utcStamp(n.at, now) })}</small></li>)}
        </ul>
      ) : <p className="note" style={{ margin: 0 }}>{t("note.none")}</p>}
      {canNote && (
        <form className="note-add" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <textarea className="field" rows={2} value={value} maxLength={MAX} placeholder={t("note.ph")} aria-label={t("note.label")}
                    onChange={(e) => setValue(e.target.value)}
                    onKeyDown={(e) => { if (shouldSend(e.nativeEvent, coarse)) { e.preventDefault(); void send(); } }} />
          <button type="submit" className="btn sm" disabled={add.isPending || !value.trim()}><span className="t">{t("note.add")}</span></button>
        </form>
      )}
      {error && <p className="note err" role="alert">{error}</p>}
      <p className="note">{t("note.rule")}</p>
    </>
  );
}
