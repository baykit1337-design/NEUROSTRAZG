"""Связь с переводчиком EPUB — чужой программой, стоящей рядом.

Перевод книг делает `translatorFork_MOD` — настольное приложение на PyQt6.
Встраивать его в NEUROSTRAZH нельзя и не нужно: PyQt6 там импортируют две
сотни файлов из четырёхсот шестидесяти, логика перевода живёт в сигналах и
диалогах, а вытащить из этого движок значит переписать чужую программу и
сопровождать свою копию вечно.

Зато у неё есть готовый вход для таких, как мы. В её собственной
документации раздел называется «CLI для автоматизации агентами»: команды
запускаются без окна, ответ печатается JSON-ом в stdout, а логи уходят в
stderr, чтобы разбор не спотыкался.

Поэтому здесь — не перевод, а разговор. Мы запускаем чужую программу
отдельным процессом и читаем её ответ, ровно как `mvl/nativedialog.py`
запускает окно выбора файлов.

Что из этого следует и что важно помнить:

- переводчик остаётся отдельной программой. Мы храним только путь к нему;
  обновляется он сам по себе, и на наш репозиторий его гигабайт не влияет;
- глоссарий, карта перевода и переведённые главы лежат в папке проекта
  переводчика — там же, где их оставляет его собственное окно. Своего
  хранилища у нас нет вовсе;
- промпты, ключи и настройки лежат в его домашней папке
  (`~/.epub_translator`). Мы их не читаем и не пишем: что человек настроил
  в родном окне, то и применится.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from config import settings

log = logging.getLogger(__name__)

#: По этому файлу папка опознаётся как переводчик, годный для разговора.
#: Проверять само имя папки бессмысленно: её называют как угодно.
MARK = Path("gemini_translator") / "cli.py"

#: А по этим — что папка та самая, просто версия старая. Разница важная:
#: «вы принесли не ту папку» и «папка верная, но в этой версии нет CLI» —
#: это две совершенно разные беды с разным лечением, а одинаковый отказ
#: отправлял человека искать то, что у него и так лежит перед глазами.
OLD_MARKS = (Path("main.py"), Path("gemini_translator") / "__init__.py")

#: А по этому — что человек принёс собранную версию, а не исходники.
#: `base_library.zip` лежит в нутре любой сборки PyInstaller, рядом с
#: `python3*.dll` и десятками `.pyd`.
#:
#: Разница тут не в уровне папки, и совет «возьмите папку выше» тут не
#: работает: в сборке питон уже скомпилирован, и `cli.py` в ней нет
#: вовсе — ни внутри `_internal`, ни рядом с exe. Прежний отказ отправлял
#: человека искать файл, которого у него в принципе нет.
BUILT_MARK = "base_library.zip"

#: Где эта примета лежит: в самой папке (человек указал нутро сборки) или
#: в её `_internal` (указал папку с exe).
BUILT_WHERE = (Path(BUILT_MARK), Path("_internal") / BUILT_MARK)

#: Где переводчик держит своё окружение. Так его создаёт `run.bat`.
VENV = (
    Path(".venv") / "Scripts" / "python.exe",   # Windows
    Path(".venv") / "bin" / "python",           # Linux и macOS
    Path("venv") / "Scripts" / "python.exe",
    Path("venv") / "bin" / "python",
)

#: Сколько ждать быстрых команд. Перевод сюда не относится — у него свой
#: срок, измеряемый часами.
QUICK_TIMEOUT = 120

#: План в сеть не ходит, но епаб читает целиком и считает знаки. На книге
#: в полтысячи глав это уже не мгновение, а быстрый срок ему тесен.
PLAN_TIMEOUT = 600

#: Какие главы брать. Слова не наши — так их называет сам переводчик, и
#: переводить их в свои значило бы держать таблицу соответствий ради
#: ничего.
PENDING = "pending"      # только ещё не переведённые
WHOLE = "all"            # все подряд, заново
DONE = "translated"      # только уже переведённые
SCOPES = (PENDING, WHOLE, DONE)

#: Сколько глав показывать списком. Остальные — счётчиком: на пятистах
#: главах список перестаёт быть ответом на вопрос «что возьмётся».
SHOW_CHAPTERS = 12


#: Чем ставятся зависимости переводчика. Список его собственный:
#: `requirements-translator-only.txt` — самый короткий набор, который он
#: сам же и объявил (без браузера, озвучки и загрузчиков).
#:
#: `fs` дописан отдельно, и это не придирка: без него не поднимается его
#: же патч файловой системы, а в короткий список он не попал. Проверено
#: на живой копии: с этими двумя `status` отвечает `ok`.
NEEDS = "python -m pip install -r requirements-translator-only.txt fs"

#: Отказ, за которым стоит не поломка, а неустановленный пакет.
MISSING = re.compile(r"No module named '([^']+)'")


class TranslatorError(Exception):
    """С переводчиком не поговорили. Причина — в сообщении."""


def _about(said: str) -> str:
    """Отказ переводчика словами, за которыми видно, что делать.

    Голое `ModuleNotFoundError: No module named 'fs'` в карточке — тупик:
    человек видит чужую питоновскую ошибку и не знает ни чей это пакет,
    ни куда его ставить. А беда обычная: взяли исходники и не поставили
    им зависимости.
    """
    said = str(said or "")
    found = MISSING.search(said)
    if not found:
        return said
    return (f"Переводчику не хватает пакета «{found.group(1)}» — это его "
            "собственная зависимость, и её не поставили.\n"
            "Откройте командную строку в его папке и выполните:\n"
            f"{NEEDS}\n"
            "Тем же Python, которым программа его и запускает. "
            "Установленную версию переводчика это не затронет.")


def where() -> str:
    """Путь к переводчику из настроек. Пусто — не указан."""
    return str(getattr(settings.translator, "path", "") or "").strip()


def looks_right(path) -> bool:
    """Годится ли папка для разговора: есть ли в ней CLI."""
    return bool(path) and (Path(str(path)).expanduser() / MARK).is_file()


def looks_built(path) -> bool:
    """Это собранная версия (.exe), а не исходники переводчика."""
    if not path:
        return False
    root = Path(str(path)).expanduser()
    return any((root / one).is_file() for one in BUILT_WHERE)


def looks_old(path) -> bool:
    """Та ли это папка, но без CLI — то есть версия старше него."""
    if not path:
        return False
    root = Path(str(path)).expanduser()
    return (all((root / one).exists() for one in OLD_MARKS)
            and not (root / MARK).is_file())


def python_for(path) -> str:
    """Каким Python его запускать.

    Сперва — окружение рядом с самим переводчиком: там стоят PyQt6 и
    остальные его зависимости, а в нашем окружении их нет и быть не
    должно. Не нашлось — берём то, что назвали в настройках, а в
    последнюю очередь `python` из PATH.
    """
    root = Path(str(path)).expanduser()
    for one in VENV:
        found = root / one
        if found.is_file():
            return str(found)

    named = str(getattr(settings.translator, "python", "") or "").strip()
    if named:
        return named
    return "python"


def trouble_with(path) -> str:
    """Почему с этой папкой не поговорить. Пусто — можно.

    Объяснение одно на всех: и проверка при выборе папки, и сам запуск
    должны говорить человеку одно и то же. Разойдись они — и совет
    зависел бы от того, какой кнопкой человек до него добрался.
    """
    if not path:
        return ("Не указано, где стоит переводчик. Укажите папку, в "
                "которой лежит его `run.bat` — ту же, из которой вы его "
                "запускаете.")
    root = Path(str(path)).expanduser()
    if not root.is_dir():
        return f"Папки нет: {root}"
    if looks_built(root) and not looks_right(root):
        return ("Это установленная версия переводчика, а не его исходники: "
                f"в папке лежит `{BUILT_MARK}`. Внутрь такой сборки хода "
                f"нет — {MARK.as_posix()} в неё не попал, а сам exe собран "
                "из `main.py`, который только открывает окно. Папкой выше "
                "это не лечится.\n"
                "Возьмите тот же переводчик исходниками — на его странице "
                "кнопка «Code» и «Download ZIP» — и распакуйте куда "
                "угодно. Ставить и запускать распакованное не надо: "
                "разговор без окна обходится без PyQt6. Установленную "
                "версию тоже не трогайте, она останется как была: ключи и "
                "промпты у неё лежат отдельно, в ~/.epub_translator.")
    if looks_old(root):
        return ("Папка та, но версия переводчика старая: в ней нет "
                f"{MARK.as_posix()}. Работа без окна появилась у него "
                "позже. Обновите переводчик до свежей версии — ключи, "
                "промпты и настройки при этом не пострадают: они лежат "
                "отдельно, в домашней папке ~/.epub_translator.")
    if not looks_right(root):
        return (f"В папке {root} нет ни {MARK.as_posix()}, ни `main.py` — "
                "это не папка переводчика. Нужна та, из которой вы его "
                "запускаете.")
    return ""


def _explain(path) -> None:
    """Отказ словами, а не пустотой. Кидает, если говорить не с чем."""
    why = trouble_with(path)
    if why:
        raise TranslatorError(why)


def run(command: str, args=(), path: str = "", timeout: int | None = None) -> dict:
    """Одна команда переводчика. Возвращает разобранный ответ.

    Ответ приходит JSON-ом в stdout, а логи — в stderr, поэтому читаем
    только первый. Если в stdout оказалось не JSON, показываем начало
    ответа как есть: молчаливое «что-то пошло не так» здесь бесполезно.
    """
    path = str(path or where()).strip()
    _explain(path)
    root = Path(path).expanduser()

    line = [python_for(root), "-m", "gemini_translator.cli", str(command),
            *[str(one) for one in args]]
    # Окно не открывается, но Qt всё равно поднимается — просим его
    # обойтись без экрана. Сам переводчик делает так же.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
           "PYTHONIOENCODING": "utf-8"}

    log.info("Переводчик: %s", " ".join(line[1:]))
    try:
        said = subprocess.run(
            line, cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env,
            timeout=timeout or QUICK_TIMEOUT)
    except FileNotFoundError as exc:
        raise TranslatorError(
            f"Не запустился Python переводчика ({python_for(root)}): {exc}. "
            "Запустите переводчик его собственным `run.bat` — он создаст "
            "себе окружение.") from exc
    except subprocess.TimeoutExpired as exc:
        raise TranslatorError(
            f"Переводчик не ответил за {timeout or QUICK_TIMEOUT} секунд") from exc

    body = (said.stdout or "").strip()
    if not body:
        tail = (said.stderr or "").strip().splitlines()
        why = tail[-1] if tail else f"код возврата {said.returncode}"
        # Через тот же разбор: нехватка пакета валит команду и до JSON, и
        # молча — а лечится она одинаково.
        raise TranslatorError(f"Переводчик ничего не ответил: {_about(why)}")

    try:
        found = json.loads(body)
    except ValueError as exc:
        raise TranslatorError(
            f"Ответ переводчика — не JSON: {body[:200]}") from exc
    if not isinstance(found, dict):
        raise TranslatorError(f"Ответ переводчика непонятен: {body[:200]}")
    return found


def status(path: str = "") -> dict:
    """Что там вообще есть: провайдеры, ключи, модели, проекты.

    Самая дешёвая команда из всех — в сеть не ходит. Ею и проверяется,
    что связка вообще живая.
    """
    said = run("status", path=path)
    if not said.get("ok", True):
        raise TranslatorError(
            _about(said.get("error") or "переводчик отказал"))
    return said


def short(said: dict) -> dict:
    """Ответ `status` в том виде, в каком его показывают человеку.

    Читаем бережно: это чужой формат, и он может поменяться. Чего не
    нашли — не показываем, но и не падаем.
    """
    rows = []
    for one in said.get("providers") or []:
        if not isinstance(one, dict):
            continue
        rows.append({
            "id": str(one.get("id") or one.get("provider") or ""),
            "name": str(one.get("name") or one.get("title") or ""),
            "keys": int(one.get("keys") or one.get("key_count") or 0),
            "models": int(one.get("models") or one.get("model_count") or 0),
        })

    saved = said.get("settings") if isinstance(said.get("settings"), dict) else {}
    return {
        "providers": rows,
        "keys": sum(one["keys"] for one in rows),
        "provider": str(saved.get("provider") or said.get("provider") or ""),
        "model": str(saved.get("model") or said.get("model") or ""),
        "projects": len(said.get("projects") or said.get("history") or []),
        "version": str(said.get("version") or ""),
    }


def _whole(value) -> int:
    """Целое из чужого ответа. Не число — ноль, а не поломка."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def plan(epub: str, project: str, scope: str = PENDING,
         path: str = "") -> dict:
    """Что именно будет переведено — не трогая ни сети, ни ключей.

    Это «до и после» для перевода, и нужно оно ровно затем же, зачем оно
    нужно в форматировании: увидеть работу до того, как за неё заплатят.
    Цена тут — квота ключей, и промахнуться дороже всего: узнать, что
    взялась вся книга вместо десяти глав, посреди прогона поздно.

    План читает епаб и считает главы, задачи и знаки. В сеть он не ходит
    вовсе, поэтому нажимать его можно сколько угодно.
    """
    book = Path(str(epub or "").strip()).expanduser()
    if not str(epub or "").strip():
        raise TranslatorError("Не выбран .epub, который переводить.")
    if not book.is_file():
        raise TranslatorError(f"Файла нет: {book}")
    if not str(project or "").strip():
        raise TranslatorError(
            "Не указана папка проекта. Переводчик держит в ней главы, "
            "глоссарий и карту перевода — без неё ему некуда складывать.")
    if scope not in SCOPES:
        raise TranslatorError(f"Неизвестно, какие главы брать: {scope}")

    return run("plan", ["--epub", str(book),
                        "--project", str(Path(str(project)).expanduser()),
                        "--chapters", scope],
               path=path, timeout=PLAN_TIMEOUT)


def short_plan(said: dict) -> dict:
    """План в том виде, в каком его показывают человеку.

    Читаем бережно, как и всё остальное отсюда: формат чужой и может
    поменяться. Чего не нашли — не показываем, но и не падаем.
    """
    made = said.get("plan") if isinstance(said.get("plan"), dict) else {}
    saved = said.get("settings") if isinstance(said.get("settings"), dict) else {}
    limits = saved.get("model_config") if isinstance(
        saved.get("model_config"), dict) else {}

    names = [str(one) for one in (made.get("chapters") or []) if one]
    return {
        "chapters": _whole(made.get("chapter_count")) or len(names),
        "tasks": _whole(made.get("task_count")),
        "chars": _whole(made.get("total_source_chars")),
        "tokens": _whole(made.get("total_source_tokens")),
        "provider": str(saved.get("provider") or ""),
        "model": str(saved.get("model") or ""),
        # Сколько запросов модель отдаёт в минуту и в сутки. Здесь это не
        # мелочь: по ним и видно, хватит ли квоты на всю книгу разом.
        "rpm": _whole(limits.get("rpm")),
        "rpd": _whole(limits.get("rpd")),
        "sample": names[:SHOW_CHAPTERS],
        "more": max(0, len(names) - SHOW_CHAPTERS),
    }


def state(path: str = "") -> dict:
    """Что показывать в карточке до всякой проверки."""
    path = str(path or where()).strip()
    return {
        "path": path,
        "found": looks_right(path),
        # Отдельно, чтобы страница могла сказать не «не та папка», а
        # «папка та, версия старая» — это разные советы человеку.
        "old": looks_old(path),
        "python": python_for(path) if path else "",
        "own_python": sys.executable,
    }


__all__ = ["BUILT_MARK", "DONE", "MARK", "NEEDS", "OLD_MARKS", "PENDING",
           "PLAN_TIMEOUT", "QUICK_TIMEOUT", "SCOPES", "SHOW_CHAPTERS",
           "TranslatorError", "WHOLE", "looks_built", "looks_old",
           "looks_right", "plan", "python_for", "run", "short", "short_plan",
           "state", "status", "trouble_with", "where"]
