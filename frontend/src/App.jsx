import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserPanel } from "./components/BrowserPanel.jsx";
import { ChatBubble } from "./components/ChatBubble.jsx";
import { useAgentStream } from "./hooks/useAgentStream.js";
import { useChatSession } from "./hooks/useChatSession.js";

const SUGGESTIONS = [
  "How does RLHF work in LLM training?",
  "What is the difference between RAG and fine-tuning?",
  "Explain how transformers work",
  "Latest developments in AI agents 2024",
  "How to implement binary search in Python?",
  "What caused the 2008 financial crisis?",
];

export default function App() {
  const [input, setInput] = useState("");
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const {
    sessionId,
    messages,
    addUserMessage,
    addAssistantPlaceholder,
    appendTimelineEvent,
    appendToken,
    finalizeAssistant,
    resetSession,
  } = useChatSession();

  const handleEvent = useCallback(
    (event) => { appendTimelineEvent(event); },
    [appendTimelineEvent]
  );

  const handleToken = useCallback(
    (token) => { appendToken(token); },
    [appendToken]
  );

  const handleDone = useCallback(
    (data) => { finalizeAssistant(data.answer ?? "", data.citations ?? []); },
    [finalizeAssistant]
  );

  const handleError = useCallback(
    (msg) => { finalizeAssistant(`Error: ${msg}`, []); },
    [finalizeAssistant]
  );

  const { stream, cancel, isStreaming } = useAgentStream({
    onEvent: handleEvent,
    onToken: handleToken,
    onDone: handleDone,
    onError: handleError,
  });

  const handleSubmit = useCallback(
    (q) => {
      const query = (q ?? input).trim();
      if (!query || isStreaming) return;

      setInput("");
      addUserMessage(query);
      addAssistantPlaceholder();
      stream(query, sessionId);
    },
    [input, isStreaming, addUserMessage, addAssistantPlaceholder, stream, sessionId]
  );

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const isEmpty = messages.length === 0;

  return (
    <div className="app-layout">
      {/* ── Left: chat panel ─────────────────────────────── */}
      <div className="chat-shell">
        <header className="chat-header">
          <div className="chat-header-left">
            <span className="chat-logo">◈</span>
            <span className="chat-title">Web Agent</span>
            <span className="model-tag">phi3:mini + llama3.1:8b · local</span>
          </div>
          <div className="chat-header-right">
            {!isEmpty && (
              <button
                className="icon-btn"
                onClick={() => { cancel(); resetSession(); }}
                title="New conversation"
              >
                ＋ New
              </button>
            )}
          </div>
        </header>

        <main className="chat-main">
          {isEmpty ? (
            <div className="empty-state">
              <div className="empty-logo">◈</div>
              <h1>Web Agent</h1>
              <p>Ask anything. I'll search, scrape, and synthesize an answer with sources.</p>
              <div className="suggestion-grid">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    className="suggestion-chip"
                    onClick={() => handleSubmit(s)}
                    disabled={isStreaming}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="messages">
              {messages.map((msg) => (
                <ChatBubble key={msg.id} message={msg} />
              ))}
              <div ref={bottomRef} />
            </div>
          )}
        </main>

        <footer className="chat-footer">
          <div className="input-row">
            <textarea
              ref={inputRef}
              className="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything..."
              rows={1}
              disabled={isStreaming}
            />
            {isStreaming ? (
              <button className="send-btn send-btn--stop" onClick={cancel}>
                ■ Stop
              </button>
            ) : (
              <button
                className="send-btn"
                onClick={() => handleSubmit()}
                disabled={!input.trim()}
              >
                Send ↑
              </button>
            )}
          </div>
          <div className="footer-hint">
            Enter to send · Shift+Enter for newline · Powered by Ollama + SearXNG
          </div>
        </footer>
      </div>

      {/* ── Right: live browser panel ─────────────────────── */}
      <BrowserPanel sessionId={sessionId} />
    </div>
  );
}
