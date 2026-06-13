"""ffmpeg/ffprobe wrappers — unit tests using subprocess mocks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.worker.services.media.ffmpeg import (
    MediaProcessingError,
    _run,
    detect_silence_points,
    probe_duration_seconds,
)


def _make_result(stdout: bytes = b"", returncode: int = 0, stderr: bytes = b""):
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


# ---------------------------------------------------------------------------
# _run
# ---------------------------------------------------------------------------

def test_run_raises_on_nonzero_returncode():
    with (
        patch("subprocess.run", return_value=_make_result(returncode=1, stderr=b"err")),
        pytest.raises(MediaProcessingError),
    ):
        _run(["ffprobe", "fake.mp3"])


def test_run_returns_result_on_success():
    mock = _make_result(stdout=b"ok", returncode=0)
    with patch("subprocess.run", return_value=mock):
        result = _run(["ffprobe", "fake.mp3"])
    assert result.stdout == b"ok"


def test_run_raises_on_timeout():
    with (
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 120)),
        pytest.raises(MediaProcessingError, match="timed out"),
    ):
        _run(["ffprobe", "fake.mp3"])


# ---------------------------------------------------------------------------
# probe_duration_seconds
# ---------------------------------------------------------------------------

def test_probe_duration_returns_float():
    payload = json.dumps({"format": {"duration": "12.5"}}).encode()
    with patch("subprocess.run", return_value=_make_result(stdout=payload)):
        assert probe_duration_seconds(Path("a.mp3")) == pytest.approx(12.5)


def test_probe_duration_raises_on_zero_duration():
    payload = json.dumps({"format": {"duration": "0.0"}}).encode()
    with (
        patch("subprocess.run", return_value=_make_result(stdout=payload)),
        pytest.raises(MediaProcessingError, match="no audio stream"),
    ):
        probe_duration_seconds(Path("a.mp3"))


def test_probe_duration_raises_on_ffprobe_failure():
    with (
        patch("subprocess.run", return_value=_make_result(returncode=1, stderr=b"bad")),
        pytest.raises(MediaProcessingError, match="valid audio or video"),
    ):
        probe_duration_seconds(Path("bad.txt"))


def test_probe_duration_raises_on_missing_format_key():
    payload = json.dumps({}).encode()
    with (
        patch("subprocess.run", return_value=_make_result(stdout=payload)),
        pytest.raises(MediaProcessingError, match="no audio stream"),
    ):
        probe_duration_seconds(Path("a.mp3"))


# ---------------------------------------------------------------------------
# detect_silence_points
# ---------------------------------------------------------------------------

def test_detect_silence_returns_midpoints():
    stderr = (
        b"[silencedetect] silence_start: 1.0\n"
        b"[silencedetect] silence_end: 3.0 | silence_duration: 2.0\n"
    )
    with patch("subprocess.run", return_value=_make_result(stderr=stderr)):
        points = detect_silence_points(Path("a.wav"))
    assert points == [pytest.approx(2.0)]


def test_detect_silence_returns_empty_when_no_silence():
    with patch("subprocess.run", return_value=_make_result(stderr=b"")):
        assert detect_silence_points(Path("a.wav")) == []


def test_detect_silence_returns_empty_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 120)):
        assert detect_silence_points(Path("a.wav")) == []


def test_detect_silence_ignores_unpaired_start():
    stderr = b"[silencedetect] silence_start: 5.0\n"  # no matching end
    with patch("subprocess.run", return_value=_make_result(stderr=stderr)):
        assert detect_silence_points(Path("a.wav")) == []


def test_detect_silence_multiple_intervals():
    stderr = (
        b"[silencedetect] silence_start: 0.0\n"
        b"[silencedetect] silence_end: 2.0 | silence_duration: 2.0\n"
        b"[silencedetect] silence_start: 10.0\n"
        b"[silencedetect] silence_end: 12.0 | silence_duration: 2.0\n"
    )
    with patch("subprocess.run", return_value=_make_result(stderr=stderr)):
        points = detect_silence_points(Path("a.wav"))
    assert points == [pytest.approx(1.0), pytest.approx(11.0)]
