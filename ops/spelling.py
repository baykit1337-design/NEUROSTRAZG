"""Проверка орфографии (4.9 ТЗ NEUROSTRAZH).

Смысловые ошибки ловит анализ, механические — проверка текста, а обычную
опечатку сейчас не ловит никто: «превет» проходит все правила, потому что
это правильно оформленное русское слово, которого не существует.

Словарь работает офлайн и собирается из двух частей.

Знает ли язык такое слово — решает `pymorphy3`: у него полная морфология,
он понимает «усмехнулся» и «длинной». Обычный список слов на этом месте не
годится: в `pyspellchecker` для русского около двадцати тысяч начальных
форм, и каждое второе слово живого текста он объявляет ошибкой.

Чем заменить — подсказывает `pyspellchecker`: перебор похожих написаний
морфологии не по силам. Подсказки необязательны, без них проверка просто
не предлагает вариантов.

Ни одного пакета нет — вкладка не ломается, а честно говорит, чего не
хватает: словари весят мегабайты, и тащить их в обязательные зависимости
неправильно.

Имена и термины сюда попадают из реестра сущностей (часть 3) — иначе
каждое имя героя было бы «опечаткой», и в шуме утонула бы настоящая. Плюс
свой список исключений, который пополняется прямо из находок.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.models import OpReport

from .base import Progress, collect_files, read_all

#: Слово: только буквы и внутренние дефис с апострофом. Цифры и знаки
#: отсекаются здесь, а не проверками словаря.
WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)

#: Короткие слова словарь знает плохо, а ошибок в них почти не бывает.
MIN_LENGTH = 3

#: Сколько подсказок показывать. Больше трёх в строке не читается.
SUGGESTIONS = 3

#: Имя файла со своими словами. Лежит рядом с книгой: у каждой книги свой
#: набор имён, общий список быстро превратился бы в свалку.
DICT_FILE = "spelling.txt"

#: Сколько находок отдавать в интерфейс. На книге в пятьсот глав их могут
#: быть тысячи, и рисовать всё разом бессмысленно.
LIMIT = 500


class SpellingError(Exception):
    """Проверить не удалось."""


def available() -> bool:
    """Есть ли чем проверять. Интерфейс спрашивает до запуска."""
    try:
        import pymorphy3  # noqa: F401
    except ImportError:
        return False
    return True


def suggestions_available() -> bool:
    """Есть ли чем подсказывать. Без этого проверка всё равно работает."""
    try:
        import spellchecker  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class Finding:
    """Одно незнакомое слово."""

    word: str = ""
    file: str = ""
    chapter: str = ""
    count: int = 0
    quote: str = ""
    suggestions: list[str] = field(default_factory=list)
    path: str = ""

    def as_dict(self) -> dict:
        return {"word": self.word, "file": self.file, "chapter": self.chapter,
                "count": self.count, "quote": self.quote,
                "suggestions": self.suggestions, "path": self.path}


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    words: int = 0
    chapters: int = 0
    #: Сколько слов пропущено по словарю исключений и реестру.
    known: int = 0
    unreadable: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "findings": [f.as_dict() for f in self.findings[:LIMIT]],
            "total": len(self.findings),
            "shown": min(len(self.findings), LIMIT),
            "words": self.words,
            "chapters": self.chapters,
            "known": self.known,
            "unreadable": self.unreadable,
        }


# --------------------------------------------------- словарь исключений


def dict_path(folder) -> Path:
    return Path(str(folder)).expanduser() / DICT_FILE


def load_words(folder) -> list[str]:
    """Свои слова книги. Отсутствие файла — обычное дело, не ошибка."""
    path = dict_path(folder)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return sorted({line.strip() for line in text.splitlines() if line.strip()},
                  key=str.lower)


def save_words(folder, words) -> Path:
    path = dict_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = sorted({str(w).strip() for w in words if str(w).strip()},
                   key=str.lower)
    path.write_text("\n".join(clean) + ("\n" if clean else ""), encoding="utf-8")
    return path


def add_words(folder, words) -> list[str]:
    """Кнопка «это имя» из находок — дописывает, не стирая прежнее."""
    have = set(load_words(folder))
    have.update(str(w).strip() for w in words if str(w).strip())
    save_words(folder, have)
    return sorted(have, key=str.lower)


def registry_words(root) -> set[str]:
    """Имена из реестра сущностей — они не опечатки, а имена.

    Реестра может не быть вовсе: анализ книги — дело добровольное.
    """
    try:
        from ops.analyze import load_registry

        registry = load_registry(Path(str(root)).expanduser())
    except Exception:  # noqa: BLE001 — без реестра проверка просто строже
        return set()

    found: set[str] = set()
    for entity in registry.entities.values():
        for name in entity.names:
            # Имя может быть составным: «Секта Пурпурного Облака».
            found.update(m.group(0) for m in WORD.finditer(name))
    return {w for w in found if w}


# ------------------------------------------------------------- проверка


class _Dictionary:
    """Знает ли язык слово и чем его заменить.

    Две разные задачи и два разных пакета: узнавание — морфология,
    подсказки — перебор похожих написаний. Второе необязательно.
    """

    def __init__(self, extra=None):
        try:
            import pymorphy3
        except ImportError as exc:
            raise SpellingError(
                "Словарь не установлен. Поставьте пакеты: "
                "pip install pymorphy3 pymorphy3-dicts-ru"
            ) from exc

        try:
            self.morph = pymorphy3.MorphAnalyzer()
        except Exception as exc:  # noqa: BLE001 — причину показываем целиком
            raise SpellingError(f"Не удалось открыть словарь: {exc}") from exc

        #: Слова книги: имена, термины и всё, что человек уже признал.
        self.extra = {str(w).strip().lower() for w in (extra or []) if str(w).strip()}
        #: Разбор одного слова стоит дорого, а слова повторяются.
        self._seen: dict[str, bool] = {}
        self._speller = None

        try:
            from spellchecker import SpellChecker

            self._speller = SpellChecker(language="ru")
        except Exception:  # noqa: BLE001 — без подсказок проверка работает
            self._speller = None

    def knows(self, word: str) -> bool:
        lower = word.lower()
        if lower in self.extra:
            return True
        found = self._seen.get(lower)
        if found is None:
            found = any(p.is_known for p in self.morph.parse(lower))
            self._seen[lower] = found
        return found

    @property
    def suggests(self) -> bool:
        return self._speller is not None

    def suggest(self, word: str) -> list[str]:
        if self._speller is None:
            return []
        try:
            options = self._speller.candidates(word.lower()) or set()
        except Exception:  # noqa: BLE001 — подсказка не обязательна
            return []
        return [w for w in sorted(options)[:SUGGESTIONS] if w != word.lower()]


def _dictionary(extra=None) -> _Dictionary:
    """Отдельной функцией — её подменяют в тестах."""
    return _Dictionary(extra)


def _quote(paragraph: str, word: str, width: int = 90) -> str:
    """Кусок абзаца вокруг слова — чтобы было видно, о чём речь."""
    place = paragraph.lower().find(word.lower())
    if place < 0:
        return paragraph[:width]
    half = width // 2
    left = max(0, place - half)
    right = min(len(paragraph), place + len(word) + half)
    piece = paragraph[left:right].strip()
    return ("…" if left > 0 else "") + piece + ("…" if right < len(paragraph) else "")


def check(targets, folder="", use_registry: bool = True,
          progress: Progress | None = None) -> Report:
    """Ищет незнакомые слова в выбранных главах.

    `folder` — где лежит книга: оттуда берутся свой словарь и реестр.
    Пусто — берём папку первого файла.
    """
    op = OpReport()
    files = collect_files(targets)
    root = Path(str(folder)).expanduser() if folder else files[0].parent

    extra = set(load_words(root))
    if use_registry:
        extra |= registry_words(root)

    words = _dictionary(extra)
    chapters = read_all(files, op, progress)

    report = Report(chapters=len(chapters),
                    unreadable=[f.as_text() for f in op.failures])
    #: Слово встречается в книге сотни раз — находка должна быть одна.
    seen: dict[str, Finding] = {}

    for index, chapter in enumerate(chapters, 1):
        if progress:
            progress.check()
        for paragraph in chapter.paragraphs:
            found_words = [m.group(0) for m in WORD.finditer(paragraph)]
            report.words += len(found_words)

            for word in found_words:
                if len(word) < MIN_LENGTH or words.knows(word):
                    continue
                key = word.lower()
                finding = seen.get(key)
                if finding is None:
                    finding = Finding(
                        word=word, file=Path(chapter.source).name,
                        chapter=chapter.label or chapter.title,
                        quote=_quote(paragraph, word),
                        path=chapter.source,
                    )
                    seen[key] = finding
                    report.findings.append(finding)
                finding.count += 1
        if progress:
            progress.step(index, len(chapters), f"Глава {index} из {len(chapters)}")

    report.known = len(extra)
    # Частое слово чаще всего и есть имя, которое стоит внести в словарь, —
    # такие показываем первыми.
    report.findings.sort(key=lambda f: (-f.count, f.word.lower()))
    # Подсказки считаются только для показанных находок: перебор вариантов —
    # самая дорогая часть, и делать его для тысяч невидимых слов незачем.
    for finding in report.findings[:LIMIT]:
        finding.suggestions = words.suggest(finding.word)
    return report


def state(folder) -> dict:
    """Что уже внесено в свой словарь — для интерфейса."""
    words = load_words(folder)
    return {"available": available(), "suggestions": suggestions_available(),
            "words": words, "count": len(words),
            "path": str(dict_path(folder)) if folder else ""}


def export_words(folder) -> str:
    return json.dumps(load_words(folder), ensure_ascii=False, indent=2)
