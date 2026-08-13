"""ЕДИНАЯ обработка текста — одна на весь проект.

Убрать дубль названия, выровнять, схлопнуть разделители, выкинуть пустые
абзацы — всё здесь. Ни одна вкладка не обрабатывает абзацы сама: операции
вызывают `prepare()` и получают готовые блоки.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Абзац-разделитель сцен: только звёздочки, точки или тире в любом числе.
SCENE_CHARS = "*＊※·•—–-_"
SCENE_BREAK = re.compile(rf"^[\s{re.escape(SCENE_CHARS)}]*[{re.escape(SCENE_CHARS)}][\s{re.escape(SCENE_CHARS)}]*$")

#: Игровые уведомления новеллы: {Обнаружен Потенциал} и [Получено достижение].
#: Это часть текста, удалять нельзя — только выровнять как обычный абзац.
SYSTEM_MESSAGE = re.compile(r"^\s*[\{\[].+[\}\]]\s*$", re.S)

#: Приставка вида «Глава 209.» перед названием — при сравнении не учитывается.
TITLE_PREFIX = re.compile(
    r"^\s*(?:глава|глaва|chapter|часть|part)\s*\d+(?:[.,]\d+)?\s*[.:\-–—]?\s*",
    re.I,
)

#: Сколько первых абзацев проверять на дубль названия.
TITLE_LOOKAHEAD = 3

# Виды разделителя сцен на выходе.
SCENE_STARS = "stars"
SCENE_BLANK = "blank"
SCENE_DASHES = "dashes"
SCENE_KEEP = "keep"
SCENE_STYLES = (SCENE_STARS, SCENE_BLANK, SCENE_DASHES, SCENE_KEEP)
SCENE_TEXT = {SCENE_STARS: "* * *", SCENE_DASHES: "— — —"}

ALIGN_LEFT = "left"
ALIGN_CENTER = "center"
ALIGN_JUSTIFY = "justify"
ALIGNMENTS = (ALIGN_LEFT, ALIGN_CENTER, ALIGN_JUSTIFY)

# Типы блоков на выходе.
KIND_TEXT = "text"
KIND_SCENE = "scene"
KIND_SYSTEM = "system"


@dataclass
class Block:
    """Абзац с пометкой, что это — обычный текст, разделитель или уведомление."""

    text: str
    kind: str = KIND_TEXT


@dataclass
class PrepOptions:
    """Настройки подготовки. Значения по умолчанию — из ТЗ v4."""

    strip_title: bool = True
    align: str = ALIGN_LEFT
    first_line_indent_cm: float = 0.0
    scene_style: str = SCENE_STARS
    drop_empty: bool = True
    italic_system: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> PrepOptions:
        data = data or {}
        align = str(data.get("align") or cls.align)
        scene = str(data.get("scene_style") or cls.scene_style)
        return cls(
            strip_title=bool(data.get("strip_title", cls.strip_title)),
            align=align if align in ALIGNMENTS else cls.align,
            first_line_indent_cm=_positive(
                data.get("first_line_indent_cm"), cls.first_line_indent_cm
            ),
            scene_style=scene if scene in SCENE_STYLES else cls.scene_style,
            drop_empty=bool(data.get("drop_empty", cls.drop_empty)),
            italic_system=bool(data.get("italic_system", cls.italic_system)),
        )


def _positive(value, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def normalize_title(text: str) -> str:
    """Приводит строку к виду, пригодному для сравнения с названием главы.

    Без регистра, без лишних пробелов, без знаков по краям и без приставки
    «Глава 209.» — иначе дубль в тексте не опознаётся.
    """
    text = unicodedata.normalize("NFKC", text or "").strip()
    text = TITLE_PREFIX.sub("", text)
    text = re.sub(r"\s+", " ", text)
    # Знаки препинания по краям: «Название?» и «Название» — одно и то же.
    # Скобки не трогаем: в названиях бывает «(1)», и обрезка сделала бы из
    # «паука (1)» несимметричное «паука (1».
    text = text.strip(" \t.,:;!?«»\"'-–—*")
    return text.casefold()


def is_scene_break(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and bool(SCENE_BREAK.match(stripped))


def is_system_message(text: str) -> bool:
    return bool(SYSTEM_MESSAGE.match(text or ""))


def prepare(paragraphs, title: str = "", options: PrepOptions | None = None) -> list[Block]:
    """Готовит абзацы главы к выводу.

    Убирает дубли названия, схлопывает разделители сцен, выбрасывает пустые
    абзацы и помечает игровые уведомления.
    """
    options = options or PrepOptions()
    blocks: list[Block] = []

    # 1. Пустые абзацы: расстояние задаётся интервалом, а не пустыми строками.
    cleaned = [p.strip() for p in paragraphs if not options.drop_empty or p.strip()]
    cleaned = [p for p in cleaned if p]

    # 2. Дубль названия в первых абзацах — удаляем все подряд, не только первый.
    if options.strip_title and title:
        cleaned = strip_leading_title(cleaned, title)

    for paragraph in cleaned:
        if is_scene_break(paragraph):
            if options.scene_style == SCENE_KEEP:
                blocks.append(Block(paragraph, KIND_SCENE))
            elif options.scene_style == SCENE_BLANK:
                blocks.append(Block("", KIND_SCENE))
            else:
                blocks.append(Block(SCENE_TEXT[options.scene_style], KIND_SCENE))
            continue
        kind = KIND_SYSTEM if is_system_message(paragraph) else KIND_TEXT
        blocks.append(Block(paragraph, kind))

    blocks = collapse_scenes(blocks)
    return trim_scenes(blocks)


def strip_leading_title(paragraphs: list[str], title: str) -> list[str]:
    """Убирает название главы из начала текста.

    Проверяются первые несколько абзацев, и удаляются **все** совпадения
    подряд: в исходнике название нередко стоит дважды.
    """
    wanted = normalize_title(title)
    if not wanted:
        return paragraphs

    index = 0
    while index < min(TITLE_LOOKAHEAD, len(paragraphs)):
        if normalize_title(paragraphs[index]) == wanted:
            index += 1
            continue
        break
    return paragraphs[index:]


def collapse_scenes(blocks: list[Block]) -> list[Block]:
    """Идущие подряд разделители схлопывает в один.

    На сайте они идут по несколько `<p>*</p>`, из-за чего в документе
    получалось по две-три звёздочки подряд.
    """
    result: list[Block] = []
    for block in blocks:
        if block.kind == KIND_SCENE and result and result[-1].kind == KIND_SCENE:
            continue
        result.append(block)
    return result


def trim_scenes(blocks: list[Block]) -> list[Block]:
    """Разделитель не должен быть первым или последним абзацем."""
    start, end = 0, len(blocks)
    while start < end and blocks[start].kind == KIND_SCENE:
        start += 1
    while end > start and blocks[end - 1].kind == KIND_SCENE:
        end -= 1
    return blocks[start:end]


def to_text(blocks: list[Block]) -> str:
    """Собирает блоки обратно в плоский текст — для .txt и .md."""
    return "\n\n".join(b.text for b in blocks if b.text)
