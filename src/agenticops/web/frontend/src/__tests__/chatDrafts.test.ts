import { describe, it, expect } from "vitest";
import { draftKey, loadDraft, saveDraft, sessionQueues } from "@/lib/chatDrafts";
import { UploadQueue } from "@/lib/attachmentUpload";

const mem = () => {
  const store: Record<string, string> = {};
  return { store, getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => { store[k] = v; },
           removeItem: (k: string) => { delete store[k]; } };
};

describe("chat drafts (MVP-2.7.0 S5)", () => {
  it("are keyed by installation, user and session", () => {
    expect(draftKey("dep1", 7, "s1")).toBe("aiops-chat-draft:dep1:7:s1");
    expect(draftKey(undefined, null, "new")).toBe("aiops-chat-draft:local:anon:new");
    const keys = new Set([draftKey("a", 1, "s"), draftKey("b", 1, "s"), draftKey("a", 2, "s"), draftKey("a", 1, "t")]);
    expect(keys.size).toBe(4);
  });
  it("round-trip; an empty draft removes the key", () => {
    const s = mem();
    saveDraft(s, "k", { text: "half a thought", attachmentIds: ["a1"] });
    expect(loadDraft(s, "k")).toEqual({ text: "half a thought", attachmentIds: ["a1"] });
    saveDraft(s, "k", { text: "", attachmentIds: [] });
    expect(s.store).toEqual({});
  });
  it("whitespace-only text with no files counts as empty", () => {
    const s = mem();
    saveDraft(s, "k", { text: "   ", attachmentIds: [] });
    expect(s.store).toEqual({});
  });
  it("a corrupt or foreign value loads as an empty draft and never throws", () => {
    const s = mem();
    for (const raw of ["{not json", "42", "null", '{"text": 5, "attachmentIds": "x"}']) {
      s.store.k = raw;
      expect(loadDraft(s, "k")).toEqual({ text: "", attachmentIds: [] });
    }
  });
  it("draft keeps attachment ids (strings only); a pre-2026-11-07 draft's file names are dropped", () => {
    const s = mem();
    s.store.k = JSON.stringify({ text: "x", attachmentIds: ["a1", 3, { id: "b" }, "c2"] });
    expect(loadDraft(s, "k").attachmentIds).toEqual(["a1", "c2"]);
    s.store.k = JSON.stringify({ text: "old", unsentFiles: ["a.png"] });
    expect(loadDraft(s, "k")).toEqual({ text: "old", attachmentIds: [] });
  });
  it("an attachment-only draft is kept", () => {
    const s = mem();
    saveDraft(s, "k", { text: "", attachmentIds: ["a1"] });
    expect(loadDraft(s, "k")).toEqual({ text: "", attachmentIds: ["a1"] });
  });
  it("a storage that throws (private mode) is survived", () => {
    const bad = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); },
                  removeItem: () => { throw new Error("denied"); } };
    expect(loadDraft(bad, "k")).toEqual({ text: "", attachmentIds: [] });
    expect(() => saveDraft(bad, "k", { text: "x", attachmentIds: [] })).not.toThrow();
  });
  it("each chat keeps one upload queue in memory (uploads go on across in-app navigation)", () => {
    const make = () => new UploadQueue({ onChange: () => {} });
    const a = sessionQueues.get("s-a", make);
    expect(sessionQueues.get("s-a", make)).toBe(a);
    expect(sessionQueues.get("s-b", make)).not.toBe(a);
    sessionQueues.drop("s-a");
    expect(sessionQueues.get("s-a", make)).not.toBe(a);
  });
});
