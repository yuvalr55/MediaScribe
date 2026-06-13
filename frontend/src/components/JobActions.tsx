import { memo } from "react";

interface Props {
  showPlayer: boolean;
  isCompleted: boolean;
  expanded: boolean;
  confirmDelete: boolean;
  onTogglePlayer: () => void;
  onStartDelete: () => void;
  onCancelDelete: () => void;
  onDelete: () => void;
}

export const JobActions = memo(function JobActions({
  showPlayer,
  isCompleted,
  expanded,
  confirmDelete,
  onTogglePlayer,
  onStartDelete,
  onCancelDelete,
  onDelete,
}: Props) {
  return (
    <>
      <button
        className="job-item__icon-btn"
        title={showPlayer ? "Hide player" : "Play audio"}
        onClick={(event) => { event.stopPropagation(); onTogglePlayer(); }}
      >
        {showPlayer ? "■" : "▶"}
      </button>

      {confirmDelete ? (
        <span className="job-item__confirm" onClick={(event) => event.stopPropagation()}>
          <button className="job-item__icon-btn job-item__icon-btn--danger" onClick={onDelete}>✓</button>
          <button className="job-item__icon-btn" onClick={onCancelDelete}>✗</button>
        </span>
      ) : (
        <button
          className="job-item__icon-btn job-item__icon-btn--muted"
          title="Delete"
          onClick={(event) => { event.stopPropagation(); onStartDelete(); }}
        >
          🗑
        </button>
      )}

      {isCompleted && (
        <span className="job-item__chevron">{expanded ? "▲" : "▼"}</span>
      )}
    </>
  );
});
