"""Библиотека: одна запись на книгу.

Зачем это отдельным предметом. Программе понадобились сразу четыре
списка: паспорт скачанной книги, история качалки, теги от модели и
метки вроде «потенциальная». Сделай их порознь — получатся три-четыре
разных списка одних и тех же книг, и разойдутся они на второй неделе:
там книгу переименовали, тут докачали, а в третьем месте она осталась
прежней. Поэтому запись одна, а всё перечисленное — её поля.

Главная тонкость — **что считать одной книгой**. Книгу находят на одном
сайте, а качают с другого: на Цидяне рейтинг работает, а скачивания нет
вовсе, и человек ищет её на сайте-сливе и вставляет оттуда адрес. Это
одна книга, а не две. Поэтому ключ берётся от того места, где книга
нашлась, и переезд на другой источник его не меняет: меняются поля
`source` и `address`, по которым потом идёт докачка.

Записи о самой работе с файлами — «разбил», «переименовал» — живут не
здесь, а в `ops/history.py`: там журнал операций и корзина. Здесь книги.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .history import DATA_DIR

log = logging.getLogger(__name__)

LIBRARY_FILE = DATA_DIR / "library.json"

#: Сколько книг держать. Столько рейтингов подряд никто не отмечает, а
#: разрастись файлу не даём: он читается на каждое открытие вкладки.
KEEP_BOOKS = 2000

#: Метки, которые ставит человек. Список закрыт нарочно: свободные метки
#: расходятся в написании («потенц», «потенциальное», «потенциальная»), и
#: одно и то же оказывается в трёх разных кучах.
MARKS = {
    "want": "Потенциальная",
    "reading": "Читаю",
    "done": "Прочитана",
    "dropped": "Брошена",
    "junk": "Не интересует",
}

#: Метки, которые программа ставит сама. Их не выбирают руками: они
#: следуют из того, что программа и так знает, и врать не могут.
AUTO = {
    "downloaded": "Скачана",
    "updatable": "Есть новые главы",
}

_LOCK = threading.Lock()

STAMP = "%Y-%m-%d %H:%M"


def stamp() -> str:
    """Сейчас — в том виде, в каком время лежит в записи.

    Отдаётся наружу, чтобы формат остался в одном месте: тому, кто
    записывает прогон, не нужно ни знать про `STAMP`, ни тащить к себе
    `datetime` ради одной строки.
    """
    return datetime.now().strftime(STAMP)


def key_of(found_site: str = "", found_id: str = "",
           source: str = "", address: str = "") -> str:
    """Чем считать книгу одной и той же.

    Сначала место, где она нашлась: на Цидяне рейтинг есть, а качать
    оттуда нельзя, и та же книга приедет с сайта-слива. Ключ от места
    находки переживает этот переезд — иначе одна книга легла бы в
    библиотеку дважды, и метка осталась бы на той половине, которую
    больше не открывают.

    Не нашлась в рейтинге (вставили адрес руками) — ключом сам адрес.
    """
    site = str(found_site or "").strip()
    code = str(found_id or "").strip()
    if site and code:
        return f"{site}:{code}"
    return f"{str(source or '').strip()}:{str(address or '').strip()}".strip(":")


@dataclass
class Book:
    """Одна книга — во всех своих качествах разом."""

    key: str = ""
    #: Название на языке оригинала и перевод, если его запрашивали.
    name: str = ""
    name_ru: str = ""
    author: str = ""
    cover: str = ""

    #: Где книгу нашли: ключ сайта рейтинга и код в нём.
    found_site: str = ""
    found_id: str = ""
    found_link: str = ""

    #: Чем и откуда её качали. У книги с Цидяня это будет вовсе не
    #: Цидянь, и без этих двух полей докачивать было бы неоткуда.
    source: str = ""
    address: str = ""
    folder: str = ""

    #: Сколько глав было у источника на последнем прогоне и до какой
    #: дошли. Разница между ними и есть «есть новые главы».
    chapters: int = 0
    last: int = 0
    skipped: int = 0

    #: Что сайт рассказывает о книге. Собирается один раз, при
    #: скачивании: потом спросить будет не у кого — сайт ляжет, а книга
    #: в библиотеке останется.
    #:
    #: У каждого поля есть русский двойник. Перевод, однажды сделанный,
    #: стоит денег и времени, и затирать его свежим оригиналом при
    #: очередной проверке обновлений было бы обиднее всего.
    about: str = ""
    about_ru: str = ""
    genres: list = field(default_factory=list)
    genres_ru: list = field(default_factory=list)
    #: Теги **сайта**, а не человека. Свои лежат в `tags` и сайту не
    #: принадлежат: складывай мы их в одно место, обновление затирало бы
    #: то, что человек расставил руками.
    site_tags: list = field(default_factory=list)
    site_tags_ru: list = field(default_factory=list)
    #: Выходит или закончена, и на каком языке лежит у источника.
    status: str = ""
    language: str = ""

    marks: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    note: str = ""

    first_seen: str = ""
    last_run: str = ""

    @property
    def downloaded(self) -> bool:
        """Скачана ли хоть одна глава и лежит ли она где-то."""
        return bool(self.folder and self.last > 0)

    @property
    def fresh(self) -> int:
        """Сколько глав вышло сверх скачанного. Ноль — новых нет."""
        return max(0, self.chapters - self.last) if self.downloaded else 0

    @property
    def auto(self) -> list:
        """Метки, которые следуют из самой записи."""
        found = []
        if self.downloaded:
            found.append("downloaded")
        if self.fresh:
            found.append("updatable")
        return found

    @property
    def title(self) -> str:
        """Как книгу называть человеку: перевод, если он есть."""
        return self.name_ru or self.name or self.key

    @property
    def about_shown(self) -> str:
        """Описание, которое показывают: перевод, если он есть."""
        return self.about_ru or self.about

    @property
    def genres_shown(self) -> list:
        return list(self.genres_ru or self.genres or [])

    @property
    def site_tags_shown(self) -> list:
        return list(self.site_tags_ru or self.site_tags or [])

    @property
    def translated(self) -> bool:
        """Переведено ли хоть что-то из описания.

        Нужно карточке: «показано по-русски» и «показан оригинал» —
        разные вещи, и человек вправе видеть, что именно перед ним.
        """
        return bool(self.about_ru or self.genres_ru or self.site_tags_ru
                    or self.name_ru)

    def as_dict(self) -> dict:
        data = {
            "key": self.key, "name": self.name, "name_ru": self.name_ru,
            "author": self.author, "cover": self.cover,
            "found_site": self.found_site, "found_id": self.found_id,
            "found_link": self.found_link,
            "source": self.source, "address": self.address,
            "folder": self.folder,
            "chapters": self.chapters, "last": self.last,
            "skipped": self.skipped,
            "marks": list(self.marks), "tags": list(self.tags),
            "note": self.note,
            "about": self.about, "about_ru": self.about_ru,
            "genres": list(self.genres), "genres_ru": list(self.genres_ru),
            "site_tags": list(self.site_tags),
            "site_tags_ru": list(self.site_tags_ru),
            "status": self.status, "language": self.language,
            "first_seen": self.first_seen, "last_run": self.last_run,
        }
        # Считаемые поля отдаём наружу, но не пишем в файл: сохранённое
        # «есть новые главы» через день соврало бы.
        data.update(title=self.title, downloaded=self.downloaded,
                    fresh=self.fresh, auto=self.auto,
                    about_shown=self.about_shown,
                    genres_shown=self.genres_shown,
                    site_tags_shown=self.site_tags_shown,
                    translated=self.translated)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Book:
        data = data or {}

        def rows(name):
            found = data.get(name)
            return [str(x) for x in found if str(x)] if isinstance(found, list) else []

        return cls(
            key=str(data.get("key") or ""),
            name=str(data.get("name") or ""),
            name_ru=str(data.get("name_ru") or ""),
            author=str(data.get("author") or ""),
            cover=str(data.get("cover") or ""),
            found_site=str(data.get("found_site") or ""),
            found_id=str(data.get("found_id") or ""),
            found_link=str(data.get("found_link") or ""),
            source=str(data.get("source") or ""),
            address=str(data.get("address") or ""),
            folder=str(data.get("folder") or ""),
            chapters=int(data.get("chapters") or 0),
            last=int(data.get("last") or 0),
            skipped=int(data.get("skipped") or 0),
            marks=rows("marks"),
            tags=rows("tags"),
            note=str(data.get("note") or ""),
            about=str(data.get("about") or ""),
            about_ru=str(data.get("about_ru") or ""),
            genres=rows("genres"),
            genres_ru=rows("genres_ru"),
            site_tags=rows("site_tags"),
            site_tags_ru=rows("site_tags_ru"),
            status=str(data.get("status") or ""),
            language=str(data.get("language") or ""),
            first_seen=str(data.get("first_seen") or ""),
            last_run=str(data.get("last_run") or ""),
        )


def _load() -> dict:
    if not LIBRARY_FILE.is_file():
        return {}
    try:
        data = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Битая библиотека не должна мешать качать.
        log.warning("Битая библиотека — начинаем заново")
        return {}
    if not isinstance(data, list):
        return {}

    found = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        book = Book.from_dict(item)
        if book.key:
            found[book.key] = book
    return found


def _save(books: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = sorted(books.values(), key=lambda b: b.last_run or b.first_seen)
    keep = rows[-KEEP_BOOKS:]
    # В файл пишем только настоящие поля: считаемые отдаются наружу, но
    # завтра посчитаются заново и по-другому.
    plain = []
    for book in keep:
        data = book.as_dict()
        for made in ("title", "downloaded", "fresh", "auto"):
            data.pop(made, None)
        plain.append(data)

    tmp = LIBRARY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(plain, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(LIBRARY_FILE)


def all_books() -> list:
    """Вся библиотека, свежие сверху."""
    with _LOCK:
        rows = list(_load().values())
    rows.sort(key=lambda b: b.last_run or b.first_seen, reverse=True)
    return rows


def get(key: str) -> Book | None:
    with _LOCK:
        return _load().get(str(key or ""))


def remember(key: str = "", **fields) -> Book:
    """Завести книгу или дополнить уже заведённую.

    Дополнить, а не заменить: докачка знает про главы и папку, рейтинг —
    про обложку и перевод названия, а метки не знает никто, кроме
    человека. Записывай мы целиком — каждый следующий прогон стирал бы
    то, что положил предыдущий.
    """
    key = str(key or "") or key_of(
        fields.get("found_site", ""), fields.get("found_id", ""),
        fields.get("source", ""), fields.get("address", ""))
    if not key:
        raise ValueError("Книге нужен ключ: сайт с кодом или адрес.")

    now = datetime.now().strftime(STAMP)
    with _LOCK:
        books = _load()
        book = books.get(key) or Book(key=key, first_seen=now)
        for name, value in fields.items():
            if not hasattr(book, name):
                continue
            # Пустое не затирает: у прогона нет обложки, у рейтинга нет
            # папки, и каждый знает не всё.
            if value in ("", None, 0, [], {}) and getattr(book, name):
                continue
            setattr(book, name, value)
        book.key = key
        books[key] = book
        _save(books)
        return book


def touch(key: str) -> Book | None:
    """Отметить, что книгу только что качали."""
    return remember(key, last_run=datetime.now().strftime(STAMP)) \
        if get(key) else None


def mark(key: str, name: str, on: bool = True) -> Book | None:
    """Поставить или снять метку человека.

    Метки, которые ставит программа, сюда не попадают: они считаются из
    записи и руками не двигаются. Иначе «скачана» осталась бы на книге,
    у которой удалили папку.
    """
    if name not in MARKS:
        raise ValueError(f"Неизвестная метка: {name}")

    with _LOCK:
        books = _load()
        book = books.get(str(key or ""))
        if book is None:
            return None
        marks = [x for x in book.marks if x != name]
        if on:
            marks.append(name)
        book.marks = marks
        _save(books)
        return book


def set_note(key: str, text: str) -> Book | None:
    """Своя заметка к книге. Пустая — стирание, и оно должно доходить.

    Отдельной функцией, а не через `remember`: там пустое намеренно не
    затирает заполненное — иначе каждый прогон стирал бы то, что положил
    предыдущий. Для заметки это правило работало бы против человека:
    стереть написанное было бы нечем.
    """
    with _LOCK:
        books = _load()
        book = books.get(str(key or ""))
        if book is None:
            return None
        book.note = str(text or "").strip()
        _save(books)
        return book


#: Больше этого числа тегов у книги не держим: тег — способ найти, а не
#: пересказать содержание. Двадцать меток не сужают поиск ни на сколько.
MAX_TAGS = 20


def split_tags(text) -> list[str]:
    """Строка или список — в чистый список тегов.

    Теги пишут через запятую в одну строку, а приходить они могут и
    списком. Повторы убираем, порядок сохраняем: человек их сам так
    расставил.
    """
    if isinstance(text, str):
        pieces = text.replace(";", ",").split(",")
    else:
        pieces = [str(one) for one in (text or [])]

    found, seen = [], set()
    for piece in pieces:
        tag = " ".join(str(piece).split()).strip()
        # Сравниваем без регистра, а храним как написали: «Культивация»
        # и «культивация» — один тег, но выглядеть он должен по-людски.
        low = tag.casefold()
        if not tag or low in seen:
            continue
        seen.add(low)
        found.append(tag)
    return found[:MAX_TAGS]


def set_tags(key: str, tags) -> Book | None:
    """Свои теги книги. Пустой список — стирание, и оно должно доходить.

    Отдельной функцией по той же причине, что и заметка: `remember` не
    затирает заполненное пустым, и снять последний тег было бы нечем.
    """
    with _LOCK:
        books = _load()
        book = books.get(str(key or ""))
        if book is None:
            return None
        book.tags = split_tags(tags)
        _save(books)
        return book


def forget(key: str) -> bool:
    """Убрать книгу из библиотеки. Файлы на диске не трогаются."""
    with _LOCK:
        books = _load()
        if str(key or "") not in books:
            return False
        books.pop(str(key))
        _save(books)
        return True


def clear() -> None:
    with _LOCK:
        _save({})


#: Как называется паспорт в папке книги.
PASSPORT = "паспорт.md"


def passport(book: Book) -> str:
    """Что положить в папку рядом со скачанным.

    Через полгода папка `异度旅社` не говорит ни о чём: ни откуда книга,
    ни докуда докачана, ни почему в ней дыра на седьмой главе. Всё это
    программа знает — но знает у себя, а папку человек открывает мимо
    неё, из проводника или на другой машине.

    Поэтому паспорт — обычный текст рядом с главами, а не запись в базе.
    Библиотеку можно потерять, папку с книгой — вряд ли.
    """
    rows = ["# " + (book.title or "Книга"), ""]
    if book.name_ru and book.name and book.name_ru != book.name:
        rows.append(f"Название на сайте: {book.name}")
    if book.author:
        rows.append(f"Автор: {book.author}")

    rows.append("")
    if book.found_site:
        found = f"Найдена: рейтинг «{book.found_site}»"
        if book.found_link:
            found += f" — {book.found_link}"
        rows.append(found)
    if book.source:
        taken = f"Скачана: источник «{book.source}»"
        if book.address:
            taken += f" — {book.address}"
        rows.append(taken)
    if book.last_run:
        rows.append(f"Последний прогон: {book.last_run}")

    rows.append("")
    rows.append(f"Глав скачано: {book.last}"
                + (f" из {book.chapters}" if book.chapters else ""))
    if book.skipped:
        # Пропуски — главное, ради чего паспорт и заводится: дыра в
        # книге иначе обнаруживается при чтении, глав через двести.
        rows.append(f"Пропущено: {book.skipped} — платные, зашифрованные "
                    "или не отдавшиеся главы")
    if book.fresh:
        rows.append(f"На сайте появилось новых глав: {book.fresh}")

    if book.tags:
        rows.append("")
        rows.append("Метки: " + ", ".join(book.tags))
    if book.marks:
        rows.append("Пометки: " + ", ".join(MARKS.get(m, m) for m in book.marks))
    if book.note:
        rows.append("")
        rows.append(book.note)

    rows.append("")
    rows.append("---")
    rows.append("Файл создан NEUROSTRAZH и перезаписывается при каждой "
                "докачке. Свои заметки лучше держать в отдельном файле.")
    return "\n".join(rows) + "\n"


def save_passport(book: Book, folder=None) -> str:
    """Записать паспорт в папку книги. Вернёт путь или пустую строку.

    Отсутствие папки — не беда прогона: книга скачана, а паспорт всего
    лишь удобство. Поэтому здесь ничего не выбрасывается наружу.
    """
    # Пустой путь проверять отдельно: `Path("")` — это не «никуда», а
    # текущая папка, и она существует всегда. Паспорт книги, которую ещё
    # не качали, лёг бы рядом с самой программой.
    said = str(folder or book.folder or "").strip()
    if not said:
        return ""
    where = Path(said)
    if not where.is_dir():
        return ""
    path = where / PASSPORT
    try:
        path.write_text(passport(book), encoding="utf-8")
    except OSError as exc:
        log.warning("Паспорт книги не записался (%s): %s", path, exc)
        return ""
    return str(path)


def state() -> dict:
    """Сводка для вкладки: сколько книг и сколько ждут докачки."""
    rows = all_books()
    return {
        "books": len(rows),
        "downloaded": sum(1 for b in rows if b.downloaded),
        "updatable": sum(1 for b in rows if b.fresh),
        "marks": {name: sum(1 for b in rows if name in b.marks)
                  for name in MARKS},
    }


__all__ = ["AUTO", "Book", "LIBRARY_FILE", "MARKS", "PASSPORT", "all_books",
           "clear", "forget", "get", "key_of", "mark", "passport", "remember",
           "save_passport", "set_note", "stamp", "state", "touch"]
