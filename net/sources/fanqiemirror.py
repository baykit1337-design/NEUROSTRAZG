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
import threading

from config import settings
from mvl.client import Client, HttpError, NetworkError
from mvl.proxies import scrub

from .base import Chapter, SourceBroken, SourceUnreachable
from .fanqie import (PAID_MARKERS, ChapterEncrypted, FanqieSource, PaidChapter,
                     _check_readable, _clean, _json)

log = logging.getLogger(__name__)

#: Успех посредник помечает кодом в теле ответа, а не в HTTP. Соглашения
#: у разных серверов разные: один пишет 200, другой — 0. Оба означают
#: «держи главу», и различать их незачем.
OK_CODES = frozenset({0, 200})

#: Известные посредники — встроенный список. Настройки его дополняют, а
#: не заменяют: сохранённый config.json со старым адресом иначе намертво
#: отрезал бы от новых. Ровно это и случилось, когда первый адрес умер.
KNOWN = (
    "http://yuefanqie.jingluo.love/content",
    "http://101.35.133.34:5000/api/raw_full",
)

#: Проверенные молчащие. Не выбрасываем — вдруг вернутся, — но пробуем
#: последними: иначе каждый запуск начинается с ожидания их таймаута, а
#: у того, кто однажды сохранил такой адрес в настройках, — ещё и на
#: каждой главе.
RETIRED = frozenset({"http://101.35.133.34:5000/api/raw_full"})

class _Refused(Exception):
    """Этот посредник главу не дал. Внутреннее: наружу не выходит.

    Отделено от поломки разбора: отказ одного сервера — повод пойти к
    следующему, а не бросить книгу.
    """


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

    def __init__(self):
        #: Свой клиент к посреднику. Заводится по первой главе и живёт до
        #: конца прогона: сессия переиспользуется, как и у витрины.
        self._direct: Client | None = None
        #: Адрес, который уже отвечал. Дальше начинаем с него, чтобы не
        #: перебирать молчащие на каждой главе.
        self._working: str = ""
        self._lock = threading.Lock()

    def reader(self, client):
        """Кто идёт к посреднику — свой прямой клиент или клиент витрины.

        Прокси в пуле нужны, чтобы попасть на китайский сайт. Посредник
        сайту не родственник: это сторонний сервер на нестандартном
        порту, и такие запросы прокси не пропускал — отвечал 502. Клиент
        видел сетевой сбой и повторял с нарастающей паузой, отсюда и
        «запросы каждую секунду, а глав ноль».

        Настройка `mirror.via_proxy` оставлена на случай, когда сам
        посредник напрямую не отвечает.
        """
        if settings.mirror.via_proxy:
            return client
        with self._lock:
            if self._direct is None:
                # Сроки с экрана важнее наших: человек их для того и
                # выставлял. Нет их — берём из настроек посредника.
                waits = {"timeout": max(1, int(settings.mirror.timeout or 30))}
                waits.update(self.timeouts or {})
                self._direct = Client(
                    max_attempts=max(1, int(settings.mirror.retries or 1)),
                    # Иначе «Остановить» ждёт лесенку повторов: клиент
                    # этот наш, и о нажатии кнопки ему сказать некому.
                    cancel=self.cancel,
                    **waits,
                )
            return self._direct

    def close(self) -> None:
        """Закрывает свой клиент. Качалка зовёт это в конце прогона."""
        with self._lock:
            if self._direct is not None:
                self._direct.close()
                self._direct = None

    def addresses(self) -> list[str]:
        """Адреса посредников по порядку: сперва тот, что уже ответил.

        Один адрес — одна точка отказа: когда он замолчал, способ
        выключился целиком. Поэтому их список, и найденный рабочий
        держится первым до конца прогона, чтобы не перебирать мёртвые на
        каждой главе.
        """
        rows = [settings.mirror.url, *(settings.mirror.spare or []), *KNOWN]
        seen, order = set(), []
        for row in rows:
            row = str(row or "").strip()
            if row and row not in seen:
                seen.add(row)
                order.append(row)

        # Молчащие — в конец. Сохранённый со старых времён мёртвый адрес
        # иначе съедал бы свой таймаут перед каждой главой.
        order.sort(key=lambda row: row in RETIRED)

        with self._lock:
            working = self._working
        if working in seen:
            order.remove(working)
            order.insert(0, working)
        return order

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        item_id = chapter.post_id
        if not item_id:
            raise SourceBroken("У главы нет идентификатора Фанкью.")

        addresses = self.addresses()
        if not addresses:
            raise SourceBroken(
                "Адрес посредника не задан: config.json, раздел mirror, "
                "поле url. Без него этот способ работать не может.")

        # Через кого пошли — важно для разбора отказа. Свой прямой клиент
        # прокси не использует, и его молчание к пулу отношения не имеет.
        reader = self.reader(client)
        direct = reader is not client
        troubles = []

        for address in addresses:
            try:
                raw = reader.get_text(f"{address}?item_id={item_id}")
            except (NetworkError, HttpError) as exc:
                if not direct:
                    # Шли через прокси — пусть с ним и разбирается качалка.
                    raise
                troubles.append(f"{address} — {scrub(str(exc))}")
                continue

            try:
                answer = self._read(raw, chapter, address)
            except _Refused as refusal:
                # Посредник ответил отказом: у него этой главы нет, а у
                # соседнего может быть. Это не повод бросать книгу.
                troubles.append(f"{address} — {refusal}")
                continue

            with self._lock:
                self._working = address
            return answer

        raise SourceUnreachable(
            "Ни один посредник не ответил: " + "; ".join(troubles)
            + ". Это чужие серверы — они могут исчезнуть совсем. Список "
            "адресов лежит в config.json, раздел mirror (поля url и "
            "spare); там же можно включить via_proxy, чтобы идти к ним "
            "через прокси. Обычный способ «Fanqie» работает и без "
            "посредника, но закрытые главы пропускает.")

    def _read(self, raw: str, chapter: Chapter, address: str):
        """Разбирает ответ посредника. `_Refused` — пробуем следующего.

        Платная и нерасшифрованная главы — не отказ посредника, а ответ
        про саму главу: соседний отдаст ровно то же самое, и перебирать
        их незачем.
        """
        data = _json(raw, "текст главы от посредника")

        if data.get("code") not in OK_CODES:
            # Посредник отвечает своим кодом в теле, и его сообщение куда
            # полезнее нашего: там сказано, что именно у него не вышло.
            # Поэтому несём его наверх, а не пишем «отказал».
            said = str(data.get("message") or "").strip()
            raise _Refused(f"код {data.get('code')}"
                           + (f": {said}" if said else ""))

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


__all__ = ["ChapterEncrypted", "FanqieMirrorSource", "PaidChapter",
           "SourceUnreachable"]
