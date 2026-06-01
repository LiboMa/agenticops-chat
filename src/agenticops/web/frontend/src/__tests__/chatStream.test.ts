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

    expect(chatStream.getSnapshot("sess-E").error).toBe("boom");
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
