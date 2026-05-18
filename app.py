# ============================================================
# BegrijpendTuben - Flask Backend
#
# Twee modi (schakelbaar via USE_AI in .env of omgevingsvariabele):
#   USE_AI=false  →  dummy-vragen uit questions.json  (prototype)
#   USE_AI=true   →  echte vragen via OpenAI ChatGPT API
#
# Video-systeem:
#   - Haalt automatisch de 20 nieuwste filmpjes op via YouTube RSS
#   - Kanalen: Het Klokhuis + NOS Jeugdjournaal + meer
#   - Elke 7 dagen worden de 5 oudste vervangen door 5 nieuwe
#
# Niveau-filtering:
#   /           → alle filmpjes
#   /onderbouw  → alleen filmpjes geschikt voor groep 1-4
#   /bovenbouw  → alleen filmpjes geschikt voor groep 5-8
# ============================================================

import json
import os
import re
import sys
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Fix Windows console encoding zodat emoji's in print() niet crashen
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

try:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    _transcript_api_beschikbaar = True
except ImportError:
    _transcript_api_beschikbaar = False

app = Flask(__name__)
CORS(app)

def _get_ip():
    # Cloudflare stuurt het echte IP-adres via CF-Connecting-IP
    return request.headers.get("CF-Connecting-IP") or get_remote_address()

limiter = Limiter(
    key_func=_get_ip,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

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

OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "")
USE_AI           = os.environ.get("USE_AI", "false").lower() == "true"
YOUTUBE_API_KEY  = os.environ.get("YOUTUBE_API_KEY", "")
MAX_DUUR_SEC     = 240   # maximale filmpjesduur in seconden (4 minuten)

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

# ── Firestore (persistente cache, optioneel) ───────────────
_db = None

def _init_firebase():
    """
    Verbindt met Firestore via een service account JSON in de
    omgevingsvariabele FIREBASE_SERVICE_ACCOUNT.
    Zonder die variabele werkt de app gewoon met lokale JSON-bestanden.
    """
    global _db
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
    if not service_account_json:
        print("ℹ️  FIREBASE_SERVICE_ACCOUNT niet ingesteld — lokale JSON-cache wordt gebruikt")
        return
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore as _fs
        if not firebase_admin._apps:
            cred = credentials.Certificate(json.loads(service_account_json))
            firebase_admin.initialize_app(cred)
        _db = _fs.client()
        print("✅ Firestore verbinding klaar")
    except Exception as e:
        print(f"⚠️  Firebase init mislukt: {e}")

_init_firebase()


# ══════════════════════════════════════════════════════════
#  YouTube RSS – automatisch videos ophalen
# ══════════════════════════════════════════════════════════

# Nederlandstalige educatieve YouTube-kanalen
# channel_id vinden: ga naar het YouTube-kanaal en kopieer de ID uit de URL
# of paginabron (zoek op "channelId").
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
    {
        "naam":       "Schooltv",
        "channel_id": "UC-qTnFGdceHsShjF2zUSAlQ",
        "categorie":  "Educatie",
        "emoji":      "📚",
    },
    {
        "naam":       "Clipphanger",
        "channel_id": "UCmyAAcFzmkD5SHIa0olqhgw",
        "categorie":  "Wetenschap",
        "emoji":      "🎒",
    },
]

ACTIEVE_VIDEOS_PAD  = os.path.join(DATA_DIR, "active_videos.json")
VRAGEN_CACHE_PAD    = os.path.join(DATA_DIR, "questions_cache.json")
MAX_VIDEOS    = 60   # maximaal aantal actieve videos
ROTATIE_BATCH = 5    # hoeveel videos per week worden vervangen
ROTATIE_DAGEN = 7    # na hoeveel dagen wordt geroteerd


# ══════════════════════════════════════════════════════════
#  Niveau-classificatie (onderbouw / bovenbouw / alles)
# ══════════════════════════════════════════════════════════

_ONDERBOUW_KW = [
    'groep 1', 'groep 2', 'groep 3', 'groep 4',
    'groep1', 'groep2', 'groep3', 'groep4',
    'kleuter', 'kleutergroep', 'voor kleuters',
    'leren lezen', 'letters leren', 'cijfers leren',
    'beginnende lezers',
]

_BOVENBOUW_KW = [
    'groep 5', 'groep 6', 'groep 7', 'groep 8',
    'groep5', 'groep6', 'groep7', 'groep8',
    'bovenbouw', 'voortgezet onderwijs',
    'oorlog', 'klimaatverandering', 'verkiezingen', 'politiek',
    'economie', 'vluchtelingen', 'migratie', 'terrorisme',
    'seksualiteit', 'drugs', 'geweld', 'rampen', 'doodstraf',
    'kijkwijzer', 'angst en spanning', 'discriminatie',
]


# Keywords waarna credits/productie-info begint — geen inhoudelijke beschrijving
_CREDITS_KW = [
    'Credits:', 'credits:', 'Regie:', 'regie:', 'Animatie:', 'animatie:',
    'Productie:', 'productie:', 'Camera:', 'camera:', 'Muziek:', 'muziek:',
    'Tekst en regie', 'tekst en regie', 'Een productie van', 'een productie van',
    'Met dank aan', 'met dank aan', 'Meer informatie:', 'meer informatie:',
    'Volg ons', 'volg ons', 'Abonneer', 'abonneer', 'Subscribe', 'subscribe',
    'Kijk ook op', 'kijk ook op', '© ', 'www.', 'http',
]


def _filter_beschrijving(tekst: str) -> str:
    """
    Verwijdert credits/productie-info uit een YouTube-beschrijving.
    Kapt de tekst af bij het eerste credits-trefwoord.
    Geeft lege string terug als er te weinig echte inhoud overblijft.
    """
    if not tekst:
        return ""
    for kw in _CREDITS_KW:
        idx = tekst.find(kw)
        if idx != -1:
            tekst = tekst[:idx].strip().rstrip(',;:-')
    return tekst if len(tekst) >= 30 else ""


def _classificeer_niveau(titel: str, beschrijving: str) -> str:
    """
    Bepaalt het educatieve niveau op basis van titel en beschrijving.
    Kijkt eerst naar expliciete groep-aanduidingen (Schooltv-stijl),
    daarna naar moeilijke onderwerpen.
    Returns: 'onderbouw', 'bovenbouw', of 'alles'
    """
    tekst = (titel + " " + beschrijving).lower()

    for kw in _BOVENBOUW_KW:
        if kw in tekst:
            return 'bovenbouw'

    for kw in _ONDERBOUW_KW:
        if kw in tekst:
            return 'onderbouw'

    return 'alles'


def _parse_iso_duur(iso: str) -> int | None:
    """Zet ISO 8601-duur (PT4M30S) om naar seconden."""
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso or '')
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)


def _format_duur(seconden: int) -> str:
    """Formatteert seconden als 'M:SS'."""
    return f"{seconden // 60}:{seconden % 60:02d}"


def _haal_duuren_via_api(video_ids: list) -> dict:
    """
    Vraagt duur op via YouTube Data API v3.
    Geeft dict {video_id: seconden} terug.
    Vereist YOUTUBE_API_KEY.
    """
    duuren = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        params = urllib.parse.urlencode({
            'part': 'contentDetails',
            'id':   ','.join(batch),
            'key':  YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/videos?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BegrijpendTuben/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            for item in data.get('items', []):
                sec = _parse_iso_duur(item['contentDetails']['duration'])
                if sec is not None:
                    duuren[item['id']] = sec
        except Exception as e:
            print(f"⚠️  YouTube API fout: {e}")
    return duuren


def _filter_op_duur(videos: list) -> list:
    """
    Voegt duur toe aan elk video-object en filtert alles > MAX_DUUR_SEC weg.
    Vereist YOUTUBE_API_KEY. Zonder sleutel worden alle videos teruggegeven
    zonder duurinformatie.
    """
    if not YOUTUBE_API_KEY:
        return videos

    video_ids = [v["id"] for v in videos]
    duuren    = _haal_duuren_via_api(video_ids)

    gefilterd = []
    for v in videos:
        sec = duuren.get(v["id"])
        if sec is None or sec <= MAX_DUUR_SEC:
            v["duur"] = _format_duur(sec) if sec else None
            gefilterd.append(v)

    verwijderd = len(videos) - len(gefilterd)
    if verwijderd:
        print(f"⏱️  {verwijderd} video(s) gefilterd (langer dan {MAX_DUUR_SEC // 60} min)")
    return gefilterd


def _fetch_rss_videos(channel_id, naam, categorie, emoji, max_items=10):
    """
    Haalt de laatste videos op via de YouTube RSS feed van een kanaal.
    Geeft een lijst van video-dicts terug, inclusief niveau-classificatie.
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
                    # Neem meer tekst op zodat afkappen op woord mogelijk is,
                    # maar filter credits/productie-info eerst weg
                    rauw = desc_el.text[:500].replace("\n", " ").strip()
                    beschrijving = _filter_beschrijving(rauw)

            titel_tekst = titel_el.text or "Onbekend filmpje"
            niveau = _classificeer_niveau(titel_tekst, beschrijving)

            videos.append({
                "id":           vid_el.text,
                "titel":        titel_tekst,
                "beschrijving": beschrijving or f"Filmpje van {naam}.",
                "categorie":    categorie,
                "kanaal":       naam,
                "emoji":        emoji,
                "thumbnail":    f"https://img.youtube.com/vi/{vid_el.text}/mqdefault.jpg",
                "tags":         [naam.lower().replace(" ", ""), categorie.lower()],
                "toegevoegd":   vandaag,
                "niveau":       niveau,
            })

        return videos

    except Exception as e:
        print(f"⚠️  RSS fout voor {naam}: {e}")
        return []


def _laad_actieve_videos():
    """Laad de actieve videolijst: eerst Firestore, dan lokaal bestand."""
    if _db:
        try:
            doc = _db.collection('cache').document('active_videos').get()
            if doc.exists:
                videos = doc.to_dict().get('videos', [])
                if videos:
                    return videos
        except Exception as e:
            print(f"⚠️  Firestore videos laden mislukt: {e}")
    if os.path.exists(ACTIEVE_VIDEOS_PAD):
        try:
            with open(ACTIEVE_VIDEOS_PAD, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _sla_actieve_videos_op(videos):
    """Sla de actieve videolijst op in Firestore en/of lokaal bestand."""
    if _db:
        try:
            _db.collection('cache').document('active_videos').set({'videos': videos})
        except Exception as e:
            print(f"⚠️  Firestore videos opslaan mislukt: {e}")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ACTIEVE_VIDEOS_PAD, "w", encoding="utf-8") as f:
            json.dump(videos, f, ensure_ascii=False, indent=2)
        _invalideer_videos_cache()
    except Exception as e:
        print(f"⚠️  Kon videos niet opslaan: {e}")


def _haal_en_roteer_videos():
    """
    Geeft de actieve videolijst terug (max. MAX_VIDEOS videos).

    Logica:
    - Eerste keer (of leeg bestand): vul met RSS-videos.
    - Nieuwe kanalen (nog geen videos in lijst): meteen ophalen.
    - Elke 7 dagen: vervang de 5 oudste door 5 nieuwe van de RSS-feeds.
    - Als RSS niet bereikbaar is: geef de bestaande lijst terug.
    - Bestaande videos zonder 'niveau' krijgen automatisch een classificatie.
    """
    actieve = _laad_actieve_videos()
    nu      = datetime.now()

    # ── Voeg niveau toe aan bestaande videos zonder het veld ──
    gewijzigd = False
    for v in actieve:
        if "niveau" not in v:
            v["niveau"] = _classificeer_niveau(v.get("titel", ""), v.get("beschrijving", ""))
            gewijzigd = True
    if gewijzigd:
        _sla_actieve_videos_op(actieve)

    # ── Haal videos op voor kanalen die nog niet vertegenwoordigd zijn ──
    kanalen_aanwezig = {v.get("kanaal") for v in actieve}
    ontbrekende = [k for k in KANALEN if k["naam"] not in kanalen_aanwezig]
    if ontbrekende and len(actieve) >= 5:
        bestaande_ids = {v["id"] for v in actieve}
        for k in ontbrekende:
            print(f"🆕 Nieuw kanaal toevoegen: {k['naam']}")
            nieuw = _fetch_rss_videos(k["channel_id"], k["naam"], k["categorie"], k["emoji"])
            nieuw = _filter_op_duur(nieuw)
            te_voegen = [v for v in nieuw if v["id"] not in bestaande_ids][:5]
            actieve.extend(te_voegen)
            bestaande_ids.update(v["id"] for v in te_voegen)
            print(f"  ✅ {len(te_voegen)} videos toegevoegd voor {k['naam']}")
        _sla_actieve_videos_op(actieve)

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
            alle = _filter_op_duur(alle)
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

    alle_nieuw = _filter_op_duur(alle_nieuw)
    te_voegen = [v for v in alle_nieuw
                 if v["id"] not in bestaande_ids][:ROTATIE_BATCH]
    actieve.extend(te_voegen)

    _sla_actieve_videos_op(actieve)
    print(f"✅ Rotatie klaar: +{len(te_voegen)} nieuwe videos, totaal {len(actieve)}")
    return actieve


# ══════════════════════════════════════════════════════════
#  Vraag-cache (gedeeld over alle spelers, persistente JSON)
# ══════════════════════════════════════════════════════════

def _laad_vragen_cache() -> dict:
    """Laad gecachede vragen: eerst Firestore, dan lokaal bestand."""
    if _db:
        try:
            docs = _db.collection('questions_cache').stream()
            cache = {doc.id: doc.to_dict().get('vragen', []) for doc in docs}
            if cache:
                print(f"💾 Vragencache geladen uit Firestore: {len(cache)} video('s)")
                return cache
        except Exception as e:
            print(f"⚠️  Firestore vragencache laden mislukt: {e}")
    try:
        if os.path.exists(VRAGEN_CACHE_PAD):
            with open(VRAGEN_CACHE_PAD, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _sla_vragen_cache_op(cache: dict) -> None:
    """Schrijf de vragencache naar lokaal bestand (backup)."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(VRAGEN_CACHE_PAD, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️  Kon vragencache niet opslaan: {e}")


def _sla_vraag_op(video_id: str, vragen: list) -> None:
    """Sla vragen voor één video op in Firestore én lokaal bestand."""
    if _db:
        try:
            _db.collection('questions_cache').document(video_id).set({'vragen': vragen})
        except Exception as e:
            print(f"⚠️  Firestore vraag opslaan mislukt: {e}")
    _sla_vragen_cache_op(_vragen_cache)


# In-memory cache: eenmalig laden bij opstart
_vragen_cache = _laad_vragen_cache()
print(f"💾 Vragencache geladen: {len(_vragen_cache)} video('s) gecached")

# In-memory video-cache: voorkomt schijf-read bij elke /api/questions aanroep
_videos_cache: list = []

def _haal_videos_cache() -> list:
    """Geeft de in-memory videocache terug; laadt van schijf als leeg."""
    global _videos_cache
    if not _videos_cache:
        _videos_cache = _laad_actieve_videos()
    return _videos_cache

def _invalideer_videos_cache():
    """Wis de in-memory videocache zodat die bij de volgende aanroep opnieuw geladen wordt."""
    global _videos_cache
    _videos_cache = []


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


def _haal_transcript_op(video_id: str) -> str:
    """Haalt de gesproken tekst op via YouTube captions. Geeft lege string terug bij mislukken."""
    if not _transcript_api_beschikbaar:
        return ""
    try:
        fragmenten = YouTubeTranscriptApi.get_transcript(video_id, languages=['nl', 'en'])
        tekst = " ".join(f["text"] for f in fragmenten)
        return tekst[:4000]
    except (NoTranscriptFound, TranscriptsDisabled):
        return ""
    except Exception as e:
        print(f"⚠️  Transcript ophalen mislukt voor '{video_id}': {e}")
        return ""


def _genereer_vragen_met_ai(video_id: str, video_titel: str, video_beschrijving: str, transcript: str = "") -> list:
    """Vraagt ChatGPT om 5 meerkeuze-vragen te maken over de video."""
    heeft_transcript = len(transcript.strip()) > 100
    heeft_beschrijving = len(video_beschrijving.strip()) > 80

    if heeft_transcript:
        inhoud_blok = f"- Gesproken tekst uit het filmpje:\n{transcript}"
        inhoud_richtlijn = (
            "FOCUS UITSLUITEND op de gesproken tekst hierboven: feiten die worden uitgelegd, "
            "hoe iets werkt, welke begrippen voorkomen, wat er besproken wordt."
        )
    elif heeft_beschrijving:
        inhoud_blok = f"- Beschrijving: {video_beschrijving}"
        inhoud_richtlijn = (
            "FOCUS UITSLUITEND op de inhoud van het filmpje: feiten die worden uitgelegd, "
            "hoe iets werkt, welke begrippen voorkomen, wat er getoond of besproken wordt."
        )
    else:
        inhoud_blok = f"- Beschrijving: {video_beschrijving}"
        inhoud_richtlijn = "Stel vragen op basis van wat je kunt afleiden uit de titel en beschrijving."

    prompt = f"""Je bent een kindvriendelijke leraar voor kinderen van 8 jaar.

Er is net een YouTube-filmpje bekeken:
- Titel: {video_titel}
{inhoud_blok}

{inhoud_richtlijn}

Maak precies 5 meerkeuze-vragen die toetsen of het kind de INHOUD van het filmpje heeft begrepen.

VERBODEN vragen (sla deze categorieën volledig over):
- Vragen over abonneren, liken, delen of andere YouTube-acties
- Vragen over het YouTube-kanaal, de maker of de presentator
- Vragen over de naam van het programma of de serie
- Vragen over hoe oud het filmpje is of wanneer het gemaakt is
- Vragen over of het filmpje leuk/interessant was
- Vragen over de doelgroep of leeftijdsgeschiktheid

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
        max_tokens=600,
    )

    tekst = response.choices[0].message.content.strip()

    if tekst.startswith("```"):
        tekst = tekst.split("```")[1]
        if tekst.startswith("json"):
            tekst = tekst[4:]
        tekst = tekst.strip()

    return json.loads(tekst)


def laad_vragen(video_id: str, video_titel: str = "", video_beschrijving: str = "") -> list:
    """
    Geeft vragen terug via drie lagen:
      1. In-memory cache (razendsnel, verdwijnt bij herstart)
      2. Firestore (persistent, overleeft herstart en meerdere workers)
      3. OpenAI genereren (alleen als er nog geen vragen zijn)
    """
    global _vragen_cache

    # Laag 1: in-memory
    if video_id in _vragen_cache:
        print(f"💾 Vragen voor '{video_id}' uit geheugen")
        return _vragen_cache[video_id]

    # Laag 2: Firestore (een andere worker kan al gegenereerd hebben)
    if _db:
        try:
            doc = _db.collection('questions_cache').document(video_id).get()
            if doc.exists:
                vragen = doc.to_dict().get('vragen', [])
                if vragen:
                    _vragen_cache[video_id] = vragen
                    print(f"💾 Vragen voor '{video_id}' uit Firestore")
                    return vragen
        except Exception as e:
            print(f"⚠️  Firestore check mislukt: {e}")

    # Laag 3: genereren via OpenAI
    if USE_AI and _openai_client:
        try:
            transcript = _haal_transcript_op(video_id)
            if transcript:
                print(f"📝 Transcript opgehaald voor '{video_id}' ({len(transcript)} tekens)")
            vragen = _genereer_vragen_met_ai(video_id, video_titel, video_beschrijving, transcript)
            _vragen_cache[video_id] = vragen
            _sla_vraag_op(video_id, vragen)
            print(f"✅ Vragen voor '{video_id}' gegenereerd en opgeslagen")
            return vragen
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
    return render_template("index.html", niveau="alles")


@app.route("/onderbouw")
def onderbouw():
    """Toont alleen filmpjes geschikt voor groep 1-4."""
    return render_template("index.html", niveau="onderbouw")


@app.route("/bovenbouw")
def bovenbouw():
    """Toont alleen filmpjes geschikt voor groep 5-8."""
    return render_template("index.html", niveau="bovenbouw")


@app.route("/api/videos")
def get_videos():
    """
    Geeft de actieve videolijst terug.
    Optionele query-parameter: ?niveau=onderbouw|bovenbouw|alles
    Videos worden automatisch wekelijks ververst via RSS.
    """
    videos = _haal_en_roteer_videos()

    niveau = request.args.get("niveau", "alles").strip().lower()
    if niveau in ("onderbouw", "bovenbouw"):
        videos = [v for v in videos if v.get("niveau", "alles") in (niveau, "alles")]

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
@limiter.limit("10 per minute")
def get_questions():
    """
    Geeft meerkeuze-vragen terug voor een video.

    Beveiligingsmaatregelen:
    - video_id wordt gevalideerd als geldig YouTube-ID (11 tekens)
    - titel en beschrijving worden altijd uit onze eigen database gehaald,
      nooit van de client – voorkomt prompt injection.
    """
    video_id = request.args.get("video_id", "standaard")

    # Valideer video_id: alleen 11 alfanumerieke tekens + - en _
    if video_id != "standaard" and not re.match(r'^[A-Za-z0-9_\-]{11}$', video_id):
        return jsonify({"error": "Ongeldig video_id"}), 400

    # Haal titel en beschrijving altijd uit onze eigen database (in-memory cache)
    actieve   = _haal_videos_cache()
    video_map = {v["id"]: v for v in actieve}

    if video_id in video_map:
        video        = video_map[video_id]
        titel        = video["titel"]
        beschrijving = video["beschrijving"]
    elif video_id == "standaard":
        titel        = "Educatieve video"
        beschrijving = ""
    else:
        return jsonify({"error": "Video niet gevonden"}), 404

    vragen = laad_vragen(video_id, titel, beschrijving)

    return jsonify({
        "video_id": video_id,
        "vragen":   vragen,
        "totaal":   len(vragen),
        "bron":     "ai" if (USE_AI and _openai_client) else "dummy",
    })


@app.route("/api/prewarm", methods=["POST"])
@limiter.limit("10 per minute")
def prewarm_questions():
    """
    Start vraag-generatie op de achtergrond zodra een video gekozen wordt.
    De gebruiker kijkt intussen het filmpje; als hij/zij klaar is zijn de
    vragen al klaar in de cache.
    """
    video_id = request.json.get("video_id", "") if request.json else ""
    if not video_id or not re.match(r'^[A-Za-z0-9_\-]{11}$', video_id):
        return jsonify({"status": "skip"}), 200

    # Al in cache? Niks te doen.
    if video_id in _vragen_cache:
        return jsonify({"status": "cached"}), 200

    # Alleen zinvol als AI actief is
    if not (USE_AI and _openai_client):
        return jsonify({"status": "no-ai"}), 200

    actieve   = _haal_videos_cache()
    video_map = {v["id"]: v for v in actieve}
    if video_id not in video_map:
        return jsonify({"status": "unknown"}), 200

    video = video_map[video_id]

    def _genereer_op_achtergrond():
        if video_id in _vragen_cache:
            return
        try:
            transcript = _haal_transcript_op(video_id)
            vragen = _genereer_vragen_met_ai(video_id, video["titel"], video["beschrijving"], transcript)
            _vragen_cache[video_id] = vragen
            _sla_vraag_op(video_id, vragen)
            print(f"🔥 Pre-warm klaar voor '{video_id}'")
        except Exception as e:
            print(f"⚠️  Pre-warm mislukt voor '{video_id}': {e}")

    t = threading.Thread(target=_genereer_op_achtergrond, daemon=True)
    t.start()
    return jsonify({"status": "started"}), 202


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


@app.errorhandler(429)
def te_veel_verzoeken(e):
    return jsonify({"error": "Te veel verzoeken. Wacht even en probeer het opnieuw."}), 429


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
