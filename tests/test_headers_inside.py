"""Чистка шапок внутри одного файла (часть 3 ТЗ NEUROSTRAZH).

Книга одним файлом на тысячу глав — обычное дело. Сравнивать её не с чем:
прежний алгоритм искал повторы между файлами, находил одну строку и чистил
одно место. Здесь проверяются правила, которые ищут внутри самого файла.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import text  # noqa: E402
from ops import headers as headers_op  # noqa: E402


def book(chapters: int = 30, title: str = "Summoners War: Only I Summoned") -> list[str]:
    """Файл из примера ТЗ: заголовок, название книги, тот же заголовок."""
    lines: list[str] = []
    for number in range(1, chapters + 1):
        lines += [
            "",
            f"Chapter {number}_ Panicking Count Ashton",
            title,
            f"Chapter {number}: Panicking Count Ashton",
            "",
            f"Текст главы {number}.",
        ]
    return lines


class TestHeadingLook(unittest.TestCase):
    """3.3: как отличается заголовок главы от названия книги."""

    def test_russian_heading(self):
        self.assertTrue(text.looks_like_heading("Глава 55"))

    def test_english_heading(self):
        self.assertTrue(text.looks_like_heading("Chapter 241: Panicking Count"))

    def test_chinese_heading(self):
        self.assertTrue(text.looks_like_heading("第 241 章"))

    def test_a_word_without_a_number_is_not_a_heading(self):
        self.assertFalse(text.looks_like_heading("Глава семьи собралась"))

    def test_a_number_without_a_word_is_not_a_heading(self):
        self.assertFalse(text.looks_like_heading("Ему было 55 лет"))

    def test_a_long_line_is_not_a_heading(self):
        self.assertFalse(text.looks_like_heading("Глава 5 " + "а" * 200))

    def test_the_name_from_the_file_counts_as_a_heading(self):
        self.assertTrue(text.looks_like_heading("Паучьи будни",
                                                title="Паучьи будни"))


class TestRepeatRule(unittest.TestCase):
    """3.3, правило первое: строка, повторяющаяся внутри файла."""

    def test_the_book_name_works_itself_out(self):
        found = text.find_repeats_inside(book(chapters=30))
        self.assertEqual([f.text for f in found],
                         ["Summoners War: Only I Summoned"])

    def test_threshold_is_adjustable(self):
        self.assertEqual(text.find_repeats_inside(book(chapters=10)), [])
        found = text.find_repeats_inside(book(chapters=10), repeat=5)
        self.assertTrue(found)

    def test_a_short_book_is_caught_by_the_share(self):
        """На сорока главах двадцати повторов нет, а шапка есть."""
        found = text.find_repeats_inside(book(chapters=12), chapters=12)
        self.assertEqual([f.text for f in found],
                         ["Summoners War: Only I Summoned"])

    def test_the_chapter_text_is_not_a_header(self):
        found = text.find_repeats_inside(book(chapters=30))
        self.assertNotIn("Текст главы 1.", [f.text for f in found])

    def test_a_long_line_is_never_a_header(self):
        lines = ["а" * 300] * 50
        self.assertEqual(text.find_repeats_inside(lines), [])

    def test_places_are_reported(self):
        found = text.find_repeats_inside(book(chapters=30))
        self.assertEqual(len(found[0].at), 30)

    def test_count_is_in_the_caption(self):
        """3.5: «встречается 1004 раза» — иначе непонятен масштаб."""
        found = text.find_repeats_inside(book(chapters=30))
        self.assertEqual(found[0].label, "встречается 30 раз")

    def test_russian_counting(self):
        self.assertEqual(text._times(1004), "1004 раза")
        self.assertEqual(text._times(1001), "1001 раз")
        self.assertEqual(text._times(1005), "1005 раз")
        self.assertEqual(text._times(11), "11 раз")
        self.assertEqual(text._times(12), "12 раз")


class TestDoubleRule(unittest.TestCase):
    """3.3, правило второе: сдвоенный заголовок."""

    def test_different_separators_are_the_same_heading(self):
        found = text.find_doubles_inside(book(chapters=30))
        self.assertIsNotNone(found)
        self.assertEqual(found.count, 30)

    def test_one_item_with_a_number_not_a_thousand_items(self):
        """3.5: список на тысячу строк прочитать нельзя."""
        found = text.find_doubles_inside(book(chapters=1000))
        self.assertEqual(found.count, 1000)
        self.assertEqual(found.label, "найдено 1000 раз")

    def test_nothing_to_find_in_a_clean_file(self):
        lines = ["Глава 1", "", "Текст.", "", "Глава 2", "", "Текст."]
        self.assertIsNone(text.find_doubles_inside(lines))

    def test_a_blank_line_between_is_not_a_double(self):
        lines = ["Глава 1", "", "Глава 1", "текст"]
        self.assertIsNone(text.find_doubles_inside(lines))

    def test_first_line_stays_second_and_third_go(self):
        cleaned = text.strip_headers_inside(
            book(chapters=2), [{"kind": text.HEAD_DOUBLE}])
        self.assertEqual(cleaned, [
            "", "Chapter 1_ Panicking Count Ashton", "", "Текст главы 1.",
            "", "Chapter 2_ Panicking Count Ashton", "", "Текст главы 2.",
        ])


class TestNeighbourRule(unittest.TestCase):
    """3.3, правило третье: одиночный заголовок с названием книги рядом."""

    def single(self, chapters: int = 30, before: bool = False) -> list[str]:
        lines: list[str] = []
        for number in range(1, chapters + 1):
            head = [f"Глава {number}", "Название книги"]
            if before:
                head.reverse()
            lines += head + ["", f"Текст главы {number}."]
        return lines

    def test_the_book_name_next_to_a_heading_is_found(self):
        lines = self.single()
        repeats = text.find_repeats_inside(lines)
        found = text.find_neighbours_inside(lines, repeats)
        self.assertEqual([f.text for f in found], ["Название книги"])

    def test_the_reverse_order_works_too(self):
        lines = self.single(before=True)
        repeats = text.find_repeats_inside(lines)
        found = text.find_neighbours_inside(lines, repeats)
        self.assertEqual([f.text for f in found], ["Название книги"])

    def test_only_the_book_name_goes_the_heading_stays(self):
        cleaned = text.strip_headers_inside(
            self.single(chapters=2),
            [{"kind": text.HEAD_NEIGHBOUR, "text": "Название книги"}])
        self.assertEqual(cleaned, [
            "Глава 1", "", "Текст главы 1.",
            "Глава 2", "", "Текст главы 2.",
        ])

    def test_a_repeated_line_in_the_middle_of_the_text_is_not_a_neighbour(self):
        """Заголовок рядом — признак шапки. В глубине главы его нет."""
        lines = []
        for number in range(1, 31):
            lines += [f"Глава {number}", "", "Начало.", "конец связи",
                      "Продолжение.", ""]
        repeats = text.find_repeats_inside(lines)
        found = text.find_neighbours_inside(lines, repeats)
        self.assertNotIn("конец связи", [f.text for f in found])


class TestManualRule(unittest.TestCase):
    """3.4: своё выражение с предпросмотром."""

    def test_plain_text_matches(self):
        found = text.find_by_pattern(book(chapters=30), "Summoners War")
        self.assertEqual(found.count, 30)

    def test_a_regular_expression_matches_too(self):
        found = text.find_by_pattern(book(chapters=30), r"^Chapter \d+_")
        self.assertEqual(found.count, 30)

    def test_places_are_shown(self):
        found = text.find_by_pattern(book(chapters=30), "Summoners War")
        self.assertEqual(len(found.at), 30)

    def test_a_broken_expression_says_so(self):
        with self.assertRaises(ValueError):
            text.find_by_pattern(["текст"], "[неза")

    def test_no_matches_is_not_a_finding(self):
        self.assertIsNone(text.find_by_pattern(["текст"], "чего тут нет"))

    def test_matched_lines_are_removed(self):
        cleaned = text.strip_headers_inside(
            book(chapters=1),
            [{"kind": text.HEAD_MANUAL, "value": "Summoners War"}])
        self.assertNotIn("Summoners War: Only I Summoned", cleaned)


class TestPositionRule(unittest.TestCase):
    """3.4: «удалять N-ю строку после каждого заголовка»."""

    def dated(self, chapters: int = 5) -> list[str]:
        lines: list[str] = []
        for number in range(1, chapters + 1):
            lines += [f"Глава {number}", f"выложено 0{number}.05.2024",
                      "", f"Текст главы {number}."]
        return lines

    def test_the_line_after_the_heading_is_found(self):
        found = text.find_by_position(self.dated(), 1)
        self.assertEqual(found.count, 5)

    def test_it_works_where_the_junk_never_repeats(self):
        """Дата в каждой главе своя — первое правило её не поймает."""
        self.assertEqual(text.find_repeats_inside(self.dated(50)), [])
        self.assertEqual(text.find_by_position(self.dated(50), 1).count, 50)

    def test_zero_means_the_rule_is_off(self):
        self.assertIsNone(text.find_by_position(self.dated(), 0))

    def test_removal_keeps_the_heading(self):
        cleaned = text.strip_headers_inside(
            self.dated(2), [{"kind": text.HEAD_POSITION, "value": "1"}])
        self.assertEqual(cleaned, [
            "Глава 1", "", "Текст главы 1.",
            "Глава 2", "", "Текст главы 2.",
        ])


class TestAllRulesTogether(unittest.TestCase):
    """3.6: алгоритм один и на один файл, и на папку с главами."""

    def test_the_example_from_the_spec(self):
        found = text.find_headers_inside(book(chapters=30))
        kinds = {f.kind for f in found}
        self.assertIn(text.HEAD_REPEAT, kinds)
        self.assertIn(text.HEAD_DOUBLE, kinds)

    def test_a_line_is_not_listed_twice(self):
        found = text.find_headers_inside(book(chapters=30))
        texts = [f.text for f in found if f.kind != text.HEAD_DOUBLE]
        self.assertEqual(len(texts), len(set(texts)))

    def test_the_file_becomes_what_the_spec_asks_for(self):
        found = text.find_headers_inside(book(chapters=30))
        cleaned = text.strip_headers_inside(
            book(chapters=30), [f.as_dict() for f in found])
        self.assertEqual(cleaned[:8], [
            "", "Chapter 1_ Panicking Count Ashton", "", "Текст главы 1.",
            "", "Chapter 2_ Panicking Count Ashton", "", "Текст главы 2.",
        ])
        self.assertEqual(len(cleaned), 30 * 4)

    def test_the_chapter_heading_is_never_offered_for_removal(self):
        """Заголовок — это ровно то, что чистка обязана оставить."""
        found = text.find_headers_inside(book(chapters=30), repeat=1)
        offered = [f.text for f in found if f.kind == text.HEAD_REPEAT]
        self.assertEqual(offered, ["Summoners War: Only I Summoned"])

    def test_plain_strings_still_work(self):
        """Старый вызов со списком строк ломаться не должен."""
        cleaned = text.strip_headers_inside(
            book(chapters=1), ["Summoners War: Only I Summoned"])
        self.assertNotIn("Summoners War: Only I Summoned", cleaned)

    def test_nothing_found_shows_the_first_lines(self):
        """3.4: «ничего не найдено» — не ответ."""
        lines = ["Глава 1", "", "Текст."]
        self.assertEqual(text.find_headers_inside(lines), [])
        shown = text.peek(lines)
        self.assertEqual(shown[0], {"number": 1, "text": "Глава 1"})
        self.assertEqual(len(shown), 3)

    def test_peek_is_limited(self):
        self.assertEqual(len(text.peek(["строка"] * 100)), text.HEAD_PEEK)

    def test_manual_parse_gets_thirty_lines(self):
        shown = text.peek(["строка"] * 100, text.HEAD_MANUAL_LINES)
        self.assertEqual(len(shown), 30)
        self.assertEqual(shown[-1]["number"], 30)


class TestWholeOperation(unittest.TestCase):
    """3.6: один алгоритм и на файл-книгу, и на папку с главами."""

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

    def one_file(self, chapters: int = 40) -> Path:
        path = self.root / "book.txt"
        path.write_text("\n\n".join(book(chapters)), encoding="utf-8")
        return path

    def folder(self, chapters: int = 20) -> Path:
        folder = self.root / "главы"
        folder.mkdir()
        for number in range(1, chapters + 1):
            (folder / f"{number:03d}.txt").write_text(
                f"Chapter {number}_ Panicking Count Ashton\n\n"
                "Summoners War: Only I Summoned\n\n"
                f"Chapter {number}: Panicking Count Ashton\n\n"
                f"Текст главы {number}.\n", encoding="utf-8")
        return folder

    def test_one_file_is_scanned_from_the_inside(self):
        found = headers_op.scan([str(self.one_file())])
        self.assertEqual([f["text"] for f in found["inside"]],
                         ["Summoners War: Only I Summoned",
                          "Сдвоенный заголовок главы"])

    def test_one_file_gives_no_nonsense_between_files(self):
        """В одном файле любая строка встречается «во всех файлах»."""
        found = headers_op.scan([str(self.one_file())])
        self.assertEqual(found["findings"], [])

    def test_a_folder_still_works_the_old_way(self):
        found = headers_op.scan([str(self.folder())])
        self.assertIn("Summoners War: Only I Summoned",
                      [f["text"] for f in found["findings"]])

    def test_the_double_is_found_in_a_folder_too(self):
        found = headers_op.scan([str(self.folder())])
        self.assertIn("Сдвоенный заголовок главы",
                      [f["text"] for f in found["inside"]])

    def test_findings_from_all_files_are_added_up(self):
        """Иначе список будет на тысячу одинаковых строк."""
        found = headers_op.scan([str(self.folder(20))])
        double = [f for f in found["inside"] if f["kind"] == text.HEAD_DOUBLE]
        self.assertEqual(len(double), 1)
        self.assertEqual(double[0]["count"], 20)

    def test_cleaning_leaves_one_heading_and_the_text(self):
        source = self.one_file(40)
        found = headers_op.scan([str(source)])
        out = self.root / "чисто"
        report = headers_op.run([str(source)], out, [], rules=found["inside"])
        self.assertEqual(report.written, 1)

        result = (out / "book.txt").read_text(encoding="utf-8")
        self.assertNotIn("Summoners War", result)
        self.assertIn("Chapter 1_ Panicking Count Ashton", result)
        self.assertNotIn("Chapter 1: Panicking Count Ashton", result)
        self.assertIn("Текст главы 40.", result)

    def test_nothing_marked_is_not_a_removal(self):
        source = self.one_file(40)
        out = self.root / "нетронуто"
        report = headers_op.run([str(source)], out, [], rules=[])
        result = (out / "book.txt").read_text(encoding="utf-8")
        self.assertIn("Summoners War", result)
        self.assertEqual(report.written, 1)

    def test_first_lines_are_offered_when_rules_find_nothing(self):
        path = self.root / "чистая.txt"
        path.write_text("Глава 1\n\nТекст.\n", encoding="utf-8")
        found = headers_op.scan([str(path)])
        self.assertEqual(found["inside"], [])
        self.assertTrue(found["peek"])

    def test_a_short_book_is_caught_by_the_share_not_by_the_count(self):
        """«Больше 20 раз ЛИБО чаще чем в трети глав» — правило из ТЗ.

        На книге в десять глав двадцати повторов не наберётся, а шапка
        всё равно шапка.
        """
        found = headers_op.scan([str(self.one_file(10))])
        self.assertIn("Summoners War: Only I Summoned",
                      [f["text"] for f in found["inside"]])

    def test_a_rare_line_is_not_a_header(self):
        path = self.root / "редкая.txt"
        lines = []
        for number in range(1, 41):
            lines += [f"Глава {number}", "", f"Текст главы {number}."]
            if number % 10 == 0:
                lines += ["конец тома", ""]
        path.write_text("\n\n".join(lines), encoding="utf-8")
        found = headers_op.scan([str(path)])
        self.assertNotIn("конец тома", [f["text"] for f in found["inside"]])

    def test_the_threshold_reaches_the_operation(self):
        """Порог настраиваемый: с ним находится и то, что реже трети."""
        path = self.root / "редкая.txt"
        lines = []
        for number in range(1, 41):
            lines += [f"Глава {number}", "", f"Текст главы {number}."]
            if number % 10 == 0:
                lines += ["конец тома", ""]
        path.write_text("\n\n".join(lines), encoding="utf-8")
        found = headers_op.scan([str(path)], repeat=3)
        self.assertIn("конец тома", [f["text"] for f in found["inside"]])

    def test_a_manual_expression_reaches_the_operation(self):
        found = headers_op.scan([str(self.one_file())], pattern="Summoners")
        kinds = [f["kind"] for f in found["inside"]]
        self.assertIn(text.HEAD_MANUAL, kinds)

    def test_a_broken_expression_is_a_human_error_not_a_crash(self):
        with self.assertRaises(ValueError):
            headers_op.scan([str(self.one_file())], pattern="[неза")


class TestWebRoutes(unittest.TestCase):
    """Правила должны доезжать до сервера и обратно."""

    @classmethod
    def setUpClass(cls):
        from webapp.app import app

        app.config["TESTING"] = True
        cls.app = app.test_client()

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.path = self.root / "book.txt"
        self.path.write_text("\n\n".join(book(40)), encoding="utf-8")

    def test_scan_returns_the_inside_findings(self):
        res = self.app.post("/api/headers/scan",
                            json={"targets": [str(self.path)]})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["inside"])
        self.assertTrue(body["peek"])

    def test_scan_takes_the_threshold_and_the_expression(self):
        res = self.app.post("/api/headers/scan",
                            json={"targets": [str(self.path)],
                                  "repeat": 5, "pattern": "Summoners"})
        kinds = [f["kind"] for f in res.get_json()["inside"]]
        self.assertIn(text.HEAD_MANUAL, kinds)

    def test_a_broken_expression_is_400_not_500(self):
        res = self.app.post("/api/headers/scan",
                            json={"targets": [str(self.path)],
                                  "pattern": "[неза"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Выражение", res.get_json()["error"])

    def test_rules_alone_are_enough_to_start(self):
        """Между файлами находок нет, а внутри — есть: чистить можно."""
        res = self.app.post("/api/headers/clean", json={
            "targets": [str(self.path)],
            "base": str(self.root), "folder": "чисто",
            "texts": [], "rules": [{"kind": text.HEAD_DOUBLE}],
        })
        self.assertEqual(res.status_code, 200)

    def test_nothing_marked_at_all_is_refused(self):
        res = self.app.post("/api/headers/clean", json={
            "targets": [str(self.path)],
            "base": str(self.root), "folder": "чисто",
            "texts": [], "rules": [],
        })
        self.assertEqual(res.status_code, 400)


class TestInsideUi(unittest.TestCase):
    """Разметка и обработчики на месте — иначе всё это некуда нажать."""

    @classmethod
    def setUpClass(cls):
        static = Path(__file__).resolve().parent.parent / "webapp" / "static"
        cls.page = (static / "index.html").read_text(encoding="utf-8")
        cls.tabs = (static / "tabs.js").read_text(encoding="utf-8")

    def test_there_is_a_place_for_the_inside_findings(self):
        self.assertIn('id="hdInside"', self.page)

    def test_every_rule_control_exists(self):
        for control in ("hdRepeat", "hdOffset", "hdPattern", "hdRescan",
                        "hdPeek"):
            with self.subTest(control=control):
                self.assertIn(f'id="{control}"', self.page)

    def test_every_rule_control_has_a_handler(self):
        self.assertIn("$('hdRescan').onclick", self.tabs)
        for field in ("hdRepeat", "hdOffset", "hdPattern"):
            with self.subTest(field=field):
                self.assertIn(f"'{field}'", self.tabs)

    def test_rules_are_sent_for_cleaning(self):
        self.assertIn("rules: hdRules()", self.tabs)

    def test_the_button_counts_both_lists(self):
        self.assertIn("hdChosen.size + hdInsideChosen.size", self.tabs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
