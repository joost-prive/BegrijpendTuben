# ============================================================
# BegrijpendTuben - Flask Backend
#
# Twee modi (schakelbaar via USE_AI in .env of omgevingsvariabele):
#   USE_AI=false  →  dummy-vragen uit questions.json  (prototype)
#   USE_AI=true   →  echte vragen via OpenAI ChatGPT API
#
# Stel je API-sleutel in via .env:
#   OPENAI_API_KEY=sk-...
#   USE_AI=true
# ============================================================

import json
import os
import sys

# Fix Windows console encoding zodat emoji's in print() niet crashen
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# ── Configuratie uit omgevingsvariabelen ───────────────────
#    Laad .env bestand als dat bestaat
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


# ── Dummy-vragen (fallback / prototype) ───────────────────
def _laad_dummy_vragen(video_id: str) -> list:
    """Laadt hardgecodeerde vragen uit questions.json."""
    pad = os.path.join(DATA_DIR, "questions.json")
    with open(pad, encoding="utf-8") as f:
        alle_vragen = json.load(f)
    if video_id in alle_vragen:
        return alle_vragen[video_id]
    return alle_vragen.get("standaard", [])


# ── AI-vragen via OpenAI ChatGPT ───────────────────────────
def _genereer_vragen_met_ai(video_id: str, video_titel: str, video_beschrijving: str) -> list:
    """
    Vraagt ChatGPT om 5 meerkeuze-vragen te maken over de video.

    De prompt stuurt de video-titel en -beschrijving mee.
    Zodra je ook een transcript hebt (via YouTube Transcript API),
    kun je dat toevoegen aan de prompt voor veel betere vragen.
    """
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
        model="gpt-4o-mini",   # Goedkoop en snel; vervang door "gpt-4o" voor betere kwaliteit
        messages=[
            {"role": "system", "content": "Je geeft altijd antwoord als pure JSON, zonder markdown of uitleg eromheen."},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.7,
        max_tokens=1000,
    )

    tekst = response.choices[0].message.content.strip()

    # Verwijder eventuele markdown code-blokken (```json ... ```)
    if tekst.startswith("```"):
        tekst = tekst.split("```")[1]
        if tekst.startswith("json"):
            tekst = tekst[4:]
        tekst = tekst.strip()

    vragen = json.loads(tekst)
    return vragen


# ── Hoofd-functie: kies dummy of AI ───────────────────────
def laad_vragen(video_id: str, video_titel: str = "", video_beschrijving: str = "") -> list:
    """
    Geeft vragen terug. Kiest automatisch tussen:
      - AI-gegenereerde vragen  (als USE_AI=true en API-sleutel ingesteld)
      - Dummy-vragen uit JSON   (standaard / fallback)
    """
    if USE_AI and _openai_client:
        try:
            return _genereer_vragen_met_ai(video_id, video_titel, video_beschrijving)
        except Exception as fout:
            print(f"⚠️  OpenAI-fout, val terug op dummy-vragen: {fout}")
            return _laad_dummy_vragen(video_id)
    else:
        return _laad_dummy_vragen(video_id)


# ── Routes ─────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/videos")
def get_videos():
    """
    Gecureerde lijst van kindvriendelijke educatieve video's.
    Elke video heeft tags voor de zoekfunctie.
    Video's zijn geselecteerd op: minimaal 3 min, geschikt voor 6-10 jaar,
    geen geweld/reclame, educatief.
    """
    videos = [
        # ── Natuur ──────────────────────────────────────────
        {
            "id": "V5RSpMQQOpw",
            "titel": "Van rups tot vlinder",
            "beschrijving": "Hoe verandert een rups in een prachtige vlinder?",
            "categorie": "Natuur",
            "emoji": "🦋",
            "tags": ["vlinder", "natuur", "dieren", "insecten", "metamorfose", "rups"],
        },
        {
            "id": "tkFPyue5X3Q",
            "titel": "Hoe groeit een zaadje?",
            "beschrijving": "Leer hoe een zaadje uitgroeit tot een grote plant.",
            "categorie": "Natuur",
            "emoji": "🌱",
            "tags": ["planten", "natuur", "groeien", "zaadje", "bloem", "fotosynthese"],
        },
        {
            "id": "ZFk0xhqT5fQ",
            "titel": "Haaien: koningen van de oceaan",
            "beschrijving": "Ontdek de wonderlijke wereld van haaien en de oceaan!",
            "categorie": "Natuur",
            "emoji": "🦈",
            "tags": ["haai", "oceaan", "zee", "vissen", "dieren", "water", "natuur"],
        },
        {
            "id": "ta154f5Rp5Y",
            "titel": "Drukke bijen!",
            "beschrijving": "Leer alles over hommels en honingbijen en hoe ze honing maken.",
            "categorie": "Natuur",
            "emoji": "🐝",
            "tags": ["bijen", "honing", "natuur", "insecten", "bijenkorf", "bloemen"],
        },
        {
            "id": "xB2DiiAOpCg",
            "titel": "De wetenschap van de herfst",
            "beschrijving": "Waarom vallen bladeren? Ontdek de geheimen van het herfstseizoen!",
            "categorie": "Natuur",
            "emoji": "🍂",
            "tags": ["seizoenen", "natuur", "herfst", "bladeren", "bomen", "lente", "winter", "weer"],
        },
        # ── Wetenschap ──────────────────────────────────────
        {
            "id": "b79xio8qgiY",
            "titel": "Gebruik je brein!",
            "beschrijving": "Ontdek de geheimen van je eigen brein!",
            "categorie": "Wetenschap",
            "emoji": "🧠",
            "tags": ["brein", "lichaam", "wetenschap", "hersenen", "denken", "biologie"],
        },
        {
            "id": "_aAmaCeq9v4",
            "titel": "Waarom slapen we?",
            "beschrijving": "Ontdek waarom slaap zo belangrijk is voor je lichaam.",
            "categorie": "Wetenschap",
            "emoji": "😴",
            "tags": ["slapen", "lichaam", "wetenschap", "dromen", "gezondheid", "brein"],
        },
        {
            "id": "K7Oq9_DU1Mc",
            "titel": "Alles over vulkanen!",
            "beschrijving": "Leer hoe vulkanen ontstaan en waarom ze uitbarsten.",
            "categorie": "Wetenschap",
            "emoji": "🌋",
            "tags": ["vulkaan", "aarde", "geologie", "wetenschap", "lava", "magma"],
        },
        {
            "id": "R0K7VKkksyc",
            "titel": "Waar komt water vandaan?",
            "beschrijving": "De watercyclus uitgelegd: van oceaan naar wolk naar regen!",
            "categorie": "Wetenschap",
            "emoji": "🌧️",
            "tags": ["regen", "water", "wolken", "weer", "watercyclus", "wetenschap", "natuur"],
        },
        {
            "id": "WwapH400lrE",
            "titel": "Alles over je lichaam!",
            "beschrijving": "Hoe werken je botten, spieren en organen?",
            "categorie": "Wetenschap",
            "emoji": "🫀",
            "tags": ["lichaam", "biologie", "wetenschap", "organen", "botten", "spieren", "hart"],
        },
        # ── Ruimte ──────────────────────────────────────────
        {
            "id": "K6dqHEoj-AU",
            "titel": "Het zonnestelsel",
            "beschrijving": "Reis langs alle planeten in ons zonnestelsel.",
            "categorie": "Ruimte",
            "emoji": "🪐",
            "tags": ["ruimte", "planeten", "zonnestelsel", "zon", "maan", "sterren", "saturnus"],
        },
        {
            "id": "0rHUDWjR5gg",
            "titel": "Introductie astronomie",
            "beschrijving": "Wat is astronomie? Ontdek hoe oud sterren zijn en hoe ver ze weg zijn.",
            "categorie": "Ruimte",
            "emoji": "⭐",
            "tags": ["sterren", "ruimte", "heelal", "zon", "licht", "melkweg", "astronomie"],
        },
        {
            "id": "yXe0yxzYkjo",
            "titel": "Waarom verandert de maan?",
            "beschrijving": "Waarom zien we de maan elke nacht anders? En hoe ver is hij weg?",
            "categorie": "Ruimte",
            "emoji": "🌕",
            "tags": ["maan", "ruimte", "aarde", "nacht", "planeten", "maanfases", "astronaut"],
        },
        # ── Dieren ──────────────────────────────────────────
        {
            "id": "gwH8xGmqGmo",
            "titel": "Bijzondere dierengroepen",
            "beschrijving": "Ontdek hoe dieren samenwerken in groepen – van olifanten tot wolven!",
            "categorie": "Dieren",
            "emoji": "🐘",
            "tags": ["olifanten", "dieren", "savanne", "natuur", "zoogdieren", "samenwerken", "roedel"],
        },
        {
            "id": "TwfKCX_8fbA",
            "titel": "Pinguïns en ijsberen in de kou",
            "beschrijving": "Hoe overleven pinguïns en ijsberen in de ijskoude natuur?",
            "categorie": "Dieren",
            "emoji": "🐧",
            "tags": ["pinguins", "dieren", "zuidpool", "ijs", "vogels", "kou", "Antarctica", "ijsbeer"],
        },
        {
            "id": "JGcIp4YEKrc",
            "titel": "Dieren die hun leefgebied veranderen",
            "beschrijving": "Leer hoe wolven, olifanten en andere dieren hun omgeving veranderen.",
            "categorie": "Dieren",
            "emoji": "🐺",
            "tags": ["wolf", "dieren", "natuur", "ecosysteem", "olifant", "roofdieren", "leefgebied"],
        },
        # ── Geschiedenis ────────────────────────────────────
        {
            "id": "Z3Wvw6BivVI",
            "titel": "De oude Egyptenaren",
            "beschrijving": "Wie waren de oude Egyptenaren en hoe leefden ze?",
            "categorie": "Geschiedenis",
            "emoji": "🏛️",
            "tags": ["Egypte", "geschiedenis", "farao", "piramide", "mummies", "hiërogliefenfiets"],
        },
        {
            "id": "oXwoy-Ce1ZE",
            "titel": "Wat is er met de dinosaurussen gebeurd?",
            "beschrijving": "Wanneer leefden dinosaurussen en hoe zijn ze uitgestorven?",
            "categorie": "Geschiedenis",
            "emoji": "🦕",
            "tags": ["dinosaurus", "prehistorie", "fossiel", "uitgestorven", "geschiedenis", "T-rex"],
        },
    ]
    return jsonify(videos)


@app.route("/api/search")
def search_videos():
    """
    Zoek door de gecureerde videolijst op titel en tags.
    Query-parameter: ?q=zoekwoord&categorie=Natuur (optioneel)
    Geeft max 12 resultaten terug.
    """
    zoekterm    = request.args.get("q", "").lower().strip()
    cat_filter  = request.args.get("categorie", "").strip()

    # Haal alle videos op via de bestaande functie
    alle_videos = get_videos().get_json()

    resultaten = []
    for video in alle_videos:
        # Categoriefilter
        if cat_filter and video["categorie"] != cat_filter:
            continue
        # Zoekfilter: match op titel of tags
        if zoekterm:
            zoekbaar = (video["titel"] + " " + " ".join(video.get("tags", []))).lower()
            if zoekterm not in zoekbaar:
                continue
        resultaten.append(video)

    return jsonify(resultaten[:12])


@app.route("/api/questions")
def get_questions():
    """
    Geeft meerkeuze-vragen terug voor een video.

    Query-parameters:
      video_id     → YouTube video ID
      titel        → Videotitel (voor AI-prompt)
      beschrijving → Videobeschrijving (voor AI-prompt)
    """
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
    """Geeft terug of de AI-modus actief is (handig voor debugging)."""
    return jsonify({
        "ai_actief":    USE_AI and _openai_client is not None,
        "model":        "gpt-4o-mini" if USE_AI else "dummy",
        "api_key_ingesteld": bool(OPENAI_API_KEY),
    })


# ── Start server ───────────────────────────────────────────

if __name__ == "__main__":
    modus = "🤖 AI-modus (ChatGPT)" if (USE_AI and _openai_client) else "📋 Dummy-modus"
    print("====================================")
    print(f"   BegrijpendTuben gestart!")
    print(f"   Modus: {modus}")
    print("   Open: http://localhost:5000")
    print("====================================")
    # Gebruik PORT omgevingsvariabele als die bestaat (vereist door Railway/Render)
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
