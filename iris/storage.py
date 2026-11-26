"""Dossier de données, réglages, historique et journal."""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import sys
import threading
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "system",
    "lang": "fr",
    "out_dir": "",  # vide : à côté du fichier source
    "open_after": False,
    "ocr": "auto",
    "max_mb": 100,
}
_CHOICES = {
    "theme": {"light", "dark", "system"},
    "lang": {"fr", "en", "es"},
    "ocr": {"auto", "yes", "no"},
}
HISTORY_LIMIT = 200
_lock = threading.RLock()


def data_dir() -> Path:
    custom = os.environ.get("IRIS_DATA_DIR")
    if custom:
        path = Path(custom)
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Iris"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Iris"
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "iris"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_out_dir() -> Path:
    """Utilisé quand le dossier du fichier source est inconnu (fichier glissé dans le navigateur)."""
    return Path.home() / "Downloads" / "Iris"


def _try_lock(handle: Any) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


_session: tuple[Path, Any] | None = None


def session_tmp() -> Path:
    """Dossier temporaire de ce lancement, verrouillé tant qu'Iris tourne.

    Les dossiers laissés par un lancement interrompu brutalement ne sont plus verrouillés :
    ils sont supprimés au démarrage suivant.
    """
    global _session
    with _lock:
        if _session and _session[0].parent.parent == data_dir():
            _session[0].mkdir(parents=True, exist_ok=True)
            return _session[0]
        close_session()
        root = data_dir() / "tmp"
        root.mkdir(exist_ok=True)
        for old in root.iterdir():
            try:
                with (old / ".lock").open("a+b") as handle:
                    if not _try_lock(handle):
                        continue
            except OSError:
                pass
            shutil.rmtree(old, ignore_errors=True)
        folder = root / uuid.uuid4().hex
        folder.mkdir()
        handle = (folder / ".lock").open("a+b")
        _try_lock(handle)
        _session = (folder, handle)
        return folder


def close_session() -> None:
    global _session
    with _lock:
        if _session:
            folder, handle = _session
            _session = None
            handle.close()
            shutil.rmtree(folder, ignore_errors=True)


atexit.register(close_session)


def setup_logging() -> Path:
    log_file = data_dir() / "iris.log"
    logger = logging.getLogger("iris")
    if not logger.handlers:
        handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return log_file


def _read(name: str, fallback: Any) -> Any:
    try:
        return json.loads((data_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _write(name: str, value: Any) -> None:
    target = data_dir() / name
    tmp = target.with_suffix(".part")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _valid(key: str, value: Any) -> bool:
    if key not in DEFAULT_SETTINGS or type(value) is not type(DEFAULT_SETTINGS[key]):
        return False
    if key in _CHOICES:
        return value in _CHOICES[key]
    if key == "max_mb":
        return 1 <= value <= 2000
    if key == "out_dir":
        return value == "" or Path(value).is_absolute()
    return True


def load_settings() -> dict[str, Any]:
    with _lock:
        saved = _read("settings.json", {})
    if not isinstance(saved, dict):
        saved = {}
    return DEFAULT_SETTINGS | {k: v for k, v in saved.items() if _valid(k, v)}


def save_settings(changes: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        settings = load_settings() | {k: v for k, v in changes.items() if _valid(k, v)}
        _write("settings.json", settings)
    return settings


def load_history() -> list[dict[str, Any]]:
    with _lock:
        items = _read("history.json", [])
    return items if isinstance(items, list) else []


def add_history(entry: dict[str, Any]) -> dict[str, Any]:
    entry = {"id": uuid.uuid4().hex, **entry}
    with _lock:
        _write("history.json", [entry, *load_history()][:HISTORY_LIMIT])
    return entry


def delete_history(entry_id: str) -> None:
    with _lock:
        _write("history.json", [e for e in load_history() if e.get("id") != entry_id])


def clear_history() -> None:
    with _lock:
        _write("history.json", [])
