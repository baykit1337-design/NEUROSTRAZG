"""Очередь книг: несколько книг подряд, каждая своим источником.

Зачем отдельным предметом, когда очередь уже есть. `ops/queue.py` — это
цепочка операций над файлами: разбить → переименовать → проверить. Там
шаги зависят друг от друга, и оборвись один — остальным нечего брать на
вход, поэтому очередь останавливается. Здесь наоборот: книги друг о
друге не знают. Не открылся сайт у третьей — четвёртую качать всё равно
надо, иначе одна закрытая книга съедала бы ночь работы.

Главная тонкость — **у каждой книги свой источник**. Одну нашли в
рейтинге Фанкью и качают оттуда же, вторую — через посредника, третью
нашли на Цидяне, где скачивания нет вовсе, и качать её придётся с
сайта-слива по вставленной ссылке. Общего «источника очереди» не бывает:
он записан в каждой строке отдельно, вместе с адресом и папкой.

Отсюда третье состояние строки, которого нет у обычной очереди:
`NEEDS_LINK` — книга в очереди есть, а качать её не с чего. Такую строку
не выбрасывают: ссылку дописывают прямо в ней, и она встаёт в общий ряд.
Выброси мы её при добавлении — человек потерял бы саму память о том, что
книгу хотел.

Чего здесь нет: границ глав, посчитанных заранее. «С какой главы» у
докачки считается в момент запуска, по тому, что лежит в папке. Заморозь
мы номер при добавлении — за ночь вышло бы ещё три главы, а очередь
качала бы вчерашний остаток.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .history import DATA_DIR
from .queue import DONE, FAILED, RUNNING, SKIPPED, WAITING

log = logging.getLogger(__name__)

QUEUE_FILE = DATA_DIR / "downloads.json"

#: Книга в очереди есть, а качать её не с чего: нашли там, где
#: скачивания нет. Ждёт вставленной ссылки, а не выбрасывается.
NEEDS_LINK = "needs_link"

#: Сколько книг держать в очереди. Больше сотни за раз никто не ставит, а
#: список читается на каждое открытие вкладки.
KEEP = 200

_LOCK = threading.Lock()


@dataclass
class Item:
    """Одна книга в очереди — со своим источником, папкой и границами."""

    id: str = ""
    #: Как показывать. Название с сайта и его перевод, если он есть.
    name: str = ""
    name_ru: str = ""
    cover: str = ""

    #: Чем качать и что подставлять. Пустой источник — строка ждёт ссылки.
    source: str = ""
    address: str = ""

    #: Куда класть: где создать папку и как её назвать.
    base: str = ""
    folder: str = ""

    #: Границы глав. Ноль — «сама разберётся»: с первой недостающей и до
    #: конца оглавления на момент запуска.
    first: int = 0
    last: int = 0

    #: Откуда книга взялась — для библиотеки. Книгу находят на одном
    #: сайте, а качают с другого, и без этого она легла бы туда дважды.
    origin: dict = field(default_factory=dict)

    state: str = WAITING
    message: str = ""
    #: Сколько глав легло на диск в прошлый запуск этой строки.
    done: int = 0

    @property
    def ready(self) -> bool:
        """Можно ли эту строку качать прямо сейчас."""
        return bool(self.source and self.address and self.base and self.folder)

    @property
    def title(self) -> str:
        return self.name_ru or self.name or self.address or self.folder

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "name_ru": self.name_ru,
            "cover": self.cover, "source": self.source,
            "address": self.address, "base": self.base, "folder": self.folder,
            "first": self.first, "last": self.last, "origin": dict(self.origin),
            "state": self.state, "message": self.message, "done": self.done,
            # Считаемое отдаём наружу, но в файл не пишем.
            "title": self.title, "ready": self.ready,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Item:
        data = data or {}

        def whole(name):
            try:
                return max(0, int(data.get(name) or 0))
            except (TypeError, ValueError):
                return 0

        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            name_ru=str(data.get("name_ru") or ""),
            cover=str(data.get("cover") or ""),
            source=str(data.get("source") or ""),
            address=str(data.get("address") or ""),
            base=str(data.get("base") or ""),
            folder=str(data.get("folder") or ""),
            first=whole("first"), last=whole("last"),
            origin=dict(data.get("origin") or {}),
            state=str(data.get("state") or WAITING),
            message=str(data.get("message") or ""),
            done=whole("done"),
        )


# ------------------------------------------------------------- хранение


def _load() -> list[Item]:
    if not QUEUE_FILE.is_file():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Битая очередь не должна мешать качать по одной книге.
        log.warning("Битая очередь книг — начинаем заново")
        return []
    if not isinstance(data, list):
        return []
    rows = [Item.from_dict(x) for x in data if isinstance(x, dict)]
    return [x for x in rows if x.id]


def _save(rows: list[Item]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    plain = []
    for item in rows[:KEEP]:
        data = item.as_dict()
        for made in ("title", "ready"):
            data.pop(made, None)
        plain.append(data)
    tmp = QUEUE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(plain, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(QUEUE_FILE)


def all_items() -> list[Item]:
    """Очередь целиком, в том порядке, в каком её качать."""
    with _LOCK:
        return _load()


def get(item_id: str) -> Item | None:
    return next((x for x in all_items() if x.id == str(item_id or "")), None)


def _settle(item: Item) -> Item:
    """Строке без источника или адреса — своё состояние, а не «ждёт».

    «Ждёт» на строке, которую никогда не начнут, — это обещание, которое
    некому исполнить: очередь дошла бы до неё и молча прошла мимо.
    """
    if item.state in (RUNNING, DONE, FAILED):
        return item
    item.state = WAITING if item.ready else NEEDS_LINK
    if item.state == NEEDS_LINK and not item.message:
        item.message = ("Нечем качать: книга нашлась там, где скачивания "
                        "нет. Вставьте ссылку с сайта, где она есть.")
    return item


def add(**fields) -> Item:
    """Поставить книгу в очередь. Повтор той же книги не плодит строк."""
    item = Item.from_dict(fields)
    item.id = item.id or uuid.uuid4().hex[:12]
    _settle(item)

    with _LOCK:
        rows = _load()
        same = next((x for x in rows if _twins(x, item)), None)
        if same is not None:
            # Ту же книгу поставили второй раз: не строка-близнец, а
            # обновление той, что уже стоит. Иначе очередь качала бы одну
            # книгу дважды в одну и ту же папку.
            item.id = same.id
            item.done = same.done
            rows[rows.index(same)] = item
        else:
            rows.append(item)
        _save(rows)
    return item


def _twins(one: Item, two: Item) -> bool:
    """Одна ли это книга. Сначала по происхождению, потом по папке.

    Книгу находят на одном сайте, а качают с другого — сравнивать только
    адреса значило бы считать разными строку с Цидяня и её же после
    вставленной ссылки на слив.
    """
    here, there = one.origin or {}, two.origin or {}
    site, code = here.get("site"), here.get("book_id")
    if site and code and (site, code) == (there.get("site"),
                                          there.get("book_id")):
        return True
    if one.base and one.folder:
        return (one.base, one.folder) == (two.base, two.folder)
    return bool(one.source) and (one.source, one.address) == (two.source,
                                                              two.address)


def update(item_id: str, **fields) -> Item | None:
    """Поправить строку: вставить ссылку, сменить папку, задать границы."""
    with _LOCK:
        rows = _load()
        item = next((x for x in rows if x.id == str(item_id or "")), None)
        if item is None:
            return None
        for name, value in fields.items():
            if name in ("id", "state") or not hasattr(item, name):
                continue
            if name in ("first", "last", "done"):
                try:
                    value = max(0, int(value or 0))
                except (TypeError, ValueError):
                    continue
            setattr(item, name, value)
        # Вставили ссылку — строка перестаёт ждать и встаёт в общий ряд.
        item.message = ""
        item.state = WAITING
        _settle(item)
        _save(rows)
        return item


def remove(item_id: str) -> bool:
    with _LOCK:
        rows = _load()
        left = [x for x in rows if x.id != str(item_id or "")]
        if len(left) == len(rows):
            return False
        _save(left)
    return True


def move(item_id: str, delta: int) -> bool:
    """Подвинуть строку вверх или вниз: порядок здесь и есть смысл."""
    with _LOCK:
        rows = _load()
        at = next((n for n, x in enumerate(rows) if x.id == str(item_id or "")),
                  None)
        if at is None:
            return False
        to = min(max(0, at + int(delta or 0)), len(rows) - 1)
        if to == at:
            return False
        rows.insert(to, rows.pop(at))
        _save(rows)
    return True


def clear(only_done: bool = False) -> int:
    """Убрать всё или только отработавшее."""
    with _LOCK:
        rows = _load()
        left = [x for x in rows if x.state != DONE] if only_done else []
        _save(left)
        return len(rows) - len(left)


def recover() -> list[Item]:
    """Расчистить строки, оборванные закрытием программы.

    «Качается» пишется на диск, чтобы очередь пережила закрытие окна. Но
    если программу закрыли посреди книги, эта надпись остаётся навсегда:
    очередь показывает работу, которой нет, и до следующего запуска
    человек не знает, качалась книга или нет.

    Звать один раз при старте, а не при каждом чтении: во время прогона
    «качается» — это правда.
    """
    with _LOCK:
        rows = _load()
        stuck = [one for one in rows if one.state == RUNNING]
        for one in stuck:
            one.state = WAITING
            one.message = ("Прервано: программу закрыли во время "
                           "скачивания. Скачанное осталось на месте.")
        if stuck:
            log.info("Очередь книг: %s строк освобождено после обрыва",
                     len(stuck))
            _save(rows)
        return rows


def reset() -> list[Item]:
    """Приготовить очередь к новому запуску, не трогая ждущих ссылку."""
    with _LOCK:
        rows = _load()
        for item in rows:
            item.done = 0
            item.message = ""
            item.state = WAITING
            _settle(item)
        _save(rows)
        return rows


def state() -> dict:
    """Сводка для подписи над очередью."""
    rows = all_items()
    return {
        "books": len(rows),
        "waiting": sum(1 for x in rows if x.state == WAITING),
        "done": sum(1 for x in rows if x.state == DONE),
        "failed": sum(1 for x in rows if x.state == FAILED),
        "needs_link": sum(1 for x in rows if x.state == NEEDS_LINK),
        "chapters": sum(x.done for x in rows),
    }


# --------------------------------------------------------------- запуск


#: Сколько книг качать разом по умолчанию. Одна — прежнее поведение, и
#: менять его молча нельзя: у книг общий пул прокси и общая квота сайта.
BOOKS_AT_ONCE = 1

#: Больше этого не пускаем при всём желании. Двадцать книг разом — это
#: двадцать оглавлений и сотни глав в минуту с одного адреса: сайт
#: закроется, и виноват будет не он.
MAX_AT_ONCE = 8


#: «Считай сам». Ноль в настройке значит не «ни одной книги», а «раздай
#: по прокси»: числа человек не знает, пока не проверит список.
AUTO = 0


def spread(proxies: int, threads: int, books: int) -> list[int]:
    """Сколько потоков дать каждой книге, чтобы всем хватило прокси.

    Правило простое: один поток занимает один прокси. Значит, пять
    проверенных адресов при одном потоке — это пять книг разом, а при
    трёх потоках — одна книга в три потока и вторая в два, потому что
    больше адресов нет.

    Остаток не выбрасываем. Считай мы честным делением, при пяти адресах
    и трёх потоках качалась бы **одна** книга, а два проверенных адреса
    простаивали бы без дела.

    Прокси нет вовсе — значит, идём напрямую, и делить нечего: одна книга
    во столько потоков, сколько попросили.
    """
    threads = max(1, int(threads or 1))
    books = max(0, int(books or 0))
    if books <= 0:
        return []

    # Прокси нет — цикл ниже не сделает ни одного шага, и книга получит
    # свои потоки из последней строки. Отдельной ветки этому случаю не
    # нужно: она делала бы ровно то же самое, только в двух местах.
    left = max(0, int(proxies))
    out: list[int] = []
    while left > 0 and len(out) < min(books, MAX_AT_ONCE):
        take = min(threads, left)
        out.append(take)
        left -= take
    return out or [threads]


def run(perform, on_change=None, cancel=None,
        workers: int = BOOKS_AT_ONCE) -> list[Item]:
    """Качает книги очереди. Упавшая книга не отменяет остальные.

    `perform(item)` качает одну книгу и возвращает текст итога либо
    возбуждает исключение. В отличие от очереди операций, здесь отказ
    одной строки останавливает только её: книги друг о друге не знают, и
    закрытый сайт у третьей — не повод бросать четвёртую.

    `workers` — сколько книг вести одновременно. Ждать, пока докачается
    первая, чтобы начать вторую, незачем: книги независимы, а узкое место
    у них не общее — одна упирается в медленный сайт, другая в разбор.

    Порядок в списке при этом сохраняется: строки остаются на своих
    местах, меняется только то, что несколько из них горят «качается»
    разом.
    """
    rows = reset()
    ready = [one for one in rows if one.ready]
    workers = max(1, min(int(workers or 1), MAX_AT_ONCE, len(ready) or 1))

    # Список общий на все потоки: и правки строк, и запись на диск, и
    # доклад наверх идут через один замок. Без него две книги, кончившие
    # разом, затирали бы записи друг друга прямо в файле очереди.
    guard = threading.Lock()

    def told(item) -> None:
        with guard:
            _save_locked(rows)
            if on_change:
                on_change(rows, item)

    def one(item) -> None:
        if cancel is not None and cancel.is_set():
            # Не начатое остаётся ждать, а не помечается пропущенным:
            # очередь продолжат тем же нажатием, что и начали.
            return

        item.state = RUNNING
        item.message = ""
        told(item)

        try:
            item.message = str(perform(item) or "")
            item.state = DONE
        except Exception as exc:  # noqa: BLE001 — причину показываем целиком
            if cancel is not None and cancel.is_set():
                # Остановили руками — это не отказ книги. Пометь мы её
                # неудачей, и «не вышло: 1» обвиняло бы сайт в том, что
                # сделал человек, а книга не попала бы в продолжение.
                item.state = WAITING
                item.message = ""
            else:
                item.state = FAILED
                item.message = f"{type(exc).__name__}: {exc}"
                log.warning("Очередь книг: «%s» не скачалась: %s",
                            item.title, item.message)
        told(item)

    if workers == 1:
        # Тот же путь, что и был: без пула, чтобы одиночная очередь вела
        # себя ровно как прежде — и в отладке тоже.
        for item in ready:
            if cancel is not None and cancel.is_set():
                break
            one(item)
        return rows

    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix="book") as pool:
        # `map` дождался бы всех и проглотил бы исключения до конца; здесь
        # каждая книга своя, и разбираться с ней надо на месте.
        for done in as_completed([pool.submit(one, item) for item in ready]):
            done.result()
    return rows


def _keep(rows: list[Item]) -> None:
    """Записать ход очереди на диск: закройся окно — не пропадёт."""
    with _LOCK:
        _save(rows)


def _save_locked(rows: list[Item]) -> None:
    """То же самое, но замок уже держит вызывающий.

    Отдельно, чтобы прогон нескольких книг мог взять один замок на
    «поправить строку, записать, доложить»: возьми он `_keep`, между
    правкой и записью влезала бы соседняя книга.
    """
    with _LOCK:
        _save(rows)


__all__ = ["AUTO", "BOOKS_AT_ONCE", "DONE", "FAILED", "Item", "KEEP",
           "MAX_AT_ONCE", "NEEDS_LINK", "QUEUE_FILE", "RUNNING", "SKIPPED",
           "WAITING", "add", "all_items", "clear", "get", "move", "recover",
           "remove", "reset", "run", "spread", "state", "update"]
