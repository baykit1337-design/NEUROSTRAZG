"""Смешанные форматы и подписи о них (часть 4 ТЗ NEUROSTRAZH).

В одной папке форматы лежат вперемешку — так получается само, когда
главы качались в разное время. Читатель приводит любой формат к общему
представлению, но по дороге терялись и файлы, и подписи о них.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core import text as coretext  # noqa: E402
from core.models import Chapter  # noqa: E402
from ops import base as ops_base, merge as merge_op  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"

#: Что кладём в папку: номер главы и в каком формате она сохранена.
MIXED = [(1, ".docx"), (2, ".txt"), (3, ".fb2"), (4, ".epub"), (5, ".md"),
         (6, ".txt"), (7, ".docx"), (8, ".odt"), (9, ".rtf"), (10, ".epub")]


class MixedBase(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.folder = self.root / "главы"
        self.folder.mkdir()
        for number, suffix in MIXED:
            formats.write(
                self.folder / f"{number:03d} - Глава {number}{suffix}",
                [Chapter(number=number, title=f"Глава {number}",
                         paragraphs=[f"Текст главы {number}."])],
                title=f"Глава {number}")


class TestShortChaptersSurvive(unittest.TestCase):
    """Короткая глава — не обложка.

    Epub разбирался по одной длине страницы: всё короче двухсот знаков
    считалось обложкой или оглавлением. Настоящая глава на пару абзацев
    так пропадала молча.
    """

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

    def epub(self, chapters) -> Path:
        path = self.root / "книга.epub"
        formats.write(path, chapters, title="Книга")
        return path

    def test_a_two_line_chapter_is_not_lost(self):
        path = self.epub([Chapter(number=1, title="Глава 1",
                                  paragraphs=["Коротко."])])
        self.assertEqual(len(formats.read(path)), 1)

    def test_long_and_short_chapters_together(self):
        made = [Chapter(number=n, title=f"Глава {n}",
                        paragraphs=["Длинный текст. " * 40 if n % 2
                                    else "Коротко."])
                for n in range(1, 7)]
        back = formats.read(self.epub(made))
        self.assertEqual([c.title for c in back],
                         [f"Глава {n}" for n in range(1, 7)])

    def test_the_table_of_contents_is_still_skipped(self):
        """Оглавление помечено в манифесте — гадать по объёму не нужно."""
        back = formats.read(self.epub(
            [Chapter(number=1, title="Глава 1", paragraphs=["Текст."])]))
        self.assertEqual([c.title for c in back], ["Глава 1"])


class TestTitleIsNotDoubled(unittest.TestCase):
    """Заголовок «Глава 217» без имени оставался продублированным.

    Название сверялось после снятия приставки «Глава N», а у главы без
    имени приставка — это всё название: сверять становилось нечего, и
    проверка молча пропускалась.
    """

    def test_a_bare_number_is_stripped(self):
        self.assertEqual(
            coretext.strip_leading_title(["Глава 1", "Текст."], "Глава 1"),
            ["Текст."])

    def test_the_same_heading_written_differently(self):
        self.assertEqual(
            coretext.strip_leading_title(["Глава 5: Паучьи будни", "Текст."],
                                         "Глава 5. Паучьи будни"),
            ["Текст."])

    def test_a_named_chapter_still_works(self):
        self.assertEqual(
            coretext.strip_leading_title(["Паучьи будни", "Текст."],
                                         "Глава 5. Паучьи будни"),
            ["Текст."])

    def test_the_text_itself_is_never_touched(self):
        self.assertEqual(
            coretext.strip_leading_title(["Текст.", "Ещё текст."], "Глава 1"),
            ["Текст.", "Ещё текст."])


class TestMixedMerge(MixedBase):
    """4.2: смешанную папку принимаем целиком и по порядку глав."""

    def test_every_file_is_taken(self):
        found = merge_op.scan([str(self.folder)])
        self.assertEqual(found["file_count"], len(MIXED))
        self.assertEqual(found["total"], len(MIXED))

    def test_the_order_is_by_chapter_number_not_by_format(self):
        out = self.root / "книга.txt"
        merge_op.run([str(self.folder)], out)
        body = out.read_text(encoding="utf-8")
        places = [body.index(f"Глава {n}") for n, _ in MIXED]
        self.assertEqual(places, sorted(places))

    def test_nothing_is_dropped_on_the_way(self):
        out = self.root / "книга.txt"
        report = merge_op.run([str(self.folder)], out)
        self.assertEqual(report.written, len(MIXED))
        self.assertEqual(report.failures, [])

    def test_the_result_can_be_any_format(self):
        out = self.root / "книга.epub"
        merge_op.run([str(self.folder)], out)
        self.assertEqual(len(formats.read(out)), len(MIXED))


class TestSkippedIsReported(MixedBase):
    """4.2: молча отсеивать часть файлов нельзя."""

    def setUp(self):
        super().setUp()
        (self.folder / "обложка.pdf").write_bytes(b"%PDF-1.4")
        (self.folder / "заметки.xlsx").write_bytes(b"PK")

    def test_what_did_not_fit_is_named(self):
        found = merge_op.scan([str(self.folder)])
        self.assertEqual(sorted(found["skipped"]),
                         ["заметки.xlsx", "обложка.pdf"])

    def test_the_readable_files_are_still_all_taken(self):
        found = merge_op.scan([str(self.folder)])
        self.assertEqual(found["file_count"], len(MIXED))

    def test_service_files_are_not_reported_as_losses(self):
        (self.folder / "spelling.txt").write_text("", encoding="utf-8")
        found = merge_op.scan([str(self.folder)])
        self.assertNotIn("spelling.txt", found["skipped"])

    def test_a_file_chosen_by_hand_is_not_counted_as_skipped(self):
        """Пропускаем по формату только внутри папки: на файл человек
        указал сам, и молчать про него — другое дело."""
        chosen = str(self.folder / "001 - Глава 1.docx")
        self.assertEqual(ops_base.skipped_files([chosen]), [])


class TestFormatCaptions(unittest.TestCase):
    """4.1: перечень расширений собирается из общего списка."""

    @classmethod
    def setUpClass(cls):
        cls.page = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_no_tab_lists_the_extensions_by_hand(self):
        self.assertNotIn(".epub, .docx, .txt или .md", self.page)

    def test_the_places_for_the_list_are_marked(self):
        self.assertGreaterEqual(self.page.count('data-formats="readable"'), 4)

    def test_the_list_comes_from_the_server_answer(self):
        self.assertIn("FORMATS[node.dataset.formats]", self.tabs)

    def test_it_is_filled_together_with_the_format_buttons(self):
        self.assertIn("writeFormatCaptions()", self.tabs)

    def test_the_server_gives_out_the_whole_list(self):
        from webapp.app import app

        app.config["TESTING"] = True
        body = app.test_client().get("/api/formats").get_json()
        self.assertEqual(body["readable"], list(formats.READABLE))
        self.assertEqual(body["writable"], list(formats.WRITABLE))

    def test_there_are_more_than_four_readable_formats(self):
        """Подпись обещала четыре — ради этого всё и затевалось."""
        self.assertGreater(len(formats.READABLE), 4)


class TestBreakdownCaption(unittest.TestCase):
    """4.2: «выбрано 312 файлов: .docx — 200, .txt — 100, .fb2 — 12»."""

    @classmethod
    def setUpClass(cls):
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_the_breakdown_is_built(self):
        self.assertIn("function formatBreakdown(files)", self.tabs)

    def test_it_is_sorted_by_count(self):
        body = self.tabs.split("function formatBreakdown(files)", 1)[1]
        self.assertIn("b[1] - a[1]", body)

    def test_it_shows_counts_not_just_names(self):
        self.assertIn("`${suffix} — ${count}`", self.tabs)

    def test_the_merge_tab_uses_it(self):
        self.assertIn("formatBreakdown(data.files)", self.tabs)

    def test_the_skipped_files_reach_the_screen(self):
        self.assertIn("Пропущено по формату", self.tabs)
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="mgSkipped"', page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
