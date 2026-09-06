"""Ожидание должно быть видно, а оглавление — иметь запасной выход.

Три книги встали на «Собираем оглавление» и шесть минут не двигались
ничем: ни строкой, ни цифрой, ни записью в журнале. Человек прочитал это
единственным возможным способом — «стоит всё, не качается» — и закрыл
программу.

Внутри в это время шло ровно то, что и задумано: клиент повторял запрос.
Три попытки со сроком ожидания в две минуты и лесенкой пауз — это шесть с
лишним минут. Молчала же программа потому, что повторы писались в `debug`,
а на экран не уходило ничего.

Второе: у глав запасной выход был всегда — не ответил адрес, берём
следующий. У оглавления не было ничего, и книга вставала на нём намертво.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import api  # noqa: E402
from mvl import client as client_mod  # noqa: E402
from mvl import downloader as downloader_mod  # noqa: E402
from mvl.client import Client, HttpError, NetworkError  # noqa: E402
from mvl.downloader import Downloader  # noqa: E402


class Silent(Exception):
    """Сеть молчит — то, что клиент повторяет."""


class Source:
    """Источник, у которого оглавление даётся не с первого клиента.

    `good` — клиенты, которым оглавление отдадут. Пусто — отдадут всем.
    """

    key = "fake"
    name = "Подставной"
    needs_proxy = False
    cancel = None
    timeouts: dict = {}

    def __init__(self, total=6, good=None):
        self.total = total
        self.good = good
        #: Через какие прокси спрашивали оглавление, по порядку.
        self.asked: list = []

    def toc(self, client, novel, first=1, last=None, on_progress=None):
        self.asked.append(getattr(client, "proxy_url", None))
        if self.good is not None and client.proxy_url not in self.good:
            raise NetworkError("сайт не ответил")
        rows = [api.Chapter(number=n, post_id=str(n))
                for n in range(first, (last or self.total) + 1)]
        if on_progress:
            on_progress(len(rows), len(rows))
        return api.Toc(chapters=rows, missing=[])

    def chapter(self, client, chapter):
        return f"Глава {chapter.number}", "Текст главы."


class Pool:
    """Список прокси — ровно тот, что нужен запасному заходу."""

    def __init__(self, urls):
        self.proxies = [self.Proxy(url) for url in urls]
        self.switches: list = []
        self.usable_count = len(self.proxies)

    class Proxy:
        def __init__(self, url):
            self.url = url
            self.label = url.split("//")[-1]
            self.disabled = False
            self.alive = True

    def current(self):
        return self.proxies[0]

    def switch(self, reason):
        self.switches.append(reason)
        return self.proxies[0]


class Base(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, client_mod, "SITE_PAUSE_RANGE",
                        client_mod.SITE_PAUSE_RANGE)
        client_mod.SITE_PAUSE_RANGE = (0, 0)
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def novel(self, total=6):
        return api.Novel(code=1, name="Книга", slug="k", total_chapters=total)

    def loader(self, source, pool=None, **more):
        said = []
        loader = Downloader(source=source, threads=1, probe=False, pool=pool,
                            on_progress=lambda p: said.append(
                                (p.stage, p.message or "")),
                            **more)
        return loader, said


class TestTheWaitIsVisible(Base):
    """Молчащая программа читается как зависшая. Так и вышло."""

    def waits(self):
        """Клиент, который дважды не дозвонился и на третий раз ответил."""
        said = []
        client = Client(max_attempts=3, on_retry=said.append)
        return client, said

    def test_the_client_says_it_is_waiting(self):
        client, said = self.waits()
        tries = []

        def sending(*args, **rest):
            tries.append(1)
            if len(tries) < 3:
                raise Silent("connection reset")
            return client_mod._UrllibResponse(200, b'ok')

        client._session = lambda: type("S", (), {"get": sending})()
        client._wait = lambda seconds: False

        client.get("https://x/y")
        self.assertEqual(len(said), 2)

    def test_it_says_how_long_and_which_try(self):
        """«Ждём» без числа — то же молчание, только вежливое: непонятно,
        сколько ещё стоять и сколько попыток осталось."""
        client, said = self.waits()
        client._session = lambda: type("S", (), {
            "get": lambda *a, **k: (_ for _ in ()).throw(Silent("сброс"))})()
        client._wait = lambda seconds: False

        with self.assertRaises(NetworkError):
            client.get("https://x/y")
        self.assertRegex(said[0], r"\d")
        self.assertIn("3", said[0])

    def test_a_request_that_goes_through_says_nothing(self):
        """Строка про повтор на каждом успешном запросе — это шум, за
        которым настоящую беду не увидеть."""
        client, said = self.waits()
        client._session = lambda: type("S", (), {
            "get": lambda *a, **k: client_mod._UrllibResponse(200, b'ok')})()
        client.get("https://x/y")
        self.assertEqual(said, [])

    def test_a_broken_listener_does_not_break_the_request(self):
        """Весть о повторе — дело десятое. Ронять из-за неё сам запрос
        значило бы менять беду на беду похуже."""
        def blows(text):
            raise RuntimeError("некому слушать")

        client = Client(max_attempts=2, on_retry=blows)
        tries = []

        def sending(*args, **rest):
            tries.append(1)
            if len(tries) < 2:
                raise Silent("сброс")
            return client_mod._UrllibResponse(200, b'ok')

        client._session = lambda: type("S", (), {"get": sending})()
        client._wait = lambda seconds: False
        self.assertEqual(client.get("https://x/y").status_code, 200)


class TestTheRunShowsTheWait(Base):
    """Сказать в журнал мало: человек смотрит на экран."""

    def test_the_message_reaches_the_screen(self):
        source = Source()
        loader, said = self.loader(source)
        loader._retold("Сайт не ответил. Попытка 2 из 3 через 4 с")
        self.assertTrue(any("Попытка 2" in text for _, text in said))

    def test_the_client_from_outside_is_given_a_voice(self):
        """Клиент приходит снаружи и живёт дольше прогона — прицепляем
        весть к нему, а не заводим свой."""
        source = Source()
        client = Client()
        Downloader(source=source, client=client, threads=1, probe=False)
        self.assertIsNotNone(client.on_retry)

    def test_a_client_that_already_speaks_is_not_taken_over(self):
        """У него мог быть свой слушатель, и отнимать его нельзя."""
        def mine(text):
            pass

        client = Client(on_retry=mine)
        Downloader(source=Source(), client=client, threads=1, probe=False)
        self.assertIs(client.on_retry, mine)


class TestTheTocHasAWayOut(Base):
    """У глав запасной выход был всегда, у оглавления — не было."""

    def test_the_toc_goes_through_a_proxy_when_direct_fails(self):
        source = Source(good={"http://b:1"})
        pool = Pool(["http://a:1", "http://b:1"])
        loader, _ = self.loader(source, pool=pool)
        report = loader.run(self.novel(), self.folder)
        self.assertEqual(report.downloaded, 6)

    def test_the_direct_way_is_tried_first(self):
        """Он быстрее и не тратит адрес."""
        source = Source()
        pool = Pool(["http://a:1"])
        loader, _ = self.loader(source, pool=pool)
        loader.run(self.novel(), self.folder)
        self.assertEqual(source.asked, [None])

    def test_a_dead_proxy_is_not_the_end(self):
        """Один невезучий адрес не должен ронять книгу: рядом рабочие."""
        source = Source(good={"http://c:1"})
        pool = Pool(["http://a:1", "http://b:1", "http://c:1"])
        loader, _ = self.loader(source, pool=pool)
        self.assertEqual(loader.run(self.novel(), self.folder).downloaded, 6)

    def test_the_screen_is_told_we_are_trying_a_proxy(self):
        """Иначе это те же полминуты тишины, только в другом месте."""
        source = Source(good={"http://b:1"})
        pool = Pool(["http://a:1", "http://b:1"])
        loader, said = self.loader(source, pool=pool)
        loader.run(self.novel(), self.folder)
        self.assertTrue(any("прокси" in text.lower() for _, text in said))

    def test_without_proxies_the_trouble_is_passed_on(self):
        """Врать про запасной выход, которого нет, — хуже отказа."""
        source = Source(good={"http://b:1"})
        loader, _ = self.loader(source)
        with self.assertRaises(HttpError):
            loader.run(self.novel(), self.folder)

    def test_when_nothing_answers_the_first_trouble_is_told(self):
        """Отвечать «не вышло через прокси» на беду прямого захода значит
        показать не ту причину."""
        source = Source(good={"http://нет:1"})
        pool = Pool(["http://a:1", "http://b:1"])
        loader, _ = self.loader(source, pool=pool)
        with self.assertRaises(HttpError):
            loader.run(self.novel(), self.folder)

    def test_more_than_a_few_addresses_are_not_walked(self):
        """Каждый мёртвый адрес — это ожидание. Перебирать весь список
        значило бы менять минуту тишины на десять."""
        source = Source(good={"http://нет:1"})
        pool = Pool([f"http://{n}:1" for n in range(9)])
        loader, _ = self.loader(source, pool=pool)
        with self.assertRaises(HttpError):
            loader.run(self.novel(), self.folder)
        # Прямой заход плюс потолок на прокси.
        self.assertEqual(len(source.asked), 1 + downloader_mod.TOC_PROXIES)


if __name__ == "__main__":
    unittest.main()
