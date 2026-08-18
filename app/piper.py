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
import wave

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize


class PiperError(RuntimeError):
    """Piper war nicht erreichbar oder lieferte keine Audiodaten."""


class PiperBackend:
    def __init__(self, host: str, port: int, timeout_s: float) -> None:
        self.host = host
        self.port = port
        self.timeout_s = timeout_s

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """Text -> WAV-Bytes. Wirft PiperError statt stumm nichts zu liefern."""
        text = text.strip()
        if not text:
            raise PiperError("Kein Text uebergeben.")
        try:
            return await asyncio.wait_for(self._synthesize(text, voice), timeout=self.timeout_s)
        except asyncio.TimeoutError as exc:
            raise PiperError(f"Piper antwortete nicht innerhalb von {self.timeout_s} s") from exc
        except PiperError:
            raise
        except Exception as exc:  # Verbindungsfehler o.ae.
            raise PiperError(f"Piper nicht erreichbar: {exc}") from exc

    async def healthy(self) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=min(1.5, self.timeout_s),
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
