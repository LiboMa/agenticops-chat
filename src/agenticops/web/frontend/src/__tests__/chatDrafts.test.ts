import { describe, it, expect } from "vitest";
import { draftKey, loadDraft, saveDraft, sessionFiles } from "@/lib/chatDrafts";

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
    saveDraft(s, "k", { text: "half a thought", unsentFiles: ["a.png"] });
    expect(loadDraft(s, "k")).toEqual({ text: "half a thought", unsentFiles: ["a.png"] });
    saveDraft(s, "k", { text: "", unsentFiles: [] });
    expect(s.store).toEqual({});
  });
  it("whitespace-only text with no files counts as empty", () => {
    const s = mem();
    saveDraft(s, "k", { text: "   ", unsentFiles: [] });
    expect(s.store).toEqual({});
  });
  it("a corrupt or foreign value loads as an empty draft and never throws", () => {
    const s = mem();
    for (const raw of ["{not json", "42", "null", '{"text": 5, "unsentFiles": "x"}']) {
      s.store.k = raw;
      expect(loadDraft(s, "k")).toEqual({ text: "", unsentFiles: [] });
    }
  });
  it("unsent files are names only", () => {
    const s = mem();
    s.store.k = JSON.stringify({ text: "x", unsentFiles: ["a.png", 3, { name: "b" }, "c.pdf"] });
    expect(loadDraft(s, "k").unsentFiles).toEqual(["a.png", "c.pdf"]);
  });
  it("a storage that throws (private mode) is survived", () => {
    const bad = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); },
                  removeItem: () => { throw new Error("denied"); } };
    expect(loadDraft(bad, "k")).toEqual({ text: "", unsentFiles: [] });
    expect(() => saveDraft(bad, "k", { text: "x", unsentFiles: [] })).not.toThrow();
  });
  it("files are kept per session, in memory", () => {
    const a = [new File(["1"], "a.png")];
    sessionFiles.set("s-a", a);
    expect(sessionFiles.get("s-a")).toBe(a);
    expect(sessionFiles.get("s-b")).toEqual([]);
    sessionFiles.clear("s-a");
    expect(sessionFiles.get("s-a")).toEqual([]);
  });
});
