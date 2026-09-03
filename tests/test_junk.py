"""Мусор в главах готовой книги: повторы, дубли заголовка и артефакты.

Главное здесь — не найти побольше, а не выкинуть нужное: чистка правит
книгу, и лишняя находка стоит дороже пропущенной.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import junk  # noqa: E402


BOOK = "Summoners War: Only I Summoned Divine Beasts"


def chapters(count: int = 12, **extra) -> list:
    """Книга, какой её отдаёт слив: название книги и второй заголовок."""
    made = []
    for number in range(1, count + 1):
        body = [
            BOOK,
            f"Chapter {number}: Panicking Count Ashton",
            f"«Это…» — граф Эштон дрожал, получив донесение, {number}.",
        ]
        body += [line.format(n=number) for line in extra.get("tail", [])]
        made.append((f"Chapter {number}_ Panicking Count Ashton", body))
    return made


def kinds(report) -> dict:
    return {find.kind: find for find in report.finds}


class TestEcho(unittest.TestCase):
    def test_the_heading_repeated_under_itself_is_found(self):
        """Загрузчик прочитает второй заголовок как начало новой главы."""
        found = kinds(junk.inspect(chapters()))["echo"]
        self.assertEqual(found.count, 12)
        self.assertTrue(found.spoils)

    def test_the_same_chapter_written_in_another_language_counts(self):
        """«Глава 10» под «Chapter 10_ Teacher Fern» — та же глава, хотя
        общих букв в них нет."""
        book = [("Chapter 10_ Teacher Fern", ["Глава 10", "Текст главы."])]
        self.assertTrue(junk.echoes("Глава 10", "Chapter 10_ Teacher Fern"))
        self.assertIn("echo", kinds(junk.inspect(book)))

    def test_a_sentence_mentioning_a_chapter_is_not_a_heading(self):
        """«…в главе 12 говорилось» содержит и слово, и число, но это
        текст, и вычеркнуть его из книги нельзя."""
        self.assertFalse(junk.echoes(
            "Как в главе 12 говорилось, дождь шёл всю ночь.",
            "Chapter 12_ Rain"))

    def test_another_chapters_number_is_not_an_echo(self):
        self.assertFalse(junk.echoes("Глава 11", "Chapter 10_ Teacher Fern"))


class TestBookName(unittest.TestCase):
    def test_a_line_standing_in_almost_every_chapter_is_found(self):
        found = kinds(junk.inspect(chapters()))["repeat"]
        self.assertEqual(found.text, BOOK)
        self.assertEqual(found.count, 12)

    def test_two_chapters_are_not_enough_to_call_a_line_a_repeat(self):
        """В одной главе любая строка встречается «во всех ста процентах
        глав», и в находки попал бы текст."""
        self.assertNotIn("repeat", kinds(junk.inspect(chapters(2))))

    def test_a_line_deep_in_the_chapter_is_text_not_a_header(self):
        """Та же строка в середине главы — уже содержание."""
        repeated = "Повторяющаяся строка глубоко в тексте."
        book = []
        for number in range(1, 13):
            # Зона шапки у каждой главы своя, повторяется только строка
            # за её пределами: иначе проверялось бы не то.
            lines = [f"Абзац {k} главы {number}, свой и длинный."
                     for k in range(1, junk.HEAD_LINES + 1)]
            lines.append(repeated)
            book.append((f"Глава {number}", lines))

        self.assertNotIn("repeat", kinds(junk.inspect(book)))
        self.assertNotIn("repeat", kinds(junk.inspect(book)))


class TestArtefacts(unittest.TestCase):
    def test_an_untranslated_paragraph_is_found(self):
        book = chapters(tail=["He simply walked away without a word, {n}."])
        self.assertEqual(kinds(junk.inspect(book))["latin"].count, 12)

    def test_hieroglyphs_are_told_apart_from_latin(self):
        book = chapters(tail=["完全没有翻译的段落 {n}。"])
        found = kinds(junk.inspect(book))
        self.assertEqual(found["cjk"].count, 12)
        self.assertNotIn("完全", found.get("latin", junk.Find("latin")).sample)

    def test_a_russian_line_with_a_foreign_word_is_left_alone(self):
        """Имена и названия пишут латиницей посреди фразы, и звать это
        непереведённым значило бы вычистить полкниги."""
        book = chapters(tail=["Он открыл ноутбук марки Lenovo, глава {n}."])
        self.assertNotIn("latin", kinds(junk.inspect(book)))


class TestNoDoubleCounting(unittest.TestCase):
    def test_a_line_lands_in_exactly_one_finding(self):
        """Название книги по-английски — это название книги, а не ещё и
        непереведённый абзац: одна беда не должна выглядеть двумя."""
        report = junk.inspect(chapters())
        self.assertEqual(sum(f.count for f in report.finds), 24)

    def test_the_summary_separates_the_loader_troubles_from_the_rest(self):
        summary = junk.inspect(chapters(
            tail=["完全没有翻译的段落 {n}。"])).summary()
        self.assertIn("мешает загрузчику", summary)
        self.assertIn("артефактов", summary)


class TestCleaning(unittest.TestCase):
    def test_only_the_marked_findings_go(self):
        book = chapters(tail=["完全没有翻译的段落 {n}。"])
        report = junk.inspect(book)
        only = [f.key for f in report.finds if f.kind == "echo"]

        made, gone = junk.clean(book, only)
        self.assertEqual(gone, 12)
        # Название книги не отмечали — оно на месте.
        self.assertIn(BOOK, made[0][1])

    def test_cleaning_removes_what_the_report_promised(self):
        """Отчёт и чистка разбирают строки одним кодом: разойдись они, и
        человек убрал бы не то, что видел."""
        book = chapters(tail=["完全没有翻译的段落 {n}。"])
        report = junk.inspect(book)
        _, gone = junk.clean(book, [f.key for f in report.finds])
        self.assertEqual(gone, sum(f.count for f in report.finds))

    def test_the_text_of_the_chapter_survives(self):
        book = chapters()
        made, _ = junk.clean(book, [f.key for f in junk.inspect(book).finds])
        self.assertEqual(made[0][1], ["«Это…» — граф Эштон дрожал, получив донесение, 1."])

    def deep_in(self, book, line):
        """Дописывает строку в первую главу за пределами зоны шапки."""
        while len(book[0][1]) < junk.HEAD_LINES:
            book[0][1].append(f"Ещё абзац {len(book[0][1])}, обычный текст.")
        book[0][1].append(line)
        # Именно последнее вхождение: та же строка стоит и в шапке, и
        # проверять надо, что уцелела глубокая, а не она же вверху.
        self.assertGreaterEqual(len(book[0][1]) - 1, junk.HEAD_LINES)
        return line

    def only(self, report, kind):
        """Ключи одной находки: проверяем одно правило, а не все сразу."""
        return [f.key for f in report.finds if f.kind == kind]

    def test_the_book_name_mentioned_mid_chapter_survives(self):
        """Герой может назвать книгу вслух. Шапка — это начало главы, а
        не всякое совпадение с ней по всему тексту."""
        book = chapters()
        deep = self.deep_in(book, BOOK)
        report = junk.inspect(book)

        made, _ = junk.clean(book, self.only(report, "repeat"))
        self.assertIn(deep, made[0][1])

    def test_a_heading_repeated_mid_chapter_survives(self):
        book = chapters()
        deep = self.deep_in(book, "Chapter 1: Panicking Count Ashton")
        report = junk.inspect(book)

        made, _ = junk.clean(book, self.only(report, "echo"))
        self.assertIn(deep, made[0][1])

    def test_the_source_chapters_are_not_touched(self):
        book = chapters()
        before = [list(lines) for _, lines in book]
        junk.clean(book, [f.key for f in junk.inspect(book).finds])
        self.assertEqual([lines for _, lines in book], before)

    def test_every_kind_has_a_name_for_the_page(self):
        book = chapters(tail=["完全没有翻译的段落 {n}。", "Just English, {n}."])
        for find in junk.inspect(book).finds:
            with self.subTest(find.kind):
                self.assertIn(find.kind, junk.KINDS)
                self.assertTrue(find.as_dict()["kind_name"])


if __name__ == "__main__":
    unittest.main()


class TestEveryFindShowsItsLines(unittest.TestCase):
    """Находка показывает все свои строки, а не одну.

    «Не переведено» собирает под собой все английские строки книги разом.
    По одному примеру не понять ни что там осталось, ни стоит ли это
    убирать: человек видел «[B]» и не видел ещё сорока строк, которые
    уйдут вместе с ней.
    """

    def finds(self, chapters):
        return {find.kind: find.as_dict()
                for find in junk.inspect(chapters).finds}

    def test_all_the_different_lines_are_shown(self):
        found = self.finds([
            ("Глава 1", ["Русский текст.", "Hello there"]),
            ("Глава 2", ["Русский.", "Another line", "[B]"]),
        ])["latin"]
        self.assertEqual([spot["text"] for spot in found["spots"]],
                         ["Hello there", "Another line", "[B]"])

    def test_each_line_says_where_it_came_from(self):
        found = self.finds([
            ("Глава 1", ["Текст.", "Hello"]),
            ("Глава 2", ["Текст.", "Goodbye"]),
        ])["latin"]
        self.assertEqual([spot["where"] for spot in found["spots"]],
                         ["Глава 1", "Глава 2"])

    def test_one_line_repeated_is_one_example(self):
        """Строка, стоящая в трёхстах главах, — одна находка с числом
        триста, а не триста примеров одного и того же."""
        # Строку кладём вне зоны шапки: там повтор в каждой главе — это
        # название книги, и находка была бы другая.
        body = ["Абзац первый.", "Абзац второй.", "Абзац третий.",
                "Абзац четвёртый.", "Абзац пятый.", "Read on site"]
        found = self.finds([("Глава %d" % n, list(body))
                            for n in range(1, 6)])["latin"]
        self.assertEqual(len(found["spots"]), 1)
        self.assertEqual(found["count"], 5)

    def test_the_list_does_not_grow_without_end(self):
        found = self.finds([
            ("Глава 1", ["Текст."] + [f"English line {n}"
                                      for n in range(junk.SHOW + 10)]),
        ])["latin"]
        self.assertLessEqual(len(found["spots"]), junk.SHOW)


class TestCommentsFromTheSite(unittest.TestCase):
    """Комментарии со страницы, утащенные вместе с главой.

    Слив Новелпии кладёт их в конец каждой главы: ник, время, ник, время.
    Ник — это любые буквы и цифры, и отличить его от строки текста нечем;
    опознаём по времени, а ник берём тот, что стоит прямо над ним.

    Главное здесь то же, что и во всём этом файле: не найти побольше, а не
    выкинуть нужное.
    """

    TEXT = ["Я продолжаю говорить, не в силах стереть улыбку.",
            "Несмотря на всё это.",
            "— Может, пойдём по домам?"]

    TAIL = ["LoftySite5764.", "9 декабря 2025 года, 12:08.",
            "BasicDoor109.", "9 декабря 2025 года, 14:53.",
            "Killusion.", "11 декабря 2025 года, 04:57."]

    def finds(self, chapters):
        return {find.kind: find.as_dict()
                for find in junk.inspect(chapters).finds}

    def test_the_whole_tail_is_found(self):
        found = self.finds([("Глава 567", self.TEXT + self.TAIL)])["comment"]
        self.assertEqual(found["count"], len(self.TAIL))

    def test_the_text_of_the_chapter_stays(self):
        made, gone = junk.clean(
            [("Глава 567", self.TEXT + self.TAIL)], ["comment"])
        self.assertEqual(made[0][1], self.TEXT)
        self.assertEqual(gone, len(self.TAIL))

    def test_a_russian_nick_with_digits_is_a_nick_too(self):
        tail = ["Тёмный Странник77.", "30 апреля 2026 года, 09:20."]
        made, _ = junk.clean([("Глава 1", ["Текст."] + tail)], ["comment"])
        self.assertEqual(made[0][1], ["Текст."])

    def test_a_time_without_a_nick_above_it_goes_alone(self):
        """Над временем стоит другое время — значит, подписи не было."""
        body = ["Текст.", "9 декабря 2025 года, 12:08.",
                "9 декабря 2025 года, 14:53."]
        made, gone = junk.clean([("Глава 1", body)], ["comment"])
        self.assertEqual(made[0][1], ["Текст."])
        self.assertEqual(gone, 2)

    def test_a_sentence_above_the_time_is_not_a_nick(self):
        """Иначе из главы уедет последняя строка текста."""
        body = ["Он ушёл, не сказав ни слова.", "9 декабря 2025 года, 12:08."]
        made, gone = junk.clean([("Глава 1", body)], ["comment"])
        self.assertEqual(made[0][1], ["Он ушёл, не сказав ни слова."])
        self.assertEqual(gone, 1)

    def test_a_line_of_speech_is_never_a_nick(self):
        body = ["— Госпожа Эйлин.", "9 декабря 2025 года, 12:08."]
        made, _ = junk.clean([("Глава 1", body)], ["comment"])
        self.assertEqual(made[0][1], ["— Госпожа Эйлин."])

    def test_a_date_inside_a_sentence_is_left_alone(self):
        """Время прозой не бывает, а вот дата — сколько угодно."""
        body = ["Это случилось 9 декабря 2025 года, и никто не понял.",
                "Он ушёл."]
        made, gone = junk.clean([("Глава 1", list(body))], ["comment"])
        self.assertEqual(made[0][1], body)
        self.assertEqual(gone, 0)

    def test_a_book_without_comments_is_not_accused(self):
        self.assertNotIn("comment", self.finds([("Глава 1", self.TEXT)]))

    def test_nothing_goes_until_it_is_ticked(self):
        """Находка не из тех, что мешают загрузчику: галочка сама не
        встаёт, и человек сначала смотрит список."""
        found = self.finds([("Глава 1", self.TEXT + self.TAIL)])["comment"]
        self.assertFalse(found["spoils"])

        made, gone = junk.clean([("Глава 1", self.TEXT + self.TAIL)], [])
        self.assertEqual(made[0][1], self.TEXT + self.TAIL)
        self.assertEqual(gone, 0)

    def test_the_lines_are_shown_before_they_go(self):
        """«Может, где-то удалять не надо» — на это и смотрят."""
        found = self.finds([("Глава 567", self.TEXT + self.TAIL)])["comment"]
        self.assertEqual([spot["text"] for spot in found["spots"]], self.TAIL)

    def test_a_nick_in_latin_does_not_go_to_untranslated(self):
        """Иначе подпись уехала бы в «не переведено», а время — в шапку
        следующей главы."""
        found = self.finds([("Глава 567", self.TEXT + self.TAIL)])
        self.assertNotIn("latin", found)

    def test_a_one_word_line_above_a_lone_comment_is_a_known_limit(self):
        """Строка «Тишина.» и ник «Killusion.» устроены одинаково: одно
        слово с точкой. Под одиноким комментарием отличить их нечем — и
        именно поэтому находка показывается, а галочка сама не встаёт.

        Проверка стоит здесь нарочно: предел известен, и молчать о нём
        хуже, чем назвать.
        """
        body = ["Тишина.", "9 декабря 2025 года, 12:08."]
        made, _ = junk.clean([("Глава 1", body)], ["comment"])
        self.assertEqual(made[0][1], [])

    def test_the_tail_is_read_from_the_end_and_stops_at_the_break(self):
        """Сломалась пара — выше не смотрим: там уже текст главы.

        Время при этом уходит и из разорванной пары: временем строка быть
        не перестала, а вот подписью над ним объявлять текст главы
        нельзя.
        """
        body = ["Он ушёл, не сказав ни слова.", "9 декабря 2025 года, 12:08.",
                "Ник1.", "9 декабря 2025 года, 14:53."]
        made, gone = junk.clean([("Глава 1", list(body))], ["comment"])
        self.assertEqual(made[0][1], ["Он ушёл, не сказав ни слова."])
        self.assertEqual(gone, 3)

    def test_a_short_line_with_a_comma_is_not_a_nick(self):
        """В нике знаков препинания нет: «Тишина, наконец.» — это текст,
        хотя слов в нём и мало."""
        body = ["Тишина, наконец.", "9 декабря 2025 года, 12:08."]
        made, gone = junk.clean([("Глава 1", list(body))], ["comment"])
        self.assertEqual(made[0][1], ["Тишина, наконец."])
        self.assertEqual(gone, 1)

    def test_a_date_without_a_time_is_just_a_date(self):
        """Комментарий узнаём по часам с минутами. Без них строка,
        начатая датой, — обычное предложение."""
        body = ["9 декабря 2025 года, но это было уже потом.", "Он ушёл."]
        made, gone = junk.clean([("Глава 1", list(body))], ["comment"])
        self.assertEqual(made[0][1], body)
        self.assertEqual(gone, 0)

    def test_a_long_line_without_punctuation_is_not_a_nick_either(self):
        """Ник — это несколько слов, а не предложение. Знаков препинания
        внутри может не быть вовсе, и длина остаётся единственным, чем
        одно отличается от другого."""
        body = ["Он ушёл прочь и не оглянулся.", "9 декабря 2025 года, 12:08."]
        made, gone = junk.clean([("Глава 1", list(body))], ["comment"])
        self.assertEqual(made[0][1], ["Он ушёл прочь и не оглянулся."])
        self.assertEqual(gone, 1)
