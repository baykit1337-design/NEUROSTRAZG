"""Обложки книг из рейтинга: свой кэш вместо чужих ссылок (2.3 ТЗ).

Адрес обложки на сайте подписан и содержит срок действия (`x-expires`).
В сохранённом срезе такая ссылка протухает, и вчерашний рейтинг остаётся
без картинок — а срезы у нас хранятся месяцами.

Поэтому картинка скачивается один раз и кладётся к себе:
`data/covers/{bookId}.webp`. Дальше рейтинг берёт её оттуда, и от чужих
подписанных адресов больше ничего не зависит.

Скачивание идёт по требованию и молча: обложка — украшение, и ронять из-за
неё показ рейтинга нельзя.
"""

from __future__ import annotations

import logging
import re
import threading

from .history import DATA_DIR

log = logging.getLogger(__name__)

COVER_DIR = DATA_DIR / "covers"

#: Имя файла — только код книги. Всё прочее в имени было бы дырой:
#: `bookId` приходит с чужого сайта.
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: Обложка — картинка на 64 пикселя высотой. Всё, что заметно больше
#: полумегабайта, обложкой быть не может, и качать это незачем.
MAX_BYTES = 2 * 1024 * 1024

#: Расширение одно на все: чем бы ни отдал сайт, у нас это просто файл
#: картинки, и разбираться в формате незачем — браузер разберётся сам.
SUFFIX = ".webp"

_LOCK = threading.Lock()


def safe_id(book_id) -> str:
    """Код книги, пригодный для имени файла. Пусто — значит, не пригоден."""
    book_id = str(book_id or "").strip()
    return book_id if SAFE_ID.match(book_id) else ""


def path_for(book_id) -> object | None:
    """Куда ляжет обложка этой книги. None — код никуда не годится."""
    ident = safe_id(book_id)
    return (COVER_DIR / f"{ident}{SUFFIX}") if ident else None


def have(book_id) -> bool:
    path = path_for(book_id)
    return bool(path and path.exists() and path.stat().st_size > 0)


def fetch(client, book_id, url: str) -> bool:
    """Скачивает обложку в кэш. Возвращает, есть ли она теперь на месте.

    Уже скачанное не перекачивается: адрес в новом срезе другой, а
    картинка та же.
    """
    path = path_for(book_id)
    if path is None or not str(url or "").strip():
        return False
    if have(book_id):
        return True

    try:
        response = client.get(url)
        data = getattr(response, "content", b"") or b""
        status = getattr(response, "status_code", 200)
        if status >= 400 or not data or len(data) > MAX_BYTES:
            log.info("Обложка %s не скачалась: ответ %s, байт %s",
                     book_id, status, len(data))
            return False
    except Exception as exc:  # noqa: BLE001 — обложка не повод ронять экран
        log.info("Обложка %s не скачалась: %s", book_id, exc)
        return False

    with _LOCK:
        try:
            COVER_DIR.mkdir(parents=True, exist_ok=True)
            # Пишем через временный файл: половина картинки на диске
            # выглядит как испорченный кэш и чинится только руками.
            tmp = path.with_suffix(SUFFIX + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError as exc:
            log.info("Обложку %s не записать: %s", book_id, exc)
            return False
    return True


#: Первые байты, по которым узнаётся формат картинки. Расширение файла у
#: нас одно на все, а браузеру нужен настоящий тип: объявишь webp там, где
#: лежит jpeg, — картинка не покажется вовсе.
SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def mimetype_of(path) -> str:
    """Какого формата картинка на самом деле."""
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return "image/webp"

    for signature, kind in SIGNATURES:
        if head.startswith(signature):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    # Сайт отдаёт webp — на нём и останавливаемся, если подписи нет.
    return "image/webp"


def forget(book_id) -> bool:
    """Убирает обложку из кэша. Нужно, когда картинка испортилась."""
    path = path_for(book_id)
    if path is None or not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def state() -> dict:
    """Сколько обложек накопилось и сколько они весят."""
    if not COVER_DIR.exists():
        return {"dir": str(COVER_DIR), "count": 0, "bytes": 0}
    files = [p for p in COVER_DIR.iterdir()
             if p.is_file() and p.suffix == SUFFIX]
    return {"dir": str(COVER_DIR), "count": len(files),
            "bytes": sum(p.stat().st_size for p in files)}
