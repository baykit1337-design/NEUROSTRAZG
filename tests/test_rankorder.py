"""Порядок среза рейтинга: по главам, по объёму, новинки вверх.

Главное здесь — не соврать. Поля у сайтов разные: у MVLEMPYR есть число
глав, у Webnovel только число рядом с книгой, а даты выхода нет ни у
кого. Порядок, который на половине рейтингов молча ничего не делает,
хуже, чем его отсутствие.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources.rank import RankRow  # noqa: E402
from ops import rank  # noqa: E402


def rows():
    return [
        RankRow(place=1, book_id="a", name="Первая", chapters=374, score=4.1),
        RankRow(place=2, book_id="b", name="Вторая", chapters=1200, score=4.9),
        RankRow(place=3, book_id="c", name="Третья", chapters=0, score=3.1),
        RankRow(place=4, book_id="d", name="Четвёртая", chapters=55, score=4.5),
    ]


def names(found):
    return [row.name for row in found]


class TestOrder(unittest.TestCase):
    def test_by_place_is_the_boards_own_order(self):
        self.assertEqual(names(rank.order(rows(), "place")),
                         ["Первая", "Вторая", "Третья", "Четвёртая"])

    def test_many_chapters_first(self):
        self.assertEqual(names(rank.order(rows(), "chapters", desc=True))[:2],
                         ["Вторая", "Первая"])

    def test_few_chapters_first(self):
        self.assertEqual(names(rank.order(rows(), "chapters", desc=False))[:2],
                         ["Четвёртая", "Первая"])

    def test_a_book_without_the_number_sinks_in_both_directions(self):
        """«Сначала те, у кого мало глав» не должно означать «сначала те,
        про кого мы ничего не знаем»."""
        for desc in (True, False):
            with self.subTest(desc=desc):
                self.assertEqual(
                    names(rank.order(rows(), "chapters", desc=desc))[-1],
                    "Третья")

    def test_new_books_come_up_and_keep_their_places_inside(self):
        """Новая книга на пятом месте интереснее новой на сороковом."""
        found = rank.order(rows(), "new", fresh={"d", "c"})
        self.assertEqual(names(found)[:2], ["Третья", "Четвёртая"])

    def test_an_unknown_order_falls_back_to_place(self):
        self.assertEqual(names(rank.order(rows(), "выдумка")),
                         ["Первая", "Вторая", "Третья", "Четвёртая"])


class TestHonesty(unittest.TestCase):
    def test_it_counts_how_many_rows_know_the_field(self):
        self.assertEqual(rank.known(rows(), "chapters"), 3)

    def test_a_rating_without_the_field_at_all_is_told_apart(self):
        """У Webnovel в срезе нет ни числа глав, ни объёма. Молча
        оставить прежний порядок нельзя — человек решит, что сортировка
        сломана."""
        self.assertEqual(rank.known(rows(), "words"), 0)

    def test_place_is_known_for_everyone(self):
        self.assertEqual(rank.known(rows(), "place"), len(rows()))

    def test_there_is_no_order_by_release_date(self):
        """Даты выхода не отдаёт ни один из четырёх рейтингов: три не
        пишут поле вовсе, Цидянь кладёт в него строку со страницы. Пункт
        меню, который ничего не делает, обещал бы несуществующее."""
        self.assertNotIn("date", rank.ORDERS)
        self.assertNotIn("updated", rank.ORDER_FIELDS.values())

    def test_every_field_order_names_a_real_row_field(self):
        """Порядок по полю, которого нет в строке, молча ничего не
        отсортировал бы."""
        sample = RankRow()
        for key, field in rank.ORDER_FIELDS.items():
            with self.subTest(key):
                self.assertIn(key, rank.ORDERS)
                self.assertTrue(hasattr(sample, field), field)


if __name__ == "__main__":
    unittest.main()
