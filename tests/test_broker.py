"""Broker-Verhalten: Prioritaets-Preemption, Backpressure, Deadline, Cancellation,
Concat. Dependency-arm: jeder Test faehrt eine eigene asyncio-Loop (kein
pytest-asyncio noetig). Das XTTS-Backend wird durch ein Fake-_render ersetzt."""
import asyncio
import io
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.broker import BackendError, DeadlineExceeded, QueueFull, TtsBroker  # noqa: E402
from app.config import (  # noqa: E402
    PRIORITY_BATCH,
    PRIORITY_INTERACTIVE,
    PRIORITY_NORMAL,
    Settings,
)


def make_wav(nframes: int = 10) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * nframes)
    return buf.getvalue()


def wav_frames(raw: bytes) -> int:
    with wave.open(io.BytesIO(raw), "rb") as w:
        return w.getnframes()


def settings(**over) -> Settings:
    base = dict(max_chars=6, queue_max=64, worker_concurrency=1)
    base.update(over)
    return Settings(**base)


async def _with_broker(s: Settings, coro):
    broker = TtsBroker(s)
    await broker.start()
    try:
        return await coro(broker)
    finally:
        await broker.close()


# --------------------------------------------------------------- Preemption
def test_interactive_preempts_batch_at_chunk_boundary():
    async def scenario(broker: TtsBroker):
        order: list[str] = []
        gate = asyncio.Event()
        first = {"hit": False}

        async def fake_render(job):
            order.append(job.text)
            if not first["hit"]:
                first["hit"] = True
                await gate.wait()  # ersten Batch-Chunk festhalten
            return make_wav(10)

        broker._render = fake_render

        t_batch = asyncio.create_task(
            broker.synthesize(text="aa. bb. cc. dd.", priority=PRIORITY_BATCH)
        )
        for _ in range(6):  # Worker greift Batch-Chunk 0, blockiert am Gate
            await asyncio.sleep(0)
        t_int = asyncio.create_task(
            broker.synthesize(text="zz.", priority=PRIORITY_INTERACTIVE)
        )
        for _ in range(4):
            await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(t_batch, t_int)
        return order

    order = asyncio.run(_with_broker(settings(), scenario))
    assert order[0] == "aa."          # lief bereits, kann nicht unterbrochen werden
    assert order[1] == "zz."          # interaktiv ueberholt die restlichen Batch-Chunks
    assert order[2:] == ["bb.", "cc.", "dd."]


# --------------------------------------------------------------- Backpressure
def test_queue_full_rejects():
    async def scenario(broker: TtsBroker):
        gate = asyncio.Event()

        async def blocking_render(job):
            await gate.wait()
            return make_wav()

        broker._render = blocking_render
        # queue_max=2: Chunk0 wird sofort vom Worker gezogen? Nein — put-Schleife
        # laeuft ohne await, fuellt die Queue bis maxsize. 3 Chunks -> QueueFull.
        with pytest.raises(QueueFull):
            await broker.synthesize(text="aa. bb. cc.", priority=PRIORITY_BATCH)
        gate.set()

    asyncio.run(_with_broker(settings(queue_max=2), scenario))


# --------------------------------------------------------------- Deadline
def test_deadline_exceeded():
    async def scenario(broker: TtsBroker):
        async def slow_render(job):
            await asyncio.sleep(0.01)
            return make_wav()

        broker._render = slow_render
        with pytest.raises(DeadlineExceeded):
            await broker.synthesize(text="hallo welt.", priority=PRIORITY_NORMAL)

    # negatives Warte-Budget -> deadline liegt in der Vergangenheit
    asyncio.run(_with_broker(settings(max_wait_normal_s=-1.0), scenario))


# --------------------------------------------------------------- Cancellation
def test_cancel_survives_and_worker_recovers():
    async def scenario(broker: TtsBroker):
        gate = asyncio.Event()
        rendered: list[str] = []

        async def render(job):
            if job.text == "block.":
                await gate.wait()
            rendered.append(job.text)
            return make_wav()

        broker._render = render
        t = asyncio.create_task(broker.synthesize(text="block.", priority=PRIORITY_INTERACTIVE))
        for _ in range(5):
            await asyncio.sleep(0)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        gate.set()
        # Worker muss nach dem Abbruch weiterarbeiten:
        out = await broker.synthesize(text="ok.", priority=PRIORITY_NORMAL)
        assert wav_frames(out) > 0
        assert "ok." in rendered

    asyncio.run(_with_broker(settings(), scenario))


# --------------------------------------------------------------- Concat
def test_concat_preserves_all_chunks():
    async def scenario(broker: TtsBroker):
        sizes = {"aa.": 5, "bb.": 7, "cc.": 11}

        async def render(job):
            return make_wav(sizes[job.text])

        broker._render = render
        out = await broker.synthesize(text="aa. bb. cc.", priority=PRIORITY_NORMAL)
        assert wav_frames(out) == sum(sizes.values())

    asyncio.run(_with_broker(settings(), scenario))


# --------------------------------------------------------------- Backend-Fehler
def test_backend_error_propagates():
    async def scenario(broker: TtsBroker):
        async def boom(job):
            raise BackendError(500, "kaputt")

        broker._render = boom
        with pytest.raises(BackendError):
            await broker.synthesize(text="hallo.", priority=PRIORITY_NORMAL)

    asyncio.run(_with_broker(settings(), scenario))
