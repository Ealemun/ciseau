/* ciseau — panneau injecté dans la page vidéo.
 *
 * - Sur YouTube, il se charge tout seul (voir content_scripts dans manifest.json).
 * - Sur n'importe quel autre site, le bouton « Afficher le panneau sur cette
 *   page » de la fenêtre de l'extension l'injecte à la demande.
 *
 * Fonctionnement : pendant la lecture, la touche D pose le début à l'instant
 * courant, la touche E pose la fin. « Revoir » rejoue exactement le passage,
 * « Extraire » envoie le travail au serveur local `ciseau ui`, puis le panneau
 * suit sa progression jusqu'au fichier prêt.
 *
 * Le panneau vit dans un Shadow DOM : les styles de la page ne l'atteignent
 * pas, et les siens ne débordent pas sur la page.
 */
(() => {
  // Déjà chargé dans cette page (réinjection depuis la fenêtre) : on le ré-affiche.
  if (window.__ciseau) {
    window.__ciseau.afficher();
    return;
  }

  const SUR_YOUTUBE = /(^|\.)youtube\.com$/.test(location.hostname);

  // ------------------------------------------------------------------
  // État
  // ------------------------------------------------------------------
  let debut = null; // secondes ; null = début de la vidéo
  let fin = null;   // secondes ; null = fin de la vidéo
  let reglages = { toucheDebut: "d", toucheFin: "e", mode: "precis", replie: false };
  let travailId = null;      // travail en cours de suivi
  let minuterieSuivi = null; // setTimeout du suivi
  let finRevoir = null;      // instant où « Revoir » doit mettre en pause

  // ------------------------------------------------------------------
  // Timecodes (mêmes règles que ciseau/timecode.py)
  // ------------------------------------------------------------------
  function lireTimecode(texte) {
    texte = String(texte).trim().toLowerCase().replace(",", ".");
    if (!texte) return null; // champ vide = borne libre
    if (texte.includes(":")) {
      const morceaux = texte.split(":");
      if (morceaux.length > 3 || morceaux.some((m) => m === "" || isNaN(m))) throw new Error("timecode illisible");
      return morceaux.reduce((acc, m) => acc * 60 + parseFloat(m), 0);
    }
    const m = texte.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?$/);
    if (!m || (!m[1] && !m[2] && !m[3])) throw new Error("timecode illisible");
    return (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (parseFloat(m[3]) || 0);
  }

  function ecrireTimecode(s) {
    const ms = Math.round(Math.max(0, s) * 1000);
    const h = Math.floor(ms / 3600000);
    const mn = Math.floor((ms % 3600000) / 60000);
    const sec = Math.floor((ms % 60000) / 1000);
    const mil = ms % 1000;
    const base = (h ? h + ":" + String(mn).padStart(2, "0") : mn) + ":" + String(sec).padStart(2, "0");
    return base + "." + String(mil).padStart(3, "0");
  }

  // ------------------------------------------------------------------
  // La vidéo de la page et la source à envoyer au serveur
  // ------------------------------------------------------------------
  function videoPrincipale() {
    if (SUR_YOUTUBE) {
      const v = document.querySelector("video.html5-main-video");
      if (v) return v;
    }
    // Ailleurs : la plus grande vidéo visible de la page.
    let meilleure = null;
    let aireMax = 0;
    for (const v of document.querySelectorAll("video")) {
      const r = v.getBoundingClientRect();
      const aire = r.width * r.height;
      if (aire > aireMax) {
        aireMax = aire;
        meilleure = v;
      }
    }
    return meilleure;
  }

  /** Vrai si la page YouTube courante est une vidéo (et pas l'accueil, une recherche…). */
  function pageVideoYouTube() {
    return location.pathname === "/watch" || location.pathname.startsWith("/shorts/");
  }

  /** Quelle adresse envoyer au serveur pour cette vidéo, et comment la décrire. */
  function sourceAEnvoyer(video) {
    if (SUR_YOUTUBE) {
      const url = new URL(location.href);
      const id = url.searchParams.get("v");
      if (url.pathname === "/watch" && id) {
        // Adresse canonique : sans playlist, sans ?t= (le début est envoyé à part).
        return { url: "https://www.youtube.com/watch?v=" + id, type: "vidéo YouTube" };
      }
      const short = url.pathname.match(/^\/shorts\/([\w-]+)/);
      if (short) return { url: "https://www.youtube.com/shorts/" + short[1], type: "Short YouTube" };
    }
    // Fichier vidéo en clair (pas un flux « blob: » assemblé par la page) : ciseau
    // le lit directement. Sinon on envoie l'adresse de la page, que yt-dlp connaît
    // pour la plupart des sites (Twitch, Twitter/X, Vimeo…).
    const src = video?.currentSrc || "";
    if (/^https?:\/\//.test(src)) return { url: src, type: "fichier vidéo de la page" };
    return { url: location.href, type: "page" };
  }

  // ------------------------------------------------------------------
  // Communication avec l'arrière-plan (qui parle au serveur local)
  // ------------------------------------------------------------------
  function api(methode, chemin, corps) {
    return new Promise((resoudre) => {
      try {
        chrome.runtime.sendMessage({ type: "api", methode, chemin, corps }, (reponse) => {
          if (chrome.runtime.lastError || !reponse) {
            resoudre({ ok: false, horsLigne: true });
          } else {
            resoudre(reponse);
          }
        });
      } catch (e) {
        // L'extension a été rechargée : ce script est orphelin jusqu'au rechargement de la page.
        resoudre({ ok: false, orphelin: true });
      }
    });
  }

  // ------------------------------------------------------------------
  // Panneau (Shadow DOM)
  // ------------------------------------------------------------------
  const hote = document.createElement("div");
  hote.id = "ciseau-panneau";
  // Au-dessus des lecteurs plein écran « faux » de certains sites, pas du vrai plein écran.
  hote.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483646;";
  const ombre = hote.attachShadow({ mode: "open" });

  ombre.innerHTML = `
<style>
  :host { all: initial; }
  * { box-sizing: border-box; font-family: "Segoe UI", system-ui, -apple-system, sans-serif; }
  /* Couleurs reprises de l'interface ciseau : tapis de découpe vert, accent orangé pour couper. */
  .carte {
    width: 300px; background: #1e3a31; color: #edefe8; border-radius: 10px;
    box-shadow: 0 10px 30px rgba(0,0,0,.45); padding: 12px 14px 14px; font-size: 13px; line-height: 1.4;
  }
  .tete { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .nom { font-weight: 700; font-size: 15px; letter-spacing: -.01em; }
  .nom b { color: #e4572e; }
  .source { color: #8ea39a; font-size: 12px; margin: -6px 0 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ligne { display: grid; grid-template-columns: 40px 1fr auto; gap: 8px; align-items: center; margin-bottom: 6px; }
  .ligne label { color: #8ea39a; }
  input, select {
    font: inherit; color: #1b2a24; background: #edefe8; border: 1px solid transparent;
    border-radius: 5px; padding: 5px 8px; width: 100%;
  }
  input { font-family: Consolas, "JetBrains Mono", monospace; font-size: 14px; }
  input::placeholder { color: #8ea39a; }
  input.invalide { border-color: #e4572e; }
  button {
    font: inherit; font-weight: 600; cursor: pointer; border-radius: 5px; padding: 5px 10px;
    border: 1px solid rgba(237,239,232,.35); background: transparent; color: #edefe8;
  }
  button:hover { border-color: #edefe8; }
  button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid #e4572e; outline-offset: 1px; }
  button:disabled { opacity: .45; cursor: default; }
  kbd {
    font-family: Consolas, monospace; font-size: 11px; border: 1px solid rgba(237,239,232,.4);
    border-bottom-width: 2px; border-radius: 3px; padding: 0 4px; margin-left: 4px; text-transform: uppercase;
  }
  .duree { display: flex; justify-content: space-between; align-items: center; margin: 8px 0 10px; gap: 10px; }
  .duree span { color: #8ea39a; }
  .duree strong { font-family: Consolas, monospace; font-size: 15px; color: #fff; }
  .duree select { width: auto; padding: 3px 6px; }
  .actions { display: flex; gap: 8px; }
  .actions .extraire { flex: 1; background: #e4572e; border-color: #e4572e; color: #fff; }
  .actions .extraire:hover:not(:disabled) { background: #c3461f; border-color: #c3461f; }
  .statut { margin-top: 10px; color: #cfd6cf; min-height: 0; word-break: break-word; }
  .statut:empty { display: none; }
  .statut.erreur { color: #ffb39c; }
  .statut .barre { height: 4px; background: rgba(237,239,232,.15); border-radius: 2px; margin-top: 6px; overflow: hidden; }
  .statut .barre i { display: block; height: 100%; background: #e4572e; transition: width .4s; }
  .statut button { margin-top: 6px; padding: 3px 8px; font-weight: 500; }
  .replier { border: 0; padding: 2px 6px; font-size: 16px; line-height: 1; color: #8ea39a; }
  /* Version repliée : une pastille. */
  .pastille {
    position: relative; width: 44px; height: 44px; border-radius: 50%; background: #1e3a31; color: #e4572e;
    border: 0; font-size: 22px; box-shadow: 0 6px 18px rgba(0,0,0,.4); display: grid; place-items: center; padding: 0;
  }
  .pastille.marque::after {
    content: ""; position: absolute; top: 1px; right: 1px; width: 11px; height: 11px; border-radius: 50%;
    background: #e4572e; border: 2px solid #1e3a31;
  }
  [hidden] { display: none !important; }
</style>
<button class="pastille" id="pastille" title="Ouvrir ciseau" hidden>✂</button>
<div class="carte" id="carte">
  <div class="tete">
    <span class="nom"><b>c</b>iseau</span>
    <button class="replier" id="replier" title="Replier">–</button>
  </div>
  <div class="source" id="source"></div>
  <div class="ligne">
    <label for="debut">Début</label>
    <input id="debut" placeholder="début de la vidéo" spellcheck="false" autocomplete="off">
    <button id="poser-debut" title="Prendre l'instant de la vidéo">Ici<kbd id="kbd-debut">d</kbd></button>
  </div>
  <div class="ligne">
    <label for="fin">Fin</label>
    <input id="fin" placeholder="fin de la vidéo" spellcheck="false" autocomplete="off">
    <button id="poser-fin" title="Prendre l'instant de la vidéo">Ici<kbd id="kbd-fin">e</kbd></button>
  </div>
  <div class="duree">
    <span>Durée <strong id="duree">—</strong></span>
    <select id="mode" title="Mode de coupe">
      <option value="precis">Précis</option>
      <option value="rapide">Rapide</option>
      <option value="audio">Audio seul</option>
    </select>
  </div>
  <div class="actions">
    <button id="revoir" title="Rejouer le passage choisi">Revoir</button>
    <button class="extraire" id="extraire">Extraire</button>
  </div>
  <div class="statut" id="statut"></div>
</div>`;

  const $ = (id) => ombre.getElementById(id);

  // ------------------------------------------------------------------
  // Affichage
  // ------------------------------------------------------------------

  /** Met à jour champs, durée, boutons et repère sur la barre de progression. */
  function rafraichir() {
    const video = videoPrincipale();
    const total = video && isFinite(video.duration) ? video.duration : null;

    // Ne pas écraser ce que l'utilisateur est en train de taper.
    const actif = ombre.activeElement;
    if (actif !== $("debut")) $("debut").value = debut == null ? "" : ecrireTimecode(debut);
    if (actif !== $("fin")) $("fin").value = fin == null ? "" : ecrireTimecode(fin);

    const a = debut ?? 0;
    const b = fin ?? total;
    $("duree").textContent = b != null && b > a ? ecrireTimecode(b - a) : "—";
    $("extraire").disabled = !video || (b != null && b <= a) || (b == null && fin == null && total == null);
    $("revoir").disabled = !video;

    const src = sourceAEnvoyer(video);
    $("source").textContent = video ? src.type : "aucune vidéo trouvée sur cette page";
    $("source").title = src.url;

    $("carte").hidden = reglages.replie;
    $("pastille").hidden = !reglages.replie;
    // Pastille marquée quand un passage est posé, pour ne pas l'oublier une fois replié.
    $("pastille").classList.toggle("marque", debut != null || fin != null);

    $("kbd-debut").textContent = reglages.toucheDebut;
    $("kbd-fin").textContent = reglages.toucheFin;
    $("mode").value = reglages.mode;

    majRepereYouTube(total);
  }

  /** Surligne le passage choisi directement sur la barre de progression de YouTube. */
  function majRepereYouTube(total) {
    if (!SUR_YOUTUBE) return;
    const barre = document.querySelector(".ytp-progress-bar");
    let repere = document.getElementById("ciseau-repere");
    if (!barre || !total || (debut == null && fin == null)) {
      repere?.remove();
      return;
    }
    if (!repere || repere.parentElement !== barre) {
      repere?.remove();
      repere = document.createElement("div");
      repere.id = "ciseau-repere";
      repere.style.cssText =
        "position:absolute;top:-3px;bottom:-3px;background:rgba(228,87,46,.55);" +
        "border-left:2px solid #e4572e;border-right:2px solid #e4572e;pointer-events:none;z-index:40;";
      barre.appendChild(repere);
    }
    const a = debut ?? 0;
    const b = fin ?? total;
    repere.style.left = (100 * a) / total + "%";
    repere.style.width = Math.max(0, (100 * (b - a)) / total) + "%";
  }

  function afficherStatut(html, erreur = false) {
    $("statut").innerHTML = html;
    $("statut").classList.toggle("erreur", erreur);
  }

  const echapper = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  const MESSAGE_HORS_LIGNE =
    "ciseau n'est pas lancé. Double-clique sur <b>ciseau.bat</b> dans le dossier du projet, puis réessaie.";

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------

  function poserDebut() {
    const video = videoPrincipale();
    if (!video) return;
    debut = video.currentTime;
    if (fin != null && fin <= debut) fin = null; // une fin avant le début n'a plus de sens
    rafraichir();
  }

  function poserFin() {
    const video = videoPrincipale();
    if (!video) return;
    fin = video.currentTime;
    if (debut != null && fin < debut) [debut, fin] = [fin, debut]; // posés à l'envers : on inverse
    rafraichir();
  }

  function revoir() {
    const video = videoPrincipale();
    if (!video) return;
    video.currentTime = debut ?? 0;
    finRevoir = fin; // null = jusqu'au bout
    video.play();
  }

  // Pause automatique à la fin du passage pendant « Revoir ».
  document.addEventListener(
    "timeupdate",
    (ev) => {
      if (finRevoir != null && ev.target === videoPrincipale() && ev.target.currentTime >= finRevoir) {
        ev.target.pause();
        finRevoir = null;
      }
    },
    true // les événements média ne remontent pas : on les capte en descente
  );

  async function extraire() {
    const video = videoPrincipale();
    if (!video) return;
    const source = sourceAEnvoyer(video);
    $("extraire").disabled = true;
    afficherStatut("Envoi à ciseau…");
    const r = await api("POST", "/api/jobs", {
      source: source.url,
      debut: debut ?? 0,
      fin: fin, // null = jusqu'à la fin
      mode: reglages.mode,
    });
    $("extraire").disabled = false;
    if (r.orphelin) return afficherStatut("L'extension a été mise à jour : recharge la page.", true);
    if (r.horsLigne) return afficherStatut(MESSAGE_HORS_LIGNE, true);
    if (!r.ok) return afficherStatut(echapper(r.donnees?.erreur || "refusé par ciseau"), true);
    travailId = r.donnees.id;
    suivre();
  }

  /** Interroge le serveur chaque seconde jusqu'à la fin du travail. */
  async function suivre() {
    clearTimeout(minuterieSuivi);
    if (!travailId) return;
    const id = travailId;
    const r = await api("GET", "/api/jobs/" + id);
    if (id !== travailId) return; // un autre extrait a été lancé entre-temps
    if (r.horsLigne) return afficherStatut(MESSAGE_HORS_LIGNE, true);
    const t = r.donnees;
    if (t.statut === "termine") {
      afficherStatut(`Prêt : ${echapper(t.nom_fichier)}<br><button id="ouvrir">Ouvrir le dossier</button>`);
      $("ouvrir").onclick = () => api("POST", `/api/jobs/${id}/dossier`);
      travailId = null;
      return;
    }
    if (t.statut === "erreur") {
      travailId = null;
      return afficherStatut("Échec : " + echapper(t.erreur), true);
    }
    const etape = t.statut === "en_attente" ? "En attente…" : echapper(t.message || "En cours…");
    const pct = t.progression != null ? Math.round(t.progression * 100) : null;
    afficherStatut(etape + (pct != null ? ` ${pct} %<div class="barre"><i style="width:${pct}%"></i></div>` : ""));
    minuterieSuivi = setTimeout(suivre, 1000);
  }

  // ------------------------------------------------------------------
  // Branchements
  // ------------------------------------------------------------------
  $("poser-debut").onclick = poserDebut;
  $("poser-fin").onclick = poserFin;
  $("revoir").onclick = revoir;
  $("extraire").onclick = extraire;
  $("replier").onclick = () => {
    reglages.replie = true;
    sauver();
    rafraichir();
  };
  $("pastille").onclick = () => {
    reglages.replie = false;
    sauver();
    rafraichir();
  };
  $("mode").onchange = () => {
    reglages.mode = $("mode").value;
    sauver();
  };

  // Saisie manuelle des timecodes : validée à la sortie du champ ou avec Entrée.
  for (const [id, poser] of [
    ["debut", (v) => (debut = v)],
    ["fin", (v) => (fin = v)],
  ]) {
    const champ = $(id);
    const valider = () => {
      try {
        poser(lireTimecode(champ.value));
        champ.classList.remove("invalide");
        rafraichir();
      } catch {
        champ.classList.add("invalide");
      }
    };
    champ.addEventListener("change", valider);
    champ.addEventListener("keydown", (ev) => {
      ev.stopPropagation(); // ne pas déclencher les raccourcis de YouTube en tapant
      if (ev.key === "Enter") champ.blur();
    });
  }

  // Touches D / E (réglables) pendant la lecture.
  document.addEventListener(
    "keydown",
    (ev) => {
      if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
      // Ne rien intercepter quand on tape quelque part (recherche, commentaires…).
      const cible = ev.composedPath()[0];
      if (cible instanceof HTMLElement && (cible.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(cible.tagName))) return;
      if (!hote.isConnected || (SUR_YOUTUBE && !pageVideoYouTube())) return;
      const touche = ev.key.toLowerCase();
      if (touche === reglages.toucheDebut) poserDebut();
      else if (touche === reglages.toucheFin) poserFin();
      else return;
      // Capturé avant YouTube : il ne verra pas la touche.
      ev.preventDefault();
      ev.stopImmediatePropagation();
    },
    true
  );

  // YouTube est une application d'une seule page : changer de vidéo ne recharge rien.
  function surChangementDePage() {
    debut = fin = null;
    finRevoir = null;
    if (!travailId) afficherStatut("");
    if (SUR_YOUTUBE && !pageVideoYouTube()) {
      hote.remove();
      document.getElementById("ciseau-repere")?.remove();
      return;
    }
    if (!hote.isConnected) document.documentElement.appendChild(hote);
    rafraichir();
  }
  if (SUR_YOUTUBE) document.addEventListener("yt-navigate-finish", surChangementDePage);

  // La durée n'est connue qu'une fois la vidéo chargée ; la barre de YouTube est
  // parfois reconstruite : un rafraîchissement léger et régulier garde tout à jour.
  setInterval(() => {
    if (hote.isConnected) rafraichir();
  }, 1000);

  // ------------------------------------------------------------------
  // Réglages persistants
  // ------------------------------------------------------------------
  function sauver() {
    try {
      chrome.storage.local.set({ mode: reglages.mode, replie: reglages.replie });
    } catch {}
  }

  chrome.storage.local.get(["toucheDebut", "toucheFin", "mode", "replie"], (r) => {
    reglages = {
      toucheDebut: (r.toucheDebut || "d").toLowerCase(),
      toucheFin: (r.toucheFin || "e").toLowerCase(),
      mode: r.mode || "precis",
      replie: !!r.replie,
    };
    rafraichir();
  });
  // Les touches réglées dans la fenêtre de l'extension s'appliquent sans recharger.
  chrome.storage.onChanged.addListener((changements) => {
    if (changements.toucheDebut) reglages.toucheDebut = (changements.toucheDebut.newValue || "d").toLowerCase();
    if (changements.toucheFin) reglages.toucheFin = (changements.toucheFin.newValue || "e").toLowerCase();
    rafraichir();
  });

  // ------------------------------------------------------------------
  // Démarrage
  // ------------------------------------------------------------------
  window.__ciseau = {
    afficher() {
      reglages.replie = false;
      if (!hote.isConnected) document.documentElement.appendChild(hote);
      rafraichir();
    },
  };

  if (!SUR_YOUTUBE || pageVideoYouTube()) {
    document.documentElement.appendChild(hote);
    rafraichir();
  }
})();
