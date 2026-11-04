/* ciseau — fenêtre de l'extension : état du serveur, derniers extraits, réglages. */

const $ = (id) => document.getElementById(id);
const PORT_DEFAUT = 8765;

/** Appel au serveur local via l'arrière-plan (même chemin que le panneau). */
function api(methode, chemin, corps) {
  return new Promise((resoudre) =>
    chrome.runtime.sendMessage({ type: "api", methode, chemin, corps }, (r) =>
      resoudre(r || { ok: false, horsLigne: true })
    )
  );
}

// ------------------------------------------------------------------
// État du serveur et derniers extraits
// ------------------------------------------------------------------
async function majEtat() {
  const r = await api("GET", "/api/version");
  const enLigne = r.ok;
  $("etat").className = "etat " + (enLigne ? "ok" : "ko");
  $("etat-texte").textContent = enLigne
    ? `ciseau ${r.donnees.version} est lancé`
    : "ciseau n'est pas lancé";
  $("aide-hors-ligne").hidden = enLigne;
  if (!enLigne) {
    $("vide").hidden = false;
    return;
  }

  const travaux = (await api("GET", "/api/jobs")).donnees || [];
  const ul = $("travaux");
  ul.innerHTML = "";
  $("vide").hidden = travaux.length > 0;
  const libelles = { en_attente: "en attente", en_cours: "en cours", termine: "prêt", erreur: "échec" };
  for (const t of travaux.slice(0, 5)) {
    const li = document.createElement("li");
    const nom = document.createElement("div");
    nom.className = "nom";
    nom.textContent = t.nom_fichier || t.titre || t.source;
    const info = document.createElement("div");
    info.className = "info" + (t.statut === "erreur" ? " erreur" : "");
    info.textContent =
      t.statut === "en_cours" && t.message ? t.message : t.statut === "erreur" ? "échec : " + t.erreur : libelles[t.statut];
    li.append(nom, info);
    ul.appendChild(li);
  }
  // Tant que quelque chose tourne, on rafraîchit.
  if (travaux.some((t) => t.statut === "en_cours" || t.statut === "en_attente")) setTimeout(majEtat, 1000);
}

// ------------------------------------------------------------------
// Boutons
// ------------------------------------------------------------------
$("injecter").onclick = async () => {
  $("message").textContent = "";
  const [onglet] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    await chrome.scripting.executeScript({ target: { tabId: onglet.id }, files: ["contenu.js"] });
    window.close();
  } catch (e) {
    // Pages internes du navigateur (chrome://, boutique d'extensions…) : interdit.
    $("message").textContent = "Impossible sur cette page : le navigateur interdit les extensions ici.";
  }
};

$("interface").onclick = async () => {
  const { port } = await chrome.storage.local.get("port");
  chrome.tabs.create({ url: `http://127.0.0.1:${Number(port) || PORT_DEFAUT}/` });
};

// ------------------------------------------------------------------
// Réglages (enregistrés à chaque modification)
// ------------------------------------------------------------------
chrome.storage.local.get(["toucheDebut", "toucheFin", "port"], (r) => {
  $("touche-debut").value = r.toucheDebut || "d";
  $("touche-fin").value = r.toucheFin || "e";
  $("port").value = r.port || PORT_DEFAUT;
});

for (const [id, cle] of [
  ["touche-debut", "toucheDebut"],
  ["touche-fin", "toucheFin"],
]) {
  $(id).addEventListener("input", () => {
    const valeur = $(id).value.trim().toLowerCase();
    const autre = $(id === "touche-debut" ? "touche-fin" : "touche-debut").value.trim().toLowerCase();
    // Une seule touche, différente de l'autre ; sinon on n'enregistre pas.
    if (valeur.length === 1 && valeur !== autre) {
      chrome.storage.local.set({ [cle]: valeur });
      $("message").textContent = "";
    } else if (valeur.length === 1) {
      $("message").textContent = "Choisis deux touches différentes pour le début et la fin.";
    }
  });
}

$("port").addEventListener("change", () => {
  const port = parseInt($("port").value, 10);
  if (port > 0 && port < 65536) {
    chrome.storage.local.set({ port });
    majEtat();
  } else {
    $("port").value = PORT_DEFAUT;
  }
});

majEtat();
