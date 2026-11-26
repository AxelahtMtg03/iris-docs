"""Lance Iris : serveur local, puis fenêtre d'application (ou navigateur à défaut)."""

import sys

if sys.version_info < (3, 10):  # noqa: UP036 - message clair sur un vieux Python
    sys.exit("Iris a besoin de Python 3.10 ou plus récent.")

try:
    from iris.app import main
except ModuleNotFoundError as exc:
    sys.exit(f"Module manquant : {exc.name}. Lance d'abord : pip install -r requirements.txt")

if __name__ == "__main__":
    main()
