"""Ligne de commande : python -m iris convert | translate | models | serve."""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from . import LANGS, convert, docx_inplace, models, pipeline, storage, translate
from .errors import Cancelled, IrisError


def _bar(fraction: float, stage: str) -> None:
    if sys.stderr.isatty():
        print(f"\r{fraction:6.1%}  {stage:<14}", end="", file=sys.stderr, flush=True)


def _detect(path: Path) -> str:
    kind = convert.sniff(path)
    text = docx_inplace.excerpt(path)[2] if kind == "docx" else convert.pdf_info(path).text
    found = translate.detect(text)
    if not found:
        raise IrisError("bad_request", "langue non détectée : précise --from")
    return found


def _process(args: argparse.Namespace, request: pipeline.Request) -> None:
    cancel = threading.Event()
    result = pipeline.run(request, _bar, cancel)
    if sys.stderr.isatty():
        print(file=sys.stderr)
    print(f"Terminé : {result.output} ({result.duration:.1f} s)")
    report = result.report.localized()
    if report["counts"]:
        print("  " + ", ".join(f"{k} : {v}" for k, v in report["counts"].items()))
    for warning in report["warnings"]:
        print(f"  ! {warning['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m iris")
    commands = parser.add_subparsers(dest="command")

    conv = commands.add_parser("convert", help="Word <-> PDF")
    conv.add_argument("file", type=Path)
    conv.add_argument("--to", required=True, choices=["pdf", "docx"])

    trad = commands.add_parser("translate", help="traduire un document")
    trad.add_argument("file", type=Path)
    trad.add_argument("--from", dest="source", choices=LANGS, help="détectée par défaut")
    trad.add_argument("--to", dest="target", required=True, choices=LANGS)
    trad.add_argument("--format", choices=["pdf", "docx"], help="format de sortie")

    for command in (conv, trad):
        command.add_argument("--out", type=Path, help="dossier de sortie")
        command.add_argument("--ocr", choices=["auto", "yes", "no"], default="auto")

    packages = commands.add_parser("models", help="modèles de langue")
    packages.add_argument("action", choices=["list", "install", "uninstall"])
    packages.add_argument("pair", nargs="*", choices=[[], *models.PAIRS])

    commands.add_parser("serve", help="lancer l'application", add_help=False)

    args, rest = parser.parse_known_args(argv)
    if args.command in (None, "serve"):
        from .app import main as app_main

        app_main(rest)
        return 0
    if rest:
        parser.error(f"arguments inconnus : {' '.join(rest)}")

    storage.setup_logging()
    try:
        if args.command == "models":
            if args.action == "list":
                for pair in models.overview():
                    for d in pair["directions"]:
                        state = f"installé ({d['version']})" if d["installed"] else "absent"
                        print(f"{pair['id']}  {d['from']} -> {d['to']} : {state}")
                return 0
            for pair in args.pair or models.PAIRS:
                if args.action == "install":
                    print(f"Installation de {pair}…")
                    models.install(pair, progress=lambda f: _bar(f, "download"))
                    print(f"\n{pair} installé.")
                else:
                    models.uninstall(pair)
                    print(f"{pair} désinstallé.")
            return 0
        path = args.file.resolve()
        if args.command == "convert":
            request = pipeline.Request(path, args.to, out_dir=args.out, ocr=args.ocr)
        else:
            request = pipeline.Request(
                path,
                args.format or convert.sniff(path),
                translate=True,
                source_lang=args.source or _detect(path),
                target_lang=args.target,
                out_dir=args.out,
                ocr=args.ocr,
            )
        _process(args, request)
    except IrisError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        if exc.detail:
            print(f"Détail : {exc.detail}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, Cancelled):
        print("\nAnnulé.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
