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
    #: С какого сайта срез. Пусто — Фанкью: так называются все срезы,
    #: снятые до появления второго рейтинга.
    site: str = ""
    rows: list = field(default_factory=list)
    #: Категория, по которой снят срез: у каждой своя динамика.
    category: str = ""
    #: Метка версии рейтинга с сайта. По ней видно, обновился ли он с
    #: прошлого раза, — дата запроса об этом не говорит.
    version: str = ""
    #: До какого момента собрана статистика по словам самого сайта. Это
    #: точнее даты запроса: рейтинг обновляется днём.
    stats_date: str = ""

    def as_dict(self) -> dict:
        return {"day": self.day, "board": self.board, "site": self.site,
                "category": self.category, "version": self.version,
                "stats_date": self.stats_date,
                "rows": [r.as_dict() for r in self.rows]}

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        data = data or {}
        return cls(
            day=str(data.get("day") or ""),
            board=str(data.get("board") or "all"),
            site=str(data.get("site") or ""),
            category=str(data.get("category") or ""),
            version=str(data.get("version") or ""),
            stats_date=str(data.get("stats_date") or ""),
            rows=[RankRow.from_dict(r) for r in data.get("rows") or []],
        )

    def by_book(self) -> dict:
        return {row.book_id: row for row in self.rows if row.book_id}


def _slug(board: str, category: str = "", site: str = "") -> str:
    """Как называется набор срезов. Пустой раздел — старое имя «all».

    Сайт приписывается спереди через дефис, а не через подчёркивание:
    подчёркивание уже отделяет день от остального имени, и третий
    разделитель того же вида сделал бы разбор имени неоднозначным.

    Пустой сайт — Фанкью. Так писались все срезы до появления второго
    рейтинга, и переименовывать их задним числом значило бы выбросить
    накопленную историю: движение считается только по ней.
    """
    board = str(board or "all")
    tail = f"{board}_{category}" if category else board
    return f"{site}-{tail}" if site else tail


def _path(day: str, board: str, category: str = "", site: str = "") -> Path:
    #: Разделы и категории лежат рядом: у мужского фэнтези и женской
    #: романтики своя динамика, и общий файл её потерял бы. С сайтами то
    #: же самое, только сильнее.
    slug = _slug(board, category, site)
    name = day if slug == "all" else f"{day}_{slug}"
    return RANK_DIR / f"{name}.json"


def save(rows, board: str = "all", day: str = "", category: str = "",
         version: str = "", stats_date: str = "", site: str = "") -> Snapshot:
    """Записывает срез за день. Повторный вызов переписывает файл."""
    snapshot = Snapshot(day=day or date.today().strftime(STAMP),
                        board=board, rows=list(rows), category=category,
                        version=version, stats_date=stats_date, site=site)
    path = _path(snapshot.day, board, category, site)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    trim()
    return snapshot


def read(path: Path) -> Snapshot | None:
    """Срез из файла.

    Имя файла разбирать не нужно: день, сайт, доска и раздел записаны
    внутри самого среза. Общей доске это и требуется — она проходит по
    всем файлам подряд, не зная заранее, чьи они.
    """
    if not path.is_file():
        return None
    try:
        return Snapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        log.warning("Битый срез рейтинга: %s", path)
        return None


def load(day: str, board: str = "all", category: str = "",
         site: str = "") -> Snapshot | None:
    return read(_path(day, board, category, site))


def days(board: str = "all", category: str = "", site: str = "") -> list[str]:
    """Дни, за которые есть срезы, свежие первыми."""
    if not RANK_DIR.is_dir():
        return []
    slug = _slug(board, category, site)
    found = []
    for path in RANK_DIR.glob("*.json"):
        name = path.stem
        if slug == "all":
            if "_" in name:
                continue
            found.append(name)
        elif name.endswith(f"_{slug}"):
            found.append(name[: -len(slug) - 1])
    return sorted(found, reverse=True)


def trim(keep: int = KEEP_DAYS) -> int:
    """Удаляет старые срезы — по столько-то дней на каждый набор.

    Считать все файлы в одну кучу было ошибкой, и с появлением второго
    сайта она стала заметной: у каждой доски и каждой категории свой
    набор срезов, а порог один на папку. Снял три среза по MVLEMPYR —
    и настолько же укоротилась история Фанкью, хотя её никто не трогал.
    Год истории обещан каждому набору, а не всем вместе.
    """
    if not RANK_DIR.is_dir():
        return 0

    sets: dict[str, list[Path]] = {}
    for path in RANK_DIR.glob("*.json"):
        name = path.stem
        # Имя среза — «день» или «день_набор». День всегда впереди и
        # всегда одной длины, поэтому набор — это всё после первого
        # подчёркивания.
        slug = name.split("_", 1)[1] if "_" in name else "all"
        sets.setdefault(slug, []).append(path)

    removed = 0
    for paths in sets.values():
        paths.sort(key=lambda p: p.name, reverse=True)
        for path in paths[keep:]:
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                log.warning("Не удалось удалить срез %s: %s", path, exc)
    return removed


def _nearest(board: str, before: str, back: int, category: str = "",
             site: str = "") -> Snapshot | None:
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
    older = [d for d in days(board, category, site) if d <= wanted]
    return load(older[0], board, category, site) if older else None


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


def movement(board: str = "all", today: str = "", category: str = "",
             site: str = "") -> dict:
    """Движение по рейтингу: новые, растущие, падающие, держащиеся.

    Считается по своей истории — на сайте этого нет вовсе.
    """
    have = days(board, category, site)
    if not have:
        return {"rows": [], "days": 0, "board": board, "category": category,
                "site": site,
                "note": "Истории пока нет — снимите первый срез."}

    day = today or have[0]
    current = load(day, board, category, site)
    if current is None:
        raise RankError(f"Среза за {day} нет")

    yesterday = _nearest(board, day, 1, category, site)
    week_ago = _nearest(board, day, WEEK, category, site)
    before = {d: load(d, board, category, site) for d in have[:WEEK + 1]}

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
            snapshot = before.get(name) or load(name, board, category, site)
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
        "category": category,
        "site": site,
        "version": current.version,
        "stats_date": current.stats_date,
        "has_week": week_ago is not None,
        "note": "" if week_ago is not None else
                "Для «за неделю» нужно несколько дней истории — пока считаем "
                "только за сутки.",
    }
