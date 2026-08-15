"""Один список форматов на все вкладки (часть 4 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core.models import Chapter  # noqa: E402
from mvl import nativedialog, rename  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"

#: То, что названо в ТЗ.
READ = ("txt", "md", "docx", "epub", "fb2", "rtf", "odt", "html")
WRITE = ("txt", "md", "docx", "epub", "fb2", "rtf", "odt")


class TestCoreList(unittest.TestCase):
    """4.1: перечень живёт в одном месте — `core/formats.py`."""

    def test_everything_from_the_spec_is_readable(self):
        for suffix in READ:
            self.assertIn(f".{suffix}", formats.READABLE, suffix)

    def test_everything_from_the_spec_is_writable(self):
        for suffix in WRITE:
            self.assertIn(f".{suffix}", formats.WRITABLE, suffix)

    def test_fb2_is_on_both_sides(self):
        """4.2: местами его не хватало."""
        self.assertIn(".fb2", formats.READABLE)
        self.assertIn(".fb2", formats.WRITABLE)


class TestFileDialog(unittest.TestCase):
    """Фильтр выбора файлов строится по тому же списку."""

    def test_patterns_come_from_the_core(self):
        patterns = nativedialog._patterns()
        for suffix in formats.READABLE:
            self.assertIn(f"*{suffix}", patterns, suffix)

    def test_fb2_is_offered(self):
        self.assertIn("*.fb2", nativedialog._patterns())


class TestTabsUseTheSameList(unittest.TestCase):
    """Ни одна вкладка не перечисляет форматы у себя."""

    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_no_hardcoded_buttons_left(self):
        """Раньше «Переименовать» знала только .txt и .docx."""
        self.assertNotIn('data-fmt="txt"', self.html)
        self.assertNotIn('data-fmt="docx"', self.html)

    def test_every_tab_builds_its_row_from_the_server(self):
        for row in ("spFormats", "mgFormats", "rnFormats"):
            self.assertIn(f'id="{row}"', self.html, row)
            self.assertIn(f"buildFormats('{row}'", self.js, row)

    def test_list_is_fetched_not_written_out(self):
        self.assertIn("call('/api/formats')", self.js)


class TestRenameWritesEveryFormat(unittest.TestCase):
    """Вкладка писала файлы сама и умела два формата из семи."""

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def row(self, name="Глава 1"):
        return rename.PlanRow(
            source="", old_name="x.txt", new_name=name, number=1, part=None,
            title=name, size=10, paragraphs=["Первый абзац.", "Второй абзац."])

    def test_all_writable_formats_work(self):
        for suffix in formats.WRITABLE:
            out = self.tmp / suffix.lstrip(".")
            report = rename.apply_plan([self.row()], out, fmt=suffix.lstrip("."))
            self.assertEqual(report.written, 1, f"{suffix}: {report.failed_files}")
            self.assertTrue(list(out.glob(f"*{suffix}")), suffix)

    def test_fb2_round_trip(self):
        out = self.tmp / "fb2"
        rename.apply_plan([self.row("Глава 7")], out, fmt="fb2")
        chapters = formats.read(next(out.glob("*.fb2")))
        self.assertIn("Первый абзац.", chapters[0].text)

    def test_unknown_format_falls_back_to_txt(self):
        out = self.tmp / "странный"
        rename.apply_plan([self.row()], out, fmt="pdf")
        self.assertTrue(list(out.glob("*.txt")))

    def test_writer_is_the_common_one(self):
        """Свой писатель на вкладке — это и был источник трёх списков."""
        source = (ROOT / "mvl" / "rename.py").read_text(encoding="utf-8")
        self.assertIn("formats.write(", source)
        self.assertNotIn("document.save(str(target))", source)


class TestRenameRouteAcceptsEveryFormat(unittest.TestCase):
    def setUp(self):
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        book = self.tmp / "книга"
        book.mkdir()
        formats.write(book / "Глава 1.txt",
                      [Chapter(number=1, title="Глава 1", paragraphs=["Текст."])],
                      headings=True)
        self.book = str(book)

    def test_every_format_is_accepted(self):
        for suffix in formats.WRITABLE:
            res = self.app.post("/api/rename/apply", json={
                "folder_in": self.book, "base": str(self.tmp),
                "folder_out": "готово-" + suffix.lstrip("."),
                "out_format": suffix.lstrip("."),
            })
            self.assertEqual(res.status_code, 200, f"{suffix}: {res.get_json()}")

    def test_unknown_format_is_refused(self):
        res = self.app.post("/api/rename/apply", json={
            "folder_in": self.book, "base": str(self.tmp),
            "folder_out": "готово", "out_format": "pdf",
        })
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
