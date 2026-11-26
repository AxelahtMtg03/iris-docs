"""Remplace le texte d'un .docx sur place, sans toucher à la mise en forme.

Seul le contenu des éléments `w:t` change : styles, polices, tableaux, listes, images,
numérotation, champs et marges restent exactement tels qu'ils étaient.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.opc.part import XmlPart
from docx.oxml.ns import qn
from lxml import etree

from .errors import Cancelled

# (texte, passages à conserver tels quels) -> traduction
Translate = Callable[[str, list[str]], str]

_WML = "application/vnd.openxmlformats-officedocument.wordprocessingml."
_STORIES = {
    _WML + "document.main+xml": "body",
    _WML + "template.main+xml": "body",
    _WML + "header+xml": "header",
    _WML + "footer+xml": "footer",
    _WML + "footnotes+xml": "footnote",
    _WML + "endnotes+xml": "footnote",
}
_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_BREAKS = {qn(f"w:{name}") for name in ("tab", "br", "cr", "ptab", "noBreakHyphen")}
# Seuls ces champs ont un résultat qui est du texte rédigé.
_TEXT_FIELDS = {"TOC", "HYPERLINK"}
_MONOSPACE = re.compile(r"courier|consolas|mono|menlo|monaco|source code|fira code|lucida console")
_CODE_STYLE = re.compile(r"code|verbatim|preformatted|macrotext", re.I)


@dataclass
class Stats:
    paragraphs: int = 0
    translated: int = 0
    failed: int = 0
    mixed: int = 0
    tables: int = 0
    images: int = 0
    headers_footers: int = 0
    footnotes: int = 0
    textboxes: int = 0
    chars_in: int = 0
    chars_out: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class Segment:
    """Texte continu d'un paragraphe, entre deux tabulations, sauts de ligne ou champs."""

    paragraph: Any
    story: str
    texts: list[Any] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(node.text or "" for node in self.texts)


def _stories(document: Any) -> Iterator[tuple[str, Any, Callable[[], None]]]:
    for part in document.part.package.iter_parts():
        story = _STORIES.get(part.content_type)
        if not story:
            continue
        if isinstance(part, XmlPart):
            yield story, part.element, lambda: None
        else:  # notes de bas de page : python-docx les garde en octets
            parser = etree.XMLParser(resolve_entities=False, huge_tree=True)
            root = etree.fromstring(part.blob, parser)

            def commit(part: Any = part, root: Any = root) -> None:
                part._blob = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8", standalone=True
                )

            yield story, root, commit


def _field_name(instruction: str) -> str:
    words = instruction.split()
    return words[0].upper() if words else ""


def segments(root: Any, story: str) -> list[Segment]:
    found: list[Segment] = []
    current: dict[Any, Segment] = {}  # paragraphe -> segment ouvert
    fields: list[list[Any]] = []  # pile de [instruction, dans_le_résultat]
    last_simple: dict[Any, Any] = {}

    def paragraph_of(node: Any) -> Any:
        return next(node.iterancestors(qn("w:p")), None)

    for node in root.iter(
        qn("w:t"), qn("w:fldChar"), qn("w:instrText"), *_BREAKS  # type: ignore[arg-type]
    ):
        tag = node.tag
        if tag == qn("w:instrText"):
            if fields and not fields[-1][1]:
                fields[-1][0] += node.text or ""
            continue
        paragraph = paragraph_of(node)
        if tag == qn("w:fldChar"):
            kind = node.get(qn("w:fldCharType"))
            if kind == "begin":
                fields.append(["", False])
            elif kind == "separate" and fields:
                fields[-1][1] = True
            elif kind == "end" and fields:
                fields.pop()
            current.pop(paragraph, None)
            continue
        if tag in _BREAKS:
            if node.getparent().tag == qn("w:r"):  # pas les taquets de tabulation
                current.pop(paragraph, None)
            continue
        if paragraph is None:
            continue
        if any(not done or _field_name(code) not in _TEXT_FIELDS for code, done in fields):
            current.pop(paragraph, None)
            continue
        simple = next(node.iterancestors(qn("w:fldSimple")), None)
        if last_simple.get(paragraph) is not simple:
            current.pop(paragraph, None)
            last_simple[paragraph] = simple
        if simple is not None and _field_name(simple.get(qn("w:instr"), "")) not in _TEXT_FIELDS:
            continue
        segment = current.get(paragraph)
        if segment is None:
            segment = current[paragraph] = Segment(paragraph, story)
            found.append(segment)
        segment.texts.append(node)
    return found


# ---------------------------------------------------------------- mise en forme


def _signature(element: Any) -> tuple:  # type: ignore[type-arg]
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        tuple(_signature(child) for child in element),
    )


def _style_key(node: Any) -> tuple:  # type: ignore[type-arg]
    run = node.getparent()
    properties = run.find(qn("w:rPr"))
    ignored = {qn("w:lang"), qn("w:noProof")}
    style = (
        tuple(_signature(child) for child in properties if child.tag not in ignored)
        if properties is not None
        else ()
    )
    return (next(run.iterancestors(qn("w:hyperlink")), None), style)


def _is_code(node: Any) -> bool:
    properties = node.getparent().find(qn("w:rPr"))
    if properties is None:
        return False
    fonts = properties.find(qn("w:rFonts"))
    if fonts is not None and _MONOSPACE.search((fonts.get(qn("w:ascii")) or "").lower()):
        return True
    style = properties.find(qn("w:rStyle"))
    return style is not None and bool(_CODE_STYLE.search(style.get(qn("w:val"), "")))


def _code_paragraph(paragraph: Any) -> bool:
    style = paragraph.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
    return style is not None and bool(_CODE_STYLE.search(style.get(qn("w:val"), "")))


def _spans(segment: Segment) -> list[list[Any]]:
    """Regroupe les morceaux voisins qui ont exactement le même style."""
    spans: list[list[Any]] = []
    previous = None
    for node in segment.texts:
        if not node.text:
            continue
        key = _style_key(node)
        if spans and key == previous:
            spans[-1].append(node)
        else:
            spans.append([node])
        previous = key
    return spans


def _snap(text: str, position: int, low: int, high: int) -> int:
    """Frontière de mot la plus proche de `position`, comprise entre `low` et `high`."""
    edges = [
        i
        for i in range(low, high + 1)
        if i in (0, len(text)) or text[i - 1].isspace() or text[i].isspace()
    ]
    if not edges:
        return max(low, min(position, high))
    return min(edges, key=lambda i: abs(i - position))


def _locate(haystack: str, candidate: str, floor: int, expected: float) -> tuple[int, int] | None:
    """Position de `candidate` dans la phrase : à l'identique, sinon par ses mots principaux
    (« improving the website » retrouve « improve the team's website »)."""
    pattern = re.escape(candidate)
    if candidate[0].isalnum():
        pattern = r"(?<!\w)" + pattern
    if candidate[-1].isalnum():
        pattern += r"(?!\w)"
    exact = [m.span() for m in re.finditer(pattern, haystack) if m.start() >= floor]
    if exact:
        return min(exact, key=lambda s: abs(s[0] - expected))
    wanted = {word[:5] for word in re.findall(r"\w{4,}", candidate)}
    if not wanted:
        return None
    clusters: list[list[tuple[int, int, str, int]]] = []
    for index, match in enumerate(re.finditer(r"\w+", haystack)):
        stem = match.group()[:5]
        if match.start() < floor or len(match.group()) < 4 or stem not in wanted:
            continue
        if clusters and index - clusters[-1][-1][3] <= 4:
            clusters[-1].append((match.start(), match.end(), stem, index))
        else:
            clusters.append([(match.start(), match.end(), stem, index)])
    good = [c for c in clusters if len({m[2] for m in c}) * 2 >= len(wanted)]
    if not good:
        return None
    best = max(good, key=lambda c: (len({m[2] for m in c}), -abs(c[0][0] - expected)))
    return best[0][0], best[-1][1]


def distribute(translated: str, originals: list[str], translate: Callable[[str], str]) -> list[str]:
    """Découpe la traduction en autant de morceaux qu'il y a de styles.

    Le style le plus long sert de fond ; pour les autres (un mot en gras, un lien…), on
    cherche leur propre traduction dans la phrase. À défaut, la coupure est proportionnelle,
    calée sur une frontière de mot.
    """
    count = len(originals)
    if count == 1:
        return [translated]
    total = sum(map(len, originals)) or 1
    dominant = max(range(count), key=lambda i: len(originals[i]))
    cuts: list[int | None] = [0] + [None] * (count - 1) + [len(translated)]
    haystack = translated.lower()
    floor = 0
    for index, original in enumerate(originals):
        core = original.strip("  .,;:!?()[]«»\"'")
        if index == dominant or len(core) < 2:
            continue
        expected = len(translated) * sum(map(len, originals[:index])) / total
        candidates = [core]
        if core.lower() not in haystack:
            candidates.append(translate(core).strip(" .,;:!?"))
        for candidate in candidates:
            if not candidate:
                continue
            found = _locate(haystack, candidate.lower(), floor, expected)
            if found:
                start, end = found
                # Aux extrémités, la ponctuation voisine reste avec le morceau.
                if index > 0:
                    cuts[index] = start
                if index < count - 1:
                    cuts[index + 1] = end
                floor = end
                break
    done = 0
    for index in range(1, count):
        done += len(originals[index - 1])
        if cuts[index] is None:
            low = cuts[index - 1] or 0
            high = next(c for c in cuts[index + 1 :] if c is not None)
            cuts[index] = _snap(translated, round(len(translated) * done / total), low, high)
    return [translated[cuts[i] : cuts[i + 1]] for i in range(count)]


def _replace(segment: Segment, translate: Translate, stats: Stats) -> None:
    spans = _spans(segment)
    originals = ["".join(n.text for n in span) for span in spans]
    keep = [o.strip() for o, s in zip(originals, spans, strict=True) if _is_code(s[0])]
    keep = [k for k in keep if k]
    source = segment.text
    core = source.strip()
    lead = source[: len(source) - len(source.lstrip())]
    trail = source[len(source.rstrip()) :]
    translated = lead + translate(core, keep) + trail
    pieces = distribute(translated, originals, lambda text: translate(text, keep))
    for span, piece in zip(spans, pieces, strict=True):
        for position, node in enumerate(span):
            node.text = piece if position == 0 else ""
            node.set(_SPACE, "preserve")
    stats.chars_in += len(source)
    stats.chars_out += len(translated)
    if len(spans) > 1:
        stats.mixed += 1


def _translatable(segment: Segment) -> bool:
    if not any(char.isalpha() for char in segment.text):
        return False
    if _code_paragraph(segment.paragraph):
        return False
    return not all(_is_code(n) for n in segment.texts if (n.text or "").strip())


def _in_fallback(node: Any) -> bool:
    return next(node.iterancestors(_FALLBACK), None) is not None


def _count(root: Any, *tags: str) -> int:
    return sum(1 for node in root.iter(*tags) if not _in_fallback(node))


def translate_docx(
    source: Path,
    target: Path,
    translate: Translate,
    cancel: threading.Event | None = None,
    progress: Callable[[float], None] = lambda _: None,
) -> Stats:
    document = Document(str(source))
    stats = Stats()
    work: list[Segment] = []
    commits = []
    for story, root, commit in _stories(document):
        found = [s for s in segments(root, story) if _translatable(s)]
        work.extend(found)
        commits.append(commit)
        stats.tables += _count(root, qn("w:tbl"))
        stats.images += _count(root, _BLIP, _IMAGEDATA)
        stats.textboxes += _count(root, qn("w:txbxContent"))
        if story in ("header", "footer") and found:
            stats.headers_footers += 1
        if story == "footnote":
            stats.footnotes += len({s.paragraph for s in found})

    done_paragraphs: set[Any] = set()
    failed_paragraphs: set[Any] = set()
    for index, segment in enumerate(work):
        if cancel and cancel.is_set():
            raise Cancelled()
        try:
            _replace(segment, translate, stats)
            done_paragraphs.add(segment.paragraph)
        except Cancelled:
            raise
        except Exception as exc:  # un paragraphe en échec ne doit pas perdre le document
            failed_paragraphs.add(segment.paragraph)
            if len(stats.errors) < 10:
                stats.errors.append(f"{type(exc).__name__}: {exc}")
        progress((index + 1) / len(work))

    visible = {s.paragraph for s in work if not _in_fallback(s.paragraph)}
    stats.paragraphs = len(visible)
    stats.translated = len((done_paragraphs - failed_paragraphs) & visible)
    stats.failed = len(failed_paragraphs & visible)
    for commit in commits:
        commit()
    document.save(str(target))
    return stats


def excerpt(path: Path, limit: int = 4000) -> tuple[str, str, str]:
    """(titre, premier paragraphe, texte d'échantillon) pour l'aperçu et la détection."""
    body = Document(str(path)).element.body
    paragraphs = []
    size = 0
    for paragraph in body.iter(qn("w:p")):
        text = "".join(node.text or "" for node in paragraph.iter(qn("w:t"))).strip()
        if text:
            paragraphs.append(text)
            size += len(text)
        if size >= limit:
            break
    title = paragraphs[0] if paragraphs else ""
    following = next((p for p in paragraphs[1:] if len(p) > 40), "")
    if not following and len(paragraphs) > 1:
        following = paragraphs[1]
    return title[:80], following[:220], "\n".join(paragraphs)
