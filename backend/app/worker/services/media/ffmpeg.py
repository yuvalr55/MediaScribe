"""Thin ffmpeg/ffprobe wrappers.

ffmpeg is a system dependency (installed in the worker image). We use it to (a)
probe the media duration and (b) normalize arbitrary input — any container or
codec — into 16 kHz mono WAV, which is what Whisper expects, and to extract a
specific time window for a chunk.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path

from app.core.exceptions import AppError

_COMMAND_TIMEOUT_SECONDS = 120


class MediaProcessingError(AppError):
    code = "media_processing_error"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessingError(
            "ffmpeg command timed out",
            details={"cmd": cmd[0], "timeout_seconds": _COMMAND_TIMEOUT_SECONDS},
        ) from exc
    if result.returncode != 0:
        raise MediaProcessingError(
            "ffmpeg command failed",
            details={"cmd": cmd[0], "stderr": result.stderr.decode(errors="replace")},
        )
    return result


def probe_duration_seconds(path: Path) -> float:
    """Return media duration in seconds via ffprobe."""
    try:
        result = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ]
        )
    except MediaProcessingError as exc:
        raise MediaProcessingError(
            "File does not appear to be a valid audio or video file",
            details=exc.details,
        ) from exc
    data = json.loads(result.stdout or b"{}")
    duration = float(data.get("format", {}).get("duration", 0.0))
    if duration <= 0:
        raise MediaProcessingError(
            "File does not appear to be a valid audio or video file"
            " — no audio stream detected",
        )
    return duration


def detect_silence_points(
    path: Path,
    *,
    noise_db: int = -35,
    min_duration: float = 0.3,
) -> list[float]:
    """Return silence midpoint timestamps (seconds) found in the audio.

    Uses ffmpeg's silencedetect filter. Returns an empty list if no silences
    are found or if the filter fails — callers should fall back gracefully.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(path),
                "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
                "-f", "null", "-",
            ],
            capture_output=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return []
    stderr = result.stderr.decode(errors="replace")
    starts: list[float] = []
    ends: list[float] = []
    for line in stderr.splitlines():
        if "silence_start" in line:
            with contextlib.suppress(ValueError):
                starts.append(float(line.split("silence_start:")[-1].strip()))
        elif "silence_end" in line:
            with contextlib.suppress(ValueError):
                val = line.split("silence_end:")[-1].split("|")[0].strip()
                ends.append(float(val))
    # Pair starts with ends; unpaired start (silence to end of file) is ignored.
    return [(s + e) / 2.0 for s, e in zip(starts, ends, strict=False)]


def extract_window(
    source: Path,
    dest: Path,
    *,
    start_seconds: float,
    duration_seconds: float,
    sample_rate: int,
) -> Path:
    """Extract `[start, start+duration]` as 16 kHz mono WAV into `dest`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            str(source),
            "-ac",
            "1",          # mono
            "-ar",
            str(sample_rate),  # 16 kHz
            "-acodec",
            "pcm_s16le",  # explicit 16-bit PCM — handles ADPCM/float/multi-ch WAV input
            "-vn",        # drop video
            str(dest),
        ]
    )
    return dest
