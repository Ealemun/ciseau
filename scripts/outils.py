"""Petits outils appelés par le Makefile.

Ils sont écrits en Python plutôt qu'en commandes shell parce que le Makefile
doit marcher aussi bien sous Windows (cmd / PowerShell) que sous macOS et
Linux (sh) : le même code Python se comporte partout de la même façon.

Usage :
    python scripts/outils.py verifier        # contrôle les prérequis
    python scripts/outils.py aide Makefile   # liste les cibles du Makefile
    python scripts/outils.py nettoyer        # supprime caches et fichiers temporaires
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# La console Windows (cp1252/cp850) ne sait pas afficher tous les caractères :
# on force l'UTF-8 et on remplace plutôt que de planter.
for flux in (sys.stdout, sys.stderr):
    try:
        flux.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

RACINE = Path(__file__).resolve().parent.parent

# Marqueurs en ASCII pur : lisibles sur n'importe quelle console.
OK, MANQUE, CONSEIL = "[ok]", "[!!]", "[--]"


# ---------------------------------------------------------------------------
# verifier
# ---------------------------------------------------------------------------

def _version_de(commande: list[str]) -> str:
    """Première ligne de la sortie d'une commande `--version`, ou chaîne vide."""
    try:
        sortie = subprocess.run(commande, capture_output=True, text=True, timeout=15)
        lignes = (sortie.stdout or sortie.stderr).strip().splitlines()
        return lignes[0] if lignes else ""
    except Exception:  # noqa: BLE001
        return ""


def verifier() -> int:
    """Contrôle chaque prérequis. Renvoie 1 si un élément indispensable manque."""
    manques: list[str] = []

    def ligne(etat: str, nom: str, detail: str) -> None:
        print(f"  {etat} {nom:<8} {detail}")

    print("Prérequis de ciseau :")

    # --- Python (indispensable) : version minimale exigée par pyproject.toml ---
    v = sys.version_info
    if v >= (3, 10):
        ligne(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    else:
        ligne(MANQUE, "Python", f"{v.major}.{v.minor} trouvé, 3.10 ou plus requis")
        manques.append("python")

    # --- ffmpeg (indispensable) : EXTRAIT_FFMPEG permet de pointer un emplacement précis ---
    ffmpeg = os.environ.get("EXTRAIT_FFMPEG") or shutil.which("ffmpeg")
    if ffmpeg:
        ligne(OK, "ffmpeg", _version_de([ffmpeg, "-version"]).replace("ffmpeg version ", "")[:60])
    else:
        ligne(MANQUE, "ffmpeg", "introuvable (make install-systeme)")
        manques.append("ffmpeg")

    # --- ffprobe : livré avec ffmpeg, sert à lire les durées ---
    ffprobe = os.environ.get("EXTRAIT_FFPROBE") or shutil.which("ffprobe")
    if ffprobe:
        ligne(OK, "ffprobe", "présent")
    else:
        ligne(CONSEIL, "ffprobe", "absent : ciseau fonctionne, mais sans mesure précise des images-clés")

    # --- yt-dlp (indispensable pour les liens ; pas pour les fichiers locaux) ---
    try:
        import yt_dlp  # type: ignore[import-not-found]

        ligne(OK, "yt-dlp", yt_dlp.version.__version__)
    except ImportError:
        ligne(MANQUE, "yt-dlp", "non installé (make install)")
        manques.append("yt-dlp")

    # --- Runtime JavaScript : yt-dlp en a besoin pour résoudre YouTube (déconseillé de s'en passer) ---
    runtime = next((n for n in ("deno", "node", "bun") if shutil.which(n)), None)
    if runtime:
        ligne(OK, runtime, "runtime JavaScript pour YouTube")
    else:
        ligne(CONSEIL, "deno", "absent : certaines vidéos YouTube échoueront (make install-systeme)")

    # --- ciseau lui-même (installé en mode éditable) ---
    try:
        import ciseau  # type: ignore[import-not-found]

        ligne(OK, "ciseau", ciseau.__version__)
    except ImportError:
        ligne(CONSEIL, "ciseau", "non installé comme paquet (make install) ; python -m ciseau marche quand même")

    print()
    if manques:
        print(f"Il manque : {', '.join(manques)}.")
        return 1
    print("Tout est prêt. Lance l'interface avec : make ui")
    return 0


# ---------------------------------------------------------------------------
# aide
# ---------------------------------------------------------------------------

def aide(makefile: str) -> int:
    """Affiche les cibles du Makefile qui ont un commentaire `## description`."""
    motif = re.compile(r"^([a-zA-Z0-9_-]+):.*?## (.*)$")
    cibles = []
    for ligne in Path(makefile).read_text(encoding="utf-8").splitlines():
        m = motif.match(ligne)
        if m:
            cibles.append(m.groups())
    print("Usage : make <cible>\n")
    largeur = max(len(c) for c, _ in cibles)
    for cible, description in cibles:
        print(f"  {cible:<{largeur}}  {description}")
    return 0


# ---------------------------------------------------------------------------
# nettoyer
# ---------------------------------------------------------------------------

def nettoyer() -> int:
    """Supprime les caches Python et de test. Ne touche JAMAIS au dossier `extraits`."""
    supprimes = 0
    for dossier in [*RACINE.rglob("__pycache__"), *RACINE.rglob("*.egg-info"),
                    RACINE / ".pytest_cache", RACINE / "build", RACINE / "dist"]:
        # On ignore tout ce qui est dans .git ou un environnement virtuel.
        if dossier.exists() and not {".git", ".venv", "venv"} & set(dossier.parts):
            shutil.rmtree(dossier, ignore_errors=True)
            supprimes += 1
    print(f"{supprimes} dossier(s) de cache supprimé(s). Le dossier des extraits est intact.")
    return 0


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    commande = sys.argv[1] if len(sys.argv) > 1 else ""
    if commande == "verifier":
        sys.exit(verifier())
    if commande == "aide" and len(sys.argv) > 2:
        sys.exit(aide(sys.argv[2]))
    if commande == "nettoyer":
        sys.exit(nettoyer())
    print(__doc__)
    sys.exit(2)
