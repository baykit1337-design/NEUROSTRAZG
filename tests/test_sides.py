"""Два слива одной книги: где они расходятся (пункт 16).

Проверяется то, ради чего сравнение и затевается: какую из двух папок
брать. Сторон здесь две равные, поэтому важно и то, что находка не
приписывается не той стороне.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import sides  # noqa: E402


FULL = "Полная глава, в которой текст на месте и ничего не потеряно. " * 12


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.left = self.book("сайт1")
        self.right = self.book("сайт2")

    def book(self, name, numbers=range(1, 21)):
        folder = self.tmp / name
        folder.mkdir(parents=True, exist_ok=True)
        for number in numbers:
            self.write(folder, number, f"{FULL} Глава {number} у «{name}».")
        return folder

    def write(self, folder, number, text):
        (folder / f"Глава {number}.txt").write_text(
            f"Глава {number}\n\n{text}", encoding="utf-8")

    def kinds(self, verdict):
        found = {}
        for finding in verdict.findings:
            found.setdefault(finding.kind, []).append(finding)
        return found


class TestSame(Base):
    def test_two_equal_downloads_are_called_equal(self):
        """Сравнение, которое всегда что-то находит, ничего не говорит."""
        verdict = sides.compare(self.left, self.right)

        self.assertEqual(verdict.findings, [])
        self.assertEqual(verdict.matched, 20)
        self.assertEqual(verdict.fuller, "")
        self.assertIn("брать можно любую", verdict.advice())

    def test_the_sides_are_named_by_their_folders(self):
        """«Слева» и «справа» без имён папок через минуту уже не помнят."""
        verdict = sides.compare(self.left, self.right)
        self.assertEqual(verdict.left_name, "сайт1")
        self.assertEqual(verdict.right_name, "сайт2")


class TestMissing(Base):
    def test_a_chapter_missing_on_one_side_is_found(self):
        (self.right / "Глава 7.txt").unlink()
        verdict = sides.compare(self.left, self.right)

        only = self.kinds(verdict)["only_left"]
        self.assertEqual([f.chapter for f in only], ["7"])
        self.assertEqual(verdict.fuller, "left")

    def test_the_side_that_lacks_chapters_is_not_the_one_advised(self):
        """Самая частая ошибка в такой сверке — перепутать стороны."""
        (self.left / "Глава 7.txt").unlink()
        (self.left / "Глава 8.txt").unlink()
        verdict = sides.compare(self.left, self.right)

        self.assertEqual(verdict.fuller, "right")
        self.assertIn("Правая", verdict.advice())
        self.assertEqual(len(self.kinds(verdict)["only_right"]), 2)


class TestCut(Base):
    def test_a_chapter_cut_in_half_is_found_on_the_right_side(self):
        self.write(self.right, 5, FULL[:120])
        verdict = sides.compare(self.left, self.right)

        cut = self.kinds(verdict)["empty_right"]
        self.assertEqual([f.chapter for f in cut], ["5"])
        self.assertEqual(verdict.fuller, "left")

    def test_a_noticeably_shorter_chapter_is_found(self):
        """Обрыв на середине — это не пусто, но и не разница переводов."""
        self.write(self.right, 5, FULL[:300])
        verdict = sides.compare(self.left, self.right)

        cut = self.kinds(verdict)["shorter_right"]
        self.assertEqual([f.chapter for f in cut], ["5"])
        # Числа рядом с находкой: без них «короче» нечем поверить.
        self.assertGreater(cut[0].left, cut[0].right)

    def test_ordinary_difference_between_translations_is_not_a_finding(self):
        """Два перевода одной главы расходятся в объёме, и звать это
        обрывом значило бы завалить отчёт шумом."""
        self.write(self.right, 5, FULL[:int(len(FULL) * 0.85)])
        self.assertEqual(sides.compare(self.left, self.right).findings, [])


class TestVerdict(Base):
    def test_losses_on_both_sides_do_not_pick_a_winner(self):
        (self.left / "Глава 3.txt").unlink()
        (self.right / "Глава 9.txt").unlink()
        verdict = sides.compare(self.left, self.right)

        self.assertEqual(verdict.fuller, "")
        self.assertIn("Ни одна не полнее", verdict.advice())

    def test_the_advice_counts_both_kinds_of_loss(self):
        (self.right / "Глава 4.txt").unlink()
        self.write(self.right, 6, FULL[:120])
        verdict = sides.compare(self.left, self.right)

        advice = verdict.advice()
        self.assertIn("Левая", advice)
        self.assertIn("только в ней", advice)
        self.assertIn("обрезан", advice)

    def test_every_kind_has_a_name_for_the_page(self):
        (self.right / "Глава 4.txt").unlink()
        (self.left / "Глава 5.txt").unlink()
        self.write(self.right, 6, FULL[:120])
        self.write(self.left, 7, FULL[:300])

        for finding in sides.compare(self.left, self.right).findings:
            with self.subTest(finding.kind):
                self.assertIn(finding.kind, sides.KINDS)
                self.assertTrue(finding.as_dict()["kind_name"])

    def test_the_report_names_how_many_chapters_each_side_has(self):
        (self.right / "Глава 4.txt").unlink()
        data = sides.compare(self.left, self.right).as_dict()

        self.assertEqual(data["left_total"], 20)
        self.assertEqual(data["right_total"], 19)
        self.assertEqual(data["matched"], 19)


if __name__ == "__main__":
    unittest.main()
