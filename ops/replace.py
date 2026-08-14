"""Пакетная замена по папке и свой словарь автозамен.

Переводчик назвал персонажа иначе в двухстах главах — вручную это чинится
день, отсюда и модуль.

Предпросмотр обязателен: замена по всей книге необратима, а регулярное
выражение легко написать шире, чем задумывалось. Поэтому сначала список
всех совпадений с контекстом, и только потом запись — в новую папку.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from core import formats, naming
from core.models import Chapter, OpReport

from .base import Progress, collect_files, read_all

#: Имя словаря автозамен. Свой у каждой книги — лежит рядом с ней.
DICT_FILE = "replacements.txt"

#: Сколько символов вокруг совпадения показывать в предпросмотре.
CONTEXT = 50

#: Больше этого числа совпадений в интерфейс не отдаём: список на сто
#: тысяч строк всё равно не просмотреть, а браузер он вешает.
MAX_MATCHES = 2000


class ReplaceError(Exception):
    """Правило замены не удалось применить."""


@dataclass
class Rule:
    """Одно правило: что искать и на что менять."""

    find: str
    replace: str = ""
    regex: bool = False
    case: bool = False

    def compile(self):
        flags = 0 if self.case else re.IGNORECASE
        pattern = self.find if self.regex else re.escape(self.find)
        try:
            return re.compile(pattern, flags)
        except re.error as exc:
            raise ReplaceError(
                f"Неверное регулярное выражение «{self.find}»: {exc}") from exc

    def apply(self, text: str):
        """Возвращает новый текст и число замен."""
        return self.compile().subn(self._replacement(), text)

    def _replacement(self) -> str:
        # При обычной замене экранируем правую часть: «\1» в ней должно
        # означать сам текст, а не группу, которой пользователь не задавал.
        return self.replace if self.regex else self.replace.replace("\\", "\\\\")

    def expand(self, found) -> str:
        """Замена для одного совпадения, с подстановкой групп."""
        return found.expand(self._replacement()) if self.regex else self.replace

    @classmethod
    def from_dict(cls, data: dict) -> Rule:
        return cls(
            find=str((data or {}).get("find") or ""),
            replace=str((data or {}).get("replace") or ""),
            regex=bool((data or {}).get("regex")),
            case=bool((data or {}).get("case")),
        )

    def as_dict(self) -> dict:
        return {"find": self.find, "replace": self.replace,
                "regex": self.regex, "case": self.case}


@dataclass
class Match:
    """Одно совпадение — то, что человек видит в предпросмотре."""

    file: str
    chapter: str = ""
    paragraph: int = 0
    before: str = ""
    after: str = ""
    rule: int = 0
    #: Какое по счёту совпадение этого правила в этом абзаце. Без него
    #: снятая галочка отменяла бы замену во всём абзаце разом.
    index: int = 0

    def as_dict(self) -> dict:
        return {"file": self.file, "chapter": self.chapter,
                "paragraph": self.paragraph, "before": self.before,
                "after": self.after, "rule": self.rule, "index": self.index}


@dataclass
class Preview:
    matches: list[Match] = field(default_factory=list)
    files: int = 0
    touched: int = 0
    total: int = 0
    unreadable: list = field(default_factory=list)
    by_rule: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "matches": [m.as_dict() for m in self.matches],
            "files": self.files, "touched": self.touched, "total": self.total,
            "shown": len(self.matches),
            "unreadable": self.unreadable,
            "by_rule": self.by_rule,
        }


def _fragment(text: str, start: int, end: int) -> str:
    left = max(0, start - CONTEXT)
    right = min(len(text), end + CONTEXT)
    piece = text[left:right]
    return ("…" if left else "") + piece + ("…" if right < len(text) else "")


def preview(targets, rules, progress: Progress | None = None) -> Preview:
    """Все совпадения с контекстом. На диск ничего не пишется."""
    rules = [r if isinstance(r, Rule) else Rule.from_dict(r) for r in rules]
    rules = [r for r in rules if r.find]
    if not rules:
        raise ReplaceError("Нечего искать: правило пустое")

    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report, progress)

    result = Preview(files=len(files),
                     unreadable=[f.as_text() for f in report.failures])
    touched: set[str] = set()

    for chapter in chapters:
        hit = False
        for index, paragraph in enumerate(chapter.paragraphs):
            for number, rule in enumerate(rules):
                pattern = rule.compile()
                order = 0
                for found in pattern.finditer(paragraph):
                    if not found.group(0):
                        # Пустое совпадение: правило вроде «a*» найдёт его
                        # между каждыми двумя буквами и завалит предпросмотр.
                        continue
                    hit = True
                    result.total += 1
                    result.by_rule[str(number)] = result.by_rule.get(str(number), 0) + 1
                    if len(result.matches) < MAX_MATCHES:
                        replaced, _ = rule.apply(found.group(0))
                        result.matches.append(Match(
                            file=Path(chapter.source).name if chapter.source else "",
                            chapter=chapter.label or chapter.title,
                            paragraph=index + 1,
                            before=_fragment(paragraph, found.start(), found.end()),
                            after=replaced,
                            rule=number,
                            index=order,
                        ))
                    order += 1
        if hit:
            touched.add(chapter.source)

    result.touched = len(touched)
    return result


def apply_to(chapter: Chapter, rules, skip=None) -> tuple[Chapter, int]:
    """Глава с применёнными правилами. Исходная не меняется.

    `skip` — снятые в предпросмотре совпадения, четвёрками «файл, абзац,
    правило, номер совпадения». Номер обязателен: без него снятая галочка
    отменяла бы замену во всём абзаце, а не в одном месте.
    """
    skip = set(skip or ())
    count = 0
    paragraphs = []

    for index, paragraph in enumerate(chapter.paragraphs):
        text = paragraph
        for number, rule in enumerate(rules):
            pattern = rule.compile()
            order = {"n": 0}

            def once(found, rule=rule, number=number, index=index, order=order):
                nonlocal count
                current = order["n"]
                order["n"] += 1
                if (chapter.source, index + 1, number, current) in skip:
                    return found.group(0)
                count += 1
                return rule.expand(found)

            text = pattern.sub(once, text)
        paragraphs.append(text)

    return Chapter(number=chapter.number, part=chapter.part, title=chapter.title,
                   paragraphs=paragraphs, source=chapter.source), count


def run(
    targets,
    output_dir: Path,
    rules,
    skip=None,
    out_format: str = "",
    encoding: str = "utf-8",
    progress: Progress | None = None,
) -> OpReport:
    """Пишет изменённые главы в новую папку. Оригиналы не трогает."""
    rules = [r if isinstance(r, Rule) else Rule.from_dict(r) for r in rules]
    rules = [r for r in rules if r.find]
    if not rules:
        raise ReplaceError("Нечего искать: правило пустое")

    progress = progress or Progress()
    report = OpReport(output=str(output_dir))

    files = collect_files(targets)
    chapters = read_all(files, report, progress)
    if not chapters:
        detail = report.failures[0].as_text() if report.failures else ""
        raise ValueError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    output_dir.mkdir(parents=True, exist_ok=True)
    report.total = len(chapters)
    width = naming.name_width(len(chapters))
    used: set[str] = set()
    replaced = 0

    for index, chapter in enumerate(chapters, 1):
        progress.check()
        changed, made = apply_to(chapter, rules, skip)
        replaced += made

        source = Path(chapter.source) if chapter.source else None
        suffix = out_format or (source.suffix if source else ".txt")
        stem = source.stem if source else \
            f"{index:0{width}d} - {naming.safe_filename(chapter.title)}"
        if f"{stem}{suffix}".lower() in used:
            stem = f"{stem} ({index})"
        used.add(f"{stem}{suffix}".lower())

        try:
            formats.write(output_dir / f"{stem}{suffix}", [changed],
                          headings=True, encoding=encoding, title=changed.title)
            report.written += 1
        except Exception as exc:
            report.fail(f"{stem}{suffix}", "запись", f"{type(exc).__name__}: {exc}")

        progress.step(index, len(chapters), f"Файл {index} из {len(chapters)}")

    report.extra["replaced"] = replaced
    return report


# ------------------------------------------------------- словарь автозамен


def parse_dictionary(text: str) -> list[Rule]:
    """Правила из файла «было = стало».

    Левая часть может быть регулярным выражением — тогда строка помечается
    приставкой `re:`. Без пометки текст ищется как есть, включая точки и
    скобки: иначе «т.е.» неожиданно совпало бы с «тхей».
    """
    rules = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//", ";")):
            continue
        if "=" not in line:
            continue

        left, _, right = line.partition("=")
        left, right = left.strip(), right.strip()
        if not left:
            continue

        regex = False
        if left.lower().startswith("re:"):
            regex = True
            left = left[3:].strip()
        if left:
            rules.append(Rule(find=left, replace=right, regex=regex))
    return rules


def dictionary_path(root: Path) -> Path:
    """Словарь ведётся отдельно для каждой книги — лежит рядом с ней."""
    return Path(root) / DICT_FILE


def load_dictionary(root: Path) -> list[Rule]:
    path = dictionary_path(root)
    if not path.is_file():
        return []
    try:
        return parse_dictionary(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise ReplaceError(f"Не удалось прочитать словарь: {exc}") from exc


def save_dictionary(root: Path, text: str) -> Path:
    path = dictionary_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def dictionary_summary(targets, rules, progress: Progress | None = None) -> dict:
    """Сколько замен даст каждое правило. Сводка до применения."""
    found = preview(targets, rules, progress)
    return {
        "total": found.total,
        "files": found.files,
        "touched": found.touched,
        "rules": [
            {"find": rule.find, "replace": rule.replace, "regex": rule.regex,
             "count": found.by_rule.get(str(index), 0)}
            for index, rule in enumerate(rules)
        ],
    }
