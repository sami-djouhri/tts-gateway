"""Prometheus-Metriken des TTS-Job-Bus. Exponiert unter /metrics."""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

# Ausgang je Request/Chunk: ok | rejected_full | rejected_deadline | cancelled | backend_error
REQUESTS = Counter(
    "tts_gateway_requests_total",
    "TTS-Requests nach Prioritaet und Ausgang",
    ["priority", "outcome"],
    registry=REGISTRY,
)
CHUNKS = Counter(
    "tts_gateway_chunks_total",
    "Synthetisierte Chunks nach Prioritaet und Ausgang",
    ["priority", "outcome"],
    registry=REGISTRY,
)
QUEUE_DEPTH = Gauge(
    "tts_gateway_queue_depth",
    "Aktuell wartende Chunk-Jobs in der Queue",
    registry=REGISTRY,
)
INFLIGHT = Gauge(
    "tts_gateway_inflight",
    "Aktuell im Backend rendernde Chunks",
    registry=REGISTRY,
)
WAIT_SECONDS = Histogram(
    "tts_gateway_wait_seconds",
    "Wartezeit eines Chunks in der Queue bis Render-Start",
    ["priority"],
    buckets=(0.05, 0.25, 1, 5, 15, 30, 60, 120, 300, 600),
    registry=REGISTRY,
)
SYNTH_SECONDS = Histogram(
    "tts_gateway_synth_seconds",
    "Backend-Renderdauer je Chunk",
    buckets=(5, 15, 30, 45, 60, 90, 120, 180),
    registry=REGISTRY,
)
BACKEND_BUSY = Counter(
    "tts_gateway_backend_busy_total",
    "Wie oft das XTTS-Backend trotz Gateway-Serialisierung tts_busy meldete "
    "(Hinweis auf Alt-Konsument mit Direktzugriff)",
    registry=REGISTRY,
)
BACKEND_UP = Gauge(
    "tts_gateway_backend_up",
    "1 = XTTS-Backend beim letzten Health-Check erreichbar, sonst 0",
    registry=REGISTRY,
)


def render() -> bytes:
    return generate_latest(REGISTRY)
