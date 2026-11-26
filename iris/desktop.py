"""Installe Iris comme une application : icône dans le menu et sur le bureau, sans terminal."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "iris" / "web" / "icons"
DESCRIPTION = "Convertit et traduit des documents, en local"

# Les chemins passent par l'environnement : aucun problème de guillemets ou d'accents.
_WINDOWS = """
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
foreach ($name in 'Programs', 'Desktop') {
  $path = Join-Path ([Environment]::GetFolderPath($name)) 'Iris.lnk'
  if ($env:IRIS_ACTION -eq 'install') {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $env:IRIS_TARGET
    $link.Arguments = $env:IRIS_ARGS
    $link.WorkingDirectory = $env:IRIS_ROOT
    $link.IconLocation = $env:IRIS_ICON
    $link.Description = $env:IRIS_DESCRIPTION
    $link.Save()
    $path
  } elseif (Test-Path -LiteralPath $path) {
    Remove-Item -LiteralPath $path
    $path
  }
}
"""


def _windows(action: str) -> list[str]:
    # pythonw lance un programme sans ouvrir de console.
    interpreter = Path(sys.executable).with_name("pythonw.exe")
    environment = os.environ | {
        "IRIS_ACTION": action,
        "IRIS_TARGET": str(interpreter),
        "IRIS_ARGS": f'"{ROOT / "run.py"}"',
        "IRIS_ROOT": str(ROOT),
        "IRIS_ICON": str(ICONS / "iris.ico"),
        "IRIS_DESCRIPTION": DESCRIPTION,
    }
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip())
    return result.stdout.split("\n")[:-1]


def _linux_entry() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "applications" / "iris.desktop"


def install() -> list[str]:
    """Crée les raccourcis et renvoie leurs chemins."""
    if sys.platform == "win32":
        return _windows("install")
    if sys.platform == "darwin":
        raise OSError("raccourci non pris en charge sur macOS : lance « python run.py »")
    entry = _linux_entry()
    entry.parent.mkdir(parents=True, exist_ok=True)
    command = shlex.join([sys.executable, str(ROOT / "run.py")])
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=Iris\n"
        f"Comment={DESCRIPTION}\nExec={command}\nPath={ROOT}\n"
        f"Icon={ICONS / 'iris.svg'}\nTerminal=false\nCategories=Office;\n",
        encoding="utf-8",
    )
    return [str(entry)]


def uninstall() -> list[str]:
    if sys.platform == "win32":
        return _windows("uninstall")
    entry = _linux_entry()
    if not entry.is_file():
        return []
    entry.unlink()
    return [str(entry)]
