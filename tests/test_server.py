import io
import time

import pytest
from conftest import needs_models

from iris import errors, server, storage, system

TOKEN = "jeton-de-test"
HEADERS = {"X-Iris-Token": TOKEN}


def no_dialog(kind):
    raise system.NoDialog()


@pytest.fixture
def app(tmp_path):
    storage.save_settings({"out_dir": str(tmp_path / "sortie")})
    app = server.create_app(token=TOKEN, picker=no_dialog)
    yield app
    app.config["JOBS"].shutdown()


@pytest.fixture
def client(app):
    return app.test_client()


def upload(client, path, name=None):
    data = {"file": (io.BytesIO(path.read_bytes()), name or path.name)}
    return client.post("/api/files", data=data, headers=HEADERS)


def wait(client, job):
    for _ in range(600):
        job = client.get(f"/api/jobs/{job['id']}", headers=HEADERS).get_json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.1)
    raise AssertionError("tâche trop longue")


@pytest.mark.parametrize("headers", [{}, {"X-Iris-Token": "faux"}])
def test_api_needs_token(client, headers):
    response = client.get("/api/state", headers=headers)
    assert response.status_code == 401


def test_foreign_host_is_refused(client):
    response = client.get("/", headers={"Host": "exemple.com"})
    assert response.status_code == 403


def test_pages_and_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert TOKEN.encode() not in response.data
    assert client.get("/../server.py").status_code in (400, 404)
    assert client.get("/%2e%2e/server.py").status_code in (400, 404)


def test_state_and_settings(client):
    state = client.get("/api/state", headers=HEADERS).get_json()
    assert {"settings", "tools", "models"} <= set(state)
    saved = client.put(
        "/api/settings",
        json={"theme": "light", "lang": "de", "max_mb": 0, "inconnu": 1},
        headers=HEADERS,
    ).get_json()
    assert saved["theme"] == "light" and saved["lang"] == "fr" and saved["max_mb"] == 100


@pytest.mark.parametrize(
    "name, content, code",
    [("a.exe", b"MZ", "unsupported_type"), ("a.pdf", b"<html>", "bad_content")],
)
def test_upload_rejects(client, name, content, code):
    response = client.post(
        "/api/files", data={"file": (io.BytesIO(content), name)}, headers=HEADERS
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == code
    assert not list((storage.session_tmp() / "uploads").iterdir())


def test_upload_size_limit(client):
    storage.save_settings({"max_mb": 1})
    big = io.BytesIO(b"%PDF-" + b"0" * (3 * 1024 * 1024))
    response = client.post("/api/files", data={"file": (big, "gros.pdf")}, headers=HEADERS)
    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "too_big"


def test_errors_follow_interface_language(client):
    headers = HEADERS | {"X-Iris-Lang": "es"}
    response = client.post("/api/jobs", json={"file_id": "x"}, headers=headers)
    assert response.get_json()["error"]["message"] == errors.message("not_found", "es")


@pytest.mark.parametrize(
    "given, expected",
    [
        ("../../etc/passwd.docx", "passwd.docx"),
        ("C:\\x\\Été 2024.docx", "Été 2024.docx"),
        ('a<b>:"c".pdf', "abc.pdf"),
        ("con.docx", "_con.docx"),
        ("...", "document"),
    ],
)
def test_safe_name(given, expected):
    assert server.safe_name(given) == expected


def test_pick_falls_back_to_browser(client):
    answer = client.post("/api/pick", json={"kind": "docx"}, headers=HEADERS).get_json()
    assert answer == {"unavailable": True}


@needs_models
def test_full_flow(client, sample_docx, tmp_path):
    described = upload(client, sample_docx).get_json()
    assert described["detected"] == "fr"
    assert described["preview"]["title"] == "Rapport de stage"
    body = {"file_id": described["id"], "target_format": "docx", "translate": True}
    job = wait(client, client.post("/api/jobs", json=body, headers=HEADERS).get_json())
    assert job["status"] == "done", job
    assert job["result"]["name"] == "Rapport_stage_en.docx"
    assert (tmp_path / "sortie" / "Rapport_stage_en.docx").is_file()
    download = client.get(f"/api/jobs/{job['id']}/download", headers=HEADERS)
    assert download.data[:2] == b"PK"
    download.close()
    history = client.get("/api/history", headers=HEADERS).get_json()
    assert history[0]["exists"] and history[0]["target_lang"] == "en"
    client.delete(f"/api/history/{history[0]['id']}", headers=HEADERS)
    assert client.get("/api/history", headers=HEADERS).get_json() == []


@needs_models
def test_cancel_then_restart(client, sample_docx):
    described = upload(client, sample_docx).get_json()
    body = {"file_id": described["id"], "target_format": "docx", "translate": True}
    job = client.post("/api/jobs", json=body, headers=HEADERS).get_json()
    client.post(f"/api/jobs/{job['id']}/cancel", headers=HEADERS)
    assert wait(client, job)["status"] == "cancelled"
    again = wait(client, client.post("/api/jobs", json=body, headers=HEADERS).get_json())
    assert again["status"] == "done"


def test_stale_temp_folders_are_removed(isolated_data):
    stale = isolated_data / "tmp" / "ancien"
    stale.mkdir(parents=True)
    (stale / "reste.docx").write_text("x")
    current = storage.session_tmp()
    assert current.is_dir() and not stale.exists()
    storage.close_session()
    assert not current.exists()
