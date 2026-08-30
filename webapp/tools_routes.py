"""Маршруты вкладки «Инструменты»: журнал, обновление, отчёт, трафик.

Первая вкладка, вынесенная из `webapp/app.py`. Он дорос до пяти с
половиной тысяч строк и ста сорока маршрутов — править вслепую стало
опасно, а резать всё разом ещё опаснее: слишком многое держится на общих
помощниках. Поэтому по одной вкладке за раз, начиная с той, что почти ни
с чем не связана.

Что берёт отсюда наружу: `Client` и `HttpError` для похода на GitHub,
задачу с её запуском и `_progress` из `app.py`. Обратной связи нет:
`app.py` про этот файл знает ровно одно — что его надо подключить.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import settings
from core import traffic
from mvl.client import Client, HttpError
from ops import history as history_op
from ops import logbook
from ops import update as update_op
from webapp.jobs import Job, progress_of, start_job

log = logging.getLogger(__name__)

tools = Blueprint("tools", __name__)


@tools.get("/api/traffic")
def api_traffic():
    """Сколько скачано за запуск и за месяц.

    При платном пакете это первое, что хочется видеть. Счёт ведётся в
    самом низу, в клиенте: через него проходят и главы, и рейтинги, и
    перевод, и обновление.
    """
    return jsonify(**traffic.totals())


@tools.get("/api/history/state")
def api_history_state():
    """Что делалось и что можно вернуть."""
    return jsonify(**history_op.state())


@tools.post("/api/history/restore")
def api_history_restore():
    """Возвращает файлы из копии на место."""
    payload = request.json or {}
    backup = (payload.get("backup") or "").strip()
    target = (payload.get("target") or "").strip()
    if not backup or not target:
        return jsonify(error="Нужны и копия, и папка, куда возвращать"), 400
    try:
        count = history_op.restore(Path(backup), Path(target))
    except history_op.RestoreError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(restored=count, **history_op.state())


@tools.post("/api/history/undo")
def api_history_undo():
    """Вернуть как было — последнюю операцию, у которой есть копия.

    То же самое, что «Восстановить» в журнале, но без похода туда:
    страховка, о которой узнаёшь, только специально полезши на четвёртую
    вкладку, спасает не тогда, когда нужна.
    """
    found = history_op.last_undo()
    if found is None:
        return jsonify(error="Возвращать нечего: последняя операция не "
                             "оставила ни добавленных файлов, ни копии — "
                             "или папку уже унесли."), 400
    try:
        count = history_op.undo(found)
    except history_op.RestoreError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(restored=count, undone=found.as_dict(),
                   **history_op.state())


@tools.get("/api/update/look")
def api_update_look():
    """Вышло ли новое. Один запрос примерно на триста байт.

    Проверка отделена от загрузки нарочно: трафик у человека может быть
    на счету, и решать, тратить ли его на сами файлы, должен он — увидев
    сперва, сколько их и насколько они изменились.
    """
    client = Client()
    try:
        return jsonify(**update_op.look(client).as_dict())
    except HttpError as exc:
        where = f"{settings.update.owner}/{settings.update.repo}"
        return jsonify(error=f"GitHub ответил {exc.status} на запрос о "
                             f"{where}. Проверьте, что репозиторий существует "
                             "и открыт."), 400
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось спросить об обновлении: {exc}"), 400
    finally:
        client.close()


@tools.post("/api/update/apply")
def api_update_apply():
    """Забирает изменившиеся файлы. Только по нажатию, не сама."""
    client = Client()
    try:
        plan = update_op.look(client)
    except (HttpError, OSError, ValueError) as exc:
        client.close()
        return jsonify(error=f"Не удалось получить список изменений: {exc}"), 400

    if plan.trouble:
        client.close()
        return jsonify(error=plan.trouble), 400
    if plan.fresh or not plan.changes:
        client.close()
        return jsonify(error="Обновлять нечего: стоит последняя версия"), 400

    total = len(plan.changes)
    job = Job(id=uuid.uuid4().hex[:12], kind="update",
              meta={"files": total, "revision": plan.there})
    job.progress = {"stage": "update", "message": f"Забираем {total} файлов…",
                    "done": 0, "total": total}

    def work(job: Job):
        try:
            done = update_op.apply(client, plan, progress_of(job, "Файл"))
        finally:
            client.close()
        job.report = done.as_dict()
        if done.rolled_back:
            # Обновление, после которого программа не запускается, хуже
            # отсутствия обновления. Прежние файлы уже вернулись на место.
            job.progress.update(
                stage="done", done=total, total=total,
                message=("Обновление отменено: с новыми файлами программа "
                         f"не запускается ({done.rolled_back}). Прежняя "
                         "версия возвращена на место."))
            return
        job.progress.update(
            stage="done", done=total, total=total,
            message=(f"Готово. Обновлено {done.written}"
                     + (f", удалено {done.removed}" if done.removed else "")
                     + (f", не вышло {len(done.failures)}"
                        if done.failures else "")
                     + ". Перезапустите программу."
                     + (" Изменился список зависимостей — выполните "
                        "pip install -r requirements.txt."
                        if done.needs_install else "")))

    return jsonify(job=start_job(job, work).snapshot())


@tools.post("/api/update/undo")
def api_update_undo():
    """Вернуться к версии, которая стояла до обновления.

    При медленном канале это единственный быстрый выход из неудачного
    обновления: качать заново нечего, прежние файлы лежат в корзине.
    """
    saved = update_op.last_backup()
    if not saved:
        return jsonify(error="Возвращаться некуда: копии перед обновлением "
                             "нет — либо обновления не было, либо копию уже "
                             "вытеснили из корзины."), 400
    count = update_op.undo(saved)
    if not count:
        return jsonify(error=f"Из копии {saved} ничего не вернулось"), 400
    # Версию забываем: на диске лежит прежняя, и следующая проверка
    # должна снова предложить обновиться.
    update_op.remember("")
    history_op.add("возврат обновления", source=saved,
                   output=str(update_op.ROOT), files=count)
    return jsonify(restored=count, backup=saved,
                   message=(f"Возвращено файлов: {count}. "
                            "Перезапустите программу."))


@tools.post("/api/report")
def api_report():
    """Готовый отчёт о проблеме: версия, система, хвост журнала.

    Одна кнопка вместо переписки «пришлите строку из консоли» — тем
    более что консоли у человека может не быть вовсе: на Windows окно
    закрывается вместе с программой.

    Ключи и пароли вычищаются здесь, а не «не попадают в журнал сами»:
    отчёт уходит наружу, и полагаться на «сами» тут нельзя.
    """
    payload = request.json or {}
    return jsonify(
        text=logbook.report(str(payload.get("what") or "")),
        folder=str(logbook.LOG_DIR),
        file=str(logbook.LOG_FILE),
        kept=logbook.LOG_FILE.is_file(),
    )
