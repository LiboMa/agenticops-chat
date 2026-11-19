import { describe, it, expect } from "vitest";
import { choiceOf, isNewPath, shellFor, shellKey } from "@/lib/shellChoice";

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
