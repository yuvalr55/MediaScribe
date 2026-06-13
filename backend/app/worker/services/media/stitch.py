"""Stitch per-chunk transcripts back into one global transcript.

Each chunk is transcribed from its own zero, so segment timestamps are local to
the chunk. Stitching shifts them onto the global timeline (by adding the chunk's
start offset) and drops segments that fall inside the overlap region of the
*previous* chunk, so overlapping audio is not transcribed twice.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.domain.models import Chunk, TranscriptSegment

logger = get_logger(__name__)

_CONTINUATION_PREFIXES = ("and ", "or ", "but ", "nor ", "yet ", "so ", "for ")
_TERMINAL_PUNCTUATION = (".", "!", "?", "...", "…")


def _dedup_join(t1: str, t2: str) -> str:
    """Join two texts, removing any duplicated words at the seam."""
    words1 = t1.split()
    words2 = t2.split()
    for overlap in range(min(len(words1), len(words2), 6), 0, -1):
        tail = [w.lower() for w in words1[-overlap:]]
        head = [w.lower() for w in words2[:overlap]]
        if tail == head:
            return " ".join(words1 + words2[overlap:])
    return t1 + " " + t2


def _is_continuation(t1: str, t2: str) -> bool:
    """True when t2 appears to continue an unfinished sentence from t1."""
    t1 = t1.strip()
    t2 = t2.strip()
    if not t1 or not t2:
        return False
    ends_mid = not any(t1.endswith(p) for p in _TERMINAL_PUNCTUATION)
    starts_lower = t2[0].islower()
    starts_conjunction = t2.lower().startswith(_CONTINUATION_PREFIXES)
    return ends_mid and (starts_lower or starts_conjunction)


def _merge_fragments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Merge consecutive segments that look like a sentence split at a chunk boundary."""
    if len(segments) <= 1:
        return segments
    merged: list[TranscriptSegment] = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        while i + 1 < len(segments) and _is_continuation(seg.text, segments[i + 1].text):
            nxt = segments[i + 1]
            merged_text = _dedup_join(seg.text, nxt.text)
            i += 1
            if merged_text == seg.text:
                # _dedup_join made no progress — avoid infinite loop
                break
            seg = TranscriptSegment(start=seg.start, end=nxt.end, text=merged_text)
        merged.append(seg)
        i += 1
    return merged


def stitch_chunks(chunks: list[Chunk]) -> tuple[str, list[TranscriptSegment]]:
    """Merge ordered chunks into ``(full_text, global_segments)``."""
    ordered = sorted(chunks, key=lambda c: c.index)
    segments: list[TranscriptSegment] = []
    boundary = 0.0  # global time already covered by previous chunks

    for chunk in ordered:
        for seg in chunk.segments:
            global_start = chunk.start_seconds + seg.start
            global_end = chunk.start_seconds + seg.end
            # Skip segments whose midpoint lies in already-covered overlap.
            midpoint = (global_start + global_end) / 2
            if midpoint < boundary:
                continue
            segments.append(
                TranscriptSegment(
                    start=round(global_start, 3),
                    end=round(global_end, 3),
                    text=seg.text.strip(),
                )
            )
        boundary = chunk.end_seconds

    # Fragment merging only makes sense when there are multiple chunks — it
    # fixes sentences that Whisper split at an artificial chunk boundary.
    # With a single chunk there are no seams, so skip it to preserve the
    # natural segment granularity Whisper produced.
    if len(ordered) > 1:
        raw_count = len(segments)
        segments = _merge_fragments(segments)
        merged_count = len(segments)
        if merged_count < raw_count:
            logger.info(
                "Fragment merge: joined boundary-split segments",
                extra={"fields": {
                    "before": raw_count,
                    "after": merged_count,
                    "merged": raw_count - merged_count,
                }},
            )
    full_text = " ".join(s.text for s in segments if s.text).strip()
    return full_text, segments
