"""Installe Iris d'un coup sous Windows. Lancé par Installer.bat ; le relancer met à jour.

L'application est copiée dans son propre dossier : le téléchargement peut ensuite être supprimé.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
TARGET = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "Iris"
TOOLS = (
    ("LibreOffice (pour créer des PDF)", "find_soffice", "TheDocumentFoundation.LibreOffice"),
    ("Tesseract (pour lire les scans)", "find_tesseract", "UB-Mannheim.TesseractOCR"),
)
TESSDATA = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{}.traineddata"


def step(text: str) -> None:
    print(f"\n==> {text}", flush=True)


def copy_app() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    if TARGET.resolve() == SOURCE:
        return
    shutil.rmtree(TARGET / "iris", ignore_errors=True)  # aucun ancien fichier ne reste
    shutil.copytree(
        SOURCE / "iris",
        TARGET / "iris",
        ignore=shutil.ignore_patterns("__pycache__"),
        dirs_exist_ok=True,
    )
    for name in ("run.py", "requirements.txt", "LICENSE"):
        shutil.copy2(SOURCE / name, TARGET / name)


def iris(python: Path, *args: str) -> bool:
    return subprocess.run([str(python), *args], cwd=TARGET).returncode == 0


def add_tools(python: Path) -> list[str]:
    """Ajoute les logiciels absents ; renvoie ceux qui n'ont pas pu l'être."""
    missing = []
    for label, finder, package in TOOLS:
        found = f"import sys; from iris import convert; sys.exit(not convert.{finder}())"
        if iris(python, "-c", found):
            continue
        step(f"Installation de {label}")
        if shutil.which("winget"):
            subprocess.run(
                ["winget", "install", "-e", "--id", package]
                + ["--accept-package-agreements", "--accept-source-agreements"]
            )
        if not iris(python, "-c", found):
            missing.append(label)
    return missing


def add_ocr_languages(python: Path) -> bool:
    """L'installeur de Tesseract n'apporte que l'anglais : ajoute le français et l'espagnol."""
    wanted = "from iris import convert; import sys; "
    if iris(python, "-c", wanted + "sys.exit(not {'fra','eng','spa'} <= convert.ocr_languages())"):
        return True
    step("Langues de lecture des scans")
    asked = subprocess.run(
        [str(python), "-c", "from iris import storage; print(storage.data_dir() / 'tessdata')"],
        cwd=TARGET,
        capture_output=True,
        text=True,
        check=True,
        env=os.environ | {"PYTHONUTF8": "1"},
        encoding="utf-8",
    )
    folder = Path(asked.stdout.strip())
    folder.mkdir(parents=True, exist_ok=True)
    try:
        # Anglais compris : ce dossier remplace celui de Tesseract.
        for name in ("eng", "fra", "spa"):
            part = folder / f"{name}.part"
            urllib.request.urlretrieve(TESSDATA.format(name), part)
            part.replace(folder / f"{name}.traineddata")
    except OSError as exc:
        print(f"Téléchargement impossible : {exc}")
        return False
    return True


def main() -> int:
    if sys.platform != "win32":
        print("Cet installateur est réservé à Windows : suis le README.")
        return 1
    step(f"Copie d'Iris dans {TARGET}")
    copy_app()
    python = TARGET / ".venv" / "Scripts" / "python.exe"
    if not (python.is_file() and iris(python, "-m", "pip", "--version")):
        step("Préparation de Python")
        # « --clear » repart de zéro après une installation interrompue.
        venv = [sys.executable, "-m", "venv", "--clear", str(TARGET / ".venv")]
        subprocess.run(venv, check=True)
    step("Installation des composants (le plus long)")
    pip = ["-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"]
    if not iris(python, *pip):
        return 1

    # La suite est utile mais pas indispensable : un échec n'arrête pas l'installation.
    missing = add_tools(python)
    if not any("Tesseract" in label for label in missing) and not add_ocr_languages(python):
        missing.append("les langues de lecture des scans")
    step("Modèles de traduction (environ 600 Mo)")
    if not iris(python, "-m", "iris", "models", "install"):
        missing.append("les modèles de traduction (installables depuis « Langues installées »)")

    step("Création des raccourcis")
    if not iris(python, "-m", "iris", "install"):
        return 1
    if missing:
        print("\nIris est installé, mais il manque :")
        for label in missing:
            print(f"  - {label}")
    subprocess.Popen([str(python.with_name("pythonw.exe")), str(TARGET / "run.py")], cwd=TARGET)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"\nErreur : {exc}")
        sys.exit(1)
