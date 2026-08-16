"""Клиент языковой модели (часть 2 ТЗ NEUROSTRAZH).

Интернет не нужен: HTTP подменяется заглушкой, поэтому разыгрываются и
недействительный ключ, и отказ прокси, и пустой ответ модели.
"""

from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from llm import client as llm  # noqa: E402


class Response:
    """Ответ HTTP в том виде, в каком его читает клиент."""

    def __init__(self, body, status: int = 200):
        self._body = body
        self.status_code = status

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeHttp:
    """Подменённый HTTP-клиент: помнит запросы и отдаёт заготовку.

    Очередь ответов общая на все адреса: перебор прокси должен брать
    следующий ответ, а не начинать список заново.
    """

    def __init__(self, replies, proxy_url=None):
        self.replies = replies
        self.proxy_url = proxy_url
        self.calls = []
        self.connect_timeout = 1
        self.timeout = 1
        self.closed = False

    def _next(self, url):
        self.calls.append(url)
        reply = self.replies.pop(0) if self.replies else Response({})
        if isinstance(reply, Exception):
            raise reply
        return reply

    def get(self, url, params=None, headers=None):
        return self._next(url)

    def _session(self):
        return self

    def post(self, url, **kwargs):
        return self._next(url)

    def close(self):
        self.closed = True


class Proxy:
    def __init__(self, url, disabled=False):
        self.url = url
        self.disabled = disabled


class Pool:
    def __init__(self, proxies):
        self.proxies = proxies


def models_body(*names):
    return {"models": [
        {"name": f"models/{n}", "displayName": n,
         "supportedGenerationMethods": ["generateContent"],
         "inputTokenLimit": 1000000}
        for n in names
    ]}


def answer(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class LlmTestCase(unittest.TestCase):
    def setUp(self):
        self.saved = (settings.llm.api_key, settings.llm.model,
                      settings.llm.use_proxies)
        settings.llm.api_key = "AIzaTESTKEY0000secret"
        settings.llm.use_proxies = True
        self.addCleanup(self.restore)

    def restore(self):
        (settings.llm.api_key, settings.llm.model,
         settings.llm.use_proxies) = self.saved

    def client(self, replies, pool=None, **kwargs):
        """Клиент с подменённым HTTP. Очередь ответов общая на все адреса."""
        made = []
        queue = list(replies)

        def http(proxy_url):
            fake = FakeHttp(queue, proxy_url)
            made.append(fake)
            return fake

        instance = llm.LlmClient(pool=pool, **kwargs)
        instance._http = http
        instance.made = made
        return instance


class TestModelChoice(unittest.TestCase):
    """2.2: модель подбирается сама, самая дешёвая из линейки Flash."""

    def pick(self, *names):
        chosen = llm.cheapest([llm.Model(f"models/{n}") for n in names])
        return chosen.short if chosen else None

    def test_flash_beats_pro(self):
        self.assertEqual(
            self.pick("gemini-2.5-pro", "gemini-2.0-flash"), "gemini-2.0-flash")

    def test_lite_beats_plain_flash(self):
        """Flash-Lite дешевле обычного Flash, а главы разбирает так же."""
        self.assertEqual(
            self.pick("gemini-2.0-flash", "gemini-2.0-flash-lite"),
            "gemini-2.0-flash-lite")

    def test_fresh_version_wins_among_equals(self):
        self.assertEqual(
            self.pick("gemini-1.5-flash", "gemini-2.0-flash"), "gemini-2.0-flash")

    def test_preview_models_are_skipped(self):
        """Экспериментальные исчезают без предупреждения — прогон сорвётся."""
        self.assertEqual(
            self.pick("gemini-2.0-flash-exp", "gemini-2.0-flash"),
            "gemini-2.0-flash")

    def test_pro_only_is_still_usable(self):
        self.assertEqual(self.pick("gemini-2.5-pro"), "gemini-2.5-pro")

    def test_nothing_to_choose(self):
        self.assertIsNone(llm.cheapest([]))


class TestKeyMasking(LlmTestCase):
    """2.4: ключ не попадает ни в интерфейс, ни в логи."""

    def test_key_is_masked_in_text(self):
        masked = llm.mask("сбой с ключом AIzaTESTKEY0000secret тут")
        self.assertNotIn("AIzaTESTKEY0000secret", masked)
        self.assertIn("AIza", masked)

    def test_key_is_masked_in_url(self):
        masked = llm.mask("https://api/models?key=AIzaTESTKEY0000secret&x=1")
        self.assertNotIn("AIzaTESTKEY0000secret", masked)

    def test_error_from_api_is_masked(self):
        body = {"error": {"message": "bad key AIzaTESTKEY0000secret"}}
        client = self.client([Response(body, 500)])
        with self.assertRaises(llm.LlmError) as ctx:
            client.models()
        self.assertNotIn("AIzaTESTKEY0000secret", str(ctx.exception))


class TestCheck(LlmTestCase):
    """2.2: недействительный ключ виден сразу, а не при первом разборе."""

    def test_check_lists_models_and_suggests_one(self):
        client = self.client([Response(models_body(
            "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-lite"))])
        result = client.check()
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["models"]), 3)
        self.assertEqual(result["suggested"], "gemini-2.0-flash-lite")
        self.assertNotIn("AIzaTESTKEY0000secret", result["key"])

    def test_bad_key_is_reported_at_once(self):
        body = {"error": {"message": "API key not valid"}}
        client = self.client([Response(body, 400)])
        with self.assertRaises(llm.BadKey):
            client.check()

    def test_forbidden_is_a_key_problem(self):
        client = self.client([Response({}, 403)])
        with self.assertRaises(llm.BadKey):
            client.check()

    def test_missing_key_does_not_go_to_the_network(self):
        settings.llm.api_key = ""
        client = self.client([Response(models_body("gemini-2.0-flash"))])
        with self.assertRaises(llm.BadKey):
            client.models()
        self.assertEqual(client.made, [])

    def test_models_without_generation_are_ignored(self):
        body = {"models": [
            {"name": "models/embedding-001",
             "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/gemini-2.0-flash",
             "supportedGenerationMethods": ["generateContent"]},
        ]}
        client = self.client([Response(body)])
        self.assertEqual([m.short for m in client.models()], ["gemini-2.0-flash"])

    def test_no_usable_models_is_reported(self):
        body = {"models": [{"name": "models/embedding-001",
                            "supportedGenerationMethods": ["embedContent"]}]}
        client = self.client([Response(body)])
        with self.assertRaises(llm.LlmError):
            client.models()


class TestProxies(LlmTestCase):
    """2.3: запросы к модели идут через тот же прокси-слой, что и парсер."""

    def test_dead_proxy_is_followed_by_the_next(self):
        pool = Pool([Proxy("http://a"), Proxy("http://b")])
        client = self.client(
            [ConnectionError("не отвечает"),
             Response(models_body("gemini-2.0-flash"))],
            pool=pool)
        # Первый адрес отказал, запрос повторился на втором.
        self.assertEqual([m.short for m in client.models()], ["gemini-2.0-flash"])
        self.assertEqual([f.proxy_url for f in client.made],
                         ["http://a", "http://b"])

    def test_disabled_proxies_are_skipped(self):
        pool = Pool([Proxy("http://dead", disabled=True), Proxy("http://live")])
        client = self.client([Response(models_body("gemini-2.0-flash"))], pool=pool)
        client.models()
        self.assertEqual([f.proxy_url for f in client.made], ["http://live"])

    def test_without_proxies_goes_direct(self):
        client = self.client([Response(models_body("gemini-2.0-flash"))], pool=None)
        client.models()
        self.assertEqual([f.proxy_url for f in client.made], [None])

    def test_empty_pool_goes_direct(self):
        client = self.client([Response(models_body("gemini-2.0-flash"))],
                             pool=Pool([]))
        client.models()
        self.assertEqual([f.proxy_url for f in client.made], [None])

    def test_switch_can_be_turned_off(self):
        settings.llm.use_proxies = False
        pool = Pool([Proxy("http://a")])
        client = self.client([Response(models_body("gemini-2.0-flash"))], pool=pool)
        client.models()
        self.assertEqual([f.proxy_url for f in client.made], [None])

    def test_bad_key_does_not_walk_the_proxy_list(self):
        """Дело в ключе, а не в адресе: перебирать прокси бессмысленно."""
        pool = Pool([Proxy("http://a"), Proxy("http://b"), Proxy("http://c")])
        body = {"error": {"message": "API key not valid"}}
        client = self.client([Response(body, 400)], pool=pool)
        with self.assertRaises(llm.BadKey):
            client.models()
        self.assertEqual(len(client.made), 1)

    def test_all_proxies_dead_reports_clearly(self):
        pool = Pool([Proxy("http://a"), Proxy("http://b")])
        client = self.client(
            [ConnectionError("нет связи"), ConnectionError("нет связи")], pool=pool)
        with self.assertRaises(llm.LlmError):
            client.models()


class TestGenerate(LlmTestCase):
    def test_answer_is_returned(self):
        client = self.client([Response(answer('{"chapter": 209}'))],
                             model="gemini-2.0-flash")
        self.assertEqual(client.generate("вопрос"), '{"chapter": 209}')

    def test_model_name_is_normalised(self):
        client = self.client([Response(answer("{}"))], model="gemini-2.0-flash")
        client.generate("вопрос")
        self.assertIn("models/gemini-2.0-flash:generateContent", client.made[0].calls[0])

    def test_model_must_be_chosen(self):
        client = self.client([Response(answer("{}"))])
        settings.llm.model = ""
        with self.assertRaises(llm.LlmError):
            client.generate("вопрос")

    def test_empty_answer_is_an_error(self):
        client = self.client([Response({"candidates": []})], model="gemini-2.0-flash")
        with self.assertRaises(llm.LlmError):
            client.generate("вопрос")

    def test_refusal_is_explained(self):
        body = {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}
        client = self.client([Response(body)], model="gemini-2.0-flash")
        with self.assertRaises(llm.LlmError) as ctx:
            client.generate("вопрос")
        self.assertIn("SAFETY", str(ctx.exception))


class TestEstimate(unittest.TestCase):
    """2.5: расход показывается до запуска."""

    class Chapter:
        def __init__(self, size):
            self.size = size

    def test_counts_chapters_and_tokens(self):
        chapters = [self.Chapter(3500) for _ in range(10)]
        result = llm.estimate(chapters)
        self.assertEqual(result.chapters, 10)
        self.assertEqual(result.characters, 35000)
        self.assertEqual(result.tokens, 10000)
        self.assertEqual(result.to_send, 10)

    def test_cached_chapters_are_not_sent_again(self):
        chapters = [self.Chapter(3500) for _ in range(10)]
        self.assertEqual(llm.estimate(chapters, cached=7).to_send, 3)

    def test_all_cached_means_nothing_to_send(self):
        chapters = [self.Chapter(100) for _ in range(4)]
        self.assertEqual(llm.estimate(chapters, cached=9).to_send, 0)


class TestWebApi(LlmTestCase):
    def setUp(self):
        super().setUp()
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()

    def test_state_never_returns_the_raw_key(self):
        body = self.app.get("/api/llm/state").get_json()
        self.assertTrue(body["configured"])
        # Ключей теперь список, и целиком не отдаётся ни один.
        self.assertNotIn("AIzaTESTKEY0000secret", json.dumps(body))
        self.assertTrue(body["keys"])

    def test_check_without_a_key_fails_before_the_network(self):
        """Ключей нет вовсе — отвечаем сразу, никуда не ходим.

        Пустое поле ввода при этом ключей не отменяет: оно означает
        «проверь то, что в списке», а не «ключ не задан». Раньше на этом
        месте и получался отказ 400 при полном списке ключей.
        """
        settings.llm.api_key = ""
        saved = list(settings.llm.keys)
        no_save = settings.save
        settings.llm.keys = []
        settings.save = lambda *a, **k: None
        try:
            res = self.app.post("/api/llm/check", json={"key": ""})
            self.assertEqual(res.status_code, 400)
            body = res.get_json()
            self.assertIn("Ключей в списке нет", body["error"])
            # Причина должна быть словами, а не общим «Ключ не задан».
            self.assertTrue(body["need_keys"])
        finally:
            settings.llm.keys = saved
            settings.save = no_save

    def test_state_reports_the_proxy_switch(self):
        body = self.app.get("/api/llm/state").get_json()
        self.assertIn("use_proxies", body)
        self.assertEqual(body["provider"], "gemini")


if __name__ == "__main__":
    unittest.main(verbosity=2)
