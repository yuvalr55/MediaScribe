import { useCallback, useEffect, useState } from "react";
import { FileUploader } from "./components/FileUploader";
import { JobListItem } from "./components/JobListItem";
import { SearchBar } from "./components/SearchBar";
import { useJobsManager } from "./hooks/useJobsManager";
import { usePagination } from "./hooks/usePagination";
import { useSearch } from "./hooks/useSearch";

const PAGE_SIZE = 8;

export default function App() {
  const { jobs, uploading, submit, retry, remove, loadTranscript, dedupeJobIds, clearDedupeToast, flashJob, uploadError, clearUploadError } = useJobsManager();
  const { query, setQuery, filteredJobs, resultMap, totalJobs } = useSearch(jobs);

  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const [showPlayer, setShowPlayer] = useState(false);

  const { page, setPage, totalPages, pageItems, resetPage } = usePagination(filteredJobs, PAGE_SIZE);

  const jumpToDedupe = useCallback((jobId: string) => {
    const idx = filteredJobs.findIndex((j) => j.jobId === jobId);
    if (idx >= 0) setPage(Math.floor(idx / PAGE_SIZE) + 1);
    flashJob(jobId);
    clearDedupeToast(jobId);
  }, [filteredJobs, setPage, flashJob, clearDedupeToast]);

  // Reset to page 1 whenever the search query changes.
  useEffect(() => { resetPage(); }, [query, resetPage]);

  const toggle = useCallback((jobId: string) => {
    // Lazy-load the transcript only when a job is actually opened.
    loadTranscript(jobId);
    setActiveJobId((prev) => {
      if (prev !== jobId) {
        setShowTranscript(true);
        setShowPlayer(false);
        return jobId;
      }
      setShowTranscript((t) => {
        const next = !t;
        if (!next) setShowPlayer((p) => { if (!p) setActiveJobId(null); return p; });
        return next;
      });
      return prev;
    });
  }, [loadTranscript]);

  const togglePlayer = useCallback((jobId: string) => {
    setActiveJobId((prev) => {
      if (prev !== jobId) {
        setShowPlayer(true);
        setShowTranscript(false);
        return jobId;
      }
      setShowPlayer((p) => {
        const next = !p;
        if (!next) setShowTranscript((t) => { if (!t) setActiveJobId(null); return t; });
        return next;
      });
      return prev;
    });
  }, []);

  const handleSelect = useCallback((files: File[]) => {
    setActiveJobId(null);
    setShowTranscript(false);
    setShowPlayer(false);
    submit(files);
    resetPage();
  }, [submit, resetPage]);

  return (
    <main className="app">
      <header className="app__header">
        <h1>MediaScribe</h1>
        <p>Upload a media file and get an accurate transcription.</p>
      </header>

      <FileUploader disabled={uploading} onSelect={handleSelect} />

      {uploadError && (
        <div className="upload-error-toast">
          <span className="upload-error-toast__icon">⚠️</span>
          <div className="upload-error-toast__body">
            <strong>Upload failed</strong>
            <span className="upload-error-toast__message">{uploadError}</span>
          </div>
          <button className="upload-error-toast__close" onClick={clearUploadError} aria-label="Dismiss">✕</button>
        </div>
      )}

      {dedupeJobIds.map((jobId, i) => {
        const job = jobs.find((j) => j.jobId === jobId);
        if (!job) return null;
        return (
          <div
            key={jobId}
            className="dedupe-toast"
            style={{ top: `${20 + i * 80}px` }}
            onClick={() => jumpToDedupe(jobId)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && jumpToDedupe(jobId)}
          >
            <span className="dedupe-toast__icon">⚡</span>
            <div className="dedupe-toast__body">
              <strong>Already transcribed</strong>
              <span className="dedupe-toast__filename">{job.filename}</span>
              <span className="dedupe-toast__hint">Click to view ↓</span>
            </div>
            <button className="dedupe-toast__close" onClick={(e) => { e.stopPropagation(); clearDedupeToast(jobId); }} aria-label="Dismiss">✕</button>
          </div>
        );
      })}

      {jobs.length > 0 && (
        <section className="jobs-list">
          <div className="jobs-list__header">
            <h2 className="jobs-list__title">Transcriptions</h2>
            <SearchBar
              query={query}
              onChange={setQuery}
              totalJobs={totalJobs}
              matchCount={query.trim() ? filteredJobs.length : null}
            />
          </div>

          {filteredJobs.length === 0 && query.trim() && (
            <p className="jobs-list__empty">No transcriptions match "{query}"</p>
          )}

          {pageItems.map((job) => (
            <JobListItem
              key={job.jobId}
              job={job}
              expanded={activeJobId === job.jobId && showTranscript}
              showPlayer={activeJobId === job.jobId && showPlayer}
              onToggle={toggle}
              onTogglePlayer={togglePlayer}
              onRetry={retry}
              onDelete={remove}
              searchResult={resultMap.get(job.jobId)}
            />
          ))}

          {totalPages > 1 && (
            <div className="pagination">
              <button
                className="pagination__btn"
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                ‹
              </button>
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                <button
                  key={p}
                  className={`pagination__btn${p === page ? " pagination__btn--active" : ""}`}
                  onClick={() => setPage(p)}
                >
                  {p}
                </button>
              ))}
              <button
                className="pagination__btn"
                disabled={page === totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                ›
              </button>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
