import { memo } from "react";

interface Props {
  query: string;
  onChange: (q: string) => void;
  totalJobs: number;
  matchCount: number | null;
}

export const SearchBar = memo(function SearchBar({ query, onChange, totalJobs, matchCount }: Props) {
  return (
    <div className="search-bar">
      <div className="search-bar__input-wrap">
        <span className="search-bar__icon">⌕</span>
        <input
          className="search-bar__input"
          type="search"
          placeholder="Search filenames or transcript text…"
          value={query}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        {query && (
          <button className="search-bar__clear" onClick={() => onChange("")}>✕</button>
        )}
      </div>
      {matchCount !== null && (
        <span className="search-bar__count">
          {matchCount === 0
            ? "No results"
            : `${matchCount} of ${totalJobs}`}
        </span>
      )}
    </div>
  );
});
