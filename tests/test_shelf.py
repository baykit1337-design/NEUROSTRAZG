"""Что у книги на самом деле лежит на диске.

Библиотека помнит, сколько глав она скачала. Это память о прогоне, а не
о диске: папку могли переименовать, перенести или вычистить руками — и
«скачано 402» продолжает говорить о книге, которой нет.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import shelf  # noqa: E402


class Base(unittest.TestCase):

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.book = Path(self.dir.name) / "Книга"
        self.book.mkdir()

    def chapter(self, number: int, size: int = 2000, name: str = ""):
        path = self.book / f"{number:04d} - {name or f'Глава {number}'}.txt"
        path.write_text("я" * size, encoding="utf-8")
        return path


class TestLookingAtAFolder(Base):

    def test_the_chapters_are_counted_and_weighed(self):
        for number in (1, 2, 3):
            self.chapter(number)
        said = shelf.look(self.book)

        self.assertTrue(said.exists)
        self.assertEqual(said.files, 3)
        self.assertGreater(said.bytes, 0)

    def test_the_numbers_come_from_the_names(self):
        for number in (1170, 1171, 1172):
            self.chapter(number)
        said = shelf.look(self.book)
        self.assertEqual((said.first, said.last), (1170, 1172))

    def test_a_hole_in_the_numbers_is_found(self):
        for number in (1, 2, 5):
            self.chapter(number)
        said = shelf.look(self.book)

        self.assertEqual(said.gaps_count, 2)
        self.assertEqual(said.gaps, ["3–4"])

    def test_the_start_of_the_book_is_not_a_hole(self):
        """Книга может начинаться с 1168-й главы, и «нет глав с 1 по
        1167» — не находка, а начало книги."""
        for number in (1168, 1169):
            self.chapter(number)
        self.assertEqual(shelf.look(self.book).gaps_count, 0)

    def test_an_empty_chapter_is_found(self):
        """Сайт отдаёт «глава недоступна» в полторы строки: файл есть, а
        главы в нём нет."""
        self.chapter(1)
        self.chapter(2, size=3)
        said = shelf.look(self.book)

        self.assertEqual(said.empty_count, 1)
        self.assertEqual(said.files, 2)

    def test_service_files_are_not_chapters(self):
        self.chapter(1)
        (self.book / "state.json").write_text("{}", encoding="utf-8")
        self.assertEqual(shelf.look(self.book).files, 1)

    def test_the_passport_is_not_a_chapter(self):
        """Паспорт — `.md`, то есть с виду такая же глава, как остальные.

        Имя ему берём у библиотеки, которая его и пишет: своим
        экземпляром имени я уже ошибся, и книга насчитывала на главу
        больше, чем в ней есть.
        """
        from ops import library

        self.chapter(1)
        (self.book / library.PASSPORT).write_text("книга" * 200,
                                                  encoding="utf-8")
        self.assertEqual(shelf.look(self.book).files, 1)

    def test_a_stranger_file_is_not_a_chapter(self):
        self.chapter(1)
        (self.book / "обложка.jpg").write_bytes(b"\xff" * 500)
        self.assertEqual(shelf.look(self.book).files, 1)

    def test_a_copy_inside_is_not_counted_twice(self):
        """Внутри папки книги бывает «копия перед правкой»."""
        self.chapter(1)
        spare = self.book / "копия"
        spare.mkdir()
        (spare / "0001 - Глава 1.txt").write_text("я" * 2000,
                                                  encoding="utf-8")
        self.assertEqual(shelf.look(self.book).files, 1)

    def test_a_folder_named_like_a_chapter_is_still_a_folder(self):
        """Копию папки называют как придётся — бывает, и с точкой в
        имени. Посчитай мы её главой, у книги нашлась бы глава, которой
        нет, а её «размер» был бы размером записи в каталоге."""
        self.chapter(1)
        (self.book / "0002 - копия.txt").mkdir()
        self.assertEqual(shelf.look(self.book).files, 1)

    def test_a_whole_book_says_so(self):
        for number in (1, 2, 3):
            self.chapter(number)
        self.assertTrue(shelf.look(self.book).whole)

    def test_a_book_with_holes_is_not_whole(self):
        self.chapter(1)
        self.chapter(3)
        self.assertFalse(shelf.look(self.book).whole)


class TestWhenThereIsNothingToLookAt(Base):

    def test_a_folder_that_is_gone_is_said_so(self):
        said = shelf.look(Path(self.dir.name) / "нет такой")
        self.assertFalse(said.exists)
        self.assertIn("нет", said.trouble)

    def test_a_folder_that_is_gone_is_not_whole(self):
        self.assertFalse(shelf.look(Path(self.dir.name) / "нет").whole)

    def test_an_empty_folder_is_not_whole(self):
        """Папка есть, книги нет — это то же самое, что книги нет."""
        self.assertFalse(shelf.look(self.book).whole)

    def test_a_book_without_a_folder_written_down(self):
        said = shelf.look("")
        self.assertFalse(said.exists)
        self.assertTrue(said.trouble)

    def test_a_file_instead_of_a_folder_is_not_a_crash(self):
        plain = Path(self.dir.name) / "просто.txt"
        plain.write_text("текст", encoding="utf-8")
        self.assertFalse(shelf.look(plain).exists)


class TestAddingItUp(Base):

    def test_the_sizes_add_up(self):
        self.chapter(1)
        first = shelf.look(self.book)
        said = shelf.weigh([first, first])

        self.assertEqual(said["books"], 2)
        self.assertEqual(said["bytes"], first.bytes * 2)

    def test_the_missing_folders_are_counted(self):
        gone = shelf.look(Path(self.dir.name) / "нет")
        said = shelf.weigh([gone, gone])
        self.assertEqual(said["missing"], 2)

    def test_a_missing_folder_is_not_also_holed(self):
        """Иначе одна беда считалась бы дважды и звучала бы как две."""
        gone = shelf.look(Path(self.dir.name) / "нет")
        self.assertEqual(shelf.weigh([gone])["holed"], 0)

    def test_the_holed_are_counted(self):
        self.chapter(1)
        self.chapter(5)
        said = shelf.weigh([shelf.look(self.book)])
        self.assertEqual(said["holed"], 1)
        self.assertEqual(said["missing"], 0)

    def test_nothing_at_all_is_not_a_crash(self):
        self.assertEqual(shelf.weigh([])["books"], 0)


class TestLookingOverHttp(unittest.TestCase):
    """Осмотр через маршрут: рядом с записанным числом глав."""

    def setUp(self):
        from ops import library
        from webapp import app as web

        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        kept = library.LIBRARY_FILE
        library.LIBRARY_FILE = Path(self.dir.name) / "library.json"
        self.addCleanup(setattr, library, "LIBRARY_FILE", kept)
        self.library = library

        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def book(self, name: str, chapters: int, said: int = 0):
        folder = Path(self.dir.name) / name
        folder.mkdir()
        for number in range(1, chapters + 1):
            (folder / f"{number:04d} - Глава {number}.txt").write_text(
                "я" * 2000, encoding="utf-8")
        return self.library.remember(
            found_site="qidian", found_id=name, name=name,
            folder=str(folder), chapters=chapters,
            last=said or chapters)

    def look(self, **body):
        return self.client.post("/api/library/shelf", json=body).get_json()

    def test_the_disk_is_reported_next_to_what_was_written_down(self):
        book = self.book("Книга", 5)
        said = self.look()["shelves"][book.key]

        self.assertEqual(said["files"], 5)
        self.assertEqual(said["said"], 5)
        self.assertTrue(said["whole"])

    def test_a_book_that_lost_its_files_is_seen(self):
        """Записано 400, на диске две — за этим сюда и приходят."""
        book = self.book("Битая", 2, said=400)
        said = self.look()["shelves"][book.key]

        self.assertEqual(said["files"], 2)
        self.assertEqual(said["said"], 400)

    def test_a_folder_that_is_gone_is_seen(self):
        book = self.library.remember(found_site="qidian", found_id="7",
                                     name="Пропажа",
                                     folder=str(Path(self.dir.name) / "нет"),
                                     chapters=10, last=10)
        said = self.look()["shelves"][book.key]
        self.assertFalse(said["exists"])

    def test_only_the_named_books_are_looked_at(self):
        """Осматривают показанные, а показано может быть три из ста."""
        one = self.book("Одна", 2)
        self.book("Вторая", 2)
        said = self.look(keys=[one.key])

        self.assertEqual(list(said["shelves"]), [one.key])

    def test_the_summary_adds_them_up(self):
        self.book("Одна", 2)
        self.book("Вторая", 3)
        said = self.look()["total"]

        self.assertEqual(said["books"], 2)
        self.assertEqual(said["files"], 5)
        self.assertGreater(said["bytes"], 0)

    def test_an_empty_library_is_not_an_error(self):
        said = self.look()
        self.assertEqual(said["shelves"], {})
        self.assertEqual(said["left"], 0)

    def test_the_rest_are_counted_not_dropped(self):
        """Молчаливый пропуск читался бы как «осмотрели всё»."""
        from webapp import app as web

        was = web.SHELF_AT_ONCE
        web.SHELF_AT_ONCE = 1
        self.addCleanup(setattr, web, "SHELF_AT_ONCE", was)

        self.book("Одна", 1)
        self.book("Вторая", 1)
        said = self.look()

        self.assertEqual(len(said["shelves"]), 1)
        self.assertEqual(said["left"], 1)


if __name__ == "__main__":
    unittest.main()
