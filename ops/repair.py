"""Починка находок осмотра — на месте, в тех же файлах.

Осмотр говорит, что не так, и на этом обрывается: дальше человек остаётся
с папкой в несколько сотен файлов и списком имён. Здесь то, что можно
починить, не выходя с той же карточки.

Работает по именам файлов из отчёта — тех самых, что осмотр показал. И
только по ним: своего мнения о том, что ещё в папке починить, у починки
нет. Это не осторожность ради осторожности — папку выбирает человек, и
выбрать он может рабочий стол.

Копия перед правкой обязательна и делается сама. Правка идёт в тех же
файлах — вернуть «как было» иначе неоткуда, а первое, чего хочется после
неудачной автоправки, это именно вернуть.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import history as history_op
from .base import collect_files

log = logging.getLogger(__name__)

#: Хвост, которым осмотр дописывает к имени размер: «глава.txt — 812
#: знаков». Он часть подписи находки, а не часть имени файла.
SIZE_TAIL = re.compile(r"\s+[—–-]\s+\d+\s+знаков\s*$")

#: Сколько строк снимает кнопка «убрать шапку». Ровно столько и пишет
#: качалка: название книги, название главы, пустая строка (см.
#: `mvl/paths.write_chapter`). Не догадка — то же число с другого конца.
HEAD_LINES = 2

#: Что правим на месте. Обычный текст: у него строка — это строка, и
#: снять две первые можно, ничего больше не тронув. В .docx и .epub то же
#: действие означало бы перезапись файла целиком, со стилями и разметкой,
#: — и это уже не «убрать две строки».
PLAIN = {".txt", ".md"}


def named(where) -> list[str]:
    """Имена файлов из строк отчёта.

    Осмотр иногда дописывает к имени подробность — размер главы. Для
    показа она нужна, для поиска файла мешает.
    """
    names = []
    for one in where or []:
        name = SIZE_TAIL.sub("", str(one)).strip()
        if name:
            names.append(name)
    return names


def find(targets, where) -> tuple[list[Path], list[str]]:
    """Файлы находки среди выбранного. Второе — чего не нашлось.

    Сверяем по имени, а не по пути: в отчёте лежит имя файла, и оно всё,
    что о нём известно.
    """
    wanted = {name.lower() for name in named(where)}
    if not wanted:
        return [], []

    try:
        here = collect_files(targets)
    except Exception as exc:  # noqa: BLE001 — читаемых файлов может не быть
        # Папка бывает и вовсе без глав: дыры в нумерации чинят там, где
        # файлов ещё нет. Это не беда, а «не нашлось ни одного».
        log.info("В %s читаемых файлов нет: %s", targets, exc)
        return [], named(where)

    found: dict[str, Path] = {}
    for path in here:
        key = path.name.lower()
        if key in wanted and key not in found:
            found[key] = path
    missed = [name for name in named(where) if name.lower() not in found]
    return list(found.values()), missed


@dataclass
class Fixed:
    """Что вышло из починки."""

    #: Сколько файлов правда изменилось.
    changed: int = 0
    #: Сколько прошло мимо и почему — по одной строке на файл.
    skipped: list[str] = field(default_factory=list)
    #: Куда легла копия «как было».
    backup: str = ""
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "changed": self.changed,
            "skipped": self.skipped,
            "backup": self.backup,
            "failures": self.failures,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        if not self.changed and not self.skipped and not self.failures:
            return "Править было нечего"
        parts = [f"Поправлено файлов: {self.changed}"]
        if self.skipped:
            parts.append(f"пропущено {len(self.skipped)}")
        if self.failures:
            parts.append(f"не вышло {len(self.failures)}")
        return " · ".join(parts)


def _without_head(text: str, lines: int) -> tuple[str, str]:
    """Текст без первых `lines` непустых строк. Второе — почему не тронули.

    Считаем непустые: между шапкой и текстом стоит пустая строка, и по
    сырому счёту «две первых» снялись бы название книги и она.

    Файл, в котором после снятия шапки ничего не остаётся, не трогаем
    вовсе. Глава из двух строк — это уже беда, и превращать её в пустой
    файл значит менять беду, которую видно, на беду, которой не видно.
    """
    rows = text.splitlines()
    seen = 0
    cut = 0
    for index, row in enumerate(rows):
        if row.strip():
            seen += 1
            if seen == lines:
                cut = index + 1
                break
    if seen < lines:
        return "", f"строк меньше {lines}"

    rest = rows[cut:]
    if not any(row.strip() for row in rest):
        return "", "кроме шапки в файле ничего нет"

    # Пустые строки, оставшиеся от шапки, уходят вместе с ней: иначе файл
    # начинался бы с пустой строки, и читалка сочла бы её названием главы.
    while rest and not rest[0].strip():
        rest.pop(0)
    return "\n".join(rest) + "\n", ""


def cut_head(targets, where, lines: int = HEAD_LINES) -> Fixed:
    """Снимает шапку — название книги и заголовок — с названных глав.

    Качалка пишет её в каждый файл нарочно: без неё непонятно, что за
    книга лежит в папке. Но в тексте, который потом переводят и
    склеивают, эти две строки лишние, и осмотр на них спотыкается.
    """
    lines = max(1, int(lines))
    paths, missed = find(targets, where)
    done = Fixed(skipped=[f"{name}: не нашёлся в выбранной папке"
                          for name in missed])
    if not paths:
        return done

    plain = [path for path in paths if path.suffix.lower() in PLAIN]
    done.skipped += [f"{path.name}: {path.suffix} правится не построчно"
                     for path in paths if path.suffix.lower() not in PLAIN]
    if not plain:
        return done

    done.backup = history_op.backup_files(plain, "убрана шапка")

    for path in plain:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            done.failures.append(f"{path.name}: не прочитался ({exc})")
            continue

        rest, why = _without_head(text, lines)
        if why:
            done.skipped.append(f"{path.name}: {why}")
            continue
        if rest == text:
            done.skipped.append(f"{path.name}: шапки нет")
            continue

        try:
            # Через временный файл: обрыв на середине записи не должен
            # оставить от главы огрызок.
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_text(rest, encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            done.failures.append(f"{path.name}: не записался ({exc})")
            continue
        done.changed += 1

    if done.changed:
        history_op.add("убрана шапка глав", source=str(plain[0].parent),
                       output=str(plain[0].parent), files=done.changed,
                       failed=len(done.failures), backup=done.backup)
    return done


def numbers_of(where) -> list[int]:
    """Номера глав из строк отчёта.

    Осмотр называет главы по-разному: файлом («0042 - Имя.txt»), голым
    номером и диапазоном («1170–1175» — так сворачиваются пропуски).
    Здесь все три вида приводятся к одному — списку номеров, которые надо
    добрать.
    """
    numbers: set[int] = set()
    for one in named(where):
        for chunk in re.split(r"[·,]", one):
            chunk = chunk.strip()
            if not chunk:
                continue
            span = re.fullmatch(r"(\d+)\s*[–—-]\s*(\d+)", chunk)
            if span:
                low, high = int(span.group(1)), int(span.group(2))
                if low <= high and high - low <= 10000:
                    numbers.update(range(low, high + 1))
                continue
            # Имя файла начинается с номера: «0042 - Имя.txt». Номер в
            # середине имени номером главы не является.
            head = re.match(r"\s*(\d+)", chunk)
            if head:
                numbers.add(int(head.group(1)))
    return sorted(numbers)


#: Где качалка помнит, что уже скачано. Имя одно на всю программу — то
#: же, что в `mvl/downloader`; берём его оттуда, чтобы не разошлось.
STATE_FILE = "state.json"


@dataclass
class Dropped:
    """Что убрали перед перекачкой."""

    #: Файлы, которых больше нет.
    removed: list[str] = field(default_factory=list)
    #: Номера, забытые в state.json: без этого качалка сочла бы их
    #: готовыми и прошла мимо.
    forgotten: list[int] = field(default_factory=list)
    backup: str = ""
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"removed": self.removed, "forgotten": self.forgotten,
                "backup": self.backup, "failures": self.failures}


def _forget(folder: Path, numbers) -> list[int]:
    """Вычёркивает номера из state.json. Возвращает вычеркнутые.

    Глава считается готовой по записи в state.json, и удалить один файл
    мало: качалка увидит запись, файла не найдёт... а вот тут как раз и
    не пройдёт мимо — `is_done` проверяет, что файл на месте. Запись всё
    равно чистим: иначе в state.json остаётся имя файла, которого нет, и
    следующая глава ляжет под другим именем, а старое так и будет висеть.
    """
    path = folder / STATE_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Не прочитался %s: %s", path, exc)
        return []
    if not isinstance(data, dict) or not isinstance(data.get("downloaded"), dict):
        return []

    gone = []
    for number in numbers:
        if data["downloaded"].pop(str(number), None) is not None:
            gone.append(int(number))
        if isinstance(data.get("failed"), dict):
            data["failed"].pop(str(number), None)
    if not gone:
        return []

    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("Не записался %s: %s", path, exc)
        return []
    return gone


def drop(folder, where) -> Dropped:
    """Убирает названные главы, чтобы качалка взяла их заново.

    Испорченную главу мало перекачать поверх: качалка считает готовым
    всё, что лежит в папке, и пройдёт мимо. Поэтому файл сначала
    уносится, а номер вычёркивается из `state.json`.

    Копия — обязательно. Обрывок главы это всё-таки половина главы, и
    если перекачать не выйдет (сайт закрылся, глава стала платной),
    остаться совсем без неё хуже, чем с половиной.
    """
    folder = Path(str(folder)).expanduser()
    paths, _ = find(folder, where)
    # Ненайденное здесь молчит нарочно, в отличие от «убрать шапку». Дыру
    # в нумерации тем и чинят, что файла нет: жаловаться на его отсутствие
    # значило бы ругаться на саму работу.
    done = Dropped()

    if paths:
        done.backup = history_op.backup_files(paths, "перекачка глав")
        for path in paths:
            try:
                path.unlink()
            except OSError as exc:
                done.failures.append(f"{path.name}: не убрался ({exc})")
                continue
            done.removed.append(path.name)

    done.forgotten = _forget(folder, numbers_of(where))
    if done.removed:
        history_op.add("главы убраны под перекачку", source=str(folder),
                       output=str(folder), files=len(done.removed),
                       failed=len(done.failures), backup=done.backup)
    return done


__all__ = ["Dropped", "Fixed", "HEAD_LINES", "cut_head", "drop", "find",
           "named", "numbers_of"]
