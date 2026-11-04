"""Lecture d'une liste d'extraits (« lot ») : une ligne par extrait.

Format, volontairement simple pour être tapé ou collé à la main :

    # Les lignes vides et celles qui commencent par # sont ignorées.
    https://www.youtube.com/watch?v=AAAA  1:23  1:45
    https://youtu.be/BBBB?t=90            -     2:30     <- « - » : début pris dans le lien (?t=)
    https://www.twitch.tv/videos/123      1:02:00          <- sans fin : jusqu'au bout
    D:\\Videos\\match.mp4                 10:00 12:00      <- un fichier local marche aussi

Séparateurs acceptés entre les champs : espaces, tabulations, virgules ou
points-virgules (pratique pour coller une colonne de tableur). Une ligne peut
aussi utiliser « début-fin » d'un bloc : `URL 1:23-1:45`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .resolver import est_url
from .timecode import TimecodeError, parse as parse_timecode


@dataclass
class Ligne:
    numero: int               # numéro de ligne dans le texte (pour les messages d'erreur)
    source: str
    debut: str | None         # None = début du lien (?t=) ou de la vidéo
    fin: str | None           # None = jusqu'à la fin


class ErreurLot(ValueError):
    """Une ou plusieurs lignes illisibles ; le message les liste toutes."""


# Séparateurs : virgule ou point-virgule (entourés d'espaces éventuels), ou espaces/tabulations.
_SEPARATEURS = re.compile(r"\s*[,;]\s*|\s+")
# « 1:23-1:45 » ou « 83-105 » : début et fin collés par un tiret.
_PLAGE_COLLEE = re.compile(r"^([\dhms:.,]+)-([\dhms:.,]+)$", re.IGNORECASE)


def _decouper_source(ligne: str) -> tuple[str, str]:
    """Sépare la source (qui peut contenir des espaces si c'est un chemin entre guillemets) du reste."""
    if ligne.startswith('"'):
        fin = ligne.find('"', 1)
        if fin == -1:
            raise ValueError("guillemet fermant manquant")
        return ligne[1:fin], ligne[fin + 1:]
    morceaux = ligne.split(None, 1)
    if len(morceaux) == 1:
        # Pas d'espace (« URL;0:05;0:09 », copié d'un tableur) : on coupe au premier
        # « , » ou « ; » suivi uniquement de timecodes. Une virgule au milieu d'une
        # URL (suivie d'autre chose) reste donc dans l'URL.
        m = re.match(r"^(.*?)[,;]([\dhms:.,;\-]+)$", ligne, re.IGNORECASE)
        if m:
            return m.group(1), m.group(2)
    return morceaux[0], (morceaux[1] if len(morceaux) > 1 else "")


def lire(texte: str) -> list[Ligne]:
    """Analyse le texte d'un lot. Lève ErreurLot en listant toutes les lignes fautives."""
    lignes: list[Ligne] = []
    erreurs: list[str] = []
    for numero, brute in enumerate(texte.splitlines(), start=1):
        ligne = brute.strip()
        if not ligne or ligne.startswith("#"):
            continue
        try:
            source, reste = _decouper_source(ligne)
            source = source.rstrip(",;")
            champs = [c for c in _SEPARATEURS.split(reste.strip()) if c]
            # « 1:23-1:45 » en un seul champ : on le sépare.
            if len(champs) == 1 and (m := _PLAGE_COLLEE.match(champs[0])):
                champs = [m.group(1), m.group(2)]
            if len(champs) > 2:
                raise ValueError(f"trop de champs après la source ({len(champs)})")
            debut = champs[0] if len(champs) >= 1 and champs[0] != "-" else None
            fin = champs[1] if len(champs) == 2 and champs[1] != "-" else None
            # Vérification immédiate des timecodes : mieux vaut une erreur tout de suite
            # qu'un échec au milieu du lot.
            for t in (debut, fin):
                if t is not None:
                    parse_timecode(t)
            if debut is not None and fin is not None and parse_timecode(fin) <= parse_timecode(debut):
                raise ValueError(f"la fin ({fin}) doit être après le début ({debut})")
            if not est_url(source) and not re.match(r"^([a-zA-Z]:)?[\\/.]|^[\w-]", source):
                raise ValueError(f"source illisible : {source!r}")
            lignes.append(Ligne(numero, source, debut, fin))
        except (ValueError, TimecodeError) as exc:
            erreurs.append(f"ligne {numero} : {exc}")
    if erreurs:
        raise ErreurLot("\n".join(erreurs))
    if not lignes:
        raise ErreurLot("aucun extrait dans la liste")
    return lignes
