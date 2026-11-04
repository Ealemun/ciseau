"""Téléchargement d'un seul extrait d'une URL de page vidéo (YouTube, Twitch…).

Deux méthodes, essayées dans cet ordre :

1. Par segments (segments.py) — la rapide. On lit l'index des flux vidéo et
   audio, on ne télécharge que les segments couvrant l'extrait, par morceaux de
   10 Mo sur plusieurs connexions (YouTube ne bride pas ces requêtes), puis on
   découpe en local. Marche pour les vidéos servies en DASH MP4 : la quasi-
   totalité de YouTube jusqu'en 1080p.

2. Par yt-dlp — le repli. yt-dlp confie la plage à ffmpeg, qui lit le flux d'un
   seul tenant : YouTube le bride alors à peu près à la vitesse de lecture. Lent,
   mais compatible avec tous les sites et tous les formats.

Les modes de coupe sont les mêmes que dans cutter.py :
- "rapide" : copie de flux, démarre sur l'image-clé précédant `debut` ;
- "precis" : réencodage, coupe à l'image près ;
- "audio"  : bande-son seule (.m4a).
"""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import cutter, ffmpeg, resolver, segments
from .cutter import EXTENSION_PAR_MODE
from .nommage import nom_fichier_extrait
from .options import Options
from .resolver import MediaInfo, _options_ytdlp

Message = Callable[[str], None]


def _destination(info: MediaInfo, debut: float, fin: float, options: Options) -> Path:
    """Chemin du fichier final : imposé par l'utilisateur, ou nom automatique."""
    if options.fichier_sortie:
        return Path(options.fichier_sortie)
    extension = EXTENSION_PAR_MODE[options.mode]
    return Path(options.dossier_sortie) / nom_fichier_extrait(info, debut, fin, extension, options.mode)


def telecharger_extrait(
    info: MediaInfo,
    debut: float,
    fin: float | None,
    options: Options,
    sur_message: Message | None = None,
    sur_progression: Callable[[float], None] | None = None,
    rapport: dict | None = None,
) -> Path:
    """Télécharge l'extrait [debut, fin] de `info.source` et renvoie le fichier écrit.

    `sur_message(texte)` reçoit des étapes lisibles ; `rapport`, s'il est fourni,
    est rempli avec la méthode employée, les octets reçus et la durée de chaque étape.
    """
    dire = sur_message or (lambda _t: None)
    rapport = rapport if rapport is not None else {}

    if info.est_direct:
        raise RuntimeError("c'est un direct en cours : impossible de découper par timecode")
    # Une fin absente = jusqu'au bout ; on la rend explicite.
    if fin is None:
        if info.duree is None:
            raise RuntimeError("durée inconnue : indique un timecode de fin")
        fin = info.duree

    destination = _destination(info, debut, fin, options)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        return _par_segments(info, debut, fin, destination, options, dire, sur_progression, rapport)
    except segments.SegmentsIndisponibles as exc:
        # Pas grave : on passe par yt-dlp. On garde la raison pour l'afficher.
        rapport["repli"] = str(exc)
        dire(f"méthode rapide impossible ({exc}) : passage par yt-dlp, plus lent…")
    return _par_ytdlp(info, debut, fin, destination, options, dire, rapport)


# ---------------------------------------------------------------------------
# Méthode 1 : par segments
# ---------------------------------------------------------------------------

def _par_segments(
    info: MediaInfo,
    debut: float,
    fin: float,
    destination: Path,
    options: Options,
    dire: Message,
    sur_progression: Callable[[float], None] | None,
    rapport: dict,
) -> Path:
    brut = resolver.infos_brutes(info.source, options)  # en cache depuis l'analyse
    video, audio = segments.choisir_formats(brut, options.mode, options.hauteur_max)
    rapport["methode"] = "segments"
    if video:
        rapport["format"] = f"{video.get('height')}p {video.get('vcodec', '')}".strip()

    # Dossier temporaire à côté de la destination (même disque : pas de copie lente).
    temp = destination.parent / f".ciseau-tmp-{uuid.uuid4().hex[:8]}"
    temp.mkdir(parents=True, exist_ok=True)
    recus = 0
    verrou = threading.Lock()
    dernier_affichage = [0.0]

    def compter(n: int) -> None:
        # Appelé depuis plusieurs connexions à la fois : on protège le compteur.
        nonlocal recus
        with verrou:
            recus += n
            maintenant = time.monotonic()
            if maintenant - dernier_affichage[0] > 0.5:  # pas plus de 2 messages par seconde
                dernier_affichage[0] = maintenant
                dire(f"téléchargement : {recus / 1e6:.1f} Mo")

    try:
        t0 = time.monotonic()
        attente = segments.attente_avant_lecture(video, audio)
        if attente > 0:
            dire(f"YouTube impose une attente de {attente:.0f} s…")
            time.sleep(attente)
        dire("téléchargement des segments…")

        def un_flux(fmt: dict, nom: str) -> segments.Plage:
            return segments.telecharger_plage(
                fmt["url"], segments.entetes_de(fmt), debut, fin, temp / nom,
                connexions=options.connexions, sur_octets=compter,
            )

        try:
            # Vidéo et audio en même temps : deux flux indépendants.
            with ThreadPoolExecutor(max_workers=2) as pool:
                futur_audio = pool.submit(un_flux, audio, "audio.m4a")
                futur_video = pool.submit(un_flux, video, "video.mp4") if video else None
                plage_audio = futur_audio.result()
                plage_video = futur_video.result() if futur_video else None
        except segments.SegmentsIndisponibles:
            # Adresses peut-être expirées : on vide le cache pour que le repli reparte de zéro.
            resolver.oublier(info.source, options)
            raise

        rapport["telechargement"] = time.monotonic() - t0
        rapport["octets"] = recus

        t1 = time.monotonic()
        dire(f"découpe ({options.mode})…")
        cutter.decouper_flux(
            plage_audio.chemin, plage_audio.origine, debut, fin, destination, mode=options.mode,
            video=plage_video.chemin if plage_video else None,
            origine_video=plage_video.origine if plage_video else 0.0,
            encodeur=options.encodeur, sur_progression=sur_progression,
        )
        rapport["decoupe"] = time.monotonic() - t1
        return destination
    finally:
        shutil.rmtree(temp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Méthode 2 : par yt-dlp (repli)
# ---------------------------------------------------------------------------

def _selecteur_format(options: Options) -> str:
    """Chaîne de sélection de format yt-dlp selon le mode et la hauteur max."""
    if options.mode == "audio":
        return "bestaudio/best"
    h = f"[height<={options.hauteur_max}]" if options.hauteur_max else ""
    # On préfère H.264 (avc1) + AAC (m4a) pour rester dans un .mp4 lisible
    # partout (et parce que VP9/AV1 sont lents à décoder pour le réencodage).
    return (
        f"bestvideo{h}[vcodec^=avc1]+bestaudio[ext=m4a]"
        f"/bestvideo{h}[ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo{h}+bestaudio"
        f"/best{h}/best"
    )


def _par_ytdlp(
    info: MediaInfo,
    debut: float,
    fin: float,
    destination: Path,
    options: Options,
    dire: Message,
    rapport: dict,
) -> Path:
    import yt_dlp  # type: ignore[import-not-found]
    from yt_dlp.utils import download_range_func  # type: ignore[import-not-found]

    rapport["methode"] = "yt-dlp"

    def hook(d: dict) -> None:
        # ffmpeg (utilisé pour les plages) ne remonte pas de pourcentage à yt-dlp :
        # on se contente des changements d'état.
        if d.get("status") == "finished":
            dire("téléchargement terminé, finalisation…")

    params = _options_ytdlp(options)
    params.update({
        "format": _selecteur_format(options),
        # yt-dlp remplace %(ext)s par l'extension finale après fusion/conversion.
        "outtmpl": str(destination.with_suffix(".%(ext)s")),
        "merge_output_format": "mp4" if options.mode != "audio" else None,
        # La plage à télécharger : une seule, exprimée en secondes.
        "download_ranges": download_range_func(None, [(debut, fin)]),
        "force_keyframes_at_cuts": options.mode == "precis",
        "progress_hooks": [hook],
        "overwrites": True,
    })
    if options.mode == "precis":
        # Options d'encodage passées à ffmpeg (côté sortie, clé "ffmpeg_o") :
        # exactement les mêmes que pour la découpe locale.
        params["external_downloader_args"] = {"ffmpeg_o": ffmpeg.args_encodage(options.encodeur)}
    elif options.mode == "audio":
        params["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "192"}
        ]

    dire("téléchargement de l'extrait (yt-dlp)…")
    t0 = time.monotonic()
    with yt_dlp.YoutubeDL(params) as ydl:
        resultat = ydl.extract_info(info.source, download=True)
    rapport["telechargement"] = time.monotonic() - t0

    # Chemin réel du fichier final (après fusion/post-traitement) : yt-dlp le
    # renseigne dans requested_downloads ; sinon on reconstruit depuis le gabarit.
    chemin = None
    for dl in (resultat or {}).get("requested_downloads") or []:
        if dl.get("filepath"):
            chemin = Path(dl["filepath"])
            break
    if chemin is None:
        chemin = Path(ydl.prepare_filename(resultat))
    if not chemin.exists():
        raise RuntimeError(f"yt-dlp a terminé mais le fichier {chemin} est introuvable")

    # Si l'extension finale diffère de celle voulue (ex. .mkv faute de fusion mp4),
    # on garde le fichier tel quel mais avec le nom attendu par l'utilisateur.
    if options.fichier_sortie and chemin != destination:
        chemin.replace(destination.with_suffix(chemin.suffix))
        chemin = destination.with_suffix(chemin.suffix)
    return chemin
