"""Lance Iris : serveur local, puis fenêtre d'application (ou navigateur à défaut)."""

import sys

if sys.version_info < (3, 10):  # noqa: UP036 - message clair sur un vieux Python
    sys.exit("Iris a besoin de Python 3.10 ou plus récent.")

try:
    from iris.app import main
except ModuleNotFoundError as exc:
    problem = f"Module manquant : {exc.name}. Lance d'abord : pip install -r requirements.txt"
    if sys.stderr is None and sys.platform == "win32":  # sans console : une boîte de dialogue
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, problem, "Iris", 0x10)
    sys.exit(problem)

if __name__ == "__main__":
    main()
