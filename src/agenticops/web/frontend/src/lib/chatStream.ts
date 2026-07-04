import { getAuthToken } from "@/api/client";

export interface ToolCall {
  name: string;
  status: "running" | "done";
}

export interface StreamState {
  streaming: boolean;
  content: string;
  toolCalls: ToolCall[];
  tokenMetrics: { input: number; output: number } | null;
  error: string | null;
}

/** Callbacks the store fires on lifecycle events (wired to TanStack cache by hooks). */
export interface StreamCallbacks {
  /** Fired once per completed assistant turn with the final text + tools + tokens. */
  onDone?: (
    sessionId: string,
    payload: { content: string; toolCalls: ToolCall[]; tokenMetrics: { input: number; output: number } | null },
  ) => void;
  /** Fired when the backend auto-renames the session. */
  onRenamed?: (sessionId: string, name: string) => void;
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

  async send(sessionId: string, content: string, files?: File[]) {
    if (this.isStreaming(sessionId)) return;

    this.set(sessionId, { streaming: true, content: "", toolCalls: [], tokenMetrics: null, error: null });

    const controller = new AbortController();
    this.controllers.set(sessionId, controller);

    // Completed-turn payload, handed to the cache layer in `finally` AFTER the
    // live slice is cleared (prevents a flash where both the streaming trailer
    // and the persisted row render at once).
    let donePayload: { content: string; toolCalls: ToolCall[]; tokenMetrics: { input: number; output: number } | null } | null = null;

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
        files.forEach((f) => formData.append("file", f));
        res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: "POST", headers: authHeaders, body: formData, signal: controller.signal,
        });
      } else {
        const body: Record<string, string> = { content };
        res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
      }

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errBody.detail ?? res.statusText);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
            continue;
          }
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;

          try {
            const data = JSON.parse(raw);
            switch (currentEvent) {
              case "text":
                if (data.token) {
                  pendingText += data.token;
                  if (!flushTimer) flushTimer = setTimeout(flush, TOKEN_FLUSH_MS);
                }
                break;
              case "tool_start":
                if (data.name) {
                  const cur = this.states.get(sessionId) ?? EMPTY;
                  this.set(sessionId, { toolCalls: [...cur.toolCalls, { name: data.name, status: "running" }] });
                }
                break;
              case "tool_end":
                if (data.name) {
                  const cur = this.states.get(sessionId) ?? EMPTY;
                  this.set(sessionId, {
                    toolCalls: cur.toolCalls.map((t) =>
                      t.name === data.name ? { ...t, status: "done" as const } : t),
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
                break;
              case "error":
                this.set(sessionId, { error: data.message ?? "Unknown error" });
                break;
            }
          } catch {
            // ignore malformed JSON
          }
        }
      }

      if (flushTimer) clearTimeout(flushTimer);
      flush();

      // Capture the completed turn; fired in `finally` after the slice clears.
      const final = this.states.get(sessionId) ?? EMPTY;
      if (!final.error) {
        donePayload = {
          content: final.content,
          toolCalls: final.toolCalls,
          tokenMetrics: final.tokenMetrics,
        };
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        this.set(sessionId, { error: err.message });
      }
    } finally {
      if (flushTimer) clearTimeout(flushTimer);
      this.controllers.delete(sessionId);
      // Clear the live slice FIRST so the streaming trailer disappears, THEN
      // hand the completed turn to the cache layer (no double-render flash).
      this.set(sessionId, { streaming: false, content: "", toolCalls: [], tokenMetrics: null });
      if (donePayload) this.callbacks.onDone?.(sessionId, donePayload);
    }
  }
}

export const chatStream = new ChatStreamStore();
