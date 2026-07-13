import { useCallback, useRef, useState } from "react";

const BACKEND = (import.meta.env.VITE_BACKEND_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export function useAgentStream({ onEvent, onDone, onError, onToken }) {
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef(null);

  const stream = useCallback(
    async (query, sessionId) => {
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setIsStreaming(true);

      try {
        const response = await fetch(`${BACKEND}/api/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query, session_id: sessionId }),
          signal: controller.signal,
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop(); // keep incomplete last line

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data:")) continue;
            const raw = trimmed.slice(5).trim();
            if (!raw || raw === "[DONE]") continue;

            try {
              const event = JSON.parse(raw);
              if (event.node === "__done__") {
                onDone?.(event.data);
                setIsStreaming(false);
                return;
              }
              if (event.node === "__error__") {
                onError?.(event.message);
                setIsStreaming(false);
                return;
              }
              // Route token events to the dedicated token handler, not the timeline
              if (event.type === "token") {
                onToken?.(event.token);
              } else {
                onEvent?.(event);
              }
            } catch {
              // malformed JSON line — skip
            }
          }
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          onError?.(err.message);
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [onEvent, onDone, onError, onToken]
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  return { stream, cancel, isStreaming };
}
