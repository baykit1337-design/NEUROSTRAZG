"""Прямая речь в кавычках — прямой речью через тире.

Главное здесь — не переписать побольше, а не тронуть лишнего: кавычка
стоит не только вокруг реплики, и слети она с названия книги, чинить это
пришлось бы вручную по всей книге.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import speech  # noqa: E402


class TestOneLine(unittest.TestCase):
    """Ровно те две строки, с которых всё началось, и их родня."""

    def test_a_whole_line_in_quotes_becomes_a_line_with_a_dash(self):
        self.assertEqual(speech.dashed("«Я-я в порядке...♥»"),
                         "— Я-я в порядке...♥")

    def test_the_dot_outside_the_quote_stays_at_the_end(self):
        """«Быстрее». — точка стояла за кавычкой, и после снятия кавычки
        она оказывается там, где ей и место."""
        self.assertEqual(speech.dashed("«Быстрее»."), "— Быстрее.")

    def test_punctuation_inside_the_quote_survives(self):
        self.assertEqual(speech.dashed("«Быстрее!»"), "— Быстрее!")

    def test_the_authors_words_after_the_reply_stay(self):
        self.assertEqual(speech.dashed("«Что?» — спросил он."),
                         "— Что? — спросил он.")

    def test_the_dash_is_an_em_dash(self):
        """Дефис на этом месте загрузчик покажет дефисом посреди строки."""
        self.assertTrue(speech.dashed("«Да».").startswith("— "))


class TestWhatIsNotAReply(unittest.TestCase):
    """Кавычка стоит не только вокруг реплики."""

    def test_a_title_inside_a_line_is_left_alone(self):
        line = "Он читал «Войну и мир»."
        self.assertEqual(speech.dashed(line), line)

    def test_a_reply_after_the_authors_words_is_left_alone(self):
        """«Он сказал: «Быстрее».» — реплика тут не абзац, а часть
        предложения: тире вместо кавычек сломало бы фразу."""
        line = "Он сказал: «Быстрее»."
        self.assertEqual(speech.dashed(line), line)

    def test_an_unclosed_quote_is_left_alone(self):
        line = "«не закрыта"
        self.assertEqual(speech.dashed(line), line)

    def test_empty_quotes_are_left_alone(self):
        self.assertEqual(speech.dashed("«»"), "«»")

    def test_a_line_already_written_with_a_dash_does_not_change(self):
        line = "— уже через тире"
        self.assertEqual(speech.dashed(line), line)

    def test_a_plain_line_does_not_change(self):
        line = "Обычная строка."
        self.assertEqual(speech.dashed(line), line)

    def test_an_empty_line_does_not_break_anything(self):
        self.assertEqual(speech.dashed(""), "")

    def test_only_the_first_closing_quote_is_taken(self):
        """Снимаем свою кавычку, а не все подряд: то, что в кавычках
        дальше по строке, кавычками и остаётся."""
        self.assertEqual(speech.dashed("«Да», — он кивнул на «Титаник»."),
                         "— Да, — он кивнул на «Титаник».")


class TestOtherQuoteMarks(unittest.TestCase):
    """Ёлочки — главное, но лапки и прямая кавычка попадаются в сливах."""

    def test_curly_quotes_work_the_same(self):
        self.assertEqual(speech.dashed("“Быстрее”."), "— Быстрее.")

    def test_straight_quotes_work_the_same(self):
        """У прямой кавычки открывающая и закрывающая — один знак."""
        self.assertEqual(speech.dashed('"Быстрее".'), "— Быстрее.")


def book():
    """Две главы: в первой речь в кавычках, во второй — уже нет."""
    return [
        ("Глава 1", ["«Я-я в порядке...♥»", "«Быстрее».",
                     "Он читал «Войну и мир»."]),
        ("Глава 2", ["— Уже через тире.", "Обычная строка."]),
    ]


class TestLookingAtTheBook(unittest.TestCase):

    def test_it_counts_only_what_will_change(self):
        found = speech.inspect(book())
        self.assertEqual(found.changed, 2)

    def test_it_counts_every_chapter(self):
        self.assertEqual(speech.inspect(book()).chapters, 2)

    def test_every_change_shows_both_sides(self):
        found = speech.inspect(book())
        self.assertEqual(found.samples[0].before, "«Я-я в порядке...♥»")
        self.assertEqual(found.samples[0].after, "— Я-я в порядке...♥")

    def test_the_change_says_which_chapter_it_is_in(self):
        self.assertEqual(speech.inspect(book()).samples[0].chapter, "Глава 1")

    def test_a_book_without_quoted_speech_is_clean(self):
        found = speech.inspect([("Глава 1", ["— Уже через тире."])])
        self.assertTrue(found.clean)
        self.assertIn("не нашлось", found.summary())

    def test_the_summary_says_how_many(self):
        self.assertIn("2", speech.inspect(book()).summary())

    def test_a_long_book_says_how_many_are_left_unshown(self):
        many = [("Глава 1", [f"«Реплика {n}»." for n in range(speech.SHOW + 5)])]
        said = speech.inspect(many).as_dict()
        self.assertEqual(len(said["samples"]), speech.SHOW)
        self.assertEqual(said["more"], 5)


class TestRewritingTheBook(unittest.TestCase):

    def test_the_replies_come_out_with_a_dash(self):
        made, _ = speech.rewrite(book())
        self.assertEqual(made[0][1][:2], ["— Я-я в порядке...♥", "— Быстрее."])

    def test_what_was_not_a_reply_stays_word_for_word(self):
        made, _ = speech.rewrite(book())
        self.assertEqual(made[0][1][2], "Он читал «Войну и мир».")
        self.assertEqual(made[1][1], ["— Уже через тире.", "Обычная строка."])

    def test_it_says_how_many_it_changed(self):
        _, count = speech.rewrite(book())
        self.assertEqual(count, 2)

    def test_the_chapters_and_their_titles_survive(self):
        made, _ = speech.rewrite(book())
        self.assertEqual([title for title, _ in made], ["Глава 1", "Глава 2"])

    def test_the_source_chapters_are_not_touched(self):
        """Переписанное пишется рядом, а не поверх."""
        was = book()
        speech.rewrite(was)
        self.assertEqual(was[0][1][0], "«Я-я в порядке...♥»")

    def test_looking_and_rewriting_agree(self):
        """Разойдись они, в списке значилось бы одно, а в книгу легло бы
        другое."""
        found = speech.inspect(book())
        _, count = speech.rewrite(book())
        self.assertEqual(found.changed, count)



class TestOverHttp(unittest.TestCase):
    """Карточка «Речь в кавычках» на вкладке «Форматировать»."""

    SOURCE = (
        " # [Глава 1 :|: :|: 1 :|: ]\n"
        "«Я-я в порядке...♥»\n"
        "«Быстрее».\n"
        "Он читал «Войну и мир».\n"
        " # [Глава 2 :|: :|: 1 :|: ]\n"
        "— Уже через тире.\n"
    )

    def setUp(self):
        from tempfile import TemporaryDirectory

        from webapp import app as web

        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        web.app.config["TESTING"] = True
        self.app = web.app.test_client()

    def book(self, text=None):
        path = self.root / "исходник.md"
        path.write_text(self.SOURCE if text is None else text,
                        encoding="utf-8")
        return path

    # Файл создаём только тогда, когда его не передали: иначе вызов
    # затирал бы книгу, которую тест положил специально.
    def look(self, **more):
        targets = more.pop("targets", None) or [str(self.book())]
        payload = {"targets": targets}
        payload.update(more)
        return self.app.post("/api/format/speech", json=payload)

    def apply(self, **more):
        targets = more.pop("targets", None) or [str(self.book())]
        payload = {"targets": targets, "base": str(self.root), "name": "тире"}
        payload.update(more)
        return self.app.post("/api/format/speech/apply", json=payload)

    def test_the_look_says_how_many_replies_there_are(self):
        said = self.look().get_json()
        self.assertEqual(said["changed"], 2)
        self.assertEqual(said["chapters"], 2)

    def test_the_look_shows_both_sides(self):
        said = self.look().get_json()
        self.assertEqual(said["samples"][0]["after"], "— Я-я в порядке...♥")

    def test_a_file_without_headers_is_refused(self):
        path = self.root / "просто.md"
        path.write_text("Просто текст.\n", encoding="utf-8")
        res = self.app.post("/api/format/speech", json={"targets": [str(path)]})
        self.assertEqual(res.status_code, 400)

    def test_the_rewritten_book_is_written(self):
        said = self.apply().get_json()
        self.assertEqual(said["changed"], 2)
        text = (self.root / "тире.md").read_text(encoding="utf-8")
        self.assertIn("— Я-я в порядке...♥", text)
        self.assertIn("— Быстрее.", text)

    def test_what_was_not_a_reply_survives(self):
        self.apply()
        text = (self.root / "тире.md").read_text(encoding="utf-8")
        self.assertIn("Он читал «Войну и мир».", text)

    def test_the_headers_survive_word_for_word(self):
        """Речь правим, а цену и том главы — нет."""
        from ops import mdbook

        self.apply()
        _, chapters = mdbook.read_book(
            (self.root / "тире.md").read_text(encoding="utf-8"))
        self.assertEqual([head.title for head, _ in chapters],
                         ["Глава 1", "Глава 2"])
        self.assertTrue(all(head.paid == "1" for head, _ in chapters))

    def test_the_source_is_left_alone(self):
        path = self.book()
        self.apply()
        self.assertEqual(path.read_text(encoding="utf-8"), self.SOURCE)

    def test_saving_over_the_source_is_refused(self):
        res = self.apply(name="исходник")
        self.assertEqual(res.status_code, 400)

    def test_a_book_without_quoted_speech_is_refused(self):
        """Копия, ничем не отличающаяся от исходника, обещает работу,
        которой не было."""
        quiet = " # [Глава 1 :|: :|: 1 :|: ]\n— Уже через тире.\n"
        res = self.apply(targets=[str(self.book(quiet))])
        self.assertEqual(res.status_code, 400)
        self.assertIn("нечего", res.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
