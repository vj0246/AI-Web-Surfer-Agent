import { useState } from "react";
import { CitationList } from "./CitationCard.jsx";
import { ReActTimeline } from "./ReActTimeline.jsx";

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button className="copy-btn" onClick={handleCopy} title="Copy answer">
      {copied ? "✓" : "⎘"}
    </button>
  );
}

export function ChatBubble({ message }) {
  const [timelineOpen, setTimelineOpen] = useState(false);
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="bubble-row bubble-row--user">
        <div className="bubble bubble--user">
          {message.content}
        </div>
      </div>
    );
  }

  // assistant bubble
  const hasTimeline = message.timeline?.length > 0;
  const hasCitations = message.citations?.length > 0;
  const noContentYet = !message.content && message.isStreaming;

  return (
    <div className="bubble-row bubble-row--assistant">
      <div className="bubble bubble--assistant">

        {hasTimeline && (
          <div className="timeline-toggle">
            <button
              className="timeline-toggle-btn"
              onClick={() => setTimelineOpen((o) => !o)}
            >
              {timelineOpen ? "▲" : "▼"} Agent steps ({message.timeline.length})
            </button>
            {timelineOpen && (
              <ReActTimeline
                timeline={message.timeline}
                isStreaming={message.isStreaming}
              />
            )}
            {!timelineOpen && message.isStreaming && (
              <ReActTimeline
                timeline={message.timeline.slice(-1)}
                isStreaming
              />
            )}
          </div>
        )}

        {noContentYet ? (
          <div className="bubble-thinking">
            <span className="dot-pulse" />
          </div>
        ) : (
          <div className="bubble-content">
            <div className="bubble-answer">
              {message.content}
              {message.isStreaming && <span className="streaming-cursor" />}
            </div>
            {!message.isStreaming && message.content && (
              <CopyButton text={message.content} />
            )}
          </div>
        )}

        {hasCitations && !message.isStreaming && (
          <CitationList citations={message.citations} />
        )}
      </div>
    </div>
  );
}
