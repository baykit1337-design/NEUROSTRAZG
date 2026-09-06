"""Починка находок осмотра.

Осмотр говорил, что не так, и на этом обрывался: дальше человек оставался
с папкой в несколько сотен файлов и списком имён. Здесь то, что можно
починить, не уходя с той же карточки: снять шапку и перекачать главу.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import history as history_op  # noqa: E402
from ops import library  # noqa: E402
from ops import repair  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        # Текущий каталог возвращаем на место: одна из проверок в него
        # переходит, а остальному набору важно, где он стоит.
        self.addCleanup(os.chdir, os.getcwd())
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = Path(self.dir.name) / "книга"
        self.folder.mkdir()

        # Корзина и журнал — в свою временную папку: настоящие трогать
        # нельзя, а копию починка делает всегда.
        self.addCleanup(setattr, history_op, "BACKUP_DIR",
                        history_op.BACKUP_DIR)
        self.addCleanup(setattr, history_op, "HISTORY_FILE",
                        history_op.HISTORY_FILE)
        history_op.BACKUP_DIR = Path(self.dir.name) / "корзина"
        history_op.HISTORY_FILE = Path(self.dir.name) / "history.json"

    def chapter(self, number, title="Название", text="Текст главы.",
                book="Название книги"):
        """Файл главы ровно такой, какой пишет качалка."""
        path = self.folder / f"{number:04d} - {title}.txt"
        path.write_text(f"{book}\n{title}\n\n{text}\n", encoding="utf-8")
        return path


class TestTheHeadIsTakenOff(Base):
    """«Убрать шапку»: название книги и заголовок — первые две строки."""

    def test_the_two_lines_are_gone(self):
        path = self.chapter(1)
        repair.cut_head(self.folder, [path.name])
        self.assertEqual(path.read_text(encoding="utf-8"), "Текст главы.\n")

    def test_the_text_itself_is_untouched(self):
        path = self.chapter(1, text="Первый абзац.\n\nВторой абзац.")
        repair.cut_head(self.folder, [path.name])
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "Первый абзац.\n\nВторой абзац.\n")

    def test_only_the_named_files_are_touched(self):
        """Папку выбирает человек, и выбрать он может рабочий стол."""
        mine = self.chapter(1)
        other = self.chapter(2)
        was = other.read_text(encoding="utf-8")
        repair.cut_head(self.folder, [mine.name])
        self.assertEqual(other.read_text(encoding="utf-8"), was)

    def test_a_copy_is_kept(self):
        """Первое, чего хочется после неудачной автоправки, — вернуть."""
        path = self.chapter(1)
        done = repair.cut_head(self.folder, [path.name])
        self.assertTrue(done.backup)
        kept = Path(done.backup) / path.name
        self.assertIn("Название книги", kept.read_text(encoding="utf-8"))

    def test_a_chapter_that_is_only_a_head_is_left_alone(self):
        """Иначе беду, которую видно, меняем на беду, которой не видно."""
        path = self.folder / "0001 - Пусто.txt"
        path.write_text("Название книги\nГлава 1\n", encoding="utf-8")
        done = repair.cut_head(self.folder, [path.name])
        self.assertEqual(done.changed, 0)
        self.assertTrue(done.skipped)
        self.assertIn("Название книги", path.read_text(encoding="utf-8"))

    def test_a_size_tail_in_the_report_is_not_part_of_the_name(self):
        """Осмотр пишет «глава.txt — 812 знаков»: это подпись, не имя."""
        path = self.chapter(1)
        done = repair.cut_head(self.folder, [f"{path.name} — 812 знаков"])
        self.assertEqual(done.changed, 1)

    def test_a_file_that_is_not_there_is_named(self):
        done = repair.cut_head(self.folder, ["нет такого.txt"])
        self.assertEqual(done.changed, 0)
        self.assertTrue(any("нет такого" in one for one in done.skipped))

    def test_a_docx_is_not_edited_line_by_line(self):
        """Убрать две строки из .docx значило бы переписать его целиком.

        Содержимое здесь нарочно такое, что построчная правка над ним
        прошла бы: в нём есть и три строки, и шапка. Останови её только
        нечитаемость байтов — проверка бы ничего не проверяла.
        """
        path = self.folder / "0001 - Глава.docx"
        was = "Название книги\nГлава 1\n\nТекст главы.\n"
        path.write_text(was, encoding="utf-8")
        done = repair.cut_head(self.folder, [path.name])
        self.assertEqual(done.changed, 0)
        self.assertTrue(done.skipped)
        self.assertEqual(path.read_text(encoding="utf-8"), was)

    def test_the_blank_line_after_the_head_goes_too(self):
        """Иначе файл начинается с пустой строки, и читалка примет её за
        название главы."""
        path = self.chapter(1)
        repair.cut_head(self.folder, [path.name])
        self.assertFalse(path.read_text(encoding="utf-8").startswith("\n"))


class TestWhichLinesCount(Base):
    """Считаем непустые: между шапкой и текстом стоит пустая строка."""

    def test_the_blank_line_is_not_one_of_the_two(self):
        path = self.folder / "0001 - Глава.txt"
        path.write_text("Книга\n\nГлава 1\n\nТекст.\n", encoding="utf-8")
        repair.cut_head(self.folder, [path.name])
        self.assertEqual(path.read_text(encoding="utf-8"), "Текст.\n")

    def test_how_many_lines_can_be_asked(self):
        path = self.chapter(1, text="Лишняя строка\nТекст главы.")
        repair.cut_head(self.folder, [path.name], lines=3)
        self.assertEqual(path.read_text(encoding="utf-8"), "Текст главы.\n")


class TestReadingTheReportRows(unittest.TestCase):
    """Осмотр называет главы тремя способами — понимать надо все три."""

    def test_a_file_name_gives_its_number(self):
        self.assertEqual(repair.numbers_of(["0042 - Имя.txt"]), [42])

    def test_a_range_unfolds(self):
        self.assertEqual(repair.numbers_of(["7–9"]), [7, 8, 9])

    def test_several_rows_come_together(self):
        self.assertEqual(repair.numbers_of(["3", "5–6"]), [3, 5, 6])

    def test_a_number_inside_the_name_is_not_a_chapter(self):
        """«0042 - Том 3.txt» — это глава 42, а не 42 и 3."""
        self.assertEqual(repair.numbers_of(["0042 - Том 3.txt"]), [42])

    def test_the_size_tail_is_not_a_number(self):
        self.assertEqual(repair.numbers_of(["0042 - Имя.txt — 812 знаков"]),
                         [42])


class TestClearingTheWayForARedownload(Base):
    """Испорченную главу мало перекачать поверх: качалка пройдёт мимо."""

    def state(self, done):
        (self.folder / repair.STATE_FILE).write_text(json.dumps({
            "version": 1,
            "downloaded": {str(n): f"{n:04d} - Название.txt" for n in done},
            "failed": {},
        }), encoding="utf-8")

    def test_the_file_is_gone(self):
        path = self.chapter(3)
        self.state([1, 2, 3])
        repair.drop(self.folder, [path.name])
        self.assertFalse(path.exists())

    def test_the_number_is_forgotten(self):
        """Иначе в state.json висит имя файла, которого нет."""
        path = self.chapter(3)
        self.state([1, 2, 3])
        done = repair.drop(self.folder, [path.name])
        kept = json.loads((self.folder / repair.STATE_FILE)
                          .read_text(encoding="utf-8"))
        self.assertNotIn("3", kept["downloaded"])
        self.assertEqual(done.forgotten, [3])

    def test_the_other_chapters_stay(self):
        self.chapter(1)
        path = self.chapter(3)
        self.state([1, 3])
        repair.drop(self.folder, [path.name])
        kept = json.loads((self.folder / repair.STATE_FILE)
                          .read_text(encoding="utf-8"))
        self.assertIn("1", kept["downloaded"])
        self.assertTrue((self.folder / "0001 - Название.txt").exists())

    def test_a_copy_is_kept(self):
        """Обрывок главы — всё-таки половина главы. Не выйдет перекачать —
        остаться совсем без неё хуже."""
        path = self.chapter(3)
        self.state([3])
        done = repair.drop(self.folder, [path.name])
        self.assertTrue(done.backup)
        self.assertTrue((Path(done.backup) / path.name).is_file())

    def test_a_missing_chapter_has_no_file_to_remove(self):
        """Дыра в нумерации: файла нет вовсе, забыть надо только номер."""
        self.state([1, 2])
        done = repair.drop(self.folder, ["7–9"])
        self.assertEqual(done.removed, [])
        self.assertEqual(done.forgotten, [])

    def test_a_folder_without_a_state_file_is_not_a_trouble(self):
        path = self.chapter(3)
        done = repair.drop(self.folder, [path.name])
        self.assertEqual(done.removed, [path.name])
        self.assertEqual(done.forgotten, [])


class TestFindingTheBookByItsFolder(Base):
    """Чем качать эту папку, знает библиотека, и только она."""

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, library, "LIBRARY_FILE", library.LIBRARY_FILE)
        library.LIBRARY_FILE = Path(self.dir.name) / "library.json"

    def test_the_book_is_found(self):
        library.remember("mvl:1", name="Книга", folder=str(self.folder),
                         source="novelcms", address="https://x/y")
        found = library.by_folder(self.folder)
        self.assertIsNotNone(found)
        self.assertEqual(found.source, "novelcms")

    def test_a_trailing_slash_is_the_same_folder(self):
        """«C:/Книги/Х» и «C:/Книги/Х/» — одна папка, и разойдись они
        написанием, книга бы «не нашлась» при живой записи о ней."""
        library.remember("mvl:1", name="Книга", folder=str(self.folder) + "/",
                         source="novelcms", address="https://x/y")
        self.assertIsNotNone(library.by_folder(self.folder))

    def test_a_stranger_folder_gives_nothing(self):
        library.remember("mvl:1", name="Книга", folder=str(self.folder),
                         source="novelcms", address="https://x/y")
        self.assertIsNone(library.by_folder(Path(self.dir.name) / "чужая"))

    def test_an_empty_folder_name_is_not_a_match(self):
        """Пустая строка — это «папку не назвали», а не «текущая папка».

        `Path("").resolve()` молча превращается в текущий каталог, и книга,
        которая в нём лежит, нашлась бы по запросу ни о чём. Починка после
        этого взялась бы чинить не то, что просили.
        """
        here = Path(self.dir.name) / "тут"
        here.mkdir()
        os.chdir(here)
        library.remember("mvl:1", name="Книга", folder=str(here),
                         source="novelcms", address="https://x/y")

        self.assertIsNone(library.by_folder(""))
        # А по настоящему имени та же книга находится: проверка про
        # пустую строку, а не про сломанный поиск.
        self.assertIsNotNone(library.by_folder(here))


class TestOverHttp(Base):
    """Маршруты: то же самое, но так, как это видит страница."""

    def setUp(self):
        super().setUp()
        from webapp import app as web

        self.addCleanup(setattr, library, "LIBRARY_FILE", library.LIBRARY_FILE)
        library.LIBRARY_FILE = Path(self.dir.name) / "library.json"
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def post(self, where, payload):
        return self.client.post(where, json=payload)

    def test_the_head_comes_off_over_http(self):
        path = self.chapter(1)
        got = self.post("/api/checkup/cuthead",
                        {"targets": [str(self.folder)], "where": [path.name]})
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["changed"], 1)

    def test_an_empty_finding_is_refused(self):
        got = self.post("/api/checkup/cuthead",
                        {"targets": [str(self.folder)], "where": []})
        self.assertEqual(got.status_code, 400)

    def test_a_folder_outside_the_library_is_told_so(self):
        """И сказано должно быть, что делать: гадать по имени папки, чем
        её качали, хуже отказа."""
        path = self.chapter(1)
        got = self.post("/api/checkup/redownload",
                        {"targets": [str(self.folder)], "where": [path.name]})
        self.assertEqual(got.status_code, 400)
        self.assertIn("библиотеке", got.get_json()["error"])

    def test_a_book_without_a_source_is_told_so(self):
        path = self.chapter(1)
        library.remember("mvl:1", name="Книга", folder=str(self.folder))
        got = self.post("/api/checkup/redownload",
                        {"targets": [str(self.folder)], "where": [path.name]})
        self.assertEqual(got.status_code, 400)
        self.assertIn("качали", got.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
