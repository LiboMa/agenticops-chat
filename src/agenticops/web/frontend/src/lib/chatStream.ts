import { getAuthToken } from "@/api/client";
import { SseParser } from "@/lib/sseParser";

export interface ToolCall {
  name: string;
  status: "running" | "done";
  call_id?: string;
  outcome?: "ok" | "error" | "unknown"; // S5: from the tool's result, never assumed from its name
}

/** Why a send did not finish (MVP-2.7.0 S5): the server's error codes, its 409 codes, or the client's own. */
export type StreamErrorCode = "throttled" | "model_unavailable" | "context_too_long" | "internal"
  | "session_busy" | "duplicate_in_flight" | "network" | "http";

export interface StreamState {
  streaming: boolean;
  content: string;
  toolCalls: ToolCall[];
  tokenMetrics: { input: number; output: number } | null;
  error: { code: StreamErrorCode; message: string } | null;
}

const SERVER_CODES = new Set<string>(["throttled", "model_unavailable", "context_too_long", "internal",
  "session_busy", "duplicate_in_flight"]);
const asCode = (c: unknown, fallback: StreamErrorCode): StreamErrorCode =>
  typeof c === "string" && SERVER_CODES.has(c) ? (c as StreamErrorCode) : fallback;

/** Callbacks the store fires on lifecycle events (wired to TanStack cache by hooks). */
export interface StreamCallbacks {
  /** Fired once per completed assistant turn with the final text + tools + tokens. */
  onDone?: (
    sessionId: string,
    payload: { content: string; toolCalls: ToolCall[]; tokenMetrics: { input: number; output: number } | null; suggestions?: string[] },
  ) => void;
  /** Fired when the backend auto-renames the session. */
  onRenamed?: (sessionId: string, name: string) => void;
  /** Fired after every send, however it ended: the history is reloaded from the server, so an interrupted or
   *  failed reply shows as the server stored it (no automatic retry — S5). */
  onSettled?: (sessionId: string) => void;
}

const EMPTY: StreamState = {
  streaming: false,
  content: "",
  toolCalls: [],
  tokenMetrics: null,
  error: null,
};

const TOKEN_FLUSH_MS = 60;

class ChatStreamStore {
  private states = new Map<string, StreamState>();
  private controllers = new Map<string, AbortController>();
  private subscribers = new Map<string, Set<() => void>>();
  private activeSubscribers = new Set<() => void>();
  private callbacks: StreamCallbacks = {};

  setCallbacks(cb: StreamCallbacks) {
    this.callbacks = cb;
  }

  getSnapshot(sessionId: string | null): StreamState {
    if (!sessionId) return EMPTY;
    return this.states.get(sessionId) ?? EMPTY;
  }

  /** session ids currently streaming (for the flyout indicator). */
  activeSessions(): string[] {
    const out: string[] = [];
    this.states.forEach((s, id) => {
      if (s.streaming) out.push(id);
    });
    return out;
  }

  subscribe(sessionId: string, cb: () => void): () => void {
    let set = this.subscribers.get(sessionId);
    if (!set) {
      set = new Set();
      this.subscribers.set(sessionId, set);
    }
    set.add(cb);
    return () => set!.delete(cb);
  }

  subscribeActive(cb: () => void): () => void {
    this.activeSubscribers.add(cb);
    return () => this.activeSubscribers.delete(cb);
  }

  private set(sessionId: string, patch: Partial<StreamState>) {
    const prev = this.states.get(sessionId) ?? EMPTY;
    this.states.set(sessionId, { ...prev, ...patch });
    this.subscribers.get(sessionId)?.forEach((cb) => cb());
    this.activeSubscribers.forEach((cb) => cb());
  }

  isStreaming(sessionId: string): boolean {
    return this.states.get(sessionId)?.streaming ?? false;
  }

  cancel(sessionId: string) {
    this.controllers.get(sessionId)?.abort();
  }

  async send(sessionId: string, content: string, files?: File[], clientMessageId: string = crypto.randomUUID()) {
    if (this.isStreaming(sessionId)) return;

    this.set(sessionId, { streaming: true, content: "", toolCalls: [], tokenMetrics: null, error: null });

    const controller = new AbortController();
    this.controllers.set(sessionId, controller);

    // Completed-turn payload, handed to the cache layer in `finally` AFTER the
    // live slice is cleared (prevents a flash where both the streaming trailer
    // and the persisted row render at once).
    let donePayload: { content: string; toolCalls: ToolCall[]; tokenMetrics: { input: number; output: number } | null; suggestions?: string[] } | null = null;
    let doneSuggestions: string[] = [];

    // Token coalescing buffer (avoids O(n^2) markdown re-parse downstream).
    let pendingText = "";
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      if (pendingText) {
        const cur = this.states.get(sessionId) ?? EMPTY;
        this.set(sessionId, { content: cur.content + pendingText });
        pendingText = "";
      }
      flushTimer = null;
    };

    try {
      const authHeaders: Record<string, string> = {};
      const token = getAuthToken();
      if (token) authHeaders["Authorization"] = `Bearer ${token}`;

      let res: Response;
      if (files && files.length > 0) {
        const formData = new FormData();
        formData.append("content", content);
        formData.append("client_message_id", clientMessageId);
        files.forEach((f) => formData.append("file", f));
        res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: "POST", headers: authHeaders, body: formData, signal: controller.signal,
        });
      } else {
        const body: Record<string, string> = { content, client_message_id: clientMessageId };
        res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
      }

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({ detail: res.statusText }));
        const d = errBody?.detail;
        const message = typeof d === "string" ? d : typeof d?.detail === "string" ? d.detail : res.statusText;
        this.set(sessionId, { error: { code: asCode(d?.code, "http"), message } });
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      const parser = new SseParser();
      const handle = (frames: { event: string; data: string }[]) => {
        for (const frame of frames) {
          if (!frame.data) continue;
          try {
            const data = JSON.parse(frame.data);
            switch (frame.event) {
              case "text":
                if (data.token) {
                  pendingText += data.token;
                  if (!flushTimer) flushTimer = setTimeout(flush, TOKEN_FLUSH_MS);
                }
                break;
              case "tool_start":
                if (data.name) {
                  const cur = this.states.get(sessionId) ?? EMPTY;
                  this.set(sessionId, { toolCalls: [...cur.toolCalls,
                    { name: data.name, status: "running", call_id: data.call_id ?? undefined }] });
                }
                break;
              case "tool_end":
                if (data.name) {
                  const cur = this.states.get(sessionId) ?? EMPTY;
                  // by call id when the server sent one (two calls of one tool are two rows), else by name
                  const same = (t: ToolCall) => (data.call_id ? t.call_id === data.call_id : t.name === data.name);
                  this.set(sessionId, {
                    toolCalls: cur.toolCalls.map((t) =>
                      same(t) ? { ...t, status: "done" as const, outcome: data.outcome ?? t.outcome } : t),
                  });
                }
                break;
              case "session_renamed":
                if (data.name) this.callbacks.onRenamed?.(sessionId, data.name);
                break;
              case "done":
                this.set(sessionId, {
                  tokenMetrics: { input: data.input_tokens ?? 0, output: data.output_tokens ?? 0 },
                });
                doneSuggestions = Array.isArray(data.suggestions) ? data.suggestions : [];
                break;
              case "error":
                this.set(sessionId, { error: { code: asCode(data.code, "internal"), message: data.message ?? "" } });
                break;
            }
          } catch {
            // ignore malformed JSON
          }
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        handle(parser.push(decoder.decode(value, { stream: true })));
      }
      handle(parser.push(decoder.decode()));
      handle(parser.flush());

      if (flushTimer) clearTimeout(flushTimer);
      flush();

      // Capture the completed turn; fired in `finally` after the slice clears.
      const final = this.states.get(sessionId) ?? EMPTY;
      if (!final.error) {
        donePayload = {
          content: final.content.split("<<SUGGEST>>")[0].trimEnd(),
          toolCalls: final.toolCalls,
          tokenMetrics: final.tokenMetrics,
          suggestions: doneSuggestions,
        };
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        this.set(sessionId, { error: { code: "network", message: err.message } });
      }
    } finally {
      if (flushTimer) clearTimeout(flushTimer);
      this.controllers.delete(sessionId);
      // Clear the live slice FIRST so the streaming trailer disappears, THEN
      // hand the completed turn to the cache layer (no double-render flash).
      this.set(sessionId, { streaming: false, content: "", toolCalls: [], tokenMetrics: null });
      if (donePayload) this.callbacks.onDone?.(sessionId, donePayload);
      this.callbacks.onSettled?.(sessionId);
    }
  }
}

export const chatStream = new ChatStreamStore();
