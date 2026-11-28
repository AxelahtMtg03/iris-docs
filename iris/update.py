"""Mises à jour : lit le numéro de version publié et relance l'installateur à la demande.

Rien n'est envoyé. La vérification se désactive dans les réglages et rien ne s'installe
sans un clic.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from . import __version__, storage
from .errors import IrisError

log = logging.getLogger("iris")
REPOSITORY = "https://github.com/AxelahtMtg03/iris-docs"
VERSION_URL = "https://raw.githubusercontent.com/AxelahtMtg03/iris-docs/main/iris/__init__.py"
ARCHIVE_URL = f"{REPOSITORY}/archive/refs/heads/main.zip"
ROOT = Path(__file__).resolve().parent.parent
# Là où l'installateur Windows pose l'application.
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "Iris"
_VERSION = re.compile(r'^__version__ = "(\d+(?:\.\d+)*)"', re.M)


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def latest_version() -> str | None:
    """Version publiée, ou None si elle est illisible (hors-ligne, par exemple)."""
    try:
        with urllib.request.urlopen(VERSION_URL, timeout=5) as response:
            found = _VERSION.search(response.read(10_000).decode("utf-8", "replace"))
    except OSError as exc:
        log.info("Vérification de mise à jour impossible : %s", exc)
        return None
    return found.group(1) if found else None


def can_install() -> bool:
    """Seule la copie installée se remplace ; un dossier de code se met à jour avec Git."""
    return sys.platform == "win32" and INSTALL_DIR.resolve() == ROOT


def check() -> dict[str, Any]:
    latest = latest_version()
    return {
        "available": bool(latest) and _numbers(latest) > _numbers(__version__),
        "latest": latest,
        "can_install": can_install(),
        "url": REPOSITORY,
    }


def _download(target: Path) -> None:
    with urllib.request.urlopen(ARCHIVE_URL, timeout=30) as response, open(target, "wb") as out:
        shutil.copyfileobj(response, out)


def start() -> None:
    """Télécharge la dernière version et lance son installateur, qui attend la fermeture d'Iris."""
    if not can_install():
        raise IrisError("bad_request", "mise à jour réservée à l'application installée")
    folder = storage.data_dir() / "update"
    try:
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        _download(folder / "iris.zip")
        with zipfile.ZipFile(folder / "iris.zip") as archive:
            archive.extractall(folder)
        installer = next(folder.glob("*/Installer.bat"), None)
        if installer is None:
            raise IrisError("update_failed", "installateur absent de l'archive")
        # Chemin relatif : aucun problème de guillemets avec le nom du dossier utilisateur.
        subprocess.Popen(
            ["cmd", "/c", ".\\Installer.bat"],
            cwd=installer.parent,
            env=os.environ | {"IRIS_UPDATE": "1", "IRIS_WAIT_PID": str(os.getpid())},
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except (OSError, zipfile.BadZipFile) as exc:
        raise IrisError("update_failed", f"{type(exc).__name__}: {exc}") from exc
