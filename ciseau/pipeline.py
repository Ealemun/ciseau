"""Orchestration : une source (URL ou fichier) + une plage -> un fichier extrait.

C'est la fonction qu'appellera tout client (CLI aujourd'hui, API web et
extension navigateur demain) : `extraire(source, debut, fin, options)`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import cutter, downloader, resolver
from .cutter import EXTENSION_PAR_MODE
from .nommage import nom_fichier_extrait
from .options import Options
from .timecode import TimecodeError, parse as parse_timecode, valider_plage

Message = Callable[[str], None]


@dataclass
class Resultat:
    fichier: Path          # fichier produit
    info: resolver.MediaInfo
    debut: float
    fin: float
    mode: str
    decalage_debut: float | None = None  # mode rapide : rab avant le début (s), si connu


def extraire(
    source: str,
    debut: str | float | None,
    fin: str | float | None,
    options: Options | None = None,
    sur_message: Message | None = None,
    sur_progression: Callable[[float], None] | None = None,
) -> Resultat:
    """Produit l'extrait [debut, fin] de `source`.

    - `debut` None : on tente le `?t=` de l'URL, sinon 0.
    - `fin` None   : jusqu'à la fin de la vidéo.
    Les timecodes sont acceptés sous forme de texte ("1:23:04") ou de secondes.
    """
    options = options or Options()
    dire = sur_message or (lambda _texte: None)

    dire("analyse de la source…")
    info = resolver.resoudre(source, options)

    # Début implicite depuis l'URL (lien YouTube copié "à cet instant").
    if debut is None:
        debut_s = (resolver.instant_depuis_url(source) if info.est_fichier is False else None) or 0.0
    else:
        debut_s = parse_timecode(debut)
    fin_s = parse_timecode(fin) if fin is not None else None
    valider_plage(debut_s, fin_s, info.duree)
    if fin_s is None:
        if info.duree is None:
            raise TimecodeError("durée inconnue : indique un timecode de fin")
        fin_s = info.duree

    if info.est_fichier:
        # Fichier local : découpe directe.
        destination = options.fichier_sortie or (
            Path(options.dossier_sortie)
            / nom_fichier_extrait(info, debut_s, fin_s, EXTENSION_PAR_MODE[options.mode], options.mode)
        )
        dire(f"découpe ({options.mode})…")
        fichier = cutter.decouper(
            info.source, debut_s, fin_s, destination,
            mode=options.mode, encodeur=options.encodeur, sur_progression=sur_progression,
        )
        decalage = cutter.decalage_image_cle(info.source, debut_s) if options.mode == "rapide" else None
    else:
        fichier = downloader.telecharger_extrait(info, debut_s, fin_s, options, sur_message=dire)
        decalage = None  # inconnu sans analyser le flux distant

    return Resultat(fichier=fichier, info=info, debut=debut_s, fin=fin_s, mode=options.mode,
                    decalage_debut=decalage)
