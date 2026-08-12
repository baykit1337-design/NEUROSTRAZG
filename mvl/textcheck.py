"""Проверка готового перевода на мусор.

Ничего не исправляет — только показывает, где смотреть. Каждый тип проверки
включается своей галочкой.
"""

from __future__ import annotations

import logging
import re
import statistics
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import checks
from .booksplit import Cancelled
from .source import SourceError
from .source import read_paragraphs as read_source_paragraphs

log = logging.getLogger(__name__)

#: Форматы, которые принимает проверка. epub разбирается как архив.
READABLE = (".txt", ".md", ".docx", ".epub")
#: Сколько символов вокруг находки показывать в таблице.
CONTEXT = 60
WHITELIST_FILE = "whitelist.txt"

# 1. Иероглифы и азиатские алфавиты — непереведённые куски.
CJK = re.compile(
    "["
    "一-鿿"   # китайские иероглифы
    "㐀-䶿"   # китайские, расширение A
    "가-힯"   # корейский хангыль
    "ᄀ-ᇿ"   # корейские джамо
    "぀-ゟ"   # японская хирагана
    "゠-ヿ"   # японская катакана
    "　-〿"   # восточноазиатская пунктуация
    "＀-￯"   # полноширинные формы
    "]+"
)

# 2. Остатки markdown.
MARKDOWN = [
    re.compile(r"\*\*"),
    re.compile(r"__"),
    re.compile(r"~~"),
    re.compile(r"`"),
    re.compile(r"^\s*#{1,6}\s"),
    re.compile(r"\[[^\]]+\]\([^)]*\)"),
    re.compile(r"^\s*>"),
    re.compile(r"^\s*-{3,}\s*$"),
]

# 3. Латиница в русском тексте — слова из трёх и более букв.
LATIN_WORD = re.compile(r"\b[A-Za-z][A-Za-z'’-]{2,}\b")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

#: Адреса, HTML-теги и сущности сами по себе латиница, но ловить их как
#: «непереведённое слово» бессмысленно — они уже видны в своих проверках.
NOISE = re.compile(r"https?://\S+|www\.\S+|</?[a-zA-Z][^>]*>|&[a-zA-Z]+;|&#\d+;|\([^)\s]*\)")


def _mask_noise(line: str) -> str:
    """Затирает адреса и разметку пробелами, сохраняя позиции символов."""
    return NOISE.sub(lambda m: " " * len(m.group(0)), line)

# 4. Следы работы модели-переводчика.
MODEL_TRACES = [
    re.compile(r"\bNote:", re.I),
    re.compile(r"Translator'?s note", re.I),
    re.compile(r"Примечани[ея] переводчика", re.I),
    re.compile(r"Вот перевод", re.I),
    re.compile(r"Here is the translation", re.I),
    re.compile(r"I hope this helps", re.I),
    re.compile(r"\bAs an AI\b", re.I),
    re.compile(r"```"),
    re.compile(r"</?thinking>", re.I),
]

# 5. Битая кодировка и HTML.
BROKEN = [
    re.compile("�"),
    re.compile(" "),
    re.compile(r"&nbsp;|&amp;|&quot;|&#\d+;"),
    re.compile(r"</?(?:p|br|span)\b[^>]*>", re.I),
]

#: Парные знаки для проверки 8. Одиночный апостроф не считаем: он часто
#: встречается внутри слов и давал ложные срабатывания.
PAIRS = (("«", "»"), ("„", "“"), ("(", ")"), ("[", "]"), ("{", "}"), ("【", "】"))

#: Сколько абзацев может занимать блок в скобках, прежде чем это станет
#: подозрительным. Игровые сообщения новеллы законно тянутся на несколько.
MAX_BRACKET_SPAN = 10

#: Ключ проверки → как называется в отчёте. Реестр правил живёт в checks.py.
KINDS = {rule.key: rule.name for rule in checks.RULES}
ALL_KINDS = tuple(KINDS)

#: Файл короче этого — подозрительный (пункт 7).
MIN_CHARS = 500
#: Во столько раз можно отличаться от медианы, прежде чем это станет подозрительным.
SIZE_FACTOR = 3
#: Столько одинаковых абзацев подряд считаем зацикливанием (пункт 6).
LOOP_REPEATS = 3


class CheckError(Exception):
    """Проверить не удалось."""


@dataclass
class Finding:
    file: str
    line: int
    kind: str
    fragment: str
    #: Абзац целиком — разворачивается по клику в интерфейсе.
    context: str = ""
    #: Полный путь: по двойному клику файл открывается в Word или редакторе.
    path: str = ""

    @property
    def kind_name(self) -> str:
        return KINDS.get(self.kind, self.kind)

    def as_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "kind": self.kind,
            "kind_name": self.kind_name,
            "fragment": self.fragment,
            "context": self.context or self.fragment,
            "path": self.path,
        }


@dataclass
class CheckReport:
    findings: list[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    latin_words: list = field(default_factory=list)
    files_checked: int = 0
    files_with_findings: int = 0
    unreadable: list = field(default_factory=list)
    #: Группы вариантов одного имени и статистика по видам кавычек.
    name_groups: list = field(default_factory=list)
    quote_kinds: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "findings": [f.as_dict() for f in self.findings],
            "summary": [
                {"kind": k, "kind_name": KINDS.get(k, k), "count": v}
                for k, v in sorted(self.summary.items(), key=lambda kv: -kv[1])
            ],
            "latin_words": self.latin_words,
            "files_checked": self.files_checked,
            "files_with_findings": self.files_with_findings,
            "unreadable": self.unreadable,
            "name_groups": self.name_groups,
            "quote_kinds": self.quote_kinds,
            "total": len(self.findings),
        }


def read_lines(path: Path) -> list[str]:
    """Строки файла.

    Для .docx строкой считается абзац, для .epub — абзац всех его глав.
    Открывать epub как текст нельзя: это ZIP-архив, и в проверку летели
    сырые байты вида `??v????A`.
    """
    suffix = path.suffix.lower()
    if suffix in (".docx", ".epub"):
        try:
            return read_source_paragraphs(path)
        except SourceError as exc:
            raise CheckError(str(exc)) from exc
    # Битая кодировка — как раз то, что ищем, поэтому errors='replace'.
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def load_whitelist(folder: Path) -> set[str]:
    """Слова-исключения для проверки латиницы: имена собственные и прочее."""
    for candidate in (folder / WHITELIST_FILE, Path.cwd() / WHITELIST_FILE):
        if candidate.is_file():
            words = candidate.read_text(encoding="utf-8", errors="replace").split()
            return {w.strip().lower() for w in words if w.strip()}
    return set()


def _fragment(line: str, start: int, end: int) -> str:
    """Кусок строки вокруг находки — CONTEXT символов с запасом по краям."""
    half = max(0, (CONTEXT - (end - start)) // 2)
    left = max(0, start - half)
    right = min(len(line), end + half)
    piece = line[left:right].strip()
    return ("…" if left > 0 else "") + piece + ("…" if right < len(line) else "")


def check_file(
    path: Path,
    kinds: set[str],
    whitelist: set[str] | None = None,
    latin_counter: Counter | None = None,
    max_span: int = MAX_BRACKET_SPAN,
    glossary: dict | None = None,
    name_counter: Counter | None = None,
    quote_counter: Counter | None = None,
) -> list[Finding]:
    """Проверки, которым хватает одного файла. Объём считается отдельно."""
    whitelist = whitelist or set()
    glossary = glossary or {}
    name_counter = name_counter if name_counter is not None else Counter()
    quote_counter = quote_counter if quote_counter is not None else Counter()
    lines = read_lines(path)
    name = path.name
    found: list[Finding] = []
    #: Кандидаты на «заглавную посреди предложения» и имена этой главы.
    mid_candidates: list[tuple] = []
    local_names: Counter = Counter()

    full_path = str(path)

    def add(number: int, kind: str, line: str, start: int, end: int):
        found.append(Finding(
            name, number, kind, _fragment(line, start, end),
            context=line.strip(), path=full_path,
        ))

    for number, line in enumerate(lines, 1):
        if "cjk" in kinds:
            for match in CJK.finditer(line):
                add(number, "cjk", line, match.start(), match.end())

        if "markdown" in kinds:
            for pattern in MARKDOWN:
                match = pattern.search(line)
                if match:
                    add(number, "markdown", line, match.start(), match.end())
                    break

        if "model" in kinds:
            for pattern in MODEL_TRACES:
                match = pattern.search(line)
                if match:
                    add(number, "model", line, match.start(), match.end())
                    break

        if "broken" in kinds:
            for pattern in BROKEN:
                match = pattern.search(line)
                if match:
                    add(number, "broken", line, match.start(), match.end())
                    break

        if "latin" in kinds and CYRILLIC.search(line):
            # Латиница интересна только внутри русского текста и только вне
            # адресов и разметки — фрагмент при этом берём из исходной строки.
            for match in LATIN_WORD.finditer(_mask_noise(line)):
                word = match.group(0)
                if word.lower() in whitelist:
                    continue
                if latin_counter is not None:
                    latin_counter[word] += 1
                add(number, "latin", line, match.start(), match.end())

        # ---- группа «Перевод» ----
        if "homoglyph" in kinds:
            for match, _ in checks.mixed_script_words(line):
                add(number, "homoglyph", line, match.start(), match.end())

        if "untranslated" in kinds:
            for match, _ in checks.untranslated_sentences(line):
                add(number, "untranslated", line, match.start(), match.end())

        if "imperial" in kinds:
            for match in checks.IMPERIAL.finditer(line):
                add(number, "imperial", line, match.start(), match.end())

        if "glossary" in kinds and glossary:
            for start, end, source, target in checks.glossary_misses(line, glossary):
                found.append(Finding(
                    name, number, "glossary",
                    f"«{source}» → по глоссарию «{target}»",
                    context=line.strip(), path=full_path,
                ))

        if "names" in kinds:
            checks.collect_proper_names(line, name_counter)

        # ---- группа «Пунктуация и типографика» ----
        if "dialog_dash" in kinds and checks.DIALOG_DASH.match(line):
            add(number, "dialog_dash", line, 0, min(len(line), 3))

        if "three_dots" in kinds:
            match = checks.THREE_DOTS.search(line)
            if match:
                add(number, "three_dots", line, match.start(), match.end())

        if "spaces" in kinds:
            for pattern in (checks.DOUBLE_SPACE, checks.SPACE_BEFORE_PUNCT):
                match = pattern.search(line)
                if match:
                    add(number, "spaces", line, match.start(), match.end())
                    break

        if "no_space" in kinds:
            match = checks.NO_SPACE_AFTER.search(line)
            if match:
                add(number, "no_space", line, match.start(), min(len(line), match.end() + 1))

        if "multi_punct" in kinds:
            match = checks.MULTI_PUNCT.search(line)
            if match:
                add(number, "multi_punct", line, match.start(), match.end())

        if "edge_space" in kinds and line and checks.EDGE_SPACE.search(line):
            add(number, "edge_space", line, 0, min(len(line), 24))

        if "hyphen_dash" in kinds:
            match = checks.HYPHEN_AS_DASH.search(line)
            if match:
                add(number, "hyphen_dash", line, match.start(), match.end())

        if "quotes" in kinds:
            for label, marks in checks.QUOTE_KINDS.items():
                for mark in marks:
                    if mark in line:
                        quote_counter[label] += line.count(mark)

        # ---- группа «Структура» ----
        if "repeated_word" in kinds:
            match = checks.REPEATED_WORD.search(line)
            if match:
                add(number, "repeated_word", line, match.start(), match.end())

        if "no_end" in kinds and line.strip() and not line.rstrip().endswith(checks.SENTENCE_END):
            add(number, "no_end", line, max(0, len(line) - 30), len(line))

        if "long_paragraph" in kinds and len(line) > checks.LONG_PARAGRAPH:
            found.append(Finding(
                name, number, "long_paragraph",
                f"{len(line)} символов в одном абзаце",
                context=line.strip(), path=full_path,
            ))

        if "caps_line" in kinds and checks.is_all_caps(line):
            add(number, "caps_line", line, 0, min(len(line), 40))

        if "mid_capital" in kinds:
            for match, word in checks.find_capital_mid_sentence(line):
                # Решение отложено: слово может оказаться именем собственным,
                # а это станет видно только по всей главе.
                mid_candidates.append((number, line, match.start(), match.end(), word))
                local_names[word] += 1

        # ---- группа «Технический мусор» ----
        if "fullwidth" in kinds:
            match = checks.FULLWIDTH.search(line)
            if match:
                add(number, "fullwidth", line, match.start(), match.end())


    if "loop" in kinds:
        found.extend(_loops(name, lines))

    if "pairs" in kinds:
        found.extend(_unbalanced(name, lines, max_span))

    if "mid_capital" in kinds:
        # Имя, встреченное в главе не раз, — это имя собственное, а не ошибка.
        # Без этого отсева проверка давала тысячи находок на каждом «сказал Тео».
        for number, line, start, end, word in mid_candidates:
            if local_names[word] >= checks.KNOWN_NAME_COUNT:
                continue
            add(number, "mid_capital", line, start, end)

    if "empty_chapter" in kinds:
        filled = [line for line in lines if line.strip()]
        if not filled:
            found.append(Finding(name, 1, "empty_chapter", "глава пустая"))
        elif len(filled) == 1:
            found.append(Finding(
                name, 1, "empty_chapter",
                f"глава из одного абзаца: {filled[0].strip()[:CONTEXT]}",
            ))

    # Путь и контекст проставляем всем разом: часть проверок работает не
    # по строке, а по файлу целиком.
    for finding in found:
        finding.path = finding.path or full_path
        if not finding.context:
            index = finding.line - 1
            finding.context = lines[index].strip() if 0 <= index < len(lines) else finding.fragment

    return found


def _unbalanced(name: str, lines: list[str], max_span: int = MAX_BRACKET_SPAN) -> list[Finding]:
    """Непарные скобки и кавычки — по балансу **всего файла**.

    Считать в пределах абзаца нельзя: игровые сообщения новеллы вида
    `{Распределение:` законно тянутся на несколько абзацев, закрывающая
    скобка стоит через два-три. Поэтому ведём стек открытых скобок по всему
    файлу и ругаемся только если скобка так и не закрылась — либо если блок
    растянулся дольше, чем `max_span` абзацев.
    """
    found: list[Finding] = []
    # Стек открытых скобок: (символ, номер строки).
    stack: list[tuple[str, int]] = []
    openers = {left: right for left, right in PAIRS}
    closers = {right: left for left, right in PAIRS}

    for number, line in enumerate(lines, 1):
        for char in line:
            if char in openers:
                stack.append((char, number))
            elif char in closers:
                wanted = closers[char]
                # Ищем ближайшую подходящую открывающую.
                for index in range(len(stack) - 1, -1, -1):
                    if stack[index][0] == wanted:
                        opened_at = stack[index][1]
                        span = number - opened_at
                        if span > max_span:
                            found.append(Finding(
                                name, opened_at, "pairs",
                                f"блок {wanted}{char} растянут на {span} строк "
                                f"(строки {opened_at}–{number})",
                            ))
                        del stack[index]
                        break
                else:
                    found.append(Finding(
                        name, number, "pairs",
                        f"закрывающая {char} без открывающей: {line.strip()[:CONTEXT]}",
                    ))

    for char, number in stack:
        found.append(Finding(
            name, number, "pairs",
            f"открывающая {char} осталась незакрытой: "
            f"{lines[number - 1].strip()[:CONTEXT]}",
        ))

    # Прямые кавычки одинаковы с обеих сторон — считаем чётность по файлу.
    doubles = sum(line.count('"') for line in lines)
    if doubles % 2:
        found.append(Finding(name, 1, "pairs", f'нечётное число кавычек " в файле: {doubles}'))

    return found


def _loops(name: str, lines: list[str]) -> list[Finding]:
    """Один и тот же абзац подряд три раза и больше."""
    found: list[Finding] = []
    previous, start, count = None, 0, 0

    def flush():
        if previous and count >= LOOP_REPEATS:
            found.append(
                Finding(name, start, "loop", f"{count}× подряд: {previous.strip()[:CONTEXT]}")
            )

    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == previous:
            count += 1
            continue
        flush()
        previous, start, count = stripped, number, 1
    flush()
    return found


def check(
    target: str | Path,
    kinds=None,
    on_progress=None,
    cancel: threading.Event | None = None,
    max_span: int = MAX_BRACKET_SPAN,
) -> CheckReport:
    """Проверяет папку или один файл."""
    kinds = set(kinds or ALL_KINDS)
    unknown = kinds - set(ALL_KINDS)
    if unknown:
        raise CheckError(f"Неизвестная проверка: {', '.join(sorted(unknown))}")

    # Принимаем один путь или сразу несколько: файлы и папки вперемешку.
    targets = [target] if isinstance(target, (str, Path)) else list(target)
    if not targets:
        raise CheckError("Выберите файлы или папку")

    files: list[Path] = []
    seen: set[str] = set()
    folder = Path.cwd()

    for item in targets:
        path = Path(str(item)).expanduser()
        if path.is_dir():
            found = [
                p for p in sorted(path.iterdir())
                # Список исключений — служебный файл, а не глава книги.
                if p.is_file() and p.suffix.lower() in READABLE
                and p.name.lower() != WHITELIST_FILE
            ]
            folder = path
        elif path.is_file():
            # Расширение проверяем и здесь: раньше одиночный epub
            # проваливался в текстовое чтение и давал тысячи мусорных находок.
            if path.suffix.lower() not in READABLE:
                raise CheckError(f"{path.name}: нужен .txt, .md, .docx или .epub")
            found = [path]
            folder = path.parent
        else:
            raise CheckError(f"Не найдено: {path}")

        for candidate in found:
            key = str(candidate.resolve())
            if key not in seen:
                seen.add(key)
                files.append(candidate)

    if not files:
        raise CheckError("Нет файлов .txt, .md, .docx или .epub")

    whitelist = load_whitelist(folder) if "latin" in kinds else set()
    glossary = checks.load_glossary(folder) if "glossary" in kinds else {}
    latin_counter: Counter = Counter()
    # Разнобой имён и кавычек виден только по книге целиком.
    name_counter: Counter = Counter()
    quote_counter: Counter = Counter()
    report = CheckReport(files_checked=len(files))
    sizes: dict[Path, int] = {}
    per_file: dict[str, list[Finding]] = {}

    for index, file_path in enumerate(files, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        try:
            found = check_file(
                file_path, kinds, whitelist, latin_counter, max_span,
                glossary, name_counter, quote_counter,
            )
            sizes[file_path] = sum(len(line) for line in read_lines(file_path))
            per_file.setdefault(file_path.name, []).extend(found)
        except Exception as exc:
            # Один нечитаемый файл не должен прерывать проверку остальных.
            log.warning("Не проверен %s: %s", file_path.name, exc)
            report.unreadable.append(f"{file_path.name}: {type(exc).__name__}: {exc}")
        if on_progress:
            on_progress(index, len(files))

    if "names" in kinds:
        # Варианты одного имени считаем по всей книге, иначе не видно разнобоя.
        for group in checks.name_variants(name_counter):
            variants = ", ".join(f"{word} ×{count}" for word, count in group)
            report.name_groups.append([{"word": w, "count": c} for w, c in group])
            per_file.setdefault("— по всей книге —", []).append(
                Finding("— по всей книге —", 1, "names", f"варианты: {variants}")
            )

    if "quotes" in kinds:
        used = {label: count for label, count in quote_counter.items() if count}
        if len(used) > 1:
            listing = ", ".join(f"{label} ×{count}" for label, count in used.items())
            report.quote_kinds = [{"kind": k, "count": v} for k, v in used.items()]
            per_file.setdefault("— по всей книге —", []).append(
                Finding("— по всей книге —", 1, "quotes", f"в тексте смешаны: {listing}")
            )

    if "size" in kinds and sizes:
        for finding in _size_findings(sizes):
            per_file.setdefault(finding.file, []).append(finding)

    for file_name in sorted(per_file):
        report.findings.extend(sorted(per_file[file_name], key=lambda f: (f.line, f.kind)))

    report.summary = dict(Counter(f.kind for f in report.findings))
    # Файлы без находок в таблицу не попадают.
    report.files_with_findings = len({f.file for f in report.findings})
    report.latin_words = [
        {"word": word, "count": count} for word, count in latin_counter.most_common()
    ]
    return report


def _size_findings(sizes: dict[Path, int]) -> list[Finding]:
    """Слишком короткие файлы и сильно отличающиеся от медианы по книге."""
    found: list[Finding] = []
    median = statistics.median(sizes.values()) if sizes else 0

    for path, size in sizes.items():
        if size < MIN_CHARS:
            found.append(Finding(path.name, 1, "size", f"всего {size} символов"))
        elif median and (size > median * SIZE_FACTOR or size * SIZE_FACTOR < median):
            found.append(
                Finding(path.name, 1, "size",
                        f"{size} символов при медиане {int(median)} по книге")
            )
    return found


def report_text(report: CheckReport) -> str:
    """Отчёт для выгрузки в .txt."""
    lines = [
        "Проверка текста",
        f"Файлов проверено: {report.files_checked}",
        f"Файлов с находками: {report.files_with_findings}",
        f"Всего находок: {len(report.findings)}",
        "",
        "Сводка по типам:",
    ]
    for row in report.as_dict()["summary"]:
        lines.append(f"  {row['kind_name']}: {row['count']}")

    if report.latin_words:
        lines += ["", "Латиница — уникальные слова:"]
        lines += [f"  {row['word']}  ×{row['count']}" for row in report.latin_words]

    if report.unreadable:
        lines += ["", "Не удалось прочитать:"] + [f"  {row}" for row in report.unreadable]

    lines += ["", "Находки:"]
    current = None
    for finding in report.findings:
        if finding.file != current:
            current = finding.file
            lines.append(f"\n{current}")
        lines.append(f"  строка {finding.line} · {finding.kind_name} · {finding.fragment}")

    return "\n".join(lines) + "\n"
