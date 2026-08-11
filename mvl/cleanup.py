"""Очистка текста от мусора, найденного проверкой.

После проверки должно быть действие, а не только список проблем. Здесь —
безопасные автоматические замены.

Иероглифы и латиницу не трогаем принципиально: их надо смотреть глазами,
машинально удалять нельзя.

Оригиналы не изменяются — результат пишется в новую папку.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .booksplit import Cancelled
from .rename import safe_filename
from .textcheck import MODEL_TRACES, READABLE, read_lines

log = logging.getLogger(__name__)

# Остатки markdown: снимаем разметку, текст внутри сохраняем.
MARKDOWN_RULES = (
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"\1"),
    (re.compile(r"__(.+?)__", re.S), r"\1"),
    (re.compile(r"~~(.+?)~~", re.S), r"\1"),
    (re.compile(r"`([^`\n]+?)`"), r"\1"),
    (re.compile(r"\[([^\]]+?)\]\([^)]*?\)", re.S), r"\1"),
    (re.compile(r"^\s*#{1,6}\s+"), ""),
    (re.compile(r"^\s*>\s?"), ""),
)

# HTML-теги и сущности.
HTML_RULES = (
    (re.compile(r"</?(?:p|br|span|div|em|strong|i|b)\b[^>]*>", re.I), ""),
    (re.compile(r"&nbsp;"), " "),
    (re.compile(r"&amp;"), "&"),
    (re.compile(r"&quot;"), '"'),
    (re.compile(r"&lt;"), "<"),
    (re.compile(r"&gt;"), ">"),
    (re.compile(r"&#(\d+);"), lambda m: _entity(m.group(1))),
)

NBSP = " "
REPLACEMENT = "�"

#: Полноширинные азиатские знаки, оставшиеся от оригинала. Замена
#: безопасная: смысл текста не меняется, поэтому её можно делать машинально
#: — в отличие от самих иероглифов.
FULLWIDTH_MAP = {
    "【": "[", "】": "]",      # 【 】
    "（": "(", "）": ")",      # （ ）
    "《": "«", "》": "»",  # 《 》
    "，": ",", "。": ".",      # ， 。
    "：": ":", "；": ";",      # ： ；
    "！": "!", "？": "?",      # ！ ？
    "　": " ",                     # полноширинный пробел
    "．": ".", "～": "~",
    "「": "«", "」": "»",  # 「 」
}

#: Ключ → подпись в интерфейсе.
KINDS = {
    "markdown": "Остатки markdown",
    "html": "HTML-теги и entity",
    "nbsp": "Неразрывные пробелы",
    "broken": "Битые символы",
    "model": "Следы модели-переводчика",
    "dupes": "Повторяющиеся абзацы",
    "blanks": "Лишние пустые строки",
    "fullwidth": "Полноширинные знаки → обычные",
}
ALL_KINDS = tuple(KINDS)


def _entity(code: str) -> str:
    try:
        return chr(int(code))
    except (ValueError, OverflowError):
        return ""


class CleanError(Exception):
    """Очистить не удалось."""


@dataclass
class CleanReport:
    output_dir: str = ""
    files: int = 0
    written: int = 0
    failed: int = 0
    counts: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def as_dict(self) -> dict:
        return {
            "output_dir": self.output_dir,
            "files": self.files,
            "written": self.written,
            "failed": self.failed,
            "total": self.total,
            "counts": [
                {"kind": k, "kind_name": KINDS.get(k, k), "count": v}
                for k, v in sorted(self.counts.items(), key=lambda kv: -kv[1])
                if v
            ],
            "failed_files": self.failures,
        }


def clean_lines(lines: list[str], kinds: set[str]) -> tuple[list[str], dict]:
    """Применяет выбранные правила. Возвращает строки и счётчик замен."""
    counts = dict.fromkeys(kinds, 0)
    result = list(lines)

    if "markdown" in kinds:
        result, counts["markdown"] = _apply(result, MARKDOWN_RULES)
    if "html" in kinds:
        result, counts["html"] = _apply(result, HTML_RULES)

    if "nbsp" in kinds:
        counts["nbsp"] = sum(line.count(NBSP) for line in result)
        result = [line.replace(NBSP, " ") for line in result]

    if "broken" in kinds:
        counts["broken"] = sum(line.count(REPLACEMENT) for line in result)
        result = [line.replace(REPLACEMENT, "") for line in result]

    if "fullwidth" in kinds:
        total = 0
        replaced = []
        for line in result:
            for wide, plain in FULLWIDTH_MAP.items():
                if wide in line:
                    total += line.count(wide)
                    line = line.replace(wide, plain)
            replaced.append(line)
        result, counts["fullwidth"] = replaced, total

    if "model" in kinds:
        kept = []
        removed = 0
        for line in result:
            # Строку со следом модели убираем целиком — это не часть текста.
            if line.strip() and any(p.search(line) for p in MODEL_TRACES):
                removed += 1
                continue
            kept.append(line)
        result, counts["model"] = kept, removed

    if "dupes" in kinds:
        kept = []
        removed = 0
        previous = None
        for line in result:
            stripped = line.strip()
            if stripped and stripped == previous:
                removed += 1
                continue
            if stripped:
                previous = stripped
            kept.append(line)
        result, counts["dupes"] = kept, removed

    if "blanks" in kinds:
        kept = []
        blanks = 0
        removed = 0
        for line in result:
            if not line.strip():
                blanks += 1
                # Три и более подряд схлопываем в одну пустую.
                if blanks >= 3:
                    removed += 1
                    continue
                if blanks == 2:
                    removed += 1
                    continue
            else:
                blanks = 0
            kept.append(line)
        result, counts["blanks"] = kept, removed

    return result, counts


def _apply(lines: list[str], rules) -> tuple[list[str], int]:
    """Прогоняет набор правил, считая срабатывания."""
    total = 0
    result = []
    for line in lines:
        for pattern, replacement in rules:
            line, count = pattern.subn(replacement, line)
            total += count
        result.append(line)
    return result, total


def collect(target: str | Path) -> list[Path]:
    """Файлы, которые будем чистить."""
    path = Path(target).expanduser()
    if path.is_dir():
        files = [
            p for p in sorted(path.iterdir())
            if p.is_file() and p.suffix.lower() in READABLE and p.name.lower() != "whitelist.txt"
        ]
    elif path.is_file():
        files = [path]
    else:
        raise CleanError(f"Не найдено: {path}")

    if not files:
        raise CleanError("Нет файлов для очистки")
    return files


def preview(target: str | Path, kinds) -> dict:
    """Сколько замен будет сделано — до того, как что-то записано."""
    kinds = _validate(kinds)
    counts: dict = dict.fromkeys(kinds, 0)
    unreadable = []

    for path in collect(target):
        try:
            _, found = clean_lines(read_lines(path), kinds)
        except Exception as exc:
            unreadable.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        for key, value in found.items():
            counts[key] = counts.get(key, 0) + value

    return {
        "counts": [
            {"kind": k, "kind_name": KINDS.get(k, k), "count": v}
            for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
        ],
        "total": sum(counts.values()),
        "unreadable": unreadable,
    }


def _validate(kinds) -> set[str]:
    kinds = set(kinds or ())
    if not kinds:
        raise CleanError("Отметьте, что именно чистить")
    unknown = kinds - set(ALL_KINDS)
    if unknown:
        raise CleanError(f"Неизвестная очистка: {', '.join(sorted(unknown))}")
    return kinds


def clean(
    target: str | Path,
    kinds,
    output_dir: Path,
    on_progress=None,
    cancel: threading.Event | None = None,
) -> CleanReport:
    """Чистит файлы и пишет результат в новую папку."""
    kinds = _validate(kinds)
    files = collect(target)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = CleanReport(output_dir=str(output_dir), files=len(files))
    report.counts = dict.fromkeys(kinds, 0)

    for index, path in enumerate(files, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        try:
            lines, found = clean_lines(read_lines(path), kinds)
            for key, value in found.items():
                report.counts[key] = report.counts.get(key, 0) + value

            # Результат всегда текстовый: очищенный .docx собирать незачем,
            # а .txt открывается чем угодно.
            name = safe_filename(path.stem) or f"{index:04d}"
            (output_dir / f"{name}.txt").write_text(
                "\n".join(lines).strip() + "\n", encoding="utf-8"
            )
            report.written += 1
        except Exception as exc:
            log.warning("Не очищен %s: %s", path.name, exc)
            report.failed += 1
            report.failures.append(f"{path.name}: {type(exc).__name__}: {exc}")

        if on_progress:
            on_progress(index, len(files))

    return report
