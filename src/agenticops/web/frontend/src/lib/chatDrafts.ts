/**
 * Chat drafts (MVP-2.7.0 S5): the text you were writing survives navigation, a language switch and a refresh —
 * keyed by installation, user and session, so it never shows up in someone else's chat or another chat. Files are
 * kept in memory per session (they survive in-app navigation, not a refresh); a draft remembers only their names,
 * so after a refresh the composer can say which ones must be selected again. Attachments are never replayed.
 */
export interface Draft { text: string; unsentFiles: string[] }

const EMPTY: Draft = { text: "", unsentFiles: [] };

export function draftKey(deploymentId: string | undefined, userId: number | null | undefined, sessionId: string): string {
  return `aiops-chat-draft:${deploymentId || "local"}:${userId ?? "anon"}:${sessionId}`;
}

export function loadDraft(storage: Pick<Storage, "getItem">, key: string): Draft {
  try {
    const v = JSON.parse(storage.getItem(key) ?? "null");
    if (!v || typeof v !== "object") return { ...EMPTY };
    return {
      text: typeof v.text === "string" ? v.text : "",
      unsentFiles: Array.isArray(v.unsentFiles) ? v.unsentFiles.filter((n: unknown): n is string => typeof n === "string") : [],
    };
  } catch {
    return { ...EMPTY };
  }
}

export function saveDraft(storage: Pick<Storage, "setItem" | "removeItem">, key: string, d: Draft): void {
  try {
    if (!d.text.trim() && d.unsentFiles.length === 0) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify({ text: d.text, unsentFiles: d.unsentFiles }));
  } catch { /* private mode / quota: the draft lives as long as the page */ }
}

const files = new Map<string, File[]>();
export const sessionFiles = {
  get: (sid: string): File[] => files.get(sid) ?? [],
  set: (sid: string, f: File[]) => { if (f.length) files.set(sid, f); else files.delete(sid); },
  clear: (sid: string) => { files.delete(sid); },
};
