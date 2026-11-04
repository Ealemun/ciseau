"""Serveur web local : l'API JSON derrière l'interface `ciseau ui`.

Volontairement bâti sur la bibliothèque standard (http.server + threads)
pour que l'outil s'installe sans dépendance supplémentaire. Un seul
utilisateur, en local : un serveur multi-threads et une file de travaux
traités un par un (ffmpeg occupe déjà tous les cœurs) suffisent largement.

Routes :
    GET  /                 -> la page (ui/index.html)
    POST /api/info         {source, cookies_navigateur?}      -> MediaInfo
    POST /api/jobs         {source, debut, fin, mode, ...}    -> job créé
    GET  /api/jobs         -> tous les travaux, du plus récent au plus ancien
    GET  /api/jobs/<id>    -> un travail
    GET  /fichier/<id>     -> télécharge le fichier produit par ce travail
    POST /api/jobs/<id>/dossier -> ouvre le dossier du fichier dans l'explorateur
"""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import queue
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, pipeline, resolver
from .options import Options

DOSSIER_UI = Path(__file__).parent / "ui"


# ---------------------------------------------------------------------------
# Travaux (jobs)
# ---------------------------------------------------------------------------

@dataclass
class Travail:
    id: str
    source: str
    debut: str | float | None
    fin: str | float | None
    mode: str
    statut: str = "en_attente"      # en_attente | en_cours | termine | erreur
    message: str = ""               # étape en cours, lisible
    progression: float | None = None  # 0..1 quand ffmpeg la rapporte (découpe locale)
    titre: str = ""
    fichier: str | None = None      # chemin du fichier produit
    nom_fichier: str | None = None
    erreur: str | None = None
    cree_le: float = field(default_factory=time.time)
    termine_le: float | None = None
    options: dict = field(default_factory=dict)  # options sérialisables (hauteur, cookies…)


class FileDeTravaux:
    """File FIFO + un thread ouvrier qui exécute pipeline.extraire()."""

    def __init__(self, dossier_sortie: Path) -> None:
        self.dossier_sortie = dossier_sortie
        self._travaux: dict[str, Travail] = {}
        self._ordre: list[str] = []
        self._file: queue.Queue[str] = queue.Queue()
        self._verrou = threading.Lock()
        threading.Thread(target=self._boucle, name="ciseau-ouvrier", daemon=True).start()

    # -- API publique --------------------------------------------------------

    def ajouter(self, donnees: dict) -> Travail:
        # Attention : 0 est un début valide, on ne peut donc pas écrire `x or None`.
        def temps(cle: str):
            valeur = donnees.get(cle)
            return None if valeur in (None, "") else valeur

        if not str(donnees.get("source") or "").strip():
            raise ValueError("source manquante")
        travail = Travail(
            id=uuid.uuid4().hex[:8],
            source=str(donnees["source"]).strip(),
            debut=temps("debut"),
            fin=temps("fin"),
            mode=donnees.get("mode") or "precis",
            options={k: donnees[k] for k in ("hauteur_max", "encodeur", "cookies_navigateur")
                     if donnees.get(k)},
        )
        with self._verrou:
            self._travaux[travail.id] = travail
            self._ordre.append(travail.id)
        self._file.put(travail.id)
        return travail

    def tous(self) -> list[dict]:
        with self._verrou:
            return [asdict(self._travaux[i]) for i in reversed(self._ordre)]

    def un(self, ident: str) -> Travail | None:
        with self._verrou:
            return self._travaux.get(ident)

    # -- Ouvrier -------------------------------------------------------------

    def _boucle(self) -> None:
        while True:
            ident = self._file.get()
            travail = self.un(ident)
            if travail is None:
                continue
            self._executer(travail)

    def _executer(self, t: Travail) -> None:
        t.statut, t.message = "en_cours", "démarrage…"
        options = Options(
            mode=t.mode,  # type: ignore[arg-type]
            dossier_sortie=self.dossier_sortie,
            hauteur_max=t.options.get("hauteur_max"),
            encodeur=t.options.get("encodeur") or Options().encodeur,
            cookies_navigateur=t.options.get("cookies_navigateur"),
        )

        def message(texte: str) -> None:
            t.message = texte

        def progression(fraction: float) -> None:
            t.progression = fraction

        try:
            resultat = pipeline.extraire(t.source, t.debut, t.fin, options,
                                         sur_message=message, sur_progression=progression)
            t.titre = resultat.info.titre
            t.fichier = str(resultat.fichier)
            t.nom_fichier = resultat.fichier.name
            t.statut, t.message, t.progression = "termine", "terminé", 1.0
        except Exception as exc:  # noqa: BLE001 — on veut tout remonter à l'interface
            t.statut, t.erreur, t.message = "erreur", str(exc), "échec"
            traceback.print_exc()
        finally:
            t.termine_le = time.time()


# ---------------------------------------------------------------------------
# Serveur HTTP
# ---------------------------------------------------------------------------

def ouvrir_dossier(fichier: Path) -> None:
    """Ouvre l'explorateur de fichiers sur le fichier (Windows, macOS, Linux)."""
    systeme = platform.system()
    if systeme == "Windows":
        subprocess.Popen(["explorer", "/select,", str(fichier)])
    elif systeme == "Darwin":
        subprocess.Popen(["open", "-R", str(fichier)])
    else:
        subprocess.Popen(["xdg-open", str(fichier.parent)])


class Gestionnaire(BaseHTTPRequestHandler):
    """Routage HTTP. L'état partagé (file de travaux) est attaché à la classe serveur."""

    server: "ServeurCiseau"

    # -- Utilitaires ---------------------------------------------------------

    def _json(self, donnees, statut: int = 200) -> None:
        corps = json.dumps(donnees, ensure_ascii=False).encode("utf-8")
        self.send_response(statut)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _lire_json(self) -> dict:
        taille = int(self.headers.get("Content-Length") or 0)
        if not taille:
            return {}
        return json.loads(self.rfile.read(taille).decode("utf-8"))

    def _fichier(self, chemin: Path, telechargement: bool = False) -> None:
        if not chemin.is_file():
            self._json({"erreur": "fichier introuvable"}, 404)
            return
        type_mime = mimetypes.guess_type(str(chemin))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(chemin.stat().st_size))
        if telechargement:
            # Nom encodé pour les accents (RFC 5987).
            from urllib.parse import quote
            self.send_header("Content-Disposition",
                             f"attachment; filename*=UTF-8''{quote(chemin.name)}")
        self.end_headers()
        with chemin.open("rb") as f:
            while bloc := f.read(1 << 16):
                self.wfile.write(bloc)

    def log_message(self, fmt, *args):  # noqa: D401 — silence le journal par défaut
        if self.server.verbeux:
            super().log_message(fmt, *args)

    # -- Sécurité ------------------------------------------------------------
    #
    # Le serveur n'écoute que sur 127.0.0.1, mais n'importe quel site ouvert
    # dans le navigateur pourrait quand même lui envoyer des requêtes (la
    # machine qui exécute la page EST 127.0.0.1). Sans protection, une page
    # malveillante pourrait lancer des téléchargements ou ouvrir l'explorateur.
    # Trois verrous, du plus simple au plus subtil :
    #
    # 1. En-tête Host : doit désigner la machine locale. Bloque le « DNS
    #    rebinding » (un domaine piégé qui se met à pointer vers 127.0.0.1).
    # 2. En-tête Origin (envoyé par les navigateurs pour les requêtes
    #    inter-sites) : seuls l'interface elle-même et les extensions sont admises.
    # 3. Les POST doivent être en application/json : pour une page web, ce type
    #    déclenche une requête préalable CORS que le serveur ne valide jamais,
    #    donc la vraie requête n'est même pas envoyée.

    def _hotes_autorises(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    def _requete_autorisee(self, post: bool) -> str | None:
        """Renvoie None si la requête est acceptable, sinon la raison du refus."""
        hote = (self.headers.get("Host") or "").lower()
        if hote not in self._hotes_autorises():
            return "hôte non autorisé"
        origine = self.headers.get("Origin")
        if origine:
            origine = origine.lower()
            interne = {f"http://{h}" for h in self._hotes_autorises()}
            extension = origine.startswith(("chrome-extension://", "moz-extension://"))
            if origine not in interne and not extension:
                return "origine non autorisée"
        if post and not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return "Content-Type application/json attendu"
        return None

    def _refuser_si_besoin(self, post: bool) -> bool:
        """Répond 403 et renvoie True si la requête doit être refusée."""
        raison = self._requete_autorisee(post)
        if raison:
            self._json({"erreur": f"requête refusée : {raison}"}, 403)
            return True
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        # Requête préalable CORS d'une page web : refusée sans en-têtes CORS,
        # le navigateur abandonne donc la requête réelle.
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- Routes --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if self._refuser_si_besoin(post=False):
            return
        chemin = urlparse(self.path).path
        if chemin in ("/", "/index.html"):
            self._fichier(DOSSIER_UI / "index.html")
        elif chemin == "/api/version":
            self._json({"version": __version__, "dossier": str(self.server.file.dossier_sortie)})
        elif chemin == "/api/jobs":
            self._json(self.server.file.tous())
        elif chemin.startswith("/api/jobs/"):
            t = self.server.file.un(chemin.split("/")[3])
            self._json(asdict(t) if t else {"erreur": "inconnu"}, 200 if t else 404)
        elif chemin.startswith("/fichier/"):
            t = self.server.file.un(chemin.split("/")[2])
            if t and t.fichier:
                self._fichier(Path(t.fichier), telechargement=True)
            else:
                self._json({"erreur": "pas de fichier"}, 404)
        else:
            self._json({"erreur": "route inconnue"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if self._refuser_si_besoin(post=True):
            return
        chemin = urlparse(self.path).path
        try:
            if chemin == "/api/info":
                donnees = self._lire_json()
                options = Options(cookies_navigateur=donnees.get("cookies_navigateur") or None)
                info = resolver.resoudre(donnees["source"], options)
                self._json(asdict(info))
            elif chemin == "/api/jobs":
                travail = self.server.file.ajouter(self._lire_json())
                self._json(asdict(travail), 201)
            elif chemin.startswith("/api/jobs/") and chemin.endswith("/dossier"):
                t = self.server.file.un(chemin.split("/")[3])
                if t and t.fichier:
                    ouvrir_dossier(Path(t.fichier))
                    self._json({"ok": True})
                else:
                    self._json({"erreur": "pas de fichier"}, 404)
            else:
                self._json({"erreur": "route inconnue"}, 404)
        except Exception as exc:  # noqa: BLE001 — l'interface affiche le message
            self._json({"erreur": str(exc)}, 400)


class ServeurCiseau(ThreadingHTTPServer):
    """ThreadingHTTPServer + la file de travaux partagée."""

    daemon_threads = True

    def __init__(self, hote: str, port: int, dossier_sortie: Path, verbeux: bool = False) -> None:
        super().__init__((hote, port), Gestionnaire)
        self.file = FileDeTravaux(dossier_sortie)
        self.verbeux = verbeux

    @property
    def url(self) -> str:
        return f"http://{self.server_address[0]}:{self.server_address[1]}/"


def lancer(port: int = 8765, dossier_sortie: Path = Path("extraits"),
           ouvrir_navigateur: bool = True, verbeux: bool = False) -> None:
    """Démarre le serveur (bloquant) et ouvre le navigateur sur l'interface."""
    serveur = ServeurCiseau("127.0.0.1", port, dossier_sortie.resolve(), verbeux)
    print(f"ciseau {__version__} — interface sur {serveur.url}  (Ctrl+C pour arrêter)")
    print(f"extraits rangés dans {serveur.file.dossier_sortie}")
    if ouvrir_navigateur:
        import webbrowser
        threading.Timer(0.4, lambda: webbrowser.open(serveur.url)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\narrêt")
    finally:
        serveur.server_close()
        os._exit(0)  # coupe net les threads ouvriers/ffmpeg encore en cours
