const TYPE_CONFIG = {
  analyzing:    { icon: "🔍", label: "Analyzing",    color: "var(--amber)" },
  cache_check:  { icon: "⚡", label: "Cache",        color: "var(--green)" },
  planning:     { icon: "🧭", label: "Planning",     color: "var(--amber)" },
  researching:  { icon: "🕵️", label: "Researcher",  color: "var(--accent)" },
  critiquing:   { icon: "⚖️", label: "Critic",       color: "var(--purple)" },
  building:     { icon: "🔧", label: "Building",     color: "var(--text-muted)" },
  synthesizing: { icon: "✨", label: "Synthesizing", color: "var(--green)" },
  caching:      { icon: "💾", label: "Caching",      color: "var(--text-muted)" },
  direct:       { icon: "⚡", label: "Direct",       color: "var(--green)" },
};

function getDomain(url) {
  try { return new URL(url).hostname.replace("www.", ""); }
  catch { return url; }
}

function TimelineEntry({ event, isLast }) {
  const cfg = TYPE_CONFIG[event.type] || { icon: "•", label: event.type, color: "var(--text-muted)" };
  const data = event.data || {};

  return (
    <div className={`tl-entry ${isLast ? "tl-active" : ""}`}>
      <div className="tl-dot-col">
        <span className="tl-icon" style={{ color: cfg.color }}>{cfg.icon}</span>
        {!isLast && <div className="tl-line" />}
      </div>
      <div className="tl-body">
        <div className="tl-header">
          <span className="tl-label" style={{ color: cfg.color }}>{cfg.label}</span>
          <span className="tl-message">{event.message}</span>
        </div>

        {event.type === "analyzing" && data.sub_queries?.length > 0 && (
          <div className="tl-pages">
            {data.sub_queries.map((q, i) => (
              <div key={i} className="tl-page-row">
                <span className="tl-relevance" style={{ color: "var(--text-muted)" }}>Q{i + 1}</span>
                <span className="tl-page-title">{q}</span>
              </div>
            ))}
          </div>
        )}

        {event.type === "planning" && data.angles?.length > 0 && (
          <div className="tl-pages">
            {data.angles.map((a, i) => (
              <div key={i} className="tl-page-row">
                <span className="tl-relevance" style={{ color: "var(--accent)" }}>A{i + 1}</span>
                <span className="tl-page-title">{a}</span>
              </div>
            ))}
          </div>
        )}

        {event.type === "researching" && (
          <>
            {data.sub_query && <div className="tl-thought">"{data.sub_query}"</div>}
            <div className="tl-meta">
              {data.extracted || 0} pages ·{" "}
              <span style={{ color: data.high_relevance > 0 ? "var(--green)" : "var(--text-muted)" }}>
                {data.high_relevance || 0} high-relevance
              </span>
            </div>
            {data.urls?.length > 0 && (
              <div className="tl-url-chips">
                {data.urls.map((url, i) => (
                  <a key={i} className="tl-url-chip" href={url} target="_blank" rel="noreferrer" title={url}>
                    <span className="tl-url-chip-icon">↗</span>
                    {getDomain(url)}
                  </a>
                ))}
              </div>
            )}
          </>
        )}

        {event.type === "critiquing" && data.note && (
          <div className="tl-action-badge">
            <strong>{data.done ? "PROCEED" : "MORE RESEARCH"}</strong>
            <span className="tl-param"> {data.note}</span>
          </div>
        )}


        {event.type === "cache_check" && data.cache_hit && (
          <div className="tl-cache-hit">Cache hit — skipping web search</div>
        )}
      </div>
    </div>
  );
}

export function ReActTimeline({ timeline, isStreaming }) {
  if (!timeline?.length) return null;

  return (
    <div className="react-timeline">
      {timeline.map((event, i) => (
        <TimelineEntry
          key={i}
          event={event}
          isLast={isStreaming && i === timeline.length - 1}
        />
      ))}
      {isStreaming && (
        <div className="tl-entry tl-active">
          <div className="tl-dot-col">
            <span className="tl-spinner" />
          </div>
          <div className="tl-body">
            <span className="tl-message">Working...</span>
          </div>
        </div>
      )}
    </div>
  );
}
