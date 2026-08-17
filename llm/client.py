"""Запросы к языковой модели.

Провайдер пока один — Gemini, — но адрес, ключ и модель берутся из
настроек, поэтому второй провайдер не потребует переписывания: достаточно
будет добавить класс с теми же тремя методами.

Ключ здесь только проезжает. В логи он не попадает никогда: всё, что
уходит в лог и в интерфейс, проходит через `mask`.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field

from config import settings

log = logging.getLogger(__name__)

#: Пауза вынесена отдельно, чтобы тесты не ждали по-настоящему.
sleep = time.sleep

#: Сколько знаков ключа показывать по краям: «AIza…4f2c».
VISIBLE = 4

#: Как зовётся в журнале запрос без прокси.
DIRECT = "напрямую"


class LlmError(Exception):
    """Запрос к модели не удался."""


class Truncated(LlmError):
    """Модель упёрлась в предел длины и оборвала ответ на середине.

    Отдельно от прочих: повторять тот же запрос бессмысленно — он снова
    не поместится. Помогает уменьшить кусок, а до тех пор — попытаться
    достроить то, что пришло.
    """

    def __init__(self, message: str, text: str = ""):
        super().__init__(message)
        #: Что успело прийти. Часто данные из этого куска ещё спасаются.
        self.text = text


class ModelBusy(LlmError):
    """Модель перегружена. Отвечает не прокси, а сам Gemini.

    Отдельно от всего прочего, потому что лечится иначе: адрес тут ни при
    чём — он честно доставил ответ, — и менять его бессмысленно, на новом
    будет ровно то же. Помогает только пауза.
    """

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class QuotaSpent(LlmError):
    """Квота ключа кончилась.

    Отдельно от `BadKey`: недействительный ключ не оживёт, а исчерпанный
    вернётся к утру, и работу надо не прекращать, а переключить.
    """

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class NoKeysLeft(LlmError):
    """Активных ключей не осталось. Работа встаёт, результат сохраняется."""


class BadKey(LlmError):
    """Ключ недействителен. Сказать об этом надо сразу, а не при разборе."""


def short(key) -> str:
    """Ключ в том виде, в каком его можно показать: начало и конец.

    Отдельно от `mask`: та вычищает ключи из чужого текста, а эта делает
    из ключа подпись. Раньше для показа звали `mask`, и на коротком ключе
    она возвращала его целиком — то есть показывала ключ как есть.
    """
    key = str(key or "")
    if not key:
        return ""
    if len(key) <= VISIBLE * 2:
        return "…"
    return f"{key[:VISIBLE]}…{key[-VISIBLE:]}"


def key_id(key) -> str:
    """Короткий признак ключа для ссылок из интерфейса.

    По маскированному виду ключи искать нельзя: у двух ключей одного
    провайдера начало совпадает, и правка ушла бы не туда. Сам ключ
    наружу не отдаём вовсе.
    """
    import hashlib

    key = str(key or "")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12] if key else ""


def _known_keys() -> list[str]:
    """Все ключи, которые надо вычищать из текста.

    Читаем настройки напрямую: `llm/keys.py` сам зовёт `mask`, и импорт
    в обратную сторону замкнул бы круг.
    """
    found = []
    for item in (getattr(settings.llm, "keys", None) or []):
        value = item.get("key") if isinstance(item, dict) else item
        if value:
            found.append(str(value))
    if settings.llm.api_key:
        found.append(settings.llm.api_key)
    return [k for k in found if len(k) >= 8]


def mask(text) -> str:
    """Прячет ключи в тексте. Через это проходит всё, что видит человек."""
    text = str(text)
    # Ключей теперь несколько, и вычищать надо каждый: в лог попадёт тот,
    # на котором сорвался запрос, а не тот, что записан в настройках.
    for key in _known_keys():
        text = text.replace(key, short(key))
    # Ключ может прийти и в адресе запроса — там его тоже быть не должно.
    return re.sub(r"([?&]key=)[^&\s]+", r"\1…", text)


@dataclass
class Model:
    """Модель, доступная по ключу."""

    name: str
    title: str = ""
    input_limit: int = 0
    output_limit: int = 0

    @property
    def short(self) -> str:
        """`models/gemini-2.0-flash` → `gemini-2.0-flash`."""
        return self.name.split("/")[-1]

    @property
    def flash(self) -> bool:
        """Линейка Flash — самая дешёвая, для разбора глав её достаточно."""
        return "flash" in self.short.lower()

    @property
    def lite(self) -> bool:
        """Ещё дешевле обычного Flash."""
        return "lite" in self.short.lower()

    def as_dict(self) -> dict:
        return {"name": self.name, "short": self.short, "title": self.title,
                "flash": self.flash, "input_limit": self.input_limit}


def cheapest(models: list[Model]) -> Model | None:
    """Самая дешёвая пригодная модель.

    Точных цен в ответе нет, поэтому идём по названию: линейка Flash
    дешевле Pro, а Flash-Lite дешевле обычного Flash. На пятистах главах
    разница существенная, а для разбора главы Flash достаточно.

    Экспериментальные и превью-модели пропускаем: они исчезают без
    предупреждения, и прогон на пятистах главах сорвётся посередине.
    """
    stable = [m for m in models if not _preview(m)] or list(models)
    flash = [m for m in stable if m.flash]
    if not flash:
        return stable[0] if stable else None

    lite = [m for m in flash if m.lite]
    pick = lite or flash
    # При прочих равных — свежая версия: у неё выше лимиты.
    return sorted(pick, key=lambda m: m.short, reverse=True)[0]


def _preview(model: Model) -> bool:
    name = model.short.lower()
    return any(mark in name for mark in ("exp", "preview", "-tuning", "latest"))


class LlmClient:
    """Клиент Gemini: список моделей, проверка ключа, генерация.

    Запросы идут через тот же прокси-слой, что и парсер: у ключа тоже
    бывают ограничения по стране, а список прокси уже проверен.
    """

    def __init__(self, key: str = "", model: str = "", pool=None,
                 base_url: str = "", timeout: int | None = None,
                 keys=None, on_event=None):
        #: Список ключей. Пусто — работаем одним, переданным явно: так
        #: проверяется только что введённый ключ, ещё не сохранённый.
        self.keys = keys
        self.current = None
        #: Куда сообщать о переключениях — журнал под прогресс-баром.
        self.on_event = on_event
        self.key = key or self._pick() or settings.llm_key
        self.model = model or settings.llm.model
        self.base_url = (base_url or settings.llm.base_url).rstrip("/")
        self.timeout = timeout or settings.llm.timeout
        self.pool = pool if settings.llm.use_proxies else None
        self._lock = threading.Lock()
        self._clients: dict[str | None, object] = {}

    # -------------------------------------------------------------- ключи

    def _pick(self) -> str:
        """Берёт активный ключ из списка. Без списка — пусто."""
        if self.keys is None:
            return ""
        self.current = self.keys.active()
        return self.current.key

    def _say(self, text: str) -> None:
        if self.on_event:
            self.on_event(text)

    def rotate(self, seconds: int | None = None) -> bool:
        """Помечает нынешний ключ исчерпанным и берёт следующий.

        Возвращает False, если брать больше нечего: тогда работа
        останавливается, но результат сохраняется.
        """
        if self.keys is None or self.current is None:
            return False

        spent = self.current
        self.keys.exhaust(spent, seconds)
        self._say(f"ключ «{spent.name or mask(spent.key)}» исчерпан")
        try:
            self.key = self._pick()
        except Exception:  # noqa: BLE001 — NoKeysLeft разбирает вызывающий
            self.current = None
            return False
        self._say(f"переключаюсь на «{self.current.name or mask(self.key)}»")
        return True

    # ------------------------------------------------------------- запросы

    def _http(self, proxy_url: str | None):
        """Клиент под конкретный прокси. Переиспользуется между запросами."""
        with self._lock:
            client = self._clients.get(proxy_url)
            if client is None:
                from mvl.client import Client

                client = Client(timeout=self.timeout, proxy_url=proxy_url,
                                max_attempts=1)
                self._clients[proxy_url] = client
            return client

    def _proxies(self) -> list[tuple[str | None, str]]:
        """Адреса для перебора парами «url, как звать в журнале».

        Имя для журнала берём у самого прокси (`label` — адрес без учётных
        данных): пароль в журнале не нужен никому.
        """
        if self.pool is None:
            # Галочка «использовать прокси для модели» снята — так и скажем.
            return [(None, DIRECT)]

        live = []
        for proxy in getattr(self.pool, "proxies", []):
            if getattr(proxy, "disabled", False):
                continue
            live.append((proxy.url, getattr(proxy, "label", "") or DIRECT))
        # Прокси не заданы — идём напрямую, это не ошибка.
        return live or [(None, DIRECT)]

    def _request(self, path: str, payload: dict | None = None) -> dict:
        """GET или POST к API, с перебором прокси при отказе.

        При отказе прокси берём следующий из списка и повторяем запрос —
        так же, как это делает парсер. Каждая попытка попадает в журнал:
        иначе на вопрос «а через прокси ли ушёл запрос» отвечать нечем.
        """
        if not self.key:
            raise BadKey("Ключ не задан. Введите его в настройках анализа.")

        url = f"{self.base_url}/{path.lstrip('/')}"
        last: Exception | None = None
        route = self._proxies()

        for number, (proxy_url, label) in enumerate(route, 1):
            self._say(f"запрос к модели {'напрямую' if label == DIRECT else 'через ' + label}")
            try:
                return self._with_patience(self._http(proxy_url), url, payload)
            except (BadKey, QuotaSpent, ModelBusy):
                # Дело в ключе или в самой модели, а не в адресе: перебирать
                # прокси бессмысленно, на следующем будет ровно то же.
                raise
            except Exception as exc:  # noqa: BLE001 — пробуем следующий адрес
                last = exc
                log.warning("Запрос к модели не прошёл: %s", mask(exc))
                left = len(route) - number
                self._say(f"{label} не ответил: {mask(exc)}"
                          + (f", пробую следующий адрес (осталось {left})"
                             if left else ""))

        # Наружу — причина словами. Внутренности curl человек всё равно не
        # чинит, а понять «сеть не пустила» или «ключ плохой» ему нужно.
        where = "напрямую" if len(route) == 1 and route[0][1] == DIRECT \
            else f"ни через один из {len(route)} адресов"
        raise LlmError(f"Не удалось связаться с Gemini {where}. "
                       f"Подробности: {mask(last or 'ответа нет')}")

    def _with_patience(self, http, url: str, payload: dict | None) -> dict:
        """Запрос с паузами на случай перегрузки модели (1.4 ТЗ).

        Перегрузка — не отказ адреса: прокси отработал и ответ доставил,
        просто у модели сейчас очередь. Раньше это принималось за молчание
        прокси, и программа переключалась на следующий — бессмысленно,
        потому что там будет то же самое. Помогает только подождать, и
        ждать надо на том же адресе.
        """
        for attempt in range(len(BUSY_WAITS) + 1):
            try:
                return self._once(http, url, payload)
            except ModelBusy as busy:
                if attempt >= len(BUSY_WAITS):
                    # Три повтора позади, очередь не рассосалась. Дальше
                    # ждать бессмысленно — пусть решает вызывающий.
                    raise
                # Сервер знает про свою очередь лучше нас.
                pause = busy.retry_after or BUSY_WAITS[attempt]
                self._say(f"модель перегружена, жду {pause} с "
                          f"(повтор {attempt + 1} из {len(BUSY_WAITS)})")
                log.info("Модель перегружена, пауза %s с", pause)
                sleep(pause)
        # Досюда не доходим: цикл либо вернёт ответ, либо бросит.
        raise ModelBusy("модель перегружена")

    def _once(self, http, url: str, payload: dict | None) -> dict:
        params = [("key", self.key)]
        if payload is None:
            response = http.get(url, params)
        else:
            response = self._post(http, url, params, payload)

        status = getattr(response, "status_code", 200)
        body = _json(response)
        if status == 400 and _is_key_error(body):
            raise BadKey("Ключ недействителен — проверьте его в настройках.")
        if status == 429 or _is_quota(body):
            raise QuotaSpent(mask(_error_text(body) or "квота ключа исчерпана"),
                             _retry_after(body, response))
        # Проверяем после квоты: «слишком часто» и «слишком много народу» —
        # разные беды. Первая лечится сменой ключа, вторая — паузой.
        if _is_busy(body, status):
            raise ModelBusy(mask(_error_text(body) or "модель перегружена"),
                            _retry_after(body, response))
        if status in (401, 403):
            raise BadKey("Ключ отклонён: нет доступа к API.")
        if status >= 400:
            raise LlmError(mask(_error_text(body) or f"HTTP {status}"))
        return body

    def _post(self, http, url: str, params, payload: dict):
        from mvl.client import encode_params

        session = http._session()
        return session.post(
            f"{url}?{encode_params(params)}",
            json=payload,
            timeout=(http.connect_timeout, http.timeout),
            headers={"Content-Type": "application/json"},
        )

    # -------------------------------------------------------------- модели

    def models(self) -> list[Model]:
        """Модели, доступные по ключу, — только пригодные для генерации."""
        body = self._request("models")
        found = []
        for item in body.get("models") or []:
            methods = item.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            found.append(Model(
                name=item.get("name", ""),
                title=item.get("displayName", ""),
                input_limit=int(item.get("inputTokenLimit") or 0),
                output_limit=int(item.get("outputTokenLimit") or 0),
            ))
        if not found:
            raise LlmError("По этому ключу нет моделей, умеющих генерацию текста.")
        return found

    def check(self) -> dict:
        """Проверяет ключ и подбирает модель. Зовётся сразу при вводе."""
        name = self.current.name if self.current and self.current.name else ""
        self._say(f"проверяю ключ {short(self.key)}"
                  + (f" («{name}»)" if name else ""))
        found = self.models()
        self._say(f"Gemini ответил: моделей с генерацией — {len(found)}")
        pick = cheapest(found)
        return {
            "ok": True,
            "models": [m.as_dict() for m in found],
            "suggested": pick.short if pick else "",
            "key": mask(self.key),
        }

    # ---------------------------------------------------------- генерация

    def generate(self, prompt: str, json_only: bool = True,
                 model: str = "", schema: dict | None = None) -> str:
        """Ответ модели на один запрос.

        `json_only` просит формат JSON на уровне API, а не в тексте
        промпта: так модель не добавляет пояснений вокруг ответа.
        """
        name = (model or self.model or "").strip()
        if not name:
            raise LlmError("Модель не выбрана.")
        if not name.startswith("models/"):
            name = f"models/{name}"

        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        if json_only:
            # Формат просим на уровне API, а не в тексте промпта: так
            # модель не добавит пояснений вокруг JSON. Предел ответа
            # задаём явно — на разбор главы двух тысяч токенов мало, и
            # ответ обрывался на середине (2.1 ТЗ).
            payload["generationConfig"] = {
                "responseMimeType": "application/json",
                "maxOutputTokens": settings.llm.max_output_tokens,
            }
            if schema:
                # Схема надёжнее любых просьб: с ней модель не сможет
                # вернуть ни текст вокруг, ни оборванную структуру.
                payload["generationConfig"]["responseSchema"] = schema

        path = f"{name}:generateContent"
        # Ключ мог кончиться прямо на этом запросе. Тогда переключаемся и
        # повторяем **тот же** запрос: потерянная глава нашлась бы нескоро.
        while True:
            try:
                body = self._request(path, payload)
            except QuotaSpent as spent:
                if not self.rotate(spent.retry_after):
                    raise NoKeysLeft(self.keys.why_stopped()
                                     if self.keys else str(spent)) from spent
                continue
            # Запрос удался — расход по этому ключу учтён.
            if self.keys is not None and self.current is not None:
                self.keys.spend(self.current)
                if self.current.state != "active":
                    # Лимит выбран до конца — следующий запрос пойдёт по
                    # другому ключу, не дожидаясь отказа сервера.
                    self.rotate()
            return _text_of(body)

    def close(self) -> None:
        with self._lock:
            for client in self._clients.values():
                try:
                    client.close()
                except Exception:  # noqa: BLE001 — закрытие не должно ронять прогон
                    pass
            self._clients.clear()


# ------------------------------------------------------------- разбор ответа


def _json(response) -> dict:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 — тело может быть не JSON вовсе
        return {}
    return body if isinstance(body, dict) else {}


def _error_text(body: dict) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "")
    return ""


#: Признаки исчерпанной квоты в ответе Gemini.
QUOTA_MARKERS = ("resource_exhausted", "quota", "rate limit", "too many requests")

#: Признаки перегрузки самой модели. Это ответ Gemini, а не молчание
#: прокси: адрес отработал и ответ доставил.
BUSY_MARKERS = ("high demand", "overloaded", "currently unavailable",
                "try again later", "model is overloaded",
                "unavailable", "перегруж")

#: Сколько ждать между попытками при перегрузке и сколько их всего.
#: Паузы растут: если модель занята, через секунду она занята и подавно.
BUSY_WAITS = (5, 15, 40)


def _is_busy(body: dict, status: int = 0) -> bool:
    """Перегружена ли модель — по её собственному ответу.

    Квоту проверяем раньше: «слишком часто» и «слишком много народу» —
    разные беды, и лечатся они по-разному.
    """
    if _is_quota(body):
        return False
    text = _error_text(body).lower()
    name = str((body.get("error") or {}).get("status") or "").lower()
    if name in ("unavailable", "resource_unavailable"):
        return True
    if status == 503:
        return True
    return any(marker in text for marker in BUSY_MARKERS)


def _is_quota(body: dict) -> bool:
    text = _error_text(body).lower()
    status = str((body.get("error") or {}).get("status") or "").lower()
    return status == "resource_exhausted" or any(m in text for m in QUOTA_MARKERS)


def _retry_after(body: dict, response=None) -> int | None:
    """Через сколько секунд пробовать снова — по словам сервера.

    Свой расчёт хуже: у разных ключей и планов сроки разные, а сервер
    знает точно.
    """
    headers = getattr(response, "headers", None) or {}
    for name in ("Retry-After", "retry-after"):
        if headers.get(name):
            try:
                return int(float(headers[name]))
            except (TypeError, ValueError):
                pass

    for item in (body.get("error") or {}).get("details") or []:
        delay = str((item or {}).get("retryDelay") or "")
        if delay.endswith("s"):
            try:
                return int(float(delay[:-1]))
            except ValueError:
                pass
    return None


def _is_key_error(body: dict) -> bool:
    text = _error_text(body).lower()
    return "api key" in text or "api_key" in text or "invalid key" in text


#: Чем Gemini объясняет обрыв ответа по длине.
CUT_REASONS = ("MAX_TOKENS", "LENGTH")


def _text_of(body: dict) -> str:
    """Текст ответа из структуры Gemini.

    Обрыв по длине распознаём здесь: модель честно пишет о нём в
    `finishReason`, и гадать по виду JSON незачем (2.1 ТЗ).
    """
    for candidate in body.get("candidates") or []:
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        why = str(candidate.get("finishReason") or "").upper()
        if why in CUT_REASONS:
            used = (body.get("usageMetadata") or {}).get("candidatesTokenCount")
            raise Truncated(
                f"ответ оборван по пределу длины"
                + (f", токенов пришло {used}" if used else ""), text)
        if text.strip():
            return text
    reason = (body.get("promptFeedback") or {}).get("blockReason")
    if reason:
        raise LlmError(f"Модель отказалась отвечать: {reason}")
    raise LlmError("Модель вернула пустой ответ.")


#: Грубая оценка: в русском тексте примерно столько символов на токен.
CHARS_PER_TOKEN = 3.5


@dataclass
class Estimate:
    """Оценка расхода до запуска: сколько глав, токенов и почём."""

    chapters: int = 0
    characters: int = 0
    tokens: int = 0
    cached: int = 0

    #: Сколько ключей есть сейчас — от этого зависит рекомендация.
    keys: int = 1

    @property
    def to_send(self) -> int:
        return max(0, self.chapters - self.cached)

    @property
    def average(self) -> int:
        """Средний размер главы в токенах."""
        return int(self.tokens / self.chapters) if self.chapters else 0

    @property
    def per_key(self) -> int:
        """Сколько запросов класть на один ключ.

        Делим работу поровну между ключами и добавляем запас: часть глав
        уходит на повтор из-за неразобранного ответа, и без запаса
        последний ключ кончился бы на последних главах.
        """
        keys = max(1, self.keys)
        share = -(-self.to_send // keys)          # деление с округлением вверх
        return int(share * (1 + RETRY_ALLOWANCE))

    def as_dict(self) -> dict:
        return {
            "chapters": self.chapters, "characters": self.characters,
            "tokens": self.tokens, "cached": self.cached,
            "to_send": self.to_send, "average": self.average,
            "keys": self.keys, "per_key": self.per_key,
            "free_daily": FREE_DAILY,
        }


#: Запас на повторы при рекомендации лимита.
RETRY_ALLOWANCE = 0.15

#: Суточный потолок бесплатной квоты Gemini Flash. Ориентир для подсказки,
#: а не закон: у платных планов он другой, поэтому поле остаётся правимым.
FREE_DAILY = 1500


def estimate(chapters, cached: int = 0, keys: int = 1) -> Estimate:
    """Сколько работы предстоит. Точных цен не называем — они меняются."""
    characters = sum(getattr(c, "size", 0) or len(getattr(c, "text", "")) for c in chapters)
    return Estimate(
        chapters=len(chapters),
        characters=characters,
        tokens=int(characters / CHARS_PER_TOKEN),
        cached=cached,
        keys=max(1, keys),
    )
