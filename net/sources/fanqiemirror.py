"""Фанкью через стороннего посредника — второй способ качать.

Зачем он нужен. Веб-версия сайта отдаёт закрытые главы только тем, кто
вошёл, а таких глав у книги обычно подавляющее большинство: у книги на
тысячу двести глав открыто десять. Обычный источник честно пропускает их
как платные, и на выходе получается огрызок.

Чем он платит. Посредник — это чужая машина по голому адресу, без TLS.
Отсюда три следствия, и о них надо знать до того, как нажать кнопку:

* адрес может исчезнуть в любой день — поэтому он лежит в настройках
  (`mirror.url`), и заменить его можно, не трогая программу;
* и текст книги, и сам факт запроса идут через постороннего открытым
  текстом — что он с этим делает, проверить нельзя;
* содержимое приходит таким, каким его отдал посредник: подменить текст
  он может, а мы этого не заметим.

Поэтому способ выбирается руками и по умолчанию не включён. Поиск книги
и оглавление берутся с самого сайта, как и раньше, — посредник отвечает
только за текст главы.

Адрес взят из проекта `ying-ck/fanqienovel-downloader` (AGPL-3.0), см.
README и LICENSE.
"""

from __future__ import annotations

import logging
import re

from config import settings

from .base import Chapter, SourceBroken
from .fanqie import (PAID_MARKERS, ChapterEncrypted, FanqieSource, PaidChapter,
                     _check_readable, _clean, _json)

log = logging.getLogger(__name__)

#: Ответ посредника: успех помечается кодом 200 в теле, а не в HTTP.
OK_CODE = 200

#: Служебные вставки озвучки внутри текста главы. В книге им не место.
VOICE_MARK = re.compile(r"\{!--\s*PGC_VOICE:.*?--\}", re.S)

#: Блоки озвучки размечены своим классом — вырезаем вместе с содержимым.
VOICE_BLOCK = re.compile(
    r"(?is)<(div|span|section)[^>]*class=\"[^\"]*novel-fm-asr[^\"]*\"[^>]*>"
    r".*?</\1>")


class FanqieMirrorSource(FanqieSource):
    """Тот же Фанкью, но текст главы приходит от посредника."""

    key = "fanqie-mirror"
    name = "Fanqie (через посредника)"
    hint = ("То же, что и Fanqie, но текст глав идёт через сторонний "
            "сервер — так забираются закрытые главы. Сервер чужой и без "
            "шифрования: и книга, и запросы видны его владельцу. Адрес "
            "меняется в config.json, раздел mirror.")

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        item_id = chapter.post_id
        if not item_id:
            raise SourceBroken("У главы нет идентификатора Фанкью.")

        address = (settings.mirror.url or "").strip()
        if not address:
            raise SourceBroken(
                "Адрес посредника не задан: config.json, раздел mirror, "
                "поле url. Без него этот способ работать не может.")

        raw = client.get_text(f"{address}?item_id={item_id}")
        data = _json(raw, "текст главы от посредника")

        code = data.get("code")
        if code != OK_CODE:
            # Посредник отвечает своим кодом в теле, и его сообщение куда
            # полезнее нашего: там сказано, что именно у него не вышло.
            said = str(data.get("message") or "").strip()
            raise SourceBroken(
                f"Посредник отказал (код {code})"
                + (f": {said}" if said else "")
                + f". Адрес: {address}")

        content = str((data.get("data") or {}).get("content") or "")
        if not content or any(mark in content for mark in PAID_MARKERS):
            raise PaidChapter(f"Глава {chapter.number} закрыта и у посредника")

        text = _clean(_strip_voice(content))
        if not text.strip():
            raise SourceBroken(
                f"Посредник вернул главу {chapter.number} без текста. "
                f"Адрес: {address}")

        # Посредник отдаёт готовый текст, без подмены шрифтом. Проверяем
        # всё равно: если однажды начнёт отдавать зашифрованное, лучше
        # узнать об этом сразу, а не через сотню глав.
        _check_readable(text, chapter)
        return (chapter.title or f"Глава {chapter.number}"), text


def _strip_voice(html: str) -> str:
    """Убирает вставки озвучки: в книге они мусор."""
    return VOICE_MARK.sub("", VOICE_BLOCK.sub("", html))


__all__ = ["ChapterEncrypted", "FanqieMirrorSource", "PaidChapter"]
