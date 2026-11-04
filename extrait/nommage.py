"""Noms de fichiers des extraits : lisibles, portables (Windows/macOS/Linux)."""

from __future__ import annotations

import re

from .resolver import MediaInfo
from .timecode import format_fichier

# Caractères interdits dans un nom de fichier sous Windows (le plus strict) + contrôle.
_RE_INTERDITS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RE_ESPACES = re.compile(r"\s+")
LONGUEUR_MAX_TITRE = 80


def nettoyer(titre: str) -> str:
    """Rend un titre utilisable comme nom de fichier."""
    propre = _RE_INTERDITS.sub("", titre)
    propre = _RE_ESPACES.sub(" ", propre).strip(" .")  # Windows refuse un nom finissant par "."
    return propre[:LONGUEUR_MAX_TITRE].rstrip(" .")


def nom_fichier_extrait(info: MediaInfo, debut: float, fin: float | None, extension: str,
                        mode: str = "precis") -> str:
    """"Titre [1m30s-2m05s].mp4" — sans ":" pour rester valide partout.

    Le mode rapide ajoute " (rapide)" pour ne pas écraser un extrait précis de
    la même plage (les deux fichiers n'ont pas le même contenu au début).
    """
    titre = nettoyer(info.titre) or info.identifiant or "extrait"
    fin_txt = format_fichier(fin) if fin is not None else "fin"
    etiquette = " (rapide)" if mode == "rapide" else ""
    return f"{titre} [{format_fichier(debut)}-{fin_txt}]{etiquette}{extension}"
