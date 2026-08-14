"""Своя история рейтинга и движение по ней (5.3 ТЗ NEUROSTRAZH).

Сайт отдаёт только суточный срез. Разовый срез отвечает на вопрос «что
популярно», а нужен ответ на другой: «что набирает обороты» — то есть кто
кандидат на перевод, пока его не разобрали. Такой ответ получается только
из нескольких дней подряд, поэтому срезы складываются к себе.

Один файл на день: `data/rank_history/ГГГГ-ММ-ДД.json`. Повторный запрос в
тот же день переписывает файл, а не плодит второй — иначе «за сутки»
считалось бы от случайного среза.

По расписанию ничего не запрашивается: срез снимается кнопкой.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from net.sources.rank import RankRow

from .history import DATA_DIR

log = logging.getLogger(__name__)

RANK_DIR = DATA_DIR / "rank_history"

#: Формат имени файла среза — он же порядок сортировки.
STAMP = "%Y-%m-%d"

#: Сколько дней держать. Год истории — это триста файлов по паре десятков
#: килобайт; больше не нужно, а меньше уже не даёт «за неделю».
KEEP_DAYS = 400

#: Окно для «роста» и «падения».
WEEK = 7

#: Держится в топе — считаем по этому срезу.
TOP_HOLD = 50


class RankError(Exception):
    """С историей рейтинга что-то не так."""


@dataclass
class Snapshot:
    """Срез за один день."""

    day: str = ""
    board: str = "all"
    rows: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"day": self.day, "board": self.board,
                "rows": [r.as_dict() for r in self.rows]}

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        return cls(
            day=str((data or {}).get("day") or ""),
            board=str((data or {}).get("board") or "all"),
            rows=[RankRow.from_dict(r) for r in (data or {}).get("rows") or []],
        )

    def by_book(self) -> dict:
        return {row.book_id: row for row in self.rows if row.book_id}


def _path(day: str, board: str) -> Path:
    #: Разделы лежат рядом: у мужского и женского рейтинга своя динамика,
    #: и складывать их в один файл значило бы её потерять.
    name = day if board == "all" else f"{day}_{board}"
    return RANK_DIR / f"{name}.json"


def save(rows, board: str = "all", day: str = "") -> Snapshot:
    """Записывает срез за день. Повторный вызов переписывает файл."""
    snapshot = Snapshot(day=day or date.today().strftime(STAMP),
                        board=board, rows=list(rows))
    path = _path(snapshot.day, board)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    trim()
    return snapshot


def load(day: str, board: str = "all") -> Snapshot | None:
    path = _path(day, board)
    if not path.is_file():
        return None
    try:
        return Snapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        log.warning("Битый срез рейтинга: %s", path)
        return None


def days(board: str = "all") -> list[str]:
    """Дни, за которые есть срезы, свежие первыми."""
    if not RANK_DIR.is_dir():
        return []
    found = []
    for path in RANK_DIR.glob("*.json"):
        name = path.stem
        if board == "all":
            if "_" in name:
                continue
            found.append(name)
        elif name.endswith(f"_{board}"):
            found.append(name[: -len(board) - 1])
    return sorted(found, reverse=True)


def trim(keep: int = KEEP_DAYS) -> int:
    """Удаляет старые срезы."""
    if not RANK_DIR.is_dir():
        return 0
    files = sorted(RANK_DIR.glob("*.json"), key=lambda p: p.name, reverse=True)
    removed = 0
    for path in files[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            log.warning("Не удалось удалить срез %s: %s", path, exc)
    return removed


def _nearest(board: str, before: str, back: int) -> Snapshot | None:
    """Срез примерно `back` дней назад.

    Именно «примерно»: срезы снимаются вручную, и ровно неделю назад
    человека могло не быть за компьютером. Берём ближайший день не новее
    искомого — иначе «за неделю» молча превращалось бы в «за вчера».
    """
    try:
        edge = datetime.strptime(before, STAMP).date() - timedelta(days=back)
    except ValueError:
        return None
    wanted = edge.strftime(STAMP)
    older = [d for d in days(board) if d <= wanted]
    return load(older[0], board) if older else None


@dataclass
class Movement:
    """Как книга движется по рейтингу."""

    row: RankRow = None
    #: Насколько поднялась за неделю. Плюс — вверх.
    week: int | None = None
    #: Насколько поднялась за сутки.
    day: int | None = None
    #: Сколько дней подряд в топе.
    holding: int = 0
    #: Прирост читателей за неделю.
    readers_gain: int | None = None
    is_new: bool = False

    def as_dict(self) -> dict:
        return {**self.row.as_dict(), "week": self.week, "day": self.day,
                "holding": self.holding, "readers_gain": self.readers_gain,
                "is_new": self.is_new}


def movement(board: str = "all", today: str = "") -> dict:
    """Движение по рейтингу: новые, растущие, падающие, держащиеся.

    Считается по своей истории — на сайте этого нет вовсе.
    """
    have = days(board)
    if not have:
        return {"rows": [], "days": 0, "board": board,
                "note": "Истории пока нет — снимите первый срез."}

    day = today or have[0]
    current = load(day, board)
    if current is None:
        raise RankError(f"Среза за {day} нет")

    yesterday = _nearest(board, day, 1)
    week_ago = _nearest(board, day, WEEK)
    before = {d: load(d, board) for d in have[:WEEK + 1]}

    moves = []
    for row in current.rows:
        move = Movement(row=row)

        if yesterday is not None:
            was = yesterday.by_book().get(row.book_id)
            move.day = (was.place - row.place) if was else None
            move.is_new = was is None
        if week_ago is not None:
            was = week_ago.by_book().get(row.book_id)
            if was is not None:
                move.week = was.place - row.place
                move.readers_gain = row.readers - was.readers

        # Сколько дней подряд держится в топе — считаем от свежего к
        # старому и обрываем на первом пропуске.
        for name in have:
            snapshot = before.get(name) or load(name, board)
            found = snapshot.by_book().get(row.book_id) if snapshot else None
            if found is None or found.place > TOP_HOLD:
                break
            move.holding += 1
        moves.append(move)

    return {
        "rows": [m.as_dict() for m in moves],
        "day": day,
        "days": len(have),
        "board": board,
        "has_week": week_ago is not None,
        "note": "" if week_ago is not None else
                "Для «за неделю» нужно несколько дней истории — пока считаем "
                "только за сутки.",
    }
