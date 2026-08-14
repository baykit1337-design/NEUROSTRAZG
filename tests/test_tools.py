"""Инструменты редактора (часть 4 ТЗ NEUROSTRAZH).

Пакетная замена, словарь автозамен и сверка оригинала с переводом.
Интернет не нужен: всё считается по файлам на диске.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core.models import Chapter  # noqa: E402
from ops import compare, replace  # noqa: E402


class ToolsTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def folder(self, name, chapters):
        """Папка с главами: {номер: [абзацы]}."""
        path = self.tmp / name
        path.mkdir(exist_ok=True)
        for number, paragraphs in chapters.items():
            formats.write(path / f"Глава {number}.txt",
                          [Chapter(number=number, title=f"Глава {number}",
                                   paragraphs=list(paragraphs))],
                          headings=True)
        return str(path)


class TestReplace(ToolsTestCase):
    """4.1: найти и заменить сразу по всей книге."""

    def book(self):
        return self.folder("книга", {
            201: ["Тео позвал Элиаса.", "Элиас пришёл."],
            202: ["Элиас молчал."],
            203: ["Здесь про другое."],
        })

    def test_preview_finds_every_match_with_context(self):
        found = replace.preview(self.book(), [{"find": "Элиас", "replace": "Элайас"}])
        self.assertEqual(found.total, 3)
        self.assertEqual(found.touched, 2)
        self.assertTrue(all(m.before for m in found.matches))
        self.assertEqual(found.matches[0].after, "Элайас")

    def test_preview_writes_nothing(self):
        book = self.book()
        before = {p.name: p.read_text(encoding="utf-8") for p in Path(book).iterdir()}
        replace.preview(book, [{"find": "Элиас", "replace": "Элайас"}])
        after = {p.name: p.read_text(encoding="utf-8") for p in Path(book).iterdir()}
        self.assertEqual(before, after)

    def test_run_writes_to_a_new_folder_and_keeps_originals(self):
        book = self.book()
        before = {p.name: p.read_text(encoding="utf-8") for p in Path(book).iterdir()}

        out = self.tmp / "правлено"
        report = replace.run(book, out, [{"find": "Элиас", "replace": "Элайас"}])

        self.assertEqual(report.written, 3)
        self.assertEqual(report.as_dict()["replaced"], 3)
        self.assertIn("Элайас", (out / "Глава 202.txt").read_text(encoding="utf-8"))
        after = {p.name: p.read_text(encoding="utf-8") for p in Path(book).iterdir()}
        self.assertEqual(before, after)

    def test_case_sensitivity(self):
        book = self.folder("регистр", {1: ["Тео и тео."]})
        loose = replace.preview(book, [{"find": "тео", "replace": "Х"}])
        strict = replace.preview(book, [{"find": "тео", "replace": "Х", "case": True}])
        self.assertEqual(loose.total, 2)
        self.assertEqual(strict.total, 1)

    def test_plain_search_does_not_treat_dots_as_regex(self):
        """«т.е.» не должно совпадать с «тхей»."""
        book = self.folder("точки", {1: ["т.е. и тхей"]})
        found = replace.preview(book, [{"find": "т.е.", "replace": "то есть"}])
        self.assertEqual(found.total, 1)

    def test_regex_with_groups(self):
        book = self.folder("группы", {1: ["Глава 5 началась"]})
        found = replace.preview(
            book, [{"find": r"Глава (\d+)", "replace": r"Chapter \1", "regex": True}])
        self.assertEqual(found.matches[0].after, "Chapter 5")

    def test_broken_regex_is_reported_clearly(self):
        with self.assertRaises(replace.ReplaceError):
            replace.preview(self.book(), [{"find": "(незакрытая", "regex": True}])

    def test_empty_rule_is_refused(self):
        with self.assertRaises(replace.ReplaceError):
            replace.preview(self.book(), [{"find": "", "replace": "х"}])

    def test_empty_matches_do_not_flood_the_preview(self):
        """Правило «а*» совпадает между каждыми двумя буквами."""
        book = self.folder("пустые", {1: ["Короткий текст"]})
        found = replace.preview(book, [{"find": "я*", "replace": "", "regex": True}])
        self.assertEqual(found.total, 0)

    def test_unchecked_matches_are_skipped(self):
        """Снятое в предпросмотре совпадение не заменяется."""
        book = self.folder("выбор", {1: ["Элиас тут", "Элиас там"]})
        source = str(Path(book) / "Глава 1.txt")
        out = self.tmp / "часть"
        replace.run(book, out, [{"find": "Элиас", "replace": "Х"}],
                    skip={(source, 2, 0, 0)})

        text = (out / "Глава 1.txt").read_text(encoding="utf-8")
        self.assertIn("Х тут", text)
        self.assertIn("Элиас там", text)

    def test_skip_touches_one_match_not_the_whole_paragraph(self):
        """В абзаце три вхождения; снято одно — остальные заменяются."""
        book = self.folder("одно", {1: ["Элиас, Элиас и Элиас"]})
        source = str(Path(book) / "Глава 1.txt")
        out = self.tmp / "одно-вых"
        report = replace.run(book, out, [{"find": "Элиас", "replace": "Х"}],
                             skip={(source, 1, 0, 1)})

        text = (out / "Глава 1.txt").read_text(encoding="utf-8")
        self.assertIn("Х, Элиас и Х", text)
        self.assertEqual(report.as_dict()["replaced"], 2)

    def test_preview_numbers_matches_within_a_paragraph(self):
        book = self.folder("номера", {1: ["Элиас, Элиас и Элиас"]})
        found = replace.preview(book, [{"find": "Элиас", "replace": "Х"}])
        self.assertEqual([m.index for m in found.matches], [0, 1, 2])

    def test_service_files_are_not_read_as_chapters(self):
        """Словарь автозамен лежит рядом с книгой, но главой не является."""
        book = Path(self.folder("служебные", {1: ["Текст главы."]}))
        replace.save_dictionary(book, "Элиас = Элайас\n")
        (book / "whitelist.txt").write_text("Тео\n", encoding="utf-8")

        found = replace.preview(str(book), [{"find": "Элиас", "replace": "Х"}])
        self.assertEqual(found.files, 1)
        self.assertEqual(found.total, 0)

    def test_several_rules_at_once(self):
        book = self.folder("много", {1: ["Тео и Элиас"]})
        out = self.tmp / "оба"
        replace.run(book, out, [{"find": "Тео", "replace": "A"},
                                {"find": "Элиас", "replace": "B"}])
        self.assertIn("A и B", (out / "Глава 1.txt").read_text(encoding="utf-8"))


class TestDictionary(ToolsTestCase):
    """4.2: свой словарь автозамен, отдельный для каждой книги."""

    def test_parses_pairs_and_skips_comments(self):
        rules = replace.parse_dictionary(
            "# заголовок\nбыло = стало\n\n// ещё\nдругое = третье\n")
        self.assertEqual([(r.find, r.replace) for r in rules],
                         [("было", "стало"), ("другое", "третье")])

    def test_regex_rules_are_marked(self):
        rules = replace.parse_dictionary(r"re:Глава (\d+) = Chapter \1")
        self.assertTrue(rules[0].regex)
        self.assertEqual(rules[0].find, r"Глава (\d+)")

    def test_plain_rules_are_not_regex(self):
        self.assertFalse(replace.parse_dictionary("т.е. = то есть")[0].regex)

    def test_dictionary_lives_next_to_the_book(self):
        book = Path(self.folder("книга", {1: ["Элиас"]}))
        replace.save_dictionary(book, "Элиас = Элайас\n")
        self.assertTrue((book / replace.DICT_FILE).is_file())
        self.assertEqual(len(replace.load_dictionary(book)), 1)

    def test_missing_dictionary_is_not_an_error(self):
        self.assertEqual(replace.load_dictionary(self.tmp), [])

    def test_summary_counts_each_rule(self):
        book = self.folder("сводка", {1: ["Элиас и Элиас", "Тео"]})
        rules = replace.parse_dictionary("Элиас = Х\nТео = Y\nНету = Z\n")
        summary = replace.dictionary_summary(book, rules)

        self.assertEqual(summary["total"], 3)
        counts = {r["find"]: r["count"] for r in summary["rules"]}
        self.assertEqual(counts, {"Элиас": 2, "Тео": 1, "Нету": 0})


class TestCompare(ToolsTestCase):
    """4.3: сверка оригинала и перевода по номерам глав."""

    def pair(self, original, translated):
        return (self.folder("оригинал", original),
                self.folder("перевод", translated))

    def kinds(self, report):
        return [f.kind for f in report.findings]

    def test_missing_chapter(self):
        left, right = self.pair({1: ["Text one."], 2: ["Text two."]},
                                {1: ["Текст один."]})
        report = compare.check(left, right)
        self.assertIn("missing", self.kinds(report))
        self.assertEqual(report.original, 2)
        self.assertEqual(report.translated, 1)

    def test_extra_chapter(self):
        left, right = self.pair({1: ["Text."]},
                                {1: ["Текст."], 2: ["Лишняя."]})
        self.assertIn("extra", self.kinds(compare.check(left, right)))

    def test_paragraph_count_gap(self):
        # Абзацы длинные намеренно: короткая глава попала бы под «пустая»,
        # и до сравнения абзацев дело бы не дошло.
        left, right = self.pair(
            {1: [f"Paragraph {n} of the original text, long enough. " * 3
                 for n in range(10)]},
            {1: [f"Абзац {n} переведённого текста, достаточно длинный. " * 6
                 for n in range(5)]})
        self.assertIn("paragraphs", self.kinds(compare.check(left, right)))

    def test_same_paragraph_count_is_quiet(self):
        left, right = self.pair(
            {1: [f"Paragraph number {n} here." for n in range(10)]},
            {1: [f"Абзац номер {n} тут." for n in range(10)]})
        self.assertNotIn("paragraphs", self.kinds(compare.check(left, right)))

    def test_suspicious_volume(self):
        left, right = self.pair({1: ["Long original text. " * 60]},
                                {1: ["Коротко. " * 3]})
        report = compare.check(left, right)
        self.assertTrue({"ratio", "empty"} & set(self.kinds(report)))

    def test_empty_translation(self):
        left, right = self.pair({1: ["Long original text. " * 60]},
                                {1: ["Оборвалась"]})
        report = compare.check(left, right)
        self.assertIn("empty", self.kinds(report))
        # Пустую главу дальше не разбираем — и так ясно, что смотреть.
        self.assertEqual(len([f for f in report.findings if f.chapter == "1"]), 1)

    def test_normal_translation_is_quiet(self):
        left, right = self.pair(
            {1: ["The original sentence goes here. " * 20]},
            {1: ["Здесь идёт переведённое предложение. " * 20]})
        report = compare.check(left, right)
        self.assertEqual(report.findings, [])
        self.assertEqual(report.matched, 1)

    def test_only_chosen_kinds(self):
        left, right = self.pair({1: ["Text."], 2: ["More."]},
                                {1: ["Текст."]})
        report = compare.check(left, right, kinds=["extra"])
        self.assertNotIn("missing", self.kinds(report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
