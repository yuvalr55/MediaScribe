"""stitch_chunks — edge cases not covered by the main test file."""

from __future__ import annotations

from app.domain.enums import ChunkStatus
from app.domain.models import Chunk, TranscriptSegment


def _chunk(index, start, end, segs=None):
    return Chunk(
        index=index,
        start_seconds=start,
        end_seconds=end,
        status=ChunkStatus.COMPLETED,
        segments=[TranscriptSegment(start=s, end=e, text=t) for s, e, t in (segs or [])],
    )


def test_empty_chunks_returns_empty():
    from app.worker.services.media.stitch import stitch_chunks

    text, segs = stitch_chunks([])
    assert text == ""
    assert segs == []


def test_single_chunk_no_segments():
    from app.worker.services.media.stitch import stitch_chunks

    text, segs = stitch_chunks([_chunk(0, 0.0, 10.0)])
    assert text == ""
    assert segs == []


def test_whitespace_segment_excluded_from_full_text():
    from app.worker.services.media.stitch import stitch_chunks

    # A segment with only whitespace gets stripped to "" and excluded from full_text.
    chunks = [_chunk(0, 0.0, 10.0, [(0.0, 1.0, "  "), (1.0, 2.0, "hello")])]
    text, segs = stitch_chunks(chunks)
    assert text == "hello"  # whitespace segment excluded from joined text


def test_all_segments_in_overlap_region_skipped():
    from app.worker.services.media.stitch import stitch_chunks

    # chunk 0 ends at 30s; chunk 1 starts at 10s → segments with midpoint < 30 dropped
    chunks = [
        _chunk(0, 0.0, 30.0, [(0.0, 5.0, "first")]),
        _chunk(1, 10.0, 40.0, [(0.0, 5.0, "overlap-only"), (20.0, 25.0, "second")]),
    ]
    text, segs = stitch_chunks(chunks)
    # "overlap-only" midpoint = 10+2.5 = 12.5 < 30 → skipped
    # "second" midpoint = 10+22.5 = 32.5 > 30 → kept
    assert "overlap-only" not in text
    assert "second" in text
