"""Маршруты связи с переводчиком EPUB.

Второй файл, отделённый от `webapp/app.py`, и по той же причине: вкладка
сама по себе, зависимостей у неё почти нет. Здесь только разговор с чужой
программой — ни перевода, ни хранения.

Сохранение пути идёт в `config.json`, потому что это настройка, а не
состояние: она должна пережить перезапуск, и человек вправе поправить её
руками.
"""

from __future__ import annotations

import logging
import uuid

from flask import Blueprint, jsonify, request

from config import settings
from ops import translator as translator_op

from .jobs import Job, start_job

log = logging.getLogger(__name__)

translator = Blueprint("translator", __name__)

#: Сколько последних строк журнала держим на виду. Перевод книги пишет их
#: тысячами, а смотрят всегда в конец.
LOG_TAIL = 60


@translator.get("/api/translator/state")
def api_translator_state():
    """Указан ли путь и похоже ли то, что по нему лежит, на переводчик."""
    return jsonify(**translator_op.state())


@translator.post("/api/translator/path")
def api_translator_path():
    """Запомнить, где стоит переводчик.

    Путь проверяется сразу: сказать «это не та папка» в момент выбора
    полезнее, чем через полчаса на середине перевода.
    """
    payload = request.json or {}
    path = str(payload.get("path") or "").strip()
    # Объяснение берём то же, что и при запуске: два разных совета на
    # одну беду — верный способ отправить человека не туда.
    why = translator_op.trouble_with(path) if path else ""
    if why:
        return jsonify(error=why, **translator_op.state(path)), 400

    settings.translator.path = path
    try:
        settings.save()
    except OSError as exc:
        return jsonify(error=f"Не удалось записать настройки: {exc}"), 400
    return jsonify(**translator_op.state())


@translator.post("/api/translator/plan")
def api_translator_plan():
    """Что именно будет переведено — до того, как за это заплатят.

    В сеть не ходит и квоту не тратит, поэтому и отвечаем сразу, а не
    задачей: ждать тут нечего, кроме чтения самого епаба.
    """
    payload = request.json or {}
    try:
        knobs = _knobs(payload)
        said = translator_op.plan(
            str(payload.get("epub") or "").strip(),
            str(payload.get("project") or "").strip(),
            path=str(payload.get("path") or "").strip(), **knobs,
        )
    except translator_op.TranslatorError as exc:
        return jsonify(error=str(exc)), 400

    if not said.get("ok", True):
        return jsonify(error=str(said.get("error") or "переводчик отказал")), 400
    return jsonify(ok=True, **translator_op.short_plan(said))


def _start(kind: str, work, payload: dict):
    """Долгая команда переводчика — обычной задачей.

    Четыре команды устроены одинаково: часы работы, живой журнал в stderr
    и кнопка «Остановить». Разница между ними — только в том, что зовём,
    и держать это четырьмя копиями значило бы однажды починить остановку
    в трёх местах из четырёх.
    """
    job = Job(id=uuid.uuid4().hex[:12], kind="translator",
              meta={"command": kind},
              output_dir=str(payload.get("project") or ""))
    job.progress = {"stage": kind, "message": "Запускаем переводчик…",
                    "done": 0, "total": 0, "lines": []}

    def note(row: str) -> None:
        """Строка чужого журнала — на экран.

        Она же и есть весь наш прогресс: сколько глав впереди, переводчик
        по ходу не сообщает, а рисовать процент наугад — врать.
        """
        job.progress["message"] = row
        rows = job.progress.setdefault("lines", [])
        rows.append(row)
        del rows[:-LOG_TAIL]

    def run(job: Job):
        said = work(note=note, stop=job.cancel)
        job.report = said if isinstance(said, dict) else {}
        # Отказ он сообщает не кодом возврата, а полем в ответе. Не
        # посмотри мы сюда — после часа работы вхолостую на экране
        # написалось бы «Готово».
        if job.report.get("ok") is False:
            raise translator_op.TranslatorError(
                str(job.report.get("error") or "переводчик отказал"))
        job.progress["stage"] = "done"
        job.progress["message"] = "Готово."

    return jsonify(job=start_job(job, run).snapshot())


def _knobs(payload: dict) -> dict:
    """Ручки, общие у плана, перевода, глоссария и сверки."""
    return {
        "scope": str(payload.get("scope") or translator_op.PENDING).strip(),
        "provider": str(payload.get("provider") or "").strip(),
        "model": str(payload.get("model") or "").strip(),
        "workers": payload.get("workers") or 0,
        "rpm": payload.get("rpm") or 0,
        "temperature": payload.get("temperature"),
        "prompt": str(payload.get("prompt") or "").strip(),
        "limit": payload.get("limit") or 0,
        "offset": payload.get("offset") or 0,
        "pick": payload.get("pick") or "",
    }


@translator.post("/api/translator/providers")
def api_translator_providers():
    """Какие сервисы перевода у него настроены и сколько там ключей.

    Список берём у него, а не держим свой: добавит он себе провайдера —
    наш перечень о том не узнает и начнёт врать.
    """
    payload = request.json or {}
    path = str(payload.get("path") or "").strip()
    try:
        said = translator_op.providers(path)
    except translator_op.TranslatorError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, providers=translator_op.short_providers(said))


@translator.post("/api/translator/models")
def api_translator_models():
    """Модели выбранного сервиса — с его же квотами."""
    payload = request.json or {}
    path = str(payload.get("path") or "").strip()
    provider = str(payload.get("provider") or "").strip()
    try:
        said = translator_op.models(provider, path)
    except translator_op.TranslatorError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, **translator_op.short_models(said))


def _check_knobs(payload: dict) -> dict:
    """Ручки одной только сверки. У перевода и глоссария их нет."""
    return {
        "way": str(payload.get("way") or "").strip(),
        "deed": str(payload.get("deed") or translator_op.LOOK).strip(),
        "sure": payload.get("sure") or (),
        "chunk": payload.get("chunk") or 0,
        "glossary_first": bool(payload.get("glossaryFirst")),
        # Вопрос прямой, флаг у него обратный.
        "source": payload.get("source", True) is not False,
        "suffix": str(payload.get("suffix") or "").strip(),
    }


def _glossary_knobs(payload: dict) -> dict:
    """Ручки одного только сбора глоссария."""
    return {
        "merge": str(payload.get("merge") or "").strip(),
        "batch": payload.get("batch") or 0,
        "new_terms": payload.get("newTerms") or 0,
        "glossary_prompt": str(payload.get("glossaryPrompt") or "").strip(),
        "glossary_file": str(payload.get("glossaryFile") or "").strip(),
    }


@translator.post("/api/translator/<any(translate,glossary,consistency):what>")
def api_translator_work(what: str):
    """Перевод, сбор глоссария и сверка — три команды одной дорогой."""
    payload = request.json or {}
    epub = str(payload.get("epub") or "").strip()
    project = str(payload.get("project") or "").strip()
    path = str(payload.get("path") or "").strip()
    doing = getattr(translator_op, what)
    knobs = _knobs(payload)
    if what == "consistency":
        knobs.update(_check_knobs(payload))
    if what == "glossary":
        knobs.update(_glossary_knobs(payload))

    try:
        translator_op.verify(epub, project, knobs["scope"])
        # Ручки сверки — здесь же, а не в задаче: она начнётся в отдельном
        # потоке, и отказ из неё пришлось бы разбирать, открыв журнал.
        if what == "consistency":
            translator_op.verify_check(knobs["way"], knobs["deed"],
                                       knobs["sure"])
        if what == "glossary":
            translator_op.verify_merge(knobs["merge"])
    except translator_op.TranslatorError as exc:
        return jsonify(error=str(exc)), 400

    return _start(what, lambda note, stop: doing(
        epub, project, path=path, note=note, stop=stop, **knobs), payload)


def _scan_knobs(payload: dict) -> dict:
    """Ручки поиска остатков. Сервиса и модели у него нет — не ходит в сеть."""
    return {
        "scope": str(payload.get("scope") or translator_op.DONE).strip(),
        "suffix": str(payload.get("suffix") or "").strip(),
        "exceptions": str(payload.get("exceptions") or "").strip(),
        # Обратный флаг у переводчика, прямой вопрос у нас: галка «искать
        # смешанные слова» понятнее, чем «не искать».
        "mixed": payload.get("mixed", True) is not False,
        "pick": payload.get("pick") or "",
        "limit": payload.get("limit") or 0,
        "offset": payload.get("offset") or 0,
    }


@translator.post("/api/translator/scan")
def api_translator_scan():
    """Непереведённые куски в уже готовых главах.

    В сеть не ходит и ключей не тратит — читает файлы. Поэтому отвечаем
    сразу, как и плану: ждать тут нечего, а находки надо просмотреть
    прежде, чем пускать на них модель.
    """
    payload = request.json or {}
    try:
        said = translator_op.scan_untranslated(
            str(payload.get("epub") or "").strip(),
            str(payload.get("project") or "").strip(),
            path=str(payload.get("path") or "").strip(),
            **_scan_knobs(payload))
    except translator_op.TranslatorError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, **translator_op.short_scan(said))


@translator.post("/api/translator/fix")
def api_translator_fix():
    """Починить остатки моделью. Это уже ключи — значит задачей."""
    payload = request.json or {}
    epub = str(payload.get("epub") or "").strip()
    project = str(payload.get("project") or "").strip()
    path = str(payload.get("path") or "").strip()
    knobs = _knobs(payload)
    knobs["scope"] = str(payload.get("scope") or translator_op.DONE).strip()

    try:
        translator_op.verify(epub, project, knobs["scope"])
    except translator_op.TranslatorError as exc:
        return jsonify(error=str(exc)), 400

    return _start("untranslated-fix",
                  lambda note, stop: translator_op.fix_untranslated(
                      epub, project, path=path, note=note, stop=stop,
                      suffix=str(payload.get("suffix") or "").strip(),
                      exceptions=str(payload.get("exceptions") or "").strip(),
                      fix_prompt=str(payload.get("fixPrompt") or "").strip(),
                      batch=payload.get("batch") or 0,
                      context=payload.get("context") or 0,
                      dry=bool(payload.get("dry")), **knobs),
                  payload)


@translator.post("/api/translator/build")
def api_translator_build():
    """Собрать переведённый EPUB.

    Ни модели, ни ключей: команда складывает уже готовое. Поэтому и ручек
    у неё нет — только куда положить.
    """
    payload = request.json or {}
    epub = str(payload.get("epub") or "").strip()
    project = str(payload.get("project") or "").strip()
    path = str(payload.get("path") or "").strip()
    output = str(payload.get("output") or "").strip()

    try:
        translator_op.verify(epub, project)
    except translator_op.TranslatorError as exc:
        return jsonify(error=str(exc)), 400

    return _start("build-epub", lambda note, stop: translator_op.build_epub(
        epub, project, output, path=path, note=note, stop=stop,
        pick=payload.get("pick") or "", limit=payload.get("limit") or 0,
        offset=payload.get("offset") or 0), payload)


@translator.post("/api/translator/check")
def api_translator_check():
    """Проверка связи: зовём самую дешёвую команду и показываем ответ.

    В сеть она не ходит — отвечает по своим сохранённым настройкам, — так
    что проверка ничего не стоит ни по трафику, ни по квоте ключей.
    """
    payload = request.json or {}
    path = str(payload.get("path") or "").strip()
    try:
        said = translator_op.status(path)
    except translator_op.TranslatorError as exc:
        return jsonify(error=str(exc), **translator_op.state(path)), 400

    return jsonify(ok=True, **translator_op.short(said),
                   **translator_op.state(path))
