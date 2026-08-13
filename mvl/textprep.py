"""Совместимость: обработка текста переехала в `core/text.py`.

Правило A0: обработка текста живёт в одном месте на весь проект. Здесь
остались только имена, под которыми к ней обращается прежний код —
собственной логики в этом файле больше нет.
"""

from __future__ import annotations

from core.text import *  # noqa: F401,F403
from core.text import (  # noqa: F401
    KIND_SCENE,
    KIND_SYSTEM,
    KIND_TEXT,
    SCENE_BLANK,
    SCENE_DASHES,
    SCENE_KEEP,
    SCENE_STARS,
    SCENE_STYLES,
    SCENE_TEXT,
    SCENE_BREAK,
    SCENE_CHARS,
    Block,
    PrepOptions,
    collapse_scenes,
    is_scene_break,
    is_system_message,
    normalize_title,
    prepare,
    strip_leading_title,
    to_text,
    trim_scenes,
)
