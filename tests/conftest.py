from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import make_samples  # noqa: E402

from iris import convert, models, storage  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Chaque test a son propre dossier de données ; le vrai n'est jamais touché."""
    real = storage.data_dir()
    monkeypatch.setenv("IRIS_DATA_DIR", str(tmp_path / "data"))
    local_languages = real / "tessdata"
    if local_languages.is_dir():
        monkeypatch.setenv("TESSDATA_PREFIX", str(local_languages))
    yield tmp_path / "data"
    storage.close_session()


@pytest.fixture
def offline(monkeypatch):
    """Toute connexion hors de la machine fait échouer le test."""
    original = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"accès réseau interdit : {address}")
        return original(self, address)

    def no_lookup(host, *args, **kwargs):
        if host not in ("127.0.0.1", "::1", "localhost", None):
            raise AssertionError(f"résolution réseau interdite : {host}")
        return lookup(host, *args, **kwargs)

    lookup = socket.getaddrinfo
    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket, "getaddrinfo", no_lookup)


@pytest.fixture
def sample_docx(tmp_path):
    return make_samples.report_docx(tmp_path / "Rapport_stage.docx")


@pytest.fixture
def sample_pdf(tmp_path):
    return make_samples.text_pdf(tmp_path / "Rapport_texte.pdf")


@pytest.fixture
def scanned_pdf(tmp_path):
    return make_samples.scanned_pdf(tmp_path / "Rapport_scanne.pdf")


needs_models = pytest.mark.skipif(
    len(models.installed()) < 4, reason="modèles Argos absents : python -m iris models install"
)
needs_office = pytest.mark.skipif(not convert.find_soffice(), reason="LibreOffice absent")
needs_ocr = pytest.mark.skipif(
    not {"fra", "eng", "spa"} <= convert.ocr_languages(), reason="Tesseract ou ses langues absents"
)
