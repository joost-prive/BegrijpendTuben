// ============================================================
// BegrijpendTuben – Hoofd-JavaScript
//
// Nieuw in deze versie:
//   - Zoekfunctie + categorie-tabs (vervangt URL-invoer)
//   - Stop-knop in de quiz
//   - Persistente score via localStorage (sterren-systeem)
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

  // ── localStorage sleutel ───────────────────────────────────
  const SCORE_SLEUTEL = 'begrijpendtuben_score';

  // ── Persistente score lezen/schrijven ──────────────────────

  function _laadScore() {
    try {
      return JSON.parse(localStorage.getItem(SCORE_SLEUTEL)) || {
        sterren: 0, totaalJuist: 0, totaalVragen: 0, sessiesGespeeld: 0, besteScore: 0,
      };
    } catch { return { sterren: 0, totaalJuist: 0, totaalVragen: 0, sessiesGespeeld: 0, besteScore: 0 }; }
  }

  function _slaScore(data) {
    localStorage.setItem(SCORE_SLEUTEL, JSON.stringify(data));
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

  /** Toont de huidige totaalscore in de header. */
  function _updateHeaderScore() {
    const s = _laadScore();
    const balk = document.getElementById('sterrenBalk');
    if (s.sessiesGespeeld > 0) {
      balk.style.display = 'flex';
      document.getElementById('sterrenWaarde').textContent = `⭐ ${s.sterren}`;
      document.getElementById('totaalGoed').textContent    = `${s.totaalJuist} / ${s.totaalVragen}`;
    }
  }

  // ── Initialisatie ──────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    _laadAlleVideos();
    _updateHeaderScore();
  });

  // ── Video laden en weergeven ───────────────────────────────

  /** Laadt alle video's bij start en slaat ze op in staat. */
  async function _laadAlleVideos() {
    const grid = document.getElementById('videoGrid');
    try {
      const res = await fetch('/api/videos');
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
      kaartje.innerHTML = `
        <img class="video-thumbnail"
             src="https://img.youtube.com/vi/${video.id}/mqdefault.jpg"
             alt="${video.titel}"
             loading="lazy"
             onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
        <div class="video-thumbnail-placeholder" style="display:none">${emoji}</div>
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

  /** Wordt aangeroepen door de kanaal-tabs. */
  function filterKanaal(knop, kanaal) {
    staat.huidigKanaal = kanaal;

    // Actieve tab bijwerken
    document.querySelectorAll('.cat-tab').forEach(t => t.classList.remove('actief'));
    knop.classList.add('actief');

    // Client-side filteren (geen extra fetch nodig)
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
    const player = document.getElementById('youtubePlayer');
    player.src = `https://www.youtube-nocookie.com/embed/${videoId}?rel=0`;

    toonScherm('schermVideo');
  }

  // ── Quiz starten ───────────────────────────────────────────

  async function startQuiz() {
    const knop = document.getElementById('btnKlaarMetKijken');
    knop.textContent = '⏳ Vragen laden...';
    knop.disabled = true;

    try {
      const params = new URLSearchParams({
        video_id:     staat.huidigVideoId,
        titel:        staat.huidigVideoInfo.titel        || '',
        beschrijving: staat.huidigVideoInfo.beschrijving || '',
      });
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
      alert('Oeps! Kon de vragen niet laden. Probeer het opnieuw.');
      console.error(err);
    } finally {
      knop.textContent = '✅ Ik ben klaar! Start de vragen →';
      knop.disabled = false;
    }
  }

  // ── Quiz stoppen ───────────────────────────────────────────

  /**
   * Vraagt bevestiging en keert terug naar het video-scherm.
   * Zo kan het kind het filmpje nog een keer bekijken.
   */
  function stopQuiz() {
    if (confirm('Wil je de quiz stoppen en het filmpje opnieuw bekijken?')) {
      toonScherm('schermVideo');
    }
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

    // Antwoord-knoppen
    const grid = document.getElementById('antwoordGrid');
    grid.innerHTML = '';
    vraag.opties.forEach((optie, i) => {
      const knop = document.createElement('button');
      knop.className = 'antwoord-knop';
      knop.innerHTML = `<span class="antwoord-letter">${LETTERS[i]}</span><span>${optie}</span>`;
      knop.addEventListener('click', () => _beantwoordVraag(optie, vraag));
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

    // Sessie-score weergeven
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

    // Sterren animatie deze sessie
    const sterrenEl = document.getElementById('sterrenSessie');
    sterrenEl.innerHTML = '';
    for (let i = 1; i <= 5; i++) {
      const ster = document.createElement('span');
      ster.className = `sessie-ster ${i <= sterrenSessie ? 'gevuld' : 'leeg'}`;
      ster.textContent = i <= sterrenSessie ? '⭐' : '☆';
      ster.style.animationDelay = `${i * 0.12}s`;
      sterrenEl.appendChild(ster);
    }

    // Persistente score bijwerken
    const totaalScore = _laadScore();
    totaalScore.sterren        += sterrenSessie;
    totaalScore.totaalJuist    += score;
    totaalScore.totaalVragen   += totaal;
    totaalScore.sessiesGespeeld++;
    totaalScore.besteScore      = Math.max(totaalScore.besteScore, Math.round(pct * 100));
    _slaScore(totaalScore);
    _updateHeaderScore();

    // Totaalscore tonen
    document.getElementById('totaalSterren').textContent = `⭐ ${totaalScore.sterren} sterren`;
    document.getElementById('totaalSub').textContent     = `Je hebt al ${totaalScore.totaalJuist} vragen goed beantwoord!`;

    // Mijlpaal-felicitatie
    const mijlpalen = [10, 25, 50, 100];
    const geraakt   = mijlpalen.find(m => totaalScore.sterren >= m && totaalScore.sterren - sterrenSessie < m);
    if (geraakt) {
      setTimeout(() => alert(`🎊 Wauw! Je hebt al ${geraakt} sterren verzameld! Super goed bezig!`), 600);
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

  function resetScore() {
    if (confirm('Weet je zeker dat je alle sterren en punten wilt wissen?')) {
      localStorage.removeItem(SCORE_SLEUTEL);
      _updateHeaderScore();
      document.getElementById('sterrenBalk').style.display = 'none';
      alert('Score gewist! Begin opnieuw met spelen.');
    }
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
    document.querySelectorAll('.stap').forEach(dot => {
      const nr = parseInt(dot.dataset.stap);
      dot.classList.remove('actief','klaar');
      if (nr === stapNummer)    dot.classList.add('actief');
      else if (nr < stapNummer) dot.classList.add('klaar');
    });

    if (schermId === 'schermKiezen') {
      document.getElementById('youtubePlayer').src = '';
    }
  }

  // ── Publieke interface ─────────────────────────────────────
  return { filterKanaal, startQuiz, stopQuiz, volgendeVraag, opnieuwDezelfde, resetScore, toonScherm };

})();
