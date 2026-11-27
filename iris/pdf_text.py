"""Particularités de lecture des PDF, surtout ceux produits par LaTeX."""

from __future__ import annotations

import re
from collections.abc import Iterable

# Polices TeX sans table Unicode : les ligatures sortent comme des caractères de contrôle.
# Codage T1 (0x1B-0x1F) et OT1 (0x0B-0x0F).
TEX_LIGATURES = {
    "\x1b": "ff",
    "\x1c": "fi",
    "\x1d": "fl",
    "\x1e": "ffi",
    "\x1f": "ffl",
    "\x0b": "ff",
    "\x0c": "fi",
    "\x0d": "fl",
    "\x0e": "ffi",
    "\x0f": "ffl",
}
# Guillemets et tirets du codage T1, lus sur le même principe.
TEX_PUNCTUATION = {
    "\x10": "“",
    "\x11": "”",
    "\x12": "„",
    "\x13": "«",
    "\x14": "»",
    "\x15": "–",
    "\x16": "—",
}
# La puce des listes (police de symboles TS1) sort aussi comme un caractère de contrôle.
TEX_CHARACTERS = TEX_LIGATURES | TEX_PUNCTUATION | {"\x88": "•"}

# Polices « F47 » sans table Unicode : le même code désigne un signe ou une lettre selon la police.
_TEX_FONT = re.compile(r"F\d+")
_TS1_SYMBOLS = {
    "\x88": "•",
    "\xd6": "×",
    "\xf6": "÷",
    "\xb0": "°",
    "\xb1": "±",
    "\xb5": "µ",
}
_T1_LETTERS = {"\xf7": "œ", "\xd7": "Œ"}


def tex_font_characters(spans: Iterable[tuple[str, str]]) -> dict[str, dict[str, str]]:
    """Corrections propres à chaque police TeX d'une page, d'après les couples (police, texte).

    Une police qui n'écrit que des signes est la police de symboles ; une police qui écrit des
    lettres est une police de texte.
    """
    seen: dict[str, set[str]] = {}
    for font, text in spans:
        if _TEX_FONT.fullmatch(font):
            seen.setdefault(font, set()).update(text.replace(" ", ""))
    return {
        font: _TS1_SYMBOLS if characters <= _TS1_SYMBOLS.keys() else _T1_LETTERS
        for font, characters in seen.items()
        if characters <= _TS1_SYMBOLS.keys() or any(c.isascii() and c.isalpha() for c in characters)
    }


def repair_pdf2docx() -> None:
    """Corrige deux pertes de pdf2docx avant une conversion.

    Il supprime les espaces isolés, nombreux dans un texte justifié (les mots se collent), et
    les ligatures TeX (« trafic » devient « trac »).
    """
    from pdf2docx.text.Char import Char
    from pdf2docx.text.Spans import Spans
    from pdf2docx.text.TextSpan import TextSpan

    original_init = Char.__init__

    def init(self, raw=None):  # type: ignore[no-untyped-def]
        if raw and raw.get("c") in TEX_CHARACTERS:
            raw = {**raw, "c": TEX_CHARACTERS[raw["c"]]}
        original_init(self, raw)

    def restore(self, raws):  # type: ignore[no-untyped-def]
        from pdf2docx.image.ImageSpan import ImageSpan

        for raw in raws:
            span = ImageSpan(raw) if "image" in raw else TextSpan(raw)
            self.append(span)
        return self

    Char.__init__ = init
    Spans.restore = restore
