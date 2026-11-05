"""Serveur HTTP de test qui imite le comportement de YouTube.

- Sert un dossier de fichiers, avec les requêtes partielles (en-tête Range).
- Compte les octets envoyés, pour vérifier qu'on ne télécharge que l'utile.
- Bride (optionnellement) les requêtes « longues » comme YouTube : une requête
  sans Range, ou dont la plage dépasse 10 Mo, ou ouverte (« bytes=N- »), est
  servie à débit limité. Les requêtes de 10 Mo au plus passent à pleine vitesse.

Utilisable comme module de test (ServeurDash) ou en ligne de commande pour les
mesures manuelles :  python tests/serveur_dash.py DOSSIER PORT [DEBIT_BRIDE]
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LIMITE_YOUTUBE = 10 * 1024 * 1024


class ServeurDash(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, dossier: Path, debit_bride: int | None = None, port: int = 0,
                 tout_brider: bool = False):
        """`debit_bride` : octets/s pour les requêtes longues (None = pas de bridage).

        `tout_brider` : bride aussi les requêtes courtes (pour simuler une connexion
        lente, par exemple afin de tester l'annulation pendant un téléchargement).
        """
        self.dossier = Path(dossier)
        self.debit_bride = debit_bride
        self.tout_brider = tout_brider
        self.octets_envoyes = 0
        self.requetes: list[str] = []  # valeurs des en-têtes Range reçus ("" = aucun)
        self._verrou = threading.Lock()
        super().__init__(("127.0.0.1", port), _Gestionnaire)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def demarrer(self) -> "ServeurDash":
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    def arreter(self) -> None:
        self.shutdown()
        self.server_close()

    def compter(self, n: int) -> None:
        with self._verrou:
            self.octets_envoyes += n


class _Gestionnaire(BaseHTTPRequestHandler):
    server: ServeurDash

    def log_message(self, *args):  # silence
        pass

    def do_GET(self):  # noqa: N802
        chemin = self.server.dossier / self.path.split("?")[0].lstrip("/")
        if not chemin.is_file():
            self.send_error(404)
            return
        taille = chemin.stat().st_size
        plage = self.headers.get("Range") or ""
        with self.server._verrou:
            self.server.requetes.append(plage)

        m = re.match(r"bytes=(\d+)-(\d*)$", plage)
        if m:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else taille - 1
            b = min(b, taille - 1)
            if a >= taille:
                self.send_error(416)
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{taille}")
        else:
            a, b = 0, taille - 1
            self.send_response(200)
        longueur = b - a + 1
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(longueur))
        self.end_headers()

        # Comme YouTube : bridé si pas de plage, plage ouverte, ou plage > 10 Mo.
        bride = self.server.debit_bride and (self.server.tout_brider or not m or not m.group(2)
                                             or longueur > LIMITE_YOUTUBE)
        bloc = 64 * 1024
        with chemin.open("rb") as f:
            f.seek(a)
            reste = longueur
            while reste > 0:
                donnees = f.read(min(bloc, reste))
                if not donnees:
                    break
                try:
                    self.wfile.write(donnees)
                except (BrokenPipeError, ConnectionResetError):
                    return  # le client a fermé (ffmpeg le fait en sautant ailleurs)
                self.server.compter(len(donnees))
                reste -= len(donnees)
                if bride:
                    time.sleep(len(donnees) / self.server.debit_bride)


if __name__ == "__main__":
    dossier, port = sys.argv[1], int(sys.argv[2])
    debit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    srv = ServeurDash(Path(dossier), debit, port)
    print(f"sert {os.path.abspath(dossier)} sur {srv.url} (bridage : {debit or 'aucun'} o/s)")
    srv.serve_forever()
