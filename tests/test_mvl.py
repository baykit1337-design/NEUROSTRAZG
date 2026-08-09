"""Тесты. Живой сайт в CI недоступен, поэтому весь пайплайн гоняем против
локального мок-сервера, повторяющего формат ответов WP REST."""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import api, client as client_mod  # noqa: E402
from mvl.client import Client  # noqa: E402
from mvl.downloader import Downloader, State, _compact_ranges, verify  # noqa: E402
from mvl.paths import chapter_filename, prepare_output_dir, sanitize_filename  # noqa: E402

NOVEL_CODE = 6615
NOVEL_NAME = "Insect Tamer's Ascension"
TOTAL = 12
HOLES = {7}  # главы, которых нет в каталоге
FLAKY = {9}  # глава, которая всегда отдаёт 500

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


class MockHandler(BaseHTTPRequestHandler):
    rest_serves_content = True  # переключаем в тестах

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
        query = parse_qs(url.query)

        if url.path == "/wp-json/wp/v2/mvl-novels":
            self._send(
                [
                    {
                        "name": NOVEL_NAME,
                        "slug": "insect-tamers-ascension-wp",
                        "novel-code": NOVEL_CODE,
                        "total-chapters": TOTAL,
                        "read-link": f"/chapter/{NOVEL_CODE}-1",
                        "author-name": "Someone",
                        "status": "Ongoing",
                    },
                    {
                        "name": "Unrelated Novel",
                        "slug": "unrelated",
                        "novel-code": 111,
                        "total-chapters": 3,
                    },
                ]
            )
            return

        if url.path == "/wp-json/wp/v2/posts":
            slugs = query.get("slug[]", [])
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
                        "link": f"{self.server.base}/chapter/{code}-{number}",
                        "acf": {
                            "novel_code": int(code),
                            "chapter_number": number,
                            "novel_name": NOVEL_NAME,
                            "ch_name": f"Chapter {number}: The Title / Part 2",
                        },
                    }
                )
            self._send(posts)
            return

        if url.path.startswith("/wp-json/wp/v2/posts/"):
            post_id = int(url.path.rsplit("/", 1)[-1])
            number = post_id - 4900000
            if number in FLAKY:
                self._send({"error": "boom"}, status=500)
                return
            rendered = ""
            if MockHandler.rest_serves_content:
                rendered = (
                    f"<p>First line of chapter {number}.</p><p>*</p>"
                    f"<p>Second line of chapter {number}.</p>"
                    f'<div class="ke400008d2"><p>Buy our premium subscription</p></div>'
                )
            self._send(
                {
                    "content": {"rendered": rendered},
                    "title": {"rendered": f"Chapter {number}"},
                }
            )
            return

        if url.path.startswith("/chapter/"):
            code, _, number = url.path.rsplit("/", 1)[-1].partition("-")
            number = int(number)
            if number in FLAKY:
                self._send({"error": "boom"}, status=500)
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
            return

        self._send({"error": "not found"}, status=404)


class MockSite:
    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.server.base = self.base
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        self._saved = (client_mod.BASE, client_mod.API, api.BASE, api.API)
        client_mod.BASE = api.BASE = self.base
        client_mod.API = api.API = f"{self.base}/wp-json/wp/v2"
        return self

    def __exit__(self, *exc):
        client_mod.BASE, client_mod.API, api.BASE, api.API = self._saved
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
        # Сортировка по имени должна совпадать с числовым порядком.
        names = sorted(chapter_filename(n, "T") for n in (1, 2, 10, 100, 1000))
        self.assertEqual(names[0], "0001 - T.txt")
        self.assertEqual(names[-1], "1000 - T.txt")


class TestInputParsing(unittest.TestCase):
    def test_numeric_code(self):
        self.assertEqual(api.parse_input("6615"), ("code", "6615"))

    def test_chapter_url_gives_code(self):
        self.assertEqual(
            api.parse_input("https://chap.heliosarchive.online/chapter/6615-200"),
            ("code", "6615"),
        )

    def test_showcase_url_gives_slug(self):
        self.assertEqual(
            api.parse_input("https://www.mvlempyr.io/novel/insect-tamers-ascension"),
            ("slug", "insect-tamers-ascension"),
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
        self.assertEqual(api.slugify("Insect Tamer's Ascension"), "insect-tamers-ascension")
        self.assertEqual(api.slugify("A & B: Vol. 2"), "a-and-b-vol-2")


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


# ------------------------------------------------------------- интеграционные


class TestAgainstMockSite(unittest.TestCase):
    def setUp(self):
        MockHandler.rest_serves_content = True
        self.site = MockSite().__enter__()
        self.client = Client()
        self.tmp = TemporaryDirectory()
        # Не ждём паузы между пачками в тестах.
        self._pause = client_mod.PAUSE_RANGE
        client_mod.PAUSE_RANGE = (0, 0)

    def tearDown(self):
        client_mod.PAUSE_RANGE = self._pause
        self.client.close()
        self.tmp.cleanup()
        self.site.__exit__()

    def test_find_by_slug(self):
        novel = api.find_novel(self.client, "https://www.mvlempyr.io/novel/insect-tamers-ascension")
        self.assertEqual(novel.code, NOVEL_CODE)
        self.assertEqual(novel.total_chapters, TOTAL)

    def test_find_by_code(self):
        self.assertEqual(api.find_novel(self.client, "6615").code, NOVEL_CODE)

    def test_find_unknown_raises(self):
        with self.assertRaises(LookupError):
            api.find_novel(self.client, "definitely-not-a-real-book-xyz")

    def test_toc_reports_holes(self):
        novel = api.find_novel(self.client, "6615")
        toc = api.fetch_toc(self.client, novel)
        self.assertEqual(toc.missing, sorted(HOLES))
        self.assertEqual(len(toc.chapters), TOTAL - len(HOLES))
        self.assertEqual([c.number for c in toc.chapters], sorted(set(range(1, TOTAL + 1)) - HOLES))

    def test_probe_detects_rest_mode(self):
        novel = api.find_novel(self.client, "6615")
        toc = api.fetch_toc(self.client, novel)
        self.assertEqual(api.probe_content_mode(self.client, toc.chapters[0]), api.MODE_REST)

    def test_probe_detects_html_mode(self):
        MockHandler.rest_serves_content = False
        novel = api.find_novel(self.client, "6615")
        toc = api.fetch_toc(self.client, novel)
        self.assertEqual(api.probe_content_mode(self.client, toc.chapters[0]), api.MODE_HTML)

    def _run(self, **kwargs):
        novel = api.find_novel(self.client, "6615")
        out = prepare_output_dir(self.tmp.name, novel.name)
        downloader = Downloader(client=self.client)
        return novel, out, downloader.run(novel, out, **kwargs)

    def test_full_run_rest_mode(self):
        novel, out, report = self._run()
        self.assertEqual(report.mode, api.MODE_REST)
        self.assertEqual(report.downloaded, TOTAL - len(HOLES) - len(FLAKY))
        self.assertEqual(report.failed_chapters, sorted(FLAKY))
        self.assertEqual(report.missing_in_toc, sorted(HOLES))

        files = sorted(p.name for p in out.glob("*.txt"))
        self.assertEqual(len(files), TOTAL - len(HOLES) - len(FLAKY))
        self.assertTrue(files[0].startswith("0001 - "))
        # Слэш из ch_name не должен превратиться в подпапку.
        self.assertFalse(any(p.is_dir() for p in out.iterdir() if p.name != "__pycache__"))

    def test_full_run_html_mode(self):
        MockHandler.rest_serves_content = False
        novel, out, report = self._run()
        self.assertEqual(report.mode, api.MODE_HTML)
        self.assertEqual(report.downloaded, TOTAL - len(HOLES) - len(FLAKY))
        body = (out / sorted(p.name for p in out.glob("*.txt"))[0]).read_text(encoding="utf-8")
        self.assertIn(NOVEL_NAME, body)
        self.assertNotIn("premium", body)

    def test_saved_file_layout(self):
        novel, out, _ = self._run()
        path = out / "0001 - Chapter 1_ The Title _ Part 2.txt"
        self.assertTrue(path.exists(), sorted(p.name for p in out.glob('*.txt')))
        lines = path.read_text(encoding="utf-8").split("\n")
        self.assertEqual(lines[0], NOVEL_NAME)
        self.assertEqual(lines[1], "Chapter 1: The Title / Part 2")
        self.assertEqual(lines[2], "")

    def test_errors_log_written(self):
        _, out, _ = self._run()
        log_text = (out / "errors.log").read_text(encoding="utf-8")
        for number in FLAKY:
            self.assertIn(f"глава {number}", log_text)
        self.assertIn("нет в оглавлении", log_text)

    def test_resume_skips_finished(self):
        novel, out, first_report = self._run()
        self.assertGreater(first_report.downloaded, 0)

        second = Downloader(client=self.client).run(novel, out)
        self.assertEqual(second.downloaded, 0)
        self.assertEqual(second.skipped, TOTAL - len(HOLES) - len(FLAKY))
        self.assertEqual(second.failed, len(FLAKY))

    def test_resume_redownloads_deleted_file(self):
        novel, out, _ = self._run()
        victim = sorted(out.glob("*.txt"))[0]
        victim.unlink()

        second = Downloader(client=self.client).run(novel, out)
        self.assertEqual(second.downloaded, 1)
        self.assertTrue(victim.exists())

    def test_range_limits_download(self):
        _, out, report = self._run(first=2, last=4)
        self.assertEqual(sorted(int(p.name[:4]) for p in out.glob("*.txt")), [2, 3, 4])
        self.assertEqual(report.downloaded, 3)

    def test_state_file_written(self):
        _, out, _ = self._run()
        state = State(out / "state.json")
        self.assertEqual(state.data["novel"]["code"], NOVEL_CODE)
        self.assertEqual(state.data["mode"], api.MODE_REST)
        self.assertIn("1", state.data["downloaded"])
        self.assertIn(str(sorted(FLAKY)[0]), state.data["failed"])

    def test_corrupt_state_does_not_crash(self):
        _, out, _ = self._run()
        (out / "state.json").write_text("{ broken", encoding="utf-8")
        state = State(out / "state.json")
        self.assertEqual(state.data["downloaded"], {})

    def test_verify_report(self):
        novel, out, _ = self._run()
        report = verify(out)
        self.assertEqual(report["total_chapters"], TOTAL)
        self.assertEqual(report["on_disk"], TOTAL - len(HOLES) - len(FLAKY))
        self.assertEqual(report["missing"], sorted(HOLES | FLAKY))
        self.assertEqual(report["missing_compact"], "7, 9")

    def test_cancel_stops_run(self):
        novel = api.find_novel(self.client, "6615")
        out = prepare_output_dir(self.tmp.name, "cancelme")
        cancel = threading.Event()
        cancel.set()
        downloader = Downloader(client=self.client, cancel_event=cancel)
        from mvl.downloader import Cancelled

        with self.assertRaises(Cancelled):
            downloader.run(novel, out)


class TestWebApp(unittest.TestCase):
    def setUp(self):
        MockHandler.rest_serves_content = True
        self.site = MockSite().__enter__()
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()
        self.tmp = TemporaryDirectory()
        self._pause = client_mod.PAUSE_RANGE
        client_mod.PAUSE_RANGE = (0, 0)

    def tearDown(self):
        client_mod.PAUSE_RANGE = self._pause
        self.tmp.cleanup()
        self.site.__exit__()

    def test_index_served(self):
        self.assertEqual(self.app.get("/").status_code, 200)

    def test_find_endpoint(self):
        res = self.app.post("/api/find", json={"query": "6615"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["novel"]["code"], NOVEL_CODE)

    def test_find_empty_query(self):
        self.assertEqual(self.app.post("/api/find", json={"query": ""}).status_code, 400)

    def test_find_unknown(self):
        res = self.app.post("/api/find", json={"query": "no-such-book-at-all"})
        self.assertEqual(res.status_code, 404)

    def test_browse_lists_dirs(self):
        (Path(self.tmp.name) / "sub").mkdir()
        res = self.app.get("/api/browse", query_string={"path": self.tmp.name})
        data = res.get_json()
        self.assertEqual([d["name"] for d in data["dirs"]], ["sub"])
        self.assertTrue(data["writable"])

    def test_start_requires_folder(self):
        res = self.app.post(
            "/api/start", json={"novel": {"code": NOVEL_CODE}, "base": self.tmp.name, "folder": ""}
        )
        self.assertEqual(res.status_code, 400)

    def test_start_and_finish_job(self):
        novel = self.app.post("/api/find", json={"query": "6615"}).get_json()["novel"]
        res = self.app.post(
            "/api/start",
            json={"novel": novel, "base": self.tmp.name, "folder": "My Book", "first": 1, "last": 5},
        )
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["job"]["id"]

        from webapp.app import JOBS

        JOBS[job_id].thread.join(timeout=30)
        job = self.app.get(f"/api/job/{job_id}").get_json()["job"]

        self.assertIsNone(job["error"])
        self.assertEqual(job["progress"]["stage"], "done")
        out = Path(self.tmp.name) / "My Book"
        self.assertTrue(out.is_dir())
        # Диапазон 1..5 — дыра (7) и сбойная глава (9) в него не попадают.
        self.assertEqual(sorted(int(p.name[:4]) for p in out.glob("*.txt")), [1, 2, 3, 4, 5])

    def test_job_not_found(self):
        self.assertEqual(self.app.get("/api/job/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
