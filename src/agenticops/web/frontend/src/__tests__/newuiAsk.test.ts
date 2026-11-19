import { describe, expect, it } from "vitest";
import { contextRefFromQuery } from "@/lib/contextRef";
import type { Draft } from "@/lib/chatDrafts";
import { askPath, withAsk } from "@/newui/lib/ask";

describe("askPath — «ask the agent about this item» opens a conversation tied to it", () => {
  it("an issue and a change, in the address the chat page already reads", () => {
    expect(askPath("I12")).toBe("/app/chat?ref=I12");
    expect(askPath("C3")).toBe("/app/chat?ref=C3");
    // the chat page's own reader agrees on what was meant
    const search = (item: string) => askPath(item)!.slice("/app/chat".length);          // "?ref=I12"
    expect(contextRefFromQuery(search("I12"))).toEqual({ kind: "issue", id: 12 });
    expect(contextRefFromQuery(search("C3"))).toEqual({ kind: "change", id: 3 });
  });
  it("nothing for what is not an item", () => {
    for (const bad of ["", "12", "I", "I0", "X12", "I12/x", "I12?ref=C3", "I-1", "i12"]) expect(askPath(bad)).toBeNull();
  });
});

describe("withAsk — a sentence from the command bar, in the new conversation's draft", () => {
  const draft = (text: string, attachmentIds: string[] = []): Draft => ({ text, attachmentIds });
  it("an empty draft becomes the sentence", () => {
    expect(withAsk(draft(""), "why is the web tier slow?")).toEqual(draft("why is the web tier slow?"));
    expect(withAsk(draft("   \n"), "why?")).toEqual(draft("why?"));
  });
  it("what the person had already written there is kept, the sentence after it", () => {
    expect(withAsk(draft("first thought\n"), "second thought")).toEqual(draft("first thought\n\nsecond thought"));
  });
  it("attachments already on the draft stay", () => {
    expect(withAsk(draft("", ["a1", "a2"]), "look at these")).toEqual(draft("look at these", ["a1", "a2"]));
  });
  it("the sentence is trimmed and kept to what one message may hold", () => {
    expect(withAsk(draft(""), "  hello  ").text).toBe("hello");
    expect(withAsk(draft(""), "x".repeat(20000)).text).toHaveLength(10000);
    expect(withAsk(draft("y".repeat(9990)), "x".repeat(100)).text).toHaveLength(10000);
  });
  it("an empty sentence changes nothing", () => {
    expect(withAsk(draft("kept"), "   ")).toEqual(draft("kept"));
  });
});
