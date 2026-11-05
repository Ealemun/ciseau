"""ciseau — télécharge un extrait précis d'une vidéo entre deux timecodes.

Le paquet est organisé en couches indépendantes :

- timecode.py   : lecture/écriture des timecodes ("1:23:04", "83", "1h23m").
- ffmpeg.py     : localisation et pilotage de ffmpeg/ffprobe.
- cutter.py     : découpe d'un fichier vidéo local (mode rapide ou précis).
- resolver.py   : métadonnées d'une URL via yt-dlp (titre, durée, chapitres...).
- downloader.py : téléchargement d'un seul extrait d'une URL via yt-dlp.
- pipeline.py   : orchestration : source (URL ou fichier) -> fichier extrait.
- cli.py        : ligne de commande `ciseau`.
"""

import os

__version__ = "0.1.0"

# yt-dlp cherche au démarrage des modules complémentaires (« plugins ») dans
# TOUS les dossiers de sys.path. Si l'un d'eux est devenu injoignable (par
# exemple un chemin \\wsl.localhost\... resté dans PYTHONPATH après la
# suppression de WSL), Windows lève une erreur d'accès que yt-dlp n'attrape
# pas, et toute analyse échoue. ciseau n'utilise aucun plugin : on désactive
# cette recherche, avant que yt-dlp ne soit importé.
os.environ.setdefault("YTDLP_NO_PLUGINS", "1")
