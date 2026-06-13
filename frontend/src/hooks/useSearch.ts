// Full-text search over jobs (filename + transcript text) using MiniSearch.
// Re-indexes automatically when the completed-jobs set changes.

import MiniSearch from "minisearch";
import { useMemo, useState } from "react";
import type { JobEntry } from "./useJobsManager";

interface SearchDoc {
  id: string;       // jobId
  filename: string;
  text: string;     // full transcript text (empty for non-completed)
}

interface SearchResult {
  jobId: string;
  /** Snippet of the transcript around the matched term, or null if matched by filename. */
  snippet: string | null;
  /** The raw query terms for highlight rendering. */
  terms: string[];
}

// Find the best snippet in `text` that contains one of `terms`.
function extractSnippet(text: string, terms: string[], windowSize = 120): string {
  const lower = text.toLowerCase();
  for (const term of terms) {
    const idx = lower.indexOf(term.toLowerCase());
    if (idx === -1) continue;
    const start = Math.max(0, idx - windowSize / 2);
    const end = Math.min(text.length, idx + term.length + windowSize / 2);
    return (start > 0 ? "…" : "") + text.slice(start, end) + (end < text.length ? "…" : "");
  }
  return text.slice(0, windowSize) + (text.length > windowSize ? "…" : "");
}

export function useSearch(jobs: JobEntry[]) {
  const [query, setQuery] = useState("");

  // Build the index whenever the set of completed transcripts changes.
  // Using a key derived from completed job IDs so the index isn't rebuilt on
  // every poll update (status / progress changes for in-flight jobs).
  const completedKey = jobs
    .filter((j) => j.status === "COMPLETED" && j.transcript)
    .map((j) => j.jobId)
    .join(",");

  const index = useMemo(() => {
    const ms = new MiniSearch<SearchDoc>({
      fields: ["filename", "text"],
      storeFields: ["filename", "text"],
      searchOptions: {
        boost: { filename: 3 },   // filename matches rank higher
        fuzzy: 0.2,               // tolerate small typos
        prefix: true,             // "trans" matches "transcription"
        combineWith: "OR",        // any term matches; score ranks multi-term higher
      },
    });

    const docs: SearchDoc[] = jobs.map((j) => ({
      id: j.jobId,
      filename: j.filename.replace(/\.[^.]+$/, ""), // strip extension for cleaner matching
      text: j.transcript?.text ?? "",
    }));

    ms.addAll(docs);
    return ms;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [completedKey, jobs.length]);

  const results: SearchResult[] | null = useMemo(() => {
    const q = query.trim();
    if (!q) return null;

    const allHits = index.search(q);

    // When the query has multiple terms, only keep results that contain ALL terms
    // (MiniSearch scores them highest anyway, but we want strict filtering).
    // For single-term queries, return everything.
    const queryTerms = q.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = queryTerms.length > 1
      ? allHits.filter((h) =>
          queryTerms.every((qt) =>
            (h.terms as string[]).some((t) => t.toLowerCase().startsWith(qt.toLowerCase()))
          )
        )
      : allHits;

    // Build a map of jobId → matched terms
    const hitMap = new Map(hits.map((h) => [h.id as string, h.terms as string[]]));

    return jobs
      .filter((j) => hitMap.has(j.jobId))
      .map((j) => {
        const terms = hitMap.get(j.jobId)!;
        const text = j.transcript?.text ?? "";
        // Only include snippet if the transcript actually contains the match.
        const hasTextMatch = terms.some((t) => text.toLowerCase().includes(t.toLowerCase()));
        return {
          jobId: j.jobId,
          snippet: hasTextMatch ? extractSnippet(text, terms) : null,
          terms,
        };
      });
  }, [query, index, jobs]);

  // Map of jobId → SearchResult for O(1) lookup in the render layer.
  const resultMap = useMemo(
    () => new Map(results?.map((r) => [r.jobId, r]) ?? []),
    [results]
  );

  const filteredJobs = useMemo(
    () => (results === null ? jobs : jobs.filter((j) => resultMap.has(j.jobId))),
    [results, jobs, resultMap]
  );

  return { query, setQuery, filteredJobs, resultMap, totalJobs: jobs.length };
}
