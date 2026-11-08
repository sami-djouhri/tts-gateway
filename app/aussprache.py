"""Aussprache-Woerterbuch: englische Woerter, die eine deutsche Stimme falsch liest.

Die Stimmen lesen nach deutscher Lautregel. „IT" wird so zu „it" wie in
„mit", „Trump" zu „Trump" mit deutschem u (gemeldet 2026-11-06 aus dem
Briefing). Hier steht je Wort eine deutsche Umschreibung, die nach genau dieser
Regel richtig klingt. Gepflegt wird die Liste nur hier (Entscheid
2026-11-06), nicht bei den Aufrufern.

Vier Dinge sind daran Absicht:

- Ganze Woerter, Gross- und Kleinschreibung zaehlt. „IT" ist die Abkuerzung,
  „it" in einem englischen Zitat nicht, und „Team" darf in „Teamarbeit" nicht
  greifen. Wer beide Schreibweisen braucht, traegt beide ein.
- Nur fuer Deutsch. Ein englischer Text an eine englische Stimme bleibt, wie
  er ist.
- Ein Bindestrich davor sperrt („E-Cloud" bleibt), einer danach nicht
  („IT-Branche" wird umgeschrieben).
- Laengere Eintraege zuerst, damit „New York" vor einem Eintrag „New" greift.
"""
from __future__ import annotations

import re

WOERTER: dict[str, str] = {
    # Abkuerzungen
    "IT": "Ei Tie",
    "CEO": "Si I Oh",
    "AI": "Ei Ei",
    "ChatGPT": "Tschätt Dschi Pi Tie",
    "OpenAI": "Ohpen Ei Ei",
    "iPhone": "Ei-Fohn",
    "iPad": "Ei-Päd",
    # Namen aus den Nachrichten
    "Trump": "Trampp",
    "Biden": "Beiden",
    "Musk": "Mask",
    "Elon": "Ielon",
    "Harris": "Härris",
    "Washington": "Woschington",
    "White House": "Weit Haus",
    "New York": "Nju York",
    "Silicon Valley": "Silikon Wälli",
    "Google": "Guhgel",
    "Apple": "Äppel",
    "Microsoft": "Maikrosoft",
    "Facebook": "Fäisbuck",
    "WhatsApp": "Wotts-Äpp",
    "Amazon": "Ämason",
    "YouTube": "Ju-Tjub",
    # Alltagswoerter
    "Update": "Apdäit",
    "Updates": "Apdäits",
    "Software": "Softwär",
    "Hardware": "Hardwär",
    "online": "onlain",
    "Online": "Onlain",
    "offline": "offlain",
    "Offline": "Offlain",
    "Smartphone": "Smartfohn",
    "Smartphones": "Smartfohns",
    "Team": "Tiem",
    "Teams": "Tiems",
    "Meeting": "Mieting",
    "Download": "Daunlohd",
    "Startup": "Startapp",
    "Start-up": "Startapp",
    "Streaming": "Strieming",
    "Cloud": "Klaud",
    "Cyber": "Saiber",
    "Server": "Sörwer",
    "Router": "Rauter",
    "Gaming": "Geiming",
    "Homeoffice": "Hohm-Office",
    "Black Friday": "Bläck Fraidei",
}

_MUSTER = re.compile(
    r"(?<![\w-])("
    + "|".join(re.escape(w) for w in sorted(WOERTER, key=len, reverse=True))
    + r")(?!\w)"
)


def aussprechbar(text: str, language: str | None = "de") -> str:
    """Ersetzt bekannte englische Woerter durch ihre deutsche Umschreibung."""
    if not text or (language or "de").lower()[:2] != "de":
        return text
    return _MUSTER.sub(lambda m: WOERTER[m.group(1)], text)
