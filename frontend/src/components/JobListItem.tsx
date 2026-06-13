import { memo, useCallback, useEffect, useRef, useState } from "react";
import type { SyntheticEvent } from "react";
import { audioUrl } from "../api/client";
import type { JobEntry } from "../hooks/useJobsManager";
import type { useSearch } from "../hooks/useSearch";
import { formatDuration, parseServerDate } from "../lib/format";
import { Stepper, statusLabel } from "./Stepper";
import { TranscriptView } from "./TranscriptView";
import { Highlight } from "./Highlight";
import { JobActions } from "./JobActions";
import { JobAudioPlayer } from "./JobAudioPlayer";

type SearchResult = ReturnType<typeof useSearch>["resultMap"] extends Map<string, infer V> ? V : never;

interface Props {
  job: JobEntry;
  expanded: boolean;
  showPlayer: boolean;
  onToggle: (jobId: string) => void;
  onTogglePlayer: (jobId: string) => void;
  onRetry: (jobId: string) => void;
  onDelete: (jobId: string) => void;
  searchResult?: SearchResult;
}

const DUPLICATE_LABEL = "Already transcribed";

// After this many seconds without reaching COMPLETED, show a warning on the badge.
const STALE_WARN_SECONDS = 60;

function useElapsedSeconds(startAt: string, active: boolean): number {
  const elapsedFrom = () =>
    Math.max(0, Math.floor((Date.now() - parseServerDate(startAt).getTime()) / 1000));
  const [elapsed, setElapsed] = useState(elapsedFrom);
  useEffect(() => {
    if (!active) return;
    setElapsed(elapsedFrom());
    const id = window.setInterval(() => setElapsed(elapsedFrom()), 1000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startAt, active]);
  return elapsed;
}

function fmtElapsed(s: number): string {
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function runtimeSeconds(createdAt: string, updatedAt: string): number {
  return Math.max(0, Math.round(
    (parseServerDate(updatedAt).getTime() - parseServerDate(createdAt).getTime()) / 1000
  ));
}


export const JobListItem = memo(function JobListItem({
  job, expanded, showPlayer, onToggle, onTogglePlayer, onRetry, onDelete, searchResult,
}: Props) {
  const isActive    = job.status === "PENDING" || job.status === "PROCESSING";
  const isCompleted = job.status === "COMPLETED";
  const isFailed    = job.status === "FAILED";
  // Total elapsed — counts from the original upload (or retry) so the
  // operator sees the cumulative time the job has been active.
  const elapsed     = useElapsedSeconds(job.startedAt, isActive);
  const isStale     = isActive && elapsed >= STALE_WARN_SECONDS;
  // The flow (stepper) is driven by the step/phase; the badge shows the data
  // status as a separate explanation.
  const statusText  = statusLabel(job.status);
  const runtime     = isCompleted
    ? runtimeSeconds(job.startedAt, job.updatedAt)
    : null;
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [audioTime, setAudioTime] = useState<number>(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const lastAudioTimeRef = useRef(0);

  const seekTo = useCallback((t: number) => {
    if (audioRef.current) audioRef.current.currentTime = t;
  }, []);

  const handleToggle = useCallback(() => onToggle(job.jobId), [onToggle, job.jobId]);
  const handleTogglePlayer = useCallback(() => onTogglePlayer(job.jobId), [onTogglePlayer, job.jobId]);
  const handleRetry = useCallback(() => onRetry(job.jobId), [onRetry, job.jobId]);
  const handleDelete = useCallback(() => onDelete(job.jobId), [onDelete, job.jobId]);
  const startDelete = useCallback(() => setConfirmDelete(true), []);
  const cancelDelete = useCallback(() => setConfirmDelete(false), []);
  const handleAudioTimeUpdate = useCallback((e: SyntheticEvent<HTMLAudioElement>) => {
    const currentTime = e.currentTarget.currentTime;
    if (Math.abs(currentTime - lastAudioTimeRef.current) < 0.25) return;
    lastAudioTimeRef.current = currentTime;
    setAudioTime(currentTime);
  }, []);
  const handleAudioEnded = useCallback(() => {
    lastAudioTimeRef.current = 0;
    setAudioTime(0);
  }, []);

  return (
    <div className={`job-item card ${isFailed ? "job-item--failed" : ""}${job.duplicateFlash ? " job-item--duplicate" : ""}`}>
      {/* header row */}
      <div
        className="job-item__header"
        onClick={isCompleted ? handleToggle : undefined}
        style={{ cursor: isCompleted ? "pointer" : "default" }}
      >
        <div className="job-item__meta">
          <span className="job-item__filename" title={job.filename}>
            {searchResult
              ? <Highlight text={job.filename} terms={searchResult.terms} />
              : job.filename}
          </span>
          {job.durationSeconds != null && (
            <span className="job-item__duration" title="Audio duration">
              ⏱ {formatDuration(job.durationSeconds)}
            </span>
          )}
        </div>
        <div className="job-item__right">
          {isActive && (
            <span className={`job-item__elapsed${isStale ? " job-item__elapsed--stale" : ""}`} title="Time since upload">
              {fmtElapsed(elapsed)}
            </span>
          )}
          <span className={`job-item__badge job-item__badge--${job.status.toLowerCase()}${isStale ? " job-item__badge--stale" : ""}`}>
            {statusText}
          </span>
          {job.duplicateFlash && (
            <span className="job-item__badge job-item__badge--duplicate">
              {DUPLICATE_LABEL}
            </span>
          )}

          <JobActions
            showPlayer={showPlayer}
            isCompleted={isCompleted}
            expanded={expanded}
            confirmDelete={confirmDelete}
            onTogglePlayer={handleTogglePlayer}
            onStartDelete={startDelete}
            onCancelDelete={cancelDelete}
            onDelete={handleDelete}
          />
        </div>
      </div>

      {/* search snippet — shown when a transcript-text match exists */}
      {searchResult?.snippet && !expanded && (
        <p className="job-item__snippet">
          <Highlight text={searchResult.snippet} terms={searchResult.terms} />
        </p>
      )}

      {/* audio player */}
      {showPlayer && (
        <JobAudioPlayer
          ref={audioRef}
          src={audioUrl(job.jobId)}
          onTimeUpdate={handleAudioTimeUpdate}
          onEnded={handleAudioEnded}
        />
      )}

      {/* stepper for active + failed */}
      {(isActive || isFailed) && (
        <div className="job-item__progress">
          <Stepper
            status={job.status}
            phase={job.phase}
          />
          {runtime != null && (
            <span className={`job-item__runtime${isFailed ? " job-item__runtime--failed" : ""}`}>
              ⚡ {fmtElapsed(runtime)}
            </span>
          )}
        </div>
      )}

      {/* error + retry */}
      {isFailed && (
        <div className="job-item__error">
          <span>{job.error}</span>
          {job.attempts > 0 && (
            <span className="job-item__attempts">
              {job.attempts + 1} runs total
            </span>
          )}
          <button onClick={handleRetry} disabled={job.busy}>
            {job.busy ? "Retrying…" : "Retry"}
          </button>
        </div>
      )}

      {/* transcript */}
      {isCompleted && expanded && job.transcript && (
        <div className="job-item__transcript">
          <TranscriptView
            transcript={job.transcript}
            currentTime={showPlayer ? audioTime : undefined}
            seekTo={showPlayer ? seekTo : undefined}
            terms={searchResult?.terms}
          />
        </div>
      )}
    </div>
  );
});
