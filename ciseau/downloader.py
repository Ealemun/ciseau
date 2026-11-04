"""Téléchargement d'un seul extrait d'une URL, via yt-dlp.

Au lieu de récupérer la vidéo entière puis de la couper, on demande à yt-dlp
de ne télécharger que la plage [debut, fin] : il délègue alors à ffmpeg, qui
lit le flux à distance en commençant directement à la bonne position (requêtes
HTTP partielles). Sur une vidéo de trois heures, extraire trente secondes ne
coûte que quelques mégaoctets.

Les mêmes deux philosophies que cutter.py s'appliquent :
- "rapide" : copie de flux, démarre sur l'image-clé précédant `debut`.
- "precis" : yt-dlp active `force_keyframes_at_cuts`, c'est-à-dire un
             réencodage par ffmpeg avec coupe à l'image près ; on lui passe
             les mêmes options d'encodage que la découpe locale.
- "audio"  : bande-son seule, convertie en m4a.
"""

from __future__ import annotations

from pathlib import Path

from . import ffmpeg
from .cutter import EXTENSION_PAR_MODE
from .options import Options
from .nommage import nom_fichier_extrait
from .resolver import MediaInfo, _options_ytdlp


def _selecteur_format(options: Options) -> str:
    """Chaîne de sélection de format yt-dlp selon le mode et la hauteur max."""
    if options.mode == "audio":
        return "bestaudio/best"
    h = f"[height<={options.hauteur_max}]" if options.hauteur_max else ""
    # En mode rapide on copie les flux : on préfère H.264 (avc1) + AAC (m4a) pour
    # rester dans un .mp4 lisible partout. En mode précis on réencode de toute
    # façon, mais garder la même préférence évite les surprises (VP9/AV1 lents à décoder).
    return (
        f"bestvideo{h}[vcodec^=avc1]+bestaudio[ext=m4a]"
        f"/bestvideo{h}[ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo{h}+bestaudio"
        f"/best{h}/best"
    )


def telecharger_extrait(
    info: MediaInfo,
    debut: float,
    fin: float | None,
    options: Options,
    sur_message: "callable | None" = None,
) -> Path:
    """Télécharge l'extrait [debut, fin] de `info.source` et renvoie le fichier écrit.

    `sur_message(texte)` reçoit des étapes lisibles ("téléchargement…", "fusion…").
    """
    import yt_dlp  # type: ignore[import-not-found]
    from yt_dlp.utils import download_range_func  # type: ignore[import-not-found]

    if info.est_direct:
        raise RuntimeError("c'est un direct en cours : impossible de découper par timecode")
    # Une fin absente = jusqu'au bout ; on la rend explicite pour que ffmpeg
    # reçoive une durée finie (yt-dlp ne gère pas une borne infinie partout).
    if fin is None:
        if info.duree is None:
            raise RuntimeError("durée inconnue : indique un timecode de fin")
        fin = info.duree

    extension = EXTENSION_PAR_MODE[options.mode]
    if options.fichier_sortie:
        destination = Path(options.fichier_sortie)
    else:
        destination = Path(options.dossier_sortie) / nom_fichier_extrait(info, debut, fin, extension, options.mode)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        # ffmpeg (utilisé pour les plages) ne remonte pas de pourcentage à yt-dlp :
        # on se contente des changements d'état.
        if sur_message and d.get("status") == "finished":
            sur_message("téléchargement terminé, finalisation…")

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

    if sur_message:
        sur_message("téléchargement de l'extrait…")

    with yt_dlp.YoutubeDL(params) as ydl:
        resultat = ydl.extract_info(info.source, download=True)

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
