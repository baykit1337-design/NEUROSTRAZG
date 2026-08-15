"""Автопроба способа скачивания (A4 ТЗ NEUROSTRAZH).

Интернет не нужен: качалка главы подставляется тестом, поэтому можно
разыграть и медленный сайт, и 403, и пустой ответ.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import api
from net import pool  # noqa: E402


class Chapter:
    def __init__(self, number: int):
        self.number = number


CHAPTERS = [Chapter(n) for n in range(1, 6)]


class FakeClient:
    """Клиент, который только помнит, каким его создали."""

    def __init__(self, proxy_url=None, shared_session=False):
        self.proxy_url = proxy_url
        self.shared_session = shared_session
        self.closed = False

    def close(self):
        self.closed = True


class Proxy:
    def __init__(self, url: str):
        self.url = url
        self.disabled = False


def maker(created=None):
    """Фабрика клиентов, складывающая созданное в список."""
    def make(proxy_url=None, shared_session=False):
        client = FakeClient(proxy_url, shared_session)
        if created is not None:
            created.append(client)
        return client
    return make


def slow(seconds: float, text: str = "Текст главы."):
    """Качалка, которая тратит заданное время на главу."""
    def fetch(client, chapter):
        time.sleep(seconds)
        return text
    return fetch


class TestOrder(unittest.TestCase):
    def test_sequential_is_never_probed(self):
        # Последовательный работает всегда — пробовать его нечего.
        self.assertNotIn(pool.SEQUENTIAL, pool.order_methods())

    def test_last_working_method_goes_first(self):
        order = pool.order_methods(pool.ASYNC)
        self.assertEqual(order[0], pool.ASYNC)
        self.assertEqual(sorted(order), sorted(pool.order_methods()))

    def test_unknown_last_method_ignored(self):
        self.assertEqual(pool.order_methods("нет такого"), pool.order_methods())


class TestProbeMethod(unittest.TestCase):
    def test_parallel_run_passes(self):
        """Три потока на пяти главах обгоняют очередь — проба проходит."""
        attempt = pool.probe_method(
            pool.OWN_SESSION, CHAPTERS, maker(), slow(0.05), threads=3)
        self.assertTrue(attempt.ok, attempt.reason)
        self.assertGreaterEqual(attempt.speedup, 1.7)

    def test_one_thread_is_reported_as_no_parallelism(self):
        """Один поток — это не «медленно», а «параллельности не было».

        Разница принципиальна: по первой формулировке непонятно, ломается
        проба или сам параллельный режим.
        """
        attempt = pool.probe_method(
            pool.OWN_SESSION, CHAPTERS, maker(), slow(0.05), threads=1)
        self.assertFalse(attempt.ok)
        self.assertEqual(attempt.concurrent, 1)
        self.assertFalse(attempt.parallel_ran)
        self.assertIn("по очереди", attempt.reason)

    def test_slow_but_parallel_is_reported_by_the_ratio(self):
        """Потоки были, но выигрыша нет — причина в цифрах, а не в догадках."""
        attempt = pool.probe_method(
            pool.OWN_SESSION, CHAPTERS, maker(), slow(0.05), threads=3,
            speedup=99.0)
        self.assertFalse(attempt.ok)
        self.assertTrue(attempt.parallel_ran)
        self.assertIn("ускорение", attempt.reason)
        self.assertIn("пороге", attempt.reason)

    def test_warmup_is_measured_and_excluded(self):
        """Первый запрос дольше — рукопожатие TLS и кука Cloudflare."""
        attempt = pool.probe_method(
            pool.OWN_SESSION, CHAPTERS, maker(), slow(0.05), threads=3)
        self.assertGreater(attempt.warmup, 0)
        # Прогрев в замер не входит: иначе способ тормозит сам себя.
        self.assertLess(attempt.seconds, attempt.warmup * len(CHAPTERS))

    def test_real_concurrency_is_counted(self):
        attempt = pool.probe_method(
            pool.OWN_SESSION, CHAPTERS, maker(), slow(0.05), threads=3)
        self.assertGreater(attempt.concurrent, 1)
        self.assertLessEqual(attempt.concurrent, 3)
        self.assertGreaterEqual(attempt.workers, 2)

    def test_empty_chapter_fails(self):
        attempt = pool.probe_method(
            pool.OWN_SESSION, CHAPTERS, maker(), slow(0.01, ""), threads=3)
        self.assertFalse(attempt.ok)
        self.assertIn("пустой", attempt.reason)

    def test_refusal_names_the_status(self):
        class Blocked(Exception):
            status = 403

        def fetch(client, chapter):
            raise Blocked("нельзя")

        attempt = pool.probe_method(
            pool.OWN_SESSION, CHAPTERS, maker(), fetch, threads=3)
        self.assertFalse(attempt.ok)
        self.assertEqual(attempt.reason, "сайт ответил 403")

    def test_rate_limit_fails_the_method(self):
        class Limited(Exception):
            status = 429

        def fetch(client, chapter):
            raise Limited("часто")

        attempt = pool.probe_method(
            pool.OWN_SESSION, CHAPTERS, maker(), fetch, threads=3)
        self.assertFalse(attempt.ok)
        self.assertEqual(attempt.reason, "сайт ответил 429")

    def test_shared_session_uses_one_client(self):
        created = []
        pool.probe_method(pool.SHARED_SESSION, CHAPTERS, maker(created),
                          slow(0.05), threads=3)
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].shared_session)

    def test_own_session_uses_client_per_thread(self):
        created = []
        pool.probe_method(pool.OWN_SESSION, CHAPTERS, maker(created),
                          slow(0.05), threads=3)
        # Клиентов не больше, чем потоков, и каждый со своей сессией.
        self.assertLessEqual(len(created), 3)
        self.assertFalse(any(c.shared_session for c in created))

    def test_proxy_per_thread_spreads_addresses(self):
        created = []
        proxies = [Proxy("http://a"), Proxy("http://b"), Proxy("http://c")]
        attempt = pool.probe_method(
            pool.PROXY_PER_THREAD, CHAPTERS, maker(created), slow(0.05),
            threads=3, proxies=proxies)
        self.assertTrue(attempt.ok, attempt.reason)
        self.assertEqual(attempt.proxies, 3)
        # Кука Cloudflare привязана к адресу: два потока на один адрес —
        # уже не то, ради чего способ нужен.
        used = [c.proxy_url for c in created]
        self.assertEqual(len(used), len(set(used)))

    def test_proxy_per_thread_needs_two_addresses(self):
        attempt = pool.probe_method(
            pool.PROXY_PER_THREAD, CHAPTERS, maker(), slow(0.01),
            threads=3, proxies=[Proxy("http://a")])
        self.assertFalse(attempt.ok)
        self.assertIn("два прокси", attempt.reason)

    def test_async_method_runs(self):
        attempt = pool.probe_method(
            pool.ASYNC, CHAPTERS, maker(), slow(0.05), threads=3)
        self.assertTrue(attempt.ok, attempt.reason)

    def test_clients_are_closed(self):
        created = []
        pool.probe_method(pool.OWN_SESSION, CHAPTERS, maker(created),
                          slow(0.02), threads=3)
        self.assertTrue(all(c.closed for c in created))

    def test_cancel_stops_the_probe(self):
        cancel = threading.Event()
        cancel.set()
        attempt = pool.probe_method(
            pool.OWN_SESSION, CHAPTERS, maker(), slow(0.01), threads=3,
            cancel=cancel)
        self.assertFalse(attempt.ok)
        self.assertEqual(attempt.reason, "остановлено")


class TestProxySwap(unittest.TestCase):
    """A5: отвалившийся адрес меняется, поток продолжает с той же главы."""

    def fetcher(self, proxies, created=None):
        return pool.Fetcher(pool.PROXY_PER_THREAD, maker(created), proxies)

    def test_replace_takes_the_next_address(self):
        created = []
        f = self.fetcher([Proxy("http://a"), Proxy("http://b")], created)
        first = f.client()
        second = f.replace("не отвечает")
        self.assertIsNot(first, second)
        self.assertNotEqual(first.proxy_url, second.proxy_url)
        # Старый клиент закрыт: сессию с мёртвым адресом держать незачем.
        self.assertTrue(first.closed)

    def test_dead_address_is_dropped_from_the_pool(self):
        proxies = [Proxy("http://a"), Proxy("http://b")]
        f = self.fetcher(proxies)
        f.client()
        f.replace("не отвечает")
        self.assertEqual(f.alive, 1)
        self.assertTrue(any(p.disabled for p in proxies))

    def test_last_address_cannot_be_replaced(self):
        f = self.fetcher([Proxy("http://a")])
        f.client()
        self.assertIsNone(f.replace("не отвечает"))
        self.assertEqual(f.alive, 0)

    def test_other_methods_do_not_swap(self):
        f = pool.Fetcher(pool.OWN_SESSION, maker(), [Proxy("http://a")])
        f.client()
        self.assertIsNone(f.replace("не отвечает"))

    def test_threads_drop_to_the_number_of_addresses(self):
        """Двум потокам на один адрес делать нечего — смысл способа в IP."""
        def fetch(client, chapter):
            if client.proxy_url is None:
                raise RuntimeError("403")
            time.sleep(0.05)
            return "Текст главы."

        proxies = [Proxy("http://a"), Proxy("http://b")]
        report = pool.autoprobe(CHAPTERS, maker(), fetch, threads=5,
                                proxies=proxies, last="")
        self.assertEqual(report.method, pool.PROXY_PER_THREAD)
        self.assertEqual(report.threads, 2)


class TestAutoprobe(unittest.TestCase):
    def test_first_working_method_wins(self):
        report = pool.autoprobe(CHAPTERS, maker(), slow(0.05), threads=3, last="")
        self.assertTrue(report.parallel)
        self.assertEqual(report.method, pool.OWN_SESSION)
        # Раз первый способ прошёл — остальные не пробуем.
        self.assertEqual(len(report.attempts), 1)

    def test_falls_back_to_sequential(self):
        """Ни один параллельный не прошёл — качаем по очереди, без ошибки."""
        class Blocked(Exception):
            status = 403

        def fetch(client, chapter):
            raise Blocked("нельзя")

        report = pool.autoprobe(CHAPTERS, maker(), fetch, threads=3, last="")
        self.assertFalse(report.parallel)
        self.assertEqual(report.method, pool.SEQUENTIAL)
        self.assertEqual(report.threads, 1)
        self.assertEqual(len(report.attempts), 4)
        self.assertEqual(
            report.message,
            "Многопоточность недоступна. Скачивание идёт по очереди.")

    def test_proxy_method_reports_how_many_addresses(self):
        """Сработал способ с прокси — сообщаем, сколько адресов в деле."""
        calls = {"n": 0}

        def fetch(client, chapter):
            # Без прокси сайт отказывает, с прокси — отвечает.
            if client.proxy_url is None:
                raise RuntimeError("403")
            calls["n"] += 1
            time.sleep(0.05)
            return "Текст главы."

        proxies = [Proxy(f"http://{n}") for n in range(3)]
        report = pool.autoprobe(CHAPTERS, maker(), fetch, threads=3,
                                proxies=proxies, last="")
        self.assertEqual(report.method, pool.PROXY_PER_THREAD)
        self.assertEqual(report.proxies, 3)
        self.assertIn("3 адреса", report.message)

    def test_no_chapters_means_no_probe(self):
        report = pool.autoprobe([], maker(), slow(0.01), threads=3, last="")
        self.assertEqual(report.attempts, [])

    def test_steps_are_reported(self):
        seen = []
        pool.autoprobe(CHAPTERS, maker(), slow(0.05), threads=3, last="",
                       on_step=seen.append)
        self.assertEqual(seen, [pool.NAMES[pool.OWN_SESSION]])

    def test_report_is_serialisable(self):
        report = pool.autoprobe(CHAPTERS, maker(), slow(0.05), threads=3, last="")
        data = report.as_dict()
        self.assertTrue(data["parallel"])
        self.assertIn("attempts", data)
        self.assertIn("message", data)


class TestManualMode(unittest.TestCase):
    """5.3: «Всегда N потоков» пропускает пробу, но не раздачу клиентов.

    Раньше пропускалось и то и другое: потоки создавались, но все делили
    одну сессию и один прокси. Кука Cloudflare привязана к адресу, и
    запросы вставали в очередь на сайте — заявленные N потоков работали
    как один.
    """

    class Proxy:
        def __init__(self, url):
            self.url = url
            self.disabled = False

    class FakePool:
        def __init__(self, proxies):
            self.proxies = proxies

    def downloader(self, proxies, threads=3):
        from mvl.downloader import Downloader

        return Downloader(pool=self.FakePool(proxies), threads=threads,
                          probe=False)

    def test_each_thread_gets_its_own_proxy(self):
        proxies = [self.Proxy(f"http://p{n}") for n in range(8)]
        fetcher = self.downloader(proxies)._manual_fetcher(
            api.Novel(code=1, name="к", slug="k", total_chapters=1))
        self.assertEqual(fetcher.method, pool.PROXY_PER_THREAD)

        taken = set()
        def take():
            taken.add(getattr(fetcher._take_proxy(), "url", None))
        threads = [threading.Thread(target=take) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(taken), 3)

    def test_one_proxy_still_gives_each_thread_its_session(self):
        fetcher = self.downloader([self.Proxy("http://one")])._manual_fetcher(
            api.Novel(code=1, name="к", slug="k", total_chapters=1))
        self.assertEqual(fetcher.method, pool.OWN_SESSION)

    def test_threads_do_not_exceed_the_addresses(self):
        """Четыре потока на два адреса — это два потока, а не четыре."""
        loader = self.downloader([self.Proxy("http://a"), self.Proxy("http://b")],
                                 threads=4)
        loader._manual_fetcher(api.Novel(code=1, name="к", slug="k",
                                         total_chapters=1))
        self.assertEqual(loader.threads, 2)

    def test_no_proxies_at_all_is_not_a_crash(self):
        loader = self.downloader([])
        fetcher = loader._manual_fetcher(
            api.Novel(code=1, name="к", slug="k", total_chapters=1))
        self.assertEqual(fetcher.method, pool.OWN_SESSION)
        self.assertEqual(loader.threads, 3)


class TestPlural(unittest.TestCase):
    def test_russian_endings(self):
        for count, word in [(1, "адрес"), (2, "адреса"), (4, "адреса"),
                            (5, "адресов"), (11, "адресов"), (21, "адрес"),
                            (0, "адресов")]:
            with self.subTest(count=count):
                self.assertEqual(pool._plural(count), word)


if __name__ == "__main__":
    unittest.main(verbosity=2)
