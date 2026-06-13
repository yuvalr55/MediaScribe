"""Chunking strategy: window planning, overlap, edge cases."""

from __future__ import annotations

import pytest

from app.worker.services.media.chunker import ChunkSpec, FixedWindowChunker, VadChunker


def test_short_audio_single_chunk():
    chunker = FixedWindowChunker(window_seconds=30, overlap_seconds=1)
    specs = chunker.plan(total_seconds=20)
    assert specs == [ChunkSpec(index=0, start_seconds=0.0, end_seconds=20.0)]


def test_windows_cover_entire_timeline_with_overlap():
    chunker = FixedWindowChunker(window_seconds=30, overlap_seconds=5)
    specs = chunker.plan(total_seconds=100)

    # Step is window - overlap = 25.
    assert specs[0] == ChunkSpec(0, 0.0, 30.0)
    assert specs[1] == ChunkSpec(1, 25.0, 55.0)
    # Neighbours overlap by exactly `overlap_seconds`.
    assert specs[0].end_seconds - specs[1].start_seconds == 5.0
    # Coverage reaches the end, last chunk clamped.
    assert specs[-1].end_seconds == 100.0


def test_zero_duration_yields_no_chunks():
    chunker = FixedWindowChunker(window_seconds=30, overlap_seconds=1)
    assert chunker.plan(0) == []


def test_invalid_overlap_rejected():
    with pytest.raises(ValueError):
        FixedWindowChunker(window_seconds=10, overlap_seconds=10)


# ── VadChunker ────────────────────────────────────────────────────────────────

def test_vad_snaps_boundary_to_nearest_silence():
    # Silence at 28s, target boundary at 30s — should split at 28.
    chunker = VadChunker(window_seconds=30, silence_points=[28.0, 58.0])
    specs = chunker.plan(total_seconds=60)
    assert specs[0].end_seconds == pytest.approx(28.0)
    assert specs[1].start_seconds == pytest.approx(28.0)
    assert specs[-1].end_seconds == pytest.approx(60.0)


def test_vad_falls_back_to_fixed_boundary_when_no_silence_nearby():
    # No silence anywhere near 30s — use the ideal boundary.
    chunker = VadChunker(window_seconds=30, silence_points=[5.0, 55.0])
    specs = chunker.plan(total_seconds=60)
    # 5s is too early (before min-chunk guard); 55s is outside radius of 30s boundary.
    # Falls back to ideal 30s split.
    assert specs[0].end_seconds == pytest.approx(30.0)


def test_vad_no_silence_points_produces_fixed_windows():
    chunker = VadChunker(window_seconds=30, silence_points=[])
    specs = chunker.plan(total_seconds=60)
    assert specs[0].end_seconds == pytest.approx(30.0)
    assert specs[1].end_seconds == pytest.approx(60.0)


def test_vad_chunks_are_contiguous_and_cover_full_duration():
    silence = [27.3, 31.1, 58.8, 62.0, 89.5]
    chunker = VadChunker(window_seconds=30, silence_points=silence)
    specs = chunker.plan(total_seconds=120)
    assert specs[0].start_seconds == 0.0
    assert specs[-1].end_seconds == pytest.approx(120.0)
    for a, b in zip(specs, specs[1:], strict=False):
        assert a.end_seconds == pytest.approx(b.start_seconds)
