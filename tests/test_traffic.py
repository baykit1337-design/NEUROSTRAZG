"""Счётчик скачанного.

При платном пакете это первое, что хочется видеть, а узнать было
неоткуда: главы, рейтинги, обложки, перевод и обновления уходили в один
общий поток, о котором никто не отчитывался.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import traffic  # noqa: E402


class TrafficTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.was = traffic.FILE
        self.addCleanup(self.restore)
        traffic.setup(self.tmp / "traffic.json")
        traffic.forget()

    def restore(self):
        traffic.FILE = self.was
        traffic.forget()


class TestCounting(TrafficTestCase):
    def test_it_adds_up(self):
        traffic.note(1000)
        traffic.note(24)
        self.assertEqual(traffic.totals()["session"], 1024)

    def test_nothing_and_nonsense_do_not_count(self):
        traffic.note(0)
        traffic.note(-5)
        traffic.note(None)
        self.assertEqual(traffic.totals()["session"], 0)

    def test_the_month_adds_up_too(self):
        traffic.note(2048)
        self.assertEqual(traffic.totals()["month"], 2048)

    def test_the_month_has_a_readable_name(self):
        self.assertRegex(traffic.totals()["month_name"], r"^[а-я]+ \d{4}$")


class TestItSurvivesTheProgramClosing(TrafficTestCase):
    def test_the_month_is_read_back(self):
        traffic.note(traffic.SAVE_EVERY + 1)
        traffic.setup(self.tmp / "traffic.json")
        self.assertEqual(traffic.totals()["month"], traffic.SAVE_EVERY + 1)

    def test_the_session_starts_from_zero_again(self):
        """За запуск — значит за запуск, а не за всё время."""
        traffic.note(traffic.SAVE_EVERY + 1)
        traffic.setup(self.tmp / "traffic.json")
        self.assertEqual(traffic.totals()["month"], traffic.SAVE_EVERY + 1)
        self.assertLess(traffic.totals()["month"], traffic.totals()["session"]
                        + traffic.SAVE_EVERY + 2)

    def test_small_change_is_not_lost_on_the_way_out(self):
        """Меньше порога на диск не пишется — но при закрытии должно."""
        traffic.note(10)
        traffic.flush()
        self.assertEqual(
            json.loads((self.tmp / "traffic.json").read_text(encoding="utf-8"))
            ["bytes"], 10)

    def test_last_month_total_is_not_ours(self):
        (self.tmp / "traffic.json").write_text(
            json.dumps({"month": "1999-01", "bytes": 999999}), encoding="utf-8")
        traffic.setup(self.tmp / "traffic.json")
        self.assertEqual(traffic.totals()["month"], 0)

    def test_a_broken_file_does_not_break_the_program(self):
        (self.tmp / "traffic.json").write_text("{не json", encoding="utf-8")
        traffic.setup(self.tmp / "traffic.json")
        self.assertEqual(traffic.totals()["month"], 0)

    def test_without_a_file_it_still_counts_in_memory(self):
        traffic.FILE = None
        traffic.note(500)
        self.assertEqual(traffic.totals()["session"], 500)
        self.assertFalse(traffic.totals()["kept"])


class TestItIsCountedWhereTheBytesArrive(TrafficTestCase):
    """Счёт стоит в клиенте — через него идут и главы, и рейтинги, и
    обновление. Тремя счётчиками они бы разошлись."""

    def setUp(self):
        super().setUp()
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading

        self.body = b"x" * 4096

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — имя задано библиотекой
                self.send_response(200)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_a_page_taken_from_a_site_lands_in_the_counter(self):
        from mvl.client import Client

        was = traffic.totals()["session"]
        client = Client()
        try:
            client.get(f"{self.base}/chapter")
        finally:
            client.close()
        self.assertGreaterEqual(traffic.totals()["session"] - was, len(self.body))

    def test_two_pages_count_twice(self):
        from mvl.client import Client

        client = Client()
        try:
            client.get(f"{self.base}/one")
            was = traffic.totals()["session"]
            client.get(f"{self.base}/two")
        finally:
            client.close()
        self.assertGreaterEqual(traffic.totals()["session"] - was, len(self.body))


if __name__ == "__main__":
    unittest.main()
