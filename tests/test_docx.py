import threading
import zipfile

import pytest
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from iris import docx_inplace
from iris.errors import Cancelled


def shout(text, keep=()):
    """Fausse traduction : majuscules, en laissant intacts les passages à conserver."""
    result = text.upper()
    for literal in keep:
        result = result.replace(literal.upper(), literal)
    return result


def xml_parts(path):
    with zipfile.ZipFile(path) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


def texts(blob):
    return [t.text or "" for t in etree.fromstring(blob).iter(qn("w:t"))]


def skeleton(blob):
    """Le XML sans le contenu des w:t : doit être identique avant et après."""
    root = etree.fromstring(blob)
    for node in root.iter(qn("w:t")):
        node.text = None
        node.attrib.clear()
    return etree.tostring(root, method="c14n")


def test_only_text_changes(sample_docx, tmp_path):
    out = tmp_path / "out.docx"
    stats = docx_inplace.translate_docx(sample_docx, out, shout)
    before, after = xml_parts(sample_docx), xml_parts(out)
    assert set(before) == set(after)
    for name in before:
        if name.startswith("word/") and name.endswith(".xml") and b"<w:t" in before[name]:
            assert skeleton(before[name]) == skeleton(after[name]), name
        if name.startswith("word/media/"):
            assert before[name] == after[name]
    assert stats.failed == 0
    assert (stats.tables, stats.images, stats.textboxes, stats.footnotes) == (2, 1, 1, 1)
    assert stats.headers_footers == 2


def test_every_story_is_translated(sample_docx, tmp_path):
    out = tmp_path / "out.docx"
    docx_inplace.translate_docx(sample_docx, out, shout)
    parts = xml_parts(out)
    body = "".join(texts(parts["word/document.xml"]))
    assert "RAPPORT DE STAGE" in body
    assert "TABLEAU IMBRIQUÉ" in body
    assert "ZONE DE TEXTE" in body
    assert "LE SCHÉMA DU PROJET" in body
    assert "pip install -r requirements.txt" in body  # le code reste tel quel
    headers = "".join("".join(texts(b)) for n, b in parts.items() if "header" in n)
    assert "UNIVERSITÉ DE LYON" in headers
    assert "BAS DE PAGE" in "".join(texts(parts["word/footnotes.xml"]))
    footer = "".join("".join(texts(b)) for n, b in parts.items() if "footer" in n)
    assert footer == "PAGE 1"


def test_field_results_are_untouched(tmp_path):
    from make_samples import _field

    document = Document()
    paragraph = document.add_paragraph("voir ")
    _field(paragraph, "REF chapitre", "section deux")
    paragraph.add_run(" et ")
    _field(paragraph, 'HYPERLINK "https://example.org"', "le site")
    source, out = tmp_path / "a.docx", tmp_path / "b.docx"
    document.save(source)
    docx_inplace.translate_docx(source, out, shout)
    assert Document(out).element.body.xpath("string(.)").count("section deux") == 1
    assert "LE SITE" in Document(out).element.body.xpath("string(.)")


def test_styles_follow_their_words(tmp_path):
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("Voici le ")
    paragraph.add_run("chat").bold = True
    paragraph.add_run(" noir.")
    source, out = tmp_path / "a.docx", tmp_path / "b.docx"
    document.save(source)
    answers = {"Voici le chat noir.": "Here is the black cat.", "chat": "cat"}
    docx_inplace.translate_docx(source, out, lambda text, keep=(): answers.get(text, text))
    runs = Document(out).paragraphs[0].runs
    assert "".join(r.text for r in runs) == "Here is the black cat."
    assert [r.text for r in runs if r.bold] == ["cat"]


@pytest.mark.parametrize(
    "translated, originals, expected",
    [
        ("one two three", ["un deux trois"], ["one two three"]),
        (
            "We absolutely had to improve the team's website for everyone.",
            ["Il nous fallait absolument ", "améliorer le site", " pour toute notre équipe."],
            ["We absolutely had to ", "improve the team's website", " for everyone."],
        ),
    ],
)
def test_distribute(translated, originals, expected):
    pieces = docx_inplace.distribute(
        translated, originals, lambda t: "improving the website" if "site" in t else t
    )
    assert pieces == expected


def test_distribute_never_loses_text():
    originals = ["abc ", "def ", "ghi ", "jkl"]
    for translated in ("x", "", "one two", "a much longer sentence than the original one"):
        assert "".join(docx_inplace.distribute(translated, originals, str.upper)) == translated


def test_failure_keeps_paragraph(sample_docx, tmp_path):
    def flaky(text, keep=()):
        if "Introduction" in text:
            raise RuntimeError("boum")
        return text.upper()

    out = tmp_path / "out.docx"
    stats = docx_inplace.translate_docx(sample_docx, out, flaky)
    assert stats.failed == 1
    assert any(p.text == "Introduction" for p in Document(out).paragraphs)


def test_cancel(sample_docx, tmp_path):
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        docx_inplace.translate_docx(sample_docx, tmp_path / "o.docx", shout, event)
    assert not (tmp_path / "o.docx").exists()
