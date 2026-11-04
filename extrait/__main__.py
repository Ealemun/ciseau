"""Permet `python -m extrait …` sans installation."""

import sys

from .cli import main

sys.exit(main())
