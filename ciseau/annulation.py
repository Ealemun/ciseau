"""Annulation d'un extrait en cours.

Un extrait passe par plusieurs étapes longues (téléchargement par morceaux,
ffmpeg, parfois yt-dlp). Pour pouvoir l'arrêter à tout moment, on transmet à
chacune un « signal d'arrêt » : un threading.Event. Quand il est levé :

- le téléchargement par segments s'arrête avant le morceau suivant (≤ 10 Mo) ;
- ffmpeg est tué dans la demi-seconde ;
- yt-dlp est interrompu à sa prochaine remontée de progression.

L'étape qui s'arrête lève `Annulation`, que les couches au-dessus laissent
remonter telle quelle (en particulier : une annulation ne déclenche PAS le
repli sur yt-dlp, contrairement à un échec de la méthode rapide).
"""

from __future__ import annotations

import threading

Arret = threading.Event


class Annulation(Exception):
    """L'utilisateur a annulé l'extrait."""

    def __init__(self, message: str = "annulé") -> None:
        super().__init__(message)


def verifier(arret: Arret | None) -> None:
    """Lève Annulation si le signal d'arrêt est levé (à appeler entre deux étapes)."""
    if arret is not None and arret.is_set():
        raise Annulation()
