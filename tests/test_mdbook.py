"""Формат загрузчика: книга одним .md с заголовками в скобках.

Главное, что здесь проверяется, — что правится только название. В
остальных полях заголовка у сайта лежат цена главы и том; «причесать» их
значило бы поменять книге цену, а заметить это можно уже только на
сайте.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Chapter  # noqa: E402
from ops import mdbook  # noqa: E402

#: Заголовок ровно в том виде, в каком его отдаёт переводчик.
REAL = "# [Chapter 1168_ Trade :|: :|: 1 :|: ]"


class TestReadingAHeader(unittest.TestCase):

    def test_a_real_header_comes_apart(self):
        head = mdbook.parse_head(REAL)
        self.assertEqual(head.title, "Chapter 1168_ Trade")
        self.assertEqual(head.order, "")
        self.assertEqual(head.paid, "1")
        self.assertEqual(head.volume, "")

    def test_a_header_without_fields_is_still_a_header(self):
        head = mdbook.parse_head("# [Пролог]")
        self.assertEqual(head.title, "Пролог")
        self.assertEqual(head.fields, [])

    def test_an_ordinary_line_is_not_a_header(self):
        self.assertIsNone(mdbook.parse_head("Обычная строка"))
        self.assertIsNone(mdbook.parse_head("# Обычный заголовок"))

    def test_spaces_around_the_hash_do_not_matter(self):
        """Переводчик ставит их как придётся."""
        self.assertIsNotNone(mdbook.parse_head("  #  [Глава 1 :|: 1] "))

    def test_the_order_is_read_when_it_is_there(self):
        head = mdbook.parse_head("# [Глава 5 :|: 270 :|: 0 :|: Том 2]")
        self.assertEqual((head.order, head.paid, head.volume),
                         ("270", "0", "Том 2"))


class TestNothingButTheTitleChanges(unittest.TestCase):
    """Ради этого модуль и хранит строку кусками, а не полями."""

    def test_a_header_survives_reading_and_writing(self):
        self.assertEqual(mdbook.parse_head(REAL).line(), REAL)

    def test_a_new_title_keeps_the_price(self):
        head = mdbook.parse_head(REAL).with_title("Глава 1168 — Торговля")
        self.assertEqual(head.line(),
                         "# [Глава 1168 — Торговля :|: :|: 1 :|: ]")

    def test_an_indented_header_keeps_its_indent(self):
        """У переводчика вторая строка вышла с пробелом в начале —
        собери мы её без него, файл поменялся бы не только названием."""
        line = " # [Chapter 1171_ Unexpected Summoning Result :|: :|: 1 :|: ]"
        self.assertEqual(mdbook.parse_head(line).line(), line)

    def test_an_indented_header_can_be_retitled_too(self):
        line = " # [Chapter 1171_ Result :|: :|: 1 :|: ]"
        head = mdbook.parse_head(line).with_title("Глава 1171 — Результат")
        self.assertTrue(head.line().startswith(" # ["))
        self.assertTrue(head.line().endswith(":|: ]"))

    def test_the_empty_volume_keeps_its_space(self):
        """Пробел в томе — не мусор: без него у сайта съедет поле."""
        head = mdbook.parse_head(REAL).with_title("Другое")
        self.assertTrue(head.line().endswith(":|: ]"))

    def test_a_whole_book_survives_reading_and_writing(self):
        text = (f"мусор до первой главы\n\n{REAL}\n\nПервый абзац.\n\n"
                "# [Chapter 1169_ Shocked :|: :|: 1 :|: ]\n\nВторой абзац.\n")
        lead, chapters = mdbook.read_book(text)
        self.assertEqual(mdbook.write_book(chapters, lead), text)

    def test_what_stands_before_the_first_header_is_kept(self):
        """Сайт эту часть выбрасывает, но человек мог писать её себе."""
        lead, _ = mdbook.read_book(f"моя заметка\n{REAL}\nтекст\n")
        self.assertEqual(lead, "моя заметка")

    def test_the_body_of_a_chapter_is_kept_line_by_line(self):
        _, chapters = mdbook.read_book(f"{REAL}\nодин\n\nдва\n")
        self.assertEqual(chapters[0][1], ["один", "", "два"])


class TestWritingAHeaderFromScratch(unittest.TestCase):

    def test_a_bare_title_needs_no_separators(self):
        self.assertEqual(mdbook.make_head("Пролог").line(), "# [Пролог]")

    def test_the_order_alone_takes_one_field(self):
        self.assertEqual(mdbook.make_head("Глава 1", order="1").line(),
                         "# [Глава 1 :|: 1]")

    def test_a_volume_forces_the_price_field(self):
        """Иначе сайт прочитает том как платность."""
        line = mdbook.make_head("Глава 1", order="1", volume="Том 2").line()
        self.assertEqual(line.count(mdbook.MARK), 3)

    def test_the_separator_cannot_get_into_a_title(self):
        """`:|:` внутри названия развалил бы разбор на сайте."""
        line = mdbook.make_head(f"До {mdbook.MARK} после").line()
        self.assertEqual(line.count(mdbook.MARK), 0)

    def test_what_was_written_is_read_back_the_same(self):
        head = mdbook.make_head("Глава 7", order="7", paid="1", volume="Том 1")
        again = mdbook.parse_head(head.line())
        self.assertEqual((again.title, again.order, again.paid, again.volume),
                         ("Глава 7", "7", "1", "Том 1"))


class TestTakingTheTitleApart(unittest.TestCase):

    def test_the_english_heading_gives_a_number_and_a_name(self):
        self.assertEqual(mdbook.split_title("Chapter 1169_ Shocked Emperor"),
                         (1169, "Shocked Emperor"))

    def test_a_heading_without_a_number_keeps_its_name(self):
        self.assertEqual(mdbook.split_title("Пролог"), (None, "Пролог"))

    def test_the_russian_heading_works_too(self):
        self.assertEqual(mdbook.split_title("Глава 101 - Название"),
                         (101, "Название"))

    def test_a_translated_title_is_told_from_an_untranslated_one(self):
        self.assertTrue(mdbook.looks_translated("Глава 1 — Торговля"))
        self.assertFalse(mdbook.looks_translated("Chapter 1_ Trade"))


class TestStrippingTheChaptersOwnNumber(unittest.TestCase):
    """Читалка отдаёт названием имя файла целиком — вместе с «Глава 101 -».

    Резать по первому числу, как это делает разбор имён файлов, здесь
    нельзя: у «Название 1» число — часть имени.
    """

    def test_the_chapter_mark_is_cut_off(self):
        self.assertEqual(mdbook.bare_name("Глава 101 - Название 101", 101),
                         "Название 101")

    def test_a_name_that_merely_ends_in_a_digit_survives(self):
        self.assertEqual(mdbook.bare_name("Название 1", 1), "Название 1")

    def test_a_name_that_starts_with_a_word_survives(self):
        self.assertEqual(mdbook.bare_name("Название 101", 101),
                         "Название 101")

    def test_a_bare_mark_leaves_nothing_and_that_is_right(self):
        """«Глава 101» — это номер, а не имя: иначе номер встанет дважды."""
        self.assertEqual(mdbook.bare_name("Глава 101", 101), "")

    def test_a_bare_number_prefix_is_cut_off_too(self):
        self.assertEqual(mdbook.bare_name("101 - Название", 101), "Название")

    def test_someone_elses_number_is_not_touched(self):
        """Номер в начале не тот — значит, это часть названия."""
        self.assertEqual(mdbook.bare_name("Глава 7 - Название", 9),
                         "Глава 7 - Название")

    def test_a_name_without_a_number_is_left_alone(self):
        self.assertEqual(mdbook.bare_name("Пролог"), "Пролог")

    def test_a_number_inside_the_name_survives(self):
        self.assertEqual(mdbook.bare_name("Глава 5. 100 дней", 5), "100 дней")


class TestBuildingTheTitle(unittest.TestCase):

    def test_number_and_name_come_together(self):
        style = mdbook.TitleStyle(prefix="Глава", separator=" — ")
        self.assertEqual(style.build(1171, "Результат"),
                         "Глава 1171 — Результат")

    def test_a_part_goes_after_the_number(self):
        style = mdbook.TitleStyle(prefix="Глава", separator=" — ")
        self.assertEqual(style.build(1171, "Результат", part=2),
                         "Глава 1171.2 — Результат")

    def test_without_a_number_there_is_no_word_chapter(self):
        """«Глава — Пролог» было бы неправдой."""
        style = mdbook.TitleStyle()
        self.assertEqual(style.build(None, "Пролог"), "Пролог")

    def test_without_a_name_there_is_no_dangling_separator(self):
        style = mdbook.TitleStyle(prefix="Глава", separator=" — ")
        self.assertEqual(style.build(5), "Глава 5")


class TestCuttingAChapterIntoParts(unittest.TestCase):

    def book(self, blocks=8):
        body = mdbook.lines_of([f"Абзац номер {n} с текстом." * 3
                                for n in range(blocks)])
        return mdbook.parse_head(REAL), body

    def test_two_parts_come_out_of_one_chapter(self):
        head, body = self.book()
        out = mdbook.cut_into_parts(head, body, 2)
        self.assertEqual(len(out), 2)

    def test_the_parts_are_numbered_in_the_title(self):
        head, body = self.book()
        out = mdbook.cut_into_parts(head, body, 2)
        self.assertIn("1168.1", out[0][0].title)
        self.assertIn("1168.2", out[1][0].title)

    def test_the_price_travels_to_every_part(self):
        """Половина главы не должна вдруг стать бесплатной."""
        head, body = self.book()
        for spare, _ in mdbook.cut_into_parts(head, body, 3):
            self.assertEqual(spare.paid, "1")

    def test_the_text_is_not_lost_and_not_doubled(self):
        head, body = self.book()
        out = mdbook.cut_into_parts(head, body, 3)
        was = mdbook.paragraphs_of(body)
        now = [p for _, piece in out for p in mdbook.paragraphs_of(piece)]
        self.assertEqual(now, was)

    def test_one_part_leaves_the_chapter_alone(self):
        head, body = self.book()
        self.assertEqual(mdbook.cut_into_parts(head, body, 1), [(head, body)])

    def test_a_chapter_too_short_to_cut_is_left_alone(self):
        head, _ = self.book()
        body = mdbook.lines_of(["Один абзац."])
        self.assertEqual(len(mdbook.cut_into_parts(head, body, 4)), 1)


class TestCollectingFilesIntoABook(unittest.TestCase):

    def chapters(self, count=3):
        return [Chapter(number=n, title=f"Название {n}",
                        paragraphs=[f"Текст главы {n}."])
                for n in range(1, count + 1)]

    def test_every_chapter_gets_a_header(self):
        out = mdbook.from_chapters(self.chapters())
        self.assertEqual(len(out), 3)
        for head, _ in out:
            self.assertTrue(head.line().startswith("# ["))

    def test_the_word_chapter_does_not_end_up_twice(self):
        """Читалка отдаёт названием имя файла целиком — вместе с «Глава
        101 - ». Возьми его как есть, и выйдет «Глава 101 — Глава 101 -
        Название»."""
        out = mdbook.from_chapters(
            [Chapter(number=101, title="Глава 101 - Название 101",
                     paragraphs=["Текст."])])
        self.assertEqual(out[0][0].title, "Глава 101 — Название 101")

    def test_a_number_only_name_leaves_no_dangling_separator(self):
        out = mdbook.from_chapters(
            [Chapter(number=101, title="Глава 101", paragraphs=["Текст."])])
        self.assertEqual(out[0][0].title, "Глава 101")

    def test_a_chapter_without_a_number_keeps_its_name(self):
        out = mdbook.from_chapters(
            [Chapter(title="Пролог", paragraphs=["Текст."])])
        self.assertEqual(out[0][0].title, "Пролог")

    def test_the_numbering_starts_where_asked(self):
        out = mdbook.from_chapters(self.chapters(), first=270)
        self.assertEqual([head.order for head, _ in out], ["270", "271", "272"])

    def test_without_a_starting_number_the_order_is_left_to_the_site(self):
        """Выдуманные числа хуже пустого поля: сайт нумерует сам."""
        out = mdbook.from_chapters(self.chapters(), first=0)
        self.assertEqual([head.order for head, _ in out], ["", "", ""])

    def test_the_price_reaches_every_chapter(self):
        out = mdbook.from_chapters(self.chapters(), paid=mdbook.PAID)
        self.assertTrue(all(head.paid == "1" for head, _ in out))

    def test_the_book_reads_back_as_a_book(self):
        text = mdbook.write_book(mdbook.from_chapters(self.chapters()))
        _, again = mdbook.read_book(text)
        self.assertEqual(len(again), 3)
        self.assertEqual(again[0][0].title, "Глава 1 — Название 1")

    def test_the_text_of_a_chapter_survives_the_trip(self):
        text = mdbook.write_book(mdbook.from_chapters(self.chapters()))
        _, again = mdbook.read_book(text)
        self.assertIn("Текст главы 1.", "\n".join(again[0][1]))

    def test_parts_shift_the_numbering_of_what_follows(self):
        """Разбили первую надвое — вторая уходит на номер дальше."""
        chapters = [Chapter(number=1, title="Первая",
                            paragraphs=[f"Абзац {n}." * 5 for n in range(6)]),
                    Chapter(number=2, title="Вторая", paragraphs=["Текст."])]
        out = mdbook.from_chapters(chapters, first=1, parts=2)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[-1][0].order, "3")


class FakeLlm:
    """Модель, переводящая всё, о чём спросили, по номерам строк."""

    def __init__(self, prefix="ПЕРЕВОД "):
        self.prefix = prefix
        self.asked = []

    def generate(self, prompt, json_only=True, model="", schema=None):
        import json
        import re

        self.asked.append(prompt)
        return json.dumps(
            {n: self.prefix + t
             for n, t in re.findall(r"^(\d+)\. (.+)$", prompt, re.M)},
            ensure_ascii=False)

    def close(self):
        pass


class WebBase(unittest.TestCase):

    def setUp(self):
        from tempfile import TemporaryDirectory

        from ops import titles
        from webapp import app as web

        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

        kept = titles.HEADINGS_FILE
        titles.HEADINGS_FILE = self.root / "headings.json"
        self.addCleanup(setattr, titles, "HEADINGS_FILE", kept)

        self.llm = FakeLlm()
        was = web._llm_client
        web._llm_client = lambda *a, **kw: self.llm
        self.addCleanup(setattr, web, "_llm_client", was)

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()
        self.web = web

    def finish(self, res):
        self.assertEqual(res.status_code, 200, res.get_json())
        job_id = res.get_json()["job"]["id"]
        self.web.JOBS[job_id].thread.join(timeout=60)
        return self.web.JOBS[job_id]


class TestCollectingOverHttp(WebBase):

    def chapters(self, count=3):
        folder = self.root / "главы"
        folder.mkdir(exist_ok=True)
        for n in range(1, count + 1):
            (folder / f"Глава {n} - Название {n}.txt").write_text(
                f"Текст главы {n}.", encoding="utf-8")
        return folder

    def test_the_scan_tells_what_will_come_out(self):
        folder = self.chapters()
        said = self.app.post("/api/format/files",
                             json={"targets": [str(folder)]}).get_json()
        self.assertEqual(said["total"], 3)
        self.assertTrue(said["sample"][0].startswith("# ["))

    def test_the_book_is_written(self):
        folder = self.chapters()
        job = self.finish(self.app.post("/api/format/collect", json={
            "targets": [str(folder)], "base": str(self.root), "name": "книга"}))
        self.assertIsNone(job.error)
        text = (self.root / "книга.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("# ["), 3)
        self.assertIn("Текст главы 1.", text)

    def test_the_numbering_starts_where_asked(self):
        folder = self.chapters()
        self.finish(self.app.post("/api/format/collect", json={
            "targets": [str(folder)], "base": str(self.root),
            "name": "книга", "first": 270}))
        _, chapters = mdbook.read_book(
            (self.root / "книга.md").read_text(encoding="utf-8"))
        self.assertEqual(chapters[0][0].order, "270")

    def test_the_price_reaches_the_headers(self):
        folder = self.chapters()
        self.finish(self.app.post("/api/format/collect", json={
            "targets": [str(folder)], "base": str(self.root),
            "name": "книга", "paid": "1", "first": 1}))
        _, chapters = mdbook.read_book(
            (self.root / "книга.md").read_text(encoding="utf-8"))
        self.assertTrue(all(head.paid == "1" for head, _ in chapters))

    def test_nowhere_to_save_is_refused(self):
        folder = self.chapters()
        res = self.app.post("/api/format/collect",
                            json={"targets": [str(folder)], "name": "книга"})
        self.assertEqual(res.status_code, 400)


class TestRetitlingOverHttp(WebBase):

    #: Ровно то, что отдаёт переводчик, — со вторым заголовком с отступа.
    SOURCE = (
        "# [Chapter 1168_ Trade :|: :|: 1 :|: ]\n"
        "\n"
        "Первый абзац главы.\n"
        "\n"
        " # [Chapter 1169_ Shocked Emperor :|: :|: 1 :|: ]\n"
        "\n"
        "Второй абзац главы.\n"
    )

    def book(self, text=None):
        path = self.root / "исходник.md"
        path.write_text(text if text is not None else self.SOURCE,
                        encoding="utf-8")
        return path

    def test_the_scan_counts_what_is_not_translated(self):
        said = self.app.post("/api/format/book",
                             json={"targets": [str(self.book())]}).get_json()
        self.assertEqual(said["total"], 2)
        self.assertEqual(said["untranslated"], 2)

    def test_a_file_without_headers_is_refused(self):
        path = self.root / "просто.md"
        path.write_text("Просто текст без заголовков.\n", encoding="utf-8")
        res = self.app.post("/api/format/book", json={"targets": [str(path)]})
        self.assertEqual(res.status_code, 400)

    def retitled(self, **more):
        # Файл создаём только тогда, когда его не передали: иначе вызов
        # затирал бы книгу, которую тест положил специально.
        targets = more.pop("targets", None) or [str(self.book())]
        payload = {"targets": targets, "base": str(self.root),
                   "name": "готово"}
        payload.update(more)
        job = self.finish(self.app.post("/api/format/retitle", json=payload))
        self.assertIsNone(job.error)
        return (self.root / "готово.md").read_text(encoding="utf-8")

    def test_the_headings_become_russian(self):
        text = self.retitled()
        self.assertIn("Глава 1168", text)
        self.assertIn("ПЕРЕВОД Trade", text)

    def test_the_number_of_the_chapter_survives(self):
        """Номер не отдаём модели вовсе — правит она только имя."""
        text = self.retitled()
        self.assertIn("Глава 1169", text)

    def test_the_price_of_every_chapter_survives(self):
        """Вот ради чего всё: заголовок несёт цену главы."""
        _, chapters = mdbook.read_book(self.retitled())
        self.assertTrue(all(head.paid == "1" for head, _ in chapters))

    def test_the_empty_volume_field_survives(self):
        _, chapters = mdbook.read_book(self.retitled())
        self.assertTrue(all(head.line().endswith(":|: ]")
                            for head, _ in chapters))

    def test_the_body_is_not_touched(self):
        text = self.retitled()
        self.assertIn("Первый абзац главы.", text)
        self.assertIn("Второй абзац главы.", text)

    def test_the_source_is_left_alone(self):
        """Перезапиши мы исходник — сверить перевод было бы не с чем."""
        path = self.book()
        self.retitled()
        self.assertEqual(path.read_text(encoding="utf-8"), self.SOURCE)

    def test_saving_over_the_source_is_refused(self):
        path = self.book()
        res = self.app.post("/api/format/retitle", json={
            "targets": [str(path)], "base": str(self.root),
            "name": "исходник"})
        self.assertEqual(res.status_code, 400)

    def test_an_untranslated_heading_keeps_its_old_name(self):
        """Пустой заголовок хуже английского: главу станет не найти."""
        self.llm.generate = lambda *a, **kw: "мусор"
        text = self.retitled()
        self.assertIn("Trade", text)

    def test_the_number_of_chapters_does_not_change(self):
        _, was = mdbook.read_book(self.SOURCE)
        _, now = mdbook.read_book(self.retitled())
        self.assertEqual(len(now), len(was))

    def test_parts_split_the_body_too(self):
        long = ("# [Chapter 5_ Long :|: :|: 1 :|: ]\n\n"
                + "\n\n".join(f"Абзац номер {n} с текстом." * 4
                              for n in range(8)) + "\n")
        text = self.retitled(targets=[str(self.book(long))], parts=2)
        _, chapters = mdbook.read_book(text)
        self.assertEqual(len(chapters), 2)
        self.assertIn("5.1", chapters[0][0].title)
        self.assertIn("5.2", chapters[1][0].title)

    def test_the_run_says_how_it_went(self):
        job = self.finish(self.app.post("/api/format/retitle", json={
            "targets": [str(self.book())], "base": str(self.root),
            "name": "готово"}))
        self.assertEqual(job.report["total"], 2)
        self.assertEqual(job.report["translated"], 2)


if __name__ == "__main__":
    unittest.main()


class TestLookingAtTheNumbering(unittest.TestCase):
    """Загрузчик сортирует главы по полю «Порядок», а человек читает
    номер в названии — расходятся они молча, и заметить это можно только
    до отправки на сайт."""

    def book(self, *lines):
        text = "".join(f"{line}\nтекст главы\n\n" for line in lines)
        return mdbook.inspect(mdbook.read_book(text)[1])

    def test_a_tidy_book_is_called_tidy(self):
        look = self.book("# [Глава 1 — А :|: 1]", "# [Глава 2 — Б :|: 2]")
        self.assertTrue(look["ok"])
        self.assertEqual(look["total"], 2)
        self.assertEqual((look["first"], look["last"]), (1, 2))

    def test_a_missing_number_is_found(self):
        """Эта глава потерялась по дороге."""
        look = self.book("# [Глава 1 — А]", "# [Глава 3 — В]")
        self.assertEqual(look["gaps"], ["2"])
        self.assertFalse(look["ok"])

    def test_a_run_of_missing_numbers_is_one_line(self):
        """Полторы тысячи глав дадут при разнобое список во весь экран."""
        look = self.book("# [Глава 1 — А]", "# [Глава 6 — Е]")
        self.assertEqual(look["gaps"], ["2–5"])

    def test_nothing_is_missing_before_the_first_chapter(self):
        """Книга может начинаться с 1168-й — это не пропуск."""
        look = self.book("# [Глава 1168 — А]", "# [Глава 1169 — Б]")
        self.assertEqual(look["gaps"], [])

    def test_a_doubled_number_is_found(self):
        """Такая глава уедет на сайт двумя."""
        look = self.book("# [Глава 5 — А]", "# [Глава 5 — Б]")
        self.assertEqual(look["doubles"], ["5"])

    def test_a_number_going_backwards_is_found(self):
        look = self.book("# [Глава 7 — А]", "# [Глава 3 — Б]")
        self.assertEqual(look["backwards"], ["7 → 3"])

    def test_a_doubled_order_field_is_found(self):
        """Сайт сортирует именно по нему."""
        look = self.book("# [Глава 1 — А :|: 4]", "# [Глава 2 — Б :|: 4]")
        self.assertEqual(look["order_doubles"], ["4"])
        self.assertFalse(look["ok"])

    def test_a_chapter_without_a_number_is_counted_apart(self):
        look = self.book("# [Пролог]", "# [Глава 1 — А]")
        self.assertEqual(look["nameless_count"], 1)
        self.assertEqual(look["numbered"], 1)

    def test_a_prologue_alone_is_not_a_disorder(self):
        """Без номера — не значит с ошибкой: сайт назначит порядок сам."""
        self.assertTrue(self.book("# [Пролог]")["ok"])

    def test_untranslated_headings_are_counted(self):
        look = self.book("# [Chapter 1_ A]", "# [Глава 2 — Б]")
        self.assertEqual(look["untranslated"], 1)

    def test_the_findings_do_not_flood_the_screen(self):
        lines = [f"# [Глава {n} — А]" for n in range(1, 200, 2)]
        look = self.book(*lines)
        self.assertLessEqual(len(look["gaps"]), mdbook.SHOW)
        self.assertGreater(look["gaps_count"], mdbook.SHOW)

    def test_an_empty_book_does_not_crash_the_check(self):
        look = mdbook.inspect([])
        self.assertEqual(look["total"], 0)
        self.assertIsNone(look["first"])
        self.assertTrue(look["ok"])


class TestWatchingTheTranslation(WebBase):
    """Полторы тысячи заголовков — это минуты, и всё это время экран
    должен отвечать на два вопроса: что происходит и хватит ли ключей."""

    SOURCE = "# [Chapter 1_ Trade :|: :|: 1 :|: ]\n\nТекст.\n"

    def run_it(self):
        path = self.root / "исходник.md"
        path.write_text(self.SOURCE, encoding="utf-8")
        return self.finish(self.app.post("/api/format/retitle", json={
            "targets": [str(path)], "base": str(self.root), "name": "готово"}))

    def test_the_translation_keeps_a_log(self):
        job = self.run_it()
        self.assertIsNotNone(job.log)
        self.assertTrue(job.log.lines())

    def test_the_log_is_readable_over_http(self):
        job = self.run_it()
        said = self.app.get(f"/api/job/{job.id}/log").get_json()
        self.assertTrue(said["lines"])

    def test_the_log_can_be_saved_to_a_file(self):
        job = self.run_it()
        got = self.app.get(f"/api/job/{job.id}/log.txt")
        self.assertEqual(got.status_code, 200)

    def test_the_keys_are_counted_beside_the_progress(self):
        """«Десять ключей» ничего не говорит, если девять уже отдали
        квоту."""
        job = self.run_it()
        self.assertIn("keys", job.progress)
        self.assertIn("active", job.progress["keys"])
        self.assertIn("exhausted", job.progress["keys"])

    def test_the_report_says_how_the_keys_ended_up(self):
        self.assertIn("keys", self.run_it().report)

    def test_collecting_keeps_no_log_because_it_asks_nobody(self):
        """Пустая раскрывашка обещала бы то, чего нет."""
        folder = self.root / "главы"
        folder.mkdir(exist_ok=True)
        (folder / "Глава 1 - А.txt").write_text("Текст.", encoding="utf-8")
        job = self.finish(self.app.post("/api/format/collect", json={
            "targets": [str(folder)], "base": str(self.root), "name": "книга"}))
        self.assertIsNone(job.log)


class TestTheBookReportOverHttp(WebBase):

    def test_the_numbering_report_travels_with_the_book(self):
        path = self.root / "книга.md"
        path.write_text("# [Глава 1 — А]\nтекст\n\n# [Глава 3 — В]\nтекст\n",
                        encoding="utf-8")
        said = self.app.post("/api/format/book",
                             json={"targets": [str(path)]}).get_json()
        self.assertFalse(said["look"]["ok"])
        self.assertEqual(said["look"]["gaps"], ["2"])
