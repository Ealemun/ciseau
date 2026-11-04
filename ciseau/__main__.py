"""Permet `python -m ciseau …` sans installation."""

import sys

from .cli import main

sys.exit(main())
