import { useState, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

interface ToolCall {
  name: string;
  status: "running" | "done";
}

interface TokenMetrics {
  input: number;
  output: number;
}

export function useChat(sessionId: string | null) {
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [tokenMetrics, setTokenMetrics] = useState<TokenMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const qc = useQueryClient();

  const sendMessage = useCallback(
    async (content: string, file?: File) => {
      if (!sessionId || streaming) return;

      setStreaming(true);
      setStreamingContent("");
      setToolCalls([]);
      setTokenMetrics(null);
      setError(null);

      abortRef.current = new AbortController();

      try {
        let res: Response;

        if (file) {
          const formData = new FormData();
          formData.append("content", content);
          formData.append("file", file);

          res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
            method: "POST",
            body: formData,
            signal: abortRef.current.signal,
          });
        } else {
          res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content }),
            signal: abortRef.current.signal,
          });
        }

        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(body.detail ?? res.statusText);
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
                    setStreamingContent((prev) => prev + data.token);
                  }
                  break;
                case "tool_start":
                  if (data.name) {
                    setToolCalls((prev) => [...prev, { name: data.name, status: "running" }]);
                  }
                  break;
                case "tool_end":
                  if (data.name) {
                    setToolCalls((prev) =>
                      prev.map((t) => (t.name === data.name ? { ...t, status: "done" as const } : t)),
                    );
                  }
                  break;
                case "done":
                  setTokenMetrics({
                    input: data.input_tokens ?? 0,
                    output: data.output_tokens ?? 0,
                  });
                  break;
                case "error":
                  setError(data.message ?? "Unknown error");
                  break;
              }
            } catch {
              // ignore malformed JSON
            }
          }
        }

        qc.invalidateQueries({ queryKey: ["chat-session", sessionId] });
        qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== "AbortError") {
          setError(err.message);
        }
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [sessionId, streaming, qc],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { streaming, streamingContent, toolCalls, tokenMetrics, error, sendMessage, cancel };
}
