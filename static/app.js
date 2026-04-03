// ============================================================
// BegrijpendTuben – Hoofd-JavaScript
//
// Nieuw in deze versie:
//   - Multi-player systeem (max 5 buttons, daarna dropdown)
//   - Antwoord-opties worden per vraag gemengd
//   - Onderbouw/bovenbouw niveau-filter via URL
//   - Persistente score per speler via localStorage
// ============================================================

const App = (() => {

  // ── Sessie-staat ───────────────────────────────────────────
  let staat = {
    huidigVideoId:   null,
    huidigVideoInfo: null,   // { titel, beschrijving, emoji }
    vragen:          [],
    huidigVraagIdx:  0,
    score:           0,
    antwoorden:      [],
    beantwoord:      false,
    huidigKanaal:    '',     // actief kanaalfilter
    alleVideos:      [],     // alle geladen video's
  };

  const LETTERS = ['A', 'B', 'C', 'D'];
  const CONFETTI_KLEUREN = ['#7c3aed','#ec4899','#fbbf24','#10b981','#f87171','#60a5fa'];

  // ── localStorage sleutels ──────────────────────────────────
  const SPELERS_SLEUTEL  = 'begrijpendtuben_spelers';   // nieuw: array van spelers
  const ACTIEVE_SLEUTEL  = 'begrijpendtuben_actieve';   // naam van actieve speler
  // Oud (voor migratie):
  const SCORE_SLEUTEL    = 'begrijpendtuben_score';
  const SPELER_SLEUTEL   = 'begrijpendtuben_speler';

  const MAX_SPELER_KNOPPEN = 5;

  // ── Multi-player staat ─────────────────────────────────────
  let _spelers     = [];    // [{ naam, thema, score: {...} }]
  let _actieveNaam = null;  // naam van actieve speler
  let _editingNaam = null;  // naam van speler die bewerkt wordt in modal (null = nieuw)

  // Backward compat: enkelvoudige speler-ref voor Firebase sync
  let _speler = null; // { naam, thema }

  // ── Niveau-filter (ingesteld via window.NIVEAU vanuit Flask) ──
  const NIVEAU = (typeof window !== 'undefined' && window.NIVEAU) ? window.NIVEAU : 'alles';

  // ── Categorie-emoji fallback ───────────────────────────────
  function _catEmoji(cat) {
    const map = {
      Wetenschap:'🔬', Nieuws:'📰', Dieren:'🐾', Natuur:'🌿',
      Ruimte:'🚀', Geschiedenis:'🏛️', Educatie:'📚',
    };
    return map[cat] || '🎬';
  }

  // ══════════════════════════════════════════════════════════
  //  Multi-player systeem
  // ══════════════════════════════════════════════════════════

  function _leegScore() {
    return { sterren: 0, totaalJuist: 0, totaalVragen: 0, sessiesGespeeld: 0, besteScore: 0 };
  }

  function _laadSpelers() {
    try {
      const data = JSON.parse(localStorage.getItem(SPELERS_SLEUTEL));
      if (data && Array.isArray(data) && data.length > 0) return data;
    } catch {}

    // Migratie van oud enkelvoudig formaat
    try {
      const oud   = JSON.parse(localStorage.getItem(SPELER_SLEUTEL));
      const score = JSON.parse(localStorage.getItem(SCORE_SLEUTEL));
      if (oud && oud.naam) {
        return [{ naam: oud.naam, thema: oud.thema || 'lief', score: score || _leegScore() }];
      }
    } catch {}

    return [];
  }

  function _slaSpelersOp() {
    localStorage.setItem(SPELERS_SLEUTEL, JSON.stringify(_spelers));
  }

  function _haalActieveSpeler() {
    return _spelers.find(s => s.naam === _actieveNaam) || null;
  }

  // ── Score lezen/schrijven (werkt per actieve speler) ──────

  function _laadScore() {
    const actief = _haalActieveSpeler();
    return actief ? { ...actief.score } : _leegScore();
  }

  function _slaScore(data) {
    const idx = _spelers.findIndex(s => s.naam === _actieveNaam);
    if (idx !== -1) {
      _spelers[idx].score = data;
      _slaSpelersOp();
    }
  }

  // ── Thema toepassen ───────────────────────────────────────

  function _pasThemaToe(thema) {
    document.body.setAttribute('data-thema', thema || 'lief');
  }

  /** Wordt aangeroepen door de thema-knoppen in de modal. */
  function kiesThema(knop) {
    document.querySelectorAll('.thema-knop').forEach(b => b.classList.remove('actief'));
    knop.classList.add('actief');
  }

  // ── Speler wisselen ───────────────────────────────────────

  function _switchNaarSpeler(naam) {
    _actieveNaam = naam;
    localStorage.setItem(ACTIEVE_SLEUTEL, naam);
    const speler = _haalActieveSpeler();
    if (speler) {
      _speler = { naam: speler.naam, thema: speler.thema };
      _pasThemaToe(speler.thema);
      _renderSpelerBalk();
      _updateHeaderScore();
      _syncFirebase();
    }
  }

  /**
   * Opent modal voor de actieve speler om naam/thema te wijzigen.
   * Wordt ook aangeroepen bij 'wisselSpeler' (backward compat).
   */
  function wisselSpeler() {
    const actief = _haalActieveSpeler();
    _editingNaam = actief ? actief.naam : null;
    document.getElementById('naamInvoer').value = actief ? actief.naam : '';
    const thema = actief ? actief.thema : 'lief';
    document.querySelectorAll('.thema-knop').forEach(b => {
      b.classList.toggle('actief', b.dataset.thema === thema);
    });
    document.getElementById('modalSluitKnop').style.display = 'block';
    document.getElementById('naamModal').style.display = 'flex';
  }

  function nieuweSpeler() {
    _editingNaam = null;
    document.getElementById('naamInvoer').value = '';
    document.querySelectorAll('.thema-knop').forEach(b => {
      b.classList.toggle('actief', b.dataset.thema === 'lief');
    });
    // Kruisje alleen tonen als er al een speler is (anders zit je vast)
    document.getElementById('modalSluitKnop').style.display =
      _actieveNaam ? 'block' : 'none';
    document.getElementById('naamModal').style.display = 'flex';
  }

  /** Bevestig naam + thema en sluit de modal. */
  function bevestigNaam() {
    const invoer = document.getElementById('naamInvoer');
    const naam = invoer.value.trim();
    if (!naam) {
      invoer.focus();
      invoer.style.borderColor = '#ef4444';
      setTimeout(() => { invoer.style.borderColor = ''; }, 1200);
      return;
    }
    const actieveKnop = document.querySelector('.thema-knop.actief');
    const thema = actieveKnop ? actieveKnop.dataset.thema : 'lief';

    if (_editingNaam !== null) {
      // Bestaande speler bewerken (naam of thema wijzigen)
      const idx = _spelers.findIndex(s => s.naam === _editingNaam);
      if (idx !== -1) {
        _spelers[idx].naam  = naam;
        _spelers[idx].thema = thema;
      }
      _actieveNaam = naam;
    } else {
      // Nieuwe speler of terugkeren naar bestaande speler
      const bestaand = _spelers.findIndex(s => s.naam === naam);
      if (bestaand !== -1) {
        // Bestaande speler: update alleen thema
        _spelers[bestaand].thema = thema;
      } else {
        // Gloednieuwe speler met lege score
        _spelers.push({ naam, thema, score: _leegScore() });
      }
      _actieveNaam = naam;
    }

    _editingNaam = null;
    _slaSpelersOp();
    localStorage.setItem(ACTIEVE_SLEUTEL, naam);
    _speler = { naam, thema };
    _pasThemaToe(thema);
    _renderSpelerBalk();
    document.getElementById('naamModal').style.display = 'none';
    _updateHeaderScore();
    _syncFirebase();
  }

  /** Rendert de speler-balk met buttons of dropdown. */
  function _renderSpelerBalk() {
    const balk = document.getElementById('spelerBalk');
    if (!_actieveNaam) { balk.style.display = 'none'; return; }
    balk.style.display = 'flex';

    const container = document.getElementById('spelersContainer');
    container.innerHTML = '';

    if (_spelers.length <= MAX_SPELER_KNOPPEN) {
      // Toon als knoppen
      _spelers.forEach(speler => {
        const knop = document.createElement('button');
        const isActief = speler.naam === _actieveNaam;
        knop.className = 'speler-knop' + (isActief ? ' actief' : '');
        knop.textContent = `👤 ${speler.naam}`;
        knop.title = isActief ? 'Klik om naam/thema te wijzigen' : `Schakel naar ${speler.naam}`;
        knop.onclick = isActief
          ? () => wisselSpeler()
          : () => _switchNaarSpeler(speler.naam);
        container.appendChild(knop);
      });
    } else {
      // Toon als dropdown
      const select = document.createElement('select');
      select.className = 'speler-dropdown';
      _spelers.forEach(speler => {
        const opt = document.createElement('option');
        opt.value    = speler.naam;
        opt.textContent = `👤 ${speler.naam}`;
        opt.selected = speler.naam === _actieveNaam;
        select.appendChild(opt);
      });
      select.onchange = (e) => _switchNaarSpeler(e.target.value);
      container.appendChild(select);
    }
  }

  // ── Persistente score: header bijwerken ───────────────────

  function _updateHeaderScore() {
    const s = _laadScore();
    const balk = document.getElementById('sterrenBalk');
    if (s.sessiesGespeeld > 0) {
      balk.style.display = 'flex';
      document.getElementById('sterrenWaarde').textContent = `⭐ ${s.sterren}`;
      document.getElementById('totaalGoed').textContent    = `${s.totaalJuist} / ${s.totaalVragen}`;
    } else {
      balk.style.display = 'none';
    }
  }

  /**
   * Berekent hoeveel sterren (0-5) een sessie waard is.
   * 100% = 5 sterren, 80% = 4, 60% = 3, 40% = 2, 20% = 1, <20% = 0
   */
  function _berekenSterren(juist, totaal) {
    if (totaal === 0) return 0;
    const pct = juist / totaal;
    if (pct === 1)    return 5;
    if (pct >= 0.8)   return 4;
    if (pct >= 0.6)   return 3;
    if (pct >= 0.4)   return 2;
    if (pct >= 0.2)   return 1;
    return 0;
  }

  // ── Firebase score-sync ───────────────────────────────────

  async function _syncFirebase() {
    if (!window.db || !window.fbUid || !_speler) return;
    const { doc, setDoc, serverTimestamp } = window.firebaseFuncs;
    const score = _laadScore();
    try {
      await setDoc(doc(window.db, 'spelers', window.fbUid), {
        naam:            _speler.naam,
        thema:           _speler.thema,
        sterren:         score.sterren,
        totaalJuist:     score.totaalJuist,
        totaalVragen:    score.totaalVragen,
        sessiesGespeeld: score.sessiesGespeeld,
        bijgewerkt:      serverTimestamp(),
      }, { merge: true });
    } catch (e) {
      console.warn('Firebase sync fout:', e);
    }
  }

  async function _laadScoreVanFirebase() {
    if (!window.db || !window.fbUid) return;
    const { doc, getDoc } = window.firebaseFuncs;
    try {
      const snap = await getDoc(doc(window.db, 'spelers', window.fbUid));
      if (snap.exists()) {
        const data = snap.data();
        // Firebase score alleen toepassen als er nog geen lokale speler is
        if (data.naam && _spelers.length === 0) {
          const nieuweScore = {
            sterren:         data.sterren         || 0,
            totaalJuist:     data.totaalJuist     || 0,
            totaalVragen:    data.totaalVragen    || 0,
            sessiesGespeeld: data.sessiesGespeeld || 0,
            besteScore:      data.besteScore      || 0,
          };
          _spelers     = [{ naam: data.naam, thema: data.thema || 'lief', score: nieuweScore }];
          _actieveNaam = data.naam;
          _slaSpelersOp();
          localStorage.setItem(ACTIEVE_SLEUTEL, data.naam);
          _speler = { naam: data.naam, thema: data.thema || 'lief' };
          _pasThemaToe(data.thema || 'lief');
          _renderSpelerBalk();
          _updateHeaderScore();
          document.getElementById('naamModal').style.display = 'none';
        } else if (_actieveNaam) {
          _updateHeaderScore();
        }
      }
    } catch (e) {
      console.warn('Firebase laad fout:', e);
    }
  }

  // ── Initialisatie ──────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    // Laad spelers en herstel actieve speler
    _spelers     = _laadSpelers();
    _actieveNaam = localStorage.getItem(ACTIEVE_SLEUTEL);

    // Migratie: als actieve naam niet bestaat, gebruik eerste speler
    if (!_actieveNaam && _spelers.length > 0) {
      _actieveNaam = _spelers[0].naam;
      localStorage.setItem(ACTIEVE_SLEUTEL, _actieveNaam);
    }

    if (_actieveNaam && _spelers.some(s => s.naam === _actieveNaam)) {
      const actief = _haalActieveSpeler();
      _speler = { naam: actief.naam, thema: actief.thema };
      _pasThemaToe(actief.thema);
      _renderSpelerBalk();
      _updateHeaderScore();
    } else {
      document.getElementById('naamModal').style.display = 'flex';
    }

    _laadAlleVideos();

    // Enter-toets in naam-invoer
    document.getElementById('naamInvoer').addEventListener('keydown', e => {
      if (e.key === 'Enter') bevestigNaam();
    });

    // YouTube IFrame API: detecteer wanneer video klaar is (state 0 = ended)
    window.addEventListener('message', (e) => {
      if (!e.data) return;
      try {
        const data = typeof e.data === 'string' ? JSON.parse(e.data) : e.data;
        if (data.event === 'onStateChange' && data.info === 0) {
          document.getElementById('videoEindeOverlay').style.display = 'flex';
        }
      } catch {}
    });
  });

  // Firebase-ready: laad score uit de cloud
  document.addEventListener('firebase-ready', () => {
    _laadScoreVanFirebase();
  });

  // ── Video laden en weergeven ───────────────────────────────

  async function _laadAlleVideos() {
    const grid = document.getElementById('videoGrid');
    try {
      const url = NIVEAU !== 'alles' ? `/api/videos?niveau=${NIVEAU}` : '/api/videos';
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      staat.alleVideos = await res.json();
      _renderVideoGrid(staat.alleVideos);
    } catch (err) {
      grid.innerHTML = `<div class="laad-spinner" style="color:#ef4444;">
        <p>⚠️ Kon de filmpjeslijst niet laden. Is de server actief?</p></div>`;
    }
  }

  function _renderVideoGrid(videos) {
    const grid    = document.getElementById('videoGrid');
    const geenRes = document.getElementById('geenResultaten');

    if (videos.length === 0) {
      grid.innerHTML = '';
      geenRes.style.display = 'block';
      return;
    }
    geenRes.style.display = 'none';
    grid.innerHTML = '';

    videos.forEach(video => {
      const emoji   = video.emoji || _catEmoji(video.categorie);
      const kaartje = document.createElement('div');
      kaartje.className = 'video-kaartje';
      kaartje.tabIndex  = 0;
      kaartje.setAttribute('role', 'button');
      kaartje.setAttribute('aria-label', `Selecteer: ${video.titel}`);
      const kanaalLabel = video.kanaal ? `<span class="video-kanaal-badge">${video.kanaal}</span>` : '';
      const duurLabel   = video.duur   ? `<span class="video-duur-badge">⏱ ${video.duur}</span>` : '';
      kaartje.innerHTML = `
        <div class="video-thumbnail-wrapper">
          <img class="video-thumbnail"
               src="https://img.youtube.com/vi/${video.id}/mqdefault.jpg"
               alt="${video.titel}"
               loading="lazy"
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
          <div class="video-thumbnail-placeholder" style="display:none">${emoji}</div>
          ${duurLabel ? `<div class="video-duur-overlay">${duurLabel}</div>` : ''}
        </div>
        <div class="video-info">
          <div class="video-badges">
            <span class="video-categorie-badge">${video.categorie}</span>
            ${kanaalLabel}
          </div>
          <div class="video-naam">${video.titel}</div>
          <div class="video-omschrijving">${video.beschrijving}</div>
        </div>`;
      const kies = () => _kiesVideo(video.id, video.titel, video.beschrijving, emoji);
      kaartje.addEventListener('click', kies);
      kaartje.addEventListener('keydown', (e) => { if (e.key==='Enter'||e.key===' '){e.preventDefault();kies();} });
      grid.appendChild(kaartje);
    });
  }

  // ── Kanaal-filter ──────────────────────────────────────────

  function filterKanaal(knop, kanaal) {
    staat.huidigKanaal = kanaal;

    document.querySelectorAll('.cat-tab').forEach(t => t.classList.remove('actief'));
    knop.classList.add('actief');

    const gefilterd = kanaal
      ? staat.alleVideos.filter(v => v.kanaal === kanaal)
      : staat.alleVideos;

    const titel = kanaal ? `📺 ${kanaal}` : '🎥 Alle filmpjes';
    document.getElementById('videoGridTitel').textContent = titel;

    _renderVideoGrid(gefilterd);
  }

  // ── Video kiezen & afspelen ────────────────────────────────

  function _kiesVideo(videoId, titel, beschrijving, emoji) {
    staat.huidigVideoId   = videoId;
    staat.huidigVideoInfo = { titel, beschrijving, emoji: emoji || '🎬' };

    document.getElementById('videoTitel').textContent       = `${emoji || '🎬'} ${titel}`;
    document.getElementById('videoBeschrijving').textContent = beschrijving;

    // YouTube privacy-enhanced embed
    // enablejsapi=1: staat toe dat we via postMessage detecteren wanneer de video eindigt
    const player = document.getElementById('youtubePlayer');
    const origin = encodeURIComponent(window.location.origin);
    player.src = `https://www.youtube-nocookie.com/embed/${videoId}?rel=0&modestbranding=1&iv_load_policy=3&enablejsapi=1&origin=${origin}`;

    // Start vraag-generatie alvast op de achtergrond terwijl het kind kijkt
    fetch('/api/prewarm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: videoId }),
    }).catch(() => {}); // fire-and-forget, fout is niet erg

    // Verberg het einde-overlay als de video herstart
    document.getElementById('videoEindeOverlay').style.display = 'none';

    toonScherm('schermVideo');
  }

  // ── Quiz starten ───────────────────────────────────────────

  async function startQuiz() {
    const knop = document.getElementById('btnKlaarMetKijken');
    knop.textContent = '⏳ Vragen laden...';
    knop.disabled = true;

    try {
      const params = new URLSearchParams({ video_id: staat.huidigVideoId });
      const res = await fetch(`/api/questions?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!data.vragen || data.vragen.length === 0) throw new Error('Geen vragen ontvangen');

      staat.vragen         = data.vragen;
      staat.huidigVraagIdx = 0;
      staat.score          = 0;
      staat.antwoorden     = [];
      staat.beantwoord     = false;

      toonScherm('schermQuiz');
      _toonVraag(0);
    } catch (err) {
      _popup('Oeps! Kon de vragen niet laden. Probeer het opnieuw.', { emoji: '⚠️' });
      console.error(err);
    } finally {
      knop.textContent = '✅ Ik ben klaar! Start de vragen →';
      knop.disabled = false;
    }
  }

  // ── Mooie popup (vervangt alert/confirm) ──────────────────

  /**
   * Toont een kindvriendelijke popup.
   * @param {string} tekst - Bericht
   * @param {object} opties - { emoji, type: 'melding'|'bevestig', okTekst, cancelTekst }
   * @returns {Promise<boolean>} true = ok/ja, false = annuleer
   */
  function _popup(tekst, opties = {}) {
    return new Promise(resolve => {
      const overlay = document.getElementById('popupOverlay');
      const emojiEl = document.getElementById('popupEmoji');
      const tekstEl = document.getElementById('popupTekst');
      const knoppen = document.getElementById('popupKnoppen');

      emojiEl.textContent = opties.emoji || '💬';
      tekstEl.textContent = tekst;
      knoppen.innerHTML   = '';

      const sluit = (val) => { overlay.style.display = 'none'; resolve(val); };

      if (opties.type === 'bevestig') {
        const nee = document.createElement('button');
        nee.className   = 'knop knop-grijs';
        nee.textContent = opties.cancelTekst || 'Nee, toch niet';
        nee.onclick = () => sluit(false);

        const ja = document.createElement('button');
        ja.className   = 'knop knop-rood';
        ja.textContent = opties.okTekst || 'Ja';
        ja.onclick = () => sluit(true);

        knoppen.appendChild(nee);
        knoppen.appendChild(ja);
      } else {
        const ok = document.createElement('button');
        ok.className   = 'knop knop-paars';
        ok.textContent = opties.okTekst || 'OK 👍';
        ok.onclick = () => sluit(true);
        knoppen.appendChild(ok);
      }

      overlay.style.display = 'flex';
    });
  }

  // ── Quiz stoppen ───────────────────────────────────────────

  async function stopQuiz() {
    const ok = await _popup(
      'Wil je de quiz stoppen en het filmpje opnieuw bekijken?',
      { emoji: '🎬', type: 'bevestig', okTekst: 'Ja, stop quiz' }
    );
    if (ok) toonScherm('schermVideo');
  }

  // ── Vraag weergeven ────────────────────────────────────────

  function _toonVraag(idx) {
    const vraag  = staat.vragen[idx];
    const totaal = staat.vragen.length;
    staat.beantwoord = false;

    document.getElementById('vraagNummer').textContent = `Vraag ${idx + 1}`;
    document.getElementById('vraagTekst').textContent  = vraag.vraag;
    document.getElementById('vraagTeller').textContent = `Vraag ${idx + 1} van ${totaal}`;
    document.getElementById('scoreTeller').textContent = `⭐ Score: ${staat.score}`;

    // Voortgangsbalk
    document.getElementById('voortgangVulling').style.width = `${(idx / totaal) * 100}%`;

    // Meng antwoordopties (maar behoudt originele correct-string voor vergelijking)
    const gemengd = vraag.opties
      .map(optie => ({ optie, correct: optie === vraag.correct }))
      .sort(() => Math.random() - 0.5);

    const grid = document.getElementById('antwoordGrid');
    grid.innerHTML = '';
    gemengd.forEach((item, i) => {
      const knop = document.createElement('button');
      knop.className = 'antwoord-knop';
      knop.innerHTML = `<span class="antwoord-letter">${LETTERS[i]}</span><span>${item.optie}</span>`;
      knop.addEventListener('click', () => _beantwoordVraag(item.optie, vraag));
      grid.appendChild(knop);
    });

    const fbBlok = document.getElementById('feedbackBlok');
    fbBlok.style.display = 'none';
    fbBlok.className = 'feedback-blok';
  }

  // ── Vraag beantwoorden ─────────────────────────────────────

  function _beantwoordVraag(gekozenOptie, vraag) {
    if (staat.beantwoord) return;
    staat.beantwoord = true;

    const isGoed = gekozenOptie === vraag.correct;
    if (isGoed) staat.score++;

    staat.antwoorden.push({ vraag: vraag.vraag, gekozen: gekozenOptie, correct: vraag.correct, uitleg: vraag.uitleg || '', goed: isGoed });

    // Knoppen inkleuren
    document.querySelectorAll('.antwoord-knop').forEach(knop => {
      knop.disabled = true;
      const tekst = knop.querySelector('span:last-child').textContent;
      if (tekst === vraag.correct)          knop.classList.add('correct');
      else if (tekst === gekozenOptie && !isGoed) knop.classList.add('fout');
    });

    _toonFeedback(isGoed, vraag);
  }

  function _toonFeedback(isGoed, vraag) {
    const fbBlok    = document.getElementById('feedbackBlok');
    const volgKnop  = document.getElementById('btnVolgende');
    const isLaatste = staat.huidigVraagIdx === staat.vragen.length - 1;

    if (isGoed) {
      const berichten = ['Super goed! 🎉','Geweldig! 🌟','Fantastisch! 🎊','Helemaal correct! ✅','Wauw, wat slim! 🧠'];
      document.getElementById('feedbackEmoji').textContent   = '🎉';
      document.getElementById('feedbackBericht').textContent = berichten[Math.floor(Math.random() * berichten.length)];
      fbBlok.className = 'feedback-blok correct-bg';
    } else {
      const berichten = ['Helaas, dat klopt niet!','Bijna! Probeer het volgende keer!','Niet helemaal goed...','Dat was lastig!'];
      document.getElementById('feedbackEmoji').textContent   = '💡';
      document.getElementById('feedbackBericht').textContent = berichten[Math.floor(Math.random() * berichten.length)];
      fbBlok.className = 'feedback-blok fout-bg';
    }

    document.getElementById('feedbackUitleg').textContent =
      vraag.uitleg ? `💬 ${vraag.uitleg}` : `Het goede antwoord was: "${vraag.correct}"`;

    volgKnop.textContent = isLaatste ? '🏆 Bekijk je score!' : 'Volgende vraag →';
    fbBlok.style.display = 'block';
    fbBlok.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // ── Volgende vraag / resultaat ─────────────────────────────

  function volgendeVraag() {
    staat.huidigVraagIdx++;
    if (staat.huidigVraagIdx < staat.vragen.length) {
      _toonVraag(staat.huidigVraagIdx);
      document.getElementById('schermQuiz').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      _toonResultaat();
    }
  }

  // ── Resultaat & persistente score ─────────────────────────

  function _toonResultaat() {
    const totaal  = staat.vragen.length;
    const score   = staat.score;
    const pct     = totaal > 0 ? score / totaal : 0;
    const sterrenSessie = _berekenSterren(score, totaal);

    document.getElementById('scoreGroot').textContent = score;
    document.getElementById('scoreMax').textContent   = `/ ${totaal}`;

    let trophy, titel, bericht;
    if (pct === 1)     { trophy = '🏆'; titel = 'Perfect gescoord!';    bericht = 'Wauw! ALLE vragen goed! Je bent een echte kampioen! 🌟'; }
    else if (pct>=0.8) { trophy = '🥇'; titel = 'Geweldig gedaan!';     bericht = `Bijna perfect! ${score} van de ${totaal} goed.`; }
    else if (pct>=0.6) { trophy = '🥈'; titel = 'Goed gedaan!';         bericht = `Netjes! ${score} van de ${totaal} goed.`; }
    else if (pct>=0.4) { trophy = '🥉'; titel = 'Goed geprobeerd!';     bericht = `${score} van de ${totaal} goed. Volgende keer beter!`; }
    else               { trophy = '💪'; titel = 'Blijf oefenen!';       bericht = `Je had ${score} van de ${totaal} goed. Kijk het filmpje nog eens!`; }

    document.getElementById('resultaatTrophy').textContent = trophy;
    document.getElementById('resultaatTitel').textContent  = titel;
    document.getElementById('scoreBericht').textContent    = bericht;

    const sterrenEl = document.getElementById('sterrenSessie');
    sterrenEl.innerHTML = '';
    for (let i = 1; i <= 5; i++) {
      const ster = document.createElement('span');
      ster.className = `sessie-ster ${i <= sterrenSessie ? 'gevuld' : 'leeg'}`;
      ster.textContent = i <= sterrenSessie ? '⭐' : '☆';
      ster.style.animationDelay = `${i * 0.12}s`;
      sterrenEl.appendChild(ster);
    }

    const totaalScore = _laadScore();
    totaalScore.sterren        += sterrenSessie;
    totaalScore.totaalJuist    += score;
    totaalScore.totaalVragen   += totaal;
    totaalScore.sessiesGespeeld++;
    totaalScore.besteScore      = Math.max(totaalScore.besteScore, Math.round(pct * 100));
    _slaScore(totaalScore);
    _updateHeaderScore();
    _syncFirebase();

    document.getElementById('totaalSterren').textContent = `⭐ ${totaalScore.sterren} sterren`;
    document.getElementById('totaalSub').textContent     = `Je hebt al ${totaalScore.totaalJuist} vragen goed beantwoord!`;

    const mijlpalen = [10, 25, 50, 100];
    const geraakt   = mijlpalen.find(m => totaalScore.sterren >= m && totaalScore.sterren - sterrenSessie < m);
    if (geraakt) {
      setTimeout(() => _popup(`Wauw! Je hebt al ${geraakt} sterren verzameld! Super goed bezig!`, { emoji: '🎊' }), 600);
    }

    document.getElementById('voortgangVulling').style.width = '100%';
    _renderAntwoordOverzicht();
    toonScherm('schermResultaat');
    if (pct >= 0.6) _startConfetti();
  }

  function _renderAntwoordOverzicht() {
    const container = document.getElementById('antwoordOverzicht');
    container.innerHTML = '<h3 style="margin-bottom:14px;font-family:var(--font-titel);">📋 Overzicht</h3>';
    staat.antwoorden.forEach((item, i) => {
      const div = document.createElement('div');
      div.className = `overzicht-item ${item.goed ? 'goed' : 'slecht'}`;
      div.innerHTML = `
        <span class="overzicht-icoon">${item.goed ? '✅' : '❌'}</span>
        <div>
          <div class="overzicht-vraag">${i+1}. ${item.vraag}</div>
          <div class="overzicht-antwoord">
            ${item.goed
              ? `Jouw antwoord: <strong>${item.gekozen}</strong> ✓`
              : `Jij zei: <strong>${item.gekozen}</strong> — goed was: <strong>${item.correct}</strong>`}
          </div>
        </div>`;
      container.appendChild(div);
    });
  }

  // ── Score resetten ─────────────────────────────────────────

  async function resetScore() {
    const ok = await _popup(
      'Weet je zeker dat je alle sterren en punten wilt wissen?',
      { emoji: '🗑️', type: 'bevestig', okTekst: 'Ja, wis alles' }
    );
    if (!ok) return;
    const idx = _spelers.findIndex(s => s.naam === _actieveNaam);
    if (idx !== -1) {
      _spelers[idx].score = _leegScore();
      _slaSpelersOp();
    }
    _updateHeaderScore();
    _popup('Score gewist! Begin opnieuw met spelen.', { emoji: '✨' });
  }

  // ── Opnieuw dezelfde quiz ──────────────────────────────────

  function opnieuwDezelfde() {
    staat.huidigVraagIdx = 0;
    staat.score          = 0;
    staat.antwoorden     = [];
    staat.beantwoord     = false;
    toonScherm('schermQuiz');
    _toonVraag(0);
  }

  // ── Confetti ───────────────────────────────────────────────

  function _startConfetti() {
    const container = document.getElementById('confettiContainer');
    container.innerHTML = '';
    for (let i = 0; i < 80; i++) {
      const s = document.createElement('div');
      s.className = 'confetti-stukje';
      const kleur = CONFETTI_KLEUREN[Math.floor(Math.random() * CONFETTI_KLEUREN.length)];
      const groot = 6 + Math.random() * 10;
      s.style.cssText = `left:${Math.random()*100}%;background:${kleur};width:${groot}px;height:${groot}px;animation-duration:${2+Math.random()*2}s;animation-delay:${Math.random()*1.5}s;transform:rotate(${Math.random()*360}deg);border-radius:${Math.random()>0.5?'50%':'2px'}`;
      container.appendChild(s);
    }
    setTimeout(() => { container.innerHTML = ''; }, 5000);
  }

  // ── Scherm-wisseling ───────────────────────────────────────

  function toonScherm(schermId) {
    document.querySelectorAll('.scherm').forEach(s => s.classList.remove('actief'));
    const scherm = document.getElementById(schermId);
    if (scherm) { scherm.classList.add('actief'); window.scrollTo({ top: 0, behavior: 'smooth' }); }

    const stapNummer = { schermKiezen:1, schermVideo:2, schermQuiz:3, schermResultaat:4 }[schermId] || 1;
    const stapLabels = { 1:'Kies een filmpje', 2:'Bekijk het filmpje', 3:'Beantwoord vragen', 4:'Bekijk je score' };

    document.querySelectorAll('.stap').forEach(dot => {
      const nr = parseInt(dot.dataset.stap);
      dot.classList.remove('actief','klaar');
      if (nr === stapNummer)    dot.classList.add('actief');
      else if (nr < stapNummer) dot.classList.add('klaar');
    });

    // Mobiele stap-info bijwerken
    const stapInfo = document.getElementById('stapActiefLabel');
    if (stapInfo) stapInfo.textContent = `Stap ${stapNummer}: ${stapLabels[stapNummer]}`;

    if (schermId === 'schermKiezen') {
      document.getElementById('youtubePlayer').src = '';
    }
  }

  // ── Publieke interface ─────────────────────────────────────
  return {
    filterKanaal, startQuiz, stopQuiz, volgendeVraag, opnieuwDezelfde,
    resetScore, toonScherm, kiesThema, bevestigNaam, wisselSpeler, nieuweSpeler,
  };

})();
