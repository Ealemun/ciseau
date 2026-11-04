# ==========================================================================
#  ciseau - Makefile
#
#  Installe les prérequis et regroupe les commandes courantes.
#  Marche sous Windows (avec make installé : winget install ezwinports.make),
#  macOS et Linux.  Pour la liste des cibles :  make help
#
#  Les lignes de commande d'une cible DOIVENT commencer par une tabulation
#  (pas des espaces), c'est une exigence de make.
# ==========================================================================

# --- Quel Python utiliser ---------------------------------------------------
# La variable s'appelle CISEAU_PY (et non PYTHON) exprès : beaucoup de machines
# ont déjà une variable d'environnement PYTHON, parfois avec un chemin contenant
# des espaces, et make la reprendrait sans guillemets (le chemin serait coupé).
#
# Choix par défaut :
#   - Windows : le lanceur "py -3" s'il fonctionne (installé avec Python depuis
#     python.org ou winget), sinon "python" tel que trouvé dans le PATH ;
#   - macOS / Linux : python3.
# Pour forcer un Python précis (les guillemets protègent les espaces du chemin) :
#   make install CISEAU_PY='"C:\mon dossier\python.exe"'
ifeq ($(OS),Windows_NT)
  CISEAU_PY ?= $(if $(shell py -3 --version 2>/dev/null),py -3,python)
  SYSTEME := windows
else
  CISEAU_PY ?= python3
  # uname renvoie Darwin sur macOS, Linux sur Linux.
  SYSTEME := $(if $(filter Darwin,$(shell uname -s)),macos,linux)
endif

# Aide affichée par défaut quand on tape juste "make".
.DEFAULT_GOAL := help

.PHONY: help prerequis install-systeme install maj verifier ui test nettoyer

help: ## Affiche cette liste
	@$(CISEAU_PY) scripts/outils.py aide Makefile

prerequis: install-systeme install verifier ## Tout installer puis tout vérifier (à lancer une fois)

# --- Programmes du système : ffmpeg et deno ------------------------------------
# Le "-" devant une commande dit à make de continuer même si elle échoue :
# winget, par exemple, renvoie une erreur quand le programme est déjà installé.
install-systeme: ## Installe ffmpeg et deno avec le gestionnaire de paquets du système
ifeq ($(SYSTEME),windows)
	-winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
	-winget install --id DenoLand.Deno -e --accept-source-agreements --accept-package-agreements
	@echo Ferme puis rouvre ce terminal pour que ffmpeg et deno soient trouves, puis lance : make install
else ifeq ($(SYSTEME),macos)
	brew install ffmpeg deno
else
	-sudo apt-get install -y ffmpeg
	@echo "Deno : installe-le avec la commande de https://docs.deno.com/runtime/getting_started/installation/ (non lancée automatiquement)."
endif

# --- Paquets Python -----------------------------------------------------------
install: ## Installe ciseau et ses dépendances Python (yt-dlp, pytest)
	$(CISEAU_PY) -m pip install -e ".[dev]"

maj: ## Met yt-dlp à jour (à faire quand YouTube cesse de marcher)
	$(CISEAU_PY) -m pip install -U "yt-dlp[default]"

# --- Contrôle et usage --------------------------------------------------------
verifier: ## Vérifie que tous les prérequis sont en place
	@$(CISEAU_PY) scripts/outils.py verifier

ui: ## Lance l'interface (comme ciseau.bat)
	$(CISEAU_PY) -m ciseau ui

test: ## Lance les tests
	$(CISEAU_PY) -m pytest

nettoyer: ## Supprime les caches (garde le dossier extraits)
	@$(CISEAU_PY) scripts/outils.py nettoyer
