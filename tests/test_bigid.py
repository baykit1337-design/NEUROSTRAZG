"""Длинные идентификаторы не должны портиться (1.2 ТЗ NEUROSTRAZH).

У Фанкью код книги — девятнадцать разрядов. JavaScript точно хранит целые
только до 9 007 199 254 740 992, то есть шестнадцати разрядов, а всё
больше округляет: `7590221243043826712` превращался в `...827000`,
возвращался на сервер уже испорченным и давал 404 на скачивании.

Лечится одним правилом: идентификатор ездит строкой и числом не бывает
нигде — ни в JSON, ни в JavaScript.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.api import Chapter, Novel  # noqa: E402
from net.sources import rank as rank_net  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"

#: Настоящий код из отчёта: ровно на нём всё и ломалось.
BIG = "7590221243043826712"

#: Дальше этого числа JavaScript целые уже не различает.
JS_SAFE = 9007199254740991


def rounds_in_js(value) -> bool:
    """Испортит ли JavaScript это число при разборе JSON.

    Считаем так же, как это делает браузер: число с плавающей точкой
    двойной точности, и обратно в целое.
    """
    return int(float(value)) != int(value)


class TestTheProblemIsReal(unittest.TestCase):
    """Проверка самой предпосылки — иначе чинить нечего."""

    def test_the_code_is_beyond_what_js_can_hold(self):
        self.assertGreater(int(BIG), JS_SAFE)

    def test_such_a_number_really_does_round(self):
        """Точность теряется — и это видно по любому представлению.

        В отчёте испорченный код выглядит как `...827000`, а Python на том
        же числе показывает `...826688`. Противоречия нет: это одно и то
        же число с плавающей точкой, просто JavaScript печатает кратчайшую
        запись, которая в него отображается. Важно другое — исходные цифры
        потеряны в обоих случаях.
        """
        self.assertTrue(rounds_in_js(BIG))
        self.assertNotEqual(int(float(BIG)), int(BIG))

    def test_a_string_does_not_round(self):
        """Строку браузер не трогает — на этом и построено лечение."""
        again = json.loads(json.dumps({"code": BIG}))
        self.assertEqual(again["code"], BIG)


class TestNovelTravelsAsAString(unittest.TestCase):
    def novel(self) -> Novel:
        return Novel(code=int(BIG), name="Книга", slug="", total_chapters=5)

    def test_the_code_leaves_as_a_string(self):
        self.assertIsInstance(self.novel().to_dict()["code"], str)

    def test_the_digits_are_exactly_the_ones_we_had(self):
        self.assertEqual(self.novel().to_dict()["code"], BIG)

    def test_nothing_in_the_json_can_round(self):
        """Ни одно число в ответе не должно быть длиннее безопасного."""
        body = self.novel().to_dict()
        for name, value in body.items():
            if isinstance(value, int) and not isinstance(value, bool):
                with self.subTest(field=name):
                    self.assertLessEqual(abs(value), JS_SAFE)

    def test_the_round_trip_is_exact(self):
        """Туда строкой, обратно строкой, и то же самое число."""
        from webapp.app import _novel_from_payload

        again = _novel_from_payload(self.novel().to_dict())
        self.assertEqual(again.code, int(BIG))
        self.assertEqual(again.to_dict()["code"], BIG)

    def test_a_short_code_still_works(self):
        """У других источников коды короткие — им это не должно мешать."""
        small = Novel(code=6615, name="к", slug="s", total_chapters=1)
        self.assertEqual(small.to_dict()["code"], "6615")


class TestChapterIdIsAString(unittest.TestCase):
    """У главы Фанкью идентификатор такой же длины, что и у книги."""

    def test_the_field_keeps_a_string(self):
        chapter = Chapter(number=1, post_id=BIG)
        self.assertEqual(chapter.post_id, BIG)

    def test_the_source_does_not_turn_it_into_a_number(self):
        source = (ROOT / "net" / "sources" / "fanqie.py").read_text(
            encoding="utf-8")
        self.assertIn("post_id=str(item_id)", source)
        self.assertNotIn("post_id=int(item_id)", source)


class TestRankIdsAreStrings(unittest.TestCase):
    """Рейтинг — начало пути: там идентификатор и появляется."""

    def test_the_row_keeps_it_as_a_string(self):
        row = rank_net.RankRow(book_id=int(BIG))
        self.assertEqual(row.as_dict()["book_id"], BIG)

    def test_it_survives_saving_and_loading(self):
        row = rank_net.RankRow(book_id=BIG)
        again = rank_net.RankRow.from_dict(row.as_dict())
        self.assertEqual(again.book_id, BIG)

    def test_the_link_is_built_from_the_exact_digits(self):
        self.assertTrue(rank_net.RankRow(book_id=BIG).as_dict()["link"]
                        .endswith(BIG))

    def test_the_book_page_keeps_every_id_as_a_string(self):
        """`uid`, `firstChapterId`, `lastChapterId` — той же длины."""
        state = {"page": {"bookInfo": {
            "bookId": int(BIG), "uid": int(BIG),
            "firstChapterId": int(BIG), "lastChapterId": int(BIG),
            "bookName": "к", "author": "а"}}}
        html = ("<html><script>window.__INITIAL_STATE__ = "
                + json.dumps(state) + ";</script></html>")
        found = rank_net.book_page(html)
        for name in ("book_id", "author_id", "first_chapter_id",
                     "last_chapter_id"):
            with self.subTest(field=name):
                self.assertEqual(found[name], BIG)


class TestNoNumericCoercionInTheBrowser(unittest.TestCase):
    """В JavaScript к идентификатору нельзя применять ничего числового."""

    @classmethod
    def setUpClass(cls):
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")
        cls.page = (STATIC / "index.html").read_text(encoding="utf-8")

    def test_the_id_is_never_run_through_number(self):
        for text in (self.tabs, self.page):
            for bad in ("Number(row.book_id", "parseInt(row.book_id",
                        "Number(novel.code", "parseInt(novel.code",
                        "+row.book_id", "+novel.code"):
                with self.subTest(bad=bad):
                    self.assertNotIn(bad, text)

    def test_the_id_goes_into_the_field_as_it_is(self):
        self.assertIn("$('q').value = row.book_id", self.tabs)

    def test_the_id_is_carried_in_a_data_attribute_unchanged(self):
        self.assertIn("box.dataset.book = row.book_id", self.tabs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
