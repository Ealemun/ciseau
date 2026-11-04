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
# Sous Windows, le lanceur "py" est installé avec Python et évite les
# faux "python" du Microsoft Store. Ailleurs, python3.
# Pour forcer un autre Python :  make install PYTHON=python3.12
ifeq ($(OS),Windows_NT)
  PYTHON ?= py -3
  SYSTEME := windows
else
  PYTHON ?= python3
  # uname renvoie Darwin sur macOS, Linux sur Linux.
  SYSTEME := $(if $(filter Darwin,$(shell uname -s)),macos,linux)
endif

# Aide affichée par défaut quand on tape juste "make".
.DEFAULT_GOAL := help

.PHONY: help prerequis install-systeme install maj verifier ui test nettoyer

help: ## Affiche cette liste
	@$(PYTHON) scripts/outils.py aide Makefile

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
	$(PYTHON) -m pip install -e ".[dev]"

maj: ## Met yt-dlp à jour (à faire quand YouTube cesse de marcher)
	$(PYTHON) -m pip install -U "yt-dlp[default]"

# --- Contrôle et usage --------------------------------------------------------
verifier: ## Vérifie que tous les prérequis sont en place
	@$(PYTHON) scripts/outils.py verifier

ui: ## Lance l'interface (comme ciseau.bat)
	$(PYTHON) -m ciseau ui

test: ## Lance les tests
	$(PYTHON) -m pytest

nettoyer: ## Supprime les caches (garde le dossier extraits)
	@$(PYTHON) scripts/outils.py nettoyer
