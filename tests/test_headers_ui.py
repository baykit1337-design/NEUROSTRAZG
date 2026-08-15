"""Очистка шапок: по месту и с открытием файла (часть 6 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats, text  # noqa: E402
from core.models import Chapter  # noqa: E402
from ops import headers as headers_op  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"


class TestFindingKnowsItsFiles(unittest.TestCase):
    """6.2: без файла находку нельзя открыть и посмотреть."""

    def samples(self, count=10):
        return [(f"Глава {n}", ["Перевод: канал", f"Текст главы {n}."],
                 f"/книга/Глава {n}.txt") for n in range(1, count + 1)]

    def test_files_are_reported(self):
        found = text.find_headers(self.samples())
        self.assertTrue(found)
        self.assertEqual(len(found[0].files), 10)
        self.assertIn("/книга/Глава 1.txt", found[0].files)

    def test_only_a_few_files_reach_the_screen(self):
        """Пятьсот путей в одной строке никому не нужны."""
        found = text.find_headers(self.samples(200))
        self.assertLessEqual(len(found[0].as_dict()["files"]), 20)
        self.assertEqual(found[0].count, 200)

    def test_pairs_without_a_file_still_work(self):
        """Прежний вызов на двух значениях ломаться не должен."""
        found = text.find_headers(
            [(f"Глава {n}", ["Перевод: канал", "Текст."]) for n in range(10)])
        self.assertTrue(found)
        self.assertEqual(found[0].files, [])

    def test_title_echo_reports_its_files_too(self):
        samples = [(f"Глава {n}", [f"Глава {n}", "Текст."], f"/к/{n}.txt")
                   for n in range(1, 11)]
        found = [f for f in text.find_headers(samples) if f.kind == text.HEAD_TITLE]
        self.assertTrue(found)
        self.assertEqual(len(found[0].files), 10)


class TestScanPassesFiles(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def test_scan_reports_where_the_line_was_found(self):
        book = self.tmp / "книга"
        book.mkdir()
        for n in range(1, 11):
            formats.write(book / f"Глава {n}.txt", [Chapter(
                number=n, title=f"Глава {n}",
                paragraphs=["Перевод: канал НЕЙРОСТРАЖ", f"Текст {n}."])],
                headings=True)

        found = headers_op.scan(str(book))["findings"]
        self.assertTrue(found)
        self.assertTrue(found[0]["files"])
        self.assertTrue(found[0]["files"][0].endswith(".txt"))


class TestHeaderBlockMarkup(unittest.TestCase):
    """6.1: блок показывается только там, где сделан выбор."""

    @classmethod
    def setUpClass(cls):
        cls.js = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_block_moves_into_the_calling_tab(self):
        self.assertIn("function hdPlaceCard(", self.js)
        self.assertIn("section.append(card)", self.js)

    def test_placing_happens_on_every_scan(self):
        block = self.js[self.js.index("async function hdScan("):]
        self.assertIn("hdPlaceCard(source)", block[:400])

    def test_click_opens_the_file(self):
        self.assertIn("call('/api/open', {path: files[0]})", self.js)

    def test_copy_button_has_a_fallback(self):
        """http://127.0.0.1 не считается защищённым, а программа живёт там."""
        self.assertIn("function hdCopy(", self.js)
        self.assertIn("document.execCommand('copy')", self.js)


class TestOpenRoute(unittest.TestCase):
    def setUp(self):
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()

    def test_missing_file_is_404(self):
        res = self.app.post("/api/open", json={"path": "/нет/такого"})
        self.assertEqual(res.status_code, 404)

    def test_nothing_to_open_with_is_not_a_server_fault(self):
        """Файл есть, а открывать его нечем — 500 пугал бы зря."""
        from core import platform

        real = platform.open_file

        def broken(path):
            raise platform.OpenError("В системе нет «xdg-open»")

        platform.open_file = broken
        self.addCleanup(setattr, platform, "open_file", real)

        res = self.app.post("/api/open", json={"path": str(ROOT / "README.md")})
        self.assertEqual(res.status_code, 400)
        self.assertIn("xdg-open", res.get_json()["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
