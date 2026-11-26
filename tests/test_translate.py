import pytest
from conftest import needs_models

from iris import models, translate


@pytest.mark.parametrize(
    "text, lang",
    [
        ("Ce rapport présente les résultats du stage effectué au sein de l'entreprise.", "fr"),
        ("This report presents the results of the internship carried out at the company.", "en"),
        ("Este informe presenta los resultados de las prácticas realizadas en la empresa.", "es"),
        ("12345 !!!", None),
    ],
)
def test_detect(text, lang):
    assert translate.detect(text) == lang


def test_split_sentences():
    text = "M. Martin est parti. Il revient à 18.30 ! Voir fig. 2 pour le détail."
    assert translate.split_sentences(text) == [
        "M. Martin est parti.",
        "Il revient à 18.30 !",
        "Voir fig. 2 pour le détail.",
    ]
    assert all(len(s) <= 600 for s in translate.split_sentences("mot, " * 500))


@pytest.mark.parametrize(
    "engine",
    [
        str.upper,
        lambda s: "perdu",  # le modèle fait disparaître les repères et les nombres
    ],
)
def test_protected_content_survives(engine):
    text = "Écris à a.b@example.org, visite https://example.org/x?y=1 avant le 12 : voir mon_fichier.txt"
    result = translate.protect(text, [], engine)
    for kept in ("a.b@example.org", "https://example.org/x?y=1", "12", "mon_fichier.txt"):
        assert kept in result


def test_route(monkeypatch):
    monkeypatch.setattr(models, "installed", lambda: {})
    assert models.route("fr", "en") == [("fr", "en")]
    assert models.route("fr", "es") == [("fr", "en"), ("en", "es")]


@needs_models
@pytest.mark.parametrize(
    "source, target, text, expected",
    [
        ("fr", "en", "Le chat dort dans la maison.", "cat"),
        ("en", "fr", "The cat sleeps in the house.", "chat"),
        ("en", "es", "The cat sleeps in the house.", "gato"),
        ("es", "en", "El gato duerme en la casa.", "cat"),
        ("fr", "es", "Le chat dort dans la maison.", "gato"),
        ("es", "fr", "El gato duerme en la casa.", "chat"),
    ],
)
def test_every_direction_offline(offline, source, target, text, expected):
    assert expected in translate.translator(source, target)(text, []).lower()


@needs_models
def test_real_numbers_and_links(offline):
    run = translate.translator("fr", "es")
    result = run("Le budget de 12 500 euros est détaillé sur https://example.org/budget.", [])
    assert "https://example.org/budget" in result
    assert "12" in result and "500" in result
