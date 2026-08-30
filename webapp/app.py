"""Локальный веб-интерфейс к качалке.

Сервер слушает только 127.0.0.1: он даёт доступ к файловой системе (выбор
папки), поэтому наружу его выставлять нельзя.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from flask import (Flask, Response, jsonify, request, send_file,
                   send_from_directory)

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats, naming, platform, traffic  # noqa: E402
from core.headings import HeadingsNotFound  # noqa: E402
from core.readers.base import ReadError  # noqa: E402
from core.registry import TYPES as ENTITY_TYPES  # noqa: E402
from core.text import PrepOptions  # noqa: E402
from core.writers.txt import ENCODINGS  # noqa: E402
from net import sources  # noqa: E402
from net.sources import categories as rank_cats  # noqa: E402
from net.sources import mvlrank as mvl_rank_net  # noqa: E402
from net.sources import novelcms  # noqa: E402
from net.sources import rank as rank_net  # noqa: E402
from net.sources import qidianrank as qd_rank_net  # noqa: E402
from net.sources import webnovelrank as wn_rank_net  # noqa: E402
from ops import books as books_op  # noqa: E402
from ops import covers  # noqa: E402
from ops import logbook  # noqa: E402
from ops import update as update_op  # noqa: E402
from ops import rank as rank_op  # noqa: E402
from ops import titles as titles_op  # noqa: E402
from ops import merge as merge_op  # noqa: E402
from ops import names as names_op  # noqa: E402
from ops import convert as convert_op  # noqa: E402
from llm.client import (  # noqa: E402
    BadKey, LlmClient, LlmError, NoKeysLeft, looks_exhausted, mask, short)
from llm import keys as keys_mod  # noqa: E402
from llm.keys import store as keystore  # noqa: E402
from ops import analyze as analyze_op  # noqa: E402
from ops import checkup as checkup_op  # noqa: E402
from ops import compare as compare_op  # noqa: E402
from ops import contradictions as contra_op  # noqa: E402
from ops import glossary as glossary_op  # noqa: E402
from ops import downloads as downloads_op  # noqa: E402
from ops import schedule as schedule_op  # noqa: E402
from ops import everywhere as everywhere_op  # noqa: E402
from ops import junk  # noqa: E402
from ops import library as library_op  # noqa: E402
from ops import diff as diff_op  # noqa: E402
from ops import docs as docs_op  # noqa: E402
from ops import retell as retell_op  # noqa: E402
from ops import headers as headers_op  # noqa: E402
from ops import history as history_op  # noqa: E402
from ops import joblog  # noqa: E402
from ops import session as session_op  # noqa: E402
from ops import queue as queue_op  # noqa: E402
from ops import reader as reader_op  # noqa: E402
from ops import replace as replace_op  # noqa: E402
from ops import sides as sides_op  # noqa: E402
from ops import signature as signature_op  # noqa: E402
from ops import spelling as spelling_op  # noqa: E402
from ops import stats as stats_op  # noqa: E402
from ops import split as split_op  # noqa: E402
from core.models import OpReport  # noqa: E402
from ops import base as base_op  # noqa: E402
from ops import mdbook  # noqa: E402
from ops.base import Cancelled as OpCancelled  # noqa: E402
from ops.base import Progress  # noqa: E402
from mvl import api, checks, cleanup, nativedialog, rename  # noqa: E402
from mvl import textcheck  # noqa: E402
from mvl.cleanup import CleanError  # noqa: E402
from mvl.source import SourceError  # noqa: E402
from mvl.rename import RenameError  # noqa: E402
from mvl import client as client_mod  # noqa: E402
from mvl.client import Blocked, Client, HttpError, NetworkError  # noqa: E402
from mvl import downloader as downloader_mod  # noqa: E402
from mvl.downloader import Cancelled, Downloader, verify  # noqa: E402
from mvl.paths import list_dirs, prepare_output_dir  # noqa: E402
from mvl import proxies as proxies_mod  # noqa: E402
from mvl.proxies import (  # noqa: E402
    PROXY_FILE, ProxyPool, scrub, working_proxies)
from mvl.word import Style  # noqa: E402
from config import settings  # noqa: E402
# Машинка фоновых задач переехала в свой файл: `app.py` дорос до
# пяти с половиной тысяч строк, и резать его начали отсюда.
from webapp.jobs import (  # noqa: E402
    JOB_TTL, JOBS, JOBS_LOCK, KEEP_JOBS, Job, Made, forget_old,
    progress_of as _progress, start_job)
from webapp.tools_routes import tools as tools_routes  # noqa: E402
from webapp.translator_routes import (  # noqa: E402
    translator as translator_routes)

log = logging.getLogger(__name__)

#: Потолок таймаута из ТЗ: прокси иногда подключается очень долго.
MAX_TIMEOUT = 300

#: Событий в книге тысячи — в интерфейс отдаём только начало.
MAX_EVENTS = 500

#: Сколько глав качать при замере многопоточности. Шести хватает, чтобы
#: на трёх потоках каждому досталось по две, а книга при этом не качается.
CHECK_CHAPTERS = 6

STATIC_DIR = Path(__file__).resolve().parent / "static"
app = Flask(__name__, static_folder=str(STATIC_DIR))
# Маршруты «Инструментов» живут отдельным файлом — первая вкладка,
# вынесенная из этого. Дальше по одной за раз.
app.register_blueprint(tools_routes)
app.register_blueprint(translator_routes)

#: Имена, под которыми к нам можно обращаться.
#:
#: «Слушаем только 127.0.0.1» защищает от соседа по сети, но не от
#: браузера. Любая открытая вкладка может отправить сюда запрос — а
#: здесь пишут и удаляют файлы на диске. Хуже того, сайт, чей домен
#: указывает на 127.0.0.1 (подмена DNS), для браузера становится тем же
#: источником, и тогда ему видны и ответы: список папок, журнал, ключи.
HOME_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})

#: Кого пускаем на самом деле. Пустое множество — проверка снята: так
#: бывает, когда человек сознательно выставил сервер наружу.
ALLOWED_NAMES: set[str] = set(HOME_NAMES)


def _bare(value: str) -> str:
    """Имя без порта: `[::1]:8765` → `::1`, `localhost:8765` → `localhost`."""
    name = (value or "").strip().lower()
    if name.startswith("["):
        return name[1:].split("]", 1)[0]
    # У голого IPv6 двоеточий много, и последнее — не порт.
    return name.rsplit(":", 1)[0] if name.count(":") == 1 else name


def open_to(host: str) -> None:
    """Настроить проверку под то, на каком адресе сервер сел.

    Вышли за пределы своей машины — проверять имя нечего: наружу ходят
    по адресу сети, и он у каждого свой. Но молчать об этом нельзя.
    """
    if _bare(host) in HOME_NAMES:
        return
    ALLOWED_NAMES.clear()
    log.warning("Сервер открыт наружу (%s) — проверка имени снята", host)


@app.before_request
def _only_ours():
    """Пускать только свою страницу.

    Два заголовка: `Host` — каким именем нас позвали, `Origin` — чья
    страница зовёт. Первый ловит подмену DNS, второй — запрос со
    стороннего сайта. Ни тот, ни другой браузер подделать странице не
    даёт, поэтому проверки достаточно.
    """
    if not ALLOWED_NAMES:
        return None
    called = request.headers.get("Host", "")
    if _bare(called) not in ALLOWED_NAMES:
        log.warning("Запрос под чужим именем: %s", called)
        return jsonify(error="Запрос пришёл под чужим именем. Программа "
                             "открывается по адресу http://127.0.0.1"), 403
    origin = request.headers.get("Origin") or ""
    if origin and _bare(urlsplit(origin).netloc) not in ALLOWED_NAMES:
        log.warning("Запрос со стороннего сайта: %s", origin)
        return jsonify(error="Запрос пришёл со стороннего сайта и отклонён."), 403
    return None


#: Текущий пул прокси. Список меняется часто, поэтому перезагружается по
#: кнопке — перезапуск программы для этого не нужен.
POOL: ProxyPool | None = None
POOL_LOCK = threading.Lock()


def load_pool(path: str) -> ProxyPool:
    """Перечитывает файл со списком и заменяет текущий пул."""
    global POOL
    pool = ProxyPool.from_file(path)
    with POOL_LOCK:
        POOL = pool
    return pool


def _targets(payload: dict) -> list[str]:
    """Что выбрано: список файлов и/или папок."""
    targets = payload.get("targets")
    if isinstance(targets, str):
        targets = [targets]
    if not targets:
        one = (payload.get("folder_in") or payload.get("target")
               or payload.get("path") or "").strip()
        targets = [one] if one else []
    return [str(t).strip() for t in targets if str(t).strip()]


def _out_format(payload: dict) -> str:
    """Расширение на выходе, всегда с точкой: и «docx», и «.docx» подойдут."""
    value = (payload.get("format") or payload.get("out_format") or ".txt").strip().lower()
    return value if value.startswith(".") else f".{value}"


def _pattern(payload: dict) -> str | None:
    return (payload.get("pattern") or "").strip() or None


def _order(payload: dict) -> str:
    return (payload.get("order") or merge_op.ORDER_NUMBER).strip()


def _encoding(payload: dict) -> str:
    """Кодировка для текстовых форматов. Проверяется до запуска задачи."""
    value = (payload.get("encoding") or "utf-8").strip()
    if value not in ENCODINGS:
        raise ValueError(f"Неизвестная кодировка: {value}")
    return value


def _parts(payload: dict) -> int:
    """На сколько частей делить каждую главу. Меньше двух — не делить."""
    try:
        return max(1, int(payload.get("parts") or 1))
    except (TypeError, ValueError):
        return 1


def _pieces(payload: dict) -> dict:
    """На сколько частей делить каждую главу поимённо.

    Ключ — порядковый номер главы в книге, а не имя файла: книга приходит
    одним файлом, и делить в ней надо отдельные главы, а не файл целиком.
    """
    raw = payload.get("pieces")
    if not isinstance(raw, dict):
        return {}
    found = {}
    for key, value in raw.items():
        try:
            count = max(1, int(value))
        except (TypeError, ValueError):
            continue
        if count > 1:
            found[str(key)] = count
    return found


def _name_format(payload: dict):
    """Свой формат имени файла. Нет его — оставляем прежние имена.

    Ключ не `format`: там уже лежит расширение файла на выходе, и второе
    значение под тем же именем разошлось бы с первым на первой же правке.
    """
    data = payload.get("name_format")
    return naming.NameFormat.from_dict(data) if isinstance(data, dict) else None


#: Сколько имён показывать в вопросе. Список на пятьсот строк в окошке
#: подтверждения — это не «видно», а «нечитаемо».
CLASH_SHOW = 8


def _busy(base: str, folder: str, payload: dict, planned=None):
    """Ответ «в папке уже что-то лежит», если это стоит подтвердить.

    Раньше операции писали в свою подпапку, и спрашивать было не о чем.
    Теперь «Разбить» и «Переименовать» кладут файлы прямо в выбранную —
    и выбрать могут папку с чужим добром. Молча смешать своё с чужим
    хуже, чем спросить один раз.

    `planned` — имена файлов, которые операция собирается записать. С
    ними вопрос перестаёт быть общим: видно, сколько файлов появится
    впервые, какие именно будут перезаписаны, и не окажется ли, что не
    перезапишется ни один. «В папке 300 файлов» на этот вопрос не
    отвечает, а решение принимают по нему.

    Спрашиваем ровно один раз: со второго захода приходит `confirm`.
    Пустая папка и своя подпапка вопросов не вызывают вовсе.
    """
    if folder or payload.get("confirm"):
        return None
    where = Path(base).expanduser()
    if not where.is_dir():
        return None
    found = sum(1 for one in where.iterdir() if one.is_file())
    if not found:
        return None

    names = [Path(str(one)).name for one in (planned or ())]
    if not names:
        return jsonify(
            error=f"В папке уже лежит файлов: {found}. Новые добавятся к "
                  "ним, а совпавшие по имени будут заменены — прежние "
                  "уйдут в корзину. Сохранять сюда?",
            need_confirm=True, busy_files=found), 409

    clash = [name for name in names if (where / name).is_file()]
    shown = ", ".join(clash[:CLASH_SHOW])
    if len(clash) > CLASH_SHOW:
        shown += f" и ещё {len(clash) - CLASH_SHOW}"
    if clash:
        what = (f"Из них будут перезаписаны: {len(clash)} — {shown}. "
                "Прежние уйдут в корзину. ")
    else:
        what = "Ни один из них не будет перезаписан. "
    return jsonify(
        error=(f"В папке уже лежит файлов: {found}. {what}"
               f"Появится новых: {len(names) - len(clash)}. Сохранять сюда?"),
        need_confirm=True, busy_files=found,
        overwrite=clash[:CLASH_SHOW], overwrite_total=len(clash),
        appear=len(names) - len(clash)), 409


def _room(base: str, targets) -> None:
    """Отказ, если на диске заведомо не хватит места.

    Точно предсказать размер выхода нельзя: `.docx` тяжелее исходного
    текста, `.txt` легче, а сколько именно — зависит от книги. Поэтому
    правило нарочно грубое и с одной стороны: свободного меньше, чем весит
    сам исходник, — значит, копия книги точно не поместится. Такое стоит
    сказать до записи, а не показать обрывом на середине.

    Сомнительные случаи пропускаем молча: пугать «возможно, не хватит»
    там, где всё поместится, хуже, чем не пугать вовсе.
    """
    where = Path(base).expanduser()
    while not where.exists() and where != where.parent:
        where = where.parent

    need = 0
    for one in targets or ():
        path = Path(str(one)).expanduser()
        try:
            if path.is_file():
                need += path.stat().st_size
            elif path.is_dir():
                need += sum(f.stat().st_size for f in path.rglob("*")
                            if f.is_file())
        except OSError:
            # Не смогли посмотреть — значит, и запрещать не за что.
            return None

    if not need:
        return None
    try:
        free = shutil.disk_usage(where).free
    except OSError:
        return None
    if free >= need:
        return None
    return jsonify(
        error=f"На диске свободно {_weigh(free)}, а книга весит "
              f"{_weigh(need)}. Запись оборвётся на середине — освободите "
              "место или выберите другой диск."), 507


def _weigh(size: int) -> str:
    """Размер по-человечески: «412 МБ», а не «432013312»."""
    step = float(size)
    for name in ("Б", "КБ", "МБ", "ГБ"):
        if step < 1024 or name == "ГБ":
            return f"{step:.0f} {name}" if name in ("Б", "КБ") \
                else f"{step:.1f} {name}"
        step /= 1024
    return f"{size} Б"


def _prepare(base: str, folder: str, operation: str, only=None) -> Made:
    """Папка для результата, с копией прежнего содержимого в корзину.

    Существующая папка используется как есть — на это опирается докачка,
    — поэтому перезапись возможна. Если в папке уже что-то лежит, старая
    версия сперва уходит в корзину: иначе восстанавливать будет нечего.

    `only` — имена файлов, которые операция собирается записать. С ними в
    корзину уходят они одни, а не вся папка: пишущий прямо в выбранную
    папку не должен утаскивать в корзину всё, что там лежало.

    Куда легла копия, запоминает сама задача. Раньше это лежало в общем
    словаре с ключом-папкой, и две задачи в одну папку затирали запись
    друг друга: «вернуть как было» возвращало чужое. А задача, упавшая
    до итога, оставляла запись навсегда — следующая операция в ту же
    папку наследовала чужую копию.
    """
    output_dir = prepare_output_dir(base, folder)
    saved = (history_op.backup_files((output_dir / name for name in only),
                                     operation)
             if only is not None
             else history_op.backup(output_dir, operation))
    if saved:
        log.info("Прежнее содержимое %s скопировано в %s", output_dir, saved)
    # Что операция собирается записать — «вернуть как было» этим и
    # убирает добавленное. Одной копии мало: в пустую папку операция
    # ничего не перезаписывает, копии не будет, а файлы появятся.
    return Made(dir=output_dir, backup=saved, wrote=list(only or ()))


def _finish(job: Job, report, verb: str) -> None:
    """Итог операции в задачу — одинаково для всех вкладок.

    Здесь же строка журнала: через `_finish` проходит каждая пишущая
    операция, поэтому вести журнал в одном месте достаточно.
    """
    job.report = report.as_dict()
    job.progress.update(
        stage="done", written=report.written, failed=report.failed,
        message=(f"Готово. {verb} {report.written} из {report.total}"
                 + (f", ошибок {report.failed}" if report.failed else "")),
    )

    sources = job.meta.get("targets") or job.meta.get("source") or ""
    if isinstance(sources, list):
        sources = "; ".join(str(s) for s in sources[:3])
    history_op.add(
        operation=job.kind,
        source=str(sources),
        output=job.output_dir,
        files=report.written,
        failed=report.failed,
        backup=job.backup,
        wrote=tuple(job.wrote),
    )


def _novel_from_payload(data: dict) -> api.Novel:
    """Книга из тела запроса — её уже нашли через /api/find."""
    return api.Novel(
        code=int(data["code"]),
        name=data.get("name") or f"novel-{data['code']}",
        slug=data.get("slug", ""),
        total_chapters=int(data.get("total_chapters") or 0),
        author=data.get("author", ""),
    )


# ---------------------------------------------------------------- страницы


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ------------------------------------------------------- отказы модели


#: Клиент модели заводится ДО `try` — иначе его нечем было бы закрыть в
#: `finally`. Значит, «ключей нет» вылетало мимо всех перехватов и
#: доезжало до браузера пятисоткой со стеком вместо строчки «добавьте
#: ключ». Обработчики ловят это один раз на всё приложение: шесть
#: одинаковых `try` вокруг шести вызовов разъехались бы через месяц.
@app.errorhandler(NoKeysLeft)
def _no_keys_left(exc):
    return jsonify(error=str(exc)), 400


@app.errorhandler(BadKey)
def _bad_key(exc):
    return jsonify(error=str(exc)), 401


@app.errorhandler(LlmError)
def _llm_failed(exc):
    return jsonify(error=str(exc)), 502


# ------------------------------------------------------------------- API


@app.get("/api/about")
def api_about():
    """Версия программы.

    Отдаётся с сервера, а не вписана в страницу: страница кэшируется
    браузером, и после обновления в шапке ещё сутки висела бы прошлая
    версия. А вопрос «что у меня стоит» задают как раз тогда, когда
    что-то пошло не так, и неверный ответ на него дороже всего.
    """
    from mvl import __version__

    return jsonify(name="NEUROSTRAZH", version=__version__)


@app.get("/api/sources")
def api_sources():
    """Откуда можно качать. Интерфейс строит список по этому ответу."""
    return jsonify(sources=[s.as_dict() for s in sources.all_sources()])


def _toc_any_proxy(source, novel, client, live, count):
    """Оглавление через любой живой прокси, а не только через первый.

    Список прокси на то и список: один адрес отвалился — это не повод
    сказать «не удалось собрать оглавление». Раньше замер брал `live[0]`
    и падал по таймауту, хотя рядом были рабочие адреса.
    """
    try:
        return source.toc(client, novel, first=1, last=count)
    except HttpError as first_error:
        for proxy in live[1:]:
            spare = Client(proxy_url=proxy.url)
            try:
                found = source.toc(spare, novel, first=1, last=count)
                log.info("Оглавление собралось через запасной прокси %s",
                         proxy.safe_url)
                return found
            except HttpError:
                continue
            finally:
                spare.close()
        raise first_error


def _found(novel) -> dict:
    """Книга для интерфейса: к своим полям добавлены перевод и имя папки.

    Имя папки считается здесь, а не в браузере (3.2 ТЗ): перевод названия
    лежит на сервере, и правило «в пути не бывает иероглифов» должно быть
    одно на всё приложение, а не двумя расходящимися копиями.
    """
    data = novel.to_dict()
    translated = titles_op.known().get(str(novel.code), "")
    data["translated"] = translated
    data["folder"] = naming.folder_name(
        novel.name, code=novel.code, translated=translated)
    return data


#: Беды, от которых помогает другой выход в сеть.
#:
#: HTTP 404 сюда не входит намеренно: страницы нет ни отсюда, ни через
#: посредника, и лишний заход стоил бы только ожидания. А вот таймаут,
#: неразобранное имя хоста и запрет по адресу — ровно то, что чинится
#: сменой выхода.
ROUTE_TROUBLE = (NetworkError, Blocked)


def _find_via_proxy(source, query: str, direct):
    """Вторая попытка найти книгу — через прокси.

    Книга искалась голым клиентом всегда, у любого источника. Для
    китайских сайтов это работало: они из России открываются через раз,
    но открываются. Webnovel не открывается вовсе — в журнале это
    выглядело как «Could not resolve host», то есть как поломка сети, а
    на экране как «книга не найдена». Качать при этом было нечего:
    скачивание начинается с найденной книги.

    Второй заход был поставлен только источникам с пометкой «нужен
    прокси» — из соображения «у остальных прямой запрос работает».
    Соображение оказалось неверным: сайты-сливы из России отвечают не
    всегда, и ixdzs8 встретил пятнадцатисекундным таймаутом. Прокси при
    этом лежал рядом, проверенный, и не использовался, потому что у
    источника не стояло пометки. Теперь заход делается по самой беде, а
    не по пометке: таймаут и запрет чинятся сменой выхода, «страницы
    нет» — нет.

    Почему по-прежнему второй попыткой, а не первой. Прямой запрос у
    большинства источников работает, а прокси до нажатия «проверить»
    никем не проверен: поставить его первым значит разменять работающее
    на непроверенное. И повторов у запасного клиента нет: до него дело
    доходит после трёх неудачных, ждать ещё три минуты незачем.

    Возвращает пару: найденную книгу и приписку к сообщению об ошибке.
    Книга пустая — приписка говорит, что ещё пробовали, чтобы человек не
    гадал, дошло ли дело до посредника.
    """
    if not isinstance(direct, ROUTE_TROUBLE):
        return None, ""
    with POOL_LOCK:
        pool = POOL
    address = _any_proxy(pool)
    if not address:
        return None, (" Посредника не пробовали: живых адресов нет — "
                      "проверьте список на вкладке «Качалка».")
    log.info("«%s» не ответил напрямую (%s) — пробуем через %s",
             source.name, direct, proxies_mod.safe(address))
    spare = Client(proxy_url=address, max_attempts=1)
    try:
        return source.find(spare, query), ""
    except HttpError as exc:
        log.warning("«%s» не открылся и через %s: %s",
                    source.name, proxies_mod.safe(address), exc)
        return None, (f" Через посредника {proxies_mod.safe(address)} — "
                      f"тоже не вышло: {exc}")
    finally:
        spare.close()


@app.post("/api/find")
def api_find():
    payload = request.json or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return jsonify(error="Введите ссылку, слаг или код книги"), 400

    try:
        source = sources.get(payload.get("source") or "")
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 400

    client = Client()
    # Что ещё пробовали, кроме прямого хода. Без этой приписки человек по
    # сообщению не отличит «посредник не помог» от «до посредника дело не
    # дошло», а это разные починки.
    tried = ""
    try:
        try:
            novel = source.find(client, query)
        except HttpError as direct:
            novel, tried = _find_via_proxy(source, query, direct)
            if novel is None:
                raise
        return jsonify(novel=_found(novel), source=source.key)
    except sources.SourceBroken as exc:
        # «Источник изменился» — не «не нашли»: жать «повторить» бесполезно.
        return jsonify(error=str(exc)), 502
    except api.StrippedResponse as exc:
        # Не «не найдено», а испорченный запрос — сообщаем отдельно.
        return jsonify(error=str(exc)), 502
    except (LookupError, ValueError) as exc:
        return jsonify(error=str(exc)), 404
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}{tried}"), 502
    finally:
        client.close()


@app.post("/api/search")
def api_search():
    query = (request.json or {}).get("query", "").strip()
    if not query:
        return jsonify(novels=[])

    client = Client()
    try:
        novels = api.search_novels(client, query, limit=20)
        return jsonify(novels=[n.to_dict() for n in novels])
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}"), 502
    finally:
        client.close()


@app.get("/api/proxies")
def api_proxies_state():
    """Текущее состояние пула, без повторной проверки."""
    with POOL_LOCK:
        pool = POOL
    if pool is None:
        return jsonify(pool=None, default_path=PROXY_FILE)
    return jsonify(pool=pool.to_dict(), default_path=PROXY_FILE)


@app.post("/api/proxies/reload")
def api_proxies_reload():
    """Перечитать файл со списком. Перезапуск программы не нужен."""
    path = (request.json or {}).get("path", "").strip() or PROXY_FILE
    try:
        pool = load_pool(path)
    except (OSError, ValueError) as exc:
        return jsonify(error=scrub(str(exc))), 400
    return jsonify(pool=pool.to_dict(), default_path=PROXY_FILE)


@app.post("/api/proxies/check")
def api_proxies_check():
    """Проверка живости всего списка. Пароли в ответ не попадают."""
    payload = request.json or {}
    path = payload.get("path", "").strip() or PROXY_FILE

    try:
        timeout = int(payload.get("timeout") or proxies_mod.CHECK_TIMEOUT)
    except (TypeError, ValueError):
        return jsonify(error="Таймаут должен быть числом секунд"), 400
    if not 1 <= timeout <= MAX_TIMEOUT:
        return jsonify(error=f"Таймаут проверки: от 1 до {MAX_TIMEOUT} секунд"), 400

    try:
        pool = load_pool(path)
    except (OSError, ValueError) as exc:
        return jsonify(error=scrub(str(exc))), 400

    pool.check_all(timeout=timeout)
    result = pool.to_dict()
    if pool.usable_count == 0:
        # Все адреса отказали одинаково и отказал сам посредник — совет
        # «обновите список» тут вредный: список в порядке, новый даст ровно
        # то же самое. Говорим, что произошло на самом деле.
        alike = proxies_mod.common_refusal(pool.proxies)
        result["warning"] = (
            f"Отказали все адреса, и одинаково: {alike}. Это ответ самого "
            "посредника о себе — до сайта запрос не дошёл, и новый список "
            "ничего не изменит. Разбираться надо с учётной записью у "
            "поставщика прокси."
            if alike else
            "Ни один прокси не пропускает до сайта. Напрямую не идём — "
            "этот путь заблокирован. Обновите список и проверьте снова."
        )
    return jsonify(pool=result, default_path=PROXY_FILE)


@app.post("/api/links")
def api_links():
    """Список ссылок на главы — для запасного плана через WebToEpub."""
    payload = request.json or {}
    novel_data = payload.get("novel") or {}
    if not novel_data.get("code"):
        return jsonify(error="Сначала найдите книгу"), 400

    novel = _novel_from_payload(novel_data)
    client = Client()
    try:
        toc = api.fetch_toc(
            client,
            novel,
            first=max(1, int(payload.get("first") or 1)),
            last=int(payload.get("last") or novel.total_chapters) or novel.total_chapters,
        )
        return jsonify(links=api.chapter_links(novel, toc.chapters), missing=toc.missing)
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}"), 502
    finally:
        client.close()


# ------------------------------------------------- библиотека книг


def _book_out(book) -> dict:
    """Книга наружу: своё плюс подписи меток.

    Подписи считает сервер, а не страница: список меток закрытый и живёт
    в `ops/library`, и держать его вторым экземпляром в разметке значило
    бы однажды разойтись — метка есть, а называть её нечем.
    """
    data = book.as_dict()
    data["mark_names"] = [library_op.MARKS[m] for m in book.marks
                          if m in library_op.MARKS]
    data["auto_names"] = [library_op.AUTO[m] for m in book.auto
                          if m in library_op.AUTO]
    return data


@app.get("/api/library")
def api_library():
    """Вся библиотека и сводка по ней."""
    return jsonify(
        books=[_book_out(b) for b in library_op.all_books()],
        state=library_op.state(),
        marks=[{"key": k, "name": n} for k, n in library_op.MARKS.items()],
        auto=[{"key": k, "name": n} for k, n in library_op.AUTO.items()],
    )


@app.post("/api/library/mark")
def api_library_mark():
    """Поставить или снять метку человека."""
    payload = request.json or {}
    key = (payload.get("key") or "").strip()
    name = (payload.get("mark") or "").strip()
    try:
        book = library_op.mark(key, name, bool(payload.get("on", True)))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if book is None:
        return jsonify(error="Такой книги в библиотеке нет"), 404
    return jsonify(book=_book_out(book))


@app.post("/api/library/note")
def api_library_note():
    """Своя заметка к книге."""
    payload = request.json or {}
    key = (payload.get("key") or "").strip()
    book = library_op.set_note(key, payload.get("note") or "")
    if book is None:
        return jsonify(error="Такой книги в библиотеке нет"), 404
    return jsonify(book=_book_out(book))


#: Сколько книг проверять за один запрос.
#:
#: Каждая проверка — это поход на сайт, а книг в библиотеке бывают сотни.
#: Проверить все разом значило бы держать кнопку нажатой полчаса и
#: получить в конце «сайт устал». Остальные проверятся следующим
#: нажатием: страница знает, какие уже посмотрели.
CHECK_AT_ONCE = 12


@app.post("/api/library/check")
def api_library_check():
    """Спросить у источника, сколько глав в книге сейчас.

    Без этого «есть новые главы» не появилось бы никогда: число глав
    записывается прогоном, а прогон и есть то, ради чего мы про новые
    главы спрашиваем.
    """
    payload = request.json or {}
    keys = [str(k) for k in (payload.get("keys") or []) if str(k)]
    if payload.get("key"):
        keys.append(str(payload["key"]))

    checked, missed = [], []
    for key in keys[:CHECK_AT_ONCE]:
        book = library_op.get(key)
        if book is None or not book.source or not book.address:
            # Книга, которую вставили руками и не качали, спрашивать не у
            # кого: источник у неё не записан.
            missed.append({"key": key, "why": "не записано, чем её качали"})
            continue
        try:
            source = sources.get(book.source)
        except sources.SourceBroken as exc:
            missed.append({"key": key, "why": str(exc)})
            continue

        client = Client()
        try:
            try:
                novel = source.find(client, book.address)
            except HttpError as direct:
                novel, _ = _find_via_proxy(source, book.address, direct)
                if novel is None:
                    raise
            library_op.remember(key, chapters=int(novel.total_chapters or 0))
            checked.append(key)
        except (HttpError, sources.SourceBroken, LookupError, ValueError) as exc:
            missed.append({"key": key, "why": str(exc)})
        finally:
            client.close()

    return jsonify(
        checked=checked, missed=missed,
        left=max(0, len(keys) - CHECK_AT_ONCE),
        books=[_book_out(b) for b in library_op.all_books()],
        state=library_op.state(),
    )


@app.post("/api/library/tags")
def api_library_tags():
    """Свои теги книги.

    Поле для них было с самого начала — его печатал паспорт и рисовала
    карточка, — а записать в него не мог никто: ни кнопки, ни маршрута.
    Теги были видны и недоступны.
    """
    payload = request.json or {}
    key = (payload.get("key") or "").strip()
    book = library_op.set_tags(key, payload.get("tags"))
    if book is None:
        return jsonify(error="Такой книги в библиотеке нет"), 404
    return jsonify(book=_book_out(book))


@app.post("/api/library/forget")
def api_library_forget():
    """Убрать книгу из библиотеки. Файлы на диске не трогаются."""
    payload = request.json or {}
    key = (payload.get("key") or "").strip()
    return jsonify(gone=library_op.forget(key))


@app.post("/api/library/passport")
def api_library_passport():
    """Переписать паспорт в папке книги."""
    payload = request.json or {}
    book = library_op.get((payload.get("key") or "").strip())
    if book is None:
        return jsonify(error="Такой книги в библиотеке нет"), 404
    path = library_op.save_passport(book)
    if not path:
        return jsonify(error=f"Папка книги недоступна: {book.folder or 'её нет'}"), 400
    return jsonify(path=path)


# ===================== Очередь книг (пункт 6) =====================
#
# Очередь качает книги подряд, и у каждой свой источник: одну нашли в
# рейтинге Фанкью и качают оттуда же, вторую — через посредника, третью
# нашли на Цидяне, где скачивания нет вовсе. Общего «источника очереди»
# не бывает — он записан в строке.


def _split_folder(path: str) -> tuple[str, str]:
    """Полный путь книги — на «где» и «как назвать».

    Библиотека помнит папку целиком, а очередь и форма скачивания просят
    их по отдельности: имя папки человек правит, а место — выбирает.
    """
    clean = str(path or "").rstrip("/\\")
    if not clean:
        return "", ""
    at = max(clean.rfind("/"), clean.rfind("\\"))
    return (clean[:at], clean[at + 1:]) if at > 0 else ("", clean)


#: Как называть состояния строки на экране. Здесь, а не в разметке: и
#: сами состояния, и их порядок живут в `ops/downloads`, а второй
#: экземпляр списка однажды разошёлся бы с первым.
QUEUE_STATES = {
    downloads_op.WAITING: "Ждёт",
    downloads_op.RUNNING: "Качается",
    downloads_op.DONE: "Скачана",
    downloads_op.FAILED: "Не вышло",
    downloads_op.NEEDS_LINK: "Нужна ссылка",
}


def _queue_out() -> dict:
    return {"items": [x.as_dict() for x in downloads_op.all_items()],
            "state": downloads_op.state(),
            "states": [{"key": k, "name": v} for k, v in QUEUE_STATES.items()]}


@app.get("/api/downloads")
def api_downloads():
    """Очередь целиком и сводка по ней."""
    return jsonify(**_queue_out())


@app.post("/api/downloads/add")
def api_downloads_add():
    """Поставить книгу в очередь.

    Источник и адрес не обязательны: книгу с Цидяня качать не с чего, и
    строка встанет ждать вставленной ссылки. Отказать в постановке
    значило бы стереть саму память о том, что книгу хотели.
    """
    payload = request.json or {}
    folder = (payload.get("folder") or "").strip()
    base = (payload.get("base") or "").strip()
    if not base or not folder:
        return jsonify(error="Выберите папку и её имя: очередь работает "
                             "сама, спросить будет некого"), 400

    item = downloads_op.add(
        name=(payload.get("name") or "").strip(),
        name_ru=(payload.get("name_ru") or "").strip(),
        cover=(payload.get("cover") or "").strip(),
        source=(payload.get("source") or "").strip(),
        address=(payload.get("address") or "").strip(),
        base=base, folder=folder,
        first=payload.get("first") or 0, last=payload.get("last") or 0,
        origin=payload.get("origin") or {},
    )
    return jsonify(item=item.as_dict(), **_queue_out())


@app.post("/api/downloads/fill")
def api_downloads_fill():
    """Поставить в очередь всё, у чего вышли новые главы.

    Ради этого библиотека и помнит, чем книгу качали: строка очереди
    берёт источник и адрес у каждой книги свои.
    """
    payload = request.json or {}
    keys = {str(k) for k in (payload.get("keys") or []) if str(k)}
    books = [b for b in library_op.all_books()
             if (b.key in keys if keys else b.fresh)]

    added, missed = 0, []
    for book in books:
        base, folder = _split_folder(book.folder)
        if not folder or not book.source or not book.address:
            missed.append({"key": book.key, "title": book.title,
                           "why": "не записано, чем и куда её качали"})
            continue
        downloads_op.add(
            name=book.name, name_ru=book.name_ru, cover=book.cover,
            source=book.source, address=book.address,
            base=base, folder=folder,
            origin={"site": book.found_site, "book_id": book.found_id,
                    "link": book.found_link, "cover": book.cover,
                    "name": book.name, "name_ru": book.name_ru},
        )
        added += 1
    return jsonify(added=added, missed=missed, **_queue_out())


def _source_for(address: str) -> str:
    """Каким источником брать этот адрес — по хосту, а не наугад.

    Человек вставляет в ждущую строку ссылку с сайта-слива; спрашивать
    после этого, чем качать, значило бы переспрашивать то, что уже
    сказано в самом адресе. Хост не из известных — не угадываем: пустой
    ответ честнее подстановки наобум, и источник выберут руками.
    """
    address = str(address or "").strip()
    if not address.lower().startswith(("http://", "https://")):
        return ""
    return "novelcms" if novelcms.rule_for(address) else ""


@app.post("/api/downloads/update")
def api_downloads_update():
    """Поправить строку: вставить ссылку, сменить папку, задать главы."""
    payload = request.json or {}
    fields = {name: payload[name] for name in
              ("source", "address", "base", "folder", "first", "last")
              if name in payload}

    # Вставили ссылку в строку, которой нечем качать: источник виден по
    # адресу. Заданный руками не трогаем — он сильнее догадки.
    item_id = (payload.get("id") or "").strip()
    if fields.get("address") and not fields.get("source"):
        was = downloads_op.get(item_id)
        if was is not None and not was.source:
            guess = _source_for(fields["address"])
            if guess:
                fields["source"] = guess

    item = downloads_op.update(item_id, **fields)
    if item is None:
        return jsonify(error="Такой книги в очереди нет"), 404
    return jsonify(item=item.as_dict(), **_queue_out())


@app.post("/api/downloads/remove")
def api_downloads_remove():
    payload = request.json or {}
    gone = downloads_op.remove((payload.get("id") or "").strip())
    return jsonify(gone=gone, **_queue_out())


@app.post("/api/downloads/move")
def api_downloads_move():
    """Порядок в очереди и есть её смысл: что качать первым."""
    payload = request.json or {}
    try:
        delta = int(payload.get("delta") or 0)
    except (TypeError, ValueError):
        return jsonify(error="Куда двигать — числом"), 400
    downloads_op.move((payload.get("id") or "").strip(), delta)
    return jsonify(**_queue_out())


@app.get("/api/downloads/schedule")
def api_schedule_show():
    """Когда очередь запустится сама."""
    return jsonify(**schedule_op.get().as_dict())


@app.post("/api/downloads/schedule")
def api_schedule_save():
    """Назначить ночной запуск.

    Настройки прогона запоминаются те же, что и у кнопки: ночью спросить
    будет некого, а качать наугад — верный способ получить утром пустую
    папку и потраченный трафик.
    """
    payload = request.json or {}
    try:
        plan = schedule_op.save(
            (payload.get("at") or "").strip(),
            bool(payload.get("on")),
            payload.get("run"),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(**plan.as_dict())


#: Как часто смотреть на часы. Полминуты хватает: окно запуска — полчаса.
SCHEDULE_TICK = 30.0


def _watch_schedule() -> None:
    """Ночной сторож: наступило время — запускает очередь книг.

    Отдельным потоком, а не по таймеру в браузере: страница к ночи
    закрыта, а программа работает.
    """
    while True:
        time.sleep(SCHEDULE_TICK)
        try:
            if not schedule_op.due():
                continue
            # Очередь уже качается — второй запуск ей ни к чему.
            with JOBS_LOCK:
                busy = any(job.running and job.kind == "downloads"
                           for job in JOBS.values())
            if busy:
                continue
            plan = schedule_op.get()
            schedule_op.mark()
            log.info("Расписание: запускаем очередь книг")
            with app.test_request_context():
                _downloads_start(plan.payload)
        except Exception as exc:  # noqa: BLE001 — сторож не должен падать
            log.warning("Расписание не сработало: %s", exc)


@app.post("/api/downloads/clear")
def api_downloads_clear():
    payload = request.json or {}
    gone = downloads_op.clear(only_done=bool(payload.get("only_done")))
    return jsonify(gone=gone, **_queue_out())


def _queue_note(rows, item=None, stopped: bool = False) -> str:
    """Строка над прогрессом: где очередь и на какой книге."""
    done = sum(1 for x in rows if x.state == downloads_op.DONE)
    total = sum(1 for x in rows if x.ready)
    if item is not None and item.state == downloads_op.RUNNING:
        return f"Книга {done + 1} из {total}: {item.title}"

    failed = sum(1 for x in rows if x.state == downloads_op.FAILED)
    if stopped:
        # «Пройдена» после остановки — неправда: остальные книги ждут, и
        # человеку надо знать, что продолжат их тем же нажатием.
        return (f"Очередь остановлена. Скачано книг: {done} из {total}. "
                "Остальные ждут — «Запустить очередь» продолжит с них.")
    said = f"Очередь пройдена. Скачано книг: {done} из {total}."
    return said + (f" Не вышло: {failed}." if failed else "")


@app.post("/api/downloads/start")
def api_downloads_start():
    """Запустить очередь: книги качаются подряд, каждая своим источником.

    Упавшая книга не отменяет остальные — в этом всё отличие от очереди
    операций, где следующий шаг ждёт результата предыдущего.
    """
    return _downloads_start(request.json or {})


def _downloads_start(payload: dict):
    """Тело запуска отдельно от маршрута: тем же путём ходит расписание.

    Иначе ночной запуск повторял бы восемьдесят строк и разошёлся бы с
    кнопкой на второй же правке.
    """
    rows = downloads_op.all_items()
    if not any(x.ready for x in rows):
        return jsonify(error="В очереди нет ни одной книги, которую есть "
                             "чем качать"), 400

    try:
        run = _run_settings(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    with POOL_LOCK:
        pool = POOL
    if pool is not None and pool.checked and pool.usable_count == 0:
        return jsonify(
            error="Ни один прокси не пропускает до сайта. Напрямую не идём — "
            "этот путь заблокирован. Обновите список и проверьте снова."
        ), 400

    job = Job(id=uuid.uuid4().hex[:12], kind="downloads",
              meta={"books": sum(1 for x in rows if x.ready)})
    job.progress = {"stage": "queued", "message": "Запускаем очередь…",
                    "done": 0, "total": 0, "downloaded": 0, "skipped": 0,
                    "failed": 0, "switches": 0,
                    "queue": [x.as_dict() for x in rows],
                    "queue_done": 0,
                    "queue_total": sum(1 for x in rows if x.ready)}
    job.log = joblog.JobLog()

    def one(item):
        """Скачать одну книгу очереди и вернуть текст итога."""
        source = sources.get(item.source)
        client = Client(timeout=run.read_timeout,
                        connect_timeout=run.connect_timeout)
        try:
            try:
                novel = source.find(client, item.address)
            except (HttpError, NetworkError, Blocked) as direct:
                novel, tried = _find_via_proxy(source, item.address, direct)
                if novel is None:
                    raise HttpError(f"{direct}{tried}") from direct

            output_dir = job.keep(_prepare(item.base, item.folder,
                                           "download"))
            # «С какой главы» считается сейчас, а не при постановке в
            # очередь: за ночь вышло бы ещё три главы, а очередь качала
            # бы вчерашний остаток.
            first = item.first or (_reached(output_dir) + 1)
            last = item.last or novel.total_chapters or first
            if last < first:
                return "Новых глав нет — качать нечего"

            job.progress.update(total=last - first + 1, done=0,
                                downloaded=0, skipped=0, failed=0)
            downloader = Downloader(
                client=client, pool=pool,
                on_progress=lambda p: job.progress.update(p.as_dict()),
                on_event=job.log.add,
                cancel_event=job.cancel, pause_event=job.paused,
                threads=run.threads, probe=run.probe, source=source,
                timeout=run.read_timeout,
                connect_timeout=run.connect_timeout,
            )
            report = downloader.run(novel, output_dir,
                                    first=first, last=last).as_dict()
            item.done = int(report.get("downloaded") or 0)
            _remember_book(novel, source.key, output_dir, item.origin, report)
            skipped = int(report.get("skipped") or 0)
            return (f"Скачано глав: {item.done}"
                    + (f", пропущено {skipped}" if skipped else ""))
        finally:
            client.close()

    def changed(rows, item):
        job.progress.update(
            queue=[x.as_dict() for x in rows],
            queue_done=sum(1 for x in rows if x.state == downloads_op.DONE),
            message=_queue_note(rows, item))

    def work(job: Job):
        done = downloads_op.run(one, on_change=changed, cancel=job.cancel)
        stopped = job.cancel.is_set()
        job.progress.update(stage="cancelled" if stopped else "done",
                            queue=[x.as_dict() for x in done],
                            message=_queue_note(done, stopped=stopped))
        job.report = {"books": sum(1 for x in done
                                   if x.state == downloads_op.DONE),
                      "failed": sum(1 for x in done
                                    if x.state == downloads_op.FAILED),
                      "chapters": sum(x.done for x in done)}

    return jsonify(job=start_job(job, work).snapshot())


@app.get("/api/pick/available")
def api_pick_available():
    """Есть ли системный проводник — если нет, интерфейс прячет кнопку."""
    return jsonify(available=nativedialog.available())


@app.post("/api/pick/<kind>")
def api_pick(kind: str):
    """Открывает настоящее окно проводника и возвращает выбранный путь.

    Пустой path — нажали «Отмена», это не ошибка.
    """
    if kind not in ("folder", "file", "files", "any"):
        return jsonify(error=f"Неизвестный выбор: {kind}"), 404

    payload = request.json or {}
    initial = (payload.get("initial") or "").strip()
    title = (payload.get("title") or "").strip()

    try:
        if kind == "folder":
            paths = [nativedialog.ask_directory(title or "Выберите папку", initial)]
        elif kind == "file":
            paths = [nativedialog.ask_open_file(title or "Выберите файл", initial)]
        elif kind == "files":
            paths = nativedialog.ask_open_files(title or "Выберите файлы", initial)
        else:
            # «Выбрать…» — принимает и файлы, и папку.
            paths = nativedialog.ask_any(title or "Выберите файлы или папку", initial)
    except nativedialog.DialogUnavailable as exc:
        # Не ошибка сервера: интерфейс просто остаётся на встроенном обзоре.
        return jsonify(error=str(exc), fallback=True), 503

    paths = [p for p in paths if p]
    return jsonify(paths=paths, path=paths[0] if paths else "", cancelled=not paths)


@app.get("/api/browse")
def api_browse():
    """Обзор папок на этой машине — чтобы выбрать место или файл книги.

    Параметр `files=epub,txt` включает показ файлов с этими расширениями.
    """
    raw = (request.args.get("files") or "").strip()
    suffixes = tuple(f".{s.strip().lstrip('.').lower()}" for s in raw.split(",") if s.strip())
    try:
        return jsonify(list_dirs(request.args.get("path"), suffixes or None))
    except OSError as exc:
        return jsonify(error=str(exc)), 400


@dataclass(frozen=True)
class RunSettings:
    """Как качать: сроки, потоки, проба способа."""

    read_timeout: int
    connect_timeout: int
    threads: int
    probe: bool


def _run_settings(payload: dict) -> RunSettings:
    """Разобрать и проверить настройки прогона.

    Одни и те же для одной книги и для очереди: держи мы их двумя
    списками проверок — однажды в очереди оказалось бы разрешено то, что
    поштучно запрещено.
    """
    payload = payload or {}
    try:
        read_timeout = int(payload.get("timeout") or client_mod.TIMEOUT)
        connect_timeout = int(payload.get("connect_timeout")
                              or client_mod.CONNECT_TIMEOUT)
    except (TypeError, ValueError):
        raise ValueError("Таймаут должен быть числом секунд") from None
    if read_timeout < 5 or connect_timeout < 1:
        raise ValueError("Слишком маленький таймаут")
    if read_timeout > MAX_TIMEOUT or connect_timeout > MAX_TIMEOUT:
        raise ValueError(
            f"Таймаут больше {MAX_TIMEOUT} секунд не имеет смысла")

    try:
        threads = int(payload.get("threads") or 1)
    except (TypeError, ValueError):
        raise ValueError("Потоков должно быть числом") from None
    if not 1 <= threads <= downloader_mod.MAX_THREADS:
        raise ValueError(f"Потоков: от 1 до {downloader_mod.MAX_THREADS}")

    # Ручной режим пропускает пробу: пользователь сам увидит по времени,
    # работает многопоточность или нет, — это надёжнее любой эвристики.
    probe = str(payload.get("mode") or "auto").strip() != "manual"
    return RunSettings(read_timeout, connect_timeout, threads, probe)


def _reached(output_dir) -> int:
    """Докуда книга докачана — по её же `state.json`.

    Не по отчёту прогона: он говорит, сколько глав скачано за этот раз, а
    нужен самый большой номер, который лежит в папке. Книгу качают
    кусками, догоняют, бросают и возвращаются — сложение отчётов дало бы
    неверный хвост, и докачка пошла бы с середины уже готового.
    """
    try:
        state = downloader_mod.State(
            Path(output_dir) / downloader_mod.STATE_FILE)
    except Exception as exc:  # noqa: BLE001 — библиотека не повод ронять прогон
        log.warning("Не прочитать состояние книги в %s: %s", output_dir, exc)
        return 0
    numbers = [int(n) for n in (state.data.get("downloaded") or {})
               if str(n).isdigit()]
    return max(numbers) if numbers else 0


def _remember_book(novel, source_key: str, output_dir, origin: dict,
                   report: dict) -> None:
    """Положить прогон в библиотеку и паспорт — в папку книги.

    Ошибки здесь наружу не выходят намеренно. Книга уже скачана; уронить
    прогон из-за того, что не записалась заметка о нём, было бы обменом
    сделанной работы на удобство.
    """
    try:
        origin = origin or {}
        site = str(origin.get("site") or "")
        code = str(origin.get("book_id") or "")
        key = library_op.key_of(site, code, source_key, novel.slug or str(novel.code))
        book = library_op.remember(
            key,
            name=str(origin.get("name") or novel.name or ""),
            name_ru=str(origin.get("name_ru") or ""),
            author=novel.author or "",
            cover=str(origin.get("cover") or novel.cover or ""),
            found_site=site,
            found_id=code,
            found_link=str(origin.get("link") or ""),
            source=source_key,
            address=novel.slug or str(novel.code),
            folder=str(output_dir),
            chapters=int(novel.total_chapters or 0),
            last=_reached(output_dir),
            skipped=int(report.get("unavailable") or 0),
            last_run=library_op.stamp(),
        )
        library_op.save_passport(book)
    except Exception as exc:  # noqa: BLE001
        log.warning("Книга не записалась в библиотеку: %s", exc)


@app.post("/api/start")
def api_start():
    payload = request.json or {}
    novel_data = payload.get("novel") or {}
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()

    if not novel_data.get("code"):
        return jsonify(error="Сначала найдите книгу"), 400
    if not base:
        return jsonify(error="Выберите папку, где создать каталог книги"), 400
    if not folder:
        return jsonify(error="Введите имя папки"), 400

    novel = _novel_from_payload(novel_data)
    # Откуда книга взялась. У строки рейтинга это сайт и код в нём: книгу
    # находят на одном сайте, а качают с другого, и без этого одна книга
    # легла бы в библиотеку дважды.
    origin = payload.get("origin") or {}

    try:
        made = _prepare(base, folder, "download")
        output_dir = made.dir
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    first = max(1, int(payload.get("first") or 1))
    last = int(payload.get("last") or novel.total_chapters) or novel.total_chapters
    if last < first:
        return jsonify(error="Конечная глава меньше начальной"), 400

    with POOL_LOCK:
        pool = POOL
    if pool is not None and pool.checked and pool.usable_count == 0:
        return jsonify(
            error="Ни один прокси не пропускает до сайта. Напрямую не идём — "
            "этот путь заблокирован. Обновите список и проверьте снова."
        ), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="download",
        meta={"novel": novel.to_dict()},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "queued", "message": "Запускаем…", "done": 0, "total": last - first + 1,
                    "downloaded": 0, "skipped": 0, "failed": 0,
                    "proxy": pool.current().label if pool and pool.usable_count else "",
                    "switches": 0}

    try:
        run = _run_settings(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    read_timeout, connect_timeout = run.read_timeout, run.connect_timeout
    threads, probe = run.threads, run.probe

    try:
        source = sources.get(payload.get("source") or "")
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 400

    job.meta["threads"] = threads

    # Журнал прогона: раздача прокси по потокам и смена адреса с причиной.
    job.log = joblog.JobLog()

    job.keep(made)

    def work(job: Job):
        client = Client(timeout=read_timeout, connect_timeout=connect_timeout)
        downloader = Downloader(
            client=client,
            pool=pool,
            on_progress=lambda p: job.progress.update(p.as_dict()),
            on_event=job.log.add,
            cancel_event=job.cancel,
            pause_event=job.paused,
            threads=threads,
            probe=probe,
            source=source,
            # Те же сроки, что и у клиента оглавления. Раньше их получал
            # только он, а главы качал клиент витрины с умолчаниями — и
            # выставленное на экране число не влияло ни на что.
            timeout=read_timeout,
            connect_timeout=connect_timeout,
        )
        try:
            job.report = downloader.run(novel, output_dir, first=first, last=last).as_dict()
            _remember_book(novel, source.key, output_dir, origin, job.report)
        finally:
            client.close()

    return jsonify(job=start_job(job, work).snapshot())


#: Флажок отмены идущего замера. Замер работает синхронно внутри своего
#: запроса, и остановить его можно только снаружи — вторым запросом.
#: Своей кнопки у него не было, а «Остановить» у прогона до него не
#: доходит: после отмены скачивания замер крутился ещё три минуты,
#: долбился в недоступный адрес и помечал прокси нерабочими — теми
#: самыми, которыми потом качать.
CHECK_LOCK = threading.Lock()
CHECK_CANCEL: threading.Event | None = None


@app.post("/api/threads/cancel")
def api_threads_cancel():
    """Останавливает идущий замер. Не идёт — так и говорим."""
    with CHECK_LOCK:
        cancel = CHECK_CANCEL
    if cancel is None:
        return jsonify(running=False)
    cancel.set()
    return jsonify(running=True)


@app.post("/api/threads/check")
def api_threads_check():
    """Замер многопоточности на живых главах (часть 6 ТЗ).

    Ручной режим чинили вслепую: убедиться, что параллельность работает,
    можно было только прогоном книги целиком. Здесь качаются несколько
    глав, ничего не сохраняется, а в ответе видно, какой поток через
    какой адрес шёл.
    """
    payload = request.json or {}
    novel_data = payload.get("novel") or {}
    if not novel_data.get("code"):
        return jsonify(error="Сначала найдите книгу"), 400

    try:
        source = sources.get(payload.get("source") or "")
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 400

    try:
        threads = max(1, int(payload.get("threads") or 1))
        count = max(2, min(int(payload.get("chapters") or CHECK_CHAPTERS), 20))
        # Замер должен ждать столько же, сколько и прогон: иначе он меряет
        # не то, что потом будет качать.
        read_timeout = int(payload.get("timeout") or client_mod.TIMEOUT)
        connect_timeout = int(payload.get("connect_timeout")
                              or client_mod.CONNECT_TIMEOUT)
    except (TypeError, ValueError):
        return jsonify(error="Потоки, число глав и сроки ожидания должны "
                             "быть числами"), 400

    novel = _novel_from_payload(novel_data)
    with POOL_LOCK:
        pool = POOL

    # Порядок важен: первым должен идти проверенный адрес, а не первый по
    # порядку в файле. Иначе замер утыкается в мёртвый прокси и обрывается,
    # хотя рядом лежит восемь рабочих.
    live = _working_proxies(pool)
    if source.needs_proxy and not live:
        # Источник без прокси не отвечает вовсе, и замер выродился бы в
        # «сайт недоступен» — причина при этом не в потоках (3.3 ТЗ).
        return jsonify(error=f"Источник «{source.name}» работает только через "
                             "прокси, а живых адресов нет. Проверьте список "
                             "на вкладке «Качалка».",
                       step="прокси"), 400

    # Оглавление берём через тот же прокси, что и всё остальное: голым
    # клиентом сайт не отвечает, и замер падал с невнятным 502.
    # Флажок отмены — свой на каждый замер. Кладём его туда, где его
    # найдёт `/api/threads/cancel`: замер идёт синхронно, и достучаться
    # до него можно только вторым запросом.
    cancel = threading.Event()
    global CHECK_CANCEL
    with CHECK_LOCK:
        CHECK_CANCEL = cancel

    client = Client(proxy_url=live[0].url if live else None,
                    timeout=read_timeout, connect_timeout=connect_timeout,
                    cancel=cancel)
    downloader = Downloader(client=client, pool=pool, threads=threads,
                            source=source, timeout=read_timeout,
                            connect_timeout=connect_timeout,
                            cancel_event=cancel)
    try:
        try:
            toc = _toc_any_proxy(source, novel, client, live, count)
        except (sources.SourceBroken, HttpError, LookupError, ValueError) as exc:
            # Разделяем шаги: «не собралось оглавление» и «не пошли потоки»
            # чинятся по-разному, а общий 502 не говорит ни о том, ни о другом.
            return jsonify(error=f"Не удалось собрать оглавление: {exc}",
                           step="оглавление"), 502
        if not toc.chapters:
            return jsonify(error="У книги не нашлось глав — замерять нечего.",
                           step="оглавление"), 400

        found = downloader.measure_threads(novel, toc.chapters, count)
    except Exception as exc:  # noqa: BLE001 — замер не должен ронять сервер
        log.exception("Замер многопоточности не удался")
        return jsonify(error=f"Замер не удался: {type(exc).__name__}: {exc}",
                       step="замер"), 502
    finally:
        client.close()
        # Источник мог завести свой клиент мимо прокси — закрыть его,
        # кроме нас, тут некому: `run` сюда не заходит.
        downloader.close_source()
        # Убираем за собой, но только своё: пока мы доигрывали, мог
        # начаться следующий замер, и гасить его отмену нельзя.
        with CHECK_LOCK:
            if CHECK_CANCEL is cancel:
                CHECK_CANCEL = None

    # Сам замер о своих бедах рассказывает в отчёте, а не кодом ответа:
    # «ни один поток не создался» — это результат, а не отказ сервера.
    return jsonify(**found.as_dict())


# --------------------------------------------- вкладка «Разбить»


@app.get("/api/formats")
def api_formats():
    """Что можно прочитать и во что записать.

    Интерфейс строит списки по этому ответу, а не по своему перечню:
    иначе новый формат приходится добавлять в двух местах.
    """
    return jsonify(readable=list(formats.READABLE), writable=list(formats.WRITABLE))


@app.post("/api/split/scan")
def api_split_scan():
    """Какие главы нашлись и какие имена выйдут — до записи на диск."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файл книги или папку"), 400
    try:
        return jsonify(**split_op.look(
            targets, _pattern(payload), _parts(payload),
            pieces=_pieces(payload), fmt=_name_format(payload),
            seq=bool(payload.get("seq", True))))
    except HeadingsNotFound as exc:
        # Наугад не режем — просим своё регулярное выражение.
        return jsonify(error=str(exc), need_pattern=True, pattern=exc.pattern), 422
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/split/names")
def api_split_names():
    """Имена файлов по уже прочитанным главам — без похода на диск.

    Предпросмотр перестраивается на каждую галочку, а книга в полторы
    тысячи глав читается секунды. Страница присылает обратно то, что
    получила при чтении; собирает имена всё равно сервер.
    """
    payload = request.json or {}
    rows = payload.get("chapters")
    if not isinstance(rows, list):
        return jsonify(error="Сначала прочитайте книгу"), 400
    rows = [row for row in rows if isinstance(row, dict)]
    return jsonify(names=split_op.names(
        rows, _parts(payload), pieces=_pieces(payload),
        fmt=_name_format(payload), seq=bool(payload.get("seq", True))))


@app.post("/api/split/volume")
def api_split_volume():
    """Объём глав внутри книги, а не объём выбранных файлов.

    Общая проверка объёма считает главой файл: она сделана для папки, где
    файл на главу и лежит. Здесь книга ещё не разбита и лежит одним
    файлом, и та же проверка честно отвечала «глав: 1, их слишком мало» —
    отвечая при этом не на тот вопрос. Главы берутся оттуда же, откуда их
    возьмёт и само разбиение.
    """
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файл книги или папку"), 400

    report = OpReport()
    try:
        _, chapters = split_op.gather(targets, _pattern(payload),
                                      _parts(payload), report)
    except HeadingsNotFound as exc:
        return jsonify(error=str(exc), need_pattern=True, pattern=exc.pattern), 422
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(**stats_op.measure(
        stats_op.rows_of(chapters),
        unreadable=[failure.as_text() for failure in report.failures],
    ).as_dict())


@app.post("/api/split/start")
def api_split_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    out_format = _out_format(payload)
    try:
        encoding = _encoding(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not targets:
        return jsonify(error="Выберите файл книги или папку"), 400
    if not base:
        return jsonify(error="Выберите папку, куда сохранить главы"), 400
    if out_format not in formats.WRITABLE:
        return jsonify(error=f"Неизвестный формат: {out_format}"), 400
    if (tight := _room(base, targets)) is not None:
        return tight

    # Читаем до создания папки, чтобы не плодить пустые каталоги. Имена
    # считаем теми же правилами, по которым будем писать: по ним решается,
    # что уйдёт в корзину, и «посчитали одно, записали другое» оставило бы
    # человека без копии как раз того файла, который затёрли.
    try:
        info = split_op.look(targets, _pattern(payload), _parts(payload),
                             pieces=_pieces(payload),
                             fmt=_name_format(payload),
                             seq=bool(payload.get("seq", True)))
    except HeadingsNotFound as exc:
        return jsonify(error=str(exc), need_pattern=True, pattern=exc.pattern), 422
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    # Вопрос о чужой папке задаём после разбора: только теперь известно,
    # какие файлы появятся и какие из них лягут поверх существующих.
    # Читать книгу ради этого не жалко — её всё равно читают следующей
    # строкой, а решение принимают по этому ответу.
    planned = [f"{name}{out_format}" for name in info["names"]]
    if (ask := _busy(base, folder, payload, planned)) is not None:
        return ask

    # Пишем прямо в выбранную папку, если своего имени ей не дали. Тогда
    # и в корзину уходит не вся она, а только те файлы, которые сейчас
    # будут перезаписаны: выбрать могут папку с чужим добром.
    try:
        made = _prepare(
            base, folder, "split",
            only=None if folder
            else [f"{name}{out_format}" for name in info["names"]])
        output_dir = made.dir
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    total = info["total"]
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="split",
        meta={"targets": targets, "format": out_format, "total": total},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "split", "message": f"Пишем {total} глав…",
                    "done": 0, "total": total, "written": 0, "failed": 0}

    job.keep(made)

    def work(job: Job):
        _finish(job, split_op.run(
            targets, Path(job.output_dir),
            out_format=out_format,
            parts=_parts(payload),
            pieces=_pieces(payload),
            fmt=_name_format(payload),
            seq=bool(payload.get("seq", True)),
            pattern=_pattern(payload),
            prep=PrepOptions.from_dict(payload.get("prep")),
            style=Style.from_dict(payload.get("style")),
            titles=bool(payload.get("headings", True)),
            encoding=encoding,
            progress=_progress(job, "Глава"),
        ), "Записано")

    return jsonify(job=start_job(job, work).snapshot())


# --------------------------------------- вкладка «Переименование и деление»


def _chosen_paths(payload: dict) -> set[str] | None:
    """Отмеченные галочками пути. `None` — «галочек не присылали»."""
    chosen = payload.get("chosen")
    if chosen is None:
        return None
    return {str(path) for path in chosen}


def _plan_from_payload(payload: dict):
    """Собирает план по параметрам запроса. Общее для предпросмотра и записи."""
    folder = (payload.get("folder_in") or "").strip()
    if not folder:
        raise RenameError("Выберите папку с главами")

    pattern = (payload.get("pattern") or "").strip() or None
    chapters = rename.scan(folder, pattern)

    start = payload.get("renumber_from")
    renumber_from = None
    if payload.get("renumber") and str(start or "").strip():
        try:
            renumber_from = int(start)
        except (TypeError, ValueError):
            raise RenameError("Начальный номер должен быть числом") from None

    rows = rename.make_plan(
        chapters,
        rename.NameFormat.from_dict(payload.get("format")),
        splits={str(k): int(v) for k, v in (payload.get("splits") or {}).items()},
        renumber_from=renumber_from,
        # Отмеченные галочками пути. Пустой список и отсутствие списка —
        # разные вещи: первое значит «не отмечено ничего», второе — «про
        # галочки не спрашивали, берём все». Раньше они были одним и тем
        # же, и снятие всех галочек означало «переименовать всё».
        chosen=_chosen_paths(payload),
    )
    return chapters, rows


@app.post("/api/rename/scan")
def api_rename_scan():
    """Список глав в папке: имя, номер, объём, пометка сомнительного разбора."""
    payload = request.json or {}
    folder = (payload.get("folder_in") or "").strip()
    if not folder:
        return jsonify(error="Выберите папку с главами"), 400
    try:
        chapters = rename.scan(folder, (payload.get("pattern") or "").strip() or None)
    except RenameError as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(
        chapters=[c.as_dict() for c in chapters],
        suspect=sum(1 for c in chapters if c.suspect),
        total=len(chapters),
    )


@app.post("/api/rename/plan")
def api_rename_plan():
    """Предпросмотр «старое имя → новое имя». На диск ничего не пишется."""
    payload = request.json or {}
    try:
        _, rows = _plan_from_payload(payload)
    except RenameError as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(
        rows=[r.as_dict() for r in rows],
        total=len(rows),
        # Двоеточие в именах файлов Windows не разрешает — предупредим один раз.
        forbidden=rename.has_forbidden(
            rename.NameFormat.from_dict(payload.get("format")).separator
        ),
    )


@app.post("/api/rename/apply")
def api_rename_apply():
    """Пишет результат в новую папку. Оригиналы не трогаются."""
    payload = request.json or {}
    base = (payload.get("base") or "").strip()
    out_name = (payload.get("folder_out") or "").strip()
    fmt = (payload.get("out_format") or "txt").strip().lower().lstrip(".")
    try:
        encoding = _encoding(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not base:
        return jsonify(error="Выберите папку, куда сохранить главы"), 400
    # Список форматов один на все вкладки и берётся из `core/formats.py`.
    if f".{fmt}" not in formats.WRITABLE:
        return jsonify(error=f"Неизвестный формат: {fmt}"), 400
    if (tight := _room(base, [payload.get("folder_in") or ""])) is not None:
        return tight

    try:
        _, rows = _plan_from_payload(payload)
    except RenameError as exc:
        return jsonify(error=str(exc)), 400
    if not rows:
        return jsonify(error="Нечего переименовывать"), 400

    # Правки из предпросмотра: приходят по индексу строки, текст глав через
    # клиент не гоняем — план пересобирается на сервере.
    for index, name in enumerate(payload.get("names") or []):
        if index < len(rows) and str(name).strip():
            rows[index].new_name = str(name).strip()

    # Спрашиваем, зная имена: видно, что именно ляжет поверх чужого.
    if (ask := _busy(base, out_name, payload,
                     rename.planned_names(rows, fmt))) is not None:
        return ask

    # Без имени пишем прямо в выбранную папку, и тогда в корзину уходит
    # не вся она, а только те файлы, которые сейчас затрут: выбрать могут
    # папку с чужим добром.
    try:
        made = _prepare(
            base, out_name, "rename",
            only=None if out_name else rename.planned_names(rows, fmt))
        output_dir = made.dir
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    style = Style.from_dict(payload.get("style"))
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="rename",
        meta={"source": payload.get("folder_in"), "format": fmt, "total": len(rows)},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "rename", "message": f"Пишем {len(rows)} файлов…",
                    "done": 0, "total": len(rows), "written": 0, "failed": 0}

    job.keep(made)

    def work(job: Job):
        report = rename.apply_plan(
            rows, Path(job.output_dir), fmt=fmt, style=style,
            prep=PrepOptions.from_dict(payload.get("prep")),
            headings=bool(payload.get("headings", True)),
            encoding=encoding,
            on_progress=lambda done, total: job.progress.update(
                done=done, total=total, message=f"Файл {done} из {total}"),
            cancel=job.cancel,
        )
        job.report = report.as_dict()
        job.progress.update(
            stage="done", written=report.written, failed=report.failed,
            message=(f"Готово. Записано {report.written} из {report.total}"
                     + (f", ошибок {report.failed}" if report.failed else "")),
        )

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------------------ модель и ключ


def _llm_client(payload: dict | None = None, log_to=None,
                only: str = "") -> LlmClient:
    """Единственный способ завести клиента модели (1.3 ТЗ).

    Хранилище ключей одно на всё приложение, и подставляется оно здесь.
    Заводить клиента в обход этой функции нельзя: про ключи слишком легко
    забыть — так и вышло с аннотацией, которая падала с «ключ не задан»
    при полном списке ключей, пока разбор глав работал.

    Список обязателен и по второй причине: без него клиент искал ключ в
    старом одиночном поле настроек, а список это поле как раз и очищает.
    """
    payload = payload or {}
    with POOL_LOCK:
        pool = POOL

    # В поле ключа может лежать вставка списком — оно для того и
    # многострочное. Взять её целиком за один ключ значит отправить
    # пятьдесят строк в поле `key`: Google отвечает «ключа нет вовсе», а
    # человек видит отказ ключа, которого не вставлял.
    #
    # `only` — тот же случай, только ключ пришёл не из поля, а из
    # обхода списка: проверять надо именно его. Без этого обход на
    # первом же исчерпанном молча уехал бы на следующий, и один ключ
    # проверился бы полсотни раз.
    typed = only or keys_mod.first_key(payload.get("key"))
    return LlmClient(key=typed, pool=pool,
                     # Названный ключ проверяется как есть: он либо ещё
                     # не сохранён, либо его и просили, — ротации нет.
                     keys=None if typed else keystore,
                     on_event=(lambda text: log_to.add(text, "key")) if log_to else None)


@app.get("/api/llm/state")
def api_llm_state():
    """Что настроено. Ключи отдаются только сокращёнными."""
    state = keystore.state()
    return jsonify(configured=state["total"] > 0,
                   provider=settings.llm.provider, **state)


@app.post("/api/llm/keys/add")
def api_llm_keys_add():
    """Добавляет ключ или сразу несколько строк."""
    payload = request.json or {}
    text = str(payload.get("key") or "")
    if not text.strip():
        return jsonify(error="Введите ключ"), 400
    keystore.add(text, name=str(payload.get("name") or "").strip(),
                 limit=int(payload.get("limit") or 0))
    return jsonify(**keystore.state())


@app.post("/api/llm/keys/remove")
def api_llm_keys_remove():
    keystore.remove(str((request.json or {}).get("id") or ""))
    return jsonify(**keystore.state())


@app.post("/api/llm/keys/update")
def api_llm_keys_update():
    """Правка имени, лимита и статуса вручную (7.2 и 7.3)."""
    payload = request.json or {}
    ident = str(payload.get("id") or "")
    if not ident:
        return jsonify(error="Не указан ключ"), 400

    fields = {}
    if "name" in payload:
        fields["name"] = str(payload.get("name") or "")
    if "limit" in payload:
        try:
            fields["limit"] = max(0, int(payload.get("limit") or 0))
        except (TypeError, ValueError):
            return jsonify(error="Лимит должен быть числом"), 400
    if "state" in payload:
        wanted = str(payload.get("state") or "").strip()
        if wanted not in (keys_mod.ACTIVE, keys_mod.EXHAUSTED):
            return jsonify(error=f"Неизвестное состояние: {wanted}"), 400
        fields["state"] = wanted
        # Сняли пометку вручную — счётчик и срок сброса больше не в счёт,
        # иначе ключ тут же снова окажется исчерпанным.
        if wanted == keys_mod.ACTIVE:
            fields.update(used=0, exhausted_at="", reset_at="")

    keystore.update(ident, **fields)
    return jsonify(**keystore.state())


@app.post("/api/llm/estimate")
def api_llm_estimate():
    """«Оценить расход»: объём работы и сколько класть на ключ (7.2)."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        info = analyze_op.scan(targets, _book_root(payload))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    keys = keystore.state()["total"] or 1
    estimate = info.get("estimate") or {}
    from llm.client import Estimate

    full = Estimate(chapters=int(estimate.get("chapters") or 0),
                    characters=int(estimate.get("characters") or 0),
                    tokens=int(estimate.get("tokens") or 0),
                    cached=int(estimate.get("cached") or 0),
                    keys=keys)
    return jsonify(**full.as_dict())


@app.post("/api/llm/check")
def api_llm_check():
    """Проверяет ключ и отдаёт список моделей.

    Зовётся сразу при вводе ключа: недействительный ключ должен быть виден
    здесь, а не при первом разборе главы.
    """
    payload = request.json or {}
    typed = (payload.get("key") or "").strip()
    if not typed and not keystore.state()["total"]:
        return jsonify(error="Ключей в списке нет — добавьте хотя бы один",
                       need_keys=True), 400

    # Проверка — не задача, прогресс-бара у неё нет, но журнал тот же:
    # он и отвечает на вопрос «через какой адрес ушёл запрос».
    trace = joblog.JobLog()
    client = _llm_client(payload, log_to=trace)
    try:
        found = client.check()
        # По какому ключу проверяли — видно и в ответе, и в журнале.
        return jsonify(**found, checked=short(client.key), log=trace.lines())
    except NoKeysLeft as exc:
        trace.add(str(exc), "error")
        return jsonify(error=str(exc), need_keys=True, log=trace.lines()), 400
    except BadKey as exc:
        # Причина словами: «наш сервер отказал» и «Gemini отклонил ключ» —
        # разные беды, и чинить их надо по-разному.
        text = f"Gemini отклонил ключ {short(client.key)}: {exc}"
        trace.add(text, "error")
        return jsonify(error=text, key=short(client.key),
                       log=trace.lines()), 400
    except LlmError as exc:
        trace.add(str(exc), "error")
        return jsonify(error=str(exc), key=short(client.key),
                       log=trace.lines()), 502
    finally:
        client.close()


#: Что стало с ключом на проверке. Список закрытый: интерфейс берёт
#: подписи отсюда, а не держит их вторым экземпляром.
KEY_STATES = {
    "live": "работает",
    "spent": "квота кончилась",
    "bad": "отклонён",
    "mute": "не достучались",
}


@app.post("/api/llm/keys/checkall")
def api_llm_keys_checkall():
    """Обойти все ключи и сказать, какие живы, а какие исчерпаны.

    Раньше проверка брала первый ключ и на нём заканчивалась: вставив
    полсотни, человек получал отказ по одному и не знал, сколько из
    остальных рабочих. Ключи кончаются за день по одному, и вопрос
    «сколько зелёных» — единственный, который тут задают.

    Задачей, а не сразу ответом: полсотни ключей — полсотни запросов.
    """
    keys = keystore.all()
    if not keys:
        return jsonify(error="Ключей в списке нет — добавьте хотя бы один",
                       need_keys=True), 400

    with POOL_LOCK:
        pool = POOL

    job = Job(id=uuid.uuid4().hex[:12], kind="keys",
              meta={"total": len(keys)})
    job.progress = {"stage": "keys", "done": 0, "total": len(keys),
                    "message": f"Ключей проверить: {len(keys)}"}

    def work(job: Job):
        rows, counts = [], dict.fromkeys(KEY_STATES, 0)
        for index, key in enumerate(keys, 1):
            if job.cancel.is_set():
                break
            client = _llm_client(only=key.key)
            state, why = "live", ""
            try:
                client.models()
            except BadKey as exc:
                state, why = "bad", str(exc)
            except LlmError as exc:
                state = "spent" if looks_exhausted(exc) else "mute"
                why = str(exc)
            except Exception as exc:  # noqa: BLE001 — отчёт важнее падения
                state, why = "mute", f"{type(exc).__name__}: {exc}"
            finally:
                client.close()

            # Итог проверки пишем в хранилище: иначе счётчик в шапке
            # остаётся прежним, и «10 зелёных» видно только тут.
            if state == "live":
                keystore.update(keys_mod.key_id(key.key),
                                state=keys_mod.ACTIVE, exhausted_at="",
                                reset_at="")
            elif state == "spent":
                keystore.exhaust(key)

            counts[state] += 1
            rows.append({"id": keys_mod.key_id(key.key),
                         "label": key.name or short(key.key),
                         "state": state, "state_name": KEY_STATES[state],
                         "why": scrub(why)})
            job.progress.update(done=index, message=f"Ключ {index} из {len(keys)}",
                                **counts)

        job.report = {"rows": rows, "checked": len(rows), **counts,
                      "states": [{"key": k, "name": v}
                                 for k, v in KEY_STATES.items()]}
        job.progress.update(
            stage="done",
            message=(f"Живых: {counts['live']} · квота кончилась: "
                     f"{counts['spent']} · отклонено: {counts['bad']}"
                     + (f" · не достучались: {counts['mute']}"
                        if counts["mute"] else "")))

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/llm/save")
def api_llm_save():
    """Сохраняет ключ и модель в config.json — он в .gitignore."""
    payload = request.json or {}
    key = (payload.get("key") or "").strip()
    model = (payload.get("model") or "").strip()

    if key:
        # Ключи живут списком: добавляем, а не заменяем единственный.
        keystore.add(key, name=str(payload.get("name") or "").strip(),
                     limit=int(payload.get("limit") or 0))
    if model:
        settings.llm.model = model
    if "use_proxies" in payload:
        settings.llm.use_proxies = bool(payload.get("use_proxies"))

    try:
        settings.save()
    except OSError as exc:
        return jsonify(error=f"Не удалось сохранить настройки: {exc}"), 500

    return jsonify(saved=True, **keystore.state())


# --------------------------------------------- очистка мусорной шапки


@app.post("/api/headers/scan")
def api_headers_scan():
    """Что похоже на шапку: и между файлами, и внутри каждого из них."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        repeat = max(1, int(payload.get("repeat") or 0)) \
            if payload.get("repeat") else 0
        offset = max(0, int(payload.get("offset") or 0))
    except (TypeError, ValueError):
        return jsonify(error="Порог и номер строки должны быть числами"), 400

    try:
        return jsonify(**headers_op.scan(
            targets, repeat=repeat,
            pattern=str(payload.get("pattern") or "").strip(),
            offset=offset))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/headers/clean")
def api_headers_clean():
    """Пишет очищенные главы в новую папку. Оригиналы не трогаются."""
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    texts = payload.get("texts")
    rules = payload.get("rules")
    texts = texts if isinstance(texts, list) else []
    rules = rules if isinstance(rules, list) else []

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите папку, где создать каталог"), 400
    if not folder:
        return jsonify(error="Введите имя папки"), 400
    # Пустой список — это «ничего не отмечено», а не «убрать всё».
    if not texts and not rules:
        return jsonify(error="Отметьте, что убрать"), 400

    try:
        made = _prepare(base, folder, "headers")
        output_dir = made.dir
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="headers",
        meta={"targets": targets},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "headers", "message": "Чистим шапки…",
                    "done": 0, "total": 0, "written": 0, "failed": 0}

    job.keep(made)

    def work(job: Job):
        _finish(job, headers_op.run(
            targets, Path(job.output_dir), texts,
            prep=PrepOptions.from_dict(payload.get("prep")),
            style=Style.from_dict(payload.get("style")),
            progress=_progress(job, "Файл"),
            rules=rules,
        ), "Очищено")

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------------- вкладка «Объединить»


@app.post("/api/merge/scan")
def api_merge_scan():
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**merge_op.scan(targets, _order(payload)))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/merge/start")
def api_merge_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    name = (payload.get("name") or "").strip()
    out_format = _out_format(payload)
    order = _order(payload)
    try:
        encoding = _encoding(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите, куда сохранить"), 400
    if not name:
        return jsonify(error="Введите имя файла"), 400
    if out_format not in formats.WRITABLE:
        return jsonify(error=f"Неизвестный формат: {out_format}"), 400
    if order not in merge_op.ORDERS:
        return jsonify(error=f"Неизвестный порядок: {order}"), 400

    base_dir = Path(base).expanduser()
    if not base_dir.is_dir():
        return jsonify(error=f"Папка не найдена: {base_dir}"), 400

    try:
        info = merge_op.scan(targets, order)
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    output = base_dir / f"{naming.safe_filename(name)}{out_format}"
    total = info["total"]
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="merge",
        meta={"targets": targets, "format": out_format, "total": total},
        output_dir=str(output),
    )
    job.progress = {"stage": "merge", "message": f"Собираем {total} глав…",
                    "done": 0, "total": total, "written": 0, "failed": 0}

    def work(job: Job):
        _finish(job, merge_op.run(
            targets, Path(job.output_dir),
            order=order,
            headings=bool(payload.get("headings", True)),
            separator=(payload.get("separator") or merge_op.DEFAULT_SEPARATOR),
            custom_separator=(payload.get("custom_separator") or ""),
            encoding=encoding,
            prep=PrepOptions.from_dict(payload.get("prep")),
            style=Style.from_dict(payload.get("style")),
            progress=_progress(job, "Файл"),
        ), "Собрано")

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------- вкладка «Конвертация»


@app.post("/api/convert/scan")
def api_convert_scan():
    """Пересчёт выбранного. Содержимое не читается — только имена."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**convert_op.scan(targets))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/convert/start")
def api_convert_start():
    """Перегон файлов в другой формат: сколько выбрали, столько и выйдет.

    Раньше для этого брали «Объединить» — она читает любой формат и
    пишет любой, но склеивает всё в один файл. Чтобы получить те же
    двести глав в `.docx`, её запускали двести раз.
    """
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    out_format = _out_format(payload)
    try:
        encoding = _encoding(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите, куда сохранить"), 400
    if out_format not in formats.WRITABLE:
        return jsonify(error=f"Неизвестный формат: {out_format}"), 400

    base_dir = Path(base).expanduser()
    if not base_dir.is_dir():
        return jsonify(error=f"Папка не найдена: {base_dir}"), 400

    # Пишем в подпапку, а не рядом с исходниками: перегон в тот же
    # формат иначе затирал бы то, что читает.
    output = base_dir / (naming.safe_filename(folder) or "Конвертация")
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="convert",
        meta={"targets": targets, "format": out_format},
        output_dir=str(output),
    )
    job.progress = {"stage": "convert", "message": "Читаем выбранное…",
                    "done": 0, "total": 0, "written": 0, "failed": 0}

    def work(job: Job):
        _finish(job, convert_op.run(
            targets, Path(job.output_dir),
            out_format=out_format,
            encoding=encoding,
            headings=bool(payload.get("headings", True)),
            prep=PrepOptions.from_dict(payload.get("prep")),
            style=Style.from_dict(payload.get("style")),
            progress=_progress(job, "Файл"),
        ), "Перегнано")

    return jsonify(job=start_job(job, work).snapshot())


# --------------------------------------- вкладка «Форматировать»
#
# Книга уезжает на сайт одним `.md`, где главы размечены строками вида
# `# [Название :|: Порядок :|: Платность :|: Том]`. Отсюда две работы:
# собрать такой файл из папки глав и переписать заголовки в уже готовом,
# когда переводчик оставил их английскими.


def _title_style(payload: dict) -> mdbook.TitleStyle:
    prefix = str(payload.get("prefix") or naming.DEFAULT_PREFIX).strip()
    separator = payload.get("separator")
    if separator is None:
        separator = mdbook.DEFAULT_SEPARATOR
    return mdbook.TitleStyle(prefix=prefix, separator=str(separator))


def _whole(payload: dict, name: str, default: int = 0) -> int:
    try:
        return max(0, int(payload.get(name) or default))
    except (TypeError, ValueError):
        return default


def _md_output(payload: dict) -> Path:
    """Куда писать. Своё имя и своя папка — исходник не трогаем."""
    base = (payload.get("base") or "").strip()
    name = (payload.get("name") or "").strip()
    if not base:
        raise ValueError("Выберите, куда сохранить")
    if not name:
        raise ValueError("Введите имя файла")
    folder = Path(base).expanduser()
    if not folder.is_dir():
        raise ValueError(f"Папка не найдена: {folder}")
    return folder / f"{naming.safe_filename(name)}.md"


#: Что делать с названием главы при переписывании заголовков.
#:
#: Во вкладке «Переименовать» то же самое делается с именами файлов, а
#: книга для загрузчика — один файл, и снаружи её имена не видны вовсе.
NAME_WAYS = {
    "translate": "перевести",
    "keep": "оставить как есть",
    "drop": "убрать, оставить номер",
}


@app.get("/api/format/options")
def api_format_options():
    """Чем размечать заголовки.

    Значения платности задал сайт: `0`, `1` и пробел «как в форме».
    Держать их вторым экземпляром в разметке нельзя — при расхождении
    книга уедет туда с чужой ценой.
    """
    # «Платная» стоит первой, потому что она и стоит в заголовках почти
    # всегда: список выбирает первый пункт по умолчанию, и с «как в
    # форме» во главе книга уезжала с пустой платностью.
    return jsonify(
        payment=[{"key": mdbook.PAYMENT["paid"], "name": "платная"},
                 {"key": mdbook.PAYMENT["free"], "name": "бесплатная"},
                 {"key": mdbook.PAYMENT["form"], "name": "как в форме"}],
        separators=[{"key": s, "name": f"«{s}»"} for s in mdbook.SEPARATORS],
        default_separator=mdbook.DEFAULT_SEPARATOR,
        prefix=naming.DEFAULT_PREFIX,
        names=[{"key": k, "name": v} for k, v in NAME_WAYS.items()])


@app.post("/api/format/files")
def api_format_files():
    """Что соберётся в книгу: сколько глав и как назовутся первые."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400

    report = OpReport()
    try:
        files = base_op.collect_files(targets)
        chapters = sorted(base_op.read_all(files, report),
                          key=naming.sort_key)
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    style = _title_style(payload)
    made = mdbook.from_chapters(
        chapters[:5], style=style,
        paid=str(payload.get("paid") or ""),
        volume=str(payload.get("volume") or ""),
        first=_whole(payload, "first"),
        parts=max(1, _whole(payload, "parts", 1)))
    return jsonify(files=len(files), total=len(chapters),
                   sample=[head.line() for head, _ in made],
                   unreadable=[f.as_text() for f in report.failures],
                   skipped=base_op.skipped_files(targets))


@app.post("/api/format/collect")
def api_format_collect():
    """Собрать главы в один .md с заголовками загрузчика."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        output = _md_output(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    style = _title_style(payload)
    paid = str(payload.get("paid") or "")
    volume = str(payload.get("volume") or "")
    first = _whole(payload, "first")
    parts = max(1, _whole(payload, "parts", 1))

    job = Job(id=uuid.uuid4().hex[:12], kind="format",
              meta={"targets": targets}, output_dir=str(output))
    job.progress = {"stage": "merge", "message": "Читаем главы…",
                    "done": 0, "total": 0, "written": 0, "failed": 0}

    def work(job: Job):
        report = OpReport(output=str(output))
        progress = _progress(job, "Файл")
        files = base_op.collect_files(targets)
        chapters = sorted(base_op.read_all(files, report, progress),
                          key=naming.sort_key)
        if not chapters:
            raise ValueError("Не удалось прочитать ни одной главы.")

        made = mdbook.from_chapters(chapters, style=style, paid=paid,
                                    volume=volume, first=first, parts=parts)
        output.write_text(mdbook.write_book(made), encoding="utf-8")
        report.total = len(chapters)
        report.written = len(made)
        _finish(job, report, "Собрано")

    return jsonify(job=start_job(job, work).snapshot())


def _keys_left() -> dict:
    """Сколько ключей ещё живы и сколько исчерпано.

    Рядом с прогрессом это отвечает на вопрос, который иначе задать
    некому: работа встала, потому что кончились ключи, или потому что
    сломалось что-то ещё.
    """
    try:
        said = keystore.state()
        return {"active": said["active"], "exhausted": said["exhausted"],
                "total": said["total"]}
    except Exception as exc:  # noqa: BLE001 — счётчик не повод ронять перевод
        log.warning("Счётчик ключей не сложился: %s", exc)
        return {"active": 0, "exhausted": 0, "total": 0}


def _read_md(payload: dict) -> tuple[Path, str, list]:
    """Готовая книга: путь, преамбула и главы."""
    targets = _targets(payload)
    if not targets:
        raise ValueError("Выберите файл книги (.md)")
    path = Path(targets[0]).expanduser()
    if not path.is_file():
        raise ValueError(f"Файл не найден: {path}")
    lead, chapters = mdbook.read_book(
        path.read_text(encoding="utf-8", errors="replace"))
    if not chapters:
        raise ValueError("В файле нет заголовков вида «# [Название :|: …]» — "
                         "похоже, это не книга для загрузчика.")
    return path, lead, chapters


@app.post("/api/format/book")
def api_format_book():
    """Что в готовом .md: сколько глав и сколько заголовков не переведено."""
    payload = request.json or {}
    try:
        path, _, chapters = _read_md(payload)
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400

    look = mdbook.inspect(chapters)
    return jsonify(path=str(path), total=look["total"],
                   untranslated=look["untranslated"],
                   look=look,
                   sample=[head.line() for head, _ in chapters[:5]])


def _retitled(way: str, number, name: str, known: dict, style):
    """Каким станет заголовок. Одна на запись и на предпросмотр.

    Держать это двумя копиями нельзя: предпросмотр «до и после» затем и
    нужен, чтобы показать будущий файл, — а разойдись он с записью,
    показывал бы не его.
    """
    if way == "keep":
        ready = name
    elif way == "drop":
        # Убрать название можно только там, где остаётся номер: у пролога
        # его нет, и «Глава» вместо «Пролога» — неправда.
        ready = "" if number is not None else name
    else:
        # Не перевелось — оставляем как было. Пустой заголовок хуже
        # непереведённого: главу в книге станет не найти.
        ready = known.get(name) or name
    title = style.build(number, ready) if number is not None else ready
    return ready, title


def _fresh_head(head, title: str, order):
    """Готовый заголовок главы. Одна на запись и на предпросмотр.

    Без своего порядка хвост строки сохраняется **дословно**: лишний или
    потерянный пробел в платности меняет для сайта смысл, а правим мы
    только название. Порядок попросили — строку приходится собрать
    заново, и тогда поля берутся из разобранных.
    """
    if order:
        return mdbook.make_head(title, str(order), head.paid, head.volume)
    return head.with_title(title)


def _numbered(chapters, renumber: int):
    """Пары «номер, название» с перенумерацией, если её просили.

    Пролог и послесловие номера не имели. Выдать им номер значило бы
    сделать из «Пролога» «Главу 3».
    """
    taken = [mdbook.split_title(head.title) for head, _ in chapters]
    if not renumber:
        return taken

    fresh, at = [], renumber
    for number, name in taken:
        if number is None:
            fresh.append((None, name))
            continue
        fresh.append((at, name))
        at += 1
    return fresh


def _md_pairs(chapters) -> list:
    """Главы книги парами «заголовок, абзацы» — как их видит `ops/junk`."""
    return [(head.title, mdbook.paragraphs_of(lines)) for head, lines in chapters]


@app.post("/api/format/volume")
def api_format_volume():
    """Объём глав готовой книги: какие выделяются на фоне остальных.

    Считает `ops/stats` — тот же, что и в «Разбить» с «Переименовать»:
    объём главы не должен зависеть от того, из какой вкладки смотрят.
    """
    payload = request.json or {}
    try:
        path, _, chapters = _read_md(payload)
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400

    report = stats_op.measure(
        (head.title, head.title, mdbook.paragraphs_of(lines), str(path))
        for head, lines in chapters)
    return jsonify(path=str(path), **report.as_dict())


@app.post("/api/format/junk")
def api_format_junk():
    """Что в главах лишнего: дубли заголовка, название книги, артефакты."""
    payload = request.json or {}
    try:
        path, _, chapters = _read_md(payload)
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400

    found = junk.inspect(_md_pairs(chapters))
    return jsonify(path=str(path), **found.as_dict())


@app.post("/api/format/junk/clean")
def api_format_junk_clean():
    """Убрать отмеченное. Исходник не трогаем — пишем рядом."""
    payload = request.json or {}
    keys = [str(key) for key in (payload.get("keys") or []) if str(key)]
    if not keys:
        return jsonify(error="Отметьте, что убрать"), 400
    try:
        path, lead, chapters = _read_md(payload)
        output = _md_output(payload)
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400

    made, gone = junk.clean(_md_pairs(chapters), keys)
    rebuilt = [(head, mdbook.lines_of(paragraphs))
               for (head, _), (_, paragraphs) in zip(chapters, made)]
    try:
        output.write_text(mdbook.write_book(rebuilt, lead), encoding="utf-8")
    except OSError as exc:
        return jsonify(error=f"Не удалось записать: {exc}"), 400

    return jsonify(output=str(output), removed=gone, chapters=len(rebuilt),
                   source=str(path))


#: Сколько строк «до и после» показывать. Книга бывает на полторы тысячи
#: глав, а решение по такому предпросмотру принимают по первым двум
#: десяткам: дальше повторяется то же самое.
RETITLE_SHOW = 60


@app.post("/api/format/retitle/preview")
def api_format_retitle_preview():
    """Как заголовки будут выглядеть — до того, как за это заплатят.

    К модели не ходим ни разу. Для «оставить» и «убрать» ответ точный: он
    и не требует перевода. Для «перевести» показываем то, что уже есть в
    словаре имён и в кэше, а остальное честно помечаем «переведётся» — и
    сразу видно, за сколько строк придётся платить.

    Считает всё та же пара функций, что и запись: разойдись они, и
    предпросмотр показывал бы не тот файл, который получится.
    """
    payload = request.json or {}
    way = str(payload.get("names") or "translate").strip()
    if way not in NAME_WAYS:
        return jsonify(error=f"Неизвестно, что делать с названиями: {way}"), 400

    try:
        path, _, chapters = _read_md(payload)
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400

    style = _title_style(payload)
    taken = _numbered(chapters, _whole(payload, "renumber"))
    # Что уже известно без единого запроса: словарь имён важнее кэша —
    # написание из него выбрал человек.
    known = {**titles_op.headings(), **titles_op.spellings()}

    # Порядок считаем так же, как считает запись: с числа «порядок с» и
    # дальше подряд. Ноль — строку не пересобираем вовсе.
    first = _whole(payload, "first")
    rows, waiting, order = [], 0, first
    for (head, _), (number, name) in zip(chapters, taken):
        _, title = _retitled(way, number, name, known, style)
        # «Переведётся» — только там, где перевод и нужен, и ещё не готов.
        later = bool(way == "translate" and name and name not in known)
        waiting += later
        rows.append({"before": head.line(),
                     "after": _fresh_head(head, title, order).line(),
                     "later": later})
        if order:
            order += 1

    return jsonify(path=str(path), total=len(rows), waiting=waiting,
                   ready=len(rows) - waiting, way=way,
                   rows=rows[:RETITLE_SHOW],
                   more=max(0, len(rows) - RETITLE_SHOW))


@app.post("/api/format/retitle")
def api_format_retitle():
    """Переписать заголовки готовой книги, не трогая всё остальное.

    Что делать с названием, решает `names`: перевести, оставить как есть
    или убрать вовсе, оставив один номер. Два последних способа к модели
    не ходят вовсе — ни ключей, ни сети им не нужно.
    """
    payload = request.json or {}
    way = str(payload.get("names") or "translate").strip()
    if way not in NAME_WAYS:
        return jsonify(error=f"Неизвестно, что делать с названиями: {way}"), 400

    try:
        path, lead, chapters = _read_md(payload)
        output = _md_output(payload)
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400
    if output == path:
        return jsonify(error="Выберите другое имя: исходник не перезаписываем "
                             "— сверить с ним будет нечего"), 400

    style = _title_style(payload)
    parts = max(1, _whole(payload, "parts", 1))
    first = _whole(payload, "first")
    # Номера глав подряд с этого числа. Ноль — не трогать номера вовсе:
    # они пришли из книги и врать про них не надо.
    renumber = _whole(payload, "renumber")
    force = bool(payload.get("force"))
    model = (payload.get("model") or "").strip()

    doing = ("Переводим заголовки…" if way == "translate"
             else "Переписываем заголовки…")
    job = Job(id=uuid.uuid4().hex[:12], kind="format",
              meta={"total": len(chapters), "names": way},
              output_dir=str(output))
    job.progress = {"stage": "translate", "message": doing,
                    "done": 0, "total": len(chapters), "written": 0,
                    "failed": 0, "keys": _keys_left()}
    # Журнал перевода: какой ключ, через какой адрес, что ответил сервер.
    # На полутора тысячах заголовков это единственное место, где видно,
    # почему работа встала.
    job.log = joblog.JobLog()

    def work(job: Job):
        # Просим только имена: номер главы у нас уже есть, и отдавать его
        # модели значило бы позволить ей его поправить.
        # Номера подряд, если попросили. Считаем до перевода: он про
        # имена, а номер к нему отношения не имеет. Считает их та же
        # `_numbered`, что и предпросмотр, — иначе он показывал бы не то,
        # что запишется.
        taken = _numbered(chapters, renumber)
        wanted = [name for _, name in taken if name]

        done: dict = {}
        if way == "translate":
            client = _llm_client(payload, log_to=job.log)
            try:
                def step(at, all_):
                    # Счётчик ключей обновляем на каждой пачке: на полутора
                    # тысячах заголовков квота кончается посреди работы, и
                    # узнать об этом в конце — поздно.
                    job.progress.update(
                        done=at, total=all_, keys=_keys_left(),
                        message=f"Переводим заголовки… {at} из {all_}")

                done = titles_op.translate_headings(
                    wanted, client, model=model, force=force, on_step=step)
            finally:
                client.close()
        else:
            job.log.add(f"названия: {NAME_WAYS[way]} — к модели не ходим",
                        "key")

        names = done.get("names") or {}
        out, order = [], first
        for (head, body), (number, name) in zip(chapters, taken):
            ready, title = _retitled(way, number, name, names, style)
            fresh = _fresh_head(head, title, order)
            pieces = mdbook.cut_into_parts(fresh, body, parts, style,
                                           number, ready)
            out.extend(pieces)
            if order:
                order += len(pieces)

        output.write_text(mdbook.write_book(out, lead), encoding="utf-8")
        job.report = {"output": str(output), "total": len(out),
                      "written": len(out),
                      "translated": done.get("translated", 0),
                      "cached": done.get("cached", 0),
                      "broken": done.get("broken", 0),
                      "missing": done.get("missing", []),
                      "keys": _keys_left()}
        job.progress.update(stage="done", written=len(out),
                            done=len(chapters), total=len(chapters),
                            keys=_keys_left(),
                            message=f"Готово. Глав: {len(out)}.")
        job.log.add(
            f"готово: глав {len(out)}"
            + (f", переведено {done.get('translated', 0)}, из кэша "
               f"{done.get('cached', 0)}" if way == "translate"
               else f", названия — {NAME_WAYS[way]}"), "done")

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------------ вкладка «Анализ»


def _book_root(payload: dict) -> Path:
    """Папка книги: рядом с ней лежит analysis/."""
    root = (payload.get("root") or "").strip()
    if root:
        return Path(root).expanduser()
    targets = _targets(payload)
    first = Path(targets[0]).expanduser() if targets else Path.cwd()
    return first.parent if first.is_file() else first


@app.post("/api/analyze/scan")
def api_analyze_scan():
    """Сколько глав предстоит разобрать и во что это обойдётся."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**analyze_op.scan(targets, _book_root(payload)))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


def _analysis_result(job: Job, report=None, reason: str = "") -> dict:
    """Блок результата разбора — обязателен в любом исходе (7.5).

    Раньше при остановке на экране оставалось «разобрано 16, ошибок 0» и
    больше ничего: было непонятно ни почему встало, ни что делать дальше.
    """
    keys = keystore.state()
    soon = [k["resets_in"] for k in keys["keys"]
            if k["resets_in"] is not None]
    progress = job.progress or {}
    if report is not None:
        # Обработанное — это разобранное и взятое из кэша. Прогресс сюда не
        # годится: он считает и осечки тоже, и «обработано 3, ошибок 3»
        # выглядело бы враньём.
        done = int(report.parsed) + int(report.cached)
    else:
        done = int(progress.get("done") or 0)

    return {
        "reason": reason,
        "done": done,
        "total": int(progress.get("total") or 0),
        "failed": int(getattr(report, "failed", 0) or progress.get("failed") or 0),
        "tokens": int(job.meta.get("tokens") or 0),
        "keys_total": keys["total"],
        "keys_exhausted": keys["exhausted"],
        "keys_active": keys["active"],
        "resets_in": min(soon) if soon else None,
        "output": job.output_dir,
        # «Продолжить» имеет смысл, только если есть чем продолжать.
        "can_continue": keys["active"] > 0 and
                        int(progress.get("done") or 0) < int(progress.get("total") or 0),
    }


@app.post("/api/analyze/start")
def api_analyze_start():
    """Этап 1: разбор глав моделью."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400

    try:
        keystore.active()
    except NoKeysLeft as exc:
        return jsonify(error=str(exc), need_keys=True), 400

    root = _book_root(payload)
    try:
        info = analyze_op.scan(targets, root)
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    if payload.get("restart"):
        # «Начать заново» стирает только отметку о ходе работы: кэш глав
        # трогать нельзя, за него уже заплачено.
        session_op.forget(root)

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="analyze",
        meta={"targets": targets, "total": info["total"]},
        output_dir=str(root / "analysis"),
    )
    job.log = joblog.JobLog()
    job.progress = {"stage": "analyze", "message": "Разбираем главы…",
                    "done": 0, "total": info["total"], "written": 0, "failed": 0}

    model = (payload.get("model") or "").strip()
    session_op.start(root, targets, info["total"], model=model,
                     keys=[k["id"] for k in keystore.state()["keys"]])

    def work(job: Job):
        with POOL_LOCK:
            pool = POOL
        client = _llm_client(log_to=job.log)
        report = None
        try:
            report = analyze_op.collect(
                targets, client, root=root, model=model,
                force=bool(payload.get("force")),
                progress=_progress(job, "Глава"),
                log_to=job.log,
            )
            # Реестр пересобираем сразу: без него разбор бесполезен.
            registry = analyze_op.rebuild(root)
            session_op.finish(root, done=report.parsed + report.cached)
            job.report = {**report.as_dict(), "registry": registry.stats(),
                          "result": _analysis_result(job, report)}
            job.progress.update(
                stage="done", written=report.parsed + report.cached,
                failed=report.failed,
                message=(f"Готово. Разобрано {report.parsed}, из кэша "
                         f"{report.cached}"
                         + (f", не вышло {report.failed}" if report.failed else "")),
            )
        except NoKeysLeft as exc:
            # Работа встала, но результат сохраняется и продолжается (7.5).
            done = int(job.progress.get("done") or 0)
            session_op.stop(root, "ключи исчерпаны", done=done)
            job.log.add(str(exc), "stop")
            job.report = {"result": _analysis_result(job, report, str(exc))}
            job.progress.update(stage="cancelled", message=str(exc))
        except OpCancelled:
            session_op.stop(root, "остановлено",
                            done=int(job.progress.get("done") or 0))
            job.log.add("остановлено человеком", "stop")
            job.report = {"result": _analysis_result(
                job, report, "Работа остановлена")}
            job.progress.update(stage="cancelled",
                                message="Остановлено. Что успело — сохранено.")
        finally:
            client.close()

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/analyze/session")
def api_analyze_session():
    """Незавершённая сессия по этой папке — чтобы предложить продолжить."""
    payload = request.json or {}
    session = session_op.load(_book_root(payload))
    if session is None or session.finished:
        return jsonify(session=None)
    return jsonify(session=session.as_dict())


@app.post("/api/analyze/sessions")
def api_analyze_sessions():
    """Все незавершённые сессии по выбранным папкам.

    Сессий бывает несколько — по одной на книгу, — поэтому список, а не
    одна: иначе вторая книга была бы не видна вовсе.
    """
    payload = request.json or {}
    found = []
    for target in _targets(payload) or []:
        path = Path(target).expanduser()
        root = path if path.is_dir() else path.parent
        session = session_op.load(root)
        if session is not None and not session.finished:
            found.append(session.as_dict())
    return jsonify(sessions=found)


@app.post("/api/analyze/forget")
def api_analyze_forget():
    """«Начать заново»: стирает ход сессии, кэш глав не трогает."""
    payload = request.json or {}
    return jsonify(forgotten=session_op.forget(_book_root(payload)))


@app.get("/api/job/<job_id>/log")
def api_job_log(job_id: str):
    """Журнал работы под прогресс-баром (7.7)."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None or job.log is None:
        return jsonify(lines=[], total=0)
    try:
        since = int(request.args.get("since") or 0)
    except (TypeError, ValueError):
        since = 0
    return jsonify(**job.log.state(since))


@app.get("/api/job/<job_id>/log.txt")
def api_job_log_file(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None or job.log is None:
        return jsonify(error="Журнала нет"), 404
    return Response(
        job.log.as_text(),
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="analysis-log.txt"'},
    )


@app.post("/api/registry/state")
def api_registry_state():
    """Реестр целиком: сущности, связи, события."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)
    return jsonify(
        root=str(root),
        stats=registry.stats(),
        entities=[e.as_dict() for e in registry.entities.values()],
        links=[l.as_dict() for l in registry.links],
        events=[e.as_dict() for e in registry.events[:MAX_EVENTS]],
        duplicates=[
            {"keep": a, "drop": b,
             "keep_name": registry.entities[a].name,
             "drop_name": registry.entities[b].name}
            for a, b in registry.duplicates()
        ],
        types=list(ENTITY_TYPES),
    )


@app.post("/api/registry/edit")
def api_registry_edit():
    """Правка записи вручную. Отредактированная считается истиной."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)

    entity = registry.entities.get((payload.get("id") or "").strip())
    if entity is None:
        return jsonify(error="Запись не найдена"), 404

    for field_name in ("name", "type", "status"):
        if field_name in payload:
            setattr(entity, field_name, str(payload[field_name]).strip()
                    or getattr(entity, field_name))
    if "aliases" in payload:
        entity.aliases = [str(a).strip() for a in payload["aliases"] if str(a).strip()]
    if "attributes" in payload and isinstance(payload["attributes"], dict):
        entity.attributes = {str(k): v for k, v in payload["attributes"].items()}
    # Правка руками — значит, модель больше эту запись не переписывает.
    entity.confirmed = True

    analyze_op.save_registry(root, registry)
    return jsonify(entity=entity.as_dict())


@app.post("/api/registry/merge")
def api_registry_merge():
    """Слияние двух записей: вторая уходит в варианты имени первой."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)

    keep = (payload.get("keep") or "").strip()
    drop = (payload.get("drop") or "").strip()
    if keep not in registry.entities or drop not in registry.entities:
        return jsonify(error="Запись не найдена"), 404

    merged = registry.merge(keep, drop)
    if merged is not None:
        merged.confirmed = True
    analyze_op.save_registry(root, registry)
    return jsonify(entity=merged.as_dict() if merged else None,
                   stats=registry.stats())


# ============ Глоссарий имён (пункт 11) ============
#
# «Анализ» строит реестр персонажей и сводит написания одного имени в
# варианты. Здесь накопленное превращается в словарь замен для той
# замены по словарю, что уже написана: имя перестаёт плясать между
# главами, а своей замены заводить не пришлось.


@app.post("/api/names/glossary")
def api_names_glossary():
    """Что стоит свести к одному написанию — по реестру книги."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)
    found = names_op.groups(registry)
    return jsonify(groups=[g.as_dict() for g in found],
                   summary=names_op.summary(found),
                   dictionary=names_op.as_dictionary(found),
                   path=str(replace_op.dictionary_path(root)))


@app.post("/api/names/save")
def api_names_save():
    """Дописать выбранное в словарь замен книги.

    Именно дописать: в словаре лежат замены, которые человек вносил
    руками, и глоссарий не вправе их стирать.
    """
    payload = request.json or {}
    root = _book_root(payload)
    chosen = names_op.from_dicts(payload.get("groups"))
    fresh = names_op.as_dictionary(chosen)
    if not fresh:
        return jsonify(error="Нечего записывать: ни одного написания не "
                             "выбрано"), 400

    path = replace_op.dictionary_path(root)
    try:
        was = path.read_text(encoding="utf-8", errors="replace") \
            if path.is_file() else ""
        text, added = names_op.merge_into(was, fresh)
        replace_op.save_dictionary(root, text)
    except OSError as exc:
        return jsonify(error=f"Не удалось записать словарь: {exc}"), 400
    return jsonify(path=str(path), added=added,
                   rules=len(replace_op.parse_dictionary(text)))


@app.post("/api/registry/rebuild")
def api_registry_rebuild():
    """Пересобрать реестр из кэша, сохранив подтверждённое."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.rebuild(root)
    return jsonify(stats=registry.stats())


@app.post("/api/glossary/import")
def api_glossary_import():
    """Глоссарий от переводчика. Записи сразу подтверждённые."""
    payload = request.json or {}
    root = _book_root(payload)
    text = payload.get("text") or ""
    path = (payload.get("path") or "").strip()

    if not text and path:
        try:
            text = Path(path).expanduser().read_text(encoding="utf-8",
                                                     errors="replace")
        except OSError as exc:
            return jsonify(error=f"Не удалось прочитать файл: {exc}"), 400
    if not text.strip():
        return jsonify(error="Глоссарий пуст"), 400

    registry = analyze_op.load_registry(root)
    added = glossary_op.load_into(registry, text)
    analyze_op.save_registry(root, registry)
    return jsonify(added=added, total=len(glossary_op.parse(text)),
                   stats=registry.stats())


@app.post("/api/glossary/export")
def api_glossary_export():
    """Выгрузка глоссария в формате переводчика."""
    payload = request.json or {}
    root = _book_root(payload)
    fmt = (payload.get("format") or "txt").strip().lower().lstrip(".")
    if fmt not in glossary_op.FORMATS:
        return jsonify(error=f"Неизвестный формат: {fmt}"), 400

    registry = analyze_op.load_registry(root)
    text = glossary_op.dump(registry, fmt, payload.get("types"))
    return jsonify(text=text, format=fmt, lines=text.count("\n"))


@app.post("/api/analyze/check")
def api_analyze_check():
    """Этап 3: поиск противоречий по реестру."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)
    if not registry.entities:
        return jsonify(error="Реестр пуст — сначала разберите главы"), 400

    kinds = payload.get("kinds")
    kinds = [k for k in kinds if k in contra_op.KINDS] if isinstance(kinds, list) else None
    report = contra_op.check(registry, root, kinds=kinds)
    return jsonify(**report.as_dict())


@app.get("/api/analyze/kinds")
def api_analyze_kinds():
    return jsonify(kinds=[{"key": k, "name": v} for k, v in contra_op.KINDS.items()],
                   formats=list(glossary_op.FORMATS))


@app.post("/api/analyze/cards")
def api_analyze_cards():
    """Карточки персонажей."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)
    kind = (payload.get("type") or "персонаж").strip()
    return jsonify(cards=glossary_op.cards(registry, kind),
                   text=glossary_op.cards_text(registry, kind))



# ------------------------------------------- рейтинг Фанкью (5.2)

#: Список категорий забирается с сайта один раз и живёт до перезапуска:
#: жанры не меняются, а запрос ради них — лишний.
RANK_CATEGORIES: dict = {}
RANK_LOCK = threading.Lock()


def _rank_client():
    """Клиент для рейтинга — через прокси, даже если их ещё не проверяли.

    `usable` значит «проверен и ответил двухсоткой», а до нажатия кнопки
    проверки это ложь у всех адресов сразу. Рейтинг из-за этого уходил на
    китайский сайт напрямую и молча ничего не привозил: снаружи выглядело
    как «нажал срез — не произошло ничего». Непроверенный прокси мёртвым
    не является; отключённый — является, его и пропускаем.
    """
    with POOL_LOCK:
        pool = POOL
    return Client(proxy_url=_any_proxy(pool))


#: Сколько посредников перебрать, прежде чем стучаться напрямую.
#:
#: Не все подряд: у каждой попытки внутри ещё своя лесенка повторов, и
#: перебор десятка мёртвых адресов превратил бы кнопку «Обновить срез» в
#: минуту ожидания. Трёх хватает, чтобы отличить «этот посредник сайту
#: не нравится» от «сайт не пускает никого».
RANK_TRIES = 3


class RankUnreachable(Exception):
    """Ни один способ дойти до сайта не сработал.

    Несёт с собой отчёт по каждой попытке. «Сайт недоступен» без него не
    отличает мёртвого посредника от запрета по адресу и от съехавшей
    разметки, а лечатся они по-разному.
    """

    def __init__(self, tried: list[str], first: Exception | None = None):
        self.tried = list(tried)
        #: Первая по счёту беда — у неё бывают подробности (`details`),
        #: которые интерфейс показывает отдельно.
        self.first = first
        super().__init__(self.report())

    def report(self) -> str:
        if not self.tried:
            return "Рейтинг не удалось снять: пробовать было нечем."
        if len(self.tried) == 1:
            return self.tried[0]
        rows = "; ".join(f"{number}) {said}"
                         for number, said in enumerate(self.tried, 1))
        return (f"Рейтинг не пришёл ни одним из {len(self.tried)} способов. "
                f"{rows}")


def _rank_ways() -> list:
    """Способы дойти до сайта: посредники по очереди, потом напрямую.

    Способ был один — первый пригодный посредник. Не понравился он
    сайту, и рейтинг не приходил вовсе, хотя рядом лежали ещё адреса и
    открытый прямой ход. Снаружи это выглядело как «нажал — не
    произошло ничего», и разобраться было нечем.

    Первым идёт тот же клиент, что и раньше: его подменяют проверки, и
    ломать подмену незачем. Прямой ход добавляется последним и только
    если посредники вообще есть, — иначе он и так первый.
    """
    with POOL_LOCK:
        pool = POOL
    found = _working_proxies(pool)[:RANK_TRIES]

    ways: list = [(f"посредник {found[0].safe_url}" if found
                   else "напрямую, без посредника", _rank_client)]

    # У запасных способов повтор отключён нарочно. Внутри клиента своя
    # лесенка попыток с паузами, и на мёртвом адресе она съедает
    # полминуты. Перемноженная на три запасных способа и два адреса
    # сайта, она превратила бы кнопку в четыре минуты ожидания — а
    # повтором здесь работает сам перебор: следующий способ и есть
    # следующая попытка.
    for spare in found[1:]:
        ways.append((f"посредник {spare.safe_url}",
                     lambda url=spare.url: Client(proxy_url=url,
                                                  max_attempts=1)))
    if found:
        ways.append(("напрямую, без посредника",
                     lambda: Client(max_attempts=1)))
    return ways


def _rank_run(run):
    """Выполнить `run(client)`, перебирая способы, пока не выйдет.

    Возвращает (что вышло, чем пробовали). Ни один не сработал —
    `RankUnreachable` с отчётом по каждому.
    """
    tried: list[str] = []
    first: Exception | None = None

    ways = _rank_ways()
    for number, (label, make) in enumerate(ways, 1):
        log.info("Рейтинг: попытка %s из %s — %s", number, len(ways), label)
        client = make()
        try:
            found = run(client)
        except (sources.SourceBroken, HttpError) as exc:
            # Три слоя в одной строке, и все три нужны: чем шли, как
            # называется беда (по имени класса видно, отказал ли
            # посредник, закрылся ли сайт или оборвалась сеть) и что
            # именно сказал сайт. Плюс короткий перевод с языка curl:
            # «CONNECT tunnel failed, response 402» человеку ничего не
            # говорит, «посредник отказал: тариф или трафик исчерпан» —
            # говорит всё.
            why = proxies_mod.short_reason(exc)
            log.warning("Рейтинг: попытка %s (%s) не вышла. %s: %s [%s]",
                        number, label, type(exc).__name__, exc, why)
            said = f"{label} — {exc}"
            if why and why not in said:
                said = f"{said} ({why})"
            tried.append(said)
            first = first or exc
            continue
        finally:
            client.close()

        if tried:
            log.info("Рейтинг: получилось через «%s» с %s-й попытки",
                     label, len(tried) + 1)
        return found, tried

    raise RankUnreachable(tried, first)


def _working_proxies(pool) -> list:
    """Тот же отбор, что и в качалке: правило одно на всю программу.

    Держать здесь свою копию было ошибкой: замер и автопроба в
    `mvl/downloader.py` отбирали прокси по-своему и продолжали утыкаться
    в мёртвый адрес после того, как отбор починили тут.
    """
    return working_proxies(pool)


def _any_proxy(pool) -> str | None:
    """Адрес лучшего доступного прокси."""
    found = _working_proxies(pool)
    return found[0].url if found else None


#: Рейтинги, которые программа умеет снимать.
#:
#: Ключ пустой у Фанкью намеренно: с него всё начиналось, его срезы
#: лежат в файлах без приписки сайта, и переименовывать их задним числом
#: значило бы выбросить накопленную историю — а движение по рейтингу
#: считается только по ней.
RANK_SITES = {
    "": {
        "name": "Фанкью",
        "source": "fanqie",
        "boards": {},
        "about": "Сайт отдаёт только суточный срез: рейтингов «за неделю» и "
                 "«за месяц» у него нет — видно не просто популярное, а то, "
                 "что набирает обороты. Названия зашифрованы шрифтом и "
                 "расшифровываются на месте.",
    },
    mvl_rank_net.SITE_KEY: {
        "name": "MVLEMPYR",
        # С какого источника качать книгу, если нажать «скачать» в строке.
        "source": "mvlempyr",
        "boards": mvl_rank_net.BOARDS,
        # Кто расскажет про книгу, когда строку раскроют. У Webnovel
        # такого нет: его рейтинг — готовая страница, и лишнего про
        # книгу там не лежит.
        "book": mvl_rank_net.book,
        "about": "Своей страницы рейтинга у сайта нет: витрина забирает весь "
                 "каталог и сортирует его в браузере. Здесь то же самое — "
                 "берём каталог и сортируем по выбранной доске. Числа "
                 "читающих сайт не показывает, зато есть средний балл и "
                 "число глав.",
    },
    wn_rank_net.SITE_KEY: {
        "name": "Webnovel",
        "source": "webnovel",
        "boards": wn_rank_net.BOARDS,
        # Страницу книги и так разбирает сам источник ради названия и
        # числа глав. Раскрытая строка брала оттуда только то, что уже
        # стояло в самой строке, — описания не показывала вовсе.
        "book": wn_rank_net.book,
        "about": "Рейтинг приходит готовой страницей — ни входа, ни токена. "
                 "Число рядом с книгой на каждой доске своё: голоса, покупки "
                 "или добавления в библиотеку, — поэтому оно подписано. "
                 "Скачать удастся не всякую книгу: часть глав там платная, и "
                 "такие остаются пропусками.",
    },
    qd_rank_net.SITE_KEY: {
        "name": "Цидянь",
        # Качать с Цидяня программа не умеет и не будет: там подписка с
        # 2003 года, открыты первые главы. Рейтинг нужен, чтобы увидеть,
        # что читают, и искать книгу по названию на сайтах-сливах.
        "source": "",
        "boards": qd_rank_net.BOARDS,
        # Второй список: у Цидяня доска и раздел — разные измерения.
        "channels": {key: name for key, (_, name)
                     in qd_rank_net.CHANNELS.items()},
        "book": qd_rank_net.book,
        "about": "Старейшая платная площадка китайского интернета — подписку "
                 "она ввела первой, в 2003 году. Досок много, и живут они в "
                 "двух измерениях: по чему считают (билеты, продажи, "
                 "библиотеки) и в каком разделе. Скачивать отсюда программа "
                 "не умеет: за первыми главами начинается подписка. Рейтинг "
                 "нужен, чтобы найти книгу, а качать её потом с сайта-слива.",
    },
}


def _rank_site(payload) -> str:
    """Какой сайт спрашивают. Незнакомый — это Фанкью, как и раньше."""
    get = payload.get if hasattr(payload, "get") else (lambda k, d=None: d)
    site = str(get("site") or "").strip()
    return site if site in RANK_SITES else ""


def _rank_where(payload) -> tuple[str, str, str]:
    """Аудитория, вид и категория из запроса."""
    get = payload.get if hasattr(payload, "get") else (lambda k, d=None: d)
    audience = str(get("audience") or rank_cats.MALE)
    kind = str(get("kind") or rank_cats.READING)
    category = str(get("category") or "")
    return audience, kind, category


def _rank_board(payload, site: str) -> tuple[str, str]:
    """Доска и категория для этого сайта.

    У Фанкью доска складывается из пола и вида, у остальных она приходит
    прямо. Разводить это по вызовам пришлось бы в каждой ручке, поэтому
    сведено в одно место.
    """
    if not site:
        audience, kind, category = _rank_where(payload)
        return rank_cats.board_key(audience, kind), category

    get = payload.get if hasattr(payload, "get") else (lambda k, d=None: d)
    boards = RANK_SITES[site]["boards"]
    board = str(get("board") or "").strip()
    if board not in boards:
        board = next(iter(boards))

    # Раздел — второе измерение, и есть оно не у всех. У Цидяня доска
    # («по чему считают») и раздел («в каком жанре») перемножаются, и
    # хранить их надо порознь: срез по «городскому» — не то же самое,
    # что срез по всем разделам, и складывать их в одну историю значило
    # бы считать движение по местам между разными списками.
    channels = RANK_SITES[site].get("channels") or {}
    channel = str(get("channel") or "").strip()
    return board, (channel if channel in channels else "")


@app.get("/api/rank/categories")
def api_rank_categories():
    """Разделы и категории. С сайта один раз, дальше из памяти."""
    global RANK_CATEGORIES
    with RANK_LOCK:
        have = dict(RANK_CATEGORIES)

    if not have and str(request.args.get("fetch") or "") == "1":
        client = _rank_client()
        try:
            have = rank_net.fetch_categories(client, rank_cats.MALE)
        except Exception as exc:  # noqa: BLE001 — есть запасной список
            log.warning("Категории рейтинга не забрались: %s", exc)
            have = {}
        finally:
            client.close()
        if have:
            with RANK_LOCK:
                RANK_CATEGORIES = have

    if not have:
        # Пустой выбор хуже известного набора: жанры не меняются годами.
        have = {side: [rank_cats.translate(c) for c in ids]
                for side, ids in rank_cats.FALLBACK.items()}

    return jsonify(
        categories=have,
        audiences=[{"key": k, "name": v} for k, v in rank_cats.AUDIENCES.items()],
        kinds=[{"key": k, "name": v} for k, v in rank_cats.KINDS.items()],
        boards=[{"key": k, "name": v} for k, v in rank_cats.BOARDS.items()],
        # По чему можно упорядочить срез и какое поле строки за это
        # отвечает. Список приходит отсюда, а не вписан в страницу:
        # порядок, которого нет в `ops/rank`, показывать нечем.
        orders=[{"key": k, "name": v, "field": rank_op.ORDER_FIELDS.get(k, "")}
                for k, v in rank_op.ORDERS.items()],
        # Какие рейтинги вообще есть и какие доски у каждого. Список
        # приходит с сервера, а не вписан в страницу: добавить третий
        # сайт иначе значило бы править ещё и разметку.
        sites=[{"key": key, "name": site["name"], "source": site["source"],
                "about": site["about"],
                # Есть ли у сайта что рассказать о книге сверх строки.
                # Без этого признака страница не знает, стоит ли вообще
                # раскрывать строку, и открывает пустую карточку.
                "details": key == "" or site.get("book") is not None,
                "boards": [{"key": k, "name": v}
                           for k, v in site["boards"].items()],
                # Второе измерение, если оно у сайта есть: у Цидяня
                # доска перемножается на раздел. Пустой список значит
                # «делить не на что» — тогда выбор и не показывается.
                "channels": [{"key": k, "name": v} for k, v
                             in (site.get("channels") or {}).items()]}
               for key, site in RANK_SITES.items()],
    )


@app.get("/api/rank/everywhere")
def api_rank_everywhere():
    """Общая доска: книга, которую узнали сразу в нескольких рейтингах."""
    names = {key: site["name"] for key, site in RANK_SITES.items()}

    # Подписи досок и разделов складываются здесь: у Фанкью доска
    # собирается из пола и вида, у остальных приходит с сайта, а вторым
    # измерением у Цидяня идёт раздел, у Фанкью — жанр. Общей доске эти
    # различия знать незачем — ей нужны готовые названия.
    boards = {key: dict(site["boards"]) for key, site in RANK_SITES.items()}
    boards[""] = dict(rank_cats.BOARDS)

    cats = dict(rank_cats.NAMES)
    for site in RANK_SITES.values():
        cats.update(site.get("channels") or {})

    # Переводы названий — то, чем китайская строка сходится с
    # английской. Они уже накоплены кнопкой «Перевести всё», и брать их
    # больше неоткуда.
    return jsonify(**everywhere_op.board(
        names=names, boards=boards, categories=cats,
        translated=titles_op.known()).as_dict())


@app.get("/api/rank/state")
def api_rank_state():
    """Что уже накоплено по этому разделу и категории."""
    site = _rank_site(request.args)
    audience, kind, _ = _rank_where(request.args)
    board, category = _rank_board(request.args, site)
    try:
        moved = rank_op.movement(board, category=category, site=site)
    except rank_op.RankError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(titles=titles_op.known(), audience=audience, kind=kind,
                   **moved)


@app.post("/api/rank/refresh")
def api_rank_refresh():
    """Запрашивает рейтинг и дописывает сегодняшний день.

    Только по кнопке: по расписанию сайт не опрашивается.
    """
    payload = request.json or {}
    site = _rank_site(payload)
    audience, kind, _ = _rank_where(payload)
    board, category = _rank_board(payload, site)

    def snap(client):
        if site == mvl_rank_net.SITE_KEY:
            # У MVLEMPYR нет ни шрифта, ни аудитории, ни жанровых досок:
            # весь рейтинг — это каталог, отсортированный по одному из
            # трёх полей. Поэтому и вызов у него свой.
            found = mvl_rank_net.fetch(client, board=board)
            found.setdefault("font", {})
        elif site == wn_rank_net.SITE_KEY:
            # Webnovel отдаёт рейтинг готовой страницей: ни токена, ни
            # входа, ни шрифта — разбирается вёрстка.
            found = wn_rank_net.fetch(client, board=board)
            found.setdefault("font", {})
        elif site == qd_rank_net.SITE_KEY:
            # У Цидяня к доске прибавляется раздел: доска говорит, по
            # чему считают, раздел — среди каких книг.
            found = qd_rank_net.fetch(client, board=board, channel=category)
            found.setdefault("font", {})
        else:
            found = rank_net.fetch(client, audience=audience, kind=kind,
                                   category=category)
        return found

    try:
        # Способов дойти до сайта несколько, и пробуются они по очереди:
        # один посредник сайту не понравился — берётся следующий, а за
        # ними прямой ход.
        found, tried = _rank_run(snap)
    except RankUnreachable as exc:
        # Подробности вместо общих слов: по ним видно, сел ли сайт,
        # запретил ли он адрес посредника или сменилась разметка.
        details = dict(getattr(exc.first, "details", None) or {})
        details["tried"] = exc.tried
        return jsonify(error=exc.report(), details=details), 502
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    have = rank_op.days(board, category, site)
    previous = rank_op.load(have[0], board, category, site) if have else None
    same = previous is not None and previous.version and \
        previous.version == found["version"]

    rank_op.save(found["rows"], board, category=found["category"],
                 version=found["version"], stats_date=found["stats_date"],
                 site=site)
    return jsonify(saved=len(found["rows"]), decoded=found["decoded"],
                   same_version=same, audience=audience, kind=kind,
                   # Чем пришлось пробовать до того, как получилось.
                   # Пусто — вышло сразу; непусто — стоит знать, что
                   # первый посредник сайту не подошёл.
                   tried=tried,
                   # 2.5: подробности разбора шрифта. Без них «названия
                   # расшифровать не удалось» не говорит, что чинить.
                   font=found.get("font") or {},
                   **rank_op.movement(board, category=found["category"],
                                      site=site))


@app.get("/api/rank/cover/<book_id>")
def api_rank_cover(book_id: str):
    """Отдаёт обложку из своего кэша (2.3 ТЗ).

    Адрес на сайте подписан и с сроком действия: в сохранённом срезе он
    протухает, а срезы хранятся месяцами. Поэтому картинка берётся из
    `data/covers`, а если её там нет — скачивается по адресу из среза и
    остаётся в кэше навсегда.
    """
    if not covers.safe_id(book_id):
        return jsonify(error="Плохой код книги"), 400

    if not covers.have(book_id):
        source = (request.args.get("url") or "").strip()
        if not source:
            return jsonify(error="Обложки нет в кэше"), 404
        client = _rank_client()
        try:
            if not covers.fetch(client, book_id, source):
                return jsonify(error="Обложку скачать не удалось"), 502
        finally:
            client.close()

    path = covers.path_for(book_id)
    # Тип определяем по самим байтам: расширение у нас одно на все, а
    # объявленный не тот формат браузер просто не покажет.
    # Кэш навсегда: имя файла — код книги, а картинка у книги одна.
    return send_file(path, mimetype=covers.mimetype_of(path),
                     max_age=31536000)


def _rank_book_elsewhere(site: str, book_id: str):
    """Подробности книги с рейтинга, который не Фанкью.

    Читателя подробностей у каждого сайта свой, и есть он не у всех:
    Webnovel отдаёт рейтинг готовой страницей, и лишнего про книгу там
    нет. Такой сайт честно отказывается — это лучше, чем показать
    карточку, повторяющую строку слово в слово.
    """
    reader = RANK_SITES[site].get("book")
    if reader is None:
        return jsonify(
            error=f"{RANK_SITES[site]['name']} не отдаёт подробностей книги "
                  "отдельно от рейтинга — показывать в карточке нечего."), 400

    client = _rank_client()
    try:
        found = reader(client, book_id, slug=request.args.get("slug", ""))
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 502
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}"), 502
    finally:
        client.close()

    # Карточку кладём в кэш, как это делает фанкьюшная ветка. Раньше
    # здесь она никуда не сохранялась, и «Перевести всё» не видело
    # описаний этих сайтов никогда — сколько строк ни раскрывай.
    saved = books_op.save(book_id, found)
    return jsonify(**saved, abstract_ru=titles_op.abstract_of(book_id))


def _fetch_card(client, site: str, book_id: str, slug: str = "") -> dict:
    """Карточка книги с сайта, сохранённая в кэш. Без Flask вокруг.

    Одна и та же работа нужна и раскрытой строке, и прогону за всеми
    описаниями сразу. Второй её экземпляр разошёлся бы с первым на
    первой же правке.
    """
    if site:
        reader = RANK_SITES[site].get("book")
        if reader is None:
            raise sources.SourceBroken(
                f"{RANK_SITES[site]['name']} не отдаёт подробностей книги")
        found = reader(client, book_id, slug=slug)
    else:
        found = rank_net.fetch_book(client, book_id)
    return books_op.save(book_id, found)


@app.get("/api/rank/book/<book_id>")
def api_rank_book(book_id: str):
    """Подробности книги для раскрытой строки (2.4 ТЗ).

    Данные подтягиваются лениво — по первому раскрытию — и кладутся в
    `data/books/{bookId}.json`. Ходить на сайт при каждом клике незачем:
    описание и жанр у книги меняются раз в месяц.
    """
    if not covers.safe_id(book_id):
        return jsonify(error="Плохой код книги"), 400

    # Каждый рейтинг рассказывает о книге сам. Раньше сюда шёл запрос
    # только фанкьюшный, и код с MVLEMPYR уходил на китайский сайт:
    # человек видел «HTTP 404 fanqienovel.com/page/13571». Потом такой
    # запрос стали отклонять — и раскрытая строка превратилась в копию
    # самой строки, без описания и меток. Теперь спрашиваем тот сайт, с
    # которого строка.
    site = _rank_site(request.args)
    if site:
        return _rank_book_elsewhere(site, book_id)

    # Перевод описания приезжает вместе с карточкой (3.1 ТЗ): переключатель
    # «原/RU» должен знать сразу, есть ли что показывать по второй кнопке.
    ru_text = titles_op.abstract_of(book_id)

    fresh = request.args.get("fresh") == "1"
    if not fresh:
        found = books_op.load(book_id)
        if found is not None:
            return jsonify(**found, abstract_ru=ru_text, cached=True)

    client = _rank_client()
    try:
        found = rank_net.fetch_book(client, book_id)
    except rank_net.Diagnosis as exc:
        return jsonify(error=str(exc), details=exc.details), 502
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 502
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}"), 502
    finally:
        client.close()

    return jsonify(**books_op.save(book_id, found), abstract_ru=ru_text,
                   cached=False)


@app.post("/api/rank/abstract")
def api_rank_abstract():
    """Перевод описания одной книги (3.1 ТЗ).

    По кнопке и по одной книге: описаний полсотни на срез, а читают из них
    два-три. Гнать все в модель ради «вдруг откроют» — полсотни лишних
    запросов на каждый снятый рейтинг.
    """
    payload = request.json or {}
    book_id = str(payload.get("book_id") or "").strip()
    if not covers.safe_id(book_id):
        return jsonify(error="Плохой код книги"), 400

    text = (payload.get("text") or "").strip()
    if not text:
        # Описание уже лежит в кэше карточки: строку раскрывали, иначе
        # кнопке «перевести» было бы неоткуда взяться.
        card = books_op.load(book_id) or {}
        text = str(card.get("abstract") or "").strip()

    client = _llm_client(payload)
    try:
        return jsonify(book_id=book_id, abstract=titles_op.translate_abstract(
            book_id, text, client,
            model=(payload.get("model") or "").strip(),
            force=bool(payload.get("force"))))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except NoKeysLeft as exc:
        return jsonify(error=str(exc)), 400
    except BadKey as exc:
        return jsonify(error=str(exc)), 401
    except LlmError as exc:
        return jsonify(error=str(exc)), 502
    finally:
        client.close()


@app.post("/api/find/translate")
def api_find_translate():
    """Перевод названия одной найденной книги.

    Книгу могли найти по коду, мимо рейтинга — тогда перевода у неё нет
    ниоткуда, а имя папки из иероглифов не собрать (3.2 ТЗ). Кладём в то
    же хранилище, что и рейтинг: у книги один код и один перевод.
    """
    payload = request.json or {}
    code = str(payload.get("code") or "").strip()
    name = (payload.get("name") or "").strip()
    if not code or not name:
        return jsonify(error="Нужны код книги и её название."), 400

    client = _llm_client(payload)
    try:
        row = rank_net.RankRow(book_id=code, name=name)
        done = titles_op.translate([row], client,
                                  model=(payload.get("model") or "").strip(),
                                  force=bool(payload.get("force")))
        translated = (done.get("titles") or {}).get(code, "")
        if not translated:
            return jsonify(error="Модель не вернула перевод названия."), 502
        return jsonify(code=code, translated=translated,
                       folder=naming.folder_name(name, code=code,
                                                 translated=translated))
    except NoKeysLeft as exc:
        return jsonify(error=str(exc)), 400
    except BadKey as exc:
        return jsonify(error=str(exc)), 401
    except LlmError as exc:
        return jsonify(error=str(exc)), 502
    finally:
        client.close()


def _about_texts(rows) -> dict:
    """Описания книг среза: `book_id` → текст на языке сайта.

    Цидянь печатает описание прямо в строке доски; у остальных сайтов оно
    появляется в кэше карточки, когда строку раскрывали. Чего нет ни там,
    ни там — переводить нечего, и ходить за этим на сайт мы не идём:
    полсотни походов по одной кнопке — это уже не перевод.
    """
    texts = {}
    for row in rows:
        if not row.book_id:
            continue
        text = str(getattr(row, "about", "") or "").strip()
        if not text:
            card = books_op.load(row.book_id) or {}
            text = str(card.get("abstract") or "").strip()
        if text:
            texts[row.book_id] = text
    return texts


def _about_missing(rows) -> tuple[int, int]:
    """Сколько описаний нет вовсе и сколько просто не забирали с сайта.

    Разница важная. «Описания нет» — это ответ, дальше делать нечего.
    «Не забирали» — это наше, и человеку надо сказать, что делать:
    раскрыть строку. Раньше оба случая складывались в одно число, и
    «Перевести всё» молча пропускало половину среза.
    """
    absent = unknown = 0
    for row in rows:
        if not row.book_id:
            continue
        if str(getattr(row, "about", "") or "").strip():
            continue
        card = books_op.load(row.book_id)
        if card is None:
            unknown += 1
        elif not str(card.get("abstract") or "").strip():
            absent += 1
    return absent, unknown


def _rank_snapshot(payload, site: str, board: str, category: str):
    """Срез, о котором идёт речь: названный день или самый свежий."""
    day = (payload.get("day") or "").strip()
    found = rank_op.load(day, board, category, site) if day else None
    if found is not None:
        return found
    days = rank_op.days(board, category, site)
    return rank_op.load(days[0], board, category, site) if days else None


@app.post("/api/rank/abouts/start")
def api_rank_abouts_start():
    """Забрать описания книг среза, которых ещё нет.

    Отдельной задачей, а не внутри перевода: это прогон по сайту на
    полсотни страниц. Держать кнопку нажатой минуту нельзя, а без
    описаний «Перевести всё» переводит одни названия — на что человек
    и жаловался.
    """
    payload = request.json or {}
    site = _rank_site(payload)
    board, category = _rank_board(payload, site)

    snapshot = _rank_snapshot(payload, site, board, category)
    if snapshot is None:
        return jsonify(error="Срезов пока нет — сначала обновите рейтинг"), 400

    # Идём только за теми, у кого описания нет ни в строке, ни в кэше.
    wanted = []
    for row in snapshot.rows:
        if not row.book_id or str(getattr(row, "about", "") or "").strip():
            continue
        card = books_op.load(row.book_id)
        if card is None:
            wanted.append(row)

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="rank",
        meta={"site": site, "board": board, "category": category},
    )
    job.progress = {"stage": "abouts", "done": 0, "total": len(wanted),
                    "message": (f"Описаний забрать: {len(wanted)}" if wanted
                                else "Все описания уже забраны")}

    def work(job: Job):
        got = missed = 0
        client = _rank_client()
        try:
            for index, row in enumerate(wanted, 1):
                if job.cancel.is_set():
                    break
                slug = (row.link or "").rstrip("/").split("/")[-1]
                try:
                    _fetch_card(client, site, row.book_id,
                                slug="" if slug == row.book_id else slug)
                    got += 1
                except (sources.SourceBroken, HttpError, ValueError,
                        rank_net.Diagnosis) as exc:
                    # Одна закрывшаяся книга не должна ронять весь прогон:
                    # её просто не будет в переводе, а остальные приедут.
                    missed += 1
                    log.info("Описание %s не забралось: %s", row.book_id, exc)
                job.progress.update(
                    done=index, got=got, missed=missed,
                    message=f"Описание {index} из {len(wanted)}")
        finally:
            client.close()

        job.report = {"got": got, "missed": missed, "total": len(wanted)}
        job.progress.update(
            stage="done",
            message=(f"Забрано описаний: {got}"
                     + (f", не далось: {missed}" if missed else "")
                     if wanted else "Все описания уже были забраны"))

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/rank/translate")
def api_rank_translate():
    """Прогоняет названия через модель. Кэш по book_id.

    С `abstracts` заодно переводит и описания — то самое «одной кнопкой».
    Счётчики у них раздельные: названия и описания стоят разного числа
    запросов, и складывать их в одно число значило бы прятать цену.
    """
    payload = request.json or {}
    site = _rank_site(payload)
    board, category = _rank_board(payload, site)
    snapshot = _rank_snapshot(payload, site, board, category)
    if snapshot is None:
        return jsonify(error="Срезов пока нет — сначала обновите рейтинг"), 400

    model = (payload.get("model") or "").strip()
    force = bool(payload.get("force"))

    client = _llm_client()
    try:
        done = titles_op.translate(snapshot.rows, client, model=model,
                                   force=force)
        if payload.get("abstracts"):
            texts = _about_texts(snapshot.rows)
            done["abouts"] = titles_op.translate_all_abstracts(
                texts, client, model=model, force=force)
            # Почему остальные остались без перевода. Без этих чисел
            # «переведено 12 из 80» читалось бы как поломка, а «нет
            # описания» врало бы про книги, у которых оно есть — просто
            # мы за ним не ходили.
            absent, unknown = _about_missing(snapshot.rows)
            done["abouts"]["absent"] = absent
            done["abouts"]["unknown"] = unknown
        return jsonify(**done)
    except NoKeysLeft as exc:
        return jsonify(error=str(exc)), 400
    except BadKey as exc:
        return jsonify(error=str(exc)), 401
    except LlmError as exc:
        return jsonify(error=str(exc)), 502
    finally:
        client.close()


# ------------------------------------------- пересказ и выгрузка (3.5)


def _export_path(payload: dict, root: Path, default: str) -> Path:
    """Куда писать выгрузку. По умолчанию — рядом с реестром."""
    chosen = (payload.get("path") or "").strip()
    if chosen:
        return Path(chosen).expanduser()
    fmt = (payload.get("format") or ".md").strip().lower()
    if not fmt.startswith("."):
        fmt = "." + fmt
    return root / "analysis" / f"{default}{fmt}"


@app.post("/api/retell/chapters")
def api_retell_chapters():
    """Пересказ по главам. Из собранных фактов, без новых запросов."""
    payload = request.json or {}
    registry = analyze_op.load_registry(_book_root(payload))
    items = retell_op.chapters(registry)
    return jsonify(chapters=[i.as_dict() for i in items],
                   total=len(items),
                   text=retell_op.chapters_text(registry))


@app.post("/api/retell/annotation")
def api_retell_annotation():
    """Аннотация книги. Один запрос к модели."""
    payload = request.json or {}
    registry = analyze_op.load_registry(_book_root(payload))
    client = _llm_client()
    try:
        return jsonify(**retell_op.annotation(
            registry, client, model=(payload.get("model") or "").strip()))
    except retell_op.RetellError as exc:
        return jsonify(error=str(exc)), 400
    except BadKey as exc:
        return jsonify(error=str(exc)), 401
    except LlmError as exc:
        return jsonify(error=str(exc)), 502
    finally:
        client.close()


@app.post("/api/export")
def api_export():
    """Выгрузка карточек, пересказа или аннотации в .md или .docx."""
    payload = request.json or {}
    root = _book_root(payload)
    what = (payload.get("what") or "cards").strip()
    registry = analyze_op.load_registry(root)

    if what == "cards":
        kind = (payload.get("type") or "персонаж").strip()
        text = glossary_op.cards_text(registry, kind)
        default = f"карточки-{kind}"
    elif what == "retell":
        text = retell_op.chapters_text(registry)
        default = "пересказ"
    elif what == "glossary":
        text = glossary_op.dump(registry, (payload.get("glossary_format") or "txt"))
        default = "глоссарий"
    elif what == "text":
        # Аннотация уже показана на экране — второй раз её не запрашиваем.
        text = str(payload.get("text") or "")
        default = "аннотация"
    else:
        return jsonify(error=f"Нечего выгружать: {what}"), 400

    try:
        saved = docs_op.save(text, _export_path(payload, root, default),
                             style=Style.from_dict(payload.get("style")))
    except docs_op.ExportError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(saved=saved, length=len(text))


# ------------------------------------------- вкладка «Инструменты»


def _rules(payload: dict) -> list:
    """Правила замены из запроса либо из словаря книги."""
    rules = payload.get("rules")
    if isinstance(rules, list) and rules:
        return [replace_op.Rule.from_dict(r) for r in rules]
    text = payload.get("dictionary")
    if isinstance(text, str) and text.strip():
        return replace_op.parse_dictionary(text)
    return []


@app.post("/api/replace/preview")
def api_replace_preview():
    """Все совпадения с контекстом. На диск ничего не пишется."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**replace_op.preview(targets, _rules(payload)).as_dict())
    except replace_op.ReplaceError as exc:
        return jsonify(error=str(exc)), 400
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/replace/start")
def api_replace_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите папку, где создать каталог"), 400
    if not folder:
        return jsonify(error="Введите имя папки"), 400

    try:
        rules = _rules(payload)
        if not rules:
            return jsonify(error="Нечего заменять: правило пустое"), 400
        made = _prepare(base, folder, "replace")
        output_dir = made.dir
    except replace_op.ReplaceError as exc:
        return jsonify(error=str(exc)), 400
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    # Снятые галочки приходят четвёрками «файл, абзац, правило, номер».
    skip = {(str(s[0]), int(s[1]), int(s[2]), int(s[3]))
            for s in (payload.get("skip") or []) if len(s) == 4}

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="replace",
        meta={"targets": targets, "rules": len(rules)},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "replace", "message": "Заменяем…",
                    "done": 0, "total": 0, "written": 0, "failed": 0}

    job.keep(made)

    def work(job: Job):
        _finish(job, replace_op.run(
            targets, Path(job.output_dir), rules, skip=skip,
            progress=_progress(job, "Файл"),
        ), "Записано")

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/dictionary/load")
def api_dictionary_load():
    """Словарь автозамен книги. Свой у каждой — лежит рядом с ней."""
    payload = request.json or {}
    root = _book_root(payload)
    path = replace_op.dictionary_path(root)
    text = ""
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return jsonify(error=f"Не удалось прочитать словарь: {exc}"), 400
    return jsonify(text=text, path=str(path),
                   rules=len(replace_op.parse_dictionary(text)))


@app.post("/api/dictionary/save")
def api_dictionary_save():
    payload = request.json or {}
    root = _book_root(payload)
    try:
        path = replace_op.save_dictionary(root, payload.get("text") or "")
    except OSError as exc:
        return jsonify(error=f"Не удалось сохранить словарь: {exc}"), 400
    return jsonify(path=str(path),
                   rules=len(replace_op.parse_dictionary(payload.get("text") or "")))


@app.post("/api/dictionary/summary")
def api_dictionary_summary():
    """Сколько замен даст каждое правило — сводка до применения."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    rules = _rules(payload)
    if not rules:
        return jsonify(error="Словарь пуст"), 400
    try:
        return jsonify(**replace_op.dictionary_summary(targets, rules))
    except replace_op.ReplaceError as exc:
        return jsonify(error=str(exc)), 400
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/compare/start")
def api_compare_start():
    """Сверка оригинала и перевода по номерам глав."""
    payload = request.json or {}
    original = _targets({"targets": payload.get("original")})
    translated = _targets({"targets": payload.get("translated")})

    if not original or not translated:
        return jsonify(error="Выберите обе папки: оригинал и перевод"), 400

    kinds = payload.get("kinds")
    kinds = [k for k in kinds if k in compare_op.KINDS] if isinstance(kinds, list) else None
    try:
        return jsonify(**compare_op.check(original, translated, kinds).as_dict())
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.get("/api/compare/kinds")
def api_compare_kinds():
    return jsonify(kinds=[{"key": k, "name": v} for k, v in compare_op.KINDS.items()])


@app.post("/api/sides/start")
def api_sides_start():
    """Одна книга с двух сайтов: где они расходятся и какую папку брать."""
    payload = request.json or {}
    left = _targets({"targets": payload.get("left")})
    right = _targets({"targets": payload.get("right")})

    if not left or not right:
        return jsonify(error="Выберите обе папки: два слива одной книги"), 400
    try:
        return jsonify(**sides_op.compare(left, right).as_dict())
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/checkup/start")
def api_checkup_start():
    """Осмотр скачанного: дыры в нумерации, пустые главы, обрывки, повторы.

    Задачей, а не сразу ответом: книга на полторы тысячи глав читается
    целиком, и держать страницу немой полминуты нельзя.
    """
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите папку книги"), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="checkup",
        meta={"targets": targets},
        output_dir=targets[0],
    )
    job.progress = {"stage": "checkup", "message": "Читаем главы…",
                    "done": 0, "total": 0}

    def work(job: Job):
        found = checkup_op.look(targets, Progress(
            lambda done, total, message="": job.progress.update(
                done=done, total=total,
                message=message or f"Файл {done} из {total}"),
            job.cancel))
        job.report = found.as_dict()
        job.progress.update(stage="done", message=found.summary())

    return jsonify(job=start_job(job, work).snapshot())



# ------------------------------- журнал, корзина и сравнение версий


@app.post("/api/diff")
def api_diff():
    """Что изменилось: до операции и после."""
    payload = request.json or {}
    before = (payload.get("before") or "").strip()
    after = (payload.get("after") or "").strip()
    if not before or not after:
        return jsonify(error="Укажите обе стороны сравнения"), 400
    try:
        return jsonify(**diff_op.compare(before, after).as_dict())
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400



# ------------------------------- статистика, шапка и подпись


@app.post("/api/stats")
def api_stats():
    """Сколько глав, символов, слов и сколько это читать."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**stats_op.collect(targets).as_dict())
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.get("/api/signature/placeholders")
def api_signature_placeholders():
    return jsonify(placeholders=[{"key": k, "name": v}
                                 for k, v in signature_op.PLACEHOLDERS.items()])


@app.post("/api/signature/preview")
def api_signature_preview():
    """Как будет выглядеть первая глава. На диск ничего не пишется."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        template = signature_op.Template.from_dict(payload.get("template"))
        return jsonify(**signature_op.preview(targets, template))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/signature/start")
def api_signature_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    template = signature_op.Template.from_dict(payload.get("template"))

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base or not folder:
        return jsonify(error="Укажите, куда сохранить"), 400
    if template.empty:
        return jsonify(error="Шаблоны пусты: нечего добавлять"), 400

    try:
        made = _prepare(base, folder, "signature")
        output_dir = made.dir
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="signature",
        meta={"targets": targets},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "signature", "message": "Дописываем…",
                    "done": 0, "total": 0, "written": 0, "failed": 0}

    job.keep(made)

    def work(job: Job):
        _finish(job, signature_op.run(
            targets, Path(job.output_dir), template,
            prep=PrepOptions.from_dict(payload.get("prep")),
            style=Style.from_dict(payload.get("style")),
            progress=_progress(job, "Глава"),
        ), "Записано")

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------------ читалка (4.4)


@app.post("/api/reader/list")
def api_reader_list():
    """Список глав — по нему интерфейс строит переход стрелками."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**reader_op.listing(targets))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/reader/open")
def api_reader_open():
    """Одна глава в том виде, в каком уйдёт в файл."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400

    # Пустой список сохраняем как есть: это снятая галочка «подсветить
    # находки», а не просьба проверить всё подряд.
    kinds = payload.get("kinds")
    if isinstance(kinds, list):
        kinds = [k for k in kinds if k in textcheck.ALL_KINDS]

    try:
        page = reader_op.open_at(
            targets,
            index=payload.get("index") or 0,
            prep=PrepOptions.from_dict(payload.get("prep")),
            kinds=kinds,
        )
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(**page.as_dict())


@app.post("/api/reader/save")
def api_reader_save():
    """Правка поверх исходного файла — единственное такое место."""
    payload = request.json or {}
    source = (payload.get("source") or "").strip()
    if not source:
        return jsonify(error="Не указана глава"), 400
    try:
        return jsonify(**reader_op.save(source, payload.get("text") or ""))
    except reader_op.SaveError as exc:
        return jsonify(error=str(exc)), 400


# ------------------------------------------------ орфография (4.9)


def _spell_root(payload: dict, targets: list[str]) -> Path:
    """Где лежит книга: оттуда свой словарь и реестр имён."""
    folder = (payload.get("folder") or "").strip()
    if folder:
        return Path(folder).expanduser()
    first = Path(targets[0]).expanduser()
    return first if first.is_dir() else first.parent


@app.post("/api/spelling/state")
def api_spelling_state():
    """Есть ли словарь и что уже внесено в свой список."""
    payload = request.json or {}
    targets = _targets(payload)
    folder = _spell_root(payload, targets) if targets else ""
    return jsonify(**spelling_op.state(folder))


@app.post("/api/spelling/start")
def api_spelling_start():
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not spelling_op.available():
        return jsonify(
            error="Словарь не установлен. Поставьте пакеты: "
                  "pip install pymorphy3 pymorphy3-dicts-ru",
            need_package=True), 422

    root = _spell_root(payload, targets)
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="spelling",
        meta={"targets": targets},
        output_dir=str(root),
    )
    job.progress = {"stage": "spelling", "message": "Читаем словарь…",
                    "done": 0, "total": 0}

    def work(job: Job):
        report = spelling_op.check(
            targets, folder=root,
            use_registry=bool(payload.get("use_registry", True)),
            progress=_progress(job, "Глава"),
        )
        job.report = report.as_dict()
        job.progress.update(
            stage="done",
            message=(f"Готово. Незнакомых слов {len(report.findings)} "
                     f"на {report.words} слов текста"))

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/spelling/known")
def api_spelling_known():
    """Кнопка «это имя»: слово уходит в свой словарь книги."""
    payload = request.json or {}
    targets = _targets(payload)
    words = [str(w) for w in (payload.get("words") or []) if str(w).strip()]
    if not words:
        return jsonify(error="Нечего добавлять"), 400

    root = _spell_root(payload, targets) if targets else None
    if root is None:
        return jsonify(error="Не понятно, к какой книге относить слово"), 400
    try:
        spelling_op.add_words(root, words)
    except OSError as exc:
        return jsonify(error=f"Не удалось записать словарь: {exc}"), 400
    return jsonify(**spelling_op.state(root))


# ------------------------------------------------ очередь задач (4.6)

#: Что умеет очередь. Ключ — вид шага, значение — как его назвать.
QUEUE_KINDS = {
    "split": "Разбить на главы",
    "merge": "Объединить в один файл",
    "rename": "Переименовать",
    "clean": "Очистить текст",
    "replace": "Замена по словарю",
    "signature": "Шапка и подпись",
    "check": "Проверить текст",
    "spelling": "Проверить орфографию",
    "stats": "Статистика",
}


def _step_targets(step, previous: str) -> list[str]:
    """Что берём на вход.

    Пустой список — значит «то, что вышло из предыдущего шага». На этом
    держится вся цепочка: разбить → переименовать → проверить.
    """
    targets = _targets(step.params)
    if targets:
        return targets
    if not previous:
        raise ValueError("Шагу нечего обрабатывать: нет ни выбора, ни "
                         "результата предыдущего шага")
    return [previous]


def _step_output(step, kind: str, job: "Job | None" = None) -> Path:
    base = (step.params.get("base") or "").strip()
    folder = (step.params.get("folder") or "").strip()
    if not base or not folder:
        raise ValueError("Укажите, куда сохранить результат шага")
    made = _prepare(base, folder, kind)
    # След оставляет последний записавший шаг — вернуть как было можно
    # ровно то, что цепочка сделала последним.
    return job.keep(made) if job is not None else made.dir


def _run_step(step, previous: str, cancel: threading.Event,
              job: "Job | None" = None) -> tuple[str, str]:
    """Выполняет один шаг очереди. Возвращает (итог, папка результата).

    Шаги делают ровно то же, что кнопки на вкладках, — те же функции из
    `ops`. Иначе очередь начала бы жить своей жизнью и расходиться с ними.
    """
    kind = step.kind
    params = step.params
    targets = _step_targets(step, previous)
    progress = Progress(cancel=cancel)

    if kind == "split":
        out = _step_output(step, kind, job)
        report = split_op.run(
            targets, out, out_format=_out_format(params),
            parts=_parts(params), pattern=_pattern(params),
            prep=PrepOptions.from_dict(params.get("prep")),
            encoding=_encoding(params), progress=progress)
        return f"Записано {report.written} из {report.total}", str(out)

    if kind == "merge":
        base = (params.get("base") or "").strip()
        name = (params.get("folder") or params.get("name") or "книга").strip()
        if not base:
            raise ValueError("Укажите, куда сохранить результат шага")
        out = Path(base).expanduser() / f"{name}{_out_format(params)}"
        out.parent.mkdir(parents=True, exist_ok=True)
        report = merge_op.run(
            targets, out, order=_order(params),
            headings=bool(params.get("headings", True)),
            encoding=_encoding(params),
            prep=PrepOptions.from_dict(params.get("prep")),
            progress=progress)
        return f"Собрано {report.written} глав в {out.name}", str(out)

    if kind == "rename":
        out = _step_output(step, kind, job)
        chapters = rename.scan(targets[0], _pattern(params))
        rows = rename.make_plan(
            chapters, rename.NameFormat.from_dict(params.get("format")))
        report = rename.apply_plan(
            rows, out, fmt=(params.get("out_format") or "txt").strip().lower(),
            cancel=cancel)
        return f"Переименовано {report.written} из {report.total}", str(out)

    if kind == "clean":
        out = _step_output(step, kind, job)
        kinds = params.get("kinds")
        kinds = list(cleanup.ALL_KINDS) if kinds is None else kinds
        cleanup._validate(kinds)
        fixed = written = 0
        for target in targets:
            report = cleanup.clean(target, kinds, out, cancel=cancel)
            fixed += sum(report.counts.values())
            written += report.written
        return f"Исправлено {fixed} мест в {written} файлах", str(out)

    if kind == "replace":
        out = _step_output(step, kind, job)
        rules = params.get("rules") or []
        report = replace_op.run(
            targets, out, rules, out_format=(params.get("format") or ""),
            encoding=_encoding(params), progress=progress)
        return f"Записано {report.written} из {report.total}", str(out)

    if kind == "signature":
        out = _step_output(step, kind, job)
        report = signature_op.run(
            targets, out, signature_op.Template.from_dict(params.get("template")),
            prep=PrepOptions.from_dict(params.get("prep")),
            encoding=_encoding(params), progress=progress)
        return f"Записано {report.written} из {report.total}", str(out)

    if kind == "check":
        kinds = params.get("kinds") or list(textcheck.ALL_KINDS)
        report = textcheck.check(targets, kinds=kinds, cancel=cancel)
        # Проверка ничего не пишет — следующий шаг работает с тем же входом.
        return (f"Находок {len(report.findings)} в {report.files_with_findings} "
                f"файлах из {report.files_checked}"), previous

    if kind == "spelling":
        report = spelling_op.check(targets, progress=progress)
        return (f"Незнакомых слов {len(report.findings)} "
                f"на {report.words} слов текста"), previous

    if kind == "stats":
        report = stats_op.collect(targets).as_dict()
        return (f"Глав {report['chapters']}, символов {report['characters']}, "
                f"чтения примерно {report['reading_time']}"), previous

    raise ValueError(f"Неизвестный шаг очереди: {kind}")


@app.get("/api/queue/state")
def api_queue_state():
    """Сохранённые очереди и виды шагов, из которых их собирают."""
    return jsonify(
        queues=[q.as_dict() for q in queue_op.all_queues()],
        kinds=[{"key": k, "name": v} for k, v in QUEUE_KINDS.items()],
    )


@app.post("/api/queue/save")
def api_queue_save():
    payload = request.json or {}
    queue = queue_op.Queue.from_dict(payload.get("queue"))
    unknown = [s.kind for s in queue.steps if s.kind not in QUEUE_KINDS]
    if unknown:
        return jsonify(error=f"Неизвестный шаг: {', '.join(unknown)}"), 400
    if not queue.steps:
        return jsonify(error="В очереди нет ни одного шага"), 400

    for step in queue.steps:
        step.title = step.title or QUEUE_KINDS[step.kind]
    try:
        queue_op.save(queue)
    except queue_op.QueueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(queues=[q.as_dict() for q in queue_op.all_queues()])


@app.post("/api/queue/remove")
def api_queue_remove():
    payload = request.json or {}
    queue_op.remove((payload.get("name") or "").strip())
    return jsonify(queues=[q.as_dict() for q in queue_op.all_queues()])


@app.post("/api/queue/start")
def api_queue_start():
    """Запускает очередь целиком — ради этого она и заводилась."""
    payload = request.json or {}
    name = (payload.get("name") or "").strip()
    queue = queue_op.get(name) if name else queue_op.Queue.from_dict(
        payload.get("queue"))
    if queue is None or not queue.steps:
        return jsonify(error="Очередь не найдена или пуста"), 400

    unknown = [s.kind for s in queue.steps if s.kind not in QUEUE_KINDS]
    if unknown:
        return jsonify(error=f"Неизвестный шаг: {', '.join(unknown)}"), 400
    queue.reset()
    for step in queue.steps:
        step.title = step.title or QUEUE_KINDS[step.kind]

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="queue",
        meta={"queue": queue.name},
        output_dir="",
    )
    job.progress = {"stage": "queue", "message": "Запускаем очередь…",
                    "done": 0, "total": len(queue.steps),
                    "queue": queue.as_dict()}

    def work(job: Job):
        # Папка результата передаётся из шага в шаг: цепочка «разбить →
        # переименовать» иначе требовала бы вписывать пути руками.
        chain = {"previous": (payload.get("start_from") or "").strip()}

        def perform(step):
            message, output = _run_step(step, chain["previous"],
                                         job.cancel, job)
            chain["previous"] = output or chain["previous"]
            job.output_dir = chain["previous"]
            return message

        def changed(current):
            job.progress.update(done=current.done, total=len(current.steps),
                                queue=current.as_dict(),
                                message=_queue_message(current))

        done = queue_op.run(queue, perform, on_change=changed, cancel=job.cancel)
        job.report = done.as_dict()
        job.progress.update(stage="done", message=_queue_message(done))
        history_op.add(operation="очередь задач", source=done.name,
                       output=chain["previous"], files=done.done,
                       failed=sum(1 for s in done.steps
                                  if s.state == queue_op.FAILED))

    return jsonify(job=start_job(job, work).snapshot())


def _queue_message(queue) -> str:
    if queue.state == queue_op.FAILED:
        broken = next((s for s in queue.steps if s.state == queue_op.FAILED), None)
        return f"Остановились на шаге «{broken.title}»: {broken.message}" if broken \
            else "Очередь остановилась"
    if queue.state == queue_op.DONE:
        return f"Готово. Выполнено шагов: {queue.done} из {len(queue.steps)}"
    if queue.state == queue_op.SKIPPED:
        return "Очередь остановлена"
    current = queue.steps[queue.current] if 0 <= queue.current < len(queue.steps) else None
    return f"Шаг {queue.current + 1} из {len(queue.steps)}: {current.title}" \
        if current else "Запускаем очередь…"


# ------------------------------------------------ вкладка «Проверка текста»


@app.get("/api/check/rules")
def api_check_rules():
    """Правила по группам и пресеты — интерфейс строит галочки по этому."""
    return jsonify(
        groups=checks.grouped(),
        presets=[
            {"key": key, "name": name, "kinds": list(checks.PRESET_KEYS[key])}
            for key, name in checks.PRESETS.items()
        ],
        clean_kinds=[
            {"key": key, "name": name} for key, name in cleanup.KINDS.items()
        ],
    )


@app.post("/api/check/start")
def api_check_start():
    payload = request.json or {}
    targets = _targets(payload)
    # Ключа нет — проверяем всё. Пустой список — это снятые галочки, и это
    # уже ошибка: молча проверять всё подряд нельзя.
    kinds = payload.get("kinds")
    if kinds is None:
        kinds = list(textcheck.ALL_KINDS)

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not kinds:
        return jsonify(error="Отметьте хотя бы одну проверку"), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="check",
        meta={"targets": targets, "kinds": kinds},
        output_dir=targets[0],
    )
    job.progress = {"stage": "check", "message": "Читаем файлы…", "done": 0, "total": 0}

    def work(job: Job):
        report = textcheck.check(
            targets, kinds,
            on_progress=lambda done, total: job.progress.update(
                done=done, total=total, message=f"Файл {done} из {total}"),
            cancel=job.cancel,
        )
        job.report = report.as_dict()
        # Текст отчёта держим в задаче — выгрузка берёт его отсюда.
        job.meta["report_text"] = textcheck.report_text(report)
        job.progress.update(
            stage="done",
            message=(f"Готово. Находок {len(report.findings)} "
                     f"в {report.files_with_findings} файлах из {report.files_checked}"),
        )

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/clean/preview")
def api_clean_preview():
    """Сколько замен будет сделано — до того, как что-то записано."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        # Считаем по всем выбранным целям сразу.
        merged: dict = {}
        total = 0
        unreadable: list = []
        for target in targets:
            kinds = payload.get("kinds")
            result = cleanup.preview(
                target, list(cleanup.ALL_KINDS) if kinds is None else kinds
            )
            total += result["total"]
            unreadable.extend(result["unreadable"])
            for row in result["counts"]:
                merged[row["kind"]] = merged.get(row["kind"], 0) + row["count"]
    except CleanError as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(
        counts=[
            {"kind": k, "kind_name": cleanup.KINDS.get(k, k), "count": v}
            for k, v in sorted(merged.items(), key=lambda kv: -kv[1])
        ],
        total=total,
        unreadable=unreadable,
    )


@app.post("/api/clean/start")
def api_clean_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    # Ключа нет — чистим всё. Пустой список — снятые галочки, это ошибка:
    # молча вычистить всё подряд нельзя, правки необратимы для результата.
    kinds = payload.get("kinds")
    if kinds is None:
        kinds = list(cleanup.ALL_KINDS)

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите, куда сохранить"), 400
    if not folder:
        return jsonify(error="Введите имя новой папки"), 400

    try:
        cleanup._validate(kinds)
    except CleanError as exc:
        return jsonify(error=str(exc)), 400

    try:
        made = _prepare(base, folder, "clean")
        output_dir = made.dir
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="clean",
        meta={"targets": targets, "kinds": kinds},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "clean", "message": "Чистим…", "done": 0, "total": 0}

    job.keep(made)

    def work(job: Job):
        # Несколько целей чистим по очереди в одну папку.
        merged: dict = {}
        written = failed = files = 0
        failures: list = []
        for target in targets:
            report = cleanup.clean(
                target, kinds, Path(job.output_dir),
                on_progress=lambda done, total: job.progress.update(
                    done=done, total=total, message=f"Файл {done} из {total}"),
                cancel=job.cancel,
            )
            written += report.written
            failed += report.failed
            files += report.files
            failures.extend(report.failures)
            for key, value in report.counts.items():
                merged[key] = merged.get(key, 0) + value

        job.report = {
            "output_dir": job.output_dir,
            "files": files, "written": written, "failed": failed,
            "total": sum(merged.values()),
            "counts": [
                {"kind": k, "kind_name": cleanup.KINDS.get(k, k), "count": v}
                for k, v in sorted(merged.items(), key=lambda kv: -kv[1]) if v
            ],
            "failed_files": failures,
        }
        job.progress.update(
            stage="done",
            message=(f"Готово. Исправлено {sum(merged.values())} мест "
                     f"в {written} файлах" + (f", ошибок {failed}" if failed else "")),
        )

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/open")
def api_open():
    """Открывает файл в программе по умолчанию (Word для .docx и так далее).

    Точное позиционирование на строке средствами Windows недостижимо,
    поэтому открываем файл целиком — искать место человек будет через
    Ctrl+F по скопированному фрагменту.
    """
    payload = request.json or {}
    name = (payload.get("path") or "").strip()
    if not name:
        return jsonify(error="Не указан файл"), 400

    path = Path(name).expanduser()
    if not path.exists():
        return jsonify(error=f"Файл не найден: {path}"), 404

    try:
        opened = platform.open_file(path)
    except platform.OpenError as exc:
        # Не поломка сервера: файл есть, а открыть его нечем. 500 здесь
        # пугал бы зря.
        return jsonify(error=str(exc)), 400

    return jsonify(opened=str(opened))


@app.get("/api/titles/spellings")
def api_spellings_show():
    """Словарь имён: как писать их по-русски."""
    table = titles_op.spellings()
    return jsonify(
        pairs=[{"from": key, "to": value} for key, value in table.items()],
        total=len(table),
        text="\n".join(f"{key} = {value}" for key, value in table.items()))


@app.post("/api/titles/spellings")
def api_spellings_save():
    """Принимает словарь в любом виде, какой прислали.

    Разбирает его `ops/glossary` — тот же, что уже принимает глоссарий от
    переводчика: `=`, стрелка, CSV, JSON. Своего разбора здесь нет
    намеренно, иначе два понимания одного файла разъехались бы.
    """
    payload = request.json or {}
    if payload.get("clear"):
        titles_op.forget_spellings()
        return jsonify(total=0, added=0, pairs=[], text="")

    pairs = glossary_op.parse(str(payload.get("text") or ""))
    if not pairs:
        return jsonify(error="Не нашлось ни одной пары «имя = перевод». "
                             "Годятся строки «Li Xiao = Ли Сяо», стрелка, "
                             "CSV и JSON."), 400

    if payload.get("replace"):
        titles_op.forget_spellings()
    table = titles_op.remember_spellings(pairs)
    return jsonify(
        total=len(table), added=len(pairs),
        pairs=[{"from": key, "to": value} for key, value in table.items()],
        text="\n".join(f"{key} = {value}" for key, value in table.items()))




@app.get("/api/check/<job_id>/report")
def api_check_report(job_id: str):
    """Выгрузка отчёта в .txt."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None or job.kind != "check":
        return jsonify(error="Задача не найдена"), 404
    text = job.meta.get("report_text")
    if not text:
        return jsonify(error="Отчёт ещё не готов"), 409

    return Response(
        text,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="check-report.txt"'},
    )


@app.get("/api/job/<job_id>")
def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="Задача не найдена"), 404
    return jsonify(job=job.snapshot())


@app.post("/api/job/<job_id>/cancel")
def api_cancel(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="Задача не найдена"), 404
    job.cancel.set()
    # Из паузы надо выйти, иначе поток так и будет стоять в ожидании и
    # отмену заметит только когда его отпустят.
    job.paused.clear()
    return jsonify(job=job.snapshot())


@app.post("/api/job/<job_id>/pause")
def api_pause(job_id: str):
    """Останавливает работу на ближайшей границе главы, не бросая её.

    Оборвалась сеть или нужно освободить канал — прогон ждёт, а не
    заканчивается. Скачанное остаётся на месте, продолжение идёт с той
    же главы.
    """
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="Задача не найдена"), 404
    job.paused.set()
    return jsonify(job=job.snapshot())


@app.post("/api/job/<job_id>/resume")
def api_resume(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="Задача не найдена"), 404
    job.paused.clear()
    return jsonify(job=job.snapshot())


@app.post("/api/verify")
def api_verify():
    path = (request.json or {}).get("path", "").strip()
    if not path:
        return jsonify(error="Укажите папку книги"), 400
    try:
        return jsonify(report=verify(Path(path).expanduser()))
    except OSError as exc:
        return jsonify(error=str(exc)), 400


def main() -> None:
    import argparse
    import webbrowser

    # Название одно на всю программу — то же, что в шапке страницы.
    # MVLEMPYR здесь стоять не может: это имя одного из источников, а
    # не программы, и в консоли оно противоречило экрану.
    parser = argparse.ArgumentParser(description="NEUROSTRAZH — веб-интерфейс")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1", help="менять не рекомендуется")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--proxies", default=PROXY_FILE, help="файл со списком прокси")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # Журнал в файл. Консоль на Windows закрывается вместе с программой,
    # и разбирать поломку по ней потом нечем.
    written = logbook.start()
    if written:
        print(f"  Журнал: {written}")
    # Счётчик трафика: месячный итог должен пережить закрытие окна.
    traffic.setup(history_op.DATA_DIR / "traffic.json")
    # Очередь книг могла остаться с надписью «качается» — программу
    # закрыли посреди книги. Работы за этой надписью уже нет.
    downloads_op.recover()
    # Ночной сторож очереди книг. Демон: закрытие программы его не ждёт.
    threading.Thread(target=_watch_schedule, daemon=True).start()

    try:
        pool = load_pool(args.proxies)
        print(f"  Список прокси: {args.proxies}, адресов — {len(pool)}")
    except (OSError, ValueError) as exc:
        print(f"  Прокси не загружены ({scrub(str(exc))}). Укажите файл в интерфейсе.")

    open_to(args.host)
    if not ALLOWED_NAMES:
        print("  ВНИМАНИЕ: сервер доступен из сети. Он даёт доступ к файлам "
              "на диске — не оставляйте его открытым.")

    url = f"http://{args.host}:{args.port}"
    print(f"\n  NEUROSTRAZH → {url}\n  Ctrl+C чтобы остановить\n")

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
