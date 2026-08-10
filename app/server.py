"""aiohttp-Server des TTS-Job-Bus. API-kompatibel zum XTTS-Backend (/api/tts,
/api/voices, /api/builtin-speakers) plus /health und /metrics.

Migration ist damit ein reiner ENV-Wechsel: Konsumenten zeigen ihre TTS_URL statt
auf .22:5002 auf den Gateway; optional setzen sie X-TTS-Priority: interactive|batch.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiohttp import web

from . import metrics
from .broker import BackendError, DeadlineExceeded, QueueFull, TtsBroker
from .config import priority_from_name, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tts-gateway")

_RETRY_AFTER = "8"  # Sekunden-Hinweis fuer 503-Backpressure


async def _parse_request(request: web.Request) -> dict[str, str]:
    """Liest text/language/speaker/speaker_id/priority aus form, json ODER query."""
    data: dict[str, str] = {}
    if request.method == "POST":
        ctype = (request.headers.get("Content-Type") or "").lower()
        if "application/json" in ctype:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    data = {k: v for k, v in body.items() if v is not None}
            except Exception:
                data = {}
        else:
            form = await request.post()
            data = {k: v for k, v in form.items() if isinstance(v, str)}
    else:
        data = dict(request.query)
    return {str(k): str(v) for k, v in data.items()}


async def handle_tts(request: web.Request) -> web.StreamResponse:
    broker: TtsBroker = request.app["broker"]
    data = await _parse_request(request)
    text = (data.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "No text provided"}, status=400)

    language = data.get("language", "de")
    speaker = data.get("speaker") or None
    speaker_id = data.get("speaker_id") or None
    # Prioritaet: Header hat Vorrang vor Feld; unbekannt/leer -> normal.
    prio_name = request.headers.get("X-TTS-Priority") or data.get("priority")
    priority = priority_from_name(prio_name)

    try:
        wav = await broker.synthesize(
            text=text,
            language=language,
            speaker=speaker,
            speaker_id=speaker_id,
            priority=priority,
        )
    except QueueFull:
        return web.json_response(
            {"error": "tts_busy", "reason": "queue_full", "busy": True},
            status=503,
            headers={"Retry-After": _RETRY_AFTER},
        )
    except DeadlineExceeded:
        return web.json_response(
            {"error": "tts_busy", "reason": "deadline", "busy": True},
            status=503,
            headers={"Retry-After": _RETRY_AFTER},
        )
    except asyncio.CancelledError:
        raise  # Client ist weg -> keine Antwort noetig
    except BackendError as exc:
        status = exc.status if 400 <= exc.status <= 599 else 502
        return web.json_response({"error": exc.message or "backend error"}, status=status)

    return web.Response(
        body=wav,
        content_type="audio/wav",
        headers={"Content-Disposition": "attachment; filename=tts_output.wav"},
    )


async def _passthrough_get(request: web.Request, path: str) -> web.StreamResponse:
    """GET an das XTTS-Backend durchreichen (voices/builtin-speakers)."""
    broker: TtsBroker = request.app["broker"]
    session: aiohttp.ClientSession = broker._session  # gemeinsame Session
    try:
        async with session.get(
            broker.s.backend_url + path, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            body = await resp.read()
            return web.Response(
                body=body,
                status=resp.status,
                content_type=resp.headers.get("Content-Type", "application/json"),
            )
    except Exception as exc:
        return web.json_response({"error": str(exc)[:200]}, status=502)


async def handle_voices(request: web.Request) -> web.StreamResponse:
    return await _passthrough_get(request, "/api/voices")


async def handle_builtin_speakers(request: web.Request) -> web.StreamResponse:
    return await _passthrough_get(request, "/api/builtin-speakers")


async def handle_health(request: web.Request) -> web.StreamResponse:
    broker: TtsBroker = request.app["broker"]
    backend_ok = await broker.backend_healthy()
    # Gateway selbst ist gesund, solange er antwortet; Backend-Status separat ausgewiesen.
    return web.json_response(
        {
            "status": "ok",
            "backend_up": backend_ok,
            "queue_depth": broker.queue_depth,
            "queue_max": broker.s.queue_max,
        },
        status=200,
    )


async def handle_metrics(request: web.Request) -> web.StreamResponse:
    return web.Response(body=metrics.render(), content_type="text/plain; version=0.0.4")


async def _on_startup(app: web.Application) -> None:
    broker = TtsBroker(settings)
    await broker.start()
    app["broker"] = broker
    log.info(
        "tts-gateway auf %s:%s -> backend %s (queue_max=%s, workers=%s)",
        settings.listen_host,
        settings.listen_port,
        settings.backend_url,
        settings.queue_max,
        settings.worker_concurrency,
    )


async def _on_cleanup(app: web.Application) -> None:
    broker: TtsBroker = app.get("broker")
    if broker is not None:
        await broker.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_route("*", "/api/tts", handle_tts)
    app.router.add_get("/api/voices", handle_voices)
    app.router.add_get("/api/builtin-speakers", handle_builtin_speakers)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app
