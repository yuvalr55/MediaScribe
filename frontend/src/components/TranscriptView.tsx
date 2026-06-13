import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { TranscriptResponse } from "../api/client";
import { countWords, formatDuration } from "../lib/format";
import { Highlight } from "./Highlight";

interface Props {
  transcript: TranscriptResponse;
  currentTime?: number;
  seekTo?: (t: number) => void;
  terms?: string[];
}

// Returns the most recently started segment index, or -1 before first segment.
// Segments stay highlighted until the next one starts — gaps keep the previous
// segment lit rather than going dark mid-audio.
function activeSegmentIndex(
  segments: TranscriptResponse["segments"],
  currentTime: number
): number {
  for (let i = segments.length - 1; i >= 0; i--) {
    if (currentTime >= segments[i].start) return i;
  }
  return -1;
}

export const TranscriptView = memo(function TranscriptView({ transcript, currentTime, seekTo, terms = [] }: Props) {
  const [copied, setCopied] = useState(false);
  const copyResetTimer = useRef<number | null>(null);

  const activeIdx = useMemo(
    () => currentTime != null && currentTime > 0
      ? activeSegmentIndex(transcript.segments, currentTime)
      : -1,
    [transcript.segments, currentTime]
  );

  const segmentRefs = useRef<(HTMLLIElement | null)[]>([]);
  const detailsRef = useRef<HTMLDetailsElement | null>(null);

  useEffect(() => {
    if (activeIdx >= 0 && detailsRef.current && !detailsRef.current.open) {
      detailsRef.current.open = true;
    }
  }, [activeIdx]);

  useEffect(() => {
    if (activeIdx >= 0) {
      segmentRefs.current[activeIdx]?.scrollIntoView({
        block: "center",
        behavior: "smooth",
      });
    }
  }, [activeIdx]);

  const copy = useCallback(async () => {
    await navigator.clipboard.writeText(transcript.text);
    setCopied(true);
    if (copyResetTimer.current) window.clearTimeout(copyResetTimer.current);
    copyResetTimer.current = window.setTimeout(() => {
      setCopied(false);
      copyResetTimer.current = null;
    }, 1500);
  }, [transcript.text]);

  useEffect(() => () => {
    if (copyResetTimer.current) window.clearTimeout(copyResetTimer.current);
  }, []);

  const download = useCallback(() => {
    const blob = new Blob([transcript.text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `transcript-${transcript.job_id}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }, [transcript.text, transcript.job_id]);

  const words = useMemo(() => countWords(transcript.text), [transcript.text]);

  return (
    <section className="card transcript">
      <div className="transcript__header">
        <div className="stats">
          {transcript.language && (
            <span className="badge">{transcript.language}</span>
          )}
          {transcript.duration_seconds != null && (
            <span className="stat">
              ⏱ {formatDuration(transcript.duration_seconds)}
            </span>
          )}
          <span className="stat">📝 {words.toLocaleString()} words</span>
          {transcript.segments.length > 0 && (
            <span className="stat">▦ {transcript.segments.length} segments</span>
          )}
        </div>
        <div className="transcript__actions">
          <button onClick={copy}>{copied ? "Copied ✓" : "Copy"}</button>
          <button className="btn-secondary" onClick={download}>
            Download .txt
          </button>
        </div>
      </div>

      <p className="transcript__text">
        <Highlight text={transcript.text} terms={terms} />
      </p>

      {transcript.segments.length > 0 && (
        <details ref={detailsRef} className="transcript__segments-wrap">
          <summary>Timestamped segments</summary>
          <ul className="transcript__segments">
            {transcript.segments.map((seg, i) => (
              <li
                key={i}
                ref={(el) => { segmentRefs.current[i] = el; }}
                className={i === activeIdx ? "transcript__segment--active" : ""}
              >
                <button
                  className={`transcript__time${seekTo ? " transcript__time--clickable" : ""}`}
                  title={seekTo ? `Seek to ${formatDuration(seg.start)}` : undefined}
                  onClick={seekTo ? () => seekTo(seg.start) : undefined}
                  disabled={!seekTo}
                >
                  {formatDuration(seg.start)}
                </button>
                <span><Highlight text={seg.text} terms={terms} /></span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
});
