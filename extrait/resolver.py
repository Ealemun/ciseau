"""Résolution d'une source : qu'est-ce que c'est, et qu'y a-t-il dedans ?

- `est_url()` distingue une URL d'un fichier local.
- `instant_depuis_url()` lit le `?t=` d'une URL YouTube (début implicite).
- `resoudre()` interroge yt-dlp sans rien télécharger et renvoie un `MediaInfo`
  (titre, durée, chapitres, meilleure hauteur…), ou lit un fichier local.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import ffmpeg
from .options import Options
from .timecode import TimecodeError, parse as parse_timecode


@dataclass
class Chapitre:
    titre: str
    debut: float
    fin: float


@dataclass
class MediaInfo:
    source: str                      # URL ou chemin du fichier
    titre: str
    duree: float | None              # None pour un direct (live) ou si inconnue
    identifiant: str = ""            # id yt-dlp ("dQw4w9WgXcQ"), vide pour un fichier
    site: str = "fichier"            # "youtube", "twitch", … ou "fichier"
    chapitres: list[Chapitre] = field(default_factory=list)
    hauteur_max: int | None = None   # plus grande hauteur vidéo disponible (1080, 2160…)
    est_direct: bool = False         # live en cours : impossible de découper par timecode
    miniature: str | None = None     # URL de la vignette

    @property
    def est_fichier(self) -> bool:
        return self.site == "fichier"


_RE_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def est_url(source: str) -> bool:
    """Vrai si `source` ressemble à une URL (schéma http://, https://…)."""
    return bool(_RE_URL.match(source.strip()))


def instant_depuis_url(url: str) -> float | None:
    """Renvoie le début encodé dans l'URL (`?t=90`, `?t=1m30s`, `&start=90`), sinon None.

    Permet de coller un lien YouTube "copié à cet instant" sans retaper le timecode.
    """
    try:
        params = parse_qs(urlparse(url).query)
    except ValueError:
        return None
    for cle in ("t", "start"):
        if cle in params and params[cle]:
            try:
                return parse_timecode(params[cle][0])
            except TimecodeError:
                continue
    return None


def _options_ytdlp(options: Options) -> dict:
    """Dictionnaire de paramètres yt-dlp commun à la résolution et au téléchargement."""
    params: dict = {
        "quiet": not options.verbeux,
        "no_warnings": not options.verbeux,
        "noprogress": True,
        # Ne jamais dérouler une playlist : une URL = une vidéo.
        "noplaylist": True,
    }
    if options.cookies_navigateur:
        # yt-dlp attend un tuple (navigateur, profil, keyring, conteneur) ; on
        # accepte "chrome" ou "chrome:Profil 1" et on laisse yt-dlp lire le reste.
        navigateur, _, profil = options.cookies_navigateur.partition(":")
        params["cookiesfrombrowser"] = (navigateur, profil or None, None, None)
    if options.cookies_fichier:
        params["cookiefile"] = str(options.cookies_fichier)
    try:
        params["ffmpeg_location"] = ffmpeg.chemin_ffmpeg()
    except ffmpeg.FFmpegIntrouvable:
        pass  # l'erreur sera levée plus proprement au moment de découper
    return params


def resoudre(source: str, options: Options | None = None) -> MediaInfo:
    """Décrit la source sans rien télécharger."""
    options = options or Options()

    # Fichier local : seule la durée nous intéresse vraiment.
    if not est_url(source):
        chemin = Path(source)
        if not chemin.exists():
            raise FileNotFoundError(chemin)
        return MediaInfo(source=str(chemin), titre=chemin.stem, duree=ffmpeg.duree(chemin))

    # Import paresseux : yt-dlp est lourd à charger et inutile pour un fichier local.
    import yt_dlp  # type: ignore[import-not-found]

    with yt_dlp.YoutubeDL(_options_ytdlp(options)) as ydl:
        info = ydl.extract_info(source, download=False)
    if info is None:
        raise RuntimeError(f"yt-dlp n'a rien trouvé pour {source}")
    # Si malgré noplaylist on reçoit une liste, on prend la première entrée.
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]

    chapitres = [
        Chapitre(c.get("title", ""), float(c["start_time"]), float(c["end_time"]))
        for c in info.get("chapters") or []
        if c.get("start_time") is not None and c.get("end_time") is not None
    ]
    hauteurs = [f["height"] for f in info.get("formats") or [] if f.get("height")]

    return MediaInfo(
        source=source,
        titre=info.get("title") or info.get("id") or "video",
        duree=float(info["duration"]) if info.get("duration") else None,
        identifiant=info.get("id") or "",
        site=info.get("extractor_key", "inconnu").lower(),
        chapitres=chapitres,
        hauteur_max=max(hauteurs) if hauteurs else None,
        est_direct=bool(info.get("is_live")),
        miniature=info.get("thumbnail"),
    )
