"""Garde-fous au démarrage de ciseau."""

import os
import subprocess
import sys


def test_plugins_ytdlp_desactives():
    """Importer ciseau coupe la recherche de plugins de yt-dlp.

    Sans ça, un dossier injoignable dans sys.path (chemin WSL resté dans
    PYTHONPATH, lecteur réseau déconnecté…) fait échouer toute analyse.
    """
    env = {k: v for k, v in os.environ.items() if k != "YTDLP_NO_PLUGINS"}
    sortie = subprocess.run(
        [sys.executable, "-c", "import os, ciseau; print(os.environ.get('YTDLP_NO_PLUGINS'))"],
        capture_output=True, text=True, env=env, check=True,
    )
    assert sortie.stdout.strip() == "1"
