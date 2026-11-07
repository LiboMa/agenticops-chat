/**
 * Chat drafts (MVP-2.7.0 S5; attachments 2026-11-07): the text you were writing survives navigation, a language
 * switch and a refresh — keyed by installation, user and session, so it never shows up in someone else's chat or
 * another chat. Attachments are uploaded as soon as they are attached; a draft keeps their server ids, so after a
 * refresh the composer fetches them back (the server keeps an unsent upload for staged_ttl_hours). Each chat's
 * upload queue lives in memory, so uploads go on while you look at another page.
 */
import type { UploadQueue } from "@/lib/attachmentUpload";

export interface Draft { text: string; attachmentIds: string[] }

const EMPTY: Draft = { text: "", attachmentIds: [] };

export function draftKey(deploymentId: string | undefined, userId: number | null | undefined, sessionId: string): string {
  return `aiops-chat-draft:${deploymentId || "local"}:${userId ?? "anon"}:${sessionId}`;
}

export function loadDraft(storage: Pick<Storage, "getItem">, key: string): Draft {
  try {
    const v = JSON.parse(storage.getItem(key) ?? "null");
    if (!v || typeof v !== "object") return { ...EMPTY, attachmentIds: [] };
    return {
      text: typeof v.text === "string" ? v.text : "",
      attachmentIds: Array.isArray(v.attachmentIds)
        ? v.attachmentIds.filter((n: unknown): n is string => typeof n === "string") : [],
    };
  } catch {
    return { ...EMPTY, attachmentIds: [] };
  }
}

export function saveDraft(storage: Pick<Storage, "setItem" | "removeItem">, key: string, d: Draft): void {
  try {
    if (!d.text.trim() && d.attachmentIds.length === 0) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify({ text: d.text, attachmentIds: d.attachmentIds }));
  } catch { /* private mode / quota: the draft lives as long as the page */ }
}

const queues = new Map<string, UploadQueue>();
export const sessionQueues = {
  get: (sid: string, make: () => UploadQueue): UploadQueue => {
    let q = queues.get(sid);
    if (!q) {
      q = make();
      queues.set(sid, q);
    }
    return q;
  },
  drop: (sid: string) => { queues.delete(sid); },
};
