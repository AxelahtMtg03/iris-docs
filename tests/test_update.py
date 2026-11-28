"""Mises à jour : comparaison des versions, réglage, installation et pannes réseau."""

import io
import urllib.error
import zipfile

import pytest

from iris import __version__, server, storage, update
from iris.errors import IrisError

HEADERS = {"X-Iris-Token": "jeton"}


@pytest.fixture
def client():
    app = server.create_app(token="jeton")
    yield app.test_client()
    app.config["JOBS"].shutdown()


def publish(monkeypatch, text):
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(text.encode()))


@pytest.mark.parametrize(
    ("published", "available"),
    [("99.0.0", True), (__version__, False), ("0.9.0", False)],
)
def test_only_a_newer_version_is_offered(monkeypatch, published, available):
    publish(monkeypatch, f'"""Iris."""\n__version__ = "{published}"\n')
    assert update.check()["available"] is available


def test_versions_compare_as_numbers():
    assert update._numbers("1.10.0") > update._numbers("1.9.0")


@pytest.mark.parametrize("answer", ["", "<html>404</html>", '__version__ = "abc"'])
def test_unreadable_answer_offers_nothing(monkeypatch, answer):
    publish(monkeypatch, answer)
    assert update.check()["available"] is False


def test_offline_offers_nothing(monkeypatch):
    def unreachable(*args, **kwargs):
        raise urllib.error.URLError("hors-ligne")

    monkeypatch.setattr(update.urllib.request, "urlopen", unreachable)
    assert update.check()["available"] is False


def test_disabled_check_never_uses_the_network(client, offline):
    storage.save_settings({"check_updates": False})
    assert client.get("/api/update", headers=HEADERS).get_json() == {"available": False}


def test_a_code_folder_is_never_replaced(client):
    answer = client.post("/api/update", headers=HEADERS)
    assert answer.status_code == 400


@pytest.fixture
def installed(monkeypatch):
    """Fait comme si Iris tournait depuis son dossier d'installation ; rien n'est lancé."""
    launched = []
    monkeypatch.setattr(update, "can_install", lambda: True)
    monkeypatch.setattr(update.subprocess, "Popen", lambda *a, **k: launched.append((a, k)))
    return launched


def archive(monkeypatch, names):
    def fake(target):
        with zipfile.ZipFile(target, "w") as out:
            for name in names:
                out.writestr(name, "contenu")

    monkeypatch.setattr(update, "_download", fake)


def test_update_extracts_and_launches_the_installer(client, installed, monkeypatch):
    archive(monkeypatch, ["iris-docs-main/Installer.bat", "iris-docs-main/installer.py"])
    assert client.post("/api/update", headers=HEADERS).get_json() == {"ok": True}
    [(args, options)] = installed
    assert args[0] == ["cmd", "/c", ".\\Installer.bat"]
    assert (options["cwd"] / "installer.py").is_file()
    assert options["env"]["IRIS_UPDATE"] == "1"
    assert options["env"]["IRIS_WAIT_PID"].isdigit()


@pytest.mark.parametrize("names", [["iris-docs-main/README.md"], []])
def test_archive_without_installer_is_refused(installed, monkeypatch, names):
    archive(monkeypatch, names)
    with pytest.raises(IrisError) as error:
        update.start()
    assert error.value.code == "update_failed"
    assert not installed


def test_broken_download_is_reported(installed, monkeypatch):
    monkeypatch.setattr(update, "_download", lambda target: target.write_bytes(b"pas un zip"))
    with pytest.raises(IrisError) as error:
        update.start()
    assert error.value.code == "update_failed"
    assert not installed
