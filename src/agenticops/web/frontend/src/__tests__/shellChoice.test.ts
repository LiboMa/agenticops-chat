import { describe, it, expect } from "vitest";
import { TO_CLASSIC, choiceOf, isNewPath, leavesNew, shellFor, shellKey } from "@/lib/shellChoice";

describe("shellChoice — which interface a person uses (per user, in this browser)", () => {
  it("only the stored word «new» is the new interface; anything else is the classic one", () => {
    expect(choiceOf("new")).toBe("new");
    for (const junk of [null, undefined, "", "classic", "NEW", "new ", "1", "true", 1, {}, []]) expect(choiceOf(junk)).toBe("classic");
  });
  it("the choice is kept per user", () => {
    expect(shellKey(7)).toBe("aiops-shell:7");
    expect(shellKey(null)).toBe("aiops-shell:anon");
    expect(shellKey(7)).not.toBe(shellKey(8));
  });
});

describe("shellFor — the shell that draws an address", () => {
  it("any /app/new address is the new shell, whatever was chosen", () => {
    for (const p of ["/app/new", "/app/new/", "/app/new/decide", "/app/new/decide/I12", "/app/new/story/C3", "/app/new/world", "/app/new/nope"]) {
      expect(isNewPath(p)).toBe(true);
      expect(shellFor(p, "classic")).toBe("new");
      expect(shellFor(p, "new")).toBe("new");
    }
  });
  it("every other address follows the choice", () => {
    for (const p of ["/app", "/app/", "/app/reports", "/app/issues/12", "/app/settings", "/app/newer", "/app/news/1", "/app/chat/new"]) {
      expect(isNewPath(p)).toBe(false);
      expect(shellFor(p, "classic")).toBe("classic");
      expect(shellFor(p, "new")).toBe("new");
    }
  });
});

describe("the frame a person is in is the frame they stay in (MVP-2.9.0 N27, review)", () => {
  it("someone in NewUI by its address alone — a bookmark, a shared link, nothing stored — stays in its frame on the next page", () => {
    // «pages → reports» opened the classic shell under their feet, and a decision inside its undo window was sent
    expect(shellFor("/app/reports", "classic", "new")).toBe("new");
    expect(shellFor("/app/settings", "classic", "new")).toBe("new");
  });
  it("«back to classic» is the way out", () => {
    expect(shellFor("/app", "classic", "new", true)).toBe("classic");
    expect(shellFor("/app/chat", "classic", "classic")).toBe("classic");      // … and it stays out
    expect(leavesNew(TO_CLASSIC)).toBe(true);
    expect(leavesNew(null)).toBe(false);
    expect(leavesNew({ classic: true })).toBe(false);                         // the classic exit of one section is another thing
    expect(leavesNew({ fresh: true })).toBe(false);
  });
  it("NewUI's own addresses are its frame whatever led there", () => {
    expect(shellFor("/app/new/decide", "classic", "classic", true)).toBe("new");
  });
  it("the first page of a tab is the stored choice, as before", () => {
    expect(shellFor("/app/reports", "classic", null)).toBe("classic");
    expect(shellFor("/app/reports", "new", null)).toBe("new");
    expect(shellFor("/app/reports", "classic")).toBe("classic");
    expect(shellFor("/app/reports", "new", "classic")).toBe("new");           // the choice was made on the classic side
  });
});
