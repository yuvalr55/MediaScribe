// Manages the full list of transcription jobs.
//
// Polling architecture: a SINGLE list poll (`GET /jobs`) on one timer refreshes
// every job at once — not one request per job. Transcripts (`GET /jobs/{id}/
// result`) are fetched lazily, only when a completed job is expanded, and cached.
// This keeps the request volume at ~1/interval regardless of how many jobs exist.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  POLL_INTERVAL_MS,
  deleteJob as apiDeleteJob,
  getResult,
  getStatus,
  listJobs,
  retryJob,
  uploadFile,
  type JobStatus,
  type JobPhase,
  type JobProgressResponse,
  type JobStatusResponse,
  type TranscriptResponse,
} from "../api/client";

const isActive = (s: JobStatus) => s === "PENDING" || s === "PROCESSING";

export interface JobEntry {
  jobId: string;
  status: JobStatus;
  phase: JobPhase;
  progress: number;
  filename: string;
  durationSeconds: number | null;
  error: string | null;
  createdAt: string;
  updatedAt: string;
  startedAt: string;
  transcript: TranscriptResponse | null;
  busy: boolean;
  attempts: number;
  duplicateFlash?: boolean; // transient highlight when same file re-uploaded
}

function fromResponse(r: JobStatusResponse, existing?: JobEntry): JobEntry {
  return {
    jobId: r.job_id,
    status: r.status,
    phase: r.phase,
    progress: r.progress,
    filename: r.original_filename,
    durationSeconds: r.duration_seconds,
    error: r.error,
    createdAt: r.created_at,
    updatedAt: r.updated_at,
    startedAt: r.started_at,
    transcript: existing?.transcript ?? null,
    busy: false,
    attempts: r.attempts,
    duplicateFlash: existing?.duplicateFlash,
  };
}

// Applies a slim progress update in-place — preserves all static fields
// (filename, createdAt, durationSeconds, attempts) that the server omits.
function applyProgress(existing: JobEntry, r: JobProgressResponse): JobEntry {
  return {
    ...existing,
    status: r.status,
    phase: r.phase,
    progress: r.progress,
    startedAt: r.started_at,
    updatedAt: r.updated_at,
    error: r.error,
    busy: false,
  };
}


export function useJobsManager() {
  const [jobs, setJobs] = useState<JobEntry[]>([]);
  const [uploadCount, setUploadCount] = useState(0);
  const [dedupeJobIds, setDedupeJobIds] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const timers = useRef<Map<string, number>>(new Map());
  const pollRef = useRef<number | null>(null);
  // Mirror of `jobs` for reads inside callbacks without re-creating them.
  const jobsRef = useRef<JobEntry[]>([]);
  useEffect(() => { jobsRef.current = jobs; }, [jobs]);

  const updateJob = useCallback(
    (jobId: string, patch: Partial<JobEntry>) =>
      setJobs((prev) =>
        prev.map((j) => (j.jobId === jobId ? { ...j, ...patch } : j))
      ),
    []
  );

  // --- single list poll -----------------------------------------------
  // One GET /jobs?active=true per tick keeps the payload small — only
  // PENDING/PROCESSING jobs come back. Jobs that transitioned to a terminal
  // state between ticks won't appear in the active list, so we fetch those
  // individually to capture their final status before stopping the loop.
  const tick = useCallback(async () => {
    pollRef.current = null;
    try {
      const active = await listJobs(50, true);
      const activeIds = new Set(active.map((r) => r.job_id));

      // Jobs we were tracking as active that are no longer in the active list
      // have just transitioned to COMPLETED or FAILED — fetch their final state.
      const disappeared = jobsRef.current.filter(
        (j) => isActive(j.status) && !activeIds.has(j.jobId)
      );
      const terminal = disappeared.length > 0
        ? (await Promise.allSettled(disappeared.map((j) => getStatus(j.jobId))))
            .flatMap((r) => (r.status === "fulfilled" ? [r.value] : []))
        : [];

      const progressMap = new Map(active.map((r) => [r.job_id, r]));
      const terminalMap = new Map(terminal.map((r) => [r.job_id, r]));

      setJobs((prev) =>
        prev.map((j) => {
          const progress = progressMap.get(j.jobId);
          if (progress) return applyProgress(j, progress);
          const full = terminalMap.get(j.jobId);
          if (full) return fromResponse(full, j);
          return j;
        })
      );

      const stillActive = active.some((r) => isActive(r.status));
      if (stillActive && pollRef.current == null) {
        pollRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
      }
    } catch (err) {
      console.error("Job poll failed", err);
      if (pollRef.current == null) {
        pollRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
      }
    }
  }, []);

  const ensurePolling = useCallback(() => {
    if (pollRef.current == null) {
      pollRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
    }
  }, [tick]);

  // Lazily fetch a transcript when a completed job is first expanded.
  const loadTranscript = useCallback(async (jobId: string) => {
    const j = jobsRef.current.find((x) => x.jobId === jobId);
    if (!j || j.transcript || j.status !== "COMPLETED") return;
    try {
      const transcript = await getResult(jobId);
      setJobs((cur) => cur.map((x) => (x.jobId === jobId ? { ...x, transcript } : x)));
    } catch {/* transcript not critical */}
  }, []);

  // Load existing jobs on mount; start the single poll loop if any are active.
  useEffect(() => {
    listJobs()
      .then((list) => {
        setJobs(list.map((r) => fromResponse(r)));
        if (list.some((r) => isActive(r.status))) ensurePolling();
      })
      .catch((err) => console.error("Failed to load jobs", err));
    const flashTimers = timers.current;
    return () => {
      if (pollRef.current) window.clearTimeout(pollRef.current);
      flashTimers.forEach((t) => window.clearTimeout(t));
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);


  // Returns deduplicated job_id if the file was a duplicate, null otherwise.
  const _uploadOne = useCallback(
    async (file: File): Promise<string | null> => {
      try {
        const accepted = await uploadFile(file);

        if (accepted.deduplicated) {
          return accepted.job_id;
        }

        const entry: JobEntry = {
          jobId: accepted.job_id,
          status: accepted.status,
          phase: "QUEUED",
          progress: 0,
          filename: file.name,
          durationSeconds: null,
          error: null,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          startedAt: new Date().toISOString(),
          transcript: null,
          busy: true,
          attempts: 0,
        };
        setJobs((prev) => [entry, ...prev]);
        ensurePolling();
        return null;
      } catch (err) {
        setUploadError(String(err).replace(/^Error:\s*/, ""));
        return null;
      }
    },
    [ensurePolling]
  );

  const submit = useCallback(
    async (files: File[]) => {
      setUploadCount((n) => n + files.length);
      try {
        const results = await Promise.all(files.map(_uploadOne));
        const newDedupeIds = results.filter((id): id is string => id !== null);
        if (newDedupeIds.length > 0) {
          // Flash all deduped jobs immediately
          newDedupeIds.forEach((id) => {
            setJobs((prev) => prev.map((j) => j.jobId === id ? { ...j, duplicateFlash: true } : j));
            const prev = timers.current.get(`flash-${id}`);
            if (prev) window.clearTimeout(prev);
            const t = window.setTimeout(
              () => {
                setJobs((prev) => prev.map((j) => j.jobId === id ? { ...j, duplicateFlash: false } : j));
                timers.current.delete(`flash-${id}`);
              },
              3000
            );
            timers.current.set(`flash-${id}`, t);
          });
          setDedupeJobIds((prev) => {
            const merged = [...prev];
            for (const id of newDedupeIds) if (!merged.includes(id)) merged.push(id);
            return merged;
          });
          for (const id of newDedupeIds) {
            const prev = timers.current.get(`dedupe-dismiss-${id}`);
            if (prev) window.clearTimeout(prev);
            const t = window.setTimeout(
              () => {
                setDedupeJobIds((ids) => ids.filter((x) => x !== id));
                timers.current.delete(`dedupe-dismiss-${id}`);
              },
              10_000,
            );
            timers.current.set(`dedupe-dismiss-${id}`, t);
          }
        }
      } finally {
        setUploadCount((n) => n - files.length);
      }
    },
    [_uploadOne]
  );

  const retry = useCallback(
    async (jobId: string) => {
      updateJob(jobId, { busy: true, error: null });
      try {
        await retryJob(jobId);
        // Optimistically reset to the start of the pipeline so the stepper
        // immediately reflects the re-enqueue rather than waiting for the next poll.
        updateJob(jobId, {
          status: "PENDING",
          phase: "QUEUED",
          progress: 0,
          durationSeconds: null,
          transcript: null,
          busy: false,
          error: null,
          startedAt: new Date().toISOString(),
        });
        ensurePolling();
      } catch (err) {
        updateJob(jobId, { error: String(err), busy: false });
      }
    },
    [ensurePolling, updateJob]
  );

  const remove = useCallback(async (jobId: string) => {
    await apiDeleteJob(jobId);
    setJobs((prev) => prev.filter((j) => j.jobId !== jobId));
  }, []);

  const flashJob = useCallback((jobId: string) => {
    setJobs((prev) => prev.map((j) => j.jobId === jobId ? { ...j, duplicateFlash: true } : j));
    const prev = timers.current.get(`flash-${jobId}`);
    if (prev) window.clearTimeout(prev);
    const t = window.setTimeout(
      () => {
        setJobs((prev) => prev.map((j) => j.jobId === jobId ? { ...j, duplicateFlash: false } : j));
        timers.current.delete(`flash-${jobId}`);
      },
      3000
    );
    timers.current.set(`flash-${jobId}`, t);
  }, []);

  const clearDedupeToast = useCallback((jobId?: string) => {
    if (jobId) {
      const timer = timers.current.get(`dedupe-dismiss-${jobId}`);
      if (timer) window.clearTimeout(timer);
      timers.current.delete(`dedupe-dismiss-${jobId}`);
      setDedupeJobIds((prev) => prev.filter((id) => id !== jobId));
      return;
    }
    for (const [key, timer] of timers.current) {
      if (key.startsWith("dedupe-dismiss-")) {
        window.clearTimeout(timer);
        timers.current.delete(key);
      }
    }
    setDedupeJobIds([]);
  }, []);

  const clearUploadError = useCallback(() => setUploadError(null), []);

  return {
    jobs,
    uploading: uploadCount > 0,
    submit,
    retry,
    remove,
    loadTranscript,
    dedupeJobIds,
    clearDedupeToast,
    flashJob,
    uploadError,
    clearUploadError,
  };
}
