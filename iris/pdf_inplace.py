"""Traduit un PDF sur la page : chaque paragraphe est remplacé à son emplacement.

Images, schémas, filets, numéros, marges et nombre de pages ne bougent pas. Seul le texte
traduit est réécrit, avec une police proche ; il est réduit s'il ne tient pas à sa place.
"""

from __future__ import annotations

import html
import itertools
import re
import statistics
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy
import pymupdf

from .docx_inplace import Translate, distribute, locate
from .errors import Cancelled
from .pdf_text import TEX_CHARACTERS

_FLAGS = pymupdf.TEXT_MEDIABOX_CLIP | pymupdf.TEXT_CID_FOR_UNKNOWN_UNICODE
_MARKER = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[A-Z]\.(?:\d+\.?)*|[•‣▪–—∗*·]|\([\divx]+\))$")
_LEADER = re.compile(r"(?:\.\s?){5,}")
_MATH_FONT = re.compile(r"CMSY|CMMI|CMEX|MSAM|MSBM|Math|Symbol", re.I)
_MONO_FONT = re.compile(r"Courier|Consolas|Mono|CMTT|Typewriter", re.I)
_BOLD_FONT = re.compile(r"Bold|Black|Heavy|CMBX|Semibold", re.I)
_ITALIC_FONT = re.compile(r"Italic|Oblique|CMTI|CMSL|CMMI", re.I)
_SANS_FONT = re.compile(r"Sans|Arial|Helvetica|Calibri|Verdana|CMSS|Inter|Roboto|Segoe", re.I)


@dataclass(frozen=True)
class Style:
    bold: bool = False
    italic: bool = False
    mono: bool = False
    caps: bool = False  # petites capitales
    sans: bool = False
    color: int = 0


@dataclass
class Char:
    text: str
    box: pymupdf.Rect
    baseline: float
    size: float
    font: str


@dataclass
class Piece:
    """Texte continu sur une ligne : une ligne de paragraphe, une cellule, un en-tête."""

    chars: list[Char]
    block: int
    opens: bool = False  # précédé d'un numéro ou d'une puce : début de paragraphe
    closes: bool = False  # suivi de points de conduite : fin de paragraphe

    @property
    def text(self) -> str:
        return "".join(c.text for c in self.chars)

    @property
    def rect(self) -> pymupdf.Rect:
        inked = [c.box for c in self.chars if c.text.strip()]
        rect = pymupdf.Rect(inked[0])
        for box in inked[1:]:
            rect |= box
        return rect

    @property
    def baseline(self) -> float:
        return statistics.median(c.baseline for c in self.chars)

    @property
    def size(self) -> float:
        return Counter(round(c.size, 1) for c in self.chars if c.text.strip()).most_common(1)[0][0]

    @property
    def font(self) -> str:
        return Counter(c.font for c in self.chars if c.text.strip()).most_common(1)[0][0]


@dataclass
class Paragraph:
    pieces: list[Piece]

    @property
    def rect(self) -> pymupdf.Rect:
        rect = pymupdf.Rect(self.pieces[0].rect)
        for piece in self.pieces[1:]:
            rect |= piece.rect
        return rect

    @property
    def size(self) -> float:
        return self.pieces[0].size


@dataclass
class Stats:
    paragraphs: int = 0
    translated: int = 0
    failed: int = 0
    fitted: int = 0  # paragraphes réduits pour tenir à leur place
    pages: int = 0
    images: int = 0
    chars_in: int = 0
    chars_out: int = 0
    title: str = ""
    title_size: float = 0
    excerpt: str = ""
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- lecture


def _lines(page: pymupdf.Page) -> list[tuple[int, list[Char]]]:
    """Caractères horizontaux de la page, regroupés par bloc et par ligne de base."""
    result = []
    for number, block in enumerate(page.get_text("rawdict", flags=_FLAGS)["blocks"]):
        rows: list[list[Char]] = []
        for line in block.get("lines", []):
            if abs(line["dir"][0] - 1) > 0.01:
                continue  # texte tourné : laissé tel quel
            for span in line["spans"]:
                for raw in span["chars"]:
                    char = Char(
                        TEX_CHARACTERS.get(raw["c"], raw["c"]),
                        pymupdf.Rect(raw["bbox"]),
                        raw["origin"][1],
                        span["size"],
                        span["font"],
                    )
                    for row in rows:
                        if abs(row[0].baseline - char.baseline) < 0.25 * row[0].size:
                            row.append(char)
                            break
                    else:
                        rows.append([char])
        _attach_raised(rows)
        result += [(number, sorted(row, key=lambda c: c.box.x0)) for row in rows]
    return result


def _attach_raised(rows: list[list[Char]]) -> None:
    """Rattache les appels de note et exposants à la ligne de texte qu'ils surmontent."""
    for small in [row for row in rows if len(row) <= 4]:
        mark = small[0]
        for row in rows:
            main = max(row, key=lambda c: c.size)
            if (
                row is not small
                and mark.size < 0.8 * main.size
                and 0 < main.baseline - mark.baseline < 0.7 * main.size
                and any(abs(c.box.x1 - mark.box.x0) < 0.8 * main.size for c in row)
            ):
                row.extend(small)
                rows.remove(small)
                break


def _split(block: int, row: list[Char], columns: set[int] = frozenset()) -> list[Piece]:
    """Sépare cellules, numéros de titre, puces et points de conduite du texte à traduire."""
    groups: list[list[Char]] = [[]]
    last: Char | None = None
    for char in row:
        if char.text.strip():
            if last is not None:
                gap = char.box.x0 - last.box.x1
                marker = _MARKER.match("".join(c.text for c in groups[-1]).strip())
                column = gap > 0.6 * last.size and round(char.box.x0) in columns
                if gap > 1.15 * last.size or column or (marker and gap > 0.45 * last.size):
                    groups.append([])
            last = char
        groups[-1].append(char)
    # Une cellule étroite justifiée écarte beaucoup ses mots : « Médianes    glis- » est un tout.
    for index in range(len(groups) - 1, 0, -1):
        word = "".join(c.text for c in groups[index]).strip()
        if word.endswith("-") and len(word) > 1 and " " not in word:
            before = groups[index - 1][-1]
            space = [] if not before.text.strip() else [replace(before, text=" ")]
            groups[index - 1] += space + groups.pop(index)
    pieces = []
    marked = False
    for group in groups:
        if _MARKER.match("".join(c.text for c in group).strip()):
            marked = True
            if not re.search(r"[^\W\d_]{2,}", "".join(c.text for c in group)):
                continue  # le numéro ou la puce reste tel quel
        leader = _LEADER.search("".join(c.text for c in group))
        if leader:  # les points et le numéro de page restent à leur place
            ends = itertools.accumulate(len(c.text) for c in group)
            group = [c for c, end in zip(group, ends, strict=True) if end <= leader.start()]
        if any(c.text.strip() for c in group):
            pieces.append(Piece(group, block, opens=marked, closes=bool(leader)))
            marked = False
    return pieces


def _pieces(page: pymupdf.Page) -> list[Piece]:
    rows = _lines(page)
    found = [piece for block, row in rows for piece in _split(block, row)]
    # Là où plusieurs textes commencent au même endroit, il y a une colonne : un écart plus
    # faible suffit alors pour séparer deux cellules voisines.
    starts = Counter(round(p.rect.x0) for p in found)
    columns = {x for x, count in starts.items() if count >= 3}
    found = [piece for block, row in rows for piece in _split(block, row, columns)]
    return sorted(found, key=lambda p: (round(p.baseline), p.rect.x0))


def _continues(paragraph: Paragraph, piece: Piece, limits: dict[int, float], width: float) -> bool:
    last = paragraph.pieces[-1]
    if piece.opens or last.closes:
        return False
    size = last.size
    pitch = piece.baseline - last.baseline
    if not 0.6 * size < pitch < 1.75 * size or abs(piece.size - size) > 0.6:
        return False
    if len(paragraph.pieces) > 1:
        usual = paragraph.pieces[1].baseline - paragraph.pieces[0].baseline
        if pitch > usual * 1.25:
            return False
    if last.font != piece.font and last.text.rstrip().endswith(":") and len(last.text) < 40:
        return False  # « Auteurs : » puis la liste
    box, above, whole = piece.rect, last.rect, paragraph.rect
    if min(box.x1, whole.x1) - max(box.x0, whole.x0) <= 0:
        return False
    bold_change = last.font != piece.font and min(len(last.text), len(piece.text)) > 25
    aligned = abs(box.x0 - above.x0) < 2.5
    first_indented = len(paragraph.pieces) == 1 and 0 < above.x0 - box.x0 < 3.5 * size
    centred = abs((box.x0 + box.x1) - (above.x0 + above.x1)) < 5
    if centred and not aligned:
        # Des lignes centrées courtes (noms, mentions) restent indépendantes.
        return size >= 14 or min(box.width, above.width) > 0.6 * width
    if not (aligned or first_indented) or (bold_change and size >= 14):
        return False
    # Si le premier mot de la ligne suivante tenait au bout de la précédente, c'est voulu.
    word = piece.text.strip().split(" ")[0]
    average = box.width / max(1, len(piece.text.strip()))
    right = max(limits[last.block], limits[piece.block], whole.x1)
    return above.x1 + average * len(word) + 0.35 * size > right - 1


def paragraphs(page: pymupdf.Page) -> list[Paragraph]:
    pieces = _pieces(page)
    limits: dict[int, float] = {}
    for piece in pieces:
        limits[piece.block] = max(limits.get(piece.block, 0), piece.rect.x1)
    width = max((p.rect.x1 for p in pieces), default=0) - min(
        (p.rect.x0 for p in pieces), default=0
    )
    found: list[Paragraph] = []
    for piece in pieces:
        for paragraph in reversed(found[-12:]):
            if _continues(paragraph, piece, limits, width):
                paragraph.pieces.append(piece)
                break
        else:
            found.append(Paragraph([piece]))
    return found


# ---------------------------------------------------------------- style des polices


def _ink(page: pymupdf.Page, box: pymupdf.Rect) -> numpy.ndarray:
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(6, 6), clip=box, colorspace=pymupdf.csGRAY)
    data = numpy.frombuffer(pixmap.samples, dtype=numpy.uint8)
    return 1 - data.reshape(pixmap.height, pixmap.stride)[:, : pixmap.width] / 255


def _sharpness(ink: numpy.ndarray, slant: float) -> float:
    height = ink.shape[0]
    shifts = [int(round(slant * (row - height / 2))) for row in range(height)]
    straight = numpy.stack([numpy.roll(ink[row], shifts[row]) for row in range(height)])
    return float((straight.sum(axis=0) ** 2).sum())


class Fonts:
    """Gras, italique, petites capitales et chasse fixe de chaque police du document.

    Les PDF issus de LaTeX nomment souvent leurs polices « F42 » sans aucune indication :
    ces propriétés sont alors mesurées sur le dessin des lettres.
    """

    def __init__(self, document: pymupdf.Document) -> None:
        samples: dict[str, list[tuple[int, Piece]]] = {}
        widths: dict[str, dict[str, float]] = {}
        usage: Counter[str] = Counter()
        for number, page in enumerate(document):
            for piece in _pieces(page):
                usage[piece.font] += len(piece.text)
                if len(piece.text) > 3 and len(samples.setdefault(piece.font, [])) < 6:
                    samples[piece.font].append((number, piece))
                for char in piece.chars:
                    if char.text.isalpha():
                        widths.setdefault(char.font, {})[char.text] = char.box.width / char.size
        measures = {font: self._measure(document, items) for font, items in samples.items()}
        # Une police grasse a des traits plus épais ET des lettres plus larges : le produit
        # des deux la distingue d'un simple titre en grand corps.
        weights = {}
        for font, (stem, _, _) in measures.items():
            common = [widths.get(font, {})[c] for c in "aeno" if c in widths.get(font, {})]
            weights[font] = stem * (statistics.mean(common) if common else 0.5)
        body = usage.most_common(1)[0][0] if usage else ""
        reference = weights.get(body, 0)
        self.styles: dict[str, Style] = {}
        for font in usage:
            _, slant, caps = measures.get(font, (0, 0, False))
            values = widths.get(font, {})
            fixed = len(values) >= 6 and max(values.values()) < 1.03 * min(values.values())
            named = not re.fullmatch(r"F\d+|T\d+|Type3.*", font)
            self.styles[font] = Style(
                bold=(
                    bool(_BOLD_FONT.search(font))
                    if named
                    else bool(reference) and weights.get(font, 0) > 1.62 * reference
                ),
                italic=bool(_ITALIC_FONT.search(font)) if named else bool(slant > 1.12),
                mono=bool(_MONO_FONT.search(font)) or fixed,
                caps=bool(not named and caps),
                sans=bool(_SANS_FONT.search(font)),
            )

    @staticmethod
    def _measure(
        document: pymupdf.Document, items: list[tuple[int, Piece]]
    ) -> tuple[float, float, bool]:
        stems, slants, ascender, flat = [], [], [], []
        for number, piece in items:
            ink = _ink(document[number], piece.rect)
            if ink.size == 0 or ink.sum() == 0:
                continue
            rows = numpy.flatnonzero(ink.max(axis=1) > 0.5)
            if rows.size:
                body = ink[rows[0] : rows[-1] + 1]
                for row in (ink > 0.45).astype(numpy.int8):  # épaisseur des traits
                    edges = numpy.flatnonzero(numpy.diff(row, prepend=0, append=0))
                    stems += list((edges[1::2] - edges[::2]) / (piece.size * 6))
                slants.append(_sharpness(body, 0.22) / max(_sharpness(body, 0), 1e-6))
            for char in piece.chars:
                if char.text in "bdhklaeomnrs" and len(ascender) + len(flat) < 60:
                    glyph = _ink(document[number], char.box)
                    lit = numpy.flatnonzero(glyph.max(axis=1) > 0.5) if glyph.size else []
                    if len(lit):
                        (ascender if char.text in "bdhkl" else flat).append(lit[-1] - lit[0])
        caps = bool(ascender and flat) and statistics.median(ascender) < 1.12 * statistics.median(
            flat
        )
        return (
            float(numpy.median(stems)) if stems else 0,
            statistics.median(slants) if slants else 0,
            caps,
        )

    def of(self, char: Char, color: int) -> Style:
        base = self.styles.get(char.font, Style())
        return Style(base.bold, base.italic, base.mono, base.caps, base.sans, color)


def _colors(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, int]]:
    blocks = page.get_text("dict", flags=_FLAGS)["blocks"]
    return [
        (pymupdf.Rect(span["bbox"]), span["color"])
        for block in blocks
        for line in block.get("lines", [])
        for span in line["spans"]
        if span["color"]
    ]


# ---------------------------------------------------------------- écriture


def _worth_translating(paragraph: Paragraph, fonts: Fonts) -> bool:
    chars = [c for p in paragraph.pieces for c in p.chars if c.text.strip()]
    if sum(bool(_MATH_FONT.search(c.font)) for c in chars) > 0.3 * len(chars):
        return False
    if all(fonts.styles.get(c.font, Style()).mono for c in chars):
        return False
    return bool(re.search(r"[^\W\d_]{2,}", "".join(p.text for p in paragraph.pieces)))


_NOTE = 0xE000  # caractère privé qui marque la place d'un appel de note


def _runs(
    paragraph: Paragraph, fonts: Fonts, colors: list[tuple[pymupdf.Rect, int]]
) -> tuple[list[tuple[Style, str]], list[tuple[str, str]]]:
    """Le texte du paragraphe, lignes recollées et découpé par style, et les appels de note
    (mot précédent, appel) retirés de la phrase pour ne pas gêner la traduction."""
    runs: list[tuple[Style, str]] = []
    notes: list[tuple[str, str]] = []

    def add(style: Style, text: str) -> None:
        if runs and (runs[-1][0] == style or not text.strip()):
            runs[-1] = (runs[-1][0], runs[-1][1] + text)
        else:
            runs.append((style, text))

    for index, piece in enumerate(paragraph.pieces):
        tinted = [(box, value) for box, value in colors if box.intersects(piece.rect)]
        text = piece.text
        following = (
            paragraph.pieces[index + 1].text.strip() if index + 1 < len(paragraph.pieces) else ""
        )
        # mot coupé en fin de ligne
        hyphen = text.rstrip().endswith("-") and following[:1].islower()
        chars = piece.chars
        while chars and not chars[-1].text.strip():
            chars = chars[:-1]
        if hyphen:
            chars = chars[:-1]
        raised = False
        for char in chars:
            if (
                char.size < 0.8 * piece.size
                and char.baseline < piece.baseline - 0.15 * piece.size
                and char.text.strip()
            ):
                if raised:
                    notes[-1] = (notes[-1][0], notes[-1][1] + char.text)
                else:
                    words = re.findall(r"[^\W\d_]+", "".join(t for _, t in runs))
                    notes.append((words[-1] if words else "", char.text))
                    if runs:
                        runs[-1] = (runs[-1][0], runs[-1][1].rstrip())
                raised = True
                continue
            raised = False
            centre = (char.box.tl + char.box.br) / 2
            color = next((value for box, value in tinted if centre in box), 0)
            style = fonts.of(char, color)
            add(style if char.text.strip() or not runs else runs[-1][0], char.text)
        if following and not hyphen:
            add(runs[-1][0], " ")
    return runs, notes


def _place_notes(translated: str, notes: list[tuple[str, str]], translate: Translate) -> str:
    """Remet chaque appel de note après la traduction du mot qu'il suivait, sinon à la fin."""
    floor = 0
    for index, (word, _) in enumerate(notes):
        found = None
        if len(word) > 1:
            candidate = translate(word, []).strip(" .").lower()
            if candidate:
                found = locate(translated.lower(), candidate, floor, len(translated))
        position = found[1] if found else len(translated.rstrip(" .:;"))
        translated = translated[:position] + chr(_NOTE + index) + translated[position:]
        floor = position + 1
    return translated


@lru_cache(maxsize=64)
def _baseline_offset(family: str, leading: float) -> float:
    """Distance, pour un corps de 100, entre le haut du cadre et la première ligne de base."""
    document = pymupdf.open()
    page = document.new_page(width=800, height=800)
    page.insert_htmlbox(
        pymupdf.Rect(0, 0, 800, 400),
        "<p>Hx</p>",
        css="* {margin:0;padding:0} "
        f"p {{font-family:{family};font-size:100px;line-height:{leading}}}",
    )
    return page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]["origin"][1]


@dataclass
class Layout:
    box: pymupdf.Rect
    align: str
    indent: float
    leading: float


def _layout(
    paragraph: Paragraph,
    family: str,
    others: list[pymupdf.Rect],
    page: pymupdf.Rect,
    left: float,
    right: float,
) -> Layout:
    """Où écrire la traduction : la place d'origine, élargie à l'espace libre voisin."""
    size, rect = paragraph.size, paragraph.rect
    pieces = paragraph.pieces
    pitches = [b.baseline - a.baseline for a, b in zip(pieces, pieces[1:], strict=False)]
    leading = round(max(1.0, min(1.6, statistics.median(pitches) / size)) if pitches else 1.2, 2)
    centre = (rect.x0 + rect.x1) / 2
    middle = (left + right) / 2
    rest = [p.rect for p in pieces[1:]] or [pieces[0].rect]
    indent = 0.0
    if (
        len(pieces) > 1
        and all(abs((p.rect.x0 + p.rect.x1) / 2 - centre) < 3 for p in pieces)
        and (max(p.rect.x0 for p in pieces) - min(p.rect.x0 for p in pieces) > 3)
    ):
        align = "center"
    elif len(pieces) > 1:
        body = min(r.x0 for r in rest)
        indent = pieces[0].rect.x0 - body
        indent = indent if indent > 0.8 * size else 0.0  # en deçà : simple irrégularité
        edges = [p.rect.x1 for p in pieces[:-1]]
        align = "justify" if len(pieces) > 2 and max(edges) - min(edges) < 2.5 else "left"
    elif pieces[0].opens or pieces[0].closes:
        align = "left"  # entrée de liste ou de table des matières
    elif abs(centre - middle) < 4 and rect.x0 > left + 15:
        align = "center"
    elif rect.x1 > right - 3 and rect.x0 > middle:
        align = "right"
    else:
        align = "left"

    first = pieces[0].baseline
    top = first - _baseline_offset(family, leading) * size / 100
    bottom = pieces[-1].baseline + max(0.35, leading - 0.85) * size
    beside = [o for o in others if o.y0 < bottom - 1 and o.y1 > first - 0.5 * size]
    x0, x1 = (rect.x0 - indent if indent else rect.x0), rect.x1
    x0 = min(p.rect.x0 for p in pieces) if indent else x0
    wall_right = min([o.x0 - 3 for o in beside if o.x0 >= rect.x1 - 1] + [max(right, rect.x1)])
    wall_left = max([o.x1 + 3 for o in beside if o.x1 <= rect.x0 + 1] + [min(left, rect.x0)])
    if align == "center":
        reach = max(0.0, min(centre - wall_left, wall_right - centre))
        x0, x1 = min(rect.x0, centre - reach), max(rect.x1, centre + reach)
    elif align == "right":
        x0 = wall_left
    elif align == "left":
        x1 = max(x1, wall_right)
    x1 += 1.5  # marge d'arrondi : une ligne identique ne doit pas passer à la suivante
    below = [
        o.y0 - 1
        for o in others
        if o.y0 >= pieces[-1].baseline + 0.15 * size and o.x0 < x1 and o.x1 > x0
    ]
    room = min([*below, page.y1 - 8])
    bottom = max(bottom, min(room, bottom + max(1.0, 0.5 * len(pieces)) * leading * size))
    return Layout(pymupdf.Rect(x0, top, x1, bottom), align, indent, leading)


def _markup(runs: list[tuple[Style, str]], notes: list[tuple[str, str]]) -> str:
    parts = []
    for style, text in runs:
        if style.caps:
            text = text.upper()
        text = html.escape(text, quote=False)
        css = []
        if style.color:
            css.append(f"color:#{style.color:06x}")
        if style.caps:
            css.append("font-size:82%")
        if style.mono:
            css.append("font-family:monospace")
        if css:
            text = f'<span style="{";".join(css)}">{text}</span>'
        if style.bold:
            text = f"<b>{text}</b>"
        if style.italic:
            text = f"<i>{text}</i>"
        parts.append(text)
    markup = "".join(parts)
    for index, (_, mark) in enumerate(notes):
        markup = markup.replace(chr(_NOTE + index), f"<sup>{html.escape(mark)}</sup>")
    return markup


@dataclass
class Replacement:
    paragraph: Paragraph
    runs: list[tuple[Style, str]]
    layout: Layout
    family: str
    notes: list[tuple[str, str]]


def _restore_links(page: pymupdf.Page, before: list[dict[str, Any]]) -> None:
    """Effacer du texte retire aussi les liens posés dessus : on les remet."""
    kept = {tuple(round(v) for v in link["from"]) for link in page.get_links()}
    for link in before:
        if tuple(round(v) for v in link["from"]) in kept:
            continue
        if link["kind"] == pymupdf.LINK_URI:
            page.insert_link({"kind": link["kind"], "from": link["from"], "uri": link["uri"]})
        elif link.get("page", -1) >= 0:
            page.insert_link(
                {
                    "kind": pymupdf.LINK_GOTO,
                    "from": link["from"],
                    "page": link["page"],
                    "to": link.get("to") or pymupdf.Point(0, 0),
                }
            )


def _write(page: pymupdf.Page, replacements: list[Replacement], stats: Stats) -> None:
    links = page.get_links()
    for item in replacements:
        for piece in item.paragraph.pieces:
            # Une bande étroite au milieu des lettres n'atteint pas les lignes voisines.
            rect, base, size = piece.rect, piece.baseline, piece.size
            band = pymupdf.Rect(rect.x0 + 0.3, base - 0.35 * size, rect.x1 - 0.3, base - 0.2 * size)
            page.add_redact_annot(band, fill=False)
            for char in piece.chars:  # les exposants sont au-dessus de la bande
                if char.size < 0.8 * size and char.text.strip():
                    centre = (char.box.tl + char.box.br) / 2
                    dot = pymupdf.Rect(centre, centre) + (-0.5, -0.5, 0.5, 0.5)
                    page.add_redact_annot(dot, fill=False)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE
    )
    for item in replacements:
        layout = item.layout
        # Un titre ou une cellule reste sur sa ligne ; une longue phrase peut passer à la suivante.
        single = len(item.paragraph.pieces) == 1
        wrap = (
            "nowrap" if single and item.paragraph.rect.width < 0.55 * page.rect.width else "normal"
        )
        css = (
            "* {margin:0;padding:0} "
            f"p {{font-family:{item.family};font-size:{item.paragraph.size}px;"
            f"line-height:{layout.leading};text-align:{layout.align};"
            f"text-indent:{layout.indent}px;white-space:{wrap}}}"
        )
        _, scale = page.insert_htmlbox(
            layout.box, f"<p>{_markup(item.runs, item.notes)}</p>", css=css, scale_low=0
        )
        if scale < 0.9:
            stats.fitted += 1
    _restore_links(page, links)


def translate_pdf(
    source: Path,
    target: Path,
    translate: Translate,
    cancel: threading.Event | None = None,
    progress: Callable[[float], None] = lambda _: None,
) -> Stats:
    stats = Stats()
    with pymupdf.open(source) as document:
        stats.pages = document.page_count
        fonts = Fonts(document)
        for number, page in enumerate(document):
            found = paragraphs(page)
            wanted = [p for p in found if _worth_translating(p, fonts)]
            stats.paragraphs += len(wanted)
            stats.images += len(page.get_images())
            if not found:
                continue
            colors = _colors(page)
            left = min(p.rect.x0 for p in found)
            right = max(p.rect.x1 for p in found)
            pictures = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
            drawings = [d["rect"] for d in page.get_drawings()]
            replacements = []
            for index, paragraph in enumerate(wanted):
                if cancel and cancel.is_set():
                    raise Cancelled()
                runs, notes = _runs(paragraph, fonts, colors)
                originals = [text for _, text in runs]
                source_text = "".join(originals).strip()
                keep = [t.strip() for s, t in runs if s.mono and t.strip()]
                try:
                    translated = _place_notes(translate(source_text, keep), notes, translate)
                    pieces = distribute(translated, originals, lambda t, k=keep: translate(t, k))
                except Cancelled:
                    raise
                except Exception as exc:
                    stats.failed += 1
                    if len(stats.errors) < 10:
                        stats.errors.append(f"{type(exc).__name__}: {exc}")
                    continue
                style = max(runs, key=lambda r: len(r[1]))[0]
                family = "monospace" if style.mono else "sans-serif" if style.sans else "serif"
                own = {id(p) for p in paragraph.pieces}
                others = [p.rect for o in found for p in o.pieces if id(p) not in own]
                area = paragraph.rect
                others += [r for r in pictures + drawings if not r.intersects(area)]
                layout = _layout(paragraph, family, others, page.rect, left, right)
                styled = [(s, piece) for (s, _), piece in zip(runs, pieces, strict=True)]
                replacements.append(Replacement(paragraph, styled, layout, family, notes))
                stats.translated += 1
                stats.chars_in += len(source_text)
                stats.chars_out += len(translated)
                if number == 0 and paragraph.size > stats.title_size:
                    stats.title, stats.title_size = translated[:80], paragraph.size
                if not stats.excerpt and len(translated) > 80:
                    stats.excerpt = translated[:220]
                progress((number + (index + 1) / len(wanted)) / document.page_count)
            _write(page, replacements, stats)
            progress((number + 1) / document.page_count)

        outline = document.get_toc(simple=False)
        if outline:
            for entry in outline:
                if cancel and cancel.is_set():
                    raise Cancelled()
                entry[1] = translate(entry[1], [])
            document.set_toc(outline)
        document.subset_fonts()
        document.save(str(target), garbage=3, deflate=True)
    return stats
