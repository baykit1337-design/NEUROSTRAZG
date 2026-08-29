"""Общая доска: одна книга сразу на нескольких сайтах (пункт 17).

Ценность доски вся в склейке, поэтому проверяется именно она: книгу
узнали в двух рейтингах — строка одна; названия совпали, а авторы разные
— строки две.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources.rank import RankRow  # noqa: E402
from ops import everywhere, rank  # noqa: E402


NAMES = {"": "Фанкью", "qidian": "Цидянь", "mvl": "MVLEMPYR"}


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        # Срезы пишутся и читаются из своей папки: настоящую историю
        # рейтинга тесты трогать не должны.
        self._was = rank.RANK_DIR
        rank.RANK_DIR = self.tmp
        everywhere.RANK_DIR = self.tmp
        self.addCleanup(self._restore)

    def _restore(self):
        rank.RANK_DIR = self._was
        everywhere.RANK_DIR = self._was

    def snap(self, site, board, day, rows):
        rank.save([RankRow(place=place, book_id=str(place), name=name,
                           author=author, link=f"{site}/{place}")
                   for place, name, author in rows],
                  board=board, site=site, day=day)

    def board(self, **titles):
        return everywhere.board(names=NAMES, **titles)

    def by_name(self, board):
        found = {}
        for row in board.rows:
            found.setdefault(row.name, []).append(row)
        return found


class TestGluing(Base):
    def test_a_book_known_on_two_sites_is_one_row(self):
        self.snap("", "hot", "2026-08-01", [(1, "Рассвет", "Юй")])
        self.snap("qidian", "sales", "2026-08-01", [(5, "Рассвет", "Юй")])
        board = self.board()

        self.assertEqual(len(board.rows), 1)
        self.assertEqual(board.rows[0].sites, 2)
        self.assertEqual(board.shared, 1)
        self.assertEqual({s.place for s in board.rows[0].seats}, {1, 5})

    def test_each_seat_says_which_site_it_is(self):
        """«Первое место» без сайта не значит ничего."""
        self.snap("", "hot", "2026-08-01", [(1, "Рассвет", "Юй")])
        self.snap("qidian", "sales", "2026-08-01", [(5, "Рассвет", "Юй")])

        seats = {s.site: s.site_name for s in self.board().rows[0].seats}
        self.assertEqual(seats, {"": "Фанкью", "qidian": "Цидянь"})

    def test_the_name_is_matched_past_case_and_spaces(self):
        self.snap("", "hot", "2026-08-01", [(1, "Рассвет  Меча", "Юй")])
        self.snap("qidian", "sales", "2026-08-01", [(5, "рассвет меча", "Юй")])
        self.assertEqual(self.board().shared, 1)

    def test_the_same_name_by_another_author_stays_apart(self):
        """Название у книг совпадает чаще, чем кажется, и склеить две
        разные книги хуже, чем не склеить одну."""
        self.snap("", "hot", "2026-08-01", [(1, "Перерождение", "Юй")])
        self.snap("qidian", "sales", "2026-08-01", [(5, "Перерождение", "Ли")])
        board = self.board()

        self.assertEqual(len(board.rows), 2)
        self.assertEqual(board.shared, 0)

    def test_a_missing_author_does_not_stop_the_glue(self):
        """Автора в строке рейтинга нет у половины сайтов, и требовать
        его значило бы не склеить ничего."""
        self.snap("", "hot", "2026-08-01", [(1, "Рассвет", "Юй")])
        self.snap("mvl", "week", "2026-08-01", [(3, "Рассвет", "")])
        self.assertEqual(self.board().shared, 1)

    def test_a_book_without_a_name_is_not_glued_to_anything(self):
        """Название не расшифровалось. Свалить такие строки в кучу —
        получить одну книгу из сотни разных."""
        self.snap("", "hot", "2026-08-01", [(1, "", ""), (2, "", "")])
        self.assertEqual(self.board().rows, [])


class TestBoards(Base):
    def test_one_site_two_boards_give_one_seat(self):
        """Книга стоит и в «продажах», и в «библиотеках». Это одна книга
        на одном сайте, а не две."""
        self.snap("qidian", "sales", "2026-08-01", [(9, "Рассвет", "Юй")])
        self.snap("qidian", "library", "2026-08-01", [(2, "Рассвет", "Юй")])
        board = self.board()

        self.assertEqual(len(board.rows), 1)
        self.assertEqual(board.rows[0].sites, 1)
        # Из двух мест остаётся лучшее: «сотая по библиотекам» ничего не
        # добавляет к «второй по продажам».
        self.assertEqual([s.place for s in board.rows[0].seats], [2])

    def test_only_the_freshest_snapshot_of_a_board_is_taken(self):
        self.snap("qidian", "sales", "2026-08-01", [(1, "Старое", "Юй")])
        self.snap("qidian", "sales", "2026-08-05", [(1, "Новое", "Юй")])

        names = [row.name for row in self.board().rows]
        self.assertEqual(names, ["Новое"])

    def test_the_board_says_what_it_was_built_from(self):
        """Срез месячной давности — не «читают сейчас», и молчать об
        этом значило бы соврать датой."""
        self.snap("qidian", "sales", "2026-08-05", [(1, "Рассвет", "Юй")])
        taken = self.board().taken

        self.assertEqual(len(taken), 1)
        self.assertEqual(taken[0]["day"], "2026-08-05")
        self.assertEqual(taken[0]["site_name"], "Цидянь")
        self.assertEqual(taken[0]["rows"], 1)

    def test_the_board_is_named_not_keyed(self):
        """«sales» и «1141» — наши внутренние имена, а не то, что читают."""
        self.snap("qidian", "sales", "2026-08-05", [(1, "Рассвет", "Юй")])
        taken = self.board(boards={"qidian": {"sales": "По продажам"}}).taken
        self.assertEqual(taken[0]["board_name"], "По продажам")

    def test_an_old_snapshot_without_a_board_is_called_by_words(self):
        """Срезы, снятые до появления досок, записаны словом «all»."""
        self.snap("", "all", "2026-08-05", [(1, "Рассвет", "Юй")])
        self.assertEqual(self.board().taken[0]["board_name"], everywhere.WHOLE)


class TestOrder(Base):
    def test_books_seen_on_several_sites_come_first(self):
        """Ради них доска и собирается. Внизу списка их не увидят."""
        self.snap("", "hot", "2026-08-01", [
            (1, "Только тут", "А"), (2, "И там тоже", "Б")])
        self.snap("qidian", "sales", "2026-08-01", [(50, "И там тоже", "Б")])

        self.assertEqual([r.name for r in self.board().rows],
                         ["И там тоже", "Только тут"])

    def test_an_empty_history_is_an_empty_board_not_a_crash(self):
        board = self.board()
        self.assertEqual(board.rows, [])
        self.assertEqual(board.taken, [])
        self.assertEqual(board.as_dict()["total"], 0)


class TestGluingAcrossLanguages(Base):
    """Китайская строка и английская сходятся только через перевод.

    У Цидяня с Фанкью названия китайские, у MVLEMPYR с Webnovel
    английские. По сырым строкам они не совпадут никогда, и доска
    выглядела сломанной, хотя работала как написано.
    """

    def test_two_names_in_different_languages_glue_by_the_translation(self):
        self.snap("", "hot", "2026-08-01", [(1, "斗破苍穹", "")])
        self.snap("mvl", "week", "2026-08-01", [(3, "Battle Through the Heavens", "")])

        board = everywhere.board(names=NAMES, translated={
            "1": "Расколотая битвой синева",
            "3": "Расколотая битвой синева",
        })
        self.assertEqual(board.shared, 1)

    def test_without_the_translation_they_stay_apart(self):
        """Так и было: не поломка, а предел способа."""
        self.snap("", "hot", "2026-08-01", [(1, "斗破苍穹", "")])
        self.snap("mvl", "week", "2026-08-01", [(3, "Battle Through the Heavens", "")])
        self.assertEqual(self.board().shared, 0)

    def test_a_book_without_a_translation_keeps_its_own_name(self):
        """Перевода нет — склеится хотя бы с соседом по языку."""
        self.snap("", "hot", "2026-08-01", [(1, "Shadow Slave", "")])
        self.snap("mvl", "week", "2026-08-01", [(3, "Shadow Slave", "")])
        self.assertEqual(everywhere.board(names=NAMES, translated={}).shared, 1)

    def test_the_key_prefers_the_translation(self):
        from net.sources.rank import RankRow

        row = RankRow(place=1, book_id="7", name="斗破苍穹")
        self.assertEqual(everywhere.key_of(row, {"7": "Синева"}), "синева")
        self.assertEqual(everywhere.key_of(row, {}), "斗破苍穹")


class TestTheBoardExplainsItself(Base):
    """Пустая доска без причины читается как поломка."""

    def test_it_says_when_the_translation_is_what_is_missing(self):
        self.snap("", "hot", "2026-08-01", [(1, "斗破苍穹", "")])
        self.snap("mvl", "week", "2026-08-01", [(3, "Battle Through", "")])
        said = self.board().advice()

        self.assertIn("нет русского названия", said)
        self.assertIn("Перевести всё", said)

    def test_it_says_when_only_one_site_was_taken(self):
        self.snap("", "hot", "2026-08-01", [(1, "Одна", "")])
        self.assertIn("одного сайта", self.board().advice())

    def test_it_says_nothing_when_something_did_glue(self):
        """Совет нужен, только когда пусто: иначе он просто шум."""
        self.snap("", "hot", "2026-08-01", [(1, "Общая", "")])
        self.snap("mvl", "week", "2026-08-01", [(3, "Общая", "")])
        self.assertEqual(self.board().advice(), "")

    def test_each_snapshot_says_how_many_of_its_books_are_translated(self):
        """По этому числу и видно, где нажать «Перевести всё»."""
        self.snap("", "hot", "2026-08-01", [(1, "斗破苍穹", ""), (2, "诡秘", "")])
        board = everywhere.board(names=NAMES, translated={"1": "Синева"})

        self.assertEqual(board.taken[0]["translated"], 1)
        self.assertEqual(board.taken[0]["untranslated"], 1)


if __name__ == "__main__":
    unittest.main()
