"""Welches Backend eine Anfrage bedient, wenn der Aufrufer es nicht sagt.

GEFUNDEN AM 2026-09-18, an der schlechten Stimme des Morgen-Briefings:

`saganta-news-api` bittet den Gateway seit jeher um `stimme-de-frau.wav`, die
geklonte Stimme aus XTTS. Seit der Vorgabe-Umstellung auf Piper am 2026-09-06
ging diese Bitte an ein Backend, das nur eingebaute Stimmnamen kennt. Piper
rettete sich in seine Standardstimme (so gebaut, damit eine unbekannte Stimme
nicht in Stille endet) und antwortete mit 200 - der Fehler war also nur als
`VoiceNotFoundError` im piper-Log sichtbar, zwoelf Tage lang, waehrend das
Briefing jeden Morgen mit der falschen Stimme sprach.

Die Lehre steckt in der Zuordnung: eine Stimmdatei kann nur XTTS erfuellen. Wer
eine nennt, hat damit das Backend gewaehlt, auch ohne `engine=` zu schreiben.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.server import waehle_engine  # noqa: E402


def test_stimmdatei_waehlt_xtts_auch_ohne_engine_feld():
    assert waehle_engine(None, None, "stimme-de-frau.wav", "piper") == "xtts", (
        "eine geklonte Stimme kann Piper strukturell nicht liefern"
    )


def test_gross_und_kleinschreibung_und_leerzeichen_stoeren_nicht():
    assert waehle_engine(None, None, " Stimme-DE-Frau.WAV ", "piper") == "xtts"


def test_eingebaute_piper_stimme_bleibt_bei_der_vorgabe():
    # Genau der Unterschied: ein Name ohne Dateiendung ist eine Piper-Stimme.
    assert waehle_engine(None, None, "de_DE-thorsten_emotional-medium", "piper") == "piper"


def test_ohne_stimme_gilt_die_vorgabe():
    assert waehle_engine(None, None, None, "piper") == "piper"
    assert waehle_engine(None, None, "", "piper") == "piper"


def test_ausdrueckliche_wahl_gewinnt_gegen_die_stimme():
    # Der Rueckweg muss eine Entscheidung bleiben: wer trotz Stimmdatei Piper
    # will (etwa fuer eine schnelle Ansage), bekommt Piper.
    assert waehle_engine(None, "piper", "stimme-de-frau.wav", "piper") == "piper"
    assert waehle_engine("piper", None, "stimme-de-frau.wav", "xtts") == "piper"


def test_kopfzeile_schlaegt_feld():
    assert waehle_engine("xtts", "piper", None, "piper") == "xtts"
