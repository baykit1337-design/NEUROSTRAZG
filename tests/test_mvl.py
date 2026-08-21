"""Тесты.

Живой сайт недоступен из CI, поэтому весь пайплайн гоняем против локального
мок-сервера. Он играет обе роли сразу: на `/wp-json/*` отвечает как REST API
бэкенда, на `/chapter/*` — как витрина.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import api, client as client_mod, downloader as downloader_mod, proxies  # noqa: E402
from mvl.client import Blocked, Client, NetworkError, RateLimited, SiteClient  # noqa: E402
from mvl.downloader import Cancelled, Downloader, State, _compact_ranges, verify  # noqa: E402
from mvl.paths import chapter_filename, prepare_output_dir, sanitize_filename  # noqa: E402

NOVEL_CODE = 6615
NOVEL_NAME = "Insect Tamer's Ascension"
NOVEL_SLUG = "insect-tamers-ascension"
TOTAL = 12
HOLES = {7}  # нет в каталоге
FLAKY = {9}  # витрина отдаёт 500
BLOCKED: set[int] = set()  # витрина отдаёт 403, ставится в отдельных тестах

CHAPTER_HTML = """
<html><body>
  <h1 id="novel-name">{novel}</h1>
  <h2 id="chapter-name">{title}</h2>
  <a id="prev-top" href="https://x/chapter/{code}-{prev}">prev</a>
  <a id="next-top" href="https://x/chapter/{code}-{next}">next</a>
  <div id="chapter">
    <span id="span-2054-1305853">
      <p>First line of chapter {n}.</p>
      <p>*</p>
      <p>Second line of chapter {n}.</p>
    </span>
    <div class="ke400008d2"><p>Buy our premium subscription</p></div>
    <p class="rb9bdb230d">Sponsored nonsense</p>
    <p>   </p>
  </div>
</body></html>
"""

CLOUDFLARE_PAGE = """
<html><head><title>Attention Required! | Cloudflare</title></head>
<body><h1>Sorry, you have been blocked</h1><div class="cf-error-details">
Ray ID: 8f2a1b</div></body></html>
"""


class Recorder:
    """Что мок увидел: заголовки, параллельность, использование _fields."""

    def __init__(self):
        self.lock = threading.Lock()
        self.chapter_headers: list[dict] = []
        self.saw_fields_param = False
        self.novel_queries: list[dict] = []
        self.in_flight = 0
        self.max_in_flight = 0
        # Сколько раз запрашивали каждую главу — для проверки «403 не ретраим».
        self.chapter_hits: dict[int, int] = {}

    def enter(self):
        with self.lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)

    def leave(self):
        with self.lock:
            self.in_flight -= 1


class MockHandler(BaseHTTPRequestHandler):
    serve_cloudflare = False  # вместо главы отдавать заглушку

    def log_message(self, *args):
        pass

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(url.query).items()}
        rec = self.server.recorder

        if "_fields" in query:
            rec.saw_fields_param = True

        if url.path == "/wp-json/wp/v2/mvl-novels":
            self._novels(query, rec)
            return
        if url.path == "/wp-json/wp/v2/posts":
            self._posts(parse_qs(url.query).get("slug[]", []))
            return
        if url.path.startswith("/chapter/"):
            self._chapter(url.path, rec)
            return

        self._send({"error": "not found"}, status=404)

    # ---------------------------------------------------------------- каталог

    def _novels(self, query, rec):
        rec.novel_queries.append(query)

        # С _fields WP молча срезает кастомные поля — массив пустых объектов.
        if "_fields" in query:
            self._send([[]])
            return

        book = {
            "name": NOVEL_NAME,
            "slug": NOVEL_SLUG,
            "novel-code": NOVEL_CODE,
            "total-chapters": TOTAL,
            "read-link": f"/chapter/{NOVEL_CODE}-1",
            "status": "Ongoing",
            "author-name": "sahejRocks",
        }
        other = {"name": "Unrelated Novel", "slug": "unrelated", "novel-code": 111,
                 "total-chapters": 3}

        if "slug" in query:
            self._send([book] if query["slug"] == NOVEL_SLUG else [])
            return
        if "search" in query:
            term = str(query["search"]).lower()
            hits = [b for b in (book, other)
                    if term in b["name"].lower() or term == str(b["novel-code"])]
            self._send(hits)
            return
        self._send([book, other])

    # ------------------------------------------------------------- оглавление

    def _posts(self, slugs):
        posts = []
        for slug in slugs:
            code, _, number = slug.partition("-")
            number = int(number)
            if number in HOLES:
                continue
            posts.append(
                {
                    "id": 4900000 + number,
                    "slug": slug,
                    "date": "2024-01-01T00:00:00",
                    # Ссылка ведёт на бэкенд-хост, где /chapter/* закрыт WAF.
                    "link": f"https://chap.heliosarchive.online/chapter/{code}-{number}",
                    "acf": {
                        "novel_code": int(code),
                        "chapter_number": number,
                        "novel_name": NOVEL_NAME,
                        "ch_name": f"Chapter {number}: The Title / Part 2",
                    },
                }
            )
        self._send(posts)

    # ---------------------------------------------------------------- витрина

    def _chapter(self, path, rec):
        rec.enter()
        try:
            code, _, number = path.rsplit("/", 1)[-1].partition("-")
            number = int(number)

            with rec.lock:
                rec.chapter_headers.append(dict(self.headers))
                rec.chapter_hits[number] = rec.chapter_hits.get(number, 0) + 1

            if number in BLOCKED:
                self._send_html(CLOUDFLARE_PAGE, status=403)
                return
            if number in FLAKY:
                self._send({"error": "boom"}, status=500)
                return
            if MockHandler.serve_cloudflare:
                self._send_html(CLOUDFLARE_PAGE, status=200)
                return

            self._send_html(
                CHAPTER_HTML.format(
                    novel=NOVEL_NAME,
                    title=f"Chapter {number}: The Title / Part 2",
                    n=number,
                    code=code,
                    prev=number - 1,
                    next=number + 1,
                )
            )
        finally:
            rec.leave()


class MockSite:
    """Поднимает мок и подменяет адреса обоих хостов на него."""

    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.recorder = Recorder()
        self.server.recorder = self.recorder
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        self._saved = (client_mod.BASE, client_mod.API, client_mod.SITE, api.BASE, api.API, api.SITE)
        client_mod.BASE = api.BASE = self.base
        client_mod.API = api.API = f"{self.base}/wp-json/wp/v2"
        client_mod.SITE = api.SITE = self.base
        return self

    def __exit__(self, *exc):
        (client_mod.BASE, client_mod.API, client_mod.SITE,
         api.BASE, api.API, api.SITE) = self._saved
        self.server.shutdown()
        self.server.server_close()


# --------------------------------------------------------------- чистые функции


class TestNames(unittest.TestCase):
    def test_sanitize_strips_forbidden(self):
        self.assertEqual(sanitize_filename('Ch 1: A/B "quote" <tag>?'), "Ch 1_ A_B _quote_ _tag__")

    def test_sanitize_trailing_dot_and_space(self):
        self.assertEqual(sanitize_filename("Название. "), "Название")

    def test_sanitize_empty_falls_back(self):
        self.assertEqual(sanitize_filename("   ", fallback="x"), "x")
        self.assertEqual(sanitize_filename("///"), "___")

    def test_sanitize_reserved_windows_name(self):
        self.assertEqual(sanitize_filename("CON"), "_CON")

    def test_sanitize_length_capped(self):
        self.assertLessEqual(len(sanitize_filename("a" * 500)), 120)

    def test_sanitize_keeps_cyrillic(self):
        self.assertEqual(sanitize_filename("Глава 1: Начало"), "Глава 1_ Начало")

    def test_chapter_filename_zero_padded(self):
        self.assertEqual(chapter_filename(7, "Start"), "0007 - Start.txt")
        self.assertEqual(chapter_filename(1234, "X"), "1234 - X.txt")
        names = sorted(chapter_filename(n, "T") for n in (1, 2, 10, 100, 1000))
        self.assertEqual(names[0], "0001 - T.txt")
        self.assertEqual(names[-1], "1000 - T.txt")


class TestInputParsing(unittest.TestCase):
    def test_numeric_code(self):
        self.assertEqual(api.parse_input("6615"), ("code", "6615"))

    def test_chapter_url_gives_code_without_network(self):
        for link in (
            "https://chap.heliosarchive.online/chapter/6615-200",
            "https://www.mvlempyr.io/chapter/6615-1",
        ):
            self.assertEqual(api.parse_input(link), ("code", "6615"))

    def test_showcase_url_gives_slug(self):
        self.assertEqual(
            api.parse_input("https://www.mvlempyr.io/novel/insect-tamers-ascension"),
            ("slug", NOVEL_SLUG),
        )

    def test_url_with_query_and_trailing_slash(self):
        self.assertEqual(
            api.parse_input("https://www.mvlempyr.io/novel/some-book/?ref=x"),
            ("slug", "some-book"),
        )

    def test_bare_slug(self):
        self.assertEqual(api.parse_input("  some-book  "), ("slug", "some-book"))

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            api.parse_input("   ")

    def test_slugify(self):
        self.assertEqual(api.slugify("Insect Tamer's Ascension"), NOVEL_SLUG)
        self.assertEqual(api.slugify("A & B: Vol. 2"), "a-and-b-vol-2")


class TestUrls(unittest.TestCase):
    def test_chapter_url_points_at_storefront(self):
        self.assertEqual(
            client_mod.chapter_url(6615, 200), "https://www.mvlempyr.io/chapter/6615-200"
        )

    def test_novel_url(self):
        self.assertEqual(
            client_mod.novel_url(NOVEL_SLUG),
            "https://www.mvlempyr.io/novel/insect-tamers-ascension",
        )


class TestStrippedResponse(unittest.TestCase):
    """Массив пустых объектов — испорченный запрос, а не «не найдено»."""

    def test_empty_lists_detected(self):
        with self.assertRaises(api.StrippedResponse):
            api._novels_from_response([[]])

    def test_several_empty_objects_detected(self):
        with self.assertRaises(api.StrippedResponse):
            api._novels_from_response([{}, {}])

    def test_message_names_the_cause(self):
        with self.assertRaises(api.StrippedResponse) as ctx:
            api._novels_from_response([[]])
        self.assertIn("_fields", str(ctx.exception))

    def test_genuinely_empty_result_is_not_an_error(self):
        self.assertEqual(api._novels_from_response([]), [])


class TestCloudflareDetection(unittest.TestCase):
    def test_block_page_detected(self):
        self.assertTrue(api.looks_like_cloudflare(CLOUDFLARE_PAGE))

    def test_normal_chapter_not_flagged(self):
        html = CHAPTER_HTML.format(novel="N", title="T", n=1, code=1, prev=0, next=2)
        self.assertFalse(api.looks_like_cloudflare(html))

    def test_empty_not_flagged(self):
        self.assertFalse(api.looks_like_cloudflare(""))


class TestHtmlParsing(unittest.TestCase):
    def page(self, n=3):
        return CHAPTER_HTML.format(
            novel=NOVEL_NAME, title=f"Chapter {n}: T", n=n, code=NOVEL_CODE, prev=n - 1, next=n + 1
        )

    def test_parse_chapter_page(self):
        title, text = api.parse_chapter_page(self.page())
        self.assertEqual(title, "Chapter 3: T")
        self.assertEqual(text, "First line of chapter 3.\n\n*\n\nSecond line of chapter 3.")

    def test_scene_separator_kept(self):
        _, text = api.parse_chapter_page(self.page())
        self.assertIn("\n\n*\n\n", text)

    def test_ads_dropped(self):
        _, text = api.parse_chapter_page(self.page())
        self.assertNotIn("premium", text)
        self.assertNotIn("Sponsored", text)

    def test_blank_paragraphs_dropped(self):
        _, text = api.parse_chapter_page(self.page())
        self.assertNotIn("\n\n\n", text)

    def test_missing_chapter_block_raises(self):
        with self.assertRaises(ValueError):
            api.parse_chapter_page("<html><body><p>nothing here</p></body></html>")

    def test_empty_chapter_block_raises(self):
        with self.assertRaises(ValueError):
            api.parse_chapter_page('<div id="chapter"></div>')

    def test_nav_links(self):
        prev, nxt = api.parse_nav_links(self.page(3))
        self.assertEqual(api.chapter_number_from_link(prev, NOVEL_CODE), 2)
        self.assertEqual(api.chapter_number_from_link(nxt, NOVEL_CODE), 4)

    def test_extract_paragraphs_on_fragment(self):
        self.assertEqual(api.extract_paragraphs("<p>a</p><p>b</p>"), ["a", "b"])

    def test_extract_paragraphs_empty(self):
        self.assertEqual(api.extract_paragraphs(""), [])
        self.assertEqual(api.extract_paragraphs("   "), [])

    def test_extract_paragraphs_br_fallback(self):
        self.assertEqual(api.extract_paragraphs("one<br>two"), ["one", "two"])

    def test_nbsp_normalised(self):
        self.assertEqual(api.extract_paragraphs("<p>a\xa0\xa0b</p>"), ["a b"])


class TestRanges(unittest.TestCase):
    def test_compact(self):
        self.assertEqual(_compact_ranges([1, 2, 3, 7, 9, 10]), "1-3, 7, 9-10")
        self.assertEqual(_compact_ranges([]), "")
        self.assertEqual(_compact_ranges([5]), "5")


class TestParamEncoding(unittest.TestCase):
    def test_repeated_keys_preserved(self):
        encoded = client_mod.encode_params([("slug[]", "6615-1"), ("slug[]", "6615-2")])
        self.assertEqual(encoded, "slug%5B%5D=6615-1&slug%5B%5D=6615-2")


class TestSiteClientConfig(unittest.TestCase):
    def test_403_blocks_but_429_does_not(self):
        # 403 — «тебе сюда нельзя», меняем прокси. 429 — «слишком часто»,
        # прокси оставляем и ждём, поэтому в block_statuses его быть не должно.
        self.assertEqual(SiteClient.block_statuses, frozenset({403}))
        self.assertTrue(SiteClient.raise_on_rate_limit)

    def test_browser_headers_present(self):
        client = SiteClient(referer="https://www.mvlempyr.io/novel/x")
        for header in ("Accept", "Accept-Language", "Referer", "Sec-Fetch-Dest",
                       "Sec-Fetch-Mode", "Sec-Fetch-Site", "Upgrade-Insecure-Requests"):
            self.assertIn(header, client.headers)
        self.assertEqual(client.headers["Referer"], "https://www.mvlempyr.io/novel/x")

    def test_api_client_still_retries_429(self):
        self.assertEqual(Client.block_statuses, frozenset())


class TestStopIsNoticedDuringRetries(unittest.TestCase):
    """«Остановить» ждало всю лесенку повторов и выглядело сломанным.

    Между попытками клиент спал `2**attempt` секунд обычным `time.sleep`.
    При трёх попытках это шесть секунд на главу, а с подменой прокси и
    того больше: нажатие замечалось только на следующей главе.
    """

    class Dead:
        """Сессия, которая всегда молчит."""

        def __init__(self, seen):
            self.seen = seen

        def get(self, *args, **kwargs):
            self.seen.append(1)
            raise OSError("не отвечает")

        def close(self):
            pass

    def client(self, cancel=None, attempts=3):
        self.tries = []
        client = Client(max_attempts=attempts, cancel=cancel)
        client._session = lambda: self.Dead(self.tries)
        return client

    def test_a_set_flag_stops_it_without_waiting(self):
        stop = threading.Event()
        stop.set()
        began = time.monotonic()

        with self.assertRaises(NetworkError):
            self.client(stop).get("http://example.invalid/глава")

        # Шесть секунд ожидания превратились бы в провал по времени.
        self.assertLess(time.monotonic() - began, 1.0)

    def test_it_does_not_even_start_a_request(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(NetworkError):
            self.client(stop).get("http://example.invalid/глава")
        self.assertEqual(self.tries, [], "запрос ушёл после нажатия «Остановить»")

    def test_the_reason_says_it_was_stopped(self):
        """Иначе по журналу не понять: остановили или сам сдался."""
        stop = threading.Event()
        stop.set()
        with self.assertRaises(NetworkError) as caught:
            self.client(stop).get("http://example.invalid/глава")
        self.assertIn("остановлено", str(caught.exception))

    def test_the_flag_set_midway_cuts_the_wait_short(self):
        stop = threading.Event()
        client = self.client(stop, attempts=3)
        threading.Timer(0.2, stop.set).start()
        began = time.monotonic()

        with self.assertRaises(NetworkError):
            client.get("http://example.invalid/глава")

        self.assertLess(time.monotonic() - began, 2.5)
        self.assertTrue(self.tries, "до нажатия попытки должны были идти")

    def test_without_a_flag_nothing_changes(self):
        """Клиент без флажка ведёт себя как раньше — повторяет и сдаётся."""
        with self.assertRaises(NetworkError) as caught:
            self.client(None, attempts=1).get("http://example.invalid/глава")
        self.assertEqual(len(self.tries), 1)
        self.assertIn("после 1 попыток", str(caught.exception))


class TestTheStopFlagReachesEveryone(unittest.TestCase):
    """Флажок бесполезен, пока о нём не знают те, кто ждёт.

    Клиенты витрины заводит качалка, а свой клиент мимо неё может
    завести источник — и тогда сказать ему про нажатие некому.
    """

    def novel(self):
        return api.Novel(code=1, name="Книга", slug="kniga", total_chapters=2)

    def test_the_session_of_the_site_knows_about_it(self):
        loader = Downloader()
        self.assertIs(loader._new_session(self.novel()).cancel, loader.cancel)

    def test_the_clients_of_the_threads_know_about_it(self):
        loader = Downloader()
        make = loader._make_site_client(self.novel())
        self.assertIs(make().cancel, loader.cancel)

    def test_the_source_is_told(self):
        """Посредник ходит своим клиентом — иначе он ждёт свою лесенку."""
        class Source:
            cancel = None

        source = Source()
        loader = Downloader(source=source)
        self.assertIs(source.cancel, loader.cancel)


class TestPauseHoldsTheRunInstead(unittest.TestCase):
    """Обрыв сети не должен заканчивать книгу на середине.

    Прогон встаёт на границе главы и ждёт: начатую надо дописать, иначе
    на диске останется огрызок. Скачанное никуда не девается,
    продолжение идёт с той же главы.
    """

    class Source:
        needs_proxy = False
        cancel = None
        timeouts: dict = {}

        def __init__(self, seen, gate):
            self.seen, self.gate = seen, gate

        def toc(self, client, novel, first=1, last=None, on_progress=None):
            rows = [api.Chapter(number=n, post_id=str(n))
                    for n in range(first, (last or 6) + 1)]
            return api.Toc(chapters=rows, missing=[])

        def chapter(self, client, chapter):
            self.seen.append(chapter.number)
            self.gate.set()
            return f"Глава {chapter.number}", "Текст главы."

    def run_in_background(self):
        import shutil
        import tempfile

        for module, name in ((client_mod, "SITE_PAUSE_RANGE"),
                             (downloader_mod, "BATCH_PAUSE_RANGE")):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, (0, 0))

        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.seen: list[int] = []
        self.gate = threading.Event()
        self.pause = threading.Event()
        self.stop = threading.Event()

        loader = Downloader(source=self.Source(self.seen, self.gate),
                            threads=1, probe=False,
                            cancel_event=self.stop, pause_event=self.pause)
        novel = api.Novel(code=1, name="Книга", slug="k", total_chapters=6)
        worker = threading.Thread(
            target=lambda: loader.run(novel, Path(folder)), daemon=True)
        worker.start()
        self.addCleanup(self.stop.set)
        self.addCleanup(worker.join, 5)
        return loader, worker

    def test_a_paused_run_stops_taking_chapters(self):
        loader, worker = self.run_in_background()
        self.assertTrue(self.gate.wait(5), "прогон не начался")

        self.pause.set()
        time.sleep(0.4)
        held = len(self.seen)
        time.sleep(0.4)

        self.assertEqual(len(self.seen), held, "на паузе главы продолжали идти")

    def test_resuming_carries_on_from_the_same_place(self):
        loader, worker = self.run_in_background()
        self.assertTrue(self.gate.wait(5))
        self.pause.set()
        time.sleep(0.3)
        held = list(self.seen)

        self.pause.clear()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive(), "прогон не продолжился")
        self.assertEqual(self.seen[:len(held)], held, "главы пошли заново")
        self.assertEqual(self.seen[-1], 6, "книга не дошла до конца")

    def test_stopping_wakes_it_out_of_the_pause(self):
        """Иначе из паузы было бы не выйти вовсе."""
        loader, worker = self.run_in_background()
        self.assertTrue(self.gate.wait(5))
        self.pause.set()
        time.sleep(0.3)

        self.stop.set()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive(), "отмена не разбудила паузу")

    def test_the_screen_is_told_it_is_a_pause(self):
        """«Ничего не происходит» без пояснения читается как зависание."""
        said = []
        loader = Downloader(threads=1, probe=False,
                            on_progress=lambda p: said.append(
                                (p.stage, p.message)))
        loader.paused.set()
        threading.Timer(0.3, loader.paused.clear).start()
        loader._check_cancel()

        self.assertIn("paused", [stage for stage, _ in said])
        self.assertTrue(any("Пауза" in text for _, text in said))


class TestWaitingTimesReachTheChapters(unittest.TestCase):
    """Выставленные сроки ожидания не доходили до скачивания глав.

    `Client(timeout=…)` в веб-слое — это клиент оглавления. Главы качает
    клиент витрины, который качалка заводит сама, и заводила с
    умолчаниями: в журнале стояло «15003 ms» независимо от того, что
    выставлено на экране, и настройка выглядела не работающей.
    """

    def novel(self):
        return api.Novel(code=1, name="Книга", slug="kniga", total_chapters=2)

    def loader(self, **kwargs):
        return Downloader(timeout=77, connect_timeout=9, **kwargs)

    def test_the_session_of_the_site_gets_them(self):
        client = self.loader()._new_session(self.novel())
        self.assertEqual((client.timeout, client.connect_timeout), (77, 9))

    def test_the_clients_of_the_threads_get_them(self):
        make = self.loader()._make_site_client(self.novel())
        client = make()
        self.assertEqual((client.timeout, client.connect_timeout), (77, 9))

    def test_the_source_is_told_as_well(self):
        """Источник со своим клиентом иначе ждёт по-своему."""
        class Source:
            cancel = None
            timeouts: dict = {}

        source = Source()
        self.loader(source=source)
        self.assertEqual(source.timeouts,
                         {"timeout": 77, "connect_timeout": 9})

    def test_nothing_is_forced_when_nothing_was_asked(self):
        """Не выставлено — у клиента свои умолчания, подменять их нечем."""
        loader = Downloader()
        self.assertEqual(loader._timeouts(), {})
        client = loader._new_session(self.novel())
        self.assertEqual(client.timeout, client_mod.TIMEOUT)
        self.assertEqual(client.connect_timeout, client_mod.CONNECT_TIMEOUT)


# ------------------------------------------------------------- интеграционные


class MockSiteTestCase(unittest.TestCase):
    """Общая обвязка: мок поднят, паузы обнулены."""

    def setUp(self):
        MockHandler.serve_cloudflare = False
        BLOCKED.clear()
        self.site = MockSite().__enter__()
        self.rec = self.site.recorder
        self.client = Client()
        self.tmp = TemporaryDirectory()
        self._pauses = (client_mod.PAUSE_RANGE, client_mod.SITE_PAUSE_RANGE)
        client_mod.PAUSE_RANGE = client_mod.SITE_PAUSE_RANGE = (0, 0)

    def tearDown(self):
        client_mod.PAUSE_RANGE, client_mod.SITE_PAUSE_RANGE = self._pauses
        self.client.close()
        self.tmp.cleanup()
        self.site.__exit__()
        BLOCKED.clear()

    def make_downloader(self, **kwargs):
        # max_attempts=1: в тестах не ждём экспоненциальный backoff.
        site = SiteClient(referer="http://x/novel/y", max_attempts=1)
        self.addCleanup(site.close)
        return Downloader(client=self.client, site_client=site, **kwargs)

    def run_download(self, **kwargs):
        novel = api.find_novel(self.client, str(NOVEL_CODE))
        out = prepare_output_dir(self.tmp.name, novel.name)
        return novel, out, self.make_downloader().run(novel, out, **kwargs)


class TestCatalog(MockSiteTestCase):
    def test_find_by_slug_uses_slug_param(self):
        novel = api.find_novel(self.client, f"https://www.mvlempyr.io/novel/{NOVEL_SLUG}")
        self.assertEqual(novel.code, NOVEL_CODE)
        self.assertEqual(novel.total_chapters, TOTAL)
        self.assertEqual(novel.name, NOVEL_NAME)
        self.assertEqual(self.rec.novel_queries[0].get("slug"), NOVEL_SLUG)

    def test_find_by_bare_slug(self):
        self.assertEqual(api.find_novel(self.client, NOVEL_SLUG).code, NOVEL_CODE)

    def test_find_by_code(self):
        self.assertEqual(api.find_novel(self.client, str(NOVEL_CODE)).code, NOVEL_CODE)

    def test_chapter_link_resolves_code_without_extra_lookup(self):
        novel = api.find_novel(
            self.client, f"https://www.mvlempyr.io/chapter/{NOVEL_CODE}-200"
        )
        self.assertEqual(novel.code, NOVEL_CODE)

    def test_find_unknown_raises(self):
        with self.assertRaises(LookupError):
            api.find_novel(self.client, "definitely-not-a-real-book-xyz")

    def test_no_fields_param_ever_sent(self):
        api.find_novel(self.client, NOVEL_SLUG)
        api.search_novels(self.client, "insect")
        api.fetch_toc(self.client, api.find_novel(self.client, NOVEL_SLUG), last=3)
        self.assertFalse(self.rec.saw_fields_param, "_fields не должен уходить на сервер")

    def test_novel_page_url(self):
        novel = api.find_novel(self.client, NOVEL_SLUG)
        self.assertTrue(novel.page_url.endswith(f"/novel/{NOVEL_SLUG}"))


class TestToc(MockSiteTestCase):
    def test_toc_reports_holes(self):
        novel = api.find_novel(self.client, NOVEL_SLUG)
        toc = api.fetch_toc(self.client, novel)
        self.assertEqual(toc.missing, sorted(HOLES))
        self.assertEqual([c.number for c in toc.chapters],
                         sorted(set(range(1, TOTAL + 1)) - HOLES))

    def test_ch_name_comes_from_api(self):
        novel = api.find_novel(self.client, NOVEL_SLUG)
        toc = api.fetch_toc(self.client, novel, last=2)
        self.assertEqual(toc.chapters[0].ch_name, "Chapter 1: The Title / Part 2")

    def test_chapter_links_point_at_storefront(self):
        novel = api.find_novel(self.client, NOVEL_SLUG)
        toc = api.fetch_toc(self.client, novel, last=3)
        for chapter in toc.chapters:
            self.assertIn("/chapter/", chapter.link)
            self.assertNotIn("heliosarchive", chapter.link)

    def test_chapter_links_export(self):
        novel = api.find_novel(self.client, NOVEL_SLUG)
        toc = api.fetch_toc(self.client, novel, first=1, last=3)
        links = api.chapter_links(novel, toc.chapters)
        self.assertEqual(len(links), 3)
        self.assertTrue(links[0].endswith(f"/chapter/{NOVEL_CODE}-1"))


class TestDownload(MockSiteTestCase):
    def test_full_run(self):
        _, out, report = self.run_download()
        self.assertEqual(report.mode, api.SOURCE_SITE)
        self.assertEqual(report.downloaded, TOTAL - len(HOLES) - len(FLAKY))
        self.assertEqual(report.failed_chapters, sorted(FLAKY))
        self.assertEqual(report.missing_in_toc, sorted(HOLES))
        self.assertIsNone(report.blocked_at)

    def test_single_threaded(self):
        self.run_download()
        self.assertEqual(self.rec.max_in_flight, 1, "витрину нельзя опрашивать параллельно")

    def test_browser_headers_sent_to_storefront(self):
        self.run_download(last=2)
        headers = self.rec.chapter_headers[0]
        self.assertIn("Referer", headers)
        self.assertEqual(headers.get("Sec-Fetch-Mode"), "navigate")
        self.assertEqual(headers.get("Upgrade-Insecure-Requests"), "1")

    def test_saved_file_layout(self):
        _, out, _ = self.run_download()
        path = out / "0001 - Chapter 1_ The Title _ Part 2.txt"
        self.assertTrue(path.exists(), sorted(p.name for p in out.glob("*.txt")))
        lines = path.read_text(encoding="utf-8").split("\n")
        self.assertEqual(lines[0], NOVEL_NAME)
        self.assertEqual(lines[1], "Chapter 1: The Title / Part 2")
        self.assertEqual(lines[2], "")

    def test_slash_in_title_does_not_make_subdir(self):
        _, out, _ = self.run_download(last=2)
        self.assertFalse(any(p.is_dir() for p in out.iterdir()))

    def test_ads_not_saved(self):
        _, out, _ = self.run_download(last=1)
        body = next(out.glob("*.txt")).read_text(encoding="utf-8")
        self.assertNotIn("premium", body)

    def test_errors_log_written(self):
        _, out, _ = self.run_download()
        log_text = (out / "errors.log").read_text(encoding="utf-8")
        for number in FLAKY:
            self.assertIn(f"глава {number}", log_text)
        self.assertIn("нет в оглавлении", log_text)

    def test_range_limits_download(self):
        _, out, report = self.run_download(first=2, last=4)
        self.assertEqual(sorted(int(p.name[:4]) for p in out.glob("*.txt")), [2, 3, 4])
        self.assertEqual(report.downloaded, 3)

    def test_state_file_written(self):
        _, out, _ = self.run_download()
        state = State(out / "state.json")
        # В state.json книга пишется тем же `to_dict`, что уходит на
        # экран, а там код — строка (1.2 ТЗ).
        self.assertEqual(state.data["novel"]["code"], str(NOVEL_CODE))
        self.assertEqual(state.data["mode"], api.SOURCE_SITE)
        self.assertIn("1", state.data["downloaded"])

    def test_corrupt_state_does_not_crash(self):
        _, out, _ = self.run_download(last=2)
        (out / "state.json").write_text("{ broken", encoding="utf-8")
        self.assertEqual(State(out / "state.json").data["downloaded"], {})

    def test_verify_report(self):
        _, out, _ = self.run_download()
        report = verify(out)
        self.assertEqual(report["total_chapters"], TOTAL)
        self.assertEqual(report["on_disk"], TOTAL - len(HOLES) - len(FLAKY))
        self.assertEqual(report["missing"], sorted(HOLES | FLAKY))
        self.assertEqual(report["missing_compact"], "7, 9")

    def test_cancel_stops_run(self):
        novel = api.find_novel(self.client, NOVEL_SLUG)
        out = prepare_output_dir(self.tmp.name, "cancelme")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.make_downloader(cancel_event=cancel).run(novel, out)


class TestResume(MockSiteTestCase):
    def test_resume_skips_finished(self):
        novel, out, first_report = self.run_download()
        self.assertGreater(first_report.downloaded, 0)

        second = self.make_downloader().run(novel, out)
        self.assertEqual(second.downloaded, 0)
        self.assertEqual(second.skipped, TOTAL - len(HOLES) - len(FLAKY))

    def test_resume_redownloads_deleted_file(self):
        novel, out, _ = self.run_download()
        victim = sorted(out.glob("*.txt"))[0]
        victim.unlink()

        second = self.make_downloader().run(novel, out)
        self.assertEqual(second.downloaded, 1)
        self.assertTrue(victim.exists())


class TestBlocking(MockSiteTestCase):
    """403 останавливает прогон целиком и не ретраится."""

    def test_run_stops_at_block(self):
        BLOCKED.add(5)
        _, out, report = self.run_download()
        self.assertEqual(report.blocked_at, 5)
        # Главы после пятой не качались.
        self.assertEqual(sorted(int(p.name[:4]) for p in out.glob("*.txt")), [1, 2, 3, 4])

    def test_block_is_not_retried(self):
        BLOCKED.add(3)
        self.run_download()
        self.assertEqual(self.rec.chapter_hits[3], 1, "403 ретраить нельзя")

    def test_block_logged(self):
        BLOCKED.add(2)
        _, out, _ = self.run_download()
        self.assertIn("БЛОКИРОВКА", (out / "errors.log").read_text(encoding="utf-8"))

    def test_resume_after_block_continues(self):
        BLOCKED.add(4)
        novel, out, first = self.run_download()
        self.assertEqual(first.blocked_at, 4)

        BLOCKED.clear()
        second = self.make_downloader().run(novel, out)
        self.assertIsNone(second.blocked_at)
        self.assertGreater(second.downloaded, 0)
        self.assertTrue((out / "0004 - Chapter 4_ The Title _ Part 2.txt").exists())

    def test_cloudflare_stub_not_saved_as_chapter(self):
        """Заглушка с кодом 200 не должна попасть в файл главы."""
        MockHandler.serve_cloudflare = True
        _, out, report = self.run_download()
        self.assertEqual(report.blocked_at, 1)
        self.assertEqual(list(out.glob("*.txt")), [])

    def test_blocked_raises_for_direct_fetch(self):
        BLOCKED.add(1)
        novel = api.find_novel(self.client, NOVEL_SLUG)
        toc = api.fetch_toc(self.client, novel, last=1)
        site = SiteClient(referer=novel.page_url, max_attempts=1)
        self.addCleanup(site.close)
        with self.assertRaises(Blocked):
            api.fetch_chapter(site, toc.chapters[0])


class TestWebApp(MockSiteTestCase):
    def setUp(self):
        super().setUp()
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()

    def test_index_served(self):
        self.assertEqual(self.app.get("/").status_code, 200)

    def test_find_endpoint(self):
        res = self.app.post("/api/find", json={"query": NOVEL_SLUG})
        self.assertEqual(res.status_code, 200)
        # Код уходит строкой: у Фанкью он в девятнадцать разрядов, а
        # числом такой длины JavaScript не хранит (1.2 ТЗ).
        self.assertEqual(res.get_json()["novel"]["code"], str(NOVEL_CODE))

    def test_find_empty_query(self):
        self.assertEqual(self.app.post("/api/find", json={"query": ""}).status_code, 400)

    def test_find_unknown(self):
        res = self.app.post("/api/find", json={"query": "no-such-book-at-all"})
        self.assertEqual(res.status_code, 404)

    def test_browse_lists_dirs(self):
        (Path(self.tmp.name) / "sub").mkdir()
        data = self.app.get("/api/browse", query_string={"path": self.tmp.name}).get_json()
        self.assertEqual([d["name"] for d in data["dirs"]], ["sub"])
        self.assertTrue(data["writable"])

    def test_links_endpoint(self):
        novel = self.app.post("/api/find", json={"query": NOVEL_SLUG}).get_json()["novel"]
        data = self.app.post("/api/links", json={"novel": novel, "first": 1, "last": 5}).get_json()
        self.assertEqual(len(data["links"]), 5)
        self.assertTrue(data["links"][0].endswith(f"/chapter/{NOVEL_CODE}-1"))

    def test_the_number_of_threads_reaches_the_job(self):
        """Страница не присылала это поле, и сервер брал умолчание — один.

        Выставленное на экране число не влияло ни на что: книга качалась
        в одну нитку, сколько бы потоков ни просили.
        """
        from webapp.app import JOBS

        novel = self.app.post("/api/find",
                              json={"query": NOVEL_SLUG}).get_json()["novel"]
        res = self.app.post("/api/start", json={
            "novel": novel, "base": self.tmp.name, "folder": "Три потока",
            "first": 1, "last": 3, "threads": 3, "mode": "manual"})

        job_id = res.get_json()["job"]["id"]
        self.assertEqual(JOBS[job_id].meta["threads"], 3)
        JOBS[job_id].cancel.set()
        JOBS[job_id].thread.join(timeout=60)

    def test_without_that_field_it_is_still_one_thread(self):
        """Умолчание не меняем: молча качать в три потока тоже неверно."""
        from webapp.app import JOBS

        novel = self.app.post("/api/find",
                              json={"query": NOVEL_SLUG}).get_json()["novel"]
        res = self.app.post("/api/start", json={
            "novel": novel, "base": self.tmp.name, "folder": "Умолчание",
            "first": 1, "last": 2})

        job_id = res.get_json()["job"]["id"]
        self.assertEqual(JOBS[job_id].meta["threads"], 1)
        JOBS[job_id].thread.join(timeout=60)

    def test_start_requires_folder(self):
        res = self.app.post(
            "/api/start", json={"novel": {"code": NOVEL_CODE}, "base": self.tmp.name, "folder": ""}
        )
        self.assertEqual(res.status_code, 400)

    def test_start_and_finish_job(self):
        novel = self.app.post("/api/find", json={"query": NOVEL_SLUG}).get_json()["novel"]
        res = self.app.post(
            "/api/start",
            json={"novel": novel, "base": self.tmp.name, "folder": "My Book", "first": 1, "last": 5},
        )
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["job"]["id"]

        from webapp.app import JOBS

        JOBS[job_id].thread.join(timeout=60)
        job = self.app.get(f"/api/job/{job_id}").get_json()["job"]

        self.assertIsNone(job["error"])
        self.assertEqual(job["progress"]["stage"], "done")
        out = Path(self.tmp.name) / "My Book"
        # Диапазон 1..5: дыра (7) и сбойная глава (9) в него не попадают.
        self.assertEqual(sorted(int(p.name[:4]) for p in out.glob("*.txt")), [1, 2, 3, 4, 5])

    def test_job_not_found(self):
        self.assertEqual(self.app.get("/api/job/nope").status_code, 404)


class TestProxyParsing(unittest.TestCase):
    def test_full_line(self):
        proxy = proxies.Proxy.parse("203.0.113.10:8000:bob:hunter2")
        self.assertEqual(proxy.host, "203.0.113.10")
        self.assertEqual(proxy.port, 8000)
        self.assertEqual(proxy.username, "bob")
        self.assertEqual(proxy.url, "http://bob:hunter2@203.0.113.10:8000")

    def test_open_proxy_without_credentials(self):
        proxy = proxies.Proxy.parse("192.0.2.1:3128")
        self.assertEqual(proxy.url, "http://192.0.2.1:3128")
        self.assertTrue(proxy.open_proxy)
        self.assertEqual(proxy.kind, "открытый")

    def test_open_proxy_with_empty_fields(self):
        proxy = proxies.Proxy.parse("192.0.2.1:3128::")
        self.assertTrue(proxy.open_proxy)
        self.assertEqual(proxy.url, "http://192.0.2.1:3128")

    def test_credentials_before_at_sign(self):
        proxy = proxies.Proxy.parse("bob:hunter2@203.0.113.10:8000")
        self.assertEqual(proxy.url, "http://bob:hunter2@203.0.113.10:8000")
        self.assertFalse(proxy.open_proxy)

    def test_scheme_prefix_ignored(self):
        self.assertEqual(proxies.Proxy.parse("http://192.0.2.1:3128").label, "192.0.2.1:3128")
        self.assertEqual(
            proxies.Proxy.parse("socks5://u:p@192.0.2.1:1080").label, "192.0.2.1:1080"
        )

    def test_trailing_comment_ignored(self):
        proxy = proxies.Proxy.parse("192.0.2.1:3128   # общий, Германия")
        self.assertEqual(proxy.label, "192.0.2.1:3128")

    def test_authenticated_proxy_kind(self):
        self.assertEqual(proxies.Proxy.parse("1.1.1.1:80:u:passw").kind, "с ключом")

    def test_mixed_list_loads(self):
        """Платные и открытые адреса уживаются в одном файле."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "proxies.txt"
            path.write_text(
                "# с ключом\n1.1.1.1:80:user:passw\n"
                "u2:passw2@2.2.2.2:81\n\n"
                "# открытые\n3.3.3.3:3128\nhttp://4.4.4.4:8080\n",
                encoding="utf-8",
            )
            loaded = proxies.load_proxies(path)

        self.assertEqual(
            [(p.label, p.open_proxy) for p in loaded],
            [("1.1.1.1:80", False), ("2.2.2.2:81", False),
             ("3.3.3.3:3128", True), ("4.4.4.4:8080", True)],
        )

    def test_login_without_password_rejected(self):
        with self.assertRaises(ValueError):
            proxies.Proxy.parse("1.1.1.1:80:onlyuser")

    def test_comments_and_blanks_skipped(self):
        self.assertIsNone(proxies.Proxy.parse("   "))
        self.assertIsNone(proxies.Proxy.parse("# комментарий"))

    def test_malformed_rejected(self):
        for line in ("no-port", "1.2.3.4:abc", "1:2:3"):
            with self.assertRaises(ValueError, msg=line):
                proxies.Proxy.parse(line)

    def test_load_from_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "proxies.txt"
            path.write_text(
                "# список\n\n1.1.1.1:80:u:p\n2.2.2.2:81\nмусор\n", encoding="utf-8"
            )
            loaded = proxies.load_proxies(path)
        self.assertEqual([p.label for p in loaded], ["1.1.1.1:80", "2.2.2.2:81"])

    def test_empty_file_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "proxies.txt"
            path.write_text("# только комментарий\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                proxies.load_proxies(path)

    def test_missing_file_rejected(self):
        with self.assertRaises(FileNotFoundError):
            proxies.load_proxies("/nonexistent/proxies.txt")


class TestPasswordMasking(unittest.TestCase):
    """Пароли не должны попадать ни в лог, ни в отчёты, ни в ошибки."""

    def setUp(self):
        self.proxy = proxies.Proxy.parse("198.51.100.9:8080:alice:s3cr3t-pass")

    def test_safe_url_masks_password(self):
        self.assertEqual(self.proxy.safe_url, "http://alice:***@198.51.100.9:8080")
        self.assertNotIn("s3cr3t-pass", self.proxy.safe_url)

    def test_str_is_masked(self):
        self.assertNotIn("s3cr3t-pass", str(self.proxy))

    def test_label_has_no_credentials(self):
        self.assertEqual(self.proxy.label, "198.51.100.9:8080")

    def test_to_dict_carries_no_password(self):
        self.assertNotIn("s3cr3t-pass", json.dumps(self.proxy.to_dict()))

    def test_scrub_removes_known_password_anywhere(self):
        text = "ConnectionError через http://alice:s3cr3t-pass@198.51.100.9:8080"
        cleaned = proxies.scrub(text)
        self.assertNotIn("s3cr3t-pass", cleaned)
        self.assertIn("***", cleaned)

    def test_scrub_masks_unknown_credentials_by_pattern(self):
        cleaned = proxies.scrub("http://someone:never-seen-before@10.0.0.1:9")
        self.assertNotIn("never-seen-before", cleaned)

    def test_short_password_does_not_mangle_unrelated_text(self):
        """Однобуквенный пароль не должен вырезать эту букву из всего лога."""
        proxies.Proxy.parse("10.0.0.9:80:u:p")
        self.assertEqual(proxies.scrub("HttpError: chapter 5"), "HttpError: chapter 5")

    def test_short_password_still_masked_inside_url(self):
        proxies.Proxy.parse("10.0.0.9:80:u:pw1")
        self.assertNotIn("pw1", proxies.scrub("http://u:pw1@10.0.0.9:80 отвалился"))

    def test_failure_report_has_no_password(self):
        pool = proxies.ProxyPool([self.proxy])
        self.proxy.disabled = True
        self.proxy.disabled_reason = "http://alice:s3cr3t-pass@198.51.100.9:8080 отвалился"
        self.assertNotIn("s3cr3t-pass", pool.failure_report())

    def test_table_has_no_password(self):
        pool = proxies.ProxyPool([self.proxy])
        self.assertNotIn("s3cr3t-pass", pool.table())


class TestProxyRanking(unittest.TestCase):
    def make(self, label, status, elapsed):
        proxy = proxies.Proxy.parse(label)
        proxy.alive = status is not None
        proxy.status = status
        proxy.elapsed = elapsed
        return proxy

    def setUp(self):
        self.slow = self.make("1.1.1.1:80", 200, 2.0)
        self.fast = self.make("2.2.2.2:80", 200, 0.4)
        self.forbidden = self.make("3.3.3.3:80", 403, 0.1)
        self.dead = self.make("4.4.4.4:80", None, None)
        self.pool = proxies.ProxyPool([self.slow, self.fast, self.forbidden, self.dead])
        self.pool._rank()

    def test_usable_sorted_by_speed(self):
        self.assertEqual(self.pool.current().label, "2.2.2.2:80")

    def test_403_kept_as_last_resort(self):
        # 403 «не проходит», но из списка не выбрасывается.
        self.assertFalse(self.forbidden.usable)
        self.assertTrue(self.forbidden.reachable)

    def test_dead_excluded_from_rotation(self):
        order = [p.label for p in self.pool._order]
        self.assertNotIn("4.4.4.4:80", order)
        self.assertEqual(order, ["2.2.2.2:80", "1.1.1.1:80", "3.3.3.3:80"])

    def test_usable_count(self):
        self.assertEqual(self.pool.usable_count, 2)

    def test_switch_moves_to_next_fastest(self):
        self.assertEqual(self.pool.current().label, "2.2.2.2:80")
        following = self.pool.switch("403")
        self.assertEqual(following.label, "1.1.1.1:80")
        self.assertTrue(self.fast.disabled)

    def test_switch_records_event(self):
        self.pool.switch("таймаут")
        self.assertEqual(len(self.pool.switches), 1)
        self.assertEqual(self.pool.switches[0].from_label, "2.2.2.2:80")
        self.assertEqual(self.pool.switches[0].reason, "таймаут")

    def test_exhausting_the_list_raises(self):
        self.pool.switch("a")
        self.pool.switch("b")
        with self.assertRaises(proxies.NoProxiesLeft):
            self.pool.switch("c")

    def test_failure_report_lists_addresses_and_reasons(self):
        self.pool.switch("таймаут")
        report = self.pool.failure_report()
        self.assertIn("2.2.2.2:80", report)
        self.assertIn("таймаут", report)
        self.assertIn("напрямую", report.lower())


class FakeSite:
    """Подменяет SiteClient: отдаёт заранее расписанные исходы по главам."""

    def __init__(self, script: dict[int, list]):
        self.script = script
        self.closed = False

    def get_text(self, url, params=None, headers=None):
        number = int(url.rsplit("-", 1)[-1])
        outcomes = self.script.get(number)
        outcome = outcomes.pop(0) if outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome
        return CHAPTER_HTML.format(
            novel=NOVEL_NAME, title=f"Chapter {number}", n=number,
            code=NOVEL_CODE, prev=number - 1, next=number + 1,
        )

    def close(self):
        self.closed = True


class TestProxySwitching(MockSiteTestCase):
    """Логика переключения: что меняет прокси, а что нет."""

    def setUp(self):
        super().setUp()
        self._cooldown = downloader_mod.RATE_LIMIT_COOLDOWN
        downloader_mod.RATE_LIMIT_COOLDOWN = 0  # не ждём минуту в тестах
        HOLES.clear()
        FLAKY.clear()

    def tearDown(self):
        downloader_mod.RATE_LIMIT_COOLDOWN = self._cooldown
        HOLES.add(7)
        FLAKY.add(9)
        super().tearDown()

    def make_pool(self, count=3):
        return proxies.ProxyPool(
            [proxies.Proxy.parse(f"10.0.0.{i}:8000:user:pw{i}") for i in range(1, count + 1)]
        )

    def run_with(self, script, pool=None, last=4):
        """Прогон с подменённой сессией витрины."""
        pool = pool or self.make_pool()
        novel = api.find_novel(self.client, NOVEL_SLUG)
        out = prepare_output_dir(self.tmp.name, "proxy-run")
        worker = Downloader(client=self.client, pool=pool)
        self.sessions = []

        def new_session(_novel):
            site = FakeSite(script)
            self.sessions.append(site)
            return site

        worker._new_session = new_session
        return pool, out, worker.run(novel, out, last=last)

    def test_403_switches_proxy_and_retries_same_chapter(self):
        script = {3: [Blocked("HTTP 403 — доступ закрыт", status=403)]}
        pool, out, report = self.run_with(script)

        self.assertEqual(report.proxy_switches, 1)
        self.assertEqual(pool.switches[0].to_label, "10.0.0.2:8000")
        # Глава, на которой сменили прокси, всё равно скачана.
        self.assertEqual(sorted(int(p.name[:4]) for p in out.glob("*.txt")), [1, 2, 3, 4])
        self.assertEqual(report.downloaded, 4)

    def test_network_error_switches_proxy(self):
        script = {2: [NetworkError("таймаут")]}
        pool, out, report = self.run_with(script)
        self.assertEqual(report.proxy_switches, 1)
        self.assertEqual(report.downloaded, 4)

    def test_new_session_per_proxy(self):
        script = {2: [Blocked("403", status=403)]}
        self.run_with(script)
        # Одна сессия на старте, вторая после переключения.
        self.assertEqual(len(self.sessions), 2)
        self.assertTrue(self.sessions[0].closed, "старая сессия должна закрываться")

    def test_cloudflare_stub_switches_proxy(self):
        # Заглушка приходит с кодом 200 — её ловит fetch_chapter.
        original = api.parse_chapter_page

        script = {1: [Blocked("заглушка Cloudflare", status=403)]}
        pool, out, report = self.run_with(script)
        self.assertEqual(report.proxy_switches, 1)
        self.assertIs(api.parse_chapter_page, original)

    def test_run_stops_when_proxies_run_out(self):
        # Каждая попытка падает — переключения съедят весь список.
        script = {n: [NetworkError("таймаут")] * 10 for n in range(1, 5)}
        pool, out, report = self.run_with(script, pool=self.make_pool(2))

        self.assertIn("Рабочих прокси не осталось", report.stopped_reason)
        self.assertEqual(report.downloaded, 0)
        self.assertIsNotNone(report.blocked_at)

    def test_failure_report_names_every_address(self):
        script = {n: [NetworkError("таймаут")] * 10 for n in range(1, 5)}
        _, _, report = self.run_with(script, pool=self.make_pool(2))
        self.assertIn("10.0.0.1:8000", report.stopped_reason)
        self.assertIn("10.0.0.2:8000", report.stopped_reason)

    def test_no_password_in_stopped_reason(self):
        script = {n: [NetworkError("http://user:pw1@10.0.0.1:8000 умер")] * 10
                  for n in range(1, 5)}
        _, out, report = self.run_with(script, pool=self.make_pool(2))
        self.assertNotIn("pw1", report.stopped_reason)
        self.assertNotIn("pw1", (out / "errors.log").read_text(encoding="utf-8"))

    # ------------------------------------------------------------------- 429

    def test_429_does_not_switch_proxy(self):
        script = {2: [RateLimited("HTTP 429", status=429)]}
        pool, out, report = self.run_with(script)

        self.assertEqual(report.proxy_switches, 0, "429 — не повод менять прокси")
        self.assertEqual(len(self.sessions), 1, "сессия остаётся прежней")
        self.assertEqual(report.downloaded, 4)

    def test_429_doubles_the_pause(self):
        script = {2: [RateLimited("HTTP 429", status=429)]}
        pool = self.make_pool()
        novel = api.find_novel(self.client, NOVEL_SLUG)
        out = prepare_output_dir(self.tmp.name, "pause-run")
        worker = Downloader(client=self.client, pool=pool)
        worker._new_session = lambda _n: FakeSite(script)

        worker.run(novel, out, last=3)
        self.assertEqual(worker.pause_multiplier, 2)

    def test_three_429_in_a_row_stops_the_run(self):
        script = {2: [RateLimited("HTTP 429", status=429)] * 5}
        pool, out, report = self.run_with(script)

        self.assertIn("429", report.stopped_reason)
        self.assertEqual(report.proxy_switches, 0)
        # Первая глава успела скачаться, дальше прогон встал.
        self.assertEqual(sorted(int(p.name[:4]) for p in out.glob("*.txt")), [1])


class TestProxyWebApi(MockSiteTestCase):
    def setUp(self):
        super().setUp()
        from webapp.app import app
        import webapp.app as webapp_module

        app.config["TESTING"] = True
        self.app = app.test_client()
        self.webapp = webapp_module
        self.addCleanup(setattr, webapp_module, "POOL", None)

        self.path = Path(self.tmp.name) / "proxies.txt"
        self.path.write_text("10.0.0.1:8000:user:topsecret\n", encoding="utf-8")

    def test_reload_reads_file_without_restart(self):
        res = self.app.post("/api/proxies/reload", json={"path": str(self.path)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["pool"]["total"], 1)

        self.path.write_text(
            "10.0.0.1:8000:user:topsecret\n10.0.0.2:8000:user:topsecret\n", encoding="utf-8"
        )
        res = self.app.post("/api/proxies/reload", json={"path": str(self.path)})
        self.assertEqual(res.get_json()["pool"]["total"], 2)

    def test_reload_missing_file_reports_error(self):
        res = self.app.post("/api/proxies/reload", json={"path": "/nope/proxies.txt"})
        self.assertEqual(res.status_code, 400)

    def test_state_endpoint_masks_passwords(self):
        self.app.post("/api/proxies/reload", json={"path": str(self.path)})
        body = self.app.get("/api/proxies").get_data(as_text=True)
        self.assertNotIn("topsecret", body)
        self.assertIn("***", body)

    def test_start_refused_when_no_usable_proxies(self):
        self.app.post("/api/proxies/reload", json={"path": str(self.path)})
        with self.webapp.POOL_LOCK:
            self.webapp.POOL.checked = True
            for proxy in self.webapp.POOL.proxies:
                proxy.alive = False

        novel = self.app.post("/api/find", json={"query": NOVEL_SLUG}).get_json()["novel"]
        res = self.app.post(
            "/api/start",
            json={"novel": novel, "base": self.tmp.name, "folder": "X", "first": 1, "last": 2},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Напрямую не идём", res.get_json()["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
