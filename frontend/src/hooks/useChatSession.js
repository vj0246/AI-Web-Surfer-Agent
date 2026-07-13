import { useCallback, useRef, useState } from "react";

export function useChatSession() {
  const sessionId = useRef(crypto.randomUUID());
  const [messages, setMessages] = useState([]);   // [{id, role, content, citations, timeline, isStreaming}]
  const pendingIdRef = useRef(null);
  const tokenBufferRef = useRef("");
  const tokenFlushRef = useRef(null);

  const addUserMessage = useCallback((content) => {
    const id = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id, role: "user", content, citations: [], timeline: [], isStreaming: false },
    ]);
    return id;
  }, []);

  const addAssistantPlaceholder = useCallback(() => {
    const id = crypto.randomUUID();
    pendingIdRef.current = id;
    tokenBufferRef.current = "";
    setMessages((prev) => [
      ...prev,
      { id, role: "assistant", content: "", citations: [], timeline: [], isStreaming: true },
    ]);
    return id;
  }, []);

  const appendTimelineEvent = useCallback((event) => {
    const id = pendingIdRef.current;
    if (!id) return;
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === id
          ? { ...msg, timeline: [...msg.timeline, event] }
          : msg
      )
    );
  }, []);

  // Batches tokens using requestAnimationFrame to avoid a setState per token
  const appendToken = useCallback((token) => {
    tokenBufferRef.current += token;
    if (!tokenFlushRef.current) {
      tokenFlushRef.current = requestAnimationFrame(() => {
        const id = pendingIdRef.current;
        const buffered = tokenBufferRef.current;
        tokenBufferRef.current = "";
        tokenFlushRef.current = null;
        if (!id || !buffered) return;
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === id ? { ...msg, content: msg.content + buffered } : msg
          )
        );
      });
    }
  }, []);

  const finalizeAssistant = useCallback((content, citations) => {
    // Cancel any pending token flush
    if (tokenFlushRef.current) {
      cancelAnimationFrame(tokenFlushRef.current);
      tokenFlushRef.current = null;
    }
    const id = pendingIdRef.current;
    if (!id) return;
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === id
          ? { ...msg, content, citations, isStreaming: false }
          : msg
      )
    );
    pendingIdRef.current = null;
    tokenBufferRef.current = "";
  }, []);

  const resetSession = useCallback(() => {
    if (tokenFlushRef.current) {
      cancelAnimationFrame(tokenFlushRef.current);
      tokenFlushRef.current = null;
    }
    sessionId.current = crypto.randomUUID();
    setMessages([]);
    pendingIdRef.current = null;
    tokenBufferRef.current = "";
  }, []);

  return {
    sessionId: sessionId.current,
    messages,
    addUserMessage,
    addAssistantPlaceholder,
    appendTimelineEvent,
    appendToken,
    finalizeAssistant,
    resetSession,
  };
}
