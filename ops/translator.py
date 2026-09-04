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
import tempfile
import threading
import time
from pathlib import Path

from config import settings
from ops.base import Cancelled

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


def providers(path: str = "") -> dict:
    """Сервисы перевода, настроенные у него, — с числом ключей у каждого.

    Нужны затем, чтобы список в карточке был его собственный. Заведи мы
    свой перечень — он разошёлся бы с его настройками в первый же раз,
    когда он добавит себе провайдера.
    """
    said = run("providers", path=path)
    if not said.get("ok", True):
        raise TranslatorError(_about(said.get("error") or "переводчик отказал"))
    return said


def short_providers(said: dict) -> list:
    """Сервисы в том виде, в каком их показывают списком.

    Читаем бережно: формат чужой. Скрытые провайдеры не спрашиваем и не
    показываем — он их сам от себя прячет.
    """
    rows = []
    for one in said.get("providers") or []:
        if not isinstance(one, dict):
            continue
        name = str(one.get("display_name") or one.get("id") or "")
        if not name:
            continue
        rows.append({
            "id": str(one.get("id") or ""),
            "name": name,
            "keys": _whole(one.get("configured_keys")),
            "models": _whole(one.get("model_count")),
            # Провайдеру через браузер ключ не нужен, и «ключей: 0» у
            # него — не беда, а норма. Без этого признака карточка
            # ругалась бы на исправный сервис.
            "browser": bool(one.get("browser_based")),
            "needs_key": bool(one.get("requires_api_key", True)),
        })
    return rows


def models(provider: str = "", path: str = "") -> dict:
    """Модели одного сервиса — с его же квотами.

    Квоты тут не украшение: по ним и видно, хватит ли одной модели на
    книгу разом. Не назвали сервис — он ответит про сохранённый у себя.
    """
    args = ["--provider", str(provider).strip()] if str(provider or "").strip() else []
    said = run("models", args, path=path)
    if not said.get("ok", True):
        raise TranslatorError(_about(said.get("error") or "переводчик отказал"))
    return said


def short_models(said: dict) -> dict:
    """Модели в том виде, в каком их показывают списком."""
    rows = []
    for one in said.get("models") or []:
        if not isinstance(one, dict):
            continue
        name = str(one.get("name") or "")
        if not name:
            continue
        rows.append({
            "name": name,
            "rpm": _whole(one.get("rpm")),
            "rpd": _whole(one.get("rpd")),
            "context": _whole(one.get("context_window")),
            "thinking": bool(one.get("supports_thinking")),
        })
    return {
        "provider": str(said.get("provider") or ""),
        # Какая выбрана у него самого: с неё и начинаем, чтобы список в
        # карточке открывался на том же, что у него в окне.
        "saved": str(said.get("saved_model") or ""),
        "models": rows,
    }


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


#: Долгие команды идут часами: книга на пятьсот глав — это ночь работы.
#: Срок нужен всё равно — забытый процесс не должен висеть вечно.
LONG_TIMEOUT = 12 * 3600

#: Как часто смотрим, не попросили ли остановиться.
WATCH_STEP = 0.2

#: Сколько ждать, пока процесс уйдёт сам, прежде чем убить его.
GRACE = 10


def run_long(command: str, args=(), path: str = "", note=None, stop=None,
             verbose: bool = False, timeout: int | None = None) -> dict:
    """Долгая команда: ответ в конце, а по ходу — её собственный журнал.

    Отличие от `run` не в сроке, а в том, что ответа ждут часами. Всё это
    время экран не должен быть немым, поэтому запускаем процесс и читаем
    его stderr строка за строкой: с `--verbose` переводчик шлёт туда свой
    журнал, и в карточке видно, что он делает прямо сейчас.

    Итог он печатает в stdout одним JSON-ом в самом конце, и забирать
    его из той же трубы нельзя. Пока мы построчно читаем stderr, stdout
    вычерпывать некому: труба наполняется, чужой процесс встаёт на записи,
    мы — на чтении, и оба ждут друг друга насмерть. Поэтому stdout уходит
    в файл, а читается, когда всё кончилось.

    Строки читает отдельный поток, а не этот. Иначе «Остановить» доходило
    бы только вместе со следующей строкой журнала, а между строками у
    перевода бывают минуты.
    """
    _explain(path)
    root = Path(str(path or where())).expanduser()

    line = [python_for(root), "-m", "gemini_translator.cli", str(command),
            *[str(one) for one in args]]
    # Только там, где он есть: `consistency` и `build-epub` его не знают
    # и падают на незнакомом флаге.
    if verbose:
        line.append("--verbose")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
           "PYTHONIOENCODING": "utf-8"}

    log.info("Переводчик (долго): %s", " ".join(line[1:]))
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                errors="replace") as out:
        try:
            work = subprocess.Popen(
                line, cwd=str(root), stdout=out, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", env=env)
        except FileNotFoundError as exc:
            raise TranslatorError(
                f"Не запустился Python переводчика ({python_for(root)}): "
                f"{exc}.") from exc

        listen = threading.Thread(target=_listen, args=(work, note),
                                  daemon=True)
        listen.start()

        stopped = _wait(work, stop, timeout or LONG_TIMEOUT)
        listen.join(timeout=GRACE)
        # Только когда читать некому: закрыть трубу под живым потоком —
        # значит уронить его на середине строки.
        if not listen.is_alive() and work.stderr is not None:
            work.stderr.close()

        out.seek(0)
        body = out.read().strip()

    if stopped:
        # Отмена в проекте одна на всех (`ops/base.py`), и это не ошибка:
        # своим отказом она подсветилась бы красным, а человек нажал сам.
        raise Cancelled("Остановлено.")
    if not body:
        raise TranslatorError(
            f"Переводчик ничего не ответил: код возврата {work.returncode}")
    try:
        found = json.loads(body)
    except ValueError as exc:
        raise TranslatorError(
            f"Ответ переводчика — не JSON: {body[:200]}") from exc
    if not isinstance(found, dict):
        raise TranslatorError(f"Ответ переводчика непонятен: {body[:200]}")
    return found


def _listen(work, note) -> None:
    """Журнал чужого процесса — наружу, строка за строкой."""
    if work.stderr is None:
        return
    for row in work.stderr:
        row = row.strip()
        if row and note:
            try:
                note(row)
            except Exception as exc:  # noqa: BLE001 — показ не роняет работу
                log.warning("Строка журнала переводчика потерялась: %s", exc)


def _wait(work, stop, timeout: int) -> bool:
    """Ждёт конца. Возвращает «остановили ли по просьбе».

    Просьба об остановке идёт процессу вежливо: `terminate` даёт ему
    дописать начатую главу и закрыть файлы. Не ушёл за отведённое —
    убиваем, иначе кнопка «Остановить» врала бы.
    """
    began = time.monotonic()
    asked = False
    while work.poll() is None:
        if stop is not None and stop.is_set() and not asked:
            asked = True
            work.terminate()
            began = time.monotonic()
        if time.monotonic() - began > (GRACE if asked else timeout):
            work.kill()
            break
        time.sleep(WATCH_STEP)
    return asked


def _whole(value) -> int:
    """Целое из чужого ответа. Не число — ноль, а не поломка."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def plan(epub: str, project: str, scope: str = PENDING,
         path: str = "", **knobs) -> dict:
    """Что именно будет переведено — не трогая ни сети, ни ключей.

    Это «до и после» для перевода, и нужно оно ровно затем же, зачем оно
    нужно в форматировании: увидеть работу до того, как за неё заплатят.
    Цена тут — квота ключей, и промахнуться дороже всего: узнать, что
    взялась вся книга вместо десяти глав, посреди прогона поздно.

    План читает епаб и считает главы, задачи и знаки. В сеть он не ходит
    вовсе, поэтому нажимать его можно сколько угодно.
    """
    # Ручки те же, что у перевода: план должен считать квоту той модели,
    # которой потом и переводить, иначе он отвечает не про эту работу.
    return run("plan", _work_args(epub, project, scope, **knobs),
               path=path, timeout=PLAN_TIMEOUT)


def _book_and_project(epub: str, project: str) -> tuple[Path, Path]:
    """Книга и папка проекта — или внятный отказ.

    Проверяем до запуска чужой программы: сказать «файла нет» сразу
    полезнее, чем через полминуты её же словами.
    """
    if not str(epub or "").strip():
        raise TranslatorError("Не выбран .epub, который переводить.")
    book = Path(str(epub).strip()).expanduser()
    if not book.is_file():
        raise TranslatorError(f"Файла нет: {book}")
    if not str(project or "").strip():
        raise TranslatorError(
            "Не указана папка проекта. Переводчик держит в ней главы, "
            "глоссарий и карту перевода — без неё ему некуда складывать.")
    return book, Path(str(project).strip()).expanduser()


def _work_args(epub: str, project: str, scope: str = PENDING, workers: int = 0,
               rpm: int = 0, temperature=None, prompt: str = "",
               limit: int = 0, offset: int = 0, provider: str = "",
               model: str = "", pick=()) -> list:
    """Флаги, общие у плана, перевода, глоссария и сверки.

    Ровно те, что переводчик объявил общими у себя (`_add_common_*`), —
    иначе команда падает на незнакомом флаге.

    Чего не назвали, того и не передаём: у переводчика всё это уже
    настроено в его собственном окне, и пустое значение отсюда затёрло бы
    его выбор своим.
    """
    book, folder = _book_and_project(epub, project)
    if scope not in SCOPES:
        raise TranslatorError(f"Неизвестно, какие главы брать: {scope}")

    args = ["--epub", str(book), "--project", str(folder),
            "--chapters", scope]
    # Сервис и модель — то же правило: не выбрали, значит его сохранённые.
    for flag, value in (("--provider", provider), ("--model", model)):
        if str(value or "").strip():
            args += [flag, str(value).strip()]
    for flag, value in (("--workers", workers), ("--rpm", rpm),
                        ("--limit", limit), ("--offset", offset)):
        if int(value or 0) > 0:
            args += [flag, str(int(value))]
    if temperature is not None and str(temperature).strip() != "":
        args += ["--temperature", str(temperature)]
    if str(prompt or "").strip():
        args += ["--prompt-file", str(Path(str(prompt)).expanduser())]
    # Отбор по именам глав. Флаг повторяемый, и это не мелочь: одна
    # строка «1,5,17» отсюда стала бы одним фильтром, который не совпадёт
    # ни с чем.
    for one in _picks(pick):
        args += ["--chapter", one]
    return args


#: Чем человек разделяет главы, когда пишет их списком. Запятая, точка с
#: запятой и перевод строки — всё, что приходит в голову; гадать, какой
#: из них «правильный», незачем.
PICK_SPLIT = re.compile(r"[,;\r\n]+")


def _picks(pick) -> list:
    """Список отборов главы — из строки или из готового списка.

    Пустые куски выбрасываем: лишняя запятая в конце — обычная опечатка,
    а пустой `--chapter` переводчик понял бы как «совпадает со всем».
    """
    if isinstance(pick, str):
        parts = PICK_SPLIT.split(pick)
    else:
        parts = list(pick or [])
    return [str(one).strip() for one in parts if str(one).strip()]


def verify(epub: str, project: str, scope: str = PENDING) -> None:
    """Годятся ли книга, папка и отбор. Не годятся — кидает и говорит чем.

    Нужна отдельно от самих команд затем, что отказ должен прийти ответом
    на нажатие. Заведи мы задачу сначала — «файла нет» всплыло бы в ней
    через полсекунды, уже с полосой прогресса и кнопкой «Остановить».
    """
    _work_args(epub, project, scope)


def translate(epub: str, project: str, scope: str = PENDING, path: str = "",
              note=None, stop=None, **knobs) -> dict:
    """Перевести главы. Это часы работы, поэтому с журналом и остановкой.

    Ключи, провайдер и модель берутся те, что настроены в самом
    переводчике: `--all-keys` отдаёт ему все его же ключи, а какие именно
    — его дело. Своего склада ключей у нас для этого нет и не будет.
    """
    args = _work_args(epub, project, scope, **knobs) + ["--all-keys"]
    return run_long("translate", args, path=path, note=note, stop=stop,
                    verbose=True)


def glossary(epub: str, project: str, scope: str = WHOLE, path: str = "",
             note=None, stop=None, **knobs) -> dict:
    """Собрать глоссарий именами и названиями до перевода.

    По всей книге, а не по непереведённому: глоссарий затем и нужен,
    чтобы имена совпадали от первой главы до последней.
    """
    args = _work_args(epub, project, scope, **knobs) + ["--all-keys"]
    return run_long("glossary-generate", args, path=path, note=note,
                    stop=stop, verbose=True)


#: Как сверять. Имена канонические, его же: «fast» он у себя разворачивает
#: в `fast_proofread_3_1`, а «deep» — в `deep_consistency`, и писать
#: короткие значило бы полагаться на чужой разбор синонимов.
CHECK_FAST = "fast_proofread_3_1"
CHECK_DEEP = "deep_consistency"
CHECK_WAYS = (CHECK_FAST, CHECK_DEEP, "fast", "deep")

#: Насколько модель уверена в находке. Порядок её, не наш.
SURE_LEVELS = ("high", "medium", "low")

#: Что делать с найденным. Три ступени, а не две галки: `--write` без
#: `--fix` у него не делает ничего — молча, — и такую пару человек
#: собрал бы первым же движением.
LOOK = "look"
OFFER = "offer"
APPLY = "apply"
DEEDS = (LOOK, OFFER, APPLY)


def consistency(epub: str, project: str, scope: str = DONE, path: str = "",
                note=None, stop=None, way: str = "", deed: str = LOOK,
                sure=(), chunk: int = 0, glossary_first: bool = False,
                source: bool = True, suffix: str = "", **knobs) -> dict:
    """Сверить переведённое: расхождения в именах, роде, логике и опечатки.

    По переведённому, а не по всей книге: сверять нечего там, где перевода
    ещё нет. `--verbose` эта команда не знает, и журнала по ходу не будет.

    Что делать с находками — три ступени. Посмотреть; попросить модель
    предложить правки; внести их в файлы. Двумя галками это не описать:
    `--write` без `--fix` у переводчика не делает ровно ничего, и притом
    молча — а собрать такую пару человек может первым же движением.
    """
    verify_check(way, deed, sure)
    args = _work_args(epub, project, scope, **knobs) + ["--all-keys"]
    if way:
        args += ["--consistency-mode", way]
    if int(chunk or 0) > 0:
        args += ["--chunk-size", str(int(chunk))]
    if glossary_first:
        args.append("--glossary-first")
    # Флаг обратный: он убирает оригинал из сверки, а не добавляет.
    if not source:
        args.append("--no-source")
    if str(suffix or "").strip():
        args += ["--suffix", str(suffix).strip()]

    if deed in (OFFER, APPLY):
        args.append("--fix")
        # Только вместе с `--fix`: в одиночку он у него пустой.
        if deed == APPLY:
            args.append("--write")
        for one in _sure(sure):
            args += ["--confidences", one]
    return run_long("consistency", args, path=path, note=note, stop=stop)


def verify_check(way: str = "", deed: str = LOOK, sure=()) -> None:
    """Годятся ли ручки сверки. Не годятся — кидает и говорит чем.

    Отдельно от самой команды затем же, зачем и `verify`: отказ должен
    прийти ответом на нажатие. Проверь мы это уже в задаче — «неизвестный
    способ сверки» всплыло бы в ней через полсекунды, и разбирать его
    пришлось бы, открыв журнал.
    """
    if deed not in DEEDS:
        raise TranslatorError(f"Неизвестно, что делать с находками: {deed}")
    if way and way not in CHECK_WAYS:
        raise TranslatorError(f"Неизвестный способ сверки: {way}")
    _sure(sure)


def _sure(sure) -> list:
    """Насколько уверенные находки чинить. Чужих уровней не выдумываем."""
    if isinstance(sure, str):
        parts = PICK_SPLIT.split(sure)
    else:
        parts = list(sure or [])
    want = [str(one).strip().lower() for one in parts if str(one).strip()]
    unknown = [one for one in want if one not in SURE_LEVELS]
    if unknown:
        raise TranslatorError(
            f"Неизвестная уверенность находки: {', '.join(unknown)}")
    return want


def short_check(said: dict) -> dict:
    """Находки сверки в том виде, в каком их показывают человеку.

    Формат чужой и приходит от модели, поэтому читаем по одному полю и
    ничего не требуем: пустая строка лучше, чем пустая карточка.
    """
    rows = []
    for one in said.get("problems") or []:
        if not isinstance(one, dict):
            continue
        rows.append({
            "chapter": str(one.get("chapter") or one.get("chapter_file") or ""),
            "kind": str(one.get("type") or ""),
            "what": str(one.get("description") or ""),
            "quote": str(one.get("quote") or ""),
            "sure": str(one.get("confidence") or ""),
        })

    fixed = said.get("fix") if isinstance(said.get("fix"), dict) else {}
    written = [str(one) for one in (fixed.get("written_files") or [])]
    changed = [str(one) for one in (fixed.get("changed_files") or [])]
    return {
        "way": str(said.get("mode") or ""),
        "checked": len(said.get("checked_chapters") or []),
        "found": _whole(said.get("problem_count")) or len(rows),
        "rows": rows[:SHOW_ISSUES],
        "more": max(0, len(rows) - SHOW_ISSUES),
        # Предложено и записано — разные числа, и путать их нельзя:
        # «исправлено 40» при пустой записи означало бы, что правки есть,
        # а в файлах их нет.
        "offered": len(changed),
        "written": len(written),
        "missing": [str(one) for one
                    in (said.get("missing_translations") or [])][:SHOW_ISSUES],
    }


def build_epub(epub: str, project: str, output: str = "",
               path: str = "", note=None, stop=None, pick=(), limit: int = 0,
               offset: int = 0) -> dict:
    """Собрать переведённый EPUB.

    Ни модели, ни ключей тут не нужно: команда складывает уже готовое.
    Отсюда и путь дальше — собранная книга ложится туда, откуда её берут
    «Разбить» и «Форматировать».

    Отбор глав своя: у этой команды нет ни `--chapters`, ни сервиса с
    моделью — только имена, пропуск и предел. Собрать половину книги
    бывает нужно, когда вторая ещё переводится.
    """
    book, folder = _book_and_project(epub, project)
    args = ["--epub", str(book), "--project", str(folder)]
    if str(output or "").strip():
        args += ["--output", str(Path(str(output)).expanduser())]
    for flag, value in (("--limit", limit), ("--offset", offset)):
        if int(value or 0) > 0:
            args += [flag, str(int(value))]
    for one in _picks(pick):
        args += ["--chapter", one]
    return run_long("build-epub", args, path=path, note=note, stop=stop)


#: Сколько глав с находками показывать списком и сколько слов в каждой.
#: На книге в пятьсот глав полный список перестаёт быть ответом.
SHOW_ISSUES = 40
SHOW_WORDS = 8


def _scan_args(epub: str, project: str, scope: str, suffix: str = "",
               exceptions: str = "", mixed: bool = True, pick=(),
               limit: int = 0, offset: int = 0) -> list:
    """Флаги поиска остатков. Своих `--provider` и `--model` у него нет.

    Команда в сеть не ходит вовсе — читает уже переведённые файлы, — и
    общих «беговых» флагов ей не объявлено. Передай мы их, она упала бы
    на первом же незнакомом.
    """
    book, folder = _book_and_project(epub, project)
    if scope not in SCOPES:
        raise TranslatorError(f"Неизвестно, какие главы брать: {scope}")

    args = ["--epub", str(book), "--project", str(folder),
            "--chapters", scope]
    for flag, value in (("--limit", limit), ("--offset", offset)):
        if int(value or 0) > 0:
            args += [flag, str(int(value))]
    for one in _picks(pick):
        args += ["--chapter", one]
    if str(suffix or "").strip():
        args += ["--suffix", str(suffix).strip()]
    if str(exceptions or "").strip():
        args += ["--exceptions", str(Path(str(exceptions)).expanduser())]
    # Флаг обратный: он выключает поиск смешанных слов, а не включает.
    if not mixed:
        args.append("--no-mixed-script")
    return args


def scan_untranslated(epub: str, project: str, scope: str = DONE,
                      path: str = "", **knobs) -> dict:
    """Найти непереведённые куски в уже готовых главах.

    Отдельная беда от сверки: там расходятся имена и смысл, а тут прямо в
    переводе остались чужие слова — модель пропустила кусок. Видно это
    только глазами, и до сих пор искать их было нечем.

    В сеть не ходит и ключей не тратит: читает файлы. Поэтому отвечаем
    сразу, а не задачей — ждать тут нечего, кроме чтения самих глав.
    """
    said = run("untranslated-scan", _scan_args(epub, project, scope, **knobs),
               path=path, timeout=PLAN_TIMEOUT)
    if not said.get("ok", True):
        raise TranslatorError(_about(said.get("error") or "переводчик отказал"))
    return said


def short_scan(said: dict) -> dict:
    """Находки в том виде, в каком их показывают человеку.

    Читаем бережно: формат чужой. Слова показываем сами — по ним и видно,
    настоящая это находка или в главе просто стоит имя латиницей.
    """
    rows = []
    for one in said.get("issues") or []:
        if not isinstance(one, dict):
            continue
        words = [str(w) for w in (one.get("untranslated_words") or []) if w]
        mixed = [str(w) for w in (one.get("mixed_script") or []) if w]
        rows.append({
            "chapter": str(one.get("chapter") or one.get("file") or ""),
            "file": str(one.get("file") or ""),
            "count": _whole(one.get("problem_count")) or len(words) + len(mixed),
            "words": words[:SHOW_WORDS],
            "mixed": mixed[:SHOW_WORDS],
        })
    rows.sort(key=lambda row: -row["count"])

    missing = [str(one) for one in (said.get("missing_translations") or [])]
    return {
        "checked": _whole(said.get("checked_chapters")),
        "chapters": _whole(said.get("problem_chapters")) or len(rows),
        "found": _whole(said.get("problem_count")),
        # Главы, у которых перевода нет вовсе: это не «остаток», а
        # пропуск, и лечится он переводом, а не починкой.
        "missing": missing[:SHOW_ISSUES],
        "more_missing": max(0, len(missing) - SHOW_ISSUES),
        "rows": rows[:SHOW_ISSUES],
        "more": max(0, len(rows) - SHOW_ISSUES),
    }


def fix_untranslated(epub: str, project: str, scope: str = DONE,
                     path: str = "", note=None, stop=None, suffix: str = "",
                     exceptions: str = "", fix_prompt: str = "",
                     batch: int = 0, context: int = 0, dry: bool = False,
                     **knobs) -> dict:
    """Починить найденные остатки моделью.

    Это уже работа с ключами, поэтому задачей и с журналом. `--dry-run`
    оставлен ручкой на виду: посмотреть, что модель собирается заменить,
    прежде чем она перепишет готовые главы, — единственная защита от
    порчи того, за что уже заплачено.
    """
    args = _work_args(epub, project, scope, **knobs) + ["--all-keys"]
    if str(suffix or "").strip():
        args += ["--suffix", str(suffix).strip()]
    if str(exceptions or "").strip():
        args += ["--exceptions", str(Path(str(exceptions)).expanduser())]
    if str(fix_prompt or "").strip():
        args += ["--fix-prompt-file", str(Path(str(fix_prompt)).expanduser())]
    for flag, value in (("--batch-size", batch),
                        ("--max-context-chars", context)):
        if int(value or 0) > 0:
            args += [flag, str(int(value))]
    if dry:
        args.append("--dry-run")
    return run_long("untranslated-fix", args, path=path, note=note, stop=stop,
                    verbose=True)


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
