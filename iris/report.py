"""Rapport de fidélité : ce qui a été traité, et ce qu'il faut vérifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .docx_inplace import Stats
from .errors import message
from .pdf_inplace import Stats as PdfStats

LONGER_THRESHOLD = 1.10


@dataclass
class Report:
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def warn(self, code: str, **params: Any) -> None:
        self.warnings.append({"code": code, "params": params})

    def add_translation(self, stats: Stats) -> None:
        self.counts = {
            "paragraphs": stats.translated,
            "tables": stats.tables,
            "images": stats.images,
            "headers_footers": stats.headers_footers,
            "footnotes": stats.footnotes,
            "textboxes": stats.textboxes,
        }
        if stats.failed:
            self.warn("w_untranslated", count=stats.failed)
        if stats.chars_in > 200 and stats.chars_out > stats.chars_in * LONGER_THRESHOLD:
            self.warn("w_longer", percent=round((stats.chars_out / stats.chars_in - 1) * 100))
        if stats.mixed:
            self.warn("w_mixed_style", count=stats.mixed)

    def add_pdf_translation(self, stats: PdfStats, keeps_pdf: bool) -> None:
        self.counts = {"paragraphs": stats.translated, "images": stats.images}
        if stats.failed:
            self.warn("w_untranslated", count=stats.failed)
        if keeps_pdf:
            self.warn("w_pdf_inplace")
        if stats.fitted:
            self.warn("w_fitted", count=stats.fitted)

    def localized(self, lang: str = "fr") -> dict[str, Any]:
        return {
            "counts": self.counts,
            "warnings": [
                {"code": w["code"], "message": message(w["code"], lang, **w["params"])}
                for w in self.warnings
            ],
        }
