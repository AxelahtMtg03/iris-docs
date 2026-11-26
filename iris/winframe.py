"""Windows : la barre de titre native disparaît, la page dessine la sienne.

La fenêtre reste une fenêtre Windows ordinaire (redimensionnement, ancrage aux bords,
animations) : seule la zone de titre est rendue à la page. Voir ``winframe.cs``.
"""

from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Any

APP_ID = "Iris.Desktop"  # regroupe la fenêtre et le raccourci dans la barre des tâches
SOURCE = Path(__file__).with_suffix(".cs")
GRIP = 4  # bande, en pixels logiques, qui redimensionne par le haut
_SC_MINIMIZE, _SC_MAXIMIZE, _SC_RESTORE, _SC_CLOSE = 0xF020, 0xF030, 0xF120, 0xF060


def identify() -> None:
    """Sans cet identifiant, la barre des tâches affiche l'icône de Python."""
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def _compile() -> Any:
    """Compile la partie C# avec le compilateur fourni par Windows."""
    from Microsoft.CSharp import CSharpCodeProvider
    from System.CodeDom.Compiler import CompilerParameters

    options = CompilerParameters()
    options.GenerateInMemory = True
    for library in ("System.dll", "System.Drawing.dll", "System.Windows.Forms.dll"):
        options.ReferencedAssemblies.Add(library)
    result = CSharpCodeProvider().CompileAssemblyFromSource(
        options, SOURCE.read_text(encoding="utf-8")
    )
    if result.Errors.HasErrors:
        raise OSError("; ".join(str(error) for error in result.Errors))
    return result.CompiledAssembly.GetType("Iris.Frame")


class Frame:
    def __init__(self, window: Any) -> None:
        self._window = window
        self._frame: Any = None
        window.events.before_show += self._install
        window.expose(
            self.window_minimize,
            self.window_maximize,
            self.window_close,
            self.window_maximized,
            self.window_color,
        )

    def _install(self) -> None:
        from System import Activator, Int32

        form = self._window.native

        def allow_drag(view: Any, args: Any) -> None:
            if args.IsSuccess:  # rend la règle CSS « app-region: drag » active
                view.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True

        form.webview.CoreWebView2InitializationCompleted += allow_drag
        self._frame = Activator.CreateInstance(_compile(), form, Int32(GRIP))

    # ---------- Appelées par la page ----------
    def window_minimize(self) -> None:
        self._frame.Command(_SC_MINIMIZE)

    def window_maximize(self) -> None:
        self._frame.Command(_SC_RESTORE if self._frame.Maximized else _SC_MAXIMIZE)

    def window_close(self) -> None:
        self._frame.Command(_SC_CLOSE)

    def window_maximized(self) -> bool:
        return bool(self._frame and self._frame.Maximized)

    def window_color(self, color: str, dark: bool) -> None:
        self._frame.Paint(color, dark)
