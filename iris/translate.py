"""Traduction hors-ligne avec les modèles Argos, pivot par l'anglais et détection de langue."""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Any

from . import models

_lock = threading.Lock()
_engines: dict[tuple[str, str], tuple[Any, Any]] = {}  # sens -> (paquet, moteur)


def load_argos():  # type: ignore[no-untyped-def]
    """Import tardif : Argos n'est chargé que lorsqu'on en a besoin."""
    os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")
    import argostranslate.package

    return argostranslate


def reset() -> None:
    """À appeler après l'installation ou la suppression d'un modèle."""
    with _lock:
        _engines.clear()
    _direct.cache_clear()


# ---------------------------------------------------------------- découpage en phrases

_BOUNDARY = re.compile(r"[.!?…]+[\"'»”’)\]]*(\s+)(?=[«\"“'(\[¿¡]*[A-ZÀ-ÖØ-ÞŒ0-9])")
_ABBREVIATION = re.compile(
    r"(?:\b(?:M|MM|Mme|Mlle|Dr|Pr|St|Ste|Sr|Sra|Srta|Mr|Mrs|Ms|Prof|etc|cf|fig|Fig|p|pp|ex|vs|"
    r"núm|pág|art|No|no|n°|av|env|e\.g|i\.e|[A-ZÀ-Þ]))\.$"
)
_LONG = 600


def split_sentences(text: str) -> list[str]:
    """Découpage par ponctuation : aucun modèle supplémentaire, donc aucun accès réseau."""
    sentences, start = [], 0
    for match in _BOUNDARY.finditer(text):
        end = match.start(1)
        if _ABBREVIATION.search(text[start:end]):
            continue
        sentences.append(text[start:end])
        start = match.end(1)
    sentences.append(text[start:])
    result = []
    for sentence in sentences:
        # Les modèles tronquent les entrées trop longues : on coupe aussi à la ponctuation faible.
        while len(sentence) > _LONG:
            cut = max(sentence.rfind(mark, 0, _LONG) for mark in ("; ", ": ", ", "))
            if cut < _LONG // 4:
                cut = sentence.rfind(" ", 0, _LONG)
            if cut <= 0:
                break
            result.append(sentence[: cut + 1].strip())
            sentence = sentence[cut + 1 :].strip()
        if sentence.strip():
            result.append(sentence.strip())
    return result


# ---------------------------------------------------------------- moteur


def _engine(source: str, target: str) -> tuple[Any, Any]:
    with _lock:
        if (source, target) not in _engines:
            import ctranslate2

            package = models.installed()[(source, target)]
            engine = ctranslate2.Translator(
                str(package.package_path / "model"),
                device="cpu",
                compute_type="default",  # "auto" abîme es->en
            )
            _engines[(source, target)] = (package, engine)
        return _engines[(source, target)]


@lru_cache(maxsize=4096)
def _direct(text: str, source: str, target: str) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return text
    package, engine = _engine(source, target)
    prefix = package.target_prefix
    results = engine.translate_batch(
        [package.tokenizer.encode(s) for s in sentences],
        target_prefix=[[prefix]] * len(sentences) if prefix else None,
        replace_unknowns=True,
        max_batch_size=32,
        beam_size=4,
        length_penalty=0.2,
    )
    translated = []
    for result in results:
        value = package.tokenizer.decode(result.hypotheses[0])
        if prefix and value.startswith(prefix):
            value = value[len(prefix) :]
        translated.append(value.strip())
    return " ".join(translated)


# ---------------------------------------------------------------- ce qui ne se traduit pas

_PROTECTED = re.compile(
    r"(?:https?://|ftp://|www\.)[^\s<>()«»\"]*[^\s<>()«»\".,;:!?]"
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|\{\{[^{}]*\}\}|\$\{[^{}]*\}|«[A-Z0-9_]+»|%[A-Z_]{2,}%"
    r"|(?:[A-Za-z]:\\|~/|\./)[^\s,;]*[^\s,;.]"
    r"|\b\w+(?:_\w+)+(?:\.\w+)?\b"
    r"|(?<= )&(?= )"  # « Dupont & Durand » : le signe devient sinon une apostrophe
    # Les modèles avalent les signes mathématiques : le signe reste collé à son nombre.
    r"|[∼≈≃±≤≥]\s?(?:\d+(?:[.,   ]\d+)*(?:\s?%)?)?"
)
_SIGNED_DECIMAL = re.compile(r"([∼≈≃±≤≥]\s?\d+),(\d{1,2})(?!\d)")
_NUMBER = re.compile(r"\d+(?:[   .,:/-]\d+)*")


def _protected_spans(text: str, keep: Sequence[str]) -> list[tuple[int, int]]:
    found = [m.span() for m in _PROTECTED.finditer(text)]
    for literal in keep:
        found += [m.span() for m in re.finditer(re.escape(literal), text)]
    merged: list[tuple[int, int]] = []
    for start, end in sorted(found):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _digits(text: str) -> list[str]:
    return sorted(re.findall(r"\d+", text))


def _unpunctuated(source: str, translated: str) -> str:
    """Le modèle ajoute volontiers un point aux titres et aux cellules de tableau."""
    if source.rstrip()[-1:] not in ".!?…" and re.search(r"[^.]\.$", translated):
        return translated[:-1]
    return translated


def _around(text: str, spans: list[tuple[int, int]], run: Callable[[str], str]) -> str:
    """Traduit les morceaux situés entre les passages protégés, recopiés tels quels."""
    parts, position = [], 0
    for start, end in [*spans, (len(text), len(text))]:
        chunk = text[position:start]
        core = chunk.strip()
        if any(c.isalpha() for c in core):
            lead = chunk[: len(chunk) - len(chunk.lstrip())]
            trail = chunk[len(chunk.rstrip()) :]
            chunk = lead + run(core) + trail
        parts.append(chunk + text[start:end])
        position = end
    return "".join(parts)


def protect(text: str, keep: Sequence[str], run: Callable[[str], str]) -> str:
    """Traduit `text` avec `run` en gardant intacts adresses, courriels, code et nombres."""
    spans = _protected_spans(text, keep)
    numbers = [m.group() for m in _NUMBER.finditer(text)]
    # Dernier recours : tout recopier, nombres compris, et ne traduire que ce qui les sépare.
    literals = [*keep, *numbers]
    if not spans:
        translated = run(text)
        if _digits(translated) == _digits(text):
            return translated
        return _around(text, _protected_spans(text, literals), run)
    # Un repère à la place de chaque passage laisse au modèle la phrase entière.
    masked, position = [], 0
    for index, (start, end) in enumerate(spans):
        masked += [text[position:start], f"ZX{index}"]
        position = end
    masked_text = "".join([*masked, text[position:]])
    if any(c.isalpha() for c in re.sub(r"ZX\d+", "", masked_text)):
        translated = run(masked_text)
        intact = all(translated.count(f"ZX{i}") == 1 for i in range(len(spans)))
        for index, (start, end) in reversed(list(enumerate(spans))):
            translated = translated.replace(f"ZX{index}", text[start:end])
        if intact and _digits(translated) == _digits(text):
            return translated
    return _around(text, _protected_spans(text, literals), run)


def translator(source: str, target: str) -> Callable[[str, list[str]], str]:
    route = models.route(source, target)

    def step(text: str, a: str, b: str) -> str:
        result = _direct(text, a, b)
        parts = re.split(r"(\s*[:;—–|]\s+)", text)
        # Le modèle « oublie » parfois la fin d'un intitulé : on retraduit morceau par morceau.
        if len(parts) > 1 and len(result) < 0.55 * len(text):
            result = "".join(
                p if i % 2 or not p else _unpunctuated(p, _direct(p, a, b))
                for i, p in enumerate(parts)
            )
        return _unpunctuated(text, result)

    def run(text: str) -> str:
        for step_source, step_target in route:
            text = step(text, step_source, step_target)
        return text

    def translate(text: str, keep: Sequence[str] = ()) -> str:
        if not any(c.isalpha() for c in text):
            return text
        result = protect(text, keep, run)
        if target == "en":  # le nombre recopié avec son signe prend le point décimal anglais
            result = _SIGNED_DECIMAL.sub(r"\1.\2", result)
        return result

    return translate


# ---------------------------------------------------------------- détection

_COMMON = {
    "fr": "le la les un une des du de et est que qui dans pour pas sur avec ce cette sont au "
    "aux ne se il elle nous vous ils mais ou où été être plus ses leur par je tu mon ton sa son",
    "en": "the a an of and is that which in for not on with this are to be was were it he she we "
    "you they but or been more from by as at has have will their our your its",
    "es": "el la los las un una unos y es que en para no sobre con este esta son al del se lo su "
    "pero o donde sido ser más por como sus nos está están fue hay también",
}
_STOPWORDS = {lang: set(words.split()) for lang, words in _COMMON.items()}
_MARKS = {"fr": "çœàèêùîô", "es": "ñ¿¡íóáú", "en": ""}


def detect(text: str) -> str | None:
    """Langue la plus probable parmi FR, EN, ES, ou None si le texte ne permet pas de conclure."""
    sample = text[:6000].lower()
    words = re.findall(r"[^\W\d_]+", sample)
    if not words:
        return None
    scores = {
        lang: sum(w in stop for w in words) + 0.5 * sum(sample.count(c) for c in _MARKS[lang])
        for lang, stop in _STOPWORDS.items()
    }
    first, second = sorted(scores, key=scores.__getitem__, reverse=True)[:2]
    if scores[first] < 1 or scores[first] <= scores[second] * 1.1:
        return None
    return first
