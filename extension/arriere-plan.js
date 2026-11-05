/* ciseau — script d'arrière-plan (service worker de l'extension).
 *
 * Seul ce script parle au serveur local `ciseau ui` (http://127.0.0.1:8765).
 * Pourquoi passer par lui plutôt que d'appeler le serveur depuis la page ?
 * Un script injecté dans youtube.com est soumis aux règles de sécurité de la
 * page (CORS) ; le service worker, lui, a la permission explicite d'appeler
 * 127.0.0.1 (voir host_permissions dans manifest.json).
 *
 * Messages acceptés (chrome.runtime.sendMessage) :
 *   { type: "api", methode: "GET"|"POST", chemin: "/api/…", corps?: {...} }
 *   -> { ok, statut, donnees }  ou  { ok: false, horsLigne: true, erreur }
 */

const PORT_DEFAUT = 8765;
// ciseau prend le premier port libre à partir de 8765 (voir PORTS_A_ESSAYER
// dans ciseau/serveur.py) : on cherche sur la même plage.
const PORTS_A_ESSAYER = 20;

/** Port du serveur ciseau, réglable dans la fenêtre de l'extension. */
async function portServeur() {
  const { port } = await chrome.storage.local.get("port");
  return Number(port) || PORT_DEFAUT;
}

/** Vrai si ciseau répond sur ce port (et pas un autre programme). */
async function estCiseau(port) {
  try {
    const r = await fetch(`http://127.0.0.1:${port}/api/version`, { signal: AbortSignal.timeout(800) });
    return (await r.json()).application === "ciseau";
  } catch {
    return false;
  }
}

/**
 * Cherche ciseau sur la plage de ports et mémorise celui qui répond.
 * Appelé seulement quand le port mémorisé ne répond plus : ciseau a pu
 * démarrer sur un autre port parce que le sien était pris ou réservé par Windows.
 */
async function retrouverPort() {
  const depart = await portServeur();
  const candidats = [depart];
  for (let p = PORT_DEFAUT; p < PORT_DEFAUT + PORTS_A_ESSAYER; p++) if (p !== depart) candidats.push(p);
  for (const p of candidats) {
    if (await estCiseau(p)) {
      await chrome.storage.local.set({ port: p });
      return p;
    }
  }
  return null;
}

/** Une requête vers ciseau sur un port donné ; lève une erreur si personne n'écoute. */
async function requete(port, { methode = "GET", chemin, corps }) {
  const options = { method: methode, headers: {} };
  if (methode === "POST") {
    // Le serveur exige du JSON sur chaque POST (protection contre les autres sites),
    // y compris quand il n'y a rien à envoyer.
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(corps ?? {});
  }
  const reponse = await fetch(`http://127.0.0.1:${port}${chemin}`, options);
  const donnees = await reponse.json().catch(() => null);
  // Toutes les réponses de l'API de ciseau sont en JSON : sinon, c'est un autre
  // programme qui occupe ce port (on fait alors comme si personne n'écoutait).
  if (donnees === null) throw new Error(`le port ${port} n'est pas celui de ciseau`);
  return { ok: reponse.ok, statut: reponse.status, donnees };
}

/** Appelle l'API du serveur local et renvoie un résultat toujours sérialisable. */
async function appelerApi(message) {
  try {
    return await requete(await portServeur(), message);
  } catch (erreur) {
    // Personne sur le port mémorisé : ciseau a peut-être démarré ailleurs.
    const port = await retrouverPort();
    if (port) {
      try {
        return await requete(port, message);
      } catch {}
    }
    return { ok: false, horsLigne: true, erreur: String(erreur) };
  }
}

chrome.runtime.onMessage.addListener((message, _expediteur, repondre) => {
  if (message?.type === "api") {
    appelerApi(message).then(repondre);
    return true; // réponse asynchrone : garde le canal ouvert
  }
  return false;
});
