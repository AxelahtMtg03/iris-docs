"""Paquets de langue Argos : liste, installation (seul accès réseau d'Iris) et suppression."""

from __future__ import annotations

import logging
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import LANGS
from .errors import Cancelled, IrisError

log = logging.getLogger("iris")
# L'anglais est la langue pivot : FR <-> ES passe par lui.
PAIRS: dict[str, list[tuple[str, str]]] = {
    "fr-en": [("fr", "en"), ("en", "fr")],
    "en-es": [("en", "es"), ("es", "en")],
}


def _argos():  # type: ignore[no-untyped-def]
    from .translate import load_argos

    return load_argos()


def installed() -> dict[tuple[str, str], Any]:
    return {(p.from_code, p.to_code): p for p in _argos().package.get_installed_packages()}


def route(source: str, target: str) -> list[tuple[str, str]]:
    """Étapes de traduction : directe si un modèle existe, sinon via l'anglais."""
    if source not in LANGS or target not in LANGS:
        raise IrisError("bad_request", f"langues {source} -> {target}")
    if source == target:
        raise IrisError("same_language")
    if "en" in (source, target) or (source, target) in installed():
        return [(source, target)]
    return [(source, "en"), ("en", target)]


def require(source: str, target: str) -> None:
    available = installed()
    missing = [
        f"{a.upper()} → {b.upper()}" for a, b in route(source, target) if (a, b) not in available
    ]
    if missing:
        raise IrisError("no_model", pairs=", ".join(missing))


def overview() -> list[dict[str, Any]]:
    available = installed()
    result = []
    for pair, directions in PAIRS.items():
        items = [
            {
                "from": a,
                "to": b,
                "installed": (a, b) in available,
                "version": str(getattr(available.get((a, b)), "package_version", "") or ""),
            }
            for a, b in directions
        ]
        result.append(
            {"id": pair, "directions": items, "installed": all(i["installed"] for i in items)}
        )
    return result


def _download(
    url: str, target: Path, cancel: threading.Event, progress: Callable[[float], None]
) -> None:
    if not url.startswith("https://"):
        raise IrisError("model_download", f"adresse refusée : {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "Iris"})
    with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(256 * 1024):
            if cancel.is_set():
                raise Cancelled()
            out.write(chunk)
            done += len(chunk)
            if total:
                progress(done / total)
    if total and done < total:
        raise IrisError("model_download", f"fichier incomplet ({done}/{total})")


def install(
    pair: str,
    cancel: threading.Event | None = None,
    progress: Callable[[float], None] = lambda _: None,
) -> None:
    if pair not in PAIRS:
        raise IrisError("bad_request", f"paire inconnue : {pair}")
    cancel = cancel or threading.Event()
    argos = _argos()
    wanted = [d for d in PAIRS[pair] if d not in installed()]
    if not wanted:
        progress(1.0)
        return
    try:
        argos.package.update_package_index()
        catalogue = {(p.from_code, p.to_code): p for p in argos.package.get_available_packages()}
        for index, direction in enumerate(wanted):
            package = catalogue.get(direction)
            if package is None or not package.links:
                raise IrisError("model_download", f"modèle absent du catalogue : {direction}")
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
                archive = Path(folder) / f"{direction[0]}_{direction[1]}.argosmodel"
                last: Exception | None = None
                for url in package.links:
                    try:
                        _download(
                            url,
                            archive,
                            cancel,
                            lambda f, i=index: progress((i + f * 0.97) / len(wanted)),
                        )
                        break
                    except (OSError, IrisError) as exc:
                        last = exc
                else:
                    raise IrisError("model_download", str(last))
                argos.package.install_from_path(archive)
            progress((index + 1) / len(wanted))
    except (Cancelled, IrisError):
        raise
    except Exception as exc:
        raise IrisError("model_download", f"{type(exc).__name__}: {exc}") from exc
    finally:
        _reset()


def uninstall(pair: str) -> None:
    if pair not in PAIRS:
        raise IrisError("bad_request", f"paire inconnue : {pair}")
    argos = _argos()
    available = installed()
    _reset()  # libère les modèles chargés avant de les supprimer
    for direction in PAIRS[pair]:
        if direction in available:
            argos.package.uninstall(available[direction])
    _reset()


def _reset() -> None:
    from .translate import reset

    reset()
