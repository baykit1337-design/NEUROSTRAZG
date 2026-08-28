"""Осмотр скачанной папки: всё ли на месте (пункт 5).

Проверяется не «функция вернула словарь», а то, ради чего она написана:
пропущенная глава названа, целая книга не обвиняется зря, а выброс не
превращает список пропусков в шестьсот номеров.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import checkup  # noqa: E402
from ops.base import Cancelled, Progress  # noqa: E402


def body(number: int = 0) -> str:
    """Текст главы. У каждой свой: одинаковые главы — уже находка."""
    return f"Глава {number}. Здесь про своё место, своих людей и свой день. " * 6


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def book(self, numbers=range(1, 21), **odd):
        """Папка с главами. `odd` — имя файла в свой текст."""
        folder = self.tmp / "книга"
        folder.mkdir(parents=True, exist_ok=True)
        for number in numbers:
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n{body(number)}", encoding="utf-8")
        for name, text in odd.items():
            (folder / f"{name}.txt").write_text(text, encoding="utf-8")
        return folder

    def kinds(self, look):
        return {trouble.kind: trouble for trouble in look.troubles}


class TestWholeBook(Base):
    def test_a_book_with_nothing_wrong_says_so(self):
        """Проверка, которая ругается всегда, не проверка."""
        look = checkup.look(self.book())
        self.assertTrue(look.clean, look.summary())
        self.assertEqual(look.chapters, 20)
        self.assertEqual((look.first, look.last), (1, 20))
        self.assertIn("всё на месте", look.summary())

    def test_the_summary_counts_chapters(self):
        look = checkup.look(self.book())
        self.assertIn("Глав: 20", look.summary())
        self.assertIn("1–20", look.summary())


class TestNumbering(Base):
    def test_a_missing_chapter_is_named(self):
        folder = self.book()
        (folder / "Глава 7.txt").unlink()
        look = checkup.look(folder)

        trouble = self.kinds(look)["missing"]
        self.assertEqual(trouble.size, 1)
        self.assertIn("7", trouble.where)
        self.assertTrue(trouble.hole)

    def test_a_run_of_missing_chapters_is_one_line(self):
        """«205, 206, 207, 208» глазами не читается, «205–208» читается."""
        folder = self.book()
        for number in (5, 6, 7, 8):
            (folder / f"Глава {number}.txt").unlink()
        trouble = self.kinds(checkup.look(folder))["missing"]

        self.assertEqual(trouble.where, ["5–8"])
        # Свёрнутая строка одна, а глав потеряно четыре — и счётчик
        # должен говорить про главы, а не про строки.
        self.assertEqual(trouble.size, 4)

    def test_a_stray_number_does_not_invent_hundreds_of_gaps(self):
        """Одна глава 9001 среди двадцати — это выброс, а не дыра в
        восемь тысяч девятьсот глав."""
        folder = self.book()
        (folder / "Глава 9001.txt").write_text(
            f"Глава 9001\n\n{body(9001)}", encoding="utf-8")
        look = checkup.look(folder)

        self.assertNotIn("missing", self.kinds(look))
        self.assertEqual(self.kinds(look)["stray"].where, ["9001"])
        self.assertEqual((look.first, look.last), (1, 20))

    def test_two_files_with_one_number_name_both(self):
        folder = self.book()
        (folder / "Глава 12 копия.txt").write_text(
            f"Глава 12\n\n{body(120)}", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["doubles"]

        self.assertEqual(trouble.size, 1)
        self.assertIn("Глава 12 копия.txt", trouble.where[0])
        self.assertIn("Глава 12.txt", trouble.where[0])

    def test_a_hole_in_the_parts_is_found(self):
        folder = self.book()
        for part in (1, 3):
            (folder / f"Глава 21.{part}.txt").write_text(
                f"Глава 21.{part}\n\n{body(210 + part)}", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["parts"]

        self.assertEqual(trouble.where, ["21.2"])

    def test_a_chapter_without_a_number_is_only_worth_a_look(self):
        """Послесловие — не дыра в книге, и красным его звать нечего."""
        folder = self.book(послесловие=f"Послесловие\n\n{body(99)}")
        trouble = self.kinds(checkup.look(folder))["nameless"]

        self.assertFalse(trouble.hole)
        self.assertEqual(trouble.where, ["послесловие.txt"])


class TestBodies(Base):
    def test_an_empty_chapter_is_a_hole(self):
        folder = self.book()
        (folder / "Глава 9.txt").write_text("Глава 9\n\n", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["empty"]

        self.assertTrue(trouble.hole)
        self.assertEqual(trouble.where, ["Глава 9.txt"])

    def test_a_chapter_cut_mid_word_is_found(self):
        folder = self.book()
        (folder / "Глава 9.txt").write_text(
            "Глава 9\n\nОн шагнул вперёд и увидел, что дверь откр",
            encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["cut"]

        self.assertEqual(trouble.where, ["Глава 9.txt"])

    def test_a_finished_chapter_is_not_called_cut(self):
        """Точка, многоточие, закрытая кавычка — глава дописана."""
        folder = self.book(numbers=range(1, 6))
        for number, tail in ((1, "."), (2, "…"), (3, "»"), (4, "!"), (5, "?")):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n{body(number).strip()[:-1]}{tail}", encoding="utf-8")
        self.assertNotIn("cut", self.kinds(checkup.look(folder)))

    def test_a_chapter_far_shorter_than_the_rest_is_suspicious(self):
        folder = self.book()
        (folder / "Глава 9.txt").write_text(
            "Глава 9\n\nОн ушёл.", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["short"]

        self.assertIn("Глава 9.txt", trouble.where[0])
        # Подписи мало: «короткая» без «короткая по сравнению с чем»
        # ничего не говорит.
        self.assertIn("знаков", trouble.detail)

    def test_a_short_book_is_not_measured_against_its_own_median(self):
        """В книге из трёх глав любая может быть вчетверо короче другой
        просто так, и обвинять её не в чем."""
        folder = self.book(numbers=range(1, 4))
        (folder / "Глава 2.txt").write_text(
            "Глава 2\n\nОн ушёл.", encoding="utf-8")
        self.assertNotIn("short", self.kinds(checkup.look(folder)))


class TestRepeats(Base):
    def test_the_same_text_under_two_numbers_is_found(self):
        """Качалка кладёт одну и ту же страницу под двумя номерами, когда
        сайт отдаёт заглушку вместо главы. По номерам это незаметно."""
        folder = self.book()
        same = "Совершенно одинаковый текст двух разных глав. " * 8
        for number in (4, 15):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n{same}", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["same"]

        # Считаются главы, а не пары: сотня одинаковых заглушек даёт пять
        # тысяч пар, и такое число только пугает.
        self.assertEqual(trouble.size, 2)
        self.assertIn("4", trouble.where[0])
        self.assertIn("15", trouble.where[0])

    def test_repeats_are_counted_in_chapters_not_in_pairs(self):
        """Сайт отдал одну заглушку вместо пяти глав — это пять глав, а
        не десять пар."""
        folder = self.book()
        stub = "Страница временно недоступна, попробуйте позже. " * 8
        for number in (3, 6, 9, 12, 18):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n{stub}", encoding="utf-8")
        self.assertEqual(self.kinds(checkup.look(folder))["same"].size, 5)

    def test_different_chapters_are_not_called_repeats(self):
        folder = self.tmp / "разные"
        folder.mkdir()
        for number in range(1, 11):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n" + f"Совсем разный текст главы {number}. "
                + "Здесь про другое место, других людей и другой день. " * 4,
                encoding="utf-8")
        self.assertNotIn("same", self.kinds(checkup.look(folder)))


class TestOrderAndLimits(Base):
    def test_holes_come_before_things_to_look_at(self):
        """С дыр начинают. Если они внизу списка, их не увидят."""
        folder = self.book(послесловие=f"Послесловие\n\n{body(99)}")
        (folder / "Глава 7.txt").unlink()
        look = checkup.look(folder)

        holes = [t.hole for t in look.troubles]
        self.assertEqual(holes, sorted(holes, reverse=True))
        self.assertGreaterEqual(look.holes, 1)

    def test_the_summary_names_holes_and_counts_the_rest(self):
        folder = self.book(послесловие=f"Послесловие\n\n{body(99)}")
        (folder / "Глава 7.txt").unlink()
        summary = checkup.look(folder).summary()

        self.assertIn("пропущенные главы: 1", summary.lower())
        self.assertIn("присмотреться", summary)

    def test_a_long_list_is_cut_but_the_count_is_not(self):
        """Полторы тысячи имён в отчёте — это отчёт, который не читают."""
        folder = self.book(numbers=range(1, 200))
        for number in range(1, 200, 2):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["empty"]

        self.assertEqual(len(trouble.as_dict()["where"]), checkup.SHOW)
        self.assertEqual(trouble.as_dict()["count"], 100)
        self.assertEqual(trouble.as_dict()["more"], 100 - checkup.SHOW)

    def test_every_kind_has_a_name_for_the_page(self):
        """Страница берёт подписи отсюда: род без имени показать нечем."""
        folder = self.book(послесловие=f"Послесловие\n\n{body(99)}")
        (folder / "Глава 7.txt").unlink()
        (folder / "Глава 9.txt").write_text("Глава 9\n\n", encoding="utf-8")

        for trouble in checkup.look(folder).troubles:
            with self.subTest(trouble.kind):
                self.assertIn(trouble.kind, checkup.KINDS)
                self.assertTrue(trouble.as_dict()["kind_name"])


class TestStopping(Base):
    def test_stopping_the_look_stops_it(self):
        """Осмотр читает всю книгу. Не прерывался бы — кнопка «Остановить»
        врала бы."""
        progress = Progress()
        progress.cancel.set()
        with self.assertRaises(Cancelled):
            checkup.look(self.book(), progress)


if __name__ == "__main__":
    unittest.main()
