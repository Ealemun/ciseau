"""Lecture et écriture des timecodes.

Formats acceptés en entrée (tous convertis en secondes, nombre flottant) :

    "83"            -> 83 s
    "83.5"          -> 83,5 s
    "1:23"          -> 1 min 23 s
    "1:23:04"       -> 1 h 23 min 4 s
    "1:23:04.250"   -> idem avec millisecondes
    "1h23m4s"       -> 1 h 23 min 4 s   (style YouTube, paramètre ?t=)
    "2m30"          -> 2 min 30 s
    "90s"           -> 90 s

Les virgules sont acceptées comme séparateur décimal ("83,5").
"""

from __future__ import annotations

import re

# Expression pour le style "1h23m4s" : chaque unité est optionnelle, mais il en faut au moins une.
_RE_UNITES = re.compile(
    r"^(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?(?:(?P<s>\d+(?:\.\d+)?)s?)?$"
)


class TimecodeError(ValueError):
    """Levée quand un timecode est illisible ou incohérent."""


def parse(texte: str | float | int) -> float:
    """Convertit un timecode en secondes.

    Accepte déjà un nombre (renvoyé tel quel) pour simplifier les appels internes.
    """
    # Cas trivial : on nous passe déjà un nombre.
    if isinstance(texte, (int, float)):
        return float(texte)

    brut = texte.strip().lower().replace(",", ".")
    if not brut:
        raise TimecodeError("timecode vide")

    # Style "hh:mm:ss.mmm" : on découpe sur ":" et on lit de droite à gauche.
    if ":" in brut:
        morceaux = brut.split(":")
        if len(morceaux) > 3:
            raise TimecodeError(f"timecode illisible : {texte!r}")
        try:
            valeurs = [float(p) for p in morceaux]
        except ValueError as exc:
            raise TimecodeError(f"timecode illisible : {texte!r}") from exc
        secondes = 0.0
        for v in valeurs:  # 1:23:04 -> ((1*60)+23)*60+4
            secondes = secondes * 60 + v
        return secondes

    # Style "1h23m4s" / "2m30" / "90s" (et aussi "83" tout nu, capté par le groupe s).
    m = _RE_UNITES.match(brut)
    if not m or not any(m.group(g) for g in ("h", "m", "s")):
        raise TimecodeError(f"timecode illisible : {texte!r}")
    h = int(m.group("h") or 0)
    mn = int(m.group("m") or 0)
    s = float(m.group("s") or 0)
    return h * 3600 + mn * 60 + s


def format_hms(secondes: float, millisecondes: bool = False) -> str:
    """Formate des secondes en "h:mm:ss" (ou "m:ss" sous l'heure).

    Avec millisecondes=True, ajoute ".mmm" — utile pour les logs de découpe précise.
    """
    if secondes < 0:
        raise TimecodeError("un timecode ne peut pas être négatif")
    total_ms = round(secondes * 1000)
    h, reste = divmod(total_ms, 3_600_000)
    mn, reste = divmod(reste, 60_000)
    s, ms = divmod(reste, 1000)
    base = f"{h}:{mn:02d}:{s:02d}" if h else f"{mn}:{s:02d}"
    return f"{base}.{ms:03d}" if millisecondes else base


def format_fichier(secondes: float) -> str:
    """Variante sans ":" pour les noms de fichiers : 1:23:04 -> "1h23m04s"."""
    total = int(round(secondes))
    h, reste = divmod(total, 3600)
    mn, s = divmod(reste, 60)
    return f"{h}h{mn:02d}m{s:02d}s" if h else f"{mn}m{s:02d}s"


def valider_plage(debut: float, fin: float | None, duree: float | None = None) -> None:
    """Vérifie qu'une plage [debut, fin] est cohérente, sinon lève TimecodeError.

    `fin` peut être None (= jusqu'à la fin de la vidéo). `duree`, si connue,
    permet de refuser un début au-delà de la vidéo.
    """
    if debut < 0:
        raise TimecodeError("le début ne peut pas être négatif")
    if fin is not None and fin <= debut:
        raise TimecodeError(
            f"la fin ({format_hms(fin)}) doit être après le début ({format_hms(debut)})"
        )
    if duree is not None and debut >= duree:
        raise TimecodeError(
            f"le début ({format_hms(debut)}) dépasse la durée de la vidéo ({format_hms(duree)})"
        )
