"""Обновление программы: забираем только изменившиеся файлы.

Трафик у человека может быть на счету, поэтому способ выбран самый
экономный из возможных без git.

    | Шаг | Что спрашиваем | Сколько весит |
    |---|---|---|
    | проверка | адрес ветки (`git/ref`) | около трёхсот байт |
    | список | сравнение «мой коммит → последний» | десятки килобайт |
    | загрузка | сами файлы, поштучно | сколько изменилось |

Первый шаг дёшев настолько, что его не жалко делать при каждом запуске.
Второй и третий — только по кнопке: сколько именно будет стоить загрузка,
человек видит до того, как согласится.

Чего этот способ **не** делает и делать не должен:

- не трогает `config.json`, `proxies.txt` и `data/` — там ключи, пароли и
  история, а они принадлежат человеку, а не репозиторию;
- не пишет файл поверх старого напрямую: сперва временный рядом, потом
  переименование. Оборвётся связь — старый файл останется целым;
- не удаляет ничего, кроме файлов, которые в самом репозитории удалены.

Свой коммит программа помнит в `data/revision.json`. Первый запуск
считает, что стоит последняя версия: человек только что её скачал, а
качать весь репозиторий ради сверки — ровно тот трафик, который мы и
бережём.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from config import settings

from .base import Progress
from .history import DATA_DIR

log = logging.getLogger(__name__)

#: Корень программы — рядом с ним и лежат обновляемые файлы.
ROOT = Path(__file__).resolve().parent.parent

#: Где помним, на каком коммите стоим.
REVISION_FILE = DATA_DIR / "revision.json"

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"

#: GitHub отвечает и без ключа, но просит назваться.
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

#: Что не трогаем никогда. Настройки с ключом, список прокси с паролями и
#: всё нажитое: журнал, корзина, скачанные книги. Обновление меняет
#: программу, а не то, что человек ею сделал.
KEEP = frozenset({"config.json", "proxies.txt"})
KEEP_DIRS = ("data/", "outputs/", ".git/", ".venv/", "__pycache__/")

#: Больше этого числа файлов за раз — что-то не так: скорее всего, мы
#: сравниваем с не тем коммитом. Лучше остановиться и сказать, чем молча
#: перекачать весь репозиторий по дорогому трафику.
TOO_MANY = 120


def mine(path: str) -> bool:
    """Наш ли это файл — тот, который обновление вправе трогать."""
    name = str(path or "").replace("\\", "/").lstrip("/")
    if not name or ".." in name.split("/"):
        return False
    if name in KEEP:
        return False
    return not any(name.startswith(one) for one in KEEP_DIRS)


@dataclass
class Change:
    """Один файл, который изменился."""

    path: str = ""
    #: `added`, `modified`, `removed`, `renamed`.
    status: str = ""
    #: Сколько строк тронуто. Именно строк, а не байт: веса файла
    #: сравнение не отдаёт вовсе, и выдавать одно за другое нельзя —
    #: человек считает трафик по этому числу.
    lines: int = 0

    @property
    def gone(self) -> bool:
        return self.status == "removed"

    def as_dict(self) -> dict:
        return {"path": self.path, "status": self.status,
                "lines": self.lines, "gone": self.gone}


@dataclass
class Look:
    """Что видно снаружи: где мы и что там вышло."""

    have: str = ""
    there: str = ""
    changes: list[Change] = field(default_factory=list)
    #: Не смогли посчитать разницу — скажем словами, а не пустотой.
    trouble: str = ""

    @property
    def fresh(self) -> bool:
        """Стоит ли последняя версия."""
        return bool(self.have) and self.have == self.there

    @property
    def lines(self) -> int:
        """Сколько строк тронуто всего.

        Единственная мерка, которую сравнение даёт заранее. Вес в байтах
        станет известен только при загрузке, и обещать его до неё —
        значит соврать человеку, который считает трафик.
        """
        return sum(one.lines for one in self.changes if not one.gone)

    @property
    def needs_install(self) -> bool:
        """Менялся ли список зависимостей.

        Обновление приносит файлы, но не библиотеки. Появится в новой
        версии зависимость — программа после перезапуска упадёт на
        импорте, и человек с медленным интернетом останется без рабочей
        программы, не понимая почему.
        """
        return any(one.path == "requirements.txt" for one in self.changes)

    def as_dict(self) -> dict:
        return {
            "have": self.have, "there": self.there,
            "fresh": self.fresh,
            "needs_install": self.needs_install,
            "changes": [one.as_dict() for one in self.changes],
            "files": len(self.changes),
            "lines": self.lines,
            "trouble": self.trouble,
            "where": f"{settings.update.owner}/{settings.update.repo}"
                     f"@{settings.update.branch}",
        }


@dataclass
class Done:
    """Итог загрузки."""

    written: int = 0
    removed: int = 0
    bytes: int = 0
    failures: list[str] = field(default_factory=list)
    revision: str = ""
    #: Куда легла копия прежних файлов — по ней и возвращаются назад.
    backup: str = ""
    #: Менялся ли `requirements.txt`: библиотеки обновление не ставит.
    needs_install: bool = False
    #: Заголовки, появившиеся в истории изменений, — «что нового».
    news: list[str] = field(default_factory=list)
    #: Программа после обновления не запустилась, и мы вернули прежнюю.
    rolled_back: str = ""

    def as_dict(self) -> dict:
        return {"written": self.written, "removed": self.removed,
                "bytes": self.bytes, "failures": self.failures,
                "revision": self.revision, "backup": self.backup,
                "needs_install": self.needs_install, "news": self.news,
                "rolled_back": self.rolled_back}


def current() -> str:
    """Коммит, на котором стоим. Пусто — ещё не знаем."""
    try:
        kept = json.loads(REVISION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(kept.get("revision") or "") if isinstance(kept, dict) else ""


def remember(revision: str) -> None:
    """Запоминает коммит. Без него следующая проверка сравнит с пустотой."""
    try:
        REVISION_FILE.parent.mkdir(parents=True, exist_ok=True)
        REVISION_FILE.write_text(
            json.dumps({"revision": str(revision or "")}, ensure_ascii=False),
            encoding="utf-8")
    except OSError as exc:
        log.warning("Не удалось запомнить версию: %s", exc)


def _head(client) -> str:
    """Последний коммит ветки. Самый дешёвый вопрос из возможных."""
    where = settings.update
    answer = client.get(
        f"{API}/repos/{where.owner}/{where.repo}/git/ref/heads/{where.branch}",
        headers=HEADERS)
    body = answer.json()
    found = (body or {}).get("object") or {}
    return str(found.get("sha") or "")


def look(client) -> Look:
    """Что нового. Один дешёвый запрос, и второй — только если есть что.

    Первый запуск ничего не качает: считаем, что стоит то, что человек
    только что скачал, и просто запоминаем этот коммит.
    """
    there = _head(client)
    have = current()
    if not have:
        remember(there)
        return Look(have=there, there=there)
    if have == there:
        return Look(have=have, there=there)

    where = settings.update
    answer = client.get(
        f"{API}/repos/{where.owner}/{where.repo}/compare/{have}...{there}",
        headers=HEADERS)
    body = answer.json() or {}
    rows = body.get("files")
    if not isinstance(rows, list):
        # Коммита, на котором мы стоим, в репозитории уже нет — так бывает
        # после переписанной истории. Сказать об этом прямо честнее, чем
        # молча перекачать всё.
        return Look(have=have, there=there,
                    trouble="Не удалось сравнить версии: коммита, на котором "
                            "стоит программа, в репозитории больше нет. "
                            "Скачайте свежую копию целиком один раз.")

    changes = [
        Change(path=str(one.get("filename") or ""),
               status=str(one.get("status") or ""),
               lines=int(one.get("changes") or 0))
        for one in rows if isinstance(one, dict)
    ]
    changes = [one for one in changes if mine(one.path)]
    if len(changes) > TOO_MANY:
        return Look(have=have, there=there, changes=changes,
                    trouble=f"Изменилось {len(changes)} файлов — это больше "
                            "похоже на новую копию, чем на обновление. "
                            "Скачайте свежую версию целиком.")
    return Look(have=have, there=there, changes=changes)


def _write(path: Path, body: bytes) -> None:
    """Пишет файл через временный рядом.

    Прямая запись поверх старого оставила бы половину файла, оборвись
    связь на середине, — и программа перестала бы запускаться.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    spare = path.with_name(path.name + ".new")
    spare.write_bytes(body)
    os.replace(spare, path)


CHANGELOG = "CHANGELOG.md"

#: Сколько ждать пробного запуска. Импорт всей программы укладывается в
#: пару секунд; минута — с запасом на медленную машину.
CHECK_TIMEOUT = 60


def headings(text: str) -> list[str]:
    """Заголовки разделов истории изменений — по ним и видно, что нового."""
    return [line[4:].strip() for line in str(text or "").splitlines()
            if line.startswith("### ")]


def news_of(before: str, after: str) -> list[str]:
    """Что появилось в истории изменений: разница заголовков.

    Показывать весь `CHANGELOG.md` бессмысленно — там полторы тысячи
    строк. А «обновлено 12 файлов» не говорит ничего.
    """
    had = set(headings(before))
    return [one for one in headings(after) if one not in had]


def works() -> str:
    """Заводится ли программа после обновления. Пусто — заводится.

    Отдельным процессом, а не импортом на месте: этот уже запущен со
    старым кодом, и проверить им новый нельзя.
    """
    import subprocess
    import sys

    # Проверять нечего, если программы по этому пути нет вовсе: так
    # бывает в тестах, где корень свой и пустой.
    if not (ROOT / "webapp" / "app.py").is_file():
        return ""

    try:
        run = subprocess.run(
            [sys.executable, "-c", "import webapp.app"],
            cwd=str(ROOT), capture_output=True, text=True,
            timeout=CHECK_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        # Проверить не вышло — это не приговор обновлению.
        log.warning("Пробный запуск не состоялся: %s", exc)
        return ""
    if run.returncode == 0:
        return ""
    tail = (run.stderr or run.stdout or "").strip().splitlines()
    return tail[-1] if tail else f"код возврата {run.returncode}"


def undo(backup_path) -> int:
    """Возвращает файлы программы из копии на место.

    Своё, а не `history.restore`: тот перед восстановлением копирует всю
    папку назначения, а здесь папка назначения — вся программа вместе с
    книгами и журналом.
    """
    source = Path(backup_path)
    if not source.is_dir():
        return 0
    count = 0
    for one in source.rglob("*"):
        if not one.is_file():
            continue
        target = ROOT / one.relative_to(source)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _write(target, one.read_bytes())
            count += 1
        except OSError as exc:
            log.warning("Не вернуть %s: %s", target, exc)
    return count


def last_backup() -> str:
    """Последняя копия, снятая перед обновлением. Пусто — такой нет."""
    from .history import backups

    for one in backups():
        if one.name.endswith("_обновление"):
            return str(one)
    return ""


def apply(client, plan: Look, progress: Progress | None = None,
          check: bool = True) -> Done:
    """Забирает изменившиеся файлы и раскладывает их по местам.

    Перед заменой старые уходят в корзину — с сохранением расположения,
    иначе вернуть их было бы некуда. После замены программа проверяется
    пробным запуском: обновление, после которого она не заводится, хуже
    отсутствия обновления, а человек с медленным каналом остался бы с
    нерабочей программой и без быстрого пути назад.
    """
    from .history import backup_tree

    progress = progress or Progress()
    result = Done(needs_install=plan.needs_install)
    where = settings.update

    was_changelog = ""
    if any(one.path == CHANGELOG for one in plan.changes):
        try:
            was_changelog = (ROOT / CHANGELOG).read_text(encoding="utf-8")
        except OSError as exc:
            log.debug("История изменений не прочиталась: %s", exc)

    doomed = [ROOT / one.path for one in plan.changes if not one.gone]
    saved = backup_tree(ROOT, doomed, "обновление")
    result.backup = saved
    if saved:
        log.info("Прежние файлы программы скопированы в %s", saved)

    for index, change in enumerate(plan.changes, 1):
        progress.check()
        target = ROOT / change.path
        try:
            if change.gone:
                target.unlink(missing_ok=True)
                result.removed += 1
            else:
                answer = client.get(
                    f"{RAW}/{where.owner}/{where.repo}/{plan.there}/{change.path}")
                body = answer.content
                _write(target, body)
                result.written += 1
                result.bytes += len(body)
        except Exception as exc:  # noqa: BLE001 — показываем любую поломку
            result.failures.append(f"{change.path}: {type(exc).__name__}: {exc}")
        progress.step(index, len(plan.changes),
                      f"Файл {index} из {len(plan.changes)}")

    if was_changelog:
        try:
            result.news = news_of(was_changelog,
                                  (ROOT / CHANGELOG).read_text(encoding="utf-8"))
        except OSError as exc:
            log.debug("История изменений не перечиталась: %s", exc)

    # Заводится ли программа с новыми файлами. Не заводится — возвращаем
    # прежние: остаться без рабочей программы страшнее, чем без новой.
    if check and not result.failures and result.written:
        broke = works()
        if broke:
            log.error("После обновления программа не запускается: %s", broke)
            result.rolled_back = broke
            undo(saved)
            return result

    # Версию запоминаем, только если всё легло. Иначе следующая проверка
    # решила бы, что обновляться не надо, а половина файлов осталась
    # старой.
    if not result.failures:
        remember(plan.there)
        result.revision = plan.there
    return result
