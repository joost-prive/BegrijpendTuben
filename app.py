# ============================================================
# BegrijpendTuben - Flask Backend
#
# Twee modi (schakelbaar via USE_AI in .env of omgevingsvariabele):
#   USE_AI=false  →  dummy-vragen uit questions.json  (prototype)
#   USE_AI=true   →  echte vragen via OpenAI ChatGPT API
#
# Video-systeem:
#   - Haalt automatisch de 20 nieuwste filmpjes op via YouTube RSS
#   - Kanalen: Het Klokhuis + NOS Jeugdjournaal
#   - Elke 7 dagen worden de 5 oudste vervangen door 5 nieuwe
# ============================================================

import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Fix Windows console encoding zodat emoji's in print() niet crashen
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# ── Configuratie uit omgevingsvariabelen ───────────────────
def _laad_env():
    pad = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(pad):
        with open(pad, encoding="utf-8") as f:
            for regel in f:
                regel = regel.strip()
                if regel and not regel.startswith("#") and "=" in regel:
                    sleutel, waarde = regel.split("=", 1)
                    os.environ.setdefault(sleutel.strip(), waarde.strip())

_laad_env()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
USE_AI         = os.environ.get("USE_AI", "false").lower() == "true"

# ── OpenAI client (alleen aanmaken als USE_AI=true) ────────
_openai_client = None
if USE_AI:
    try:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        print("✅ OpenAI API-verbinding klaar")
    except ImportError:
        print("⚠️  openai package niet geïnstalleerd. Voer uit: pip install openai")
        USE_AI = False


# ══════════════════════════════════════════════════════════
#  YouTube RSS – automatisch videos ophalen
# ══════════════════════════════════════════════════════════

# Nederlandstalige educatieve YouTube-kanalen
KANALEN = [
    {
        "naam":       "Het Klokhuis",
        "channel_id": "UC1rz0CNVZBUAlnk1xrlrjAw",
        "categorie":  "Wetenschap",
        "emoji":      "🔬",
    },
    {
        "naam":       "Jeugdjournaal",
        "channel_id": "UC-bbHiTZGWKbsCjpzUfrk6Q",
        "categorie":  "Nieuws",
        "emoji":      "📰",
    },
    {
        "naam":       "De Buitendienst",
        "channel_id": "UCfShWs-d9Kx8zmiKULvog2g",
        "categorie":  "Dieren",
        "emoji":      "🐾",
    },
    {
        "naam":       "Vroege Vogels",
        "channel_id": "UCX8tlPIkOkeeRmtTweswP6w",
        "categorie":  "Natuur",
        "emoji":      "🌿",
    },
    {
        "naam":       "Klaas Kan Alles",
        "channel_id": "UCCaOWydWlVe6f1HJjtXc6xw",
        "categorie":  "Ruimte",
        "emoji":      "🚀",
    },
    {
        "naam":       "Jort Kelder Geschiedenis",
        "channel_id": "UCJZ5YSBIxTywVEtRmm0oJfQ",
        "categorie":  "Geschiedenis",
        "emoji":      "🏛️",
    },
]

ACTIEVE_VIDEOS_PAD = os.path.join(DATA_DIR, "active_videos.json")
MAX_VIDEOS    = 60   # maximaal aantal actieve videos
ROTATIE_BATCH = 5    # hoeveel videos per week worden vervangen
ROTATIE_DAGEN = 7    # na hoeveel dagen wordt geroteerd


def _fetch_rss_videos(channel_id, naam, categorie, emoji, max_items=10):
    """
    Haalt de laatste videos op via de YouTube RSS feed van een kanaal.
    Geeft een lijst van video-dicts terug.
    """
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "BegrijpendTuben/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        ns = {
            "atom":  "http://www.w3.org/2005/Atom",
            "yt":    "http://www.youtube.com/xml/schemas/2015",
            "media": "http://search.yahoo.com/mrss/",
        }

        vandaag = datetime.now().strftime("%Y-%m-%d")
        videos  = []

        for entry in root.findall("atom:entry", ns)[:max_items]:
            vid_el   = entry.find("yt:videoId", ns)
            titel_el = entry.find("atom:title",  ns)
            if vid_el is None or titel_el is None:
                continue

            beschrijving = ""
            media_group  = entry.find("media:group", ns)
            if media_group is not None:
                desc_el = media_group.find("media:description", ns)
                if desc_el is not None and desc_el.text:
                    beschrijving = desc_el.text[:200].replace("\n", " ").strip()

            videos.append({
                "id":           vid_el.text,
                "titel":        titel_el.text or "Onbekend filmpje",
                "beschrijving": beschrijving or f"Filmpje van {naam}.",
                "categorie":    categorie,
                "kanaal":       naam,
                "emoji":        emoji,
                "thumbnail":    f"https://img.youtube.com/vi/{vid_el.text}/mqdefault.jpg",
                "tags":         [naam.lower().replace(" ", ""), categorie.lower()],
                "toegevoegd":   vandaag,   # datum waarop video in de app is gezet
            })

        return videos

    except Exception as e:
        print(f"⚠️  RSS fout voor {naam}: {e}")
        return []


def _laad_actieve_videos():
    """Laad de actieve videolijst uit het JSON-bestand."""
    if os.path.exists(ACTIEVE_VIDEOS_PAD):
        try:
            with open(ACTIEVE_VIDEOS_PAD, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _sla_actieve_videos_op(videos):
    """Sla de actieve videolijst op in het JSON-bestand."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ACTIEVE_VIDEOS_PAD, "w", encoding="utf-8") as f:
            json.dump(videos, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️  Kon videos niet opslaan: {e}")


def _haal_en_roteer_videos():
    """
    Geeft de actieve videolijst terug (max. 20 videos).

    Logica:
    - Eerste keer (of leeg bestand): vul met RSS-videos.
    - Elke 7 dagen: vervang de 5 oudste door 5 nieuwe van de RSS-feeds.
    - Als RSS niet bereikbaar is: geef de bestaande lijst terug.
    """
    actieve = _laad_actieve_videos()
    nu      = datetime.now()

    # ── Eerste keer of bijna leeg ─────────────────────────
    if len(actieve) < 5:
        print("📺 Eerste keer videos ophalen via RSS...")
        alle = []
        for k in KANALEN:
            alle.extend(
                _fetch_rss_videos(k["channel_id"], k["naam"],
                                  k["categorie"], k["emoji"])
            )
        if alle:
            actieve = alle[:MAX_VIDEOS]
            _sla_actieve_videos_op(actieve)
            print(f"✅ {len(actieve)} videos geladen uit RSS")
        else:
            print("⚠️  RSS niet bereikbaar bij eerste start")
        return actieve

    # ── Controleer of wekelijkse rotatie nodig is ────────
    actieve.sort(key=lambda v: v.get("toegevoegd", "2000-01-01"))
    try:
        oudste_datum = datetime.strptime(actieve[0]["toegevoegd"], "%Y-%m-%d")
    except ValueError:
        oudste_datum = nu - timedelta(days=8)   # Forceer rotatie bij ongeldig formaat

    if (nu - oudste_datum).days < ROTATIE_DAGEN:
        return actieve   # Nog geen rotatie nodig

    # ── Rotatie: verwijder 5 oudste, voeg 5 nieuw toe ────
    print(f"🔄 Wekelijkse rotatie: {ROTATIE_BATCH} videos worden vervangen...")
    actieve       = actieve[ROTATIE_BATCH:]           # Verwijder 5 oudste
    bestaande_ids = {v["id"] for v in actieve}

    alle_nieuw = []
    for k in KANALEN:
        alle_nieuw.extend(
            _fetch_rss_videos(k["channel_id"], k["naam"],
                              k["categorie"], k["emoji"], max_items=15)
        )

    te_voegen = [v for v in alle_nieuw
                 if v["id"] not in bestaande_ids][:ROTATIE_BATCH]
    actieve.extend(te_voegen)

    _sla_actieve_videos_op(actieve)
    print(f"✅ Rotatie klaar: +{len(te_voegen)} nieuwe videos, totaal {len(actieve)}")
    return actieve


# ══════════════════════════════════════════════════════════
#  Vraag-systeem
# ══════════════════════════════════════════════════════════

def _laad_dummy_vragen(video_id: str) -> list:
    """Laadt hardgecodeerde vragen uit questions.json."""
    pad = os.path.join(DATA_DIR, "questions.json")
    with open(pad, encoding="utf-8") as f:
        alle_vragen = json.load(f)
    if video_id in alle_vragen:
        return alle_vragen[video_id]
    return alle_vragen.get("standaard", [])


def _genereer_vragen_met_ai(video_id: str, video_titel: str, video_beschrijving: str) -> list:
    """Vraagt ChatGPT om 5 meerkeuze-vragen te maken over de video."""
    prompt = f"""Je bent een leuke, kindvriendelijke leraar voor kinderen van 8 jaar.

Er is net een YouTube-filmpje bekeken met de volgende informatie:
- Titel: {video_titel}
- Beschrijving: {video_beschrijving}

Maak precies 5 meerkeuze-vragen over dit filmpje, passend voor een kind van 8 jaar.
Gebruik eenvoudige, duidelijke taal.

Geef je antwoord ALLEEN als geldige JSON (geen extra tekst erbuiten), in dit exacte formaat:
[
  {{
    "vraag": "Wat is de vraag?",
    "opties": ["Optie A", "Optie B", "Optie C"],
    "correct": "Optie A",
    "uitleg": "Korte uitleg waarom dit het goede antwoord is."
  }}
]

Regels:
- Precies 3 antwoordopties per vraag
- Precies 1 correct antwoord
- De uitleg is maximaal 1 zin
- Alles in het Nederlands
"""

    response = _openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Je geeft altijd antwoord als pure JSON, zonder markdown of uitleg eromheen."},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.7,
        max_tokens=1000,
    )

    tekst = response.choices[0].message.content.strip()

    if tekst.startswith("```"):
        tekst = tekst.split("```")[1]
        if tekst.startswith("json"):
            tekst = tekst[4:]
        tekst = tekst.strip()

    return json.loads(tekst)


def laad_vragen(video_id: str, video_titel: str = "", video_beschrijving: str = "") -> list:
    """Geeft vragen terug (AI of dummy, afhankelijk van USE_AI)."""
    if USE_AI and _openai_client:
        try:
            return _genereer_vragen_met_ai(video_id, video_titel, video_beschrijving)
        except Exception as fout:
            print(f"⚠️  OpenAI-fout, val terug op dummy-vragen: {fout}")
            return _laad_dummy_vragen(video_id)
    else:
        return _laad_dummy_vragen(video_id)


# ══════════════════════════════════════════════════════════
#  Routes
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/videos")
def get_videos():
    """
    Geeft de actieve videolijst terug (max. 20 videos).
    Videos worden automatisch wekelijks ververst via RSS.
    """
    videos = _haal_en_roteer_videos()
    return jsonify(videos)


@app.route("/api/search")
def search_videos():
    """
    Zoek door de videolijst op titel, kanaal en tags.
    Query-parameter: ?q=zoekwoord&categorie=Nieuws (optioneel)
    """
    zoekterm   = request.args.get("q", "").lower().strip()
    cat_filter = request.args.get("categorie", "").strip()

    alle_videos = _haal_en_roteer_videos()

    resultaten = []
    for video in alle_videos:
        if cat_filter and video["categorie"] != cat_filter:
            continue
        if zoekterm:
            zoekbaar = (
                video["titel"] + " " +
                video.get("kanaal", "") + " " +
                " ".join(video.get("tags", []))
            ).lower()
            if zoekterm not in zoekbaar:
                continue
        resultaten.append(video)

    return jsonify(resultaten[:12])


@app.route("/api/questions")
def get_questions():
    """Geeft meerkeuze-vragen terug voor een video."""
    video_id     = request.args.get("video_id",     "standaard")
    titel        = request.args.get("titel",        "Educatieve video")
    beschrijving = request.args.get("beschrijving", "")

    vragen = laad_vragen(video_id, titel, beschrijving)

    return jsonify({
        "video_id": video_id,
        "vragen":   vragen,
        "totaal":   len(vragen),
        "bron":     "ai" if (USE_AI and _openai_client) else "dummy",
    })


@app.route("/api/status")
def get_status():
    """Geeft terug of de AI-modus actief is en hoeveel videos er actief zijn."""
    actieve = _laad_actieve_videos()
    return jsonify({
        "ai_actief":         USE_AI and _openai_client is not None,
        "model":             "gpt-4o-mini" if USE_AI else "dummy",
        "api_key_ingesteld": bool(OPENAI_API_KEY),
        "actieve_videos":    len(actieve),
        "kanalen":           [k["naam"] for k in KANALEN],
    })


# ══════════════════════════════════════════════════════════
#  Start server
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    modus = "🤖 AI-modus (ChatGPT)" if (USE_AI and _openai_client) else "📋 Dummy-modus"
    print("====================================")
    print("   BegrijpendTuben gestart!")
    print(f"   Modus: {modus}")
    print("   Open: http://localhost:5000")
    print("====================================")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
