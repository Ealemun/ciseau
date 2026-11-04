# ciseau

Télécharge **un extrait précis** de n'importe quelle vidéo, entre un instant de début et un instant de fin, sans récupérer la vidéo entière. Marche avec YouTube, Twitch, Twitter/X, Vimeo et 1 800 autres sites (via yt-dlp), avec un lien direct vers un fichier vidéo, ou avec un fichier sur ton disque.

Trois façons de s'en servir :

- **l'interface** dans le navigateur : on colle un lien, on règle début et fin, on clique ;
- **l'extension** de navigateur : on regarde la vidéo sur YouTube, on appuie sur `D` au début du passage, `E` à la fin, puis « Extraire » ;
- **la ligne de commande**, pour les scripts.

Tout tourne sur ta machine : rien n'est envoyé ailleurs que vers le site de la vidéo.

---

## Démarrage rapide (Windows)

### 1. Installer les prérequis (une seule fois)

Ouvre **PowerShell** et tape ces trois commandes :

```
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install DenoLand.Deno
```

- **Python** fait tourner ciseau.
- **ffmpeg** découpe les vidéos.
- **Deno** sert à yt-dlp pour lire YouTube (sans lui, certaines vidéos YouTube échouent).

**Ferme ensuite PowerShell** : les nouveaux programmes ne sont visibles que dans une fenêtre ouverte après leur installation.

Si tu n'as pas encore le projet sur ton disque :

```
cd D:\Documents
git clone https://github.com/Ealemun/ciseau Ciseau
```

### 2. Lancer ciseau

Dans l'explorateur, ouvre le dossier du projet et **double-clique sur `ciseau.bat`**.

- La première fois, il installe ce qu'il faut (une minute environ).
- Une **fenêtre noire** reste ouverte : c'est ciseau qui tourne. Garde-la ouverte pendant que tu t'en sers, ferme-la pour arrêter.
- Ton navigateur s'ouvre sur l'interface, à l'adresse `http://127.0.0.1:8765`. Si tu la fermes, cette adresse la rouvre tant que la fenêtre noire est là.

### 3. Faire un extrait depuis l'interface

1. Colle le lien de la vidéo dans le champ du haut et clique **Analyser**.
   Astuce : sur YouTube, clic droit sur la vidéo → « Copier l'URL de la vidéo à l'heure actuelle » ; le début est alors déjà placé.
2. Règle le passage, au choix :
   - pour une vidéo YouTube, lance la lecture dans la page et appuie sur **D** au début du passage, **E** à la fin ;
   - fais glisser les deux repères ✂ sur la frise ;
   - tape les instants dans les champs « Début » et « Fin » (`1:23`, `1:23:04`, `83`, `1h23m`…) ;
   - clique sur un chapitre (les petits segments sous la frise) pour le prendre en entier.
3. **Lire l'extrait** rejoue exactement le passage choisi, pour vérifier.
4. Clique **Extraire**. L'extrait apparaît dans la liste du bas avec sa progression, puis les boutons **Ouvrir le dossier** et **Télécharger**.

Les extraits sont rangés dans le dossier **`extraits`** du projet, nommés d'après la vidéo et le passage : `Titre de la vidéo [1m23s-1m45s].mp4`.

### 4. Installer l'extension (facultatif, recommandé)

L'extension pose un petit panneau en bas à droite des pages YouTube : plus besoin de copier des liens.

Dans **Chrome**, **Edge** ou **Brave** :

1. Ouvre la page des extensions : `chrome://extensions` (Edge : `edge://extensions`).
2. Active le **mode développeur** (interrupteur en haut à droite ; dans Edge, à gauche).
3. Clique **Charger l'extension non empaquetée** et choisis le dossier **`extension`** du projet.
4. Épingle l'icône ✂ dans la barre d'outils (icône en forme de pièce de puzzle → épingle).

Ensuite, avec `ciseau.bat` lancé :

1. Ouvre une vidéo YouTube : le panneau ciseau apparaît en bas à droite.
2. Pendant la lecture, appuie sur **D** au début du passage et sur **E** à la fin. Le passage s'affiche en orange sur la barre de progression de YouTube.
3. **Revoir** rejoue le passage ; **Extraire** l'envoie à ciseau. Le panneau suit la progression puis propose **Ouvrir le dossier**.

Sur un autre site (Twitch, Twitter/X, une page avec une vidéo…), clique sur l'icône ✂ puis **Afficher le panneau sur cette page**.

Le bouton **–** replie le panneau en pastille ✂ ; la fenêtre de l'extension permet de changer les touches D et E.

### 5. Mettre à jour

Dans PowerShell, depuis le dossier du projet :

```
git pull
```

puis relance `ciseau.bat`. Si tu as installé l'extension, clique aussi sur la flèche de rechargement de sa carte dans `chrome://extensions`, puis recharge les pages ouvertes.

### En cas de problème

| Ce que tu vois | Quoi faire |
|---|---|
| `ciseau.bat` dit « Python est introuvable » ou « ffmpeg est introuvable » | Installe-le avec la commande `winget` indiquée, **ferme** la fenêtre, relance `ciseau.bat`. |
| Le panneau de l'extension dit « ciseau n'est pas lancé » | Double-clique sur `ciseau.bat` et laisse la fenêtre noire ouverte. |
| Échec avec « Sign in to confirm you're not a bot » | YouTube veut une session connectée. Dans l'interface, ouvre **Réglages** → **Cookies du navigateur** et choisis **Firefox** si tu y es connecté à YouTube (le plus fiable sous Windows). Avec Chrome ou Edge, ferme complètement le navigateur avant d'extraire. |
| Échec avec « Requested format is not available » ou « n challenge solving failed » | Installe Deno (`winget install DenoLand.Deno`) et relance `ciseau.bat`, qui met aussi yt-dlp à jour. |
| L'extrait démarre une ou deux secondes trop tôt | Tu es en mode **Rapide** : il démarre sur l'image-clé précédente. Passe en **Précis** (par défaut). |
| Le port 8765 est déjà utilisé | Lance `python -m ciseau ui --port 8766` et règle le même port dans la fenêtre de l'extension. |

---

## Ligne de commande

Après `pip install -e .` (ce que fait `ciseau.bat` la première fois), la commande `ciseau` est disponible. Si Windows ne la trouve pas, `python -m ciseau` fait la même chose.

```
ciseau ui                                  # l'interface (ce que lance ciseau.bat)
ciseau clip SOURCE [DEBUT] [FIN] [options] # un extrait
ciseau info SOURCE                         # titre, durée, chapitres
```

- `SOURCE` : un lien (page vidéo ou fichier direct) ou un fichier sur le disque.
- `DEBUT`, `FIN` : `1:23:04`, `83`, `1h23m4s`, `2m30`… Un `-` à la place du début prend le `?t=` du lien ; sans fin, l'extrait va jusqu'au bout.

Exemples :

```
ciseau clip "https://www.youtube.com/watch?v=XXXX" 1:23:04 1:25:30
ciseau clip "https://youtu.be/XXXX?t=90" - 2:00             # de 1:30 (dans le lien) à 2:00
ciseau clip conference.mp4 12:00 14:30 --rapide             # fichier local, copie instantanée
ciseau clip "https://…" 10:00 12:00 --audio -o refrain.m4a  # bande-son seule
ciseau clip "https://…" 0:10 0:40 --hauteur 1080 --encodeur h264_nvenc
ciseau clip "https://…" 0:10 0:40 --cookies-navigateur firefox
```

Options de `ciseau ui` : `--port`, `-d DOSSIER` (dossier des extraits), `--sans-navigateur`.

### Modes de découpe

| Mode | Option | Début | Vitesse | Qualité |
|---|---|---|---|---|
| précis (défaut) | `--precis` | à l'image près | réencodage : à peu près le temps réel sur le processeur, bien plus vite avec `--encodeur h264_nvenc` (NVIDIA), `h264_amf` (AMD), `h264_qsv` (Intel), `h264_videotoolbox` (Mac) | quasi sans perte |
| rapide | `--rapide` | sur l'image-clé **précédente** (quelques secondes de rab possibles, rien ne manque) | instantané | copie, sans perte |
| audio | `--audio` | à l'instant près | rapide | AAC 192 kb/s |

---

## Pour les développeurs

### Architecture

```
ciseau/
  timecode.py    lecture/écriture des timecodes
  ffmpeg.py      localisation et pilotage de ffmpeg/ffprobe, encodeurs
  cutter.py      découpe d'un fichier local ou d'un lien direct (rapide / précis / audio)
  resolver.py    description d'une source : fichier, lien direct, ou page via yt-dlp
  downloader.py  téléchargement d'une seule plage via yt-dlp + ffmpeg
  nommage.py     noms de fichiers portables
  pipeline.py    orchestration : extraire(source, debut, fin, options)
  cli.py         ligne de commande
  serveur.py     API JSON locale (bibliothèque standard) + file de travaux
  ui/index.html  interface web, un seul fichier sans build
extension/       extension Chrome/Edge/Brave (Manifest V3), sans build
ciseau.bat       lanceur Windows
```

`pipeline.extraire()` est le point d'entrée unique : la ligne de commande, le serveur et donc l'interface et l'extension passent tous par lui.

Le serveur n'écoute que sur `127.0.0.1` et refuse les requêtes venant d'autres sites web (vérification des en-têtes `Host` et `Origin`, JSON obligatoire sur les POST) : une page malveillante ouverte dans le navigateur ne peut pas lancer de téléchargement à ta place. Seules l'interface elle-même et les extensions sont admises.

### Tests

```
pip install -e .[dev]
pytest
```

Les tests génèrent des vidéos synthétiques avec ffmpeg et démarrent de vrais serveurs locaux ; aucun accès à Internet n'est nécessaire.

### Feuille de route

- Frise de vignettes (storyboard YouTube) pour viser sans lire la vidéo
- « Smart cut » : réencodage des seules bordures, copie du milieu, précis et quasi instantané
- Plusieurs extraits d'une même vidéo en une passe, découpe par chapitres, recherche dans les sous-titres
- Préréglages d'export (vertical 9:16, GIF, codec intermédiaire pour le montage)
- Extension pour Firefox
