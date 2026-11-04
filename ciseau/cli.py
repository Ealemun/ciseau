"""Ligne de commande `ciseau`.

Exemples :

    ciseau clip "https://www.youtube.com/watch?v=XXXX" 1:23:04 1:25:30
    ciseau clip "https://youtu.be/XXXX?t=90" - 2:00          # début pris dans l'URL
    ciseau clip video.mp4 0:10 0:25 --rapide
    ciseau clip "https://…" 10:00 12:00 --audio -o refrain.m4a
    ciseau info "https://www.youtube.com/watch?v=XXXX"

Bibliothèque standard uniquement (argparse) pour une installation sans friction.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, ffmpeg, pipeline, resolver
from .options import Options
from .timecode import TimecodeError, format_hms


def _construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ciseau",
        description="Télécharge ou découpe un extrait précis d'une vidéo entre deux timecodes.",
    )
    p.add_argument("--version", action="version", version=f"ciseau {__version__}")
    sous = p.add_subparsers(dest="commande", required=True)

    # --- ciseau clip ------------------------------------------------------
    c = sous.add_parser("clip", help="télécharger / découper un extrait")
    c.add_argument("source", help="URL (YouTube, Twitch, …) ou fichier vidéo local")
    c.add_argument("debut", nargs="?", default=None,
                   help="timecode de début (1:23:04, 83, 1h23m) ; '-' = début de l'URL (?t=) ou 0")
    c.add_argument("fin", nargs="?", default=None,
                   help="timecode de fin ; absent ou '-' = jusqu'à la fin")
    mode = c.add_mutually_exclusive_group()
    mode.add_argument("--precis", action="store_true", default=True,
                      help="coupe à l'image près, réencodage (défaut)")
    mode.add_argument("--rapide", action="store_true",
                      help="copie sans réencodage : instantané, démarre sur l'image-clé précédente")
    mode.add_argument("--audio", action="store_true", help="bande-son seule (.m4a)")
    c.add_argument("-o", "--sortie", type=Path, help="fichier de sortie (sinon nom automatique)")
    c.add_argument("-d", "--dossier", type=Path, default=Path("extraits"),
                   help="dossier des extraits (défaut : ./extraits)")
    c.add_argument("--hauteur", type=int, metavar="PX", help="hauteur max de la vidéo (ex. 1080)")
    c.add_argument("--encodeur", default=ffmpeg.ENCODEUR_DEFAUT, choices=sorted(ffmpeg.ENCODEURS),
                   help="encodeur du mode précis (défaut : libx264 ; h264_nvenc = carte NVIDIA)")
    c.add_argument("--cookies-navigateur", metavar="NAV",
                   help="lire les cookies d'un navigateur (chrome, firefox, edge, 'chrome:Profil 1')")
    c.add_argument("--cookies", type=Path, metavar="FICHIER", help="fichier cookies.txt")
    c.add_argument("-v", "--verbeux", action="store_true", help="journaux détaillés")

    # --- ciseau info ------------------------------------------------------
    i = sous.add_parser("info", help="afficher titre, durée et chapitres d'une source")
    i.add_argument("source")
    i.add_argument("--cookies-navigateur", metavar="NAV")
    i.add_argument("--cookies", type=Path, metavar="FICHIER")
    i.add_argument("-v", "--verbeux", action="store_true")
    return p


def _options_depuis_args(args: argparse.Namespace) -> Options:
    """Traduit les arguments argparse en Options du pipeline."""
    mode = "audio" if getattr(args, "audio", False) else "rapide" if getattr(args, "rapide", False) else "precis"
    return Options(
        mode=mode,
        encodeur=getattr(args, "encodeur", ffmpeg.ENCODEUR_DEFAUT),
        dossier_sortie=getattr(args, "dossier", Path("extraits")),
        fichier_sortie=getattr(args, "sortie", None),
        hauteur_max=getattr(args, "hauteur", None),
        cookies_navigateur=args.cookies_navigateur,
        cookies_fichier=args.cookies,
        verbeux=args.verbeux,
    )


class _Barre:
    """Barre de progression minimaliste sur une seule ligne du terminal."""

    def __init__(self) -> None:
        self._derniere = -1

    def __call__(self, fraction: float) -> None:
        pct = int(fraction * 100)
        if pct == self._derniere:
            return
        self._derniere = pct
        rempli = int(fraction * 30)
        sys.stderr.write(f"\r  [{'#' * rempli}{'.' * (30 - rempli)}] {pct:3d} %")
        sys.stderr.flush()
        if pct >= 100:
            sys.stderr.write("\n")


def _cmd_clip(args: argparse.Namespace) -> int:
    options = _options_depuis_args(args)
    debut = None if args.debut in (None, "-") else args.debut
    fin = None if args.fin in (None, "-") else args.fin

    def dire(texte: str) -> None:
        print(f"• {texte}", file=sys.stderr)

    resultat = pipeline.extraire(args.source, debut, fin, options,
                                 sur_message=dire, sur_progression=_Barre())

    print(f"✔ {resultat.fichier}")
    print(f"  {resultat.info.titre} — {format_hms(resultat.debut)} → {format_hms(resultat.fin)} "
          f"({format_hms(resultat.fin - resultat.debut)}), mode {resultat.mode}")
    if resultat.decalage_debut:
        print(f"  (mode rapide : l'extrait commence {resultat.decalage_debut:.1f} s avant le point demandé)")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    info = resolver.resoudre(args.source, _options_depuis_args(args))
    print(f"Titre   : {info.titre}")
    print(f"Site    : {info.site}")
    print(f"Durée   : {format_hms(info.duree) if info.duree is not None else 'inconnue (direct ?)'}")
    if info.hauteur_max:
        print(f"Qualité : jusqu'à {info.hauteur_max}p")
    if info.chapitres:
        print("Chapitres :")
        for ch in info.chapitres:
            print(f"  {format_hms(ch.debut):>9} → {format_hms(ch.fin):<9} {ch.titre}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _construire_parseur().parse_args(argv)
    try:
        return _cmd_clip(args) if args.commande == "clip" else _cmd_info(args)
    except (TimecodeError, FileNotFoundError, ffmpeg.FFmpegIntrouvable, RuntimeError) as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n✘ interrompu", file=sys.stderr)
        return 130


if __name__ == "__main__":  # python -m ciseau.cli …
    sys.exit(main())
