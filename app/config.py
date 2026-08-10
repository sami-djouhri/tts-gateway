"""Konfiguration des TTS-Job-Bus — rein ENV-getrieben, sichere Defaults.

Der Gateway ist der EINZIGE Sprecher gegenueber dem single-threaded XTTS-Backend
(.22:5002). Alle Konsumenten (host-router, wyoming-tts-bridge, saganta-news,
life-ops) reden nur noch mit dem Gateway; die Serialisierung/Priorisierung passiert
hier zentral.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    val = os.environ.get(name, "").strip()
    return val if val else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


# Prioritaets-Tiers (kleiner = wichtiger). Der Worker zieht immer den wichtigsten
# wartenden Chunk zuerst -> ein interaktiver Request ueberholt einen laufenden
# Batch-Briefing an der naechsten Chunk-Grenze (statt hinter allen 12 Chunks zu warten).
PRIORITY_INTERACTIVE = 0
PRIORITY_NORMAL = 1
PRIORITY_BATCH = 2

_PRIORITY_NAMES = {
    "interactive": PRIORITY_INTERACTIVE,
    "normal": PRIORITY_NORMAL,
    "batch": PRIORITY_BATCH,
}
_PRIORITY_LABELS = {v: k for k, v in _PRIORITY_NAMES.items()}


def priority_from_name(name: str | None) -> int:
    """Mappt X-TTS-Priority / priority-Feld auf einen Rang. Unbekannt/leer -> normal.
    So bleiben unmodifizierte Konsumenten waehrend der Migration lauffaehig."""
    if not name:
        return PRIORITY_NORMAL
    return _PRIORITY_NAMES.get(name.strip().lower(), PRIORITY_NORMAL)


def priority_label(rank: int) -> str:
    return _PRIORITY_LABELS.get(rank, "normal")


@dataclass(frozen=True)
class Settings:
    # --- Netz ---
    listen_host: str = field(default_factory=lambda: _env("LISTEN_HOST", "0.0.0.0"))
    listen_port: int = field(default_factory=lambda: _env_int("LISTEN_PORT", 8146))
    # XTTS-Backend (Basis-URL ohne Pfad). /api/tts, /api/voices etc. werden angehaengt.
    backend_url: str = field(
        default_factory=lambda: _env("XTTS_URL", "http://192.0.2.10:5002").rstrip("/")
    )

    # --- Queue / Backpressure ---
    # Maximale Anzahl gleichzeitig WARTENDER Chunk-Jobs (ueber alle Requests/Prioritaeten).
    # Ist die Queue voll -> sofort 503 tts_busy (statt unbegrenztem Speicherwachstum).
    queue_max: int = field(default_factory=lambda: _env_int("QUEUE_MAX", 64))
    # Anzahl Worker (= gleichzeitige Backend-Renders). XTTS ist single-thread -> 1.
    # Architektur bleibt fuer >1 offen (spaeter mehrere TTS-Backends).
    worker_concurrency: int = field(default_factory=lambda: _env_int("WORKER_CONCURRENCY", 1))

    # --- Chunking (XTTS-Limit ~400 Zeichen/Chunk) ---
    max_chars: int = field(default_factory=lambda: _env_int("TTS_MAX_CHARS", 400))
    # Deckel gegen entlaufene Synthese je Request, getrennt nach interaktiv/Batch.
    max_chunks_interactive: int = field(
        default_factory=lambda: _env_int("TTS_MAX_CHUNKS_INTERACTIVE", 8)
    )
    max_chunks_batch: int = field(default_factory=lambda: _env_int("TTS_MAX_CHUNKS_BATCH", 60))

    # --- Deadlines: wie lange ein Chunk MAXIMAL in der Queue warten darf, bevor er
    #     als 503 (Retry-After) verworfen wird. Muss die laengste EINZELNE Chunk-Renderzeit
    #     uebersteigen (XTTS ist mid-render nicht unterbrechbar -> ein interaktiver Request
    #     wartet im schlimmsten Fall einen laufenden 400-Zeichen-Chunk ab, ~50 s). Die
    #     Deadline ist der Saettigungs-Schutz (mehrere Jobs gleicher Prioritaet stauen sich),
    #     NICHT der Fast-Fail-Pfad — den regelt jeder Konsument ueber sein eigenes HTTP-Timeout
    #     + Fallback (wyoming->Piper 45 s, host-router->Text 90 s).
    max_wait_interactive_s: float = field(
        default_factory=lambda: _env_float("MAX_WAIT_INTERACTIVE_S", 90.0)
    )
    max_wait_normal_s: float = field(default_factory=lambda: _env_float("MAX_WAIT_NORMAL_S", 180.0))
    max_wait_batch_s: float = field(default_factory=lambda: _env_float("MAX_WAIT_BATCH_S", 1800.0))

    # --- Backend-Aufruf ---
    backend_timeout_s: float = field(default_factory=lambda: _env_float("BACKEND_TIMEOUT_S", 180.0))
    backend_connect_timeout_s: float = field(
        default_factory=lambda: _env_float("BACKEND_CONNECT_TIMEOUT_S", 5.0)
    )
    # Defensive: falls waehrend der Migration noch ein Alt-Konsument XTTS DIREKT
    # anspricht, kann XTTS trotz Gateway "tts_busy" liefern -> kurzer Retry.
    backend_busy_retries: int = field(default_factory=lambda: _env_int("BACKEND_BUSY_RETRIES", 3))
    backend_busy_backoff_s: float = field(
        default_factory=lambda: _env_float("BACKEND_BUSY_BACKOFF_S", 4.0)
    )
    # Health-Cache: Backend-/health nicht bei jedem /health-Poll hart durchreichen.
    health_cache_s: float = field(default_factory=lambda: _env_float("HEALTH_CACHE_S", 10.0))

    def max_wait_for(self, priority: int) -> float:
        if priority == PRIORITY_INTERACTIVE:
            return self.max_wait_interactive_s
        if priority == PRIORITY_BATCH:
            return self.max_wait_batch_s
        return self.max_wait_normal_s

    def max_chunks_for(self, priority: int) -> int:
        return self.max_chunks_interactive if priority <= PRIORITY_NORMAL else self.max_chunks_batch


settings = Settings()
