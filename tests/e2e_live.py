"""Live-E2E gegen den laufenden tts-gateway (127.0.0.1:8146) + echtes XTTS-Backend.
Nicht Teil der Unit-Suite (macht echte ~40s-Synthesen). Aufruf: python tests/e2e_live.py
"""
import io
import json
import sys
import time
import urllib.request
import wave

BASE = "http://127.0.0.1:8146"


def get(path, timeout=10):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, r.read()


def tts(text, priority=None, timeout=200):
    data = urllib.parse.urlencode({"text": text}).encode()
    req = urllib.request.Request(BASE + "/api/tts", data=data, method="POST")
    if priority:
        req.add_header("X-TTS-Priority", priority)
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return r.status, body, time.monotonic() - t0


def wav_seconds(raw):
    with wave.open(io.BytesIO(raw), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def main():
    print("== /health ==")
    st, body = get("/health")
    h = json.loads(body)
    print(st, h)
    assert st == 200 and h["backend_up"] is True, "backend nicht erreichbar"

    print("== /api/voices ==")
    st, body = get("/api/voices")
    print(st, body[:120])
    assert st == 200

    print("== einzelne interaktive Synthese ==")
    st, wav, dt = tts("Hallo, das ist ein Test des TTS Job Bus.", priority="interactive")
    ok = wav[:4] == b"RIFF"
    print(f"status={st} bytes={len(wav)} riff={ok} audio_s={wav_seconds(wav):.1f} latency_s={dt:.1f}")
    assert st == 200 and ok, "keine gueltige WAV"

    print("\nE2E OK")


if __name__ == "__main__":
    import urllib.parse

    main()
