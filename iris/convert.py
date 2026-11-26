"""Vérification des fichiers et conversions DOCX <-> PDF (LibreOffice, pdf2docx, Tesseract)."""

from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import Cancelled, IrisError
from .storage import data_dir

Progress = Callable[[float], None]
OCR_LANGS = {"fr": "fra", "en": "eng", "es": "spa"}
MAX_UNZIPPED = 1024**3  # garde-fou contre les archives piégées
_office_lock = threading.Lock()


# ---------------------------------------------------------------- outils système


def _find(env: str, names: list[str], candidates: list[str]) -> str | None:
    if env in os.environ:  # permet de forcer un chemin (ou de simuler une absence)
        value = os.environ[env]
        return value if value and Path(value).is_file() else None
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for candidate in candidates:
        path = Path(os.path.expandvars(candidate)).expanduser()
        if path.is_file():
            return str(path)
    return None


def find_soffice() -> str | None:
    return _find(
        "IRIS_SOFFICE",
        ["soffice", "libreoffice"],
        [
            r"%ProgramFiles%\LibreOffice\program\soffice.exe",
            r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "~/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/usr/bin/soffice",
            "/snap/bin/libreoffice",
        ],
    )


def find_tesseract() -> str | None:
    return _find(
        "IRIS_TESSERACT",
        ["tesseract"],
        [
            r"%ProgramFiles%\Tesseract-OCR\tesseract.exe",
            r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe",
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/usr/bin/tesseract",
        ],
    )


def _use_local_tessdata() -> None:
    """Des fichiers .traineddata déposés dans le dossier d'Iris sont prioritaires."""
    local = data_dir() / "tessdata"
    if any(local.glob("*.traineddata")):
        os.environ["TESSDATA_PREFIX"] = str(local)


def ocr_languages() -> set[str]:
    exe = find_tesseract()
    if not exe:
        return set()
    _use_local_tessdata()
    result = subprocess.run(
        [exe, "--list-langs"], capture_output=True, text=True, timeout=30, **_no_window()
    )
    return {line.strip() for line in result.stdout.splitlines()[1:] if line.strip()}


def _no_window() -> dict:  # type: ignore[type-arg]
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


# ---------------------------------------------------------------- validation


def sniff(path: Path) -> str:
    """Renvoie 'docx' ou 'pdf' après contrôle de l'extension ET du contenu réel."""
    if not path.is_file():
        raise IrisError("not_found", str(path))
    ext = path.suffix.lower().lstrip(".")
    if ext == "doc":
        raise IrisError("old_word")
    if ext not in ("docx", "pdf"):
        raise IrisError("unsupported_type", path.name)
    if path.stat().st_size == 0:
        raise IrisError("empty_file")
    if ext == "pdf":
        with path.open("rb") as handle:
            if b"%PDF-" not in handle.read(1024):
                raise IrisError("bad_content", "en-tête %PDF absent", kind="PDF")
        _open_pdf(path).close()
        return ext
    with path.open("rb") as handle:
        if handle.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # conteneur OLE : chiffré
            raise IrisError("encrypted")
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if sum(info.file_size for info in archive.infolist()) > MAX_UNZIPPED:
                raise IrisError("bad_content", "archive décompressée trop volumineuse", kind="Word")
    except zipfile.BadZipFile as exc:
        raise IrisError("bad_content", str(exc), kind="Word") from exc
    if not {"word/document.xml", "[Content_Types].xml"} <= names:
        raise IrisError("bad_content", "word/document.xml absent", kind="Word")
    return ext


def _open_pdf(path: Path):  # type: ignore[no-untyped-def]
    import pymupdf

    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise IrisError("bad_content", str(exc), kind="PDF") from exc
    if document.needs_pass:
        document.close()
        raise IrisError("encrypted")
    if document.page_count == 0:
        document.close()
        raise IrisError("bad_content", "aucune page", kind="PDF")
    return document


@dataclass
class PdfInfo:
    pages: int
    scanned: int  # pages composées d'images, sans texte
    text: str  # extrait, pour la détection de langue et l'aperçu

    @property
    def is_scan(self) -> bool:
        return self.scanned > self.pages / 2


def pdf_info(path: Path) -> PdfInfo:
    with _open_pdf(path) as document:
        scanned, sample = 0, []
        for page in document:
            text = page.get_text().strip()
            if len(text) < 10 and (page.get_images() or page.get_drawings()):
                scanned += 1
            if sum(map(len, sample)) < 4000:
                sample.append(text)
        return PdfInfo(document.page_count, scanned, "\n".join(sample))


# ---------------------------------------------------------------- processus externes


def _kill_tree(process: subprocess.Popen) -> None:  # type: ignore[type-arg]
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            **_no_window(),
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=30)


def run_process(
    command: list[str],
    cancel: threading.Event,
    timeout: float = 900,
    on_line: Callable[[str], None] | None = None,
) -> str:
    """Lance une commande en surveillant l'annulation ; renvoie la sortie complète."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=sys.platform != "win32",
        **_no_window(),
    )
    lines: list[str] = []

    def drain() -> None:
        assert process.stdout
        for line in process.stdout:
            lines.append(line)
            if on_line:
                on_line(line)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    waited = 0.0
    while process.poll() is None:
        if cancel.wait(0.1):
            _kill_tree(process)
            reader.join(timeout=5)
            raise Cancelled()
        waited += 0.1
        if waited > timeout:
            _kill_tree(process)
            raise IrisError("timeout", "".join(lines[-20:]))
    reader.join(timeout=10)
    output = "".join(lines)
    if process.returncode != 0:
        raise IrisError("convert_failed", f"code {process.returncode}\n{output[-3000:]}")
    return output


# ---------------------------------------------------------------- DOCX -> PDF


def docx_to_pdf(source: Path, target: Path, cancel: threading.Event) -> None:
    soffice = find_soffice()
    if not soffice:
        raise IrisError("no_libreoffice")
    # Un profil dédié évite le conflit avec un LibreOffice déjà ouvert.
    profile = (data_dir() / "libreoffice-profile").resolve().as_uri()
    workdir = target.parent / "pdf-export"
    workdir.mkdir(exist_ok=True)
    with _office_lock:
        output = run_process(
            [
                soffice,
                f"-env:UserInstallation={profile}",
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--convert-to",
                "pdf",
                "--outdir",
                str(workdir),
                str(source),
            ],
            cancel,
        )
    produced = workdir / (source.stem + ".pdf")
    if not produced.is_file():
        raise IrisError("convert_failed", output[-3000:])
    os.replace(produced, target)


# ---------------------------------------------------------------- PDF -> DOCX

_PAGE_LOG = re.compile(r"\((\d+)/(\d+)\) Page")


def pdf_to_docx(source: Path, target: Path, cancel: threading.Event, progress: Progress) -> None:
    """pdf2docx dans un processus séparé : annulable, et sa mémoire est rendue à la fin."""
    state = {"phase": 0, "last": 0}

    def follow(line: str) -> None:
        match = _PAGE_LOG.search(line)
        if match:
            current, total = int(match[1]), int(match[2])
            if current < state["last"]:
                state["phase"] = 1  # analyse terminée, écriture en cours
            state["last"] = current
            progress(min(1.0, (state["phase"] + current / total) / 2))

    env_root = str(Path(__file__).resolve().parent.parent)
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from iris.convert import _pdf2docx; _pdf2docx(sys.argv[2], sys.argv[3])"
    )
    run_process(
        [sys.executable, "-X", "utf8", "-c", code, env_root, str(source), str(target)],
        cancel,
        timeout=1800,
        on_line=follow,
    )
    if not target.is_file():
        raise IrisError("convert_failed", "pdf2docx n'a produit aucun fichier")


def _pdf2docx(source: str, target: str) -> None:
    from pdf2docx import Converter

    converter = Converter(source)
    try:
        converter.convert(target)
    finally:
        converter.close()


# ---------------------------------------------------------------- OCR


def check_ocr(language: str | None) -> str:
    """Vérifie Tesseract et renvoie l'argument de langues à lui passer."""
    if not find_tesseract():
        raise IrisError("no_tesseract")
    installed = ocr_languages()
    wanted = [OCR_LANGS[language]] if language else list(OCR_LANGS.values())
    usable = [code for code in wanted if code in installed]
    if not usable or (language and len(usable) < len(wanted)):
        missing = ", ".join(code for code in wanted if code not in installed)
        raise IrisError("no_ocr_lang", langs=missing, folder=str(data_dir() / "tessdata"))
    return "+".join(usable)


def ocr_to_docx(
    source: Path,
    target: Path,
    language: str | None,
    cancel: threading.Event,
    progress: Progress,
) -> None:
    """Reconnaît le texte d'un scan et reconstruit un document paragraphe par paragraphe."""
    import pymupdf
    import pytesseract
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    from PIL import Image

    langs = check_ocr(language)
    pytesseract.pytesseract.tesseract_cmd = find_tesseract()
    dpi = 300
    scale = 72 / dpi
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Liberation Serif"
    normal.paragraph_format.space_after = Pt(0)
    found_text = False

    with _open_pdf(source) as pdf:
        for index, page in enumerate(pdf):
            if cancel.is_set():
                raise Cancelled()
            pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            try:
                data = pytesseract.image_to_data(
                    image, lang=langs, output_type=pytesseract.Output.DICT, timeout=300
                )
            except RuntimeError as exc:
                raise IrisError("convert_failed", f"Tesseract : {exc}") from exc
            paragraphs = _group_words(data)
            width, height = page.rect.width, page.rect.height

            section = (
                document.sections[0] if index == 0 else document.add_section(WD_SECTION.NEW_PAGE)
            )
            section.page_width, section.page_height = Pt(width), Pt(height)
            lefts = [p["left"] * scale for p in paragraphs] or [72]
            rights = [width - p["right"] * scale for p in paragraphs] or [72]
            tops = [p["top"] * scale for p in paragraphs] or [72]
            margin_left = max(28, min(min(lefts), 90))
            margin_right = max(28, min(min(rights), margin_left))
            section.left_margin, section.right_margin = Pt(margin_left), Pt(margin_right)
            section.top_margin = Pt(max(28, min(min(tops), 90)))
            section.bottom_margin = Pt(28)

            previous_bottom = section.top_margin.pt
            for block in paragraphs:
                found_text = True
                size = max(7.0, min(36.0, round(block["height"] * scale * 2) / 2))
                paragraph = document.add_paragraph()
                paragraph.add_run(block["text"]).font.size = Pt(size)
                fmt = paragraph.paragraph_format
                gap = block["top"] * scale - previous_bottom
                fmt.space_before = Pt(max(0.0, min(gap * 0.8, 120.0)))
                left = block["left"] * scale
                right = width - block["right"] * scale
                if block["lines"] == 1 and abs(left - right) < 20 and left > width * 0.2:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                else:
                    fmt.left_indent = Pt(max(0.0, left - margin_left))
                previous_bottom = block["bottom"] * scale
            progress((index + 1) / pdf.page_count)

    if not found_text:
        raise IrisError("no_text")
    document.save(str(target))


def _group_words(data: dict) -> list[dict]:  # type: ignore[type-arg]
    """Regroupe les mots de Tesseract en paragraphes avec leur position."""
    blocks: dict[tuple[int, int], dict[int, list[int]]] = {}
    for i, word in enumerate(data["text"]):
        if word.strip() and float(data["conf"][i]) >= 30:
            key = (data["block_num"][i], data["par_num"][i])
            blocks.setdefault(key, {}).setdefault(data["line_num"][i], []).append(i)
    result = []
    for lines in blocks.values():
        text = ""
        heights = []
        for line in lines.values():
            chunk = " ".join(data["text"][i] for i in line)
            if text.endswith("-") and chunk[:1].islower():
                text = text[:-1] + chunk  # mot coupé en fin de ligne
            else:
                text = f"{text} {chunk}".strip()
            top = min(data["top"][i] for i in line)
            heights.append(max(data["top"][i] + data["height"][i] for i in line) - top)
        words = [i for line in lines.values() for i in line]
        result.append(
            {
                "text": text,
                "lines": len(lines),
                "height": statistics.median(heights),
                "left": min(data["left"][i] for i in words),
                "right": max(data["left"][i] + data["width"][i] for i in words),
                "top": min(data["top"][i] for i in words),
                "bottom": max(data["top"][i] + data["height"][i] for i in words),
            }
        )
    return sorted(result, key=lambda b: (b["top"], b["left"]))
