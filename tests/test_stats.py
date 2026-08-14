"""Статистика книги и подпись в главах (4.7 и 4.8 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core.models import Chapter  # noqa: E402
from ops import signature, stats  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def folder(self, name, chapters):
        path = self.tmp / name
        path.mkdir(parents=True, exist_ok=True)
        for number, paragraphs in chapters.items():
            formats.write(path / f"Глава {number}.txt",
                          [Chapter(number=number, title=f"Глава {number}",
                                   paragraphs=list(paragraphs))],
                          headings=True)
        return str(path)


class TestStats(Base):
    """4.7: сколько глав, символов, слов и сколько это читать."""

    def book(self):
        return self.folder("книга", {
            1: ["Одно слово."],
            2: ["Тут ровно четыре слова здесь."],
            3: ["Длинная глава. " * 50],
        })

    def test_counts(self):
        report = stats.collect(self.book()).as_dict()
        self.assertEqual(report["chapters"], 3)
        self.assertGreater(report["characters"], 0)
        self.assertGreater(report["words"], 0)
        self.assertEqual(report["paragraphs"], 3)

    def test_shortest_and_longest(self):
        report = stats.collect(self.book()).as_dict()
        self.assertEqual(report["shortest"]["label"], "1")
        self.assertEqual(report["longest"]["label"], "3")

    def test_median_is_reported_next_to_the_average(self):
        """Одна глава-гигант перекашивает среднее — медиана честнее."""
        report = stats.collect(self.book()).as_dict()
        self.assertIn("median", report)
        self.assertLess(report["median"], report["average"])

    def test_reading_time_is_human(self):
        report = stats.collect(self.book()).as_dict()
        self.assertRegex(report["reading_time"], r"(мин|ч|дн)")

    def test_long_book_reads_in_hours(self):
        big = {n: ["Слово " * 400] for n in range(1, 30)}
        report = stats.collect(self.folder("большая", big)).as_dict()
        self.assertIn("ч", report["reading_time"])

    def test_buckets_are_capped(self):
        """На пятистах главах пятьсот столбиков сливаются в кашу."""
        many = {n: [f"Текст главы {n}. " * 5] for n in range(1, 300)}
        report = stats.collect(self.folder("много", many)).as_dict()
        self.assertLessEqual(len(report["buckets"]), stats.BUCKETS + 1)
        self.assertEqual(sum(b["count"] for b in report["buckets"]), 299)

    def test_empty_selection_is_not_a_crash(self):
        empty = stats.Report()
        self.assertEqual(empty.as_dict()["chapters"], 0)


class TestSignature(Base):
    """4.8: шапка и подпись при экспорте, в исходниках не сохраняются."""

    def book(self):
        return self.folder("книга", {
            1: ["Текст первой главы."],
            2: ["Текст второй главы."],
            3: ["Текст третьей главы."],
        })

    def test_head_and_foot_are_added(self):
        out = self.tmp / "с-подписью"
        template = signature.Template(head="Перевод: я", foot="Спасибо за чтение")
        report = signature.run(self.book(), out, template)

        self.assertEqual(report.written, 3)
        text = (out / "Глава 2.txt").read_text(encoding="utf-8")
        self.assertIn("Перевод: я", text)
        self.assertIn("Спасибо за чтение", text)
        self.assertIn("Текст второй главы", text)

    def test_placeholders_are_filled(self):
        out = self.tmp / "подстановки"
        template = signature.Template(
            head="Глава {номер} из {всего_глав}: {название}")
        signature.run(self.book(), out, template)

        text = (out / "Глава 2.txt").read_text(encoding="utf-8")
        self.assertIn("Глава 2 из 3", text)

    def test_date_is_substituted(self):
        from datetime import date

        template = signature.Template(foot="Выложено {дата}")
        lines = signature.fill(template.foot, Chapter(number=1), 1)
        self.assertIn(date.today().strftime("%d.%m.%Y"), lines[0])

    def test_edges_can_be_skipped(self):
        out = self.tmp / "без-краёв"
        template = signature.Template(head="ШАПКА", skip_edges=True)
        signature.run(self.book(), out, template)

        self.assertNotIn("ШАПКА", (out / "Глава 1.txt").read_text(encoding="utf-8"))
        self.assertIn("ШАПКА", (out / "Глава 2.txt").read_text(encoding="utf-8"))
        self.assertNotIn("ШАПКА", (out / "Глава 3.txt").read_text(encoding="utf-8"))

    def test_originals_are_untouched(self):
        """Иначе после двух прогонов подпись оказалась бы в главе дважды."""
        book = self.book()
        before = {p.name: p.read_text(encoding="utf-8")
                  for p in Path(book).iterdir()}
        signature.run(book, self.tmp / "копия",
                      signature.Template(head="ШАПКА"))
        after = {p.name: p.read_text(encoding="utf-8")
                 for p in Path(book).iterdir()}
        self.assertEqual(before, after)

    def test_empty_template_is_refused(self):
        with self.assertRaises(ValueError):
            signature.run(self.book(), self.tmp / "пусто", signature.Template())

    def test_multiline_template_becomes_paragraphs(self):
        lines = signature.fill("Первая строка\n\nВторая строка",
                               Chapter(number=1), 1)
        self.assertEqual(lines, ["Первая строка", "Вторая строка"])

    def test_preview_writes_nothing(self):
        book = self.book()
        before = sorted(p.name for p in Path(book).iterdir())
        result = signature.preview(book, signature.Template(head="ШАПКА"))

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["head"], ["ШАПКА"])
        self.assertEqual(sorted(p.name for p in Path(book).iterdir()), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
