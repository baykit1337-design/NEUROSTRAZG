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

from flask import Blueprint, jsonify, request

from config import settings
from ops import translator as translator_op

log = logging.getLogger(__name__)

translator = Blueprint("translator", __name__)


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
