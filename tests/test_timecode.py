"""Tests du module timecode (aucune dépendance externe)."""

import pytest

from ciseau.timecode import TimecodeError, format_fichier, format_hms, parse, valider_plage


@pytest.mark.parametrize(
    "texte, attendu",
    [
        ("83", 83.0),
        ("83.5", 83.5),
        ("83,5", 83.5),           # virgule décimale française
        ("1:23", 83.0),
        ("1:23:04", 4984.0),
        ("1:23:04.250", 4984.25),
        ("0:05", 5.0),
        ("1h23m4s", 4984.0),
        ("2m30", 150.0),
        ("90s", 90.0),
        ("1h", 3600.0),
        (" 12 ", 12.0),           # espaces tolérés
        (42, 42.0),               # nombre déjà numérique
    ],
)
def test_parse_formats_valides(texte, attendu):
    assert parse(texte) == pytest.approx(attendu)


@pytest.mark.parametrize("texte", ["", "abc", "1:2:3:4", "1:xx", "h", "-5"])
def test_parse_formats_invalides(texte):
    with pytest.raises(TimecodeError):
        parse(texte)


def test_format_hms():
    assert format_hms(83) == "1:23"
    assert format_hms(4984) == "1:23:04"
    assert format_hms(4984.25, millisecondes=True) == "1:23:04.250"
    assert format_hms(0) == "0:00"


def test_format_fichier_sans_deux_points():
    assert format_fichier(4984) == "1h23m04s"
    assert format_fichier(83) == "1m23s"
    assert ":" not in format_fichier(4984)


def test_valider_plage():
    valider_plage(10, 20, 100)             # ok
    valider_plage(10, None, 100)           # fin libre ok
    with pytest.raises(TimecodeError):
        valider_plage(20, 10, 100)         # fin avant début
    with pytest.raises(TimecodeError):
        valider_plage(200, None, 100)      # début après la fin de la vidéo
    with pytest.raises(TimecodeError):
        valider_plage(-1, 10, 100)
