/**
 * chatStream store: concurrent-session isolation + lifecycle.
 *
 * We stub global.fetch to return a ReadableStream of SSE bytes so the store's
 * parse loop runs without a server.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { chatStream } from "@/lib/chatStream";

// jsdom/node: provide a minimal localStorage so getAuthToken() works.
beforeEach(() => {
  (globalThis as any).localStorage = {
    store: {} as Record<string, string>,
    getItem(k: string) { return this.store[k] ?? null; },
    setItem(k: string, v: string) { this.store[k] = v; },
    removeItem(k: string) { delete this.store[k]; },
  };
});

/** Build a Response whose body streams the given SSE lines. */
function sseResponse(lines: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const l of lines) controller.enqueue(encoder.encode(l));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const SSE_HELLO = [
  'event: text\ndata: {"token":"Hello"}\n\n',
  'event: text\ndata: {"token":" world"}\n\n',
  'event: done\ndata: {"input_tokens":3,"output_tokens":2}\n\n',
];

describe("chatStream", () => {
  it("streams tokens and fires onDone with final content", async () => {
    const done: any[] = [];
    chatStream.setCallbacks({ onDone: (sid, p) => done.push({ sid, ...p }) });
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse(SSE_HELLO)));

    await chatStream.send("sess-A", "hi");

    expect(done).toHaveLength(1);
    expect(done[0].sid).toBe("sess-A");
    expect(done[0].content).toBe("Hello world");
    expect(done[0].tokenMetrics).toEqual({ input: 3, output: 2 });
    // live slice cleared after completion
    expect(chatStream.getSnapshot("sess-A").streaming).toBe(false);
    expect(chatStream.getSnapshot("sess-A").content).toBe("");
  });

  it("keeps two sessions isolated when streamed concurrently", async () => {
    const done: Record<string, string> = {};
    chatStream.setCallbacks({ onDone: (sid, p) => { done[sid] = p.content; } });

    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("sess-X")) {
        return sseResponse(['event: text\ndata: {"token":"X1"}\n\n',
                            'event: done\ndata: {"input_tokens":0,"output_tokens":0}\n\n']);
      }
      return sseResponse(['event: text\ndata: {"token":"Y1"}\n\n',
                          'event: done\ndata: {"input_tokens":0,"output_tokens":0}\n\n']);
    }));

    await Promise.all([chatStream.send("sess-X", "hi"), chatStream.send("sess-Y", "yo")]);

    expect(done["sess-X"]).toBe("X1");
    expect(done["sess-Y"]).toBe("Y1");
  });

  it("records an error on the session slice and does not fire onDone", async () => {
    const done: any[] = [];
    chatStream.setCallbacks({ onDone: () => done.push(1) });
    vi.stubGlobal("fetch", vi.fn(async () =>
      sseResponse(['event: error\ndata: {"message":"boom"}\n\n'])));

    await chatStream.send("sess-E", "hi");

    expect(chatStream.getSnapshot("sess-E").error).toEqual({ code: "internal", message: "boom" });
    expect(done).toHaveLength(0);
  });

  it("reports active sessions while streaming", async () => {
    let activeDuringStream: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async () => {
      // capture active set synchronously after streaming flips true
      activeDuringStream = chatStream.activeSessions();
      return sseResponse(['event: done\ndata: {"input_tokens":0,"output_tokens":0}\n\n']);
    }));
    await chatStream.send("sess-ACT", "hi");
    expect(activeDuringStream).toContain("sess-ACT");
    expect(chatStream.activeSessions()).not.toContain("sess-ACT"); // cleared after done
  });
});

/** A Response whose body streams raw byte chunks (a UTF-8 character can be split across two). */
function byteResponse(chunks: Uint8Array[], status = 200): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) { for (const c of chunks) controller.enqueue(c); controller.close(); },
  });
  return new Response(stream, { status, headers: { "Content-Type": "text/event-stream" } });
}

describe("chatStream — S5 stream client", () => {
  it("a UTF-8 character split across two chunks arrives whole", async () => {
    const done: string[] = [];
    chatStream.setCallbacks({ onDone: (_s, p) => done.push(p.content) });
    const bytes = new TextEncoder().encode('event: text\ndata: {"token":"你好"}\n\nevent: done\ndata: {}\n\n');
    const cut = bytes.indexOf(0xe4) + 1;  // inside 你
    vi.stubGlobal("fetch", vi.fn(async () => byteResponse([bytes.slice(0, cut), bytes.slice(cut)])));
    await chatStream.send("s5-utf8", "hi");
    expect(done).toEqual(["你好"]);
  });

  it("every send carries a client_message_id (a UUID)", async () => {
    const bodies: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)));
      return sseResponse(['event: done\ndata: {}\n\n']);
    }));
    await chatStream.send("s5-id", "hi");
    expect(bodies[0].client_message_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    await chatStream.send("s5-id", "hi", undefined, "11111111-2222-3333-4444-555555555555");
    expect(bodies[1].client_message_id).toBe("11111111-2222-3333-4444-555555555555");
  });

  it("a 409 says its code, and the history is reloaded", async () => {
    const settled: string[] = [];
    chatStream.setCallbacks({ onSettled: (sid) => settled.push(sid) });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: { detail: "busy", code: "session_busy" } }), { status: 409 })));
    await chatStream.send("s5-busy", "hi");
    expect(chatStream.getSnapshot("s5-busy").error?.code).toBe("session_busy");
    expect(settled).toEqual(["s5-busy"]);
  });

  it("an error frame keeps its code", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse(['event: error\ndata: {"code":"throttled","message":"m"}\n\n'])));
    await chatStream.send("s5-err", "hi");
    expect(chatStream.getSnapshot("s5-err").error).toEqual({ code: "throttled", message: "m" });
  });

  it("a network failure is 'network', and the history is reloaded", async () => {
    const settled: string[] = [];
    chatStream.setCallbacks({ onSettled: (sid) => settled.push(sid) });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await chatStream.send("s5-net", "hi");
    expect(chatStream.getSnapshot("s5-net").error?.code).toBe("network");
    expect(settled).toEqual(["s5-net"]);
  });

  it("an abort is no error, and the history is reloaded (the server stored what it had)", async () => {
    const settled: string[] = [];
    chatStream.setCallbacks({ onSettled: (sid) => settled.push(sid) });
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init: RequestInit) => new Promise((_res, rej) => {
      init.signal?.addEventListener("abort", () => rej(Object.assign(new Error("aborted"), { name: "AbortError" })));
    })));
    const p = chatStream.send("s5-abort", "hi");
    chatStream.cancel("s5-abort");
    await p;
    expect(chatStream.getSnapshot("s5-abort").error).toBeNull();
    expect(settled).toEqual(["s5-abort"]);
  });
});
