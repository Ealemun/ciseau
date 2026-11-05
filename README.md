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

> **Variante avec `make`** (macOS, Linux, ou Windows si tu préfères) : le `Makefile` du projet fait tout ça d'un coup.
> Sous Windows, installe d'abord make (`winget install ezwinports.make`) et rouvre PowerShell. Puis, dans le dossier du projet :
>
> ```
> make prerequis     # installe ffmpeg et deno, puis ciseau, puis vérifie
> make verifier      # à tout moment : liste ce qui est en place ou manque
> make ui            # lance l'interface
> make help          # toutes les commandes (maj, test, nettoyer…)
> ```
>
> Si `make prerequis` s'arrête après l'installation de ffmpeg et deno, rouvre le terminal et relance-le.

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

**Plusieurs extraits d'un coup :** ouvre « Plusieurs extraits d'un coup » sous le champ du lien, colle une ligne par extrait (le lien, le début, la fin) et clique **Ajouter à la file**. Trois extraits sont traités en même temps ; les autres attendent leur tour.

```
https://www.youtube.com/watch?v=AAAA 1:23 1:45
https://youtu.be/BBBB?t=90 - 2:30
https://www.twitch.tv/videos/123 1:02:00 1:03:30
```

Sous chaque extrait terminé, ciseau indique comment il l'a obtenu et en combien de temps (survole la ligne pour le détail de chaque étape).

**Piloter la file :** au-dessus de la liste, **En même temps** règle combien d'extraits tournent à la fois, sans relancer ciseau. Sur chaque extrait :

- **Annuler** arrête un extrait en attente ou en cours et libère aussitôt sa place pour le suivant ;
- **Passer en premier** fait partir un extrait en attente au prochain créneau libre (son rang dans la file s'affiche à droite) ;
- **Annuler tout ce qui attend** vide la file sans toucher aux extraits en cours.

Le panneau de l'extension propose aussi **Annuler** pendant qu'un extrait tourne.

**Rapide ou Précis ?** Le mode **Rapide** (par défaut) copie la vidéo sans la réencoder : l'extrait sort à la vitesse de ta connexion, sans perte de qualité, mais il démarre sur l'image-clé qui précède ton début, soit jusqu'à quelques secondes de rab. Le mode **Précis** réencode l'extrait (et seulement l'extrait, jamais la vidéo entière) pour couper pile sur l'image voulue : comptez 2 à 3 fois le temps réel en 1080p sur un processeur de portable. Si tu retravailles l'extrait dans un logiciel de montage, le mode Rapide suffit.

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
| Un extrait affiche « yt-dlp (méthode lente) » | La méthode rapide ne s'applique pas à cette vidéo : survole la ligne pour savoir pourquoi (pas de flux H.264 séparé, site qui ne sert pas de DASH MP4, adresse refusée…). L'extrait est quand même produit, mais au rythme de la vidéo. Si ça arrive sur YouTube, mets yt-dlp à jour (relance `ciseau.bat`, ou `make maj`). |
| L'extrait démarre une ou deux secondes trop tôt | C'est le mode **Rapide** (par défaut) : il démarre sur l'image-clé précédente. Pour couper pile, passe en **Précis** (plus lent). |
| Le lecteur intégré affiche « Cette vidéo n'est pas disponible » | Le propriétaire interdit la lecture de sa vidéo hors de YouTube (fréquent pour les chaînes officielles). L'extraction marche quand même : règle début et fin avec la frise ou les champs, ou utilise l'extension sur la page YouTube. |
| Des extraits restent longtemps « en attente » | Les places sont prises par des extraits plus longs, souvent en mode **Précis**. Annule-les, passe celui que tu veux en premier, ou augmente **En même temps**. |
| Le port 8765 est déjà utilisé | Lance `python -m ciseau ui --port 8766` et règle le même port dans la fenêtre de l'extension. |

---

## Ligne de commande

Après `pip install -e .` (ce que fait `ciseau.bat` la première fois), la commande `ciseau` est disponible. Si Windows ne la trouve pas, `python -m ciseau` fait la même chose.

```
ciseau ui                                  # l'interface (ce que lance ciseau.bat)
ciseau clip SOURCE [DEBUT] [FIN] [options] # un extrait
ciseau lot LISTE.txt [-j N] [options]      # plusieurs extraits, N à la fois (3 par défaut)
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

`LISTE.txt` contient une ligne par extrait, au même format que la zone « Plusieurs extraits d'un coup » de l'interface (voir `ciseau/lot.py`). Les lignes vides et celles qui commencent par `#` sont ignorées ; un échec n'arrête pas les autres extraits.

Options de `ciseau ui` : `--port`, `-d DOSSIER` (dossier des extraits), `-j N` (extraits en même temps, modifiable ensuite dans l'interface), `--sans-navigateur`.

### Vitesse : comment ciseau télécharge

YouTube bride toute connexion qui ne télécharge pas par morceaux de 10 Mo au plus. Or, pour une plage de temps, yt-dlp confie le travail à ffmpeg, qui lit la vidéo d'un seul tenant : bridé, il avance à peu près au rythme de la vidéo. Une minute d'extrait coûte une minute d'attente.

ciseau procède autrement (`ciseau/segments.py`) :

1. il lit l'index des flux vidéo et audio (quelques dizaines de Ko) pour savoir quels octets couvrent l'extrait ;
2. il ne télécharge que ces octets, par morceaux de 10 Mo, sur 4 connexions par flux (`--connexions`), vidéo et audio en même temps ;
3. il assemble et coupe en local : copie instantanée en mode rapide, réencodage de l'extrait seul en mode précis.

Sur un serveur de test bridé comme YouTube, extraire 1 minute d'une vidéo 720p passe de 50 s à la seule durée du transfert (31 Mo, soit environ 3 s sur une connexion à 100 Mb/s). Cette méthode s'applique aux vidéos servies en DASH MP4 (H.264 + AAC), soit l'essentiel de YouTube. Comme avant, ciseau prend le meilleur flux H.264, soit 1080p au plus sur YouTube (au-delà, YouTube ne propose que du VP9 ou de l'AV1). Si la méthode rapide ne s'applique pas, ciseau se rabat automatiquement sur yt-dlp.

S'y ajoutent :

- les métadonnées de chaque vidéo sont gardées 30 minutes : l'analyse puis le téléchargement n'interrogent YouTube qu'une fois ;
- plusieurs extraits tournent en parallèle (3 par défaut). Monter au-delà de 4 ou 5 gagne peu (la connexion ou le processeur saturent) et risque d'attirer l'attention de YouTube, qui bride les adresses trop gourmandes ;
- le mode rapide (par défaut) ne réencode rien. En mode précis, la découpe réencode l'extrait : c'est alors l'étape la plus longue. Sur une carte graphique, choisis l'encodeur correspondant (**Réglages** → **Encodeur**) pour aller plusieurs fois plus vite ;
- chaque étape peut être interrompue (`ciseau/annulation.py`) : le téléchargement s'arrête dans les 64 Ko qui suivent, ffmpeg dans la demi-seconde.

### Modes de découpe

| Mode | Option | Début | Vitesse | Qualité |
|---|---|---|---|---|
| rapide (défaut) | `--rapide` | sur l'image-clé **précédente** (quelques secondes de rab possibles, rien ne manque) | instantané | copie, sans perte |
| précis | `--precis` | à l'image près | réencodage de l'extrait : 2 à 3 fois le temps réel sur le processeur, bien plus vite avec `--encodeur h264_nvenc` (NVIDIA), `h264_amf` (AMD), `h264_qsv` (Intel), `h264_videotoolbox` (Mac) | quasi sans perte |
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
  segments.py    téléchargement rapide : index sidx, octets utiles seulement, morceaux de 10 Mo
  lot.py         lecture d'une liste d'extraits (une ligne par extrait)
  annulation.py  signal d'arrêt partagé par toutes les étapes
  pipeline.py    orchestration : extraire(source, debut, fin, options)
  cli.py         ligne de commande
  serveur.py     API JSON locale (bibliothèque standard) + file de travaux
  ui/index.html  interface web, un seul fichier sans build
extension/       extension Chrome/Edge/Brave (Manifest V3), sans build
ciseau.bat       lanceur Windows
Makefile         prérequis et commandes courantes (make help)
scripts/         petits outils appelés par le Makefile
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
- Découpe par chapitres, recherche dans les sous-titres
- Méthode rapide pour le WebM (VP9/AV1, au-delà de 1080p) et les flux HLS
- Préréglages d'export (vertical 9:16, GIF, codec intermédiaire pour le montage)
- Extension pour Firefox
