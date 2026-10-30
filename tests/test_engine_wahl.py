"""Welches Backend eine Anfrage bedient, wenn der Aufrufer es nicht sagt.

GEFUNDEN AM 2026-09-18, an der schlechten Stimme des Morgen-Briefings:

`saganta-news-api` bittet den Gateway seit jeher um `stimme-de-frau.wav`, die
geklonte Stimme aus XTTS. Seit der Vorgabe-Umstellung auf Piper am 2026-09-06
ging diese Bitte an ein Backend, das nur eingebaute Stimmnamen kennt. Piper
rettete sich in seine Standardstimme (so gebaut, damit eine unbekannte Stimme
nicht in Stille endet) und antwortete mit 200, der Fehler war also nur als
`VoiceNotFoundError` im piper-Log sichtbar, zwoelf Tage lang, waehrend das
Briefing jeden Morgen mit der falschen Stimme sprach.

Die Lehre steckt in der Zuordnung: eine Stimmdatei kann Piper nicht erfuellen.
Wer eine nennt, hat damit die andere Lane gewaehlt, auch ohne `engine=` zu
schreiben.

NACHTRAG 2026-10-11: auf `.22:5002` antwortet seit heute **Kokoro** statt
Coqui-XTTS, und `kokoro` ist auch die neue Vorgabe („Piper ist auf jeden
Fall nicht gut genug"). `xtts` bleibt als Altname gueltig und wird uebersetzt,
weil drei Konsumenten ihn fuehren. Diese Faelle halten beides fest: dass der
alte Name weiter traegt, und dass er nicht mehr der richtige ist.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.server import ALTNAMEN, waehle_engine  # noqa: E402


def test_stimmdatei_waehlt_die_queue_lane_auch_ohne_engine_feld():
    assert waehle_engine(None, None, "stimme-de-frau.wav", "piper") == "kokoro", (
        "eine geklonte Stimme kann Piper strukturell nicht liefern"
    )


def test_gross_und_kleinschreibung_und_leerzeichen_stoeren_nicht():
    assert waehle_engine(None, None, " Stimme-DE-Frau.WAV ", "piper") == "kokoro"


def test_eingebaute_piper_stimme_bleibt_bei_der_vorgabe():
    # Genau der Unterschied: ein Name ohne Dateiendung ist eine Piper-Stimme.
    assert waehle_engine(None, None, "de_DE-thorsten_emotional-medium", "piper") == "piper"


def test_ohne_stimme_gilt_die_vorgabe():
    assert waehle_engine(None, None, None, "piper") == "piper"
    assert waehle_engine(None, None, "", "piper") == "piper"
    assert waehle_engine(None, None, None, "kokoro") == "kokoro"


def test_ausdrueckliche_wahl_gewinnt_gegen_die_stimme():
    # Der Rueckweg muss eine Entscheidung bleiben: wer trotz Stimmdatei Piper
    # will (etwa fuer eine schnelle Ansage), bekommt Piper.
    assert waehle_engine(None, "piper", "stimme-de-frau.wav", "piper") == "piper"
    assert waehle_engine("piper", None, "stimme-de-frau.wav", "kokoro") == "piper"


def test_kopfzeile_schlaegt_feld():
    assert waehle_engine("xtts", "piper", None, "piper") == "kokoro"


# --- Die Altnamen -------------------------------------------------------

def test_alter_name_xtts_landet_bei_kokoro():
    """Auf `.22:5002` laeuft seit dem 2026-10-11 Kokoro.

    Der Name `xtts` steht in drei fremden Konfigurationen und bleibt deshalb
    gueltig. Er wird aber UEBERSETZT und nicht stillschweigend weiterbenutzt:
    das ist der Unterschied zum Alias `node2-gemma`, hinter dem seit Wochen kein
    Gemma mehr steckt und unter dem die Gateway-Datenbank Aufrufe verbucht, die
    nie an ein Gemma gingen.
    """
    assert waehle_engine(None, "xtts", None, "piper") == "kokoro"
    assert waehle_engine("XTTS", None, None, "piper") == "kokoro"
    assert waehle_engine(None, "coqui", None, "piper") == "kokoro"


def test_altname_als_vorgabe_wird_ebenfalls_uebersetzt():
    """Sonst bliebe genau ein Weg ungeuebersetzt: ein `TTS_ENGINE_DEFAULT=xtts`
    aus der Zeit davor. Der Dienst liefe dann mit einem Backend-Namen, den der
    Broker nicht kennt, und das faellt erst beim ersten Satz auf."""
    assert waehle_engine(None, None, None, "xtts") == "kokoro"


def test_unbekannter_name_wird_nicht_erfunden():
    """Was nicht in der Tabelle steht, geht unveraendert durch. Ein stiller
    Rueckfall auf die Vorgabe waere schlimmer als eine klare Absage weiter
    unten: er machte aus einem Tippfehler eine andere Stimme."""
    assert waehle_engine(None, "tippfehler", None, "kokoro") == "tippfehler"


def test_die_tabelle_zeigt_nur_auf_echte_backends():
    """Gegenprobe gegen eine Uebersetzung, die ins Leere laeuft."""
    assert set(ALTNAMEN.values()) <= {"kokoro", "piper"}
