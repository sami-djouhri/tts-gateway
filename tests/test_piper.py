"""Piper-Backend: die Frist waechst mit dem Text, und eine unbekannte Stimme
endet nicht in Stille.

BEIDES GEFUNDEN AM 2026-09-06, live an der gesprochenen Tagesuebersicht:

  * `life-ops-api` reichte `speaker='lecture-de-mann.wav'` durch, eine
    XTTS-Stimmdatei aus der Zeit vor dem Piper-Entscheid. Piper lieferte darauf
    GAR KEINE Audiodaten, der Aufrufer bekam 502. Im Quelltext stand daneben,
    eine durchgefallene Zuweisung fuehre "einfach zur Standardstimme" - eine
    Annahme, die nie geprueft worden war.
  * Die feste Frist von 15 s war an einer kurzen Ansage bemessen. Gemessen auf
    dem Wirt: 71 Zeichen 3,2 s, 213 Zeichen 6,6 s, 426 Zeichen nicht mehr. Ein
    Briefing ist immer laenger, es scheiterte also zuverlaessig - und die
    Meldung ("antwortete nicht innerhalb von 15 s") las sich wie ein haengender
    Dienst, obwohl Piper einfach noch arbeitete.

Die Tests fassen beides ohne echten Piper: der eine rechnet nur die Frist, der
andere ersetzt die Verbindung durch eine, die sich wie die Bridge verhaelt.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.piper import PiperBackend, PiperError  # noqa: E402


def _backend(**kw):
    grund = dict(host="127.0.0.1", port=10200, basis_s=10.0, s_je_zeichen=0.08, max_s=180.0)
    grund.update(kw)
    return PiperBackend(**grund)


def test_frist_waechst_mit_dem_text():
    p = _backend()
    kurz = p.frist_fuer("Turm nach e4.")
    lang = p.frist_fuer("Guten Morgen. " * 60)  # ~840 Zeichen, Briefing-Laenge
    assert kurz < lang, "ein langer Text braucht mehr Zeit als eine Ansage"
    assert lang > 15.0, (
        "genau hier lag der Fehler: mit der alten festen Frist von 15 s "
        f"scheiterte jedes Briefing, hier waeren es {lang:.0f} s"
    )


def test_frist_ist_gedeckelt():
    """Ein hängender Dienst darf nicht ewig binden - der Deckel bleibt."""
    p = _backend(max_s=60.0)
    assert p.frist_fuer("x" * 100000) == 60.0


def test_kurze_ansage_scheitert_weiterhin_schnell():
    """Die Gegenprobe zur wachsenden Frist: fuer Schach bleibt sie eng.

    Ohne diese Grenze waere aus der Reparatur eine Zugansage geworden, die im
    Fehlerfall drei Minuten wartet.
    """
    p = _backend()
    assert p.frist_fuer("Bauer e2 nach e4.") < 15.0


def test_unbekannte_stimme_faellt_auf_die_standardstimme(monkeypatch):
    """Der Fall life-ops: Stimme unbekannt, Piper liefert nichts.

    Vorher: 502 und die Sprachausgabe war tot. Jetzt: zweiter Versuch ohne
    Stimme, und der traegt.
    """
    versuche = []

    async def gefaelscht(self, text, voice):
        versuche.append(voice)
        if voice is not None:
            raise PiperError("Piper hat keine Audiodaten geliefert.")
        return b"RIFF....WAVE"

    monkeypatch.setattr(PiperBackend, "_synthesize", gefaelscht)
    ergebnis = asyncio.run(_backend().synthesize("Guten Morgen.", voice="lecture-de-mann.wav"))

    assert ergebnis == b"RIFF....WAVE"
    assert versuche == ["lecture-de-mann.wav", None], (
        "erst mit der gewuenschten Stimme, dann ohne - genau einmal nachgefasst"
    )


def test_zweiter_versuch_erbt_die_restzeit(monkeypatch):
    """Der Rueckfall darf die zugesagte Frist nicht verdoppeln.

    Sonst wartet der Aufrufer laenger als vereinbart, bricht ab, und dieser
    Dienst rechnet fuer eine Antwort weiter, die niemand mehr entgegennimmt.
    """
    fristen = []

    async def gefaelscht(self, text, voice):
        if voice is not None:
            await asyncio.sleep(0.05)
            raise PiperError("Piper hat keine Audiodaten geliefert.")
        return b"WAV"

    echtes_wait_for = asyncio.wait_for

    async def messendes_wait_for(aw, timeout):
        fristen.append(timeout)
        return await echtes_wait_for(aw, timeout)

    monkeypatch.setattr(PiperBackend, "_synthesize", gefaelscht)
    monkeypatch.setattr(asyncio, "wait_for", messendes_wait_for)
    asyncio.run(_backend().synthesize("Guten Morgen.", voice="fremd.wav"))

    assert len(fristen) == 2, "erst mit Stimme, dann ohne"
    assert fristen[1] < fristen[0], (
        f"der zweite Versuch bekam {fristen[1]:.2f} s statt der Restzeit von "
        f"weniger als {fristen[0]:.2f} s"
    )


def test_ohne_stimme_wird_nicht_zweimal_gefragt(monkeypatch):
    """Wer gar keine Stimme nennt, bekommt keinen zweiten Versuch.

    Sonst wuerde jeder echte Ausfall doppelt so lange dauern wie noetig.
    """
    versuche = []

    async def gefaelscht(self, text, voice):
        versuche.append(voice)
        raise PiperError("Piper hat keine Audiodaten geliefert.")

    monkeypatch.setattr(PiperBackend, "_synthesize", gefaelscht)
    try:
        asyncio.run(_backend().synthesize("Guten Morgen."))
    except PiperError:
        pass
    assert versuche == [None], f"genau ein Versuch erwartet, es waren {len(versuche)}"


def test_andere_fehler_werden_nicht_wiederholt(monkeypatch):
    """Ein nicht erreichbarer Dienst ist kein Stimmenproblem.

    Der zweite Versuch gilt genau dem einen Fall, sonst verdeckt er Ursachen.
    """
    versuche = []

    async def gefaelscht(self, text, voice):
        versuche.append(voice)
        raise PiperError("Piper nicht erreichbar: connection refused")

    monkeypatch.setattr(PiperBackend, "_synthesize", gefaelscht)
    try:
        asyncio.run(_backend().synthesize("Text", voice="egal.wav"))
    except PiperError as e:
        assert "nicht erreichbar" in str(e)
    assert versuche == ["egal.wav"], "ein Verbindungsfehler wird nicht nachgefasst"


def test_leerer_text_wird_abgewiesen():
    try:
        asyncio.run(_backend().synthesize("   "))
    except PiperError as e:
        assert "Kein Text" in str(e)
    else:
        raise AssertionError("leerer Text muss einen PiperError geben")
