// Small, dependency-free formatting helpers shared across components.

/**
 * Parse a server timestamp as UTC.
 *
 * The API emits naive ISO strings (e.g. "2026-06-12T00:02:38") with no
 * timezone marker. The browser would otherwise parse these as *local* time,
 * which skews every elapsed-time calculation by the viewer's UTC offset.
 * Appending "Z" forces UTC interpretation.
 */
export function parseServerDate(iso: string): Date {
  const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`);
}

/** Human-readable file size, e.g. 1536 -> "1.5 KB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

/** Seconds -> "m:ss" (or "h:mm:ss" past an hour). */
export function formatDuration(seconds: number): string {
  const s = Math.floor(seconds % 60);
  const m = Math.floor((seconds / 60) % 60);
  const h = Math.floor(seconds / 3600);
  const mm = m.toString().padStart(2, "0");
  const ss = s.toString().padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

/** Rough word count of a transcript. */
export function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}
