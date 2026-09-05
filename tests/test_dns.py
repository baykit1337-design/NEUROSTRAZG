"""Куда программа спрашивает имена сайтов.

Сети тут нет: проверяется, что настройка доезжает до сессии и что мусор
до неё не доезжает.

Зачем это вообще. DNS провайдера может не отдавать служебный хост
источника — сайт при этом жив, а программа до него не доходит вовсе, и
выглядит это как «сайт лёг». Поле «адрес DNS-сервера» тут не сделать:
такие адреса libcurl принимает только собранный с c-ares, а наш собран
без него — опция отвергается с ошибкой 48. Проверено, а не предположено.
DoH же — обычный HTTPS-запрос, и он проходит.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from mvl import client as client_mod  # noqa: E402
from webapp import app as web  # noqa: E402

CLOUDFLARE = "https://cloudflare-dns.com/dns-query"


class DnsTestCase(unittest.TestCase):
    """Настройка общая на программу, поэтому её обязательно возвращают."""

    def setUp(self):
        was = client_mod.DOH_URL
        self.addCleanup(setattr, client_mod, "DOH_URL", was)

        was_saved = settings.network.doh_url
        self.addCleanup(setattr, settings.network, "doh_url", was_saved)

        # Настоящий config.json тестам трогать нечего: в нём ключи.
        self.saved = []
        was_save = settings.save
        settings.save = lambda *a, **kw: self.saved.append(
            settings.network.doh_url)
        self.addCleanup(setattr, settings, "save", was_save)

        web.app.config["TESTING"] = True
        self.client = web.app.test_client()


class TestWhatCountsAsAnAddress(DnsTestCase):

    def test_an_https_address_is_taken(self):
        self.assertEqual(client_mod.use_doh(CLOUDFLARE), CLOUDFLARE)

    def test_a_bare_ip_is_not_an_address_here(self):
        """`1.1.1.1` — то, что человек напишет первым делом, и принять
        это молча значило бы обещать работу, которой не будет: libcurl
        такую опцию отвергает."""
        self.assertEqual(client_mod.use_doh("1.1.1.1"), "")

    def test_plain_http_is_refused_too(self):
        """Имена по открытому каналу видит ровно тот, кто их сейчас и не
        отдаёт."""
        self.assertEqual(client_mod.use_doh("http://dns.example/q"), "")

    def test_empty_means_ask_the_system(self):
        client_mod.use_doh(CLOUDFLARE)
        self.assertEqual(client_mod.use_doh(""), "")


class TestTheSettingReachesTheSession(DnsTestCase):
    """Настройка, до сессии не доехавшая, — это настройка, которой нет."""

    def test_the_session_asks_where_it_was_told(self):
        client_mod.use_doh(CLOUDFLARE)
        session, kind = client_mod._make_session()
        if kind != "curl_cffi":
            self.skipTest("без curl_cffi спрашивать некуда")

        self.assertEqual(session.doh_url, CLOUDFLARE)

    def test_without_the_setting_the_session_asks_the_system(self):
        client_mod.use_doh("")
        session, kind = client_mod._make_session()
        if kind != "curl_cffi":
            self.skipTest("без curl_cffi спрашивать некуда")

        self.assertFalse(session.doh_url)

    def test_it_reaches_the_session_that_goes_through_a_proxy_too(self):
        """Через посредника имя разрешает он сам, но клиент один на оба
        пути, и разводить их значило бы завести вторую настройку."""
        client_mod.use_doh(CLOUDFLARE)
        session, kind = client_mod._make_session("http://1.2.3.4:8080")
        if kind != "curl_cffi":
            self.skipTest("без curl_cffi спрашивать некуда")

        self.assertEqual(session.doh_url, CLOUDFLARE)


class TestTheKnobOnThePage(DnsTestCase):

    def test_it_says_what_is_set_now_and_what_can_be_chosen(self):
        client_mod.use_doh(CLOUDFLARE)
        said = self.client.get("/api/dns").get_json()

        self.assertEqual(said["url"], CLOUDFLARE)
        self.assertIn(CLOUDFLARE, [one["url"] for one in said["choices"]])

    def test_the_system_way_is_among_the_choices(self):
        """Иначе передумать нельзя: выбрал раз — и обратно никак."""
        said = self.client.get("/api/dns").get_json()

        self.assertIn("", [one["url"] for one in said["choices"]])

    def test_choosing_one_applies_it_at_once(self):
        answer = self.client.post("/api/dns", json={"url": CLOUDFLARE})

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(client_mod.DOH_URL, CLOUDFLARE)

    def test_choosing_one_remembers_it(self):
        """Иначе после перезапуска человек ищет настройку заново — а
        ищет он её тогда, когда уже ничего не качается."""
        self.client.post("/api/dns", json={"url": CLOUDFLARE})

        self.assertEqual(settings.network.doh_url, CLOUDFLARE)
        self.assertEqual(self.saved, [CLOUDFLARE])

    def test_a_bare_ip_is_refused_with_words(self):
        """Молчаливый отказ хуже отказа: человек уверен, что настроил."""
        answer = self.client.post("/api/dns", json={"url": "1.1.1.1"})

        self.assertEqual(answer.status_code, 400)
        self.assertIn("https://", answer.get_json()["error"])

    def test_a_refused_address_changes_nothing(self):
        client_mod.use_doh(CLOUDFLARE)
        self.client.post("/api/dns", json={"url": "1.1.1.1"})

        self.assertEqual(client_mod.DOH_URL, CLOUDFLARE)
        self.assertEqual(self.saved, [])

    def test_going_back_to_the_system_way_works(self):
        client_mod.use_doh(CLOUDFLARE)
        answer = self.client.post("/api/dns", json={"url": ""})

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(client_mod.DOH_URL, "")


if __name__ == "__main__":
    unittest.main()
