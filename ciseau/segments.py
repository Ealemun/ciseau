"""Téléchargement rapide d'une plage de temps par segments (flux DASH en MP4).

Pourquoi ce module existe
-------------------------
Quand on demande une plage de temps à yt-dlp, il confie le téléchargement à
ffmpeg, qui lit le flux d'un seul tenant. Or YouTube bride toute connexion qui
ne télécharge pas par morceaux de 10 Mo au plus : la lecture tombe alors à peu
près à la vitesse de la vidéo elle-même (une minute d'extrait = une minute
d'attente, voire plus). yt-dlp le sait pour les vidéos entières (il découpe en
morceaux de 10 Mo), mais pas dans ce cas.

Ce que fait ce module
---------------------
Les vidéos YouTube (et beaucoup d'autres sites) sont servies en « DASH » : un
fichier MP4 par flux (vidéo seule, audio seul), organisé ainsi :

    ftyp | moov | sidx | moof mdat | moof mdat | moof mdat | …
    └─ en-tête ─┘ index   └────── segments de quelques secondes ──────┘

L'index `sidx` donne, pour chaque segment, sa durée et sa taille en octets.
On peut donc calculer exactement quels octets couvrent [début, fin], puis :

1. lire l'en-tête et l'index (quelques dizaines de Ko) ;
2. télécharger uniquement les segments utiles, par morceaux de 10 Mo au plus,
   sur plusieurs connexions en parallèle ;
3. les recoller derrière l'en-tête : on obtient un petit MP4 valide, que
   ffmpeg découpe ensuite en local, à l'image près, en une fraction de seconde.

Si quelque chose ne colle pas (pas d'index, format WebM, refus du serveur…),
on lève SegmentsIndisponibles et l'appelant se rabat sur yt-dlp.
"""

from __future__ import annotations

import struct
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

# Taille maximale d'une requête : au-delà, YouTube bride la connexion.
TAILLE_MORCEAU = 10 * 1024 * 1024

# Combien d'octets lire au départ pour trouver en-tête + index. Un index de
# YouTube pèse ~12 octets par segment : 64 Ko couvrent déjà plus d'une heure de
# vidéo. Si ça ne suffit pas, on relit seulement la suite de l'index.
LECTURE_INITIALE = 64 * 1024

CONNEXIONS_DEFAUT = 4
ESSAIS = 3  # tentatives par morceau avant d'abandonner


class SegmentsIndisponibles(Exception):
    """Le téléchargement par segments ne s'applique pas : se rabattre sur yt-dlp."""


# ---------------------------------------------------------------------------
# Lecture HTTP par plages d'octets
# ---------------------------------------------------------------------------

def lire_octets(url: str, entetes: dict, debut: int, fin: int) -> bytes:
    """Renvoie les octets [debut, fin] (bornes incluses) de `url`.

    Réessaie quelques fois en cas d'erreur réseau passagère. Un refus (403, 404…)
    lève SegmentsIndisponibles : l'URL n'est pas utilisable ainsi.
    """
    requete = urllib.request.Request(url, headers={**entetes, "Range": f"bytes={debut}-{fin}"})
    derniere_erreur: Exception | None = None
    for essai in range(ESSAIS):
        try:
            with urllib.request.urlopen(requete, timeout=30) as reponse:
                donnees = reponse.read()
                # 200 au lieu de 206 : le serveur ignore les plages et renvoie tout.
                if reponse.status == 200 and len(donnees) > fin - debut + 1:
                    donnees = donnees[debut:fin + 1]
                return donnees
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404, 410, 416):
                raise SegmentsIndisponibles(f"le serveur refuse la lecture partielle (HTTP {exc.code})") from exc
            derniere_erreur = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            derniere_erreur = exc
        time.sleep(0.5 * (essai + 1))  # petite attente croissante avant de réessayer
    raise SegmentsIndisponibles(f"échec réseau répété : {derniere_erreur}")


# ---------------------------------------------------------------------------
# Lecture de l'index MP4 (boîtes ftyp / moov / sidx)
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    debut: float   # secondes
    fin: float     # secondes
    octet_a: int   # premier octet (inclus)
    octet_b: int   # dernier octet (inclus)


@dataclass
class Index:
    fin_entete: int            # les octets [0, fin_entete) forment l'en-tête (ftyp + moov)
    segments: list[Segment]


def _boites(donnees: bytes, depart: int = 0):
    """Parcourt les boîtes MP4 de premier niveau : renvoie (type, position, taille).

    S'arrête à la première boîte qui déborde des données lues.
    """
    i = depart
    while i + 8 <= len(donnees):
        taille, type_ = struct.unpack(">I4s", donnees[i:i + 8])
        entete = 8
        if taille == 1:  # taille sur 64 bits juste après le type
            if i + 16 > len(donnees):
                return
            taille = struct.unpack(">Q", donnees[i + 8:i + 16])[0]
            entete = 16
        if taille < entete:
            return  # boîte corrompue ou « jusqu'à la fin du fichier » : on arrête
        yield type_.decode("latin-1"), i, taille
        i += taille


def _lire_sidx(donnees: bytes, position: int, taille: int) -> list[Segment]:
    """Décode une boîte sidx (ISO/IEC 14496-12, § 8.16.3) en liste de segments."""
    p = position + 8
    version = donnees[p]
    p += 4  # version (1 octet) + drapeaux (3 octets)
    p += 4  # reference_ID
    echelle = struct.unpack(">I", donnees[p:p + 4])[0]
    p += 4
    if version == 0:
        t0, decalage = struct.unpack(">II", donnees[p:p + 8])
        p += 8
    else:
        t0, decalage = struct.unpack(">QQ", donnees[p:p + 16])
        p += 16
    p += 2  # réservé
    nombre = struct.unpack(">H", donnees[p:p + 2])[0]
    p += 2

    # Les tailles des segments sont comptées à partir de la fin de la boîte sidx.
    octet = position + taille + decalage
    temps = t0
    segments = []
    for _ in range(nombre):
        ref, duree, _sap = struct.unpack(">III", donnees[p:p + 12])
        p += 12
        if ref >> 31:  # renvoi vers un autre sidx (index hiérarchique) : non géré
            raise SegmentsIndisponibles("index sidx hiérarchique non géré")
        longueur = ref & 0x7FFFFFFF
        segments.append(Segment(temps / echelle, (temps + duree) / echelle, octet, octet + longueur - 1))
        octet += longueur
        temps += duree
    if not segments:
        raise SegmentsIndisponibles("index sidx vide")
    return segments


def lire_index(url: str, entetes: dict) -> tuple[Index, bytes]:
    """Lit l'en-tête et l'index du fichier distant. Renvoie (index, octets de l'en-tête)."""
    donnees = lire_octets(url, entetes, 0, LECTURE_INITIALE - 1)
    fin_moov = None
    for type_, position, taille in _boites(donnees):
        if type_ == "moov":
            fin_moov = position + taille
        elif type_ == "sidx":
            if fin_moov is None:
                raise SegmentsIndisponibles("sidx avant moov : structure inattendue")
            # Index plus grand que ce qu'on a lu : on récupère la suite.
            if position + taille > len(donnees):
                donnees += lire_octets(url, entetes, len(donnees), position + taille - 1)
            return Index(fin_moov, _lire_sidx(donnees, position, taille)), donnees[:fin_moov]
        elif type_ in ("moof", "mdat"):
            break  # les données commencent sans index : impossible de viser
    raise SegmentsIndisponibles("pas d'index sidx en tête de fichier (format non DASH)")


# ---------------------------------------------------------------------------
# Téléchargement d'une plage
# ---------------------------------------------------------------------------

@dataclass
class Plage:
    chemin: Path       # petit MP4 local : en-tête + segments utiles
    origine: float     # instant (dans la vidéo d'origine) où commence ce fichier
    octets: int        # octets réellement téléchargés


def telecharger_plage(
    url: str,
    entetes: dict,
    debut: float,
    fin: float,
    destination: Path,
    connexions: int = CONNEXIONS_DEFAUT,
    sur_octets: Callable[[int], None] | None = None,
    arret: threading.Event | None = None,
) -> Plage:
    """Écrit dans `destination` un MP4 couvrant au moins [debut, fin] du flux distant.

    `sur_octets(n)` est appelé à chaque morceau reçu (n = octets du morceau),
    pour afficher une progression. `arret`, s'il est levé, interrompt proprement.
    """
    index, entete = lire_index(url, entetes)

    # Segments qui recouvrent la plage demandée. Une vidéo ne peut démarrer que
    # sur une image-clé, et chaque segment commence justement par une image-clé :
    # le premier segment retenu est celui qui contient `debut`.
    utiles = [s for s in index.segments if s.fin > debut and s.debut < fin]
    if not utiles:
        raise SegmentsIndisponibles("la plage demandée est hors de la vidéo")
    a, b = utiles[0].octet_a, utiles[-1].octet_b

    # Découpe en morceaux de 10 Mo au plus, téléchargés en parallèle.
    morceaux = [(x, min(x + TAILLE_MORCEAU - 1, b)) for x in range(a, b + 1, TAILLE_MORCEAU)]

    def recuperer(morceau: tuple[int, int]) -> bytes:
        if arret is not None and arret.is_set():
            raise SegmentsIndisponibles("interrompu")
        donnees = lire_octets(url, entetes, *morceau)
        if len(donnees) != morceau[1] - morceau[0] + 1:
            raise SegmentsIndisponibles("réponse tronquée par le serveur")
        if sur_octets:
            sur_octets(len(donnees))
        return donnees

    destination.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, connexions)) as pool, destination.open("wb") as f:
        # L'en-tête (sans l'index, dont les positions ne seraient plus justes)…
        f.write(entete)
        # …puis les segments, dans l'ordre : pool.map rend les résultats dans
        # l'ordre des morceaux, même s'ils arrivent dans le désordre.
        for donnees in pool.map(recuperer, morceaux):
            f.write(donnees)

    return Plage(destination, utiles[0].debut, len(entete) + (b - a + 1))


# ---------------------------------------------------------------------------
# Choix des formats dans les métadonnées yt-dlp
# ---------------------------------------------------------------------------

def _est_mp4_http(f: dict) -> bool:
    """Format en MP4 servi en HTTP simple, avec une URL utilisable telle quelle."""
    return (
        bool(f.get("url"))
        and f.get("protocol") in ("https", "http")
        and f.get("ext") in ("mp4", "m4a")
        and not f.get("has_drm")
        and not f.get("fragments")
        # yt-dlp marque ainsi les flux YouTube tronqués (préférence -10, note "DAMAGED").
        and f.get("preference") != -10
        and "DAMAGED" not in str(f.get("format_note") or "")
    )


def _cle_audio(f: dict) -> tuple:
    """Ordre de préférence des pistes audio : piste par défaut, sans DRC, meilleur débit."""
    return (
        f.get("language_preference") or 0,              # piste d'origine plutôt qu'un doublage
        "drc" not in str(f.get("format_id") or ""),     # DRC = dynamique compressée
        f.get("abr") or f.get("tbr") or 0,
    )


def attente_avant_lecture(*formats: dict | None) -> float:
    """Secondes à attendre avant que YouTube serve ces flux (champ available_at de yt-dlp).

    YouTube impose parfois un court délai entre l'obtention des adresses et le
    téléchargement ; yt-dlp le respecte, nous aussi.
    """
    instants = [f.get("available_at") or 0 for f in formats if f]
    return max(0.0, max(instants, default=0) - time.time())


def choisir_formats(info: dict, mode: str, hauteur_max: int | None) -> tuple[dict | None, dict]:
    """Choisit (flux vidéo, flux audio) parmi les formats DASH MP4 de `info`.

    - vidéo : H.264 (avc1), la plus haute définition ≤ hauteur_max, puis le meilleur débit ;
      None en mode audio ;
    - audio : AAC (m4a), le meilleur débit.
    Lève SegmentsIndisponibles si l'un des deux manque (vidéo protégée, flux
    combiné seulement, WebM seulement…).
    """
    formats = info.get("formats") or []
    audios = [f for f in formats if _est_mp4_http(f) and f.get("vcodec") == "none"
              and str(f.get("acodec", "")).startswith("mp4a")]
    if not audios:
        raise SegmentsIndisponibles("aucun flux audio AAC séparé")
    audio = max(audios, key=_cle_audio)

    if mode == "audio":
        return None, audio

    videos = [f for f in formats if _est_mp4_http(f) and f.get("acodec") == "none"
              and str(f.get("vcodec", "")).startswith("avc1") and f.get("height")
              and (hauteur_max is None or f["height"] <= hauteur_max)]
    if not videos:
        raise SegmentsIndisponibles("aucun flux vidéo H.264 séparé")
    video = max(videos, key=lambda f: (f["height"], f.get("fps") or 0, f.get("tbr") or 0))
    return video, audio


def entetes_de(f: dict) -> dict:
    """En-têtes HTTP que yt-dlp associe au format (User-Agent, Referer…)."""
    return {k: v for k, v in (f.get("http_headers") or {}).items() if isinstance(v, str)}
