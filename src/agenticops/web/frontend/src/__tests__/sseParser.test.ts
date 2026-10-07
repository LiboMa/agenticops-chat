import { describe, it, expect } from "vitest";
import { SseParser } from "@/lib/sseParser";

describe("SseParser (MVP-2.7.0 S5)", () => {
  it("emits one frame per blank line", () => {
    expect(new SseParser().push('event: text\ndata: {"token":"a"}\n\n')).toEqual([{ event: "text", data: '{"token":"a"}' }]);
  });
  it("treats CRLF and CR as line ends", () => {
    expect(new SseParser().push('event: text\r\ndata: x\r\n\r\n')).toEqual([{ event: "text", data: "x" }]);
    expect(new SseParser().push("event: text\rdata: y\r\r\n")).toEqual([{ event: "text", data: "y" }]);
  });
  it("a CRLF split across chunks is one line end", () => {
    const p = new SseParser();
    expect(p.push("data: a\r")).toEqual([]);
    expect(p.push("\n\r\n")).toEqual([{ event: "message", data: "a" }]);
  });
  it("a frame split across chunks is emitted only once it is complete", () => {
    const p = new SseParser();
    expect(p.push("event: te")).toEqual([]);
    expect(p.push("xt\ndata: {\"tok")).toEqual([]);
    expect(p.push("en\":\"a\"}\n\n")).toEqual([{ event: "text", data: '{"token":"a"}' }]);
  });
  it("joins multi-line data with newlines; the default event is message", () => {
    expect(new SseParser().push("data: a\ndata: b\n\n")).toEqual([{ event: "message", data: "a\nb" }]);
  });
  it("skips comments and blank frames", () => {
    expect(new SseParser().push(": ping\n\n\n\n")).toEqual([]);
  });
  it("returns unknown events as they are (the caller ignores them)", () => {
    expect(new SseParser().push("event: brand_new\ndata: {}\n\n")).toEqual([{ event: "brand_new", data: "{}" }]);
  });
  it("flush() returns a trailing frame that never got its blank line", () => {
    const p = new SseParser();
    p.push("event: done\ndata: {}");
    expect(p.flush()).toEqual([{ event: "done", data: "{}" }]);
  });
  it("an event line without data does not leak into the next frame", () => {
    const p = new SseParser();
    expect(p.push("event: lonely\n\ndata: z\n\n")).toEqual([{ event: "message", data: "z" }]);
  });
});
