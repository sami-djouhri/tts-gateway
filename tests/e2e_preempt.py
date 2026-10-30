"""Live-Preemption-Beweis: Batch (mehrere Chunks) laeuft, kurz danach kommt ein
interaktiver Request. Erwartung: interaktiv ueberholt an der Chunk-Grenze und ist
FRUEHER fertig, obwohl spaeter gestartet. Aufruf: python tests/e2e_preempt.py
"""
import threading
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8146"
# 3 lange Saetze -> 3 Chunks (jeder <=400 Zeichen).
BATCH_TEXT = (
    "Dies ist der erste lange Abschnitt eines simulierten Nachrichten-Briefings, "
    "der bewusst viele Woerter enthaelt, damit er einen eigenen Synthese-Chunk fuellt. "
    + "Und hier folgt der zweite ausfuehrliche Abschnitt des Briefings mit weiteren "
    "Saetzen, sodass auch dieser Teil als eigener Chunk gerendert werden muss. "
    + "Schliesslich kommt der dritte und letzte Abschnitt, der das Briefing abrundet "
    "und ebenfalls genug Text besitzt, um einen dritten Chunk zu erzeugen."
)
INT_TEXT = "Wie spaet ist es?"

results = {}


def call(name, text, priority):
    data = urllib.parse.urlencode({"text": text}).encode()
    req = urllib.request.Request(BASE + "/api/tts", data=data, method="POST")
    req.add_header("X-TTS-Priority", priority)
    t0 = time.monotonic()
    status = 0
    nbytes = 0
    try:
        with urllib.request.urlopen(req, timeout=400) as r:
            status = r.status
            nbytes = len(r.read())
    except Exception as exc:  # noqa: BLE001
        status = -1
        nbytes = 0
        results[name + "_err"] = str(exc)[:200]
    results[name] = {"status": status, "bytes": nbytes, "done_at": time.monotonic() - t0}


def main():
    start = time.monotonic()
    tb = threading.Thread(target=call, args=("batch", BATCH_TEXT, "batch"))
    tb.start()
    time.sleep(2)  # Batch-Chunk 0 rendert bereits
    ti = threading.Thread(target=call, args=("interactive", INT_TEXT, "interactive"))
    ti.start()
    ti.join()
    tb.join()

    b = results.get("batch", {})
    i = results.get("interactive", {})
    print(f"batch:       status={b.get('status')} bytes={b.get('bytes')} done_at={b.get('done_at',0):.1f}s")
    print(f"interactive: status={i.get('status')} bytes={i.get('bytes')} done_at={i.get('done_at',0):.1f}s "
          f"(2s spaeter gestartet)")
    if results.get("batch_err"):
        print("batch_err:", results["batch_err"])
    if results.get("interactive_err"):
        print("interactive_err:", results["interactive_err"])

    # interaktiv (2s spaeter gestartet) muss deutlich frueher fertig sein als der Batch
    ok = (
        i.get("status") == 200
        and b.get("status") == 200
        and i.get("done_at", 1e9) + 2 < b.get("done_at", 0)
    )
    print("PREEMPTION OK" if ok else "PREEMPTION FAILED")


if __name__ == "__main__":
    main()
