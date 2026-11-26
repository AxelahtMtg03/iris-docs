"""Enchaîne les étapes d'une demande : lecture, traduction, export, enregistrement."""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import convert, docx_inplace, models, translate
from .errors import Cancelled, IrisError
from .report import Report
from .storage import session_tmp

log = logging.getLogger("iris")
Progress = Callable[[float, str], None]
_WEIGHTS = {"pdf_to_docx": 30, "ocr": 60, "translate": 60, "docx_to_pdf": 25, "save": 2}


@dataclass
class Request:
    source: Path
    target_format: str  # "docx" ou "pdf"
    translate: bool = False
    source_lang: str = "fr"
    target_lang: str = "en"
    out_dir: Path | None = None  # None : à côté du fichier source
    ocr: str = "auto"
    name: str | None = None  # nom d'origine si le fichier est une copie temporaire


@dataclass
class Result:
    output: Path
    report: Report
    duration: float
    preview: tuple[str, str] = ("", "")  # titre et début du texte produit


def save_unique(produced: Path, folder: Path, stem: str, ext: str) -> Path:
    """Copie sans jamais écraser : Nom.ext, puis Nom_1.ext, Nom_2.ext…"""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        number = 0
        while True:
            candidate = folder / (f"{stem}_{number}.{ext}" if number else f"{stem}.{ext}")
            try:
                handle = candidate.open("xb")
                break
            except FileExistsError:
                number += 1
        try:
            with handle, produced.open("rb") as source:
                shutil.copyfileobj(source, handle)
        except OSError:
            candidate.unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise IrisError("write_failed", str(exc), folder=str(folder)) from exc
    return candidate


def _preview(document: Path) -> tuple[str, str]:
    """Lu dans le Word, avant un éventuel export : le PDF mettrait l'en-tête en premier."""
    try:
        title, body, _ = docx_inplace.excerpt(document)
    except Exception:  # l'aperçu est un bonus : il ne doit pas faire échouer la tâche
        log.exception("Aperçu impossible")
        return "", ""
    return title, body


def run(
    request: Request,
    progress: Progress = lambda fraction, stage: None,
    cancel: threading.Event | None = None,
) -> Result:
    started = time.monotonic()
    cancel = cancel or threading.Event()
    progress(0.0, "analyze")
    kind = convert.sniff(request.source)
    target = request.target_format
    if target not in ("docx", "pdf"):
        raise IrisError("bad_request", f"format {target}")
    if not request.translate and kind == target:
        raise IrisError("nothing_to_do")

    # Tout ce qui peut manquer est vérifié avant de commencer à travailler.
    if target == "pdf" and not convert.find_soffice():
        raise IrisError("no_libreoffice")
    if request.translate:
        models.require(request.source_lang, request.target_lang)
    info, scan = None, False
    if kind == "pdf":
        info = convert.pdf_info(request.source)
        if info.is_scan and request.ocr == "no":
            raise IrisError("scan_without_ocr")
        scan = request.ocr == "yes" or (request.ocr == "auto" and info.is_scan)
        if scan:
            convert.check_ocr(request.source_lang if request.translate else None)
        elif not info.text.strip():
            raise IrisError("no_text")

    steps = []
    if kind == "pdf":
        steps.append("ocr" if scan else "pdf_to_docx")
    if request.translate:
        steps.append("translate")
    if target == "pdf":
        steps.append("docx_to_pdf")
    steps.append("save")
    total = sum(_WEIGHTS[s] for s in steps)

    def stage(name: str) -> Callable[[float], None]:
        before = sum(_WEIGHTS[s] for s in steps[: steps.index(name)])

        def report_progress(fraction: float) -> None:
            progress((before + _WEIGHTS[name] * fraction) / total, name)

        report_progress(0.0)
        return report_progress

    def check() -> None:
        if cancel.is_set():
            raise Cancelled()

    report = Report()
    with tempfile.TemporaryDirectory(dir=session_tmp(), ignore_cleanup_errors=True) as folder:
        tmp = Path(folder)
        working = tmp / f"source.{kind}"
        shutil.copyfile(request.source, working)
        check()

        if kind == "pdf":
            assert info
            document = tmp / "rebuilt.docx"
            if scan:
                convert.ocr_to_docx(
                    working,
                    document,
                    request.source_lang if request.translate else None,
                    cancel,
                    stage("ocr"),
                )
                report.warn("w_ocr", pages=info.pages)
            else:
                convert.pdf_to_docx(working, document, cancel, stage("pdf_to_docx"))
                report.warn("w_pdf_rebuilt")
                if info.scanned:
                    report.warn("w_pages_without_text", count=info.scanned)
            working = document
        check()

        if request.translate:
            engine = translate.translator(request.source_lang, request.target_lang)
            translated = tmp / "translated.docx"
            stats = docx_inplace.translate_docx(
                working, translated, engine, cancel, stage("translate")
            )
            if stats.failed and not stats.translated:
                raise IrisError("internal", "\n".join(stats.errors))
            report.add_translation(stats)
            if len(models.route(request.source_lang, request.target_lang)) > 1:
                report.warn("w_pivot")
            if kind == "pdf" and target == "pdf":
                report.warn("w_pdf_roundtrip")
            working = translated
        check()
        preview = _preview(working)

        if target == "pdf":
            stage("docx_to_pdf")
            exported = tmp / "export.pdf"
            convert.docx_to_pdf(working, exported, cancel)
            pages = convert.pdf_info(exported).pages
            report.counts["pages"] = pages
            if info and pages != info.pages:
                report.warn("w_pages", before=info.pages, after=pages)
            working = exported
        elif info:
            report.counts["pages"] = info.pages
        check()

        save = stage("save")
        stem = Path(request.name or request.source.name).stem
        if request.translate:
            stem = f"{stem}_{request.target_lang}"
        output = save_unique(working, request.out_dir or request.source.parent, stem, target)
        save(1.0)

    return Result(output, report, time.monotonic() - started, preview)
