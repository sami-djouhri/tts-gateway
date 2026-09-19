"""Piper-Backend des Gateways — das schnelle Gegenstueck zu XTTS.

Warum ein zweites Backend: XTTS klingt gut, rendert aber ~44 s pro Chunk und ist
single-threaded. Fuer alles Interaktive (Zug-Ansagen im Schach, kurze Quittungen)
ist das unbrauchbar. Piper synthetisiert in Echtzeit und vertraegt parallele
Anfragen — deshalb laeuft dieser Pfad bewusst **an der Queue vorbei**: die Queue
existiert nur, um das single-threaded XTTS zu serialisieren.

Damit wird der Gateway zum einzigen TTS-Einstieg fuer beide Qualitaeten, statt
dass jeder Konsument sein eigenes Wyoming-Protokoll spricht. Die Wyoming-Bridge
wird dabei nicht umgangen, sondern hier zentral bedient.
"""
from __future__ import annotations

import asyncio
import io
import logging
import time
import wave

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize


log = logging.getLogger(__name__)


class PiperError(RuntimeError):
    """Piper war nicht erreichbar oder lieferte keine Audiodaten."""


class PiperBackend:
    def __init__(
        self,
        host: str,
        port: int,
        basis_s: float = 10.0,
        s_je_zeichen: float = 0.08,
        max_s: float = 180.0,
    ) -> None:
        self.host = host
        self.port = port
        self.basis_s = basis_s
        self.s_je_zeichen = s_je_zeichen
        self.max_s = max_s

    def frist_fuer(self, text: str) -> float:
        """Wie lange dieser Text hoechstens dauern darf.

        Eine feste Frist misst die falsche Groesse: Piper braucht Zeit
        proportional zur Laenge des Textes, nicht pro Anfrage. Die alten 15 s
        waren an einer Ansage bemessen und liessen jedes Briefing scheitern.
        """
        return min(self.basis_s + len(text) * self.s_je_zeichen, self.max_s)

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """Text -> WAV-Bytes. Wirft PiperError statt stumm nichts zu liefern.

        ★ EINE UNBEKANNTE STIMME DARF NICHT IN STILLE ENDEN. Hier stand, eine
        durchgefallene Zuweisung fuehre "einfach zur Standardstimme" - das war
        eine Annahme, und sie ist falsch: mit `voice='lecture-de-mann.wav'`
        (einer XTTS-Stimmdatei, die life-ops-api aus der Zeit vor dem
        Piper-Entscheid weiterreichte) liefert die Bridge GAR KEINE Audiodaten,
        und der Aufrufer bekommt 502. Gemessen am 2026-09-06; die gesprochene
        Tagesuebersicht war deshalb tot, waehrend Schach - das keine Stimme
        mitgibt - einwandfrei sprach.
        Der zweite Versuch ohne Stimme macht den dokumentierten Vorsatz wahr,
        statt ihn zu behaupten. Er kostet nur dort Zeit, wo es sonst gar keine
        Antwort gaebe.
        """
        text = text.strip()
        if not text:
            raise PiperError("Kein Text uebergeben.")
        frist = self.frist_fuer(text)
        begonnen = time.monotonic()
        try:
            return await asyncio.wait_for(self._synthesize(text, voice), timeout=frist)
        except asyncio.TimeoutError as exc:
            raise PiperError(
                f"Piper antwortete nicht innerhalb von {frist:.0f} s ({len(text)} Zeichen)"
            ) from exc
        except PiperError as exc:
            if voice is None or "keine Audiodaten" not in str(exc):
                raise
            # ★ Der zweite Versuch erbt die RESTZEIT, er bekommt keine neue
            # Frist. Sonst dauert der Fall im schlechtesten Fall doppelt so
            # lange wie zugesagt, und der Aufrufer bricht vorher ab - dann
            # rechnet dieser Dienst fuer eine Antwort weiter, die niemand mehr
            # entgegennimmt.
            rest = frist - (time.monotonic() - begonnen)
            if rest <= 1.0:
                raise
            log.warning(
                "Piper lieferte mit Stimme %r nichts, zweiter Versuch mit der Standardstimme "
                "(%.0f s Rest)", voice, rest,
            )
            try:
                return await asyncio.wait_for(self._synthesize(text, None), timeout=rest)
            except asyncio.TimeoutError as zweiter:
                raise PiperError(
                    f"Piper antwortete nicht innerhalb von {frist:.0f} s ({len(text)} Zeichen)"
                ) from zweiter
        except Exception as exc:  # Verbindungsfehler o.ae.
            raise PiperError(f"Piper nicht erreichbar: {exc}") from exc

    async def healthy(self) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=1.5,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def _synthesize(self, text: str, voice: str | None) -> bytes:
        client = AsyncTcpClient(self.host, self.port)
        await client.connect()
        try:
            ereignis = Synthesize(text=text)
            if voice:
                # Wyoming kennt eine Stimmenangabe; aeltere Piper-Bridges nicht.
                # Faellt die Zuweisung durch, wird einfach die Standardstimme genutzt.
                try:
                    from wyoming.tts import SynthesizeVoice

                    ereignis = Synthesize(text=text, voice=SynthesizeVoice(name=voice))
                except Exception:
                    pass
            await client.write_event(ereignis.event())

            rate, width, channels = 22050, 2, 1
            stuecke: list[bytes] = []
            while True:
                event = await client.read_event()
                if event is None:
                    break
                if AudioStart.is_type(event.type):
                    start = AudioStart.from_event(event)
                    rate, width, channels = start.rate, start.width, start.channels
                elif AudioChunk.is_type(event.type):
                    stuecke.append(AudioChunk.from_event(event).audio)
                elif AudioStop.is_type(event.type):
                    break

            if not stuecke:
                raise PiperError("Piper hat keine Audiodaten geliefert.")

            puffer = io.BytesIO()
            with wave.open(puffer, "wb") as wav:
                wav.setnchannels(channels)
                wav.setsampwidth(width)
                wav.setframerate(rate)
                wav.writeframes(b"".join(stuecke))
            return puffer.getvalue()
        finally:
            await client.disconnect()
