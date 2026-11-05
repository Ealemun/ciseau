"""Orchestration : une source (URL ou fichier) + une plage -> un fichier extrait.

C'est la fonction qu'appellera tout client (CLI aujourd'hui, API web et
extension navigateur demain) : `extraire(source, debut, fin, options)`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import cutter, downloader, resolver
from .annulation import Arret, verifier
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
    # Comment ça s'est passé, pour comprendre une lenteur :
    #   methode        "segments" (rapide), "yt-dlp" (repli, plus lent) ou "ffmpeg" (fichier/lien direct)
    #   analyse, telechargement, decoupe, total : durées en secondes
    #   octets         octets téléchargés ; repli : pourquoi la méthode rapide a été écartée
    rapport: dict = field(default_factory=dict)


def extraire(
    source: str,
    debut: str | float | None,
    fin: str | float | None,
    options: Options | None = None,
    sur_message: Message | None = None,
    sur_progression: Callable[[float], None] | None = None,
    arret: Arret | None = None,
    sur_info: Callable[[resolver.MediaInfo], None] | None = None,
) -> Resultat:
    """Produit l'extrait [debut, fin] de `source`.

    - `debut` None : on tente le `?t=` de l'URL, sinon 0.
    - `fin` None   : jusqu'à la fin de la vidéo.
    Les timecodes sont acceptés sous forme de texte ("1:23:04") ou de secondes.
    `arret` : signal d'annulation (voir annulation.py) ; lève Annulation s'il est levé.
    `sur_info(info)` : appelé dès que la source est analysée (titre, durée connus).
    """
    options = options or Options()
    dire = sur_message or (lambda _texte: None)
    rapport: dict = {}
    t0 = time.monotonic()

    dire("analyse de la source…")
    info = resolver.resoudre(source, options)
    rapport["analyse"] = time.monotonic() - t0
    if sur_info:
        sur_info(info)
    verifier(arret)  # annulé pendant l'analyse : on s'arrête avant de télécharger

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

    if info.decoupe_directe:
        # Fichier local ou lien direct vers un média : ffmpeg s'en charge seul.
        destination = options.fichier_sortie or (
            Path(options.dossier_sortie)
            / nom_fichier_extrait(info, debut_s, fin_s, EXTENSION_PAR_MODE[options.mode], options.mode)
        )
        dire(f"découpe ({options.mode})…")
        rapport["methode"] = "ffmpeg"
        t1 = time.monotonic()
        fichier = cutter.decouper(
            info.source, debut_s, fin_s, destination,
            mode=options.mode, encodeur=options.encodeur, sur_progression=sur_progression, arret=arret,
        )
        rapport["decoupe"] = time.monotonic() - t1
        # Le rab du mode rapide n'est mesuré que pour un fichier local : sur un
        # lien distant, il faudrait relire le flux jusqu'au début demandé.
        decalage = (cutter.decalage_image_cle(info.source, debut_s)
                    if options.mode == "rapide" and info.est_fichier else None)
    else:
        fichier = downloader.telecharger_extrait(info, debut_s, fin_s, options, sur_message=dire,
                                                 sur_progression=sur_progression, rapport=rapport,
                                                 arret=arret)
        decalage = None  # inconnu sans analyser le flux distant

    rapport["total"] = time.monotonic() - t0
    return Resultat(fichier=fichier, info=info, debut=debut_s, fin=fin_s, mode=options.mode,
                    decalage_debut=decalage, rapport=rapport)


def resumer(rapport: dict) -> str:
    """Résumé d'une ligne du rapport, pour comprendre où le temps est passé.

    Exemple : "segments, 31,3 Mo — analyse 2,1 s · téléchargement 3,4 s · découpe 1,2 s"
    """
    tete = rapport.get("methode", "?")
    if rapport.get("octets"):
        tete += f", {rapport['octets'] / 1e6:.1f} Mo".replace(".", ",")
    etapes = [(nom, rapport[cle]) for cle, nom in
              (("analyse", "analyse"), ("telechargement", "téléchargement"), ("decoupe", "découpe"))
              if rapport.get(cle) is not None]
    texte = tete + " — " + " · ".join(f"{nom} {duree:.1f} s".replace(".", ",") for nom, duree in etapes)
    if rapport.get("repli"):
        texte += f" (méthode rapide écartée : {rapport['repli']})"
    return texte
