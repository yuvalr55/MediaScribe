"""Stitching: global timestamp offsets and overlap de-duplication."""

from __future__ import annotations

import pytest

from app.domain.enums import ChunkStatus
from app.domain.models import Chunk, TranscriptSegment


def _chunk(index, start, end, segs):
    return Chunk(
        index=index,
        start_seconds=start,
        end_seconds=end,
        status=ChunkStatus.COMPLETED,
        segments=[TranscriptSegment(start=s, end=e, text=t) for s, e, t in segs],
    )


def test_offsets_shift_to_global_timeline():
    from app.worker.services.media.stitch import stitch_chunks

    chunks = [
        _chunk(0, 0.0, 30.0, [(0.0, 2.0, "hello")]),
        _chunk(1, 30.0, 60.0, [(0.0, 2.0, "World")]),
    ]
    text, segments = stitch_chunks(chunks)

    assert text == "hello World"
    assert segments[1].start == 30.0  # local 0 shifted by chunk start
    assert segments[1].end == 32.0


def test_overlap_region_is_not_duplicated():
    from app.worker.services.media.stitch import stitch_chunks

    # Chunk 0 covers [0,30]; chunk 1 starts at 25 (5s overlap). A segment in the
    # overlap should be counted once.
    chunks = [
        _chunk(0, 0.0, 30.0, [(26.0, 27.0, "overlap")]),
        _chunk(1, 25.0, 55.0, [(1.0, 2.0, "overlap"), (10.0, 11.0, "after")]),
    ]
    text, segments = stitch_chunks(chunks)

    assert text.count("overlap") == 1
    assert "after" in text


def test_out_of_order_chunks_are_sorted():
    from app.worker.services.media.stitch import stitch_chunks

    chunks = [
        _chunk(1, 30.0, 60.0, [(0.0, 1.0, "second")]),
        _chunk(0, 0.0, 30.0, [(0.0, 1.0, "first")]),
    ]
    text, _ = stitch_chunks(chunks)
    assert text == "first second"


def test_mid_sentence_split_is_merged():
    """Segments split at a chunk boundary with duplicate word should be joined."""
    from app.worker.services.media.stitch import stitch_chunks

    chunks = [
        _chunk(0, 0.0, 30.0, [
            (22.0, 29.5, "In a world that has known peace for generations and"),
        ]),
        _chunk(1, 27.0, 57.0, [(2.0, 8.0, "and insidious corruption festers unseen.")]),
    ]
    text, segments = stitch_chunks(chunks)

    assert "and and" not in text
    assert "insidious corruption" in text
    assert len(segments) == 1
    assert segments[0].start == 22.0
    assert segments[0].end == pytest.approx(35.0, abs=0.1)


def test_complete_sentence_not_merged():
    """Segments ending with period should not be merged even if next starts lowercase."""
    from app.worker.services.media.stitch import stitch_chunks

    chunks = [
        _chunk(0, 0.0, 30.0, [(0.0, 5.0, "Hello world.")]),
        _chunk(1, 30.0, 60.0, [(0.0, 5.0, "another sentence here.")]),
    ]
    text, segments = stitch_chunks(chunks)

    assert len(segments) == 2
