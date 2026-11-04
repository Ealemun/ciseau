# ciseau

Télécharge **un extrait précis** de n'importe quelle vidéo (YouTube, Twitch, Twitter, 1 800+ sites via yt-dlp, ou un fichier local) entre un timecode de début et un timecode de fin — sans récupérer la vidéo entière.

```
ciseau clip "https://www.youtube.com/watch?v=XXXX" 1:23:04 1:25:30
```

## Installation

Prérequis : Python 3.10+ et [ffmpeg](https://ffmpeg.org/download.html) dans le PATH.

```
# Windows
winget install Gyan.FFmpeg
# macOS
brew install ffmpeg
# Debian / Ubuntu
sudo apt install ffmpeg
```

Puis :

```
pip install .
# ou, pour développer :
pip install -e .[dev]
```

YouTube change souvent : si un téléchargement échoue, mettez d'abord yt-dlp à jour (`pip install -U yt-dlp`).

## Interface

```
ciseau ui
```

Ouvre l'interface dans le navigateur (http://127.0.0.1:8765). Colle un lien, pose le début et la fin sur la frise, en tapant les timecodes, ou en regardant la vidéo YouTube intégrée avec les touches **I** (début) et **O** (fin). Les extraits apparaissent dans la liste avec leur progression ; un bouton ouvre le dossier ou télécharge le fichier. Tout tourne en local, rien ne quitte la machine.

Options : `--port`, `-d DOSSIER` pour le dossier des extraits, `--sans-navigateur`.

## Ligne de commande

```
ciseau clip SOURCE [DEBUT] [FIN] [options]
ciseau info SOURCE
```

- `SOURCE` : une URL ou un fichier vidéo local.
- `DEBUT`, `FIN` : `1:23:04`, `83`, `1h23m4s`, `2m30`… Un `-` à la place du début prend le `?t=` de l'URL (lien YouTube « copié à cet instant ») ; une fin absente va jusqu'au bout.

Exemples :

```
ciseau clip "https://youtu.be/XXXX?t=90" - 2:00            # de 1:30 (dans l'URL) à 2:00
ciseau clip conference.mp4 12:00 14:30 --rapide             # fichier local, copie instantanée
ciseau clip "https://…" 10:00 12:00 --audio -o refrain.m4a  # bande-son seule
ciseau clip "https://…" 0:10 0:40 --hauteur 1080 --encodeur h264_nvenc
ciseau info "https://www.youtube.com/watch?v=XXXX"          # titre, durée, chapitres
```

### Modes de découpe

| Mode | Option | Début | Vitesse | Qualité |
|---|---|---|---|---|
| précis (défaut) | `--precis` | à l'image près | réencodage, ~temps réel sur CPU, bien plus vite avec `--encodeur h264_nvenc` (NVIDIA), `h264_videotoolbox` (Mac), `h264_qsv` (Intel), `h264_amf` (AMD) | crf 18, quasi sans perte |
| rapide | `--rapide` | sur l'image-clé **précédente** (jusqu'à quelques secondes de rab, rien ne manque) | instantané | copie, sans perte |
| audio | `--audio` | à l'instant près | rapide | AAC 192 kb/s |

En mode rapide sur un fichier local, l'outil indique de combien de secondes l'extrait commence avant le point demandé.

### YouTube : « Sign in to confirm you're not a bot »

YouTube bloque parfois les téléchargements. Dans l'ordre :

1. `pip install -U yt-dlp`
2. `--cookies-navigateur chrome` (ou `firefox`, `edge`, `"chrome:Profil 1"`) pour réutiliser votre session de navigateur.
3. `--cookies cookies.txt` avec un fichier exporté depuis le navigateur.
4. Installer un runtime JS (deno ou node) : yt-dlp s'en sert pour résoudre certains formats.

## Architecture

```
ciseau/
  timecode.py    lecture/écriture des timecodes
  ffmpeg.py      localisation et pilotage de ffmpeg/ffprobe, encodeurs
  cutter.py      découpe d'un fichier local (rapide / précis / audio)
  resolver.py    métadonnées d'une URL via yt-dlp (titre, durée, chapitres)
  downloader.py  téléchargement d'une seule plage via yt-dlp + ffmpeg
  nommage.py     noms de fichiers portables
  pipeline.py    orchestration : extraire(source, debut, fin, options)
  cli.py         ligne de commande
  serveur.py     API JSON locale (bibliothèque standard) + file de travaux
  ui/index.html  interface web, un seul fichier sans build
```

`pipeline.extraire()` est le point d'entrée unique : tout client futur (API web, extension navigateur) s'y branche.

## Tests

```
pytest
```

Les tests de découpe génèrent une vidéo synthétique avec ffmpeg ; aucun accès réseau n'est nécessaire.

## Feuille de route

- Frise de vignettes (storyboard YouTube) pour viser sans lire
- Extension navigateur : touches I / O pour poser début et fin en regardant la vidéo
- « Smart cut » : réencodage des seules bordures, copie du milieu
- Extraits multiples en une passe, découpe par chapitres, recherche dans les sous-titres
- Presets d'export (vertical 9:16, GIF, codec intermédiaire pour le montage)
