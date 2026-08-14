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

#: Сколько знаков ключа показывать по краям: «AIza…4f2c».
VISIBLE = 4


class LlmError(Exception):
    """Запрос к модели не удался."""


class BadKey(LlmError):
    """Ключ недействителен. Сказать об этом надо сразу, а не при разборе."""


def mask(text) -> str:
    """Прячет ключи в тексте. Через это проходит всё, что видит человек."""
    text = str(text)
    key = settings.llm_key
    if key and len(key) > VISIBLE * 2:
        text = text.replace(key, f"{key[:VISIBLE]}…{key[-VISIBLE:]}")
    elif key:
        text = text.replace(key, "…")
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
                 base_url: str = "", timeout: int | None = None):
        self.key = key or settings.llm_key
        self.model = model or settings.llm.model
        self.base_url = (base_url or settings.llm.base_url).rstrip("/")
        self.timeout = timeout or settings.llm.timeout
        self.pool = pool if settings.llm.use_proxies else None
        self._lock = threading.Lock()
        self._clients: dict[str | None, object] = {}

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

    def _proxies(self) -> list:
        """Адреса для перебора. Пустой список — идём напрямую."""
        if self.pool is None:
            return [None]
        live = [p.url for p in getattr(self.pool, "proxies", []) if not p.disabled]
        # Прокси не заданы — идём напрямую, это не ошибка.
        return live or [None]

    def _request(self, path: str, payload: dict | None = None) -> dict:
        """GET или POST к API, с перебором прокси при отказе.

        При отказе прокси берём следующий из списка и повторяем запрос —
        так же, как это делает парсер.
        """
        if not self.key:
            raise BadKey("Ключ не задан. Введите его в настройках анализа.")

        url = f"{self.base_url}/{path.lstrip('/')}"
        last: Exception | None = None

        for proxy_url in self._proxies():
            try:
                return self._once(self._http(proxy_url), url, payload)
            except BadKey:
                # Дело в ключе, а не в адресе: перебирать прокси бессмысленно.
                raise
            except Exception as exc:  # noqa: BLE001 — пробуем следующий адрес
                last = exc
                log.warning("Запрос к модели не прошёл: %s", mask(exc))

        raise LlmError(mask(last or "не удалось связаться с моделью"))

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
        found = self.models()
        pick = cheapest(found)
        return {
            "ok": True,
            "models": [m.as_dict() for m in found],
            "suggested": pick.short if pick else "",
            "key": mask(self.key),
        }

    # ---------------------------------------------------------- генерация

    def generate(self, prompt: str, json_only: bool = True,
                 model: str = "") -> str:
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
            payload["generationConfig"] = {"responseMimeType": "application/json"}

        body = self._request(f"{name}:generateContent", payload)
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


def _is_key_error(body: dict) -> bool:
    text = _error_text(body).lower()
    return "api key" in text or "api_key" in text or "invalid key" in text


def _text_of(body: dict) -> str:
    """Текст ответа из структуры Gemini."""
    for candidate in body.get("candidates") or []:
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
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

    @property
    def to_send(self) -> int:
        return max(0, self.chapters - self.cached)

    def as_dict(self) -> dict:
        return {
            "chapters": self.chapters, "characters": self.characters,
            "tokens": self.tokens, "cached": self.cached,
            "to_send": self.to_send,
        }


def estimate(chapters, cached: int = 0) -> Estimate:
    """Сколько работы предстоит. Точных цен не называем — они меняются."""
    characters = sum(getattr(c, "size", 0) or len(getattr(c, "text", "")) for c in chapters)
    return Estimate(
        chapters=len(chapters),
        characters=characters,
        tokens=int(characters / CHARS_PER_TOKEN),
        cached=cached,
    )
