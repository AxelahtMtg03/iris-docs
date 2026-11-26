"""Fabrique les documents d'exemple utilisés par les tests (python tests/make_samples.py)."""

from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt
from PIL import Image, ImageDraw

SAMPLES = Path(__file__).parent / "samples"

TEXT = {
    "fr": {
        "title": "Rapport de stage",
        "intro": "Introduction",
        "p1": "Ce rapport présente les résultats du stage effectué au sein de l'entreprise.",
        "bold": ("La mission principale consistait à ", "améliorer le site internet", " de l'équipe."),
        "link": ("Plus d'informations sur ", "notre site officiel", " ou par courriel à "),
        "list": ["Analyser les besoins des clients", "Développer une nouvelle page", "Former les collègues"],
        "table": [["Tâche", "Durée"], ["Réunion d'équipe", "Deux semaines"], ["Rédaction du rapport", "Une semaine"]],
        "nested": "Tableau imbriqué avec une remarque",
        "header": "Université de Lyon — document confidentiel",
        "footer": "Page ",
        "note": "Cette note de bas de page précise le contexte.",
        "box": "Texte placé dans une zone de texte.",
        "caption": "Figure 1 : le schéma du projet",
    },
}

NOTES_XML = (
    '<w:footnotes {ns}><w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p>'
    '</w:footnote><w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r>'
    "<w:continuationSeparator/></w:r></w:p></w:footnote>"
    '<w:footnote w:id="1"><w:p><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:footnoteRef/>'
    '</w:r><w:r><w:t xml:space="preserve"> {text}</w:t></w:r></w:p></w:footnote></w:footnotes>'
)


def _field(paragraph, instruction: str, shown: str) -> None:
    for xml in (
        '<w:r {ns}><w:fldChar w:fldCharType="begin"/></w:r>',
        f'<w:r {{ns}}><w:instrText xml:space="preserve"> {instruction} </w:instrText></w:r>',
        '<w:r {ns}><w:fldChar w:fldCharType="separate"/></w:r>',
        f"<w:r {{ns}}><w:t>{shown}</w:t></w:r>",
        '<w:r {ns}><w:fldChar w:fldCharType="end"/></w:r>',
    ):
        paragraph._p.append(parse_xml(xml.format(ns=nsdecls("w"))))


def _hyperlink(paragraph, text: str, url: str) -> None:
    rel = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = parse_xml(
        f'<w:hyperlink {nsdecls("w", "r")} r:id="{rel}"><w:r><w:rPr><w:color w:val="1D5FD8"/>'
        f'<w:u w:val="single"/></w:rPr><w:t>{text}</w:t></w:r></w:hyperlink>'
    )
    paragraph._p.append(link)


def _picture() -> io.BytesIO:
    image = Image.new("RGB", (600, 240), "#7FB5F0")
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 40, 200, 200), fill="#E8A33D")
    draw.rectangle((260, 80, 560, 160), fill="#05060B")
    stream = io.BytesIO()
    image.save(stream, "PNG")
    stream.seek(0)
    return stream


def report_docx(path: Path, lang: str = "fr") -> Path:
    """Un document complet : titres, listes, tableaux, image, en-tête, pied, note, zone de texte."""
    t = TEXT[lang]
    document = Document()
    document.styles["Normal"].font.name = "Liberation Serif"
    document.styles["Normal"].font.size = Pt(11)
    section = document.sections[0]
    section.header.paragraphs[0].text = t["header"]
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(t["footer"])
    _field(footer, "PAGE", "1")

    document.add_heading(t["title"], 0)
    document.add_heading(t["intro"], 1)
    first = document.add_paragraph(t["p1"])
    first._p.append(
        parse_xml(
            f'<w:r {nsdecls("w")}><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
            '<w:footnoteReference w:id="1"/></w:r>'
        )
    )
    mixed = document.add_paragraph()
    mixed.add_run(t["bold"][0])
    mixed.add_run(t["bold"][1]).bold = True
    mixed.add_run(t["bold"][2])
    linked = document.add_paragraph()
    linked.add_run(t["link"][0])
    _hyperlink(linked, t["link"][1], "https://example.org/projet")
    linked.add_run(t["link"][2] + "contact@example.org (https://example.org/aide).")
    for item in t["list"]:
        document.add_paragraph(item, style="List Bullet")
    code = document.add_paragraph()
    code.add_run("pip install -r requirements.txt").font.name = "Consolas"

    table = document.add_table(rows=3, cols=2, style="Light Grid Accent 1")
    for row, values in zip(table.rows, t["table"], strict=True):
        for cell, value in zip(row.cells, values, strict=True):
            cell.text = value
    inner = table.cell(2, 1).add_table(rows=1, cols=1)
    inner.style = document.styles["Table Grid"]
    inner.cell(0, 0).text = t["nested"]

    document.add_picture(_picture(), width=Inches(4.5))
    document.add_paragraph(t["caption"], style="Caption")
    box = document.add_paragraph()
    box._p.append(
        parse_xml(
            f'<w:r {nsdecls("w")} xmlns:v="urn:schemas-microsoft-com:vml"><w:pict>'
            '<v:shape id="box" type="#_x0000_t202" style="width:320pt;height:40pt">'
            f"<v:textbox><w:txbxContent><w:p><w:r><w:t>{t['box']}</w:t></w:r></w:p>"
            "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
        )
    )

    notes = NOTES_XML.format(ns=nsdecls("w"), text=t["note"]).encode()
    part = Part(
        PackURI("/word/footnotes.xml"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
        notes,
        document.part.package,
    )
    document.part.relate_to(part, RT.FOOTNOTES)
    assert qn("w:p")
    document.save(str(path))
    return path


def scanned_pdf(path: Path) -> Path:
    """Un PDF qui ne contient que l'image d'une page de texte."""
    import pymupdf

    source = pymupdf.open()
    page = source.new_page(width=595, height=842)
    page.insert_text((72, 100), "Rapport de stage", fontsize=24, fontname="hebo")
    page.insert_textbox(
        pymupdf.Rect(72, 140, 523, 400),
        "Ce rapport présente les résultats du stage effectué au sein de l'entreprise. "
        "La mission principale consistait à améliorer le site internet de l'équipe.",
        fontsize=14,
    )
    pixmap = page.get_pixmap(dpi=220)
    scan = pymupdf.open()
    scan.new_page(width=595, height=842).insert_image(
        pymupdf.Rect(0, 0, 595, 842), stream=pixmap.tobytes("png")
    )
    scan.save(str(path), deflate=True)
    return path


def text_pdf(path: Path) -> Path:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 100), "Rapport de stage", fontsize=22, fontname="hebo")
    page.insert_textbox(
        pymupdf.Rect(72, 140, 523, 400),
        "Ce rapport présente les résultats du stage effectué au sein de l'entreprise.",
        fontsize=12,
    )
    document.save(str(path), deflate=True)
    return path


if __name__ == "__main__":
    SAMPLES.mkdir(exist_ok=True)
    report_docx(SAMPLES / "Rapport_stage.docx")
    text_pdf(SAMPLES / "Rapport_texte.pdf")
    scanned_pdf(SAMPLES / "Rapport_scanne.pdf")
    print("Documents créés dans", SAMPLES)
