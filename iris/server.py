"""Serveur local d'Iris : interface web et API, accessibles depuis cet ordinateur seulement."""

from __future__ import annotations

import hmac
import logging
import secrets
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from . import __version__, convert, docx_inplace, models, pipeline, storage, system, translate
from .errors import IrisError, message
from .jobs import Job, JobManager

log = logging.getLogger("iris")
PACKAGE = Path(__file__).resolve().parent
WEB = PACKAGE / "web"
SITE = PACKAGE.parent / "site"
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


@dataclass
class Source:
    id: str
    path: Path
    name: str
    ext: str
    uploaded: bool  # copie temporaire : le dossier d'origine est inconnu


def safe_name(name: str) -> str:
    """Nom de fichier utilisable partout, accents conservés."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"/\\|?*').strip(". ")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return name[:120] or "document"
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10))}
    reserved |= {f"lpt{i}" for i in range(10)}
    stem = stem[:120] or "document"
    if stem.lower() in reserved:
        stem = f"_{stem}"
    return f"{stem}.{ext}"


def _excerpt(path: Path, ext: str) -> tuple[str, str, str]:
    if ext == "docx":
        return docx_inplace.excerpt(path)
    text = convert.pdf_info(path).text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else ""
    return title[:80], " ".join(lines[1:])[:220], text


def create_app(
    token: str | None = None,
    jobs: JobManager | None = None,
    picker: Callable[[str], str | None] = system.pick_with_tk,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False  # l'ordre du rapport est voulu
    app.config["TOKEN"] = token or secrets.token_urlsafe(32)
    manager = app.config["JOBS"] = jobs or JobManager()
    sources: dict[str, Source] = {}
    outputs: dict[str, dict[str, Any]] = {}  # résultats par tâche
    dialog_lock = threading.Lock()
    storage.setup_logging()

    def lang() -> str:
        wanted = request.headers.get("X-Iris-Lang", "")
        return wanted if wanted in ("fr", "en", "es") else storage.load_settings()["lang"]

    def failure(error: IrisError, status: int = 400):  # type: ignore[no-untyped-def]
        body = {
            "code": error.code,
            "message": message(error.code, lang(), **error.params),
            "detail": error.detail,
        }
        return jsonify(error=body), status

    @app.before_request
    def guard():  # type: ignore[no-untyped-def]
        if request.host.rsplit(":", 1)[0] not in LOCAL_HOSTS:
            return failure(IrisError("unauthorized", "hôte refusé"), 403)
        if request.path.startswith("/api/"):
            given = request.headers.get("X-Iris-Token", "")
            if not hmac.compare_digest(given.encode(), app.config["TOKEN"].encode()):
                return failure(IrisError("unauthorized"), 401)
            limit = storage.load_settings()["max_mb"]
            request.max_content_length = limit * 1024 * 1024 + 64 * 1024
        return None

    @app.after_request
    def harden(response):  # type: ignore[no-untyped-def]
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = (
            "no-store" if request.path.startswith("/api/") else ("no-cache")
        )
        return response

    @app.errorhandler(IrisError)
    def on_iris_error(error: IrisError):  # type: ignore[no-untyped-def]
        log.warning("%s %s", error.code, error.detail)
        return failure(error)

    @app.errorhandler(RequestEntityTooLarge)
    def on_too_big(_: Exception):  # type: ignore[no-untyped-def]
        return failure(IrisError("too_big", max=storage.load_settings()["max_mb"]), 413)

    @app.errorhandler(Exception)
    def on_error(error: Exception):  # type: ignore[no-untyped-def]
        if isinstance(error, HTTPException):
            return failure(IrisError("bad_request", str(error)), error.code or 400)
        log.exception("Erreur serveur")
        return failure(IrisError("internal", f"{type(error).__name__}: {error}"), 500)

    # ------------------------------------------------------------ pages

    @app.get("/")
    def index():  # type: ignore[no-untyped-def]
        return send_from_directory(WEB, "index.html")

    @app.get("/vitrine/")
    @app.get("/vitrine/<path:name>")
    def showcase(name: str = "index.html"):  # type: ignore[no-untyped-def]
        return send_from_directory(SITE, name)

    @app.get("/<path:name>")
    def assets(name: str):  # type: ignore[no-untyped-def]
        return send_from_directory(WEB, name)

    # ------------------------------------------------------------ état et réglages

    def tools() -> dict[str, Any]:
        return {
            "libreoffice": bool(convert.find_soffice()),
            "tesseract": bool(convert.find_tesseract()),
        }

    @app.get("/api/state")
    def state():  # type: ignore[no-untyped-def]
        return jsonify(
            version=__version__,
            settings=storage.load_settings(),
            tools=tools(),
            models=models.overview(),
            default_out_dir=str(storage.default_out_dir()),
            log_file=str(storage.data_dir() / "iris.log"),
            downloads=[j.to_dict(lang()) for j in manager.active("model")],
        )

    @app.put("/api/settings")
    def settings():  # type: ignore[no-untyped-def]
        changes = request.get_json(silent=True)
        if not isinstance(changes, dict):
            raise IrisError("bad_request")
        return jsonify(storage.save_settings(changes))

    # ------------------------------------------------------------ fichiers

    def own_folder(source: Source) -> Path:
        return storage.default_out_dir() if source.uploaded else source.path.parent

    def describe(source: Source) -> dict[str, Any]:
        title, body, sample = _excerpt(source.path, source.ext)
        info = convert.pdf_info(source.path) if source.ext == "pdf" else None
        return {
            "id": source.id,
            "name": source.name,
            "ext": source.ext,
            "size": source.path.stat().st_size,
            # dossier de sortie quand les réglages n'en imposent pas
            "source_dir": str(own_folder(source)),
            "uploaded": source.uploaded,
            "detected": translate.detect(sample),
            "preview": {"title": title, "body": body},
            "scan": bool(info and info.is_scan),
            "pages": info.pages if info else None,
        }

    def register(path: Path, name: str, uploaded: bool) -> dict[str, Any]:
        limit = storage.load_settings()["max_mb"]
        if path.is_file() and path.stat().st_size > limit * 1024 * 1024:
            raise IrisError("too_big", max=limit)
        ext = convert.sniff(path)
        source = Source(uuid.uuid4().hex, path, name, ext, uploaded)
        try:
            described = describe(source)
        except IrisError:
            raise
        except Exception as exc:  # fichier à la structure illisible
            kind = "PDF" if ext == "pdf" else "Word"
            raise IrisError("bad_content", f"{type(exc).__name__}: {exc}", kind=kind) from exc
        sources[source.id] = source
        return described

    @app.post("/api/files")
    def upload():  # type: ignore[no-untyped-def]
        sent = request.files.get("file")
        if not sent or not sent.filename:
            raise IrisError("bad_request", "aucun fichier")
        name = safe_name(sent.filename)
        folder = storage.session_tmp() / "uploads" / uuid.uuid4().hex
        folder.mkdir(parents=True)
        try:
            sent.save(folder / name)
            return jsonify(register(folder / name, name, uploaded=True))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def ask(kind: str) -> tuple[bool, str | None]:
        if not dialog_lock.acquire(blocking=False):
            return True, None
        try:
            return True, picker(kind)
        except system.NoDialog:
            return False, None
        finally:
            dialog_lock.release()

    @app.post("/api/pick")
    def pick():  # type: ignore[no-untyped-def]
        kind = (request.get_json(silent=True) or {}).get("kind", "any")
        if kind not in (*system.FILE_TYPES, "folder"):
            raise IrisError("bad_request", f"type {kind}")
        available, chosen = ask(kind)
        if not available:
            return jsonify(unavailable=True)
        if not chosen:
            return jsonify(cancelled=True)
        if kind == "folder":
            return jsonify(folder=str(Path(chosen)))
        path = Path(chosen)
        return jsonify(file=register(path, path.name, uploaded=False))

    @app.delete("/api/files/<file_id>")
    def forget(file_id: str):  # type: ignore[no-untyped-def]
        source = sources.pop(file_id, None)
        busy = bool(manager.active("document"))
        if source and source.uploaded and not busy:
            shutil.rmtree(source.path.parent, ignore_errors=True)
        return jsonify(ok=True)

    # ------------------------------------------------------------ tâches

    def job_or_404(job_id: str) -> Job:
        job = manager.get(job_id)
        if not job:
            raise IrisError("not_found", f"tâche {job_id}")
        return job

    def job_dict(job: Job) -> dict[str, Any]:
        data = job.to_dict(lang())
        result = outputs.get(job.id)
        if job.status == "done" and result:
            data["result"] = {**result, "report": result["report"].localized(lang())}
        return data

    @app.post("/api/jobs")
    def start():  # type: ignore[no-untyped-def]
        body = request.get_json(silent=True) or {}
        source = sources.get(str(body.get("file_id")))
        if not source:
            raise IrisError("not_found", "fichier non déposé")
        options = storage.load_settings()
        folder = options["out_dir"] or own_folder(source)
        demand = pipeline.Request(
            source=source.path,
            name=source.name,
            target_format=str(body.get("target_format")),
            translate=body.get("translate") is True,
            source_lang=str(body.get("source_lang", "fr")),
            target_lang=str(body.get("target_lang", "en")),
            out_dir=Path(folder),
            ocr=options["ocr"],
        )

        def work(job: Job) -> None:
            result = pipeline.run(demand, job.update, job.cancel)
            try:
                title, text, _ = _excerpt(result.output, demand.target_format)
            except Exception:  # l'aperçu est un bonus, le fichier est déjà là
                log.exception("Aperçu impossible")
                title, text = "", ""
            storage.add_history(
                {
                    "name": result.output.name,
                    "path": str(result.output),
                    "date": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "from": source.ext,
                    "to": demand.target_format,
                    "source_lang": demand.source_lang if demand.translate else None,
                    "target_lang": demand.target_lang if demand.translate else None,
                    "duration": round(result.duration, 1),
                }
            )
            outputs[job.id] = {
                "name": result.output.name,
                "path": str(result.output),
                "duration": round(result.duration, 1),
                "preview": {"title": title, "body": text},
                "report": result.report,
            }
            if storage.load_settings()["open_after"]:
                try:
                    system.reveal(result.output)
                except (IrisError, OSError):
                    log.exception("Ouverture du dossier impossible")

        job = manager.submit("document", work, label=source.name)
        return jsonify(job_dict(job)), 202

    @app.get("/api/jobs/<job_id>")
    def status(job_id: str):  # type: ignore[no-untyped-def]
        return jsonify(job_dict(job_or_404(job_id)))

    @app.post("/api/jobs/<job_id>/cancel")
    def cancel(job_id: str):  # type: ignore[no-untyped-def]
        job = job_or_404(job_id)
        job.cancel.set()
        return jsonify(job_dict(job))

    def output_of(job_id: str) -> Path:
        result = outputs.get(job_id)
        if not result or not Path(result["path"]).is_file():
            raise IrisError("not_found", "résultat absent")
        return Path(result["path"])

    @app.get("/api/jobs/<job_id>/download")
    def download(job_id: str):  # type: ignore[no-untyped-def]
        path = output_of(job_id)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.post("/api/jobs/<job_id>/reveal")
    def reveal_result(job_id: str):  # type: ignore[no-untyped-def]
        system.reveal(output_of(job_id))
        return jsonify(ok=True)

    # ------------------------------------------------------------ historique

    @app.get("/api/history")
    def history():  # type: ignore[no-untyped-def]
        items = [{**e, "exists": Path(e["path"]).is_file()} for e in storage.load_history()]
        return jsonify(items)

    @app.delete("/api/history")
    def empty_history():  # type: ignore[no-untyped-def]
        storage.clear_history()
        return jsonify(ok=True)

    @app.delete("/api/history/<entry_id>")
    def drop_history(entry_id: str):  # type: ignore[no-untyped-def]
        storage.delete_history(entry_id)
        return jsonify(ok=True)

    @app.post("/api/history/<entry_id>/reveal")
    def reveal_history(entry_id: str):  # type: ignore[no-untyped-def]
        entry = next((e for e in storage.load_history() if e["id"] == entry_id), None)
        if not entry:
            raise IrisError("not_found")
        system.reveal(Path(entry["path"]))
        return jsonify(ok=True)

    # ------------------------------------------------------------ modèles de langue

    @app.get("/api/models")
    def list_models():  # type: ignore[no-untyped-def]
        return jsonify(models.overview())

    @app.post("/api/models/<pair>")
    def install_model(pair: str):  # type: ignore[no-untyped-def]
        if pair not in models.PAIRS:
            raise IrisError("bad_request", f"paire inconnue : {pair}")
        for job in manager.active("model"):
            if job.label == pair:
                return jsonify(job.to_dict(lang())), 202
        job = manager.submit(
            "model", lambda j: models.install(pair, j.cancel, j.update), label=pair
        )
        return jsonify(job.to_dict(lang())), 202

    @app.delete("/api/models/<pair>")
    def remove_model(pair: str):  # type: ignore[no-untyped-def]
        if manager.active("document") or manager.active("model"):
            raise IrisError("busy")
        models.uninstall(pair)
        return jsonify(models.overview())

    return app
