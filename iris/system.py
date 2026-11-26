"""Dialogues natifs et explorateur de fichiers, sur Windows, macOS et Linux."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .errors import IrisError

FILE_TYPES = {
    "docx": [("Word (.docx)", "*.docx")],
    "pdf": [("PDF", "*.pdf")],
    "any": [("Word, PDF", "*.docx *.pdf")],
}

# Lancé à part : Tk exige le fil principal, que le serveur n'a pas.
_PICKER = """
import sys, tkinter
from tkinter import filedialog
sys.path.insert(0, sys.argv[1])
from iris.system import FILE_TYPES
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
kind = sys.argv[2]
if kind == "folder":
    chosen = filedialog.askdirectory(parent=root, title="Iris", mustexist=True)
else:
    chosen = filedialog.askopenfilename(parent=root, title="Iris", filetypes=FILE_TYPES[kind])
sys.stdout.write(chosen or "")
"""


class NoDialog(Exception):
    """Aucun dialogue natif disponible : l'interface utilise alors le sélecteur du navigateur."""


def pick_with_tk(kind: str) -> str | None:
    if os.environ.get("IRIS_NO_DIALOG"):
        raise NoDialog()
    root = str(Path(__file__).resolve().parent.parent)
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", _PICKER, root, kind],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise NoDialog()
    return result.stdout.strip() or None


def reveal(path: Path) -> None:
    """Ouvre le dossier du fichier dans l'explorateur, en le sélectionnant si possible."""
    exists = path.exists()
    folder = path if path.is_dir() else path.parent
    if not folder.is_dir():
        raise IrisError("not_found", str(path))
    if sys.platform == "win32":
        if exists and path.is_file():
            # Un nom de fichier Windows ne peut pas contenir de guillemet.
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if exists else ["open", str(folder)])
    else:
        opener = shutil.which("xdg-open")
        if not opener:
            raise IrisError("internal", "xdg-open introuvable")
        subprocess.Popen([opener, str(folder)])
