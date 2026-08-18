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

    def test_one_proxy_is_still_used(self):
        """Единственный адрес — тоже адрес.

        Порог «раздавать прокси по потокам, только если их хотя бы два»
        уводил настройку с одним адресом в прямое соединение: прокси не
        работал вовсе, а на Фанкью это ещё и утечка своего адреса.
        """
        loader = self.downloader([self.Proxy("http://one")])
        fetcher = loader._manual_fetcher(
            api.Novel(code=1, name="к", slug="k", total_chapters=1))
        self.assertEqual(fetcher.method, pool.PROXY_PER_THREAD)
        self.assertEqual(getattr(fetcher._take_proxy(), "url", None),
                         "http://one")
        # Адрес один — и поток при нём один: ломиться в него втроём значит
        # ровно то, ради чего раздача по потокам и делалась.
        self.assertEqual(loader.threads, 1)

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


class Addressed:
    """Прокси, каким его видит замер: с адресом для отчёта."""

    def __init__(self, label: str):
        self.label = label
        self.url = f"http://{label}"
        self.disabled = False


class TestMeasure(unittest.TestCase):
    """Замер многопоточности (часть 6 ТЗ).

    Ручной режим чинили вслепую: убедиться, что потоки идут параллельно и
    через разные адреса, было нечем, кроме прогона книги целиком.
    """

    def proxies(self, count: int = 3):
        return [Addressed(f"10.0.0.{n}:8000") for n in range(1, count + 1)]

    def test_every_thread_gets_its_own_address(self):
        found = pool.measure(CHAPTERS, maker(), slow(0.05), threads=3,
                             proxies=self.proxies(3))
        addresses = [row.proxy for row in found.rows]
        self.assertEqual(len(addresses), 3)
        self.assertEqual(len(set(addresses)), 3)

    def test_the_address_is_named_without_the_password(self):
        found = pool.measure(CHAPTERS, maker(), slow(0.05), threads=2,
                             proxies=self.proxies(2))
        for row in found.rows:
            with self.subTest(row=row.number):
                self.assertNotIn("@", row.proxy)
                self.assertNotIn("http", row.proxy)

    def test_chapters_are_listed_per_thread(self):
        found = pool.measure(CHAPTERS, maker(), slow(0.05), threads=3,
                             proxies=self.proxies(3))
        taken = sorted(n for row in found.rows for n in row.chapters)
        self.assertEqual(taken, [c.number for c in CHAPTERS])

    def test_one_address_for_everyone_is_called_out(self):
        """Ровно то, ради чего замер и затевался."""
        found = pool.measure(CHAPTERS, maker(), slow(0.05), threads=3,
                             proxies=self.proxies(1))
        self.assertTrue(found.rows)
        self.assertTrue(found.shared_address or len(found.rows) == 1)

    def test_without_proxies_the_report_says_so(self):
        found = pool.measure(CHAPTERS, maker(), slow(0.05), threads=3)
        self.assertEqual(found.proxies, 0)
        self.assertTrue(all(row["proxy"] == pool.DIRECT_LABEL
                            for row in found.as_dict()["rows"]))

    def test_fewer_proxies_than_threads_is_said_in_words(self):
        found = pool.measure(CHAPTERS, maker(), slow(0.05), threads=5,
                             proxies=self.proxies(3))
        self.assertEqual(found.threads, 3)
        self.assertIn("потоков 5, живых прокси 3", found.note)

    def test_speedup_is_measured(self):
        found = pool.measure(CHAPTERS, maker(), slow(0.1), threads=3,
                             proxies=self.proxies(3))
        self.assertGreater(found.speedup, 1.5)
        self.assertGreater(found.expected, found.seconds)

    def test_warmup_is_kept_out_of_the_measurement(self):
        """Первый запрос дольше остальных — он тормозил бы сам замер."""
        found = pool.measure(CHAPTERS, maker(), slow(0.05), threads=3,
                             proxies=self.proxies(3))
        self.assertGreater(found.warmup, 0)

    def test_an_empty_chapter_is_marked_not_counted(self):
        found = pool.measure(CHAPTERS, maker(), slow(0.01, text=" "),
                             threads=2, proxies=self.proxies(2))
        self.assertEqual([n for row in found.rows for n in row.chapters], [])
        self.assertTrue([n for row in found.rows for n in row.failed])

    def test_a_broken_site_does_not_crash_the_measurement(self):
        def refuse(client, chapter):
            raise OSError("соединение сброшено")

        found = pool.measure(CHAPTERS, maker(), refuse, threads=2,
                             proxies=self.proxies(2))
        self.assertTrue(found.error)

    def test_nothing_to_download_is_said_plainly(self):
        found = pool.measure([], maker(), slow(0.01), threads=2)
        self.assertIn("не нашлось глав", found.error)

    def test_cancelling_stops_it(self):
        stop = threading.Event()
        stop.set()
        found = pool.measure(CHAPTERS, maker(), slow(0.01), threads=2,
                             cancel=stop)
        self.assertEqual(found.error, "остановлено")

    def test_the_report_survives_the_trip_to_the_screen(self):
        found = pool.measure(CHAPTERS, maker(), slow(0.05), threads=3,
                             proxies=self.proxies(3)).as_dict()
        for key in ("threads", "proxies", "warmup", "seconds", "expected",
                    "speedup", "rows", "shared_address", "note"):
            with self.subTest(key=key):
                self.assertIn(key, found)
        self.assertIn("chapters", found["rows"][0])

    def test_nothing_is_saved_anywhere(self):
        """Это замер, а не скачивание: файлов после него быть не должно."""
        written = []

        def fetch(client, chapter):
            written.append(chapter.number)
            return "Текст."

        pool.measure(CHAPTERS, maker(), fetch, threads=2,
                     proxies=self.proxies(2))
        # Качалка вызвана, но записывать ей нечем — writer сюда не передан.
        self.assertTrue(written)


class TestOneDeadAddressDoesNotKillTheMeasurement(unittest.TestCase):
    """Замер утыкался в мёртвый адрес и выдавал нули по всем графам.

    Прогрев идёт первым и первым же падает: исключение вылетает из
    `.result()`, `warmup`, `seconds` и `expected` остаются нулями, и в
    отчёте выходит «прогрев 0.0 с · последовательно 0.0 с · фактически
    0.0 с · ускорение 0.0×» — при восьми рабочих адресах рядом.
    Скачивание давно умеет переезжать на другой прокси, замер — нет.
    """

    def proxies(self, count: int = 3):
        return [Addressed(f"10.0.0.{n}:8000") for n in range(1, count + 1)]

    def dead_first(self, dead="10.0.0.1:8000"):
        """Качалка, у которой первый адрес молчит, а остальные отвечают.

        Отказ занимает столько же времени, сколько успех. Мгновенный
        отказ делал поток на мёртвом адресе быстрее всех остальных, и он
        успевал разобрать всю очередь глав раньше, чем рабочие потоки
        вообще начинали работать.
        """
        def fetch(client, chapter):
            time.sleep(0.02)
            if dead in (getattr(client, "proxy_url", "") or ""):
                raise ConnectionError(f"не достучаться до {dead}")
            return "Текст главы."
        return fetch

    def swap(self, exc):
        return isinstance(exc, ConnectionError)

    def test_the_measurement_finishes_on_the_other_addresses(self):
        found = pool.measure(CHAPTERS, maker(), self.dead_first(), threads=3,
                             proxies=self.proxies(3), swap_when=self.swap)

        self.assertFalse(found.error, found.error)
        self.assertGreater(found.seconds, 0)
        self.assertEqual(sorted(n for row in found.rows for n in row.chapters),
                         [c.number for c in CHAPTERS])

    def test_several_bad_addresses_in_a_row_are_stepped_over(self):
        """Переезд был один-единственный, и второй плохой адрес добивал.

        Ровно то, что видел человек: одиннадцать прокси в пуле, а в
        отчёте «Замер прервался: NetworkError: прокси ответил HTTP 502».
        """
        dead = {"10.0.0.1:8000", "10.0.0.2:8000", "10.0.0.3:8000"}

        def fetch(client, chapter):
            where = getattr(client, "proxy_url", "") or ""
            if any(bad in where for bad in dead):
                raise ConnectionError("прокси ответил HTTP 502")
            time.sleep(0.02)
            return "Текст главы."

        found = pool.measure(CHAPTERS, maker(), fetch, threads=3,
                             proxies=self.proxies(8), swap_when=self.swap)

        self.assertFalse(found.error, found.error)
        self.assertEqual(sorted(n for row in found.rows for n in row.chapters),
                         [c.number for c in CHAPTERS])

    def test_the_dead_address_is_left_out_of_the_work(self):
        proxies = self.proxies(3)
        pool.measure(CHAPTERS, maker(), self.dead_first(), threads=3,
                     proxies=proxies, swap_when=self.swap)

        dead = next(p for p in proxies if p.label == "10.0.0.1:8000")
        self.assertTrue(dead.disabled, "мёртвый адрес остался в работе")

    def test_without_the_rule_the_thread_stays_on_the_dead_address(self):
        """Правило приходит снаружи: без него переезжать замер не станет.

        Ронять весь прогон он теперь не станет тоже — просто у одного
        потока не выйдет ни одной главы, и это будет видно в отчёте.
        """
        proxies = self.proxies(3)
        found = pool.measure(CHAPTERS, maker(), self.dead_first(), threads=3,
                             proxies=proxies)

        self.assertFalse([p.label for p in proxies if p.disabled])
        empty = [row for row in found.rows if not row.chapters]
        self.assertTrue(empty, "поток на мёртвом адресе должен быть виден")
        self.assertIn("10.0.0.1:8000", empty[0].note)

    def test_the_report_says_why_a_thread_brought_nothing(self):
        """«Ни одной главы» без причины ничего не объясняет."""
        found = pool.measure(CHAPTERS, maker(), self.dead_first(), threads=3,
                             proxies=self.proxies(3))
        empty = [row for row in found.rows if not row.chapters][0]
        self.assertIn("не достучаться", empty.note)
        self.assertIn("note", empty.as_dict())

    def test_a_measurement_that_got_something_is_not_called_broken(self):
        """Иначе поверх нормального отчёта висит «Замер прервался».

        Осечку вешаем на главу, а не на адрес: кто из потоков какую главу
        возьмёт, решает планировщик, и «одна глава не вышла, остальные
        вышли» — единственная формулировка, не зависящая от него.
        """
        def fetch(client, chapter):
            time.sleep(0.02)
            if chapter.number == CHAPTERS[0].number:
                raise ConnectionError("не достучаться до 10.0.0.1:8000")
            return "Текст главы."

        found = pool.measure(CHAPTERS, maker(), fetch, threads=3,
                             proxies=self.proxies(3))

        self.assertFalse(found.error, found.error)
        self.assertGreater(found.seconds, 0)
        self.assertEqual(sorted(n for row in found.rows for n in row.chapters),
                         [c.number for c in CHAPTERS[1:]])

    def test_a_refusal_is_not_blamed_on_the_address(self):
        """Иначе одна закрытая глава пометит мёртвыми все прокси разом."""
        proxies = self.proxies(3)

        def paid(client, chapter):
            raise ValueError("глава платная")

        pool.measure(CHAPTERS, maker(), paid, threads=3, proxies=proxies,
                     swap_when=self.swap)
        self.assertFalse([p.label for p in proxies if p.disabled])

    def test_the_last_address_left_is_not_swapped_into_nothing(self):
        """Менять не на что — осечку показываем, а не глотаем."""
        def dead(client, chapter):
            raise ConnectionError("молчит")

        found = pool.measure(CHAPTERS, maker(), dead, threads=1,
                             proxies=self.proxies(1), swap_when=self.swap)
        self.assertTrue(found.error)


class TestThreadsWord(unittest.TestCase):
    def test_russian_endings(self):
        self.assertEqual(pool.threads_word(1), "поток")
        self.assertEqual(pool.threads_word(3), "потока")
        self.assertEqual(pool.threads_word(5), "потоков")
        self.assertEqual(pool.threads_word(11), "потоков")


class TestThreadsRoute(unittest.TestCase):
    """Замер должен доехать до экрана целиком."""

    @classmethod
    def setUpClass(cls):
        import webapp.app as web
        from mvl.api import Toc
        from net.sources.base import Source

        class FakeSource(Source):
            key, name, hint, placeholder = "fake", "Тест", "", ""

            def find(self, client, query):
                return api.Novel(code=1, name="Т", slug="t", total_chapters=20)

            def toc(self, client, novel, first=1, last=None, on_progress=None):
                return Toc(chapters=[api.Chapter(number=n)
                                     for n in range(first, (last or 6) + 1)])

            def chapter(self, client, chapter):
                time.sleep(0.02)
                return f"Глава {chapter.number}", f"Текст {chapter.number}."

        cls.web = web
        cls.real_get = web.sources.get
        web.sources.get = lambda key="": FakeSource()
        web.app.config["TESTING"] = True
        cls.app = web.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.web.sources.get = cls.real_get

    def setUp(self):
        self.was = self.web.POOL
        self.addCleanup(lambda: setattr(self.web, "POOL", self.was))

    def pool(self, count: int):
        class Pool:
            proxies = [Addressed(f"10.0.0.{n}:8000") for n in range(1, count + 1)]

        self.web.POOL = Pool() if count else None

    def check(self, **extra):
        return self.app.post("/api/threads/check", json={
            "novel": {"code": 1, "name": "Т", "total_chapters": 20},
            "source": "fake", **extra})

    def test_the_report_comes_back(self):
        self.pool(3)
        res = self.check(threads=3)
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(len(body["rows"]), 3)
        self.assertEqual(len({row["proxy"] for row in body["rows"]}), 3)

    def test_without_a_book_it_refuses_before_the_network(self):
        res = self.app.post("/api/threads/check", json={"novel": {}})
        self.assertEqual(res.status_code, 400)
        self.assertIn("найдите книгу", res.get_json()["error"])

    def test_fewer_proxies_than_threads_is_explained(self):
        self.pool(2)
        body = self.check(threads=5).get_json()
        self.assertIn("живых прокси 2", body["note"])

    def test_nothing_is_written_to_disk(self):
        """Это замер: папки для него никто не выбирал."""
        self.pool(2)
        body = self.check(threads=2).get_json()
        self.assertNotIn("output_dir", body)
        self.assertNotIn("job", body)


class TestThreadsRouteExplainsItself(unittest.TestCase):
    """3.3: маршрут падал с 502 без единого слова о причине.

    Оглавление он забирал голым клиентом, без прокси, — а источник без
    прокси не отвечает вовсе. Ответ при этом не говорил ни что за шаг
    сорвался, ни что дело вообще не в потоках.
    """

    @classmethod
    def setUpClass(cls):
        import webapp.app as web

        web.app.config["TESTING"] = True
        cls.web = web
        cls.app = web.app.test_client()
        cls.real = web.sources.get

    @classmethod
    def tearDownClass(cls):
        cls.web.sources.get = cls.real

    def setUp(self):
        self.was = self.web.POOL
        self.addCleanup(lambda: setattr(self.web, "POOL", self.was))

    class Source:
        key, name, hint, placeholder = "fanqie", "Fanqie", "", ""
        needs_proxy = True

        def __init__(self, toc=None):
            self._toc = toc

        def find(self, client, query):
            return api.Novel(code=1, name="К", slug="", total_chapters=9)

        def toc(self, client, novel, first=1, last=None, on_progress=None):
            if callable(self._toc):
                return self._toc()
            from mvl.api import Toc

            return Toc(chapters=[api.Chapter(number=n)
                                 for n in range(first, (last or 6) + 1)])

        def chapter(self, client, chapter):
            time.sleep(0.02)
            return f"Глава {chapter.number}", "текст"

    def use(self, source, proxies: int):
        self.web.sources.get = lambda key="": source

        class Pool:
            pass

        if proxies:
            Pool.proxies = [Addressed(f"10.0.0.{n}:8000")
                            for n in range(1, proxies + 1)]
            self.web.POOL = Pool()
        else:
            self.web.POOL = None

    def check(self):
        return self.app.post("/api/threads/check", json={
            "novel": {"code": "7590221243043826712", "name": "К",
                      "total_chapters": 9},
            "source": "fanqie", "threads": 3})

    def test_a_source_that_needs_a_proxy_says_so(self):
        self.use(self.Source(), proxies=0)
        res = self.check()
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertIn("только через прокси", body["error"])
        self.assertEqual(body["step"], "прокси")

    def test_a_broken_toc_names_the_step(self):
        from net import sources as sources_mod

        def broken():
            raise sources_mod.SourceBroken("разметка изменилась")

        self.use(self.Source(toc=broken), proxies=3)
        body = self.check().get_json()
        self.assertEqual(body["step"], "оглавление")
        self.assertIn("разметка изменилась", body["error"])

    def test_a_book_without_chapters_is_not_a_server_failure(self):
        from mvl.api import Toc

        self.use(self.Source(toc=lambda: Toc(chapters=[])), proxies=3)
        res = self.check()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["step"], "оглавление")

    def test_the_toc_is_fetched_through_a_proxy(self):
        """Голым клиентом сайт не отвечает — отсюда и брался 502.

        Спрашиваем сам клиент, а не текст вызова: имена переменных и
        набор параметров меняются, а «оглавление идёт через прокси» —
        нет, и ломаться тест должен только на этом.
        """
        seen = []
        source = self.Source()
        original = source.toc

        def watched(client, *args, **kwargs):
            seen.append(getattr(client, "proxy_url", None))
            return original(client, *args, **kwargs)

        source.toc = watched
        self.use(source, proxies=3)
        self.check()

        self.assertTrue(seen, "оглавление вообще не собиралось")
        self.assertIn("10.0.0.", seen[0] or "")

    def test_a_running_measurement_can_be_stopped(self):
        """Замер жил отдельно от прогона, и остановить его было нечем.

        После отмены скачивания он крутился ещё три минуты, долбился в
        недоступный адрес и помечал прокси нерабочими — теми самыми,
        которыми потом качать.
        """
        source = self.Source()
        began = threading.Event()

        def crawl(client, chapter):
            began.set()
            time.sleep(0.3)
            return f"Глава {chapter.number}", "текст"

        source.chapter = crawl
        self.use(source, proxies=3)

        answer = {}

        def run():
            answer["body"] = self.check().get_json()

        worker = threading.Thread(target=run)
        worker.start()
        self.addCleanup(worker.join, 10)

        self.assertTrue(began.wait(5), "замер так и не начался")
        stopped = self.app.post("/api/threads/cancel", json={})
        self.assertTrue(stopped.get_json()["running"])

        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), "замер не остановился")
        self.assertIn("остановлено", answer["body"].get("error", ""))

    def test_stopping_when_nothing_runs_is_not_an_error(self):
        answer = self.app.post("/api/threads/cancel", json={})
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(answer.get_json()["running"])

    def test_the_flag_is_let_go_when_the_measurement_ends(self):
        """Иначе следующая остановка гасит уже закончившийся замер."""
        self.use(self.Source(), proxies=3)
        self.check()
        self.assertFalse(self.app.post("/api/threads/cancel",
                                       json={}).get_json()["running"])

    def test_the_waiting_times_reach_the_measurement(self):
        """Замер должен ждать столько же, сколько потом будет качать.

        Иначе он меряет не то: в журнале стояло «15003 ms» независимо от
        того, что выставлено на экране.
        """
        seen = []
        source = self.Source()
        original = source.toc

        def watched(client, *args, **kwargs):
            seen.append((client.timeout, client.connect_timeout))
            return original(client, *args, **kwargs)

        source.toc = watched
        self.use(source, proxies=3)
        self.app.post("/api/threads/check", json={
            "novel": {"code": "7590221243043826712", "name": "К",
                      "total_chapters": 9},
            "source": "fanqie", "threads": 3,
            "timeout": 77, "connect_timeout": 9})

        self.assertEqual(seen[0], (77, 9))

    def test_a_good_run_still_answers_with_the_report(self):
        self.use(self.Source(), proxies=3)
        res = self.check()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.get_json()["rows"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
