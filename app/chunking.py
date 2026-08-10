"""Text-Splitting + WAV-Concat — identische Semantik wie die bisherigen Konsumenten
(host-router `_split_for_tts`, saganta `_split`), damit die Migration verhaltensneutral
ist. Der Gateway uebernimmt das Chunking zentral, sodass Konsumenten nur noch
Volltext + Prioritaet schicken."""
from __future__ import annotations

import io
import wave


def split_for_tts(text: str, *, max_chars: int, max_chunks: int) -> list[str]:
    """Zerlegt Text an Satzgrenzen in <=max_chars-Stuecke, gedeckelt auf max_chunks."""
    text = (text or "").replace("\n", " ")
    chunks: list[str] = []
    cur = ""
    for raw in text.split(". "):
        s = raw.strip()
        if not s:
            continue
        if not s.endswith((".", "!", "?")):
            s += "."
        if len(cur) + len(s) + 1 > max_chars and cur:
            chunks.append(cur.strip())
            cur = s
        else:
            cur = f"{cur} {s}".strip()
        if len(chunks) >= max_chunks:
            break
    if cur and len(chunks) < max_chunks:
        chunks.append(cur.strip())
    return chunks or [text.strip()[:max_chars] or text[:max_chars]]


def concat_wavs(wavs: list[bytes]) -> bytes | None:
    """Fuegt mehrere WAV-Chunks (gleiche Parameter) rahmenweise zusammen. In-Memory."""
    wavs = [w for w in wavs if w]
    if not wavs:
        return None
    if len(wavs) == 1:
        return wavs[0]
    out = io.BytesIO()
    writer: "wave.Wave_write | None" = None
    try:
        for raw in wavs:
            with wave.open(io.BytesIO(raw), "rb") as w:
                if writer is None:
                    writer = wave.open(out, "wb")
                    writer.setparams(w.getparams())
                writer.writeframes(w.readframes(w.getnframes()))
        if writer is not None:
            writer.close()
        return out.getvalue()
    except Exception:
        return None
