"""Пропуск Цидяня — кука `w_tsfp`.

Зачем это вообще нужно
======================

Цидянь сидит за защитой Tencent. На запрос без пропуска она отвечает не
страницей, а заглушкой на две сотни байт: кодом 202 «принято», внутри —
крохотный кусок разметки, который в браузере запускает `probev3.js`.
Скрипт считает пропуск, кладёт его в куку `w_tsfp` и перезагружает
страницу; со второго захода приходит уже рейтинг.

Ни заголовки, ни смена прокси тут не при чём: заглушка приходит и через
китайский адрес, и напрямую, и с самыми браузерными заголовками — она
приходит **всем, у кого нет куки**. Значит, либо запускать настоящий
браузер, либо посчитать пропуск самим. Здесь — второе.

Что внутри пропуска
===================

Внутри — обычный JSON, зашифрованный RC4 на постоянном ключе и
записанный в base64:

* `loadts` — когда страницу «начали грузить», миллисекунды эпохи;
* `timestamp` — когда «догрузили»: `loadts` плюс 0.3–1 секунда;
* `fingerprint` — отпечаток гостя, 32 шестнадцатеричных знака; браузер
  считает его один раз и носит с собой всё посещение;
* `abnormal` — метка подозрительности; у чистого гостя тридцать два нуля;
* `checksum` — подпись `md5(адрес + loadts + отпечаток)`. Она и привязывает
  пропуск к странице: чужой пропуск на другой адрес не годится.

Отсюда два следствия, из-за которых пропуск живёт отдельным предметом, а
не одной функцией. Первое: подпись считается **на каждый адрес заново**,
то есть на каждую страницу доски. Второе: отпечаток за одно посещение
меняться не должен — браузер его не перевыдумывает, и гость, у которого
отпечаток скачет от страницы к странице, выглядит как раз подозрительно.

Откуда правила
==============

Из `saudadez21/novel-downloader` (`plugins/sites/qidian/fetcher.py`) —
единственной из трёх найденных качалок Цидяня, которая обходит защиту без
браузера. `ma6254/FictionDown` на этом месте предлагает включить
chromedp или phantomjs, то есть поднимает настоящий браузер.

Чего мы не знаем наверняка: что именно защита кладёт в подпись — адрес
целиком или один путь. У качалки выше берётся адрес целиком; проверить
живьём отсюда нечем, сайт из песочницы недоступен. Поэтому пропуск умеет
обе формы, а разбор рейтинга при отказе пробует вторую (`other`).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import random
import time
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

#: Имя куки. Одно на весь сайт.
COOKIE = "w_tsfp"

#: Ключ шифра. Постоянная защиты, а не наша выдумка.
KEY = b"tg09It3*9h"

#: Метка подозрительности у гостя, к которому претензий нет.
CLEAN = "0" * 32

#: Сколько «грузилась» страница, миллисекунды. Скрипт защиты пишет сюда
#: настоящее время загрузки; мы разыгрываем правдоподобное — мгновенная
#: загрузка выглядела бы одинаково у всех наших запросов.
LOAD_MEAN, LOAD_SPREAD = 600, 150
LOAD_MIN, LOAD_MAX = 300, 1000


def _box(key: bytes) -> list[int]:
    """Начальная перестановка RC4 (KSA)."""
    box = list(range(256))
    j = 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) & 0xFF
        box[i], box[j] = box[j], box[i]
    return box


def cipher(data: bytes, key: bytes = KEY) -> bytes:
    """RC4. Шифрование и расшифровка — одно и то же действие."""
    box = _box(key)
    i = j = 0
    out = bytearray(len(data))
    for at, byte in enumerate(data):
        i = (i + 1) & 0xFF
        j = (j + box[i]) & 0xFF
        box[i], box[j] = box[j], box[i]
        out[at] = byte ^ box[(box[i] + box[j]) & 0xFF]
    return bytes(out)


def unpack(token: str) -> dict:
    """Что лежит внутри пропуска. Нужно для разбора полётов и проверок."""
    try:
        plain = cipher(base64.b64decode(str(token or "")))
        found = json.loads(plain.decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 — чужая кука может быть любой
        log.debug("Пропуск не разобрался: %s", exc)
        return {}
    return found if isinstance(found, dict) else {}


def _path_of(address: str) -> str:
    """Путь с запросом — адрес без протокола и хоста."""
    parts = urlsplit(str(address or ""))
    tail = parts.path or "/"
    return f"{tail}?{parts.query}" if parts.query else tail


class Pass:
    """Пропуск на одно посещение.

    Отпечаток и метка живут вместе с предметом, подпись пересчитывается
    на каждый адрес. Один предмет — один «гость»: заводить его надо на
    обход доски целиком, а не на страницу.
    """

    __slots__ = ("fingerprint", "abnormal", "whole")

    def __init__(self, fingerprint: str = "", abnormal: str = "",
                 whole: bool = True):
        #: Отпечаток гостя. Пустой — выдумываем свой, как это делает
        #: скрипт при первом заходе: у него тоже брать неоткуда.
        self.fingerprint = str(fingerprint or "") or _invented()
        self.abnormal = str(abnormal or "") or CLEAN
        #: Что кладём в подпись: адрес целиком или один путь.
        self.whole = bool(whole)

    def token(self, address: str) -> str:
        """Пропуск для этого адреса."""
        loadts = int(time.time() * 1000)
        spent = int(random.normalvariate(LOAD_MEAN, LOAD_SPREAD))
        spent = max(LOAD_MIN, min(LOAD_MAX, spent))

        signed = address if self.whole else _path_of(address)
        inside = {
            "loadts": loadts,
            "timestamp": loadts + spent,
            "fingerprint": self.fingerprint,
            "abnormal": self.abnormal,
            "checksum": hashlib.md5(
                f"{signed}{loadts}{self.fingerprint}".encode()).hexdigest(),
        }
        plain = json.dumps(inside, separators=(",", ":")).encode("utf-8")
        return base64.b64encode(cipher(plain)).decode("ascii")

    def cookies(self, address: str) -> dict:
        """Пропуск в виде куки — то, что подмешивается к запросу.

        Именно кукой, а не заголовком `Cookie`: заголовок, поставленный
        руками, не заменяет тот, что складывает curl из своей банки, а
        добавляется к нему второй строкой. В банке же лежит кука, которую
        Цидянь выдал вместе с заглушкой, и уходит она первой — то есть
        сайт читал бы ровно тот пропуск, которым нас не пустили.
        """
        return {COOKIE: self.token(address)}

    def learn(self, token: str) -> bool:
        """Взять отпечаток из куки, которую отдал сам сайт.

        Свой отпечаток он присылает не всегда, но если прислал — носить
        надо его: чужой гость, назвавшийся своим именем, сайту виднее.
        """
        inside = unpack(token)
        found = str(inside.get("fingerprint") or "")
        if not found:
            return False
        self.fingerprint = found
        self.abnormal = str(inside.get("abnormal") or "") or CLEAN
        return True

    def other(self) -> "Pass":
        """Тот же гость, другая форма подписи.

        Про форму мы гадаем (см. заголовок модуля), и это единственное
        место, где гадание видно наружу: не пустил один пропуск — стоит
        попробовать второй, прежде чем объявлять сайт закрытым.
        """
        return Pass(self.fingerprint, self.abnormal, not self.whole)


def _invented() -> str:
    """Отпечаток на пустом месте — 32 шестнадцатеричных знака."""
    return hashlib.md5(os.urandom(16)).hexdigest()
