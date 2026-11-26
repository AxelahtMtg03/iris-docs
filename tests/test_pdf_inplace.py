import threading

import pymupdf
import pytest

from iris import pdf_inplace
from iris.errors import Cancelled
from iris.pdf_text import TEX_CHARACTERS


def shout(text, keep=()):
    return text.upper()


@pytest.fixture
def report(tmp_path):
    """En-tête à deux colonnes, titre, paragraphe justifié, sommaire, lien, image et filet."""
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 40), "rapport annuel", fontsize=9)
    page.insert_text((430, 40), "ma petite école", fontsize=9)
    page.draw_line((72, 48), (523, 48))
    page.insert_text((72, 90), "1", fontsize=18, fontname="hebo")
    page.insert_text((100, 90), "introduction générale", fontsize=18, fontname="hebo")
    page.insert_textbox(
        pymupdf.Rect(72, 110, 523, 220),
        "ce texte assez long occupe plusieurs lignes de la page afin de vérifier que les "
        "lignes sont recollées en un seul paragraphe avant la traduction, puis remises à la "
        "même place sans toucher au reste du document.",
        fontsize=12,
        align=pymupdf.TEXT_ALIGN_JUSTIFY,
    )
    page.insert_text((72, 260), "contexte . . . . . . . . . . . . . . . . . 7", fontsize=12)
    page.insert_text((72, 300), "voir notre site officiel", fontsize=12)
    area = page.search_for("site officiel")[0]
    page.insert_link({"kind": pymupdf.LINK_URI, "from": area, "uri": "https://example.org"})
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 20), False)
    pixmap.set_rect(pixmap.irect, (232, 163, 61))
    page.insert_image(pymupdf.Rect(72, 340, 232, 420), pixmap=pixmap)
    document.set_toc([[1, "introduction générale", 1]])
    path = tmp_path / "rapport.pdf"
    document.save(path)
    return path


def test_paragraphs_are_rebuilt(report):
    with pymupdf.open(report) as document:
        found = pdf_inplace.paragraphs(document[0])
    texts = [" ".join(p.text.strip() for p in paragraph.pieces) for paragraph in found]
    assert "rapport annuel" in texts and "ma petite école" in texts  # deux colonnes
    assert "introduction générale" in texts  # sans son numéro
    assert "contexte" in texts  # sans les points ni le numéro de page
    body = next(p for p in found if p.pieces[0].text.startswith("ce texte"))
    assert len(body.pieces) >= 3


def test_translation_keeps_the_page(report, tmp_path):
    out = tmp_path / "out.pdf"
    stats = pdf_inplace.translate_pdf(report, out, shout)
    assert stats.failed == 0 and stats.translated >= 6
    with pymupdf.open(report) as before, pymupdf.open(out) as after:
        old, new = before[0], after[0]
        assert after.page_count == before.page_count
        assert len(new.get_images()) == len(old.get_images())
        assert len(new.get_drawings()) == len(old.get_drawings())
        text = " ".join(new.get_text().split())
        assert "INTRODUCTION GÉNÉRALE" in text and "CE TEXTE ASSEZ LONG" in text
        assert "introduction" not in text and ". . . . . 7" in text
        assert "1" in text
        assert [link["uri"] for link in new.get_links()] == ["https://example.org"]
        assert after.get_toc()[0][1] == "INTRODUCTION GÉNÉRALE"
        # le titre reste à sa place
        was = old.search_for("introduction générale")[0]
        now = new.search_for("INTRODUCTION")[0]
        assert abs(was.x0 - now.x0) < 2 and abs(was.y1 - now.y1) < 4


def test_cancel(report, tmp_path):
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        pdf_inplace.translate_pdf(report, tmp_path / "o.pdf", shout, event)
    assert not (tmp_path / "o.pdf").exists()


def test_tex_ligatures_and_punctuation():
    assert "tra\x1cc d'identi\x1cer".translate(str.maketrans(TEX_CHARACTERS)) == (
        "trafic d'identifier"
    )
    assert TEX_CHARACTERS["\x16"] == "—" and TEX_CHARACTERS["\x13"] == "«"


def test_pdf2docx_keeps_isolated_spaces():
    from pdf2docx.text.Spans import Spans

    from iris.pdf_text import repair_pdf2docx

    repair_pdf2docx()
    space = {"c": " ", "bbox": (0, 0, 3, 10), "origin": (0, 8)}
    raw = {"bbox": (0, 0, 3, 10), "chars": [space], "font": "F1", "size": 10, "flags": 0}
    assert [span.text for span in Spans().restore([raw])] == [" "]
