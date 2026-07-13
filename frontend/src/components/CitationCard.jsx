function getDomain(url) {
  try {
    return new URL(url).hostname.replace("www.", "");
  } catch {
    return url;
  }
}

export function CitationCard({ citation }) {
  return (
    <a
      className="citation-card"
      href={citation.url}
      target="_blank"
      rel="noreferrer"
      title={citation.url}
    >
      <div className="cit-index">[{citation.index}]</div>
      <div className="cit-body">
        <div className="cit-domain">{getDomain(citation.url)}</div>
        <div className="cit-title">{citation.title}</div>
        {citation.snippet && (
          <div className="cit-snippet">{citation.snippet.slice(0, 120)}…</div>
        )}
      </div>
      <span className="cit-arrow">↗</span>
    </a>
  );
}

export function CitationList({ citations }) {
  if (!citations?.length) return null;

  return (
    <div className="citation-list">
      <div className="cit-list-header">Sources</div>
      <div className="cit-grid">
        {citations.map((c) => (
          <CitationCard key={c.index} citation={c} />
        ))}
      </div>
    </div>
  );
}
