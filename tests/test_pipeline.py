import threading

import pytest
from conftest import needs_models, needs_ocr, needs_office
from docx import Document

from iris import convert, pipeline, storage
from iris.errors import Cancelled, IrisError


def leftovers():
    """Fichiers restés dans le dossier temporaire de la session (verrou excepté)."""
    return [p for p in storage.session_tmp().iterdir() if p.name != ".lock"]


def request(source, target, tmp_path, **options):
    return pipeline.Request(source, target, out_dir=tmp_path / "out", **options)


@pytest.mark.parametrize(
    "name, content, code",
    [
        ("a.txt", b"bonjour", "unsupported_type"),
        ("a.doc", b"x", "old_word"),
        ("a.pdf", b"pas un pdf", "bad_content"),
        ("a.docx", b"pas un zip", "bad_content"),
        ("a.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1xxxx", "encrypted"),
        ("a.pdf", b"", "empty_file"),
    ],
)
def test_rejects_bad_files(tmp_path, name, content, code):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(IrisError) as error:
        convert.sniff(path)
    assert error.value.code == code


def test_nothing_to_do(sample_docx, tmp_path):
    with pytest.raises(IrisError) as error:
        pipeline.run(request(sample_docx, "docx", tmp_path))
    assert error.value.code == "nothing_to_do"


def test_missing_tools_are_explained(sample_docx, scanned_pdf, tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_SOFFICE", "")
    monkeypatch.setenv("IRIS_TESSERACT", "")
    for source, target, code in [
        (sample_docx, "pdf", "no_libreoffice"),
        (scanned_pdf, "docx", "no_tesseract"),
    ]:
        with pytest.raises(IrisError) as error:
            pipeline.run(request(source, target, tmp_path))
        assert error.value.code == code
        assert "winget" in str(error.value)


def test_never_overwrites(tmp_path):
    produced = tmp_path / "p"
    produced.write_text("neuf")
    (tmp_path / "Nom.docx").write_text("ancien")
    first = pipeline.save_unique(produced, tmp_path, "Nom", "docx")
    second = pipeline.save_unique(produced, tmp_path, "Nom", "docx")
    assert (first.name, second.name) == ("Nom_1.docx", "Nom_2.docx")
    assert (tmp_path / "Nom.docx").read_text() == "ancien"


@needs_models
@pytest.mark.parametrize("target", ["en", "es"])
def test_translate_keeping_word(offline, sample_docx, tmp_path, target):
    seen = []
    result = pipeline.run(
        request(sample_docx, "docx", tmp_path, translate=True, target_lang=target),
        lambda fraction, stage: seen.append(fraction),
    )
    assert result.output.name == f"Rapport_stage_{target}.docx"
    assert seen == sorted(seen) and seen[-1] == 1.0 and len(seen) > 10
    assert result.report.counts["tables"] == 2
    text = "\n".join(p.text for p in Document(result.output).paragraphs)
    assert "Rapport de stage" not in text
    assert "contact@example.org" in text and "https://example.org/aide" in text
    assert "pip install -r requirements.txt" in text
    codes = [w["code"] for w in result.report.warnings]
    assert ("w_pivot" in codes) == (target == "es")
    assert not leftovers()


@needs_models
def test_cancel_leaves_nothing(sample_docx, tmp_path):
    event = threading.Event()

    def progress(fraction, stage):
        if stage == "translate" and fraction > 0.2:
            event.set()

    with pytest.raises(Cancelled):
        pipeline.run(request(sample_docx, "docx", tmp_path, translate=True), progress, event)
    assert not (tmp_path / "out").exists()
    assert not leftovers()
    # et on peut recommencer aussitôt
    assert pipeline.run(request(sample_docx, "docx", tmp_path, translate=True)).output.is_file()


@needs_office
def test_docx_to_pdf(sample_docx, tmp_path):
    result = pipeline.run(request(sample_docx, "pdf", tmp_path))
    info = convert.pdf_info(result.output)
    assert result.output.name == "Rapport_stage.pdf"
    assert "Rapport de stage" in info.text
    assert not leftovers()


def test_pdf_to_docx(sample_pdf, tmp_path):
    result = pipeline.run(request(sample_pdf, "docx", tmp_path))
    text = " ".join(p.text for p in Document(result.output).paragraphs)
    assert "Rapport de stage" in text and "entreprise" in text
    assert [w["code"] for w in result.report.warnings] == ["w_pdf_rebuilt"]
    assert not leftovers()


def test_cancel_external_process(sample_pdf, tmp_path):
    event = threading.Event()
    threading.Timer(0.2, event.set).start()
    with pytest.raises(Cancelled):
        pipeline.run(request(sample_pdf, "docx", tmp_path), cancel=event)
    assert not leftovers()


def test_scan_detection(sample_pdf, scanned_pdf, tmp_path):
    assert convert.pdf_info(scanned_pdf).is_scan
    assert not convert.pdf_info(sample_pdf).is_scan
    with pytest.raises(IrisError) as error:
        pipeline.run(request(scanned_pdf, "docx", tmp_path, ocr="no"))
    assert error.value.code == "scan_without_ocr"


@needs_ocr
@needs_models
def test_scanned_pdf_is_read_and_translated(offline, scanned_pdf, tmp_path):
    result = pipeline.run(request(scanned_pdf, "docx", tmp_path, translate=True))
    text = " ".join(p.text for p in Document(result.output).paragraphs).lower()
    assert "internship" in text and "company" in text
    assert "w_ocr" in [w["code"] for w in result.report.warnings]


@needs_office
@needs_models
def test_pdf_to_translated_pdf(offline, sample_pdf, tmp_path):
    result = pipeline.run(request(sample_pdf, "pdf", tmp_path, translate=True, target_lang="es"))
    assert "empresa" in convert.pdf_info(result.output).text.lower()
    assert "w_pdf_roundtrip" in [w["code"] for w in result.report.warnings]
