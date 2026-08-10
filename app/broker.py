"""TTS-Job-Bus — Prioritaets-Queue + single-in-flight Worker vor dem XTTS-Backend.

Kern-Idee: Jeder eingehende /api/tts-Request wird in <=max_chars-Chunks zerlegt und
JEDER Chunk als eigener Job in eine bounded PriorityQueue gelegt. Der Worker zieht
immer den wichtigsten wartenden Chunk zuerst -> ein interaktiver Request ueberholt
einen laufenden Batch-Briefing an der naechsten Chunk-Grenze (max ~1 Render Wartezeit
statt hinter allen 12 Chunks). Das XTTS-Backend ist single-thread; darum genau EIN
Worker (WORKER_CONCURRENCY=1). Die Architektur bleibt fuer mehrere Backends offen.

Backpressure: Queue voll -> sofort QueueFull (der Server macht daraus 503 + Retry-After).
Deadline: ein Chunk, der laenger als max_wait_for(priority) in der Queue steht, wird
verworfen (DeadlineExceeded) statt endlos zu haengen. Cancellation: bricht der HTTP-Client
ab, werden die noch wartenden Chunk-Jobs des Requests uebersprungen.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import aiohttp

from . import metrics
from .chunking import concat_wavs, split_for_tts
from .config import Settings, priority_label


class QueueFull(Exception):
    """Die Queue ist am Limit -> Backpressure (503 tts_busy, Retry-After)."""


class DeadlineExceeded(Exception):
    """Ein Chunk hat sein Warte-Budget ueberschritten (503, Retry-After)."""


class BackendError(Exception):
    """Das XTTS-Backend hat nicht 2xx geliefert."""

    def __init__(self, status: int, message: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class ChunkJob:
    text: str
    language: str
    speaker: str | None
    speaker_id: str | None
    priority: int
    index: int          # Position im Request (fuer geordnete Concat)
    seq: int            # global monoton -> FIFO innerhalb einer Prioritaet
    enqueued_at: float  # loop.time()
    deadline: float     # loop.time()-Zeitpunkt, ab dem verworfen wird
    future: asyncio.Future = field(repr=False)


class TtsBroker:
    def __init__(self, settings: Settings):
        self.s = settings
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=settings.queue_max)
        self._seq = 0
        self._workers: list[asyncio.Task] = []
        self._session: aiohttp.ClientSession | None = None
        self._health_cache: tuple[float, bool] = (0.0, False)

    async def start(self) -> None:
        self._session = aiohttp.ClientSession()
        for wid in range(max(1, self.s.worker_concurrency)):
            self._workers.append(asyncio.create_task(self._worker(wid), name=f"tts-worker-{wid}"))

    async def close(self) -> None:
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            try:
                await w
            except asyncio.CancelledError:
                pass
        if self._session is not None:
            await self._session.close()

    # ------------------------------------------------------------------ submit
    async def synthesize(
        self,
        *,
        text: str,
        language: str = "de",
        speaker: str | None = None,
        speaker_id: str | None = None,
        priority: int,
    ) -> bytes:
        """Volltext -> WAV. Chunkt, enqueued je Chunk, sammelt geordnet, concatet.

        Wirft QueueFull / DeadlineExceeded / BackendError. Propagiert CancelledError,
        wenn der aufrufende HTTP-Handler abgebrochen wird (Client-Disconnect)."""
        text = (text or "").strip()
        if not text:
            raise BackendError(400, "empty text")

        loop = asyncio.get_running_loop()
        max_chunks = self.s.max_chunks_for(priority)
        chunks = split_for_tts(text, max_chars=self.s.max_chars, max_chunks=max_chunks)
        now = loop.time()
        deadline = now + self.s.max_wait_for(priority)
        plabel = priority_label(priority)

        jobs: list[ChunkJob] = []
        for idx, chunk in enumerate(chunks):
            self._seq += 1
            job = ChunkJob(
                text=chunk,
                language=language,
                speaker=speaker,
                speaker_id=speaker_id,
                priority=priority,
                index=idx,
                seq=self._seq,
                enqueued_at=now,
                deadline=deadline,
                future=loop.create_future(),
            )
            try:
                self._queue.put_nowait((job.priority, job.seq, job))
            except asyncio.QueueFull:
                # Teil-enqueue zuruecknehmen: schon eingereihte Chunks dieses Requests
                # abbrechen, damit sie kein Render-Budget verbrauchen.
                for j in jobs:
                    if not j.future.done():
                        j.future.cancel()
                metrics.REQUESTS.labels(plabel, "rejected_full").inc()
                raise QueueFull()
            jobs.append(job)
        metrics.QUEUE_DEPTH.set(self._queue.qsize())

        try:
            parts = await asyncio.gather(*(j.future for j in jobs))
        except BaseException as exc:
            for j in jobs:
                if not j.future.done():
                    j.future.cancel()
            if isinstance(exc, asyncio.CancelledError):
                metrics.REQUESTS.labels(plabel, "cancelled").inc()
            elif isinstance(exc, DeadlineExceeded):
                metrics.REQUESTS.labels(plabel, "rejected_deadline").inc()
            else:
                metrics.REQUESTS.labels(plabel, "backend_error").inc()
            raise

        merged = concat_wavs(list(parts))
        if not merged:
            metrics.REQUESTS.labels(plabel, "backend_error").inc()
            raise BackendError(502, "concat failed")
        metrics.REQUESTS.labels(plabel, "ok").inc()
        return merged

    # ------------------------------------------------------------------ worker
    async def _worker(self, wid: int) -> None:
        loop = asyncio.get_running_loop()
        while True:
            _prio, _seq, job = await self._queue.get()
            metrics.QUEUE_DEPTH.set(self._queue.qsize())
            plabel = priority_label(job.priority)
            try:
                # Client hat schon aufgegeben (Cancel/QueueFull-Rollback) -> ueberspringen.
                if job.future.done():
                    metrics.CHUNKS.labels(plabel, "cancelled").inc()
                    continue
                now = loop.time()
                if now > job.deadline:
                    if not job.future.done():
                        job.future.set_exception(DeadlineExceeded())
                    metrics.CHUNKS.labels(plabel, "rejected_deadline").inc()
                    continue
                metrics.WAIT_SECONDS.labels(plabel).observe(now - job.enqueued_at)
                metrics.INFLIGHT.inc()
                try:
                    wav = await self._render(job)
                    if not job.future.done():
                        job.future.set_result(wav)
                    metrics.CHUNKS.labels(plabel, "ok").inc()
                except BaseException as exc:  # noqa: BLE001 - alles zurueck an den Caller
                    if not job.future.done():
                        err = exc if isinstance(exc, BackendError) else BackendError(502, str(exc))
                        job.future.set_exception(err)
                    if isinstance(exc, asyncio.CancelledError):
                        # Worker wird beendet -> Job zurueck an Caller, dann re-raise.
                        raise
                    metrics.CHUNKS.labels(plabel, "backend_error").inc()
                finally:
                    metrics.INFLIGHT.dec()
            finally:
                self._queue.task_done()

    async def _render(self, job: ChunkJob) -> bytes:
        assert self._session is not None
        loop = asyncio.get_running_loop()
        url = self.s.backend_url + "/api/tts"
        data: dict[str, str] = {"text": job.text, "language": job.language}
        if job.speaker_id:
            data["speaker_id"] = job.speaker_id
        elif job.speaker:
            data["speaker"] = job.speaker
        timeout = aiohttp.ClientTimeout(
            total=self.s.backend_timeout_s, connect=self.s.backend_connect_timeout_s
        )
        started = loop.time()
        for attempt in range(self.s.backend_busy_retries + 1):
            async with self._session.post(url, data=data, timeout=timeout) as resp:
                body = await resp.read()
                if resp.status == 503 and b"tts_busy" in body:
                    # Sollte bei alleinigem Gateway-Zugriff nie passieren -> Alt-Konsument
                    # mit XTTS-Direktzugriff. Kurzer Backoff, dann erneut.
                    metrics.BACKEND_BUSY.inc()
                    if attempt < self.s.backend_busy_retries:
                        await asyncio.sleep(self.s.backend_busy_backoff_s * (attempt + 1))
                        continue
                    raise BackendError(503, "backend busy after retries")
                if resp.status >= 400 or not body:
                    raise BackendError(
                        resp.status if resp.status >= 400 else 502,
                        body[:200].decode(errors="ignore") or "empty backend response",
                    )
                metrics.SYNTH_SECONDS.observe(loop.time() - started)
                return body
        raise BackendError(503, "backend busy")

    # ------------------------------------------------------------------ health
    async def backend_healthy(self) -> bool:
        """XTTS-/health mit kurzem Cache (kein Hammering bei /health-Polls)."""
        now = time.monotonic()
        ts, ok = self._health_cache
        if now - ts < self.s.health_cache_s:
            return ok
        ok = False
        try:
            assert self._session is not None
            async with self._session.get(
                self.s.backend_url + "/health",
                timeout=aiohttp.ClientTimeout(total=4),
            ) as resp:
                ok = resp.status == 200
        except Exception:
            ok = False
        self._health_cache = (now, ok)
        metrics.BACKEND_UP.set(1 if ok else 0)
        return ok

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()
