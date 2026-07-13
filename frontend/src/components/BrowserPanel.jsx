import { useEffect, useRef, useState } from "react";

const BACKEND = (import.meta.env.VITE_BACKEND_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const WS_BASE = BACKEND.replace(/^https?/, (m) => (m === "https" ? "wss" : "ws"));

function getDomain(url) {
  try { return new URL(url).hostname.replace("www.", ""); }
  catch { return url || ""; }
}

export function BrowserPanel({ sessionId }) {
  const imgRef         = useRef(null);
  const wsRef          = useRef(null);
  const aliveRef       = useRef(false);
  const reconnTimerRef = useRef(null);

  const [currentUrl, setCurrentUrl] = useState("");
  const [status, setStatus]         = useState("connecting"); // connecting | idle | navigating | live
  const [hasFrame, setHasFrame]     = useState(false);

  useEffect(() => {
    if (!sessionId) return;

    aliveRef.current = true;

    function connect() {
      if (!aliveRef.current) return;

      const ws = new WebSocket(`${WS_BASE}/ws/browser/${sessionId}`);
      wsRef.current = ws;

      ws.onopen = () => {
        // connected — waiting for frames
        setStatus((s) => (s === "connecting" ? "idle" : s));
      };

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);

          if (msg.type === "frame") {
            if (imgRef.current) {
              // Update DOM directly — no React re-render per frame
              imgRef.current.src = `data:image/jpeg;base64,${msg.frame}`;
            }
            if (msg.url) setCurrentUrl(msg.url);
            setStatus("live");
            setHasFrame(true);

          } else if (msg.type === "url") {
            setCurrentUrl(msg.url);
            setStatus("navigating");

          } else if (msg.type === "idle") {
            setStatus("idle");

          } else if (msg.type === "error") {
            setStatus("idle");
          }
        } catch (_) { /* ignore malformed */ }
      };

      ws.onerror = () => {
        setStatus("connecting");
      };

      ws.onclose = () => {
        if (!aliveRef.current) return;
        setStatus("connecting");
        // Auto-reconnect after 1.2 s
        reconnTimerRef.current = setTimeout(connect, 1200);
      };
    }

    connect();

    return () => {
      aliveRef.current = false;
      clearTimeout(reconnTimerRef.current);
      wsRef.current?.close();
    };
  }, [sessionId]);

  const domain = getDomain(currentUrl);

  /* ─── Status dot colour ────────────────────────────────────── */
  const dotClass =
    status === "live"        ? "dot-live"  :
    status === "navigating"  ? "dot-nav"   :
    status === "connecting"  ? "dot-conn"  :
    "dot-idle";

  /* ─── Address bar label ────────────────────────────────────── */
  const addrLabel =
    status === "connecting"  ? "Connecting…" :
    status === "navigating"  ? `Loading ${domain}…` :
    status === "live" && currentUrl ? currentUrl :
    "Live Browser";

  /* ─── Tag ──────────────────────────────────────────────────── */
  const tagClass =
    status === "live"       ? "tag-live" :
    status === "navigating" ? "tag-nav"  :
    status === "connecting" ? "tag-conn" :
    "tag-idle";

  const tagLabel =
    status === "live"       ? "LIVE"    :
    status === "navigating" ? "LOADING" :
    status === "connecting" ? "CONN…"   :
    "IDLE";

  return (
    <div className="browser-panel">

      {/* ── Address bar ───────────────────────────────────────── */}
      <div className="browser-bar">
        <span className={`browser-dot ${dotClass}`} />
        <div className="browser-address" title={currentUrl}>
          {status === "live" && currentUrl ? (
            <a href={currentUrl} target="_blank" rel="noreferrer" className="browser-url-link">
              {domain}
            </a>
          ) : (
            <span className="browser-url-placeholder">{addrLabel}</span>
          )}
        </div>
        <div className={`browser-status-tag ${tagClass}`}>{tagLabel}</div>
      </div>

      {/* ── Viewport ──────────────────────────────────────────── */}
      <div className="browser-viewport">

        {/* Placeholder before first frame */}
        {!hasFrame && status !== "navigating" && (
          <div className="browser-idle-msg">
            <div className="browser-idle-icon">🌐</div>
            <p>Agent browser</p>
            <p className="browser-idle-sub">
              {status === "connecting"
                ? "Connecting to backend…"
                : "Live view appears when the agent visits a page"}
            </p>
          </div>
        )}

        {/* Navigation overlay */}
        {status === "navigating" && (
          <div className="browser-nav-overlay">
            <div className="browser-nav-spinner" />
            <div className="browser-nav-text">
              Opening <strong>{domain || currentUrl}</strong>
            </div>
          </div>
        )}

        {/* Frame image — always in DOM so src updates work instantly */}
        <img
          ref={imgRef}
          className={[
            "browser-frame",
            !hasFrame              ? "browser-frame--hidden" : "",
            status === "idle" && hasFrame ? "browser-frame--dim"    : "",
          ].join(" ")}
          alt="Agent browser view"
          draggable={false}
        />

        {/* LIVE badge */}
        {status === "live" && (
          <div className="browser-live-badge">
            <span className="live-pulse" />
            LIVE
          </div>
        )}
      </div>
    </div>
  );
}
