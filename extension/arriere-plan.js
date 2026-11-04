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

/** Port du serveur ciseau, réglable dans la fenêtre de l'extension. */
async function portServeur() {
  const { port } = await chrome.storage.local.get("port");
  return Number(port) || PORT_DEFAUT;
}

/** Appelle l'API du serveur local et renvoie un résultat toujours sérialisable. */
async function appelerApi({ methode = "GET", chemin, corps }) {
  const port = await portServeur();
  const options = { method: methode, headers: {} };
  if (methode === "POST") {
    // Le serveur exige du JSON sur chaque POST (protection contre les autres sites),
    // y compris quand il n'y a rien à envoyer.
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(corps ?? {});
  }
  try {
    const reponse = await fetch(`http://127.0.0.1:${port}${chemin}`, options);
    const donnees = await reponse.json().catch(() => null);
    return { ok: reponse.ok, statut: reponse.status, donnees };
  } catch (erreur) {
    // fetch échoue (au lieu de répondre) quand personne n'écoute sur le port.
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
