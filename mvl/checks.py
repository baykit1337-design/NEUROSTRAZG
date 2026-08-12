"""Расширенные проверки перевода: правила и группы.

Вынесено из `textcheck.py` отдельно — правил стало много, и держать их
вперемешку с обходом файлов неудобно.

Проверки сгруппированы по смыслу: перевод, пунктуация, структура,
технический мусор. Группы видны в интерфейсе.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

# --------------------------------------------------------------- группы

GROUP_TRANSLATION = "translation"
GROUP_PUNCTUATION = "punctuation"
GROUP_STRUCTURE = "structure"
GROUP_TECH = "tech"

GROUPS = {
    GROUP_TRANSLATION: "Перевод",
    GROUP_PUNCTUATION: "Пунктуация и типографика",
    GROUP_STRUCTURE: "Структура",
    GROUP_TECH: "Технический мусор",
}

#: Пресеты для быстрого выбора.
PRESETS = {
    "quick": "Быстрая",
    "full": "Полная",
    "translation": "Только перевод",
}


@dataclass(frozen=True)
class Rule:
    """Одна проверка: как называется, к какой группе относится, зачем нужна."""

    key: str
    name: str
    group: str
    tip: str


# ------------------------------------------------------------- гомоглифы

#: Буквы, одинаковые на вид в кириллице и латинице. Самая коварная ошибка
#: машинного перевода: слово с подменённой буквой не найдётся поиском и не
#: подчеркнётся проверкой орфографии.
HOMOGLYPHS = {
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "y": "у", "k": "к",
}
LATIN_LETTERS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
CYRILLIC_LETTERS = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def mixed_script_words(line: str):
    """Слова, где кириллица и латиница смешаны в одном слове."""
    for match in WORD.finditer(line):
        word = match.group(0)
        letters = set(word)
        if letters & LATIN_LETTERS and letters & CYRILLIC_LETTERS:
            yield match, word


# --------------------------------------------------- непереведённые куски

SENTENCE = re.compile(r"[^.!?…]+[.!?…]?")
LATIN_WORD = re.compile(r"\b[A-Za-z][A-Za-z'’-]{1,}\b")
CYRILLIC_WORD = re.compile(r"\b[А-Яа-яЁё][А-Яа-яЁё-]*\b")
#: Доля латинских слов, выше которой предложение считаем непереведённым.
UNTRANSLATED_SHARE = 0.5


def untranslated_sentences(line: str):
    """Предложения, где латинских слов больше половины."""
    for match in SENTENCE.finditer(line):
        text = match.group(0).strip()
        if len(text) < 20:
            continue
        latin = len(LATIN_WORD.findall(text))
        cyrillic = len(CYRILLIC_WORD.findall(text))
        if latin and latin > (latin + cyrillic) * UNTRANSLATED_SHARE:
            yield match, text


# ------------------------------------------------- имена собственные

PROPER = re.compile(r"\b[А-ЯЁ][а-яё]{2,}\b")
#: На столько символов могут отличаться варианты одного имени.
NAME_DISTANCE = 2
#: Реже этого имя не считаем за вариант — скорее опечатка одного раза.
NAME_MIN_COUNT = 2


#: Частые слова с заглавной, которые именами не являются. Они проскакивают
#: мимо отсева «начало предложения», когда стоят после запятой или тире.
NOT_NAMES = frozenset("""
что это так как она они оно все всё его ему их им тот та то те там тут
нет да даже если когда потом теперь может надо нужно после перед пока
однако впрочем конечно наконец затем вдруг снова опять просто ведь
""".split())


def collect_proper_names(line: str, counter: Counter) -> None:
    """Копит слова с заглавной буквы, кроме начала предложения."""
    for match in PROPER.finditer(line):
        # Слово в начале строки заглавное просто по правилам письма.
        if match.start() == 0:
            continue
        before = line[: match.start()].rstrip()
        if before.endswith((".", "!", "?", "…", "»", '"', "—", "-", ":")):
            continue
        word = match.group(0)
        if word.lower() in NOT_NAMES:
            continue
        counter[word] += 1


def edit_distance(left: str, right: str, limit: int = NAME_DISTANCE) -> int:
    """Расстояние Левенштейна, обрываем счёт на пороге."""
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (a != b),
            ))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def is_declension(left: str, right: str) -> bool:
    """Одно слово — падежная форма другого.

    «Барон» и «Барона», «Клара» и «Кларе» — это склонение, а не разнобой в
    переводе. Отличаются только окончанием при общем корне.
    """
    short, long_ = sorted((left, right), key=len)
    if long_.startswith(short) and len(long_) - len(short) <= 3:
        return True
    common = 0
    for a, b in zip(left, right):
        if a != b:
            break
        common += 1
    return common >= max(3, min(len(left), len(right)) - 2)


def looks_like_variant(left: str, right: str) -> bool:
    """Похожи ли слова настолько, чтобы счесть их вариантами одного имени.

    Короткие слова требуют совпадения длины и ровно одного отличия: иначе
    «Тео» собирает вокруг себя «Что», «Это» и «Так», которые к именам
    отношения не имеют.
    """
    if is_declension(left, right):
        return False
    distance = edit_distance(left, right)
    if min(len(left), len(right)) < 5:
        return len(left) == len(right) and distance == 1
    return 0 < distance <= NAME_DISTANCE


def name_variants(counter: Counter) -> list[list[tuple[str, int]]]:
    """Группы похожих имён: «Тео» / «Тэо», «Элиас» / «Илиас»."""
    names = [(w, c) for w, c in counter.items() if c >= NAME_MIN_COUNT]
    names.sort(key=lambda item: -item[1])

    groups: list[list[tuple[str, int]]] = []
    taken: set[str] = set()
    for index, (word, count) in enumerate(names):
        if word in taken:
            continue
        group = [(word, count)]
        taken.add(word)
        for other, other_count in names[index + 1:]:
            if other in taken:
                continue
            if looks_like_variant(word.lower(), other.lower()):
                group.append((other, other_count))
                taken.add(other)
        if len(group) > 1:
            groups.append(group)
    return groups


# ------------------------------------------------------------- глоссарий

GLOSSARY_FILE = "glossary.txt"


def load_glossary(folder) -> dict[str, str]:
    """Файл `оригинал = перевод`. Пустой словарь, если файла нет."""
    from pathlib import Path

    for candidate in (Path(folder) / GLOSSARY_FILE, Path.cwd() / GLOSSARY_FILE):
        if not candidate.is_file():
            continue
        pairs: dict[str, str] = {}
        for row in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            row = row.strip()
            if not row or row.startswith("#") or "=" not in row:
                continue
            source, target = row.split("=", 1)
            source, target = source.strip(), target.strip()
            if source and target:
                pairs[source] = target
        return pairs
    return {}


def glossary_misses(line: str, glossary: dict[str, str]):
    """Оригинальный термин остался в тексте вместо перевода."""
    for source, target in glossary.items():
        if not source:
            continue
        position = line.lower().find(source.lower())
        if position >= 0 and target.lower() not in line.lower():
            yield position, position + len(source), source, target


# --------------------------------------------------------- имперские единицы

IMPERIAL = re.compile(
    r"\b\d+[\d\s.,/]*\s*(?:"
    r"мил[ья]|миль|мили|фут(?:ов|а|ы)?|дюйм(?:ов|а|ы)?|"
    r"фунт(?:ов|а|ы)?|ярд(?:ов|а|ы)?|унци[йя]|галлон(?:ов|а|ы)?"
    r")\b",
    re.I,
)

# ------------------------------------------- пунктуация и типографика

#: Дефис вместо длинного тире в начале реплики.
DIALOG_DASH = re.compile(r"^\s*[-–]\s+\S")
#: Три точки вместо многоточия.
THREE_DOTS = re.compile(r"\.\.\.")
#: Два и более пробела подряд.
DOUBLE_SPACE = re.compile(r"  +")
#: Пробел перед знаком препинания.
SPACE_BEFORE_PUNCT = re.compile(r"\s+[.,!?;:](?:\s|$)")
#: Нет пробела после знака — слипшиеся слова.
NO_SPACE_AFTER = re.compile(r"[.,!?;:](?=[А-Яа-яЁёA-Za-z])")
#: Множественные знаки.
MULTI_PUNCT = re.compile(r"[!?]{2,}")
#: Пробелы по краям абзаца.
EDGE_SPACE = re.compile(r"^\s+|\s+$")
#: Дефис вместо тире между словами.
HYPHEN_AS_DASH = re.compile(r"\S\s-\s\S")

#: Виды кавычек, разнобой которых стоит показать.
QUOTE_KINDS = {"«»": ("«", "»"), '""': ('"',), "„“": ("„", "“"), "“”": ("“", "”")}

# ---------------------------------------------------------------- структура

#: Повторяющееся слово подряд: «в в», «что что».
REPEATED_WORD = re.compile(r"\b([^\W\d_]+)(\s+\1)\b", re.I | re.UNICODE)
#: Абзац без завершающего знака — признак обрыва перевода.
SENTENCE_END = (".", "!", "?", "…", ":", "»", '"', "”", ")", "]", "*", "—")
#: Абзац длиннее этого, вероятно, слипся из нескольких.
LONG_PARAGRAPH = 1500
#: Строка целиком капсом длиннее этого — подозрительна.
CAPS_MIN = 30
#: Заглавная посреди предложения.
MID_CAPITAL = re.compile(r"[а-яё]\s+[А-ЯЁ][а-яё]")


def is_all_caps(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    if len(letters) < CAPS_MIN:
        return False
    return all(c.isupper() for c in letters)


#: Сколько раз слово должно встретиться с заглавной, чтобы считаться именем.
KNOWN_NAME_COUNT = 2


def find_capital_mid_sentence(line: str):
    """Заглавная буква там, где предложение не начиналось.

    Возвращает совпадение и само слово: имена собственные отсеиваются
    отдельно, уже зная всю главу.
    """
    for match in MID_CAPITAL.finditer(line):
        word = match.group(0).split()[-1]
        yield match, word


# --------------------------------------------------------------- реестр

RULES: tuple[Rule, ...] = (
    # Перевод
    Rule("homoglyph", "Гомоглифы — латиница внутри слов", GROUP_TRANSLATION,
         "Буквы с o a e p x y k H B M T выглядят одинаково в обеих раскладках. "
         "Слово с подменённой буквой не найдётся поиском и не подчеркнётся "
         "проверкой орфографии."),
    Rule("untranslated", "Непереведённые фрагменты", GROUP_TRANSLATION,
         "Предложения, где латинских слов больше половины — скорее всего, "
         "кусок остался без перевода."),
    Rule("names", "Разнобой в именах собственных", GROUP_TRANSLATION,
         "Варианты одного имени, отличающиеся на 1–2 буквы: Тео и Тэо, "
         "Элиас и Илиас. Показываются группами с числом вхождений."),
    Rule("glossary", "Расхождения с глоссарием", GROUP_TRANSLATION,
         "Термин переведён не так, как записано в glossary.txt рядом с "
         "главами. Формат строки: оригинал = перевод."),
    Rule("imperial", "Имперские единицы", GROUP_TRANSLATION,
         "Мили, футы, дюймы, фунты, ярды. Часто требуют пересчёта в "
         "метрические."),
    Rule("latin", "Латиница в русском тексте", GROUP_TRANSLATION,
         "Английские слова, которые могли остаться без перевода. Часто это "
         "имена — смотреть глазами."),
    Rule("cjk", "Иероглифы и азиатские алфавиты", GROUP_TRANSLATION,
         "Куски текста, оставшиеся непереведёнными: китайские, корейские, "
         "японские символы."),

    # Пунктуация и типографика
    Rule("dialog_dash", "Тире в диалогах", GROUP_PUNCTUATION,
         "Дефис вместо длинного тире в начале реплики: «- Привет» вместо "
         "«— Привет»."),
    Rule("quotes", "Разнобой кавычек", GROUP_PUNCTUATION,
         "В одном файле встречаются «ёлочки», \"прямые\" и „лапки“. "
         "Показывается, каких сколько."),
    Rule("three_dots", "Три точки вместо многоточия", GROUP_PUNCTUATION,
         "«...» вместо «…»."),
    Rule("spaces", "Двойные пробелы и пробел перед знаком", GROUP_PUNCTUATION,
         "Два пробела подряд, а также пробел перед точкой, запятой и "
         "остальными знаками."),
    Rule("no_space", "Нет пробела после знака", GROUP_PUNCTUATION,
         "Слипшиеся слова: «конец.Начало»."),
    Rule("multi_punct", "Множественные знаки", GROUP_PUNCTUATION,
         "«!!!», «???», «?!!» — обычно достаточно одного знака."),
    Rule("edge_space", "Пробелы по краям абзаца", GROUP_PUNCTUATION,
         "Лишние пробелы в начале и в конце абзаца."),
    Rule("hyphen_dash", "Дефис вместо тире между словами", GROUP_PUNCTUATION,
         "« - » вместо « — » в середине предложения."),
    Rule("pairs", "Непарные кавычки и скобки", GROUP_PUNCTUATION,
         "Открывающая есть, закрывающей нет. Считается по файлу целиком, "
         "поэтому многоабзацные игровые блоки не мешают."),

    # Структура
    Rule("repeated_word", "Повторяющиеся слова подряд", GROUP_STRUCTURE,
         "«в в», «и и», «что что» — след сбоя при переводе."),
    Rule("no_end", "Абзац без завершающего знака", GROUP_STRUCTURE,
         "Признак того, что перевод оборвался на середине."),
    Rule("long_paragraph", "Слишком длинный абзац", GROUP_STRUCTURE,
         f"Больше {LONG_PARAGRAPH} символов — вероятно, слиплись несколько."),
    Rule("caps_line", "Строка целиком капсом", GROUP_STRUCTURE,
         f"Длиннее {CAPS_MIN} символов и вся заглавными."),
    Rule("empty_chapter", "Пустые и однострочные главы", GROUP_STRUCTURE,
         "Глава пустая или состоит из одного абзаца — перевод мог не дойти."),
    Rule("mid_capital", "Заглавная посреди предложения", GROUP_STRUCTURE,
         "Заглавная буква там, где предложение не начиналось."),
    Rule("loop", "Зацикливание модели", GROUP_STRUCTURE,
         "Один и тот же абзац повторён три раза подряд и больше. Так бывает, "
         "когда модель «залипает» при переводе."),
    Rule("numbering", "Целостность нумерации", GROUP_STRUCTURE,
         "Пропуски, дубли номеров, пропущенные части и главы, выпадающие из "
         "диапазона. Работает по именам файлов и текст не читает."),
    Rule("dupes", "Повторяющиеся главы", GROUP_STRUCTURE,
         "Главы с одинаковым или почти одинаковым текстом. Бывает, когда "
         "скачивание сбилось и глава записалась дважды под разными номерами."),
    Rule("size", "Подозрительный объём", GROUP_STRUCTURE,
         "Глава заметно короче или длиннее остальных. Возможно, перевод "
         "оборвался."),

    # Технический мусор
    Rule("markdown", "Остатки markdown", GROUP_TECH,
         "Служебные символы разметки (**, ##, ---), которые модель оставила "
         "в тексте."),
    Rule("broken", "Битая кодировка и HTML", GROUP_TECH,
         "Испорченные символы и неубранные теги вроде &nbsp; или <br>."),
    Rule("model", "Следы модели-переводчика", GROUP_TECH,
         "Фразы вроде «Вот перевод» или «Translator's note», случайно "
         "попавшие в текст."),
    Rule("fullwidth", "Полноширинные знаки", GROUP_TECH,
         "Азиатские 【】（），。, оставшиеся от оригинала."),
)

BY_KEY = {rule.key: rule for rule in RULES}
ALL_KEYS = tuple(BY_KEY)

#: Что входит в каждый пресет.
PRESET_KEYS = {
    "full": ALL_KEYS,
    "quick": tuple(r.key for r in RULES if r.group == GROUP_TECH),
    "translation": tuple(r.key for r in RULES if r.group == GROUP_TRANSLATION),
}


def grouped() -> list[dict]:
    """Правила по группам — в том виде, в каком их рисует интерфейс."""
    order = [GROUP_TRANSLATION, GROUP_PUNCTUATION, GROUP_STRUCTURE, GROUP_TECH]
    buckets: dict[str, list] = defaultdict(list)
    for rule in RULES:
        buckets[rule.group].append(
            {"key": rule.key, "name": rule.name, "tip": rule.tip}
        )
    return [
        {"group": key, "title": GROUPS[key], "rules": buckets[key]}
        for key in order
        if buckets[key]
    ]


#: Полноширинные знаки — тот же набор, что чинит очистка.
FULLWIDTH = re.compile("[【】（）《》，。"
                       "：；！？　．～「」]")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)
