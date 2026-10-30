"""Reine Funktionen: Split + Concat + Prioritaets-Mapping."""
import io
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chunking import concat_wavs, split_for_tts  # noqa: E402
from app.config import (  # noqa: E402
    PRIORITY_BATCH,
    PRIORITY_INTERACTIVE,
    PRIORITY_NORMAL,
    priority_from_name,
    priority_label,
)


def _wav(nframes: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * nframes)
    return buf.getvalue()


def test_split_respects_max_chars():
    chunks = split_for_tts("Eins zwei drei. Vier fuenf sechs. Sieben.", max_chars=20, max_chunks=10)
    assert all(len(c) <= 22 for c in chunks)  # +Satzzeichen-Toleranz
    assert len(chunks) >= 2


def test_split_caps_at_max_chunks():
    chunks = split_for_tts("a. b. c. d. e. f.", max_chars=3, max_chunks=3)
    assert len(chunks) == 3


def test_split_empty_yields_something():
    assert split_for_tts("", max_chars=400, max_chunks=6) == [""]


def test_concat_single_is_passthrough():
    w = _wav(10)
    assert concat_wavs([w]) == w


def test_concat_sums_frames():
    merged = concat_wavs([_wav(3), _wav(5), _wav(7)])
    with wave.open(io.BytesIO(merged), "rb") as w:
        assert w.getnframes() == 15


def test_concat_empty_is_none():
    assert concat_wavs([]) is None


def test_priority_mapping():
    assert priority_from_name("interactive") == PRIORITY_INTERACTIVE
    assert priority_from_name("batch") == PRIORITY_BATCH
    assert priority_from_name(None) == PRIORITY_NORMAL
    assert priority_from_name("bogus") == PRIORITY_NORMAL
    assert priority_label(PRIORITY_INTERACTIVE) == "interactive"
