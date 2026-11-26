"""Démarrage et arrêt propre de l'application de bureau."""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import webbrowser
from typing import Any

from werkzeug.serving import make_server

from . import desktop, storage, system
from .server import create_app

HOST = "127.0.0.1"
PORT = 8765  # fixe de préférence : le navigateur garde ainsi le thème choisi
log = logging.getLogger("iris")


def free_port(preferred: int) -> int:
    for port in (*range(preferred, preferred + 20), 0):
        with socket.socket() as probe:
            try:
                probe.bind((HOST, port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise OSError("aucun port disponible")


def _window_picker(window: Any, webview: Any):  # type: ignore[no-untyped-def]
    def pick(kind: str) -> str | None:
        if kind == "folder":
            chosen = window.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            patterns = ";".join(p for _, ext in system.FILE_TYPES[kind] for p in ext.split())
            chosen = window.create_file_dialog(
                webview.FileDialog.OPEN, file_types=(f"Documents ({patterns})",)
            )
        return chosen[0] if chosen else None

    return pick


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="iris", description="Convertit et traduit des documents.")
    parser.add_argument("--browser", action="store_true", help="ouvrir dans le navigateur")
    parser.add_argument("--no-open", action="store_true", help="ne rien ouvrir, afficher l'adresse")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    if sys.stdout is None:  # lancé sans console (pythonw) : les messages vont dans un fichier
        console = open(storage.data_dir() / "console.log", "w", encoding="utf-8")  # noqa: SIM115
        sys.stdout = sys.stderr = console

    webview = None
    if not (args.browser or args.no_open):
        try:
            import webview  # type: ignore[no-redef]
        except ImportError:
            webview = None

    picker = {"call": system.pick_with_tk}
    app = create_app(picker=lambda kind: picker["call"](kind))
    port = free_port(args.port)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    server = make_server(HOST, port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{HOST}:{port}/#t={app.config['TOKEN']}"

    try:
        if webview is not None:
            try:
                window = webview.create_window(
                    "Iris",
                    url + "&d=1",  # présentation « application » : sans décor autour
                    width=1180,
                    height=880,
                    min_size=(360, 560),
                    background_color="#0E1222",
                )
                picker["call"] = _window_picker(window, webview)
                webview.settings["ALLOW_DOWNLOADS"] = True
                # shortcut: un fichier glissé dans la fenêtre est envoyé sans son chemin ;
                # lire `pywebviewFullPath` si l'enregistrement à côté de la source est voulu.
                webview.start(icon=str(desktop.ICONS / "iris.ico"))
                return
            except Exception:  # pas de moteur d'affichage : on se rabat sur le navigateur
                log.exception("Fenêtre indisponible, ouverture dans le navigateur")
                picker["call"] = system.pick_with_tk
        print(f"Iris est prêt : {url}")
        print("Ctrl+C pour quitter.")
        if not args.no_open:
            webbrowser.open(url)
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nArrêt d'Iris…")
    finally:
        server.shutdown()
        app.config["JOBS"].shutdown()
        storage.close_session()
