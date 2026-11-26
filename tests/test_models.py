import json
import threading
import zipfile

import pytest

from iris import models
from iris.errors import Cancelled, IrisError


class Package:
    def __init__(self, source, target):
        self.links = [f"https://example.invalid/{source}_{target}.argosmodel"]
        self.from_code, self.to_code = source, target


@pytest.fixture
def argos(tmp_path, monkeypatch):
    """Dossier de modèles vide, catalogue et téléchargement simulés : aucun accès réseau."""
    argostranslate = models._argos()
    from argostranslate import settings

    folder = tmp_path / "packages"
    folder.mkdir()
    monkeypatch.setattr(settings, "package_data_dir", folder)
    monkeypatch.setattr(settings, "package_dirs", [folder])
    catalogue = [Package(a, b) for pair in models.PAIRS.values() for a, b in pair]
    monkeypatch.setattr(argostranslate.package, "update_package_index", lambda: None)
    monkeypatch.setattr(argostranslate.package, "get_available_packages", lambda: catalogue)

    def fake_download(url, target, cancel, progress):
        if cancel.is_set():
            raise Cancelled()
        source, destination = url.rsplit("/", 1)[1].split(".")[0].split("_")
        metadata = {"from_code": source, "to_code": destination, "type": "translate"}
        with zipfile.ZipFile(target, "w") as archive:
            root = f"translate-{source}_{destination}"
            archive.writestr(f"{root}/metadata.json", json.dumps(metadata))
            archive.writestr(f"{root}/sentencepiece.model", b"x")
        progress(1.0)

    monkeypatch.setattr(models, "_download", fake_download)
    yield argostranslate
    models._reset()


def test_install_then_uninstall(argos):
    seen = []
    models.install("fr-en", progress=seen.append)
    assert seen == sorted(seen) and seen[-1] == 1.0
    assert [p["installed"] for p in models.overview()] == [True, False]
    models.uninstall("fr-en")
    assert not models.installed()


def test_missing_model_is_explained(argos):
    with pytest.raises(IrisError) as error:
        models.require("fr", "es")
    assert error.value.code == "no_model"
    assert "FR → EN" in str(error.value) and "EN → ES" in str(error.value)


def test_cancelled_install(argos):
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        models.install("en-es", event)
    assert not models.installed()


def test_network_failure(argos, monkeypatch):
    def broken(*args):
        raise OSError("réseau coupé")

    monkeypatch.setattr(models, "_download", broken)
    with pytest.raises(IrisError) as error:
        models.install("fr-en")
    assert error.value.code == "model_download"
