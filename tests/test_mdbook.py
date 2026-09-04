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

    def test_every_header_carries_all_three_fields(self):
        """Пробел перед решёткой тоже от загрузчика: так пишет заголовок
        переводчик, из которого книгу приносят, и так она возвращается с
        сайта.

        Так пишет сам загрузчик, и так выглядит книга, которую он
        отдаёт обратно. Сначала пустые поля с конца здесь опускались —
        это была выдумка, а строка с одним разделителем вместо трёх для
        сайта уже другая строка."""
        self.assertEqual(mdbook.make_head("Пролог").line(),
                         " # [Пролог :|: :|: :|: ]")

    def test_the_usual_header_looks_exactly_like_the_loaders_own(self):
        """Образец из отчёта: платность стоит, порядок и том пусты."""
        self.assertEqual(mdbook.make_head("Глава 31", paid="1").line(),
                         " # [Глава 31 :|: :|: 1 :|: ]")
        self.assertEqual(
            mdbook.make_head("Глава 1 — Правила ассасина", paid="1").line(),
            " # [Глава 1 — Правила ассасина :|: :|: 1 :|: ]")

    def test_the_order_keeps_its_own_slot(self):
        self.assertEqual(mdbook.make_head("Глава 1", order="1").line(),
                         " # [Глава 1 :|: 1 :|: :|: ]")

    def test_a_volume_forces_the_price_field(self):
        """Иначе сайт прочитает том как платность."""
        line = mdbook.make_head("Глава 1", order="1", volume="Том 2").line()
        self.assertEqual(line.count(mdbook.MARK), 3)

    def test_the_separator_cannot_get_into_a_title(self):
        """`:|:` внутри названия развалил бы разбор на сайте: сайт
        прочитал бы вторую половину названия как номер."""
        head = mdbook.make_head(f"До {mdbook.MARK} после")
        self.assertNotIn(mdbook.MARK, head.title)
        # Разделителей ровно три — те, что отделяют поля, и ни одного
        # лишнего из названия.
        self.assertEqual(head.line().count(mdbook.MARK), 3)

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
            self.assertTrue(head.line().startswith(" # ["))

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
        self.assertTrue(said["sample"][0].startswith(" # ["))

    def test_the_book_is_written(self):
        folder = self.chapters()
        job = self.finish(self.app.post("/api/format/collect", json={
            "targets": [str(folder)], "base": str(self.root), "name": "книга"}))
        self.assertIsNone(job.error)
        text = (self.root / "книга.md").read_text(encoding="utf-8")
        self.assertEqual(text.count(" # ["), 3)
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


class TestABookThatGoesInPairs(unittest.TestCase):
    """Книгу, поделённую надвое, отдают загрузчику парами.

    «Глава 295» стоит дважды подряд, без номера части в заголовке — так
    её собрал переводчик. Для такой книги две главы под номером норма, а
    не находка.

    Проверка этого не знала и врала дважды. На книге в пятьсот шестьдесят
    глав она объявляла дублями двести шестьдесят девять номеров — почти
    всю книгу, — и за этим списком не было видно ничего. А пропажу
    четырёх глав не показывала вовсе: глава ушла, номер остался, дыры в
    номерах нет.
    """

    def book(self, titles):
        return [(mdbook.make_head(title), []) for title in titles]

    def pairs(self, missing=()):
        """Книга парами; у названных номеров — по одной главе."""
        titles = []
        for number in range(294, 583):
            titles += [f"Глава {number}"] * (1 if number in missing else 2)
        return self.book(titles)

    def test_the_book_says_how_many_chapters_a_number_has(self):
        self.assertEqual(mdbook.inspect(self.pairs())["per_number"], 2)

    def test_pairs_are_not_doubles(self):
        """Двести шестьдесят девять находок вместо ни одной."""
        self.assertEqual(mdbook.inspect(self.pairs())["doubles"], [])

    def test_a_book_in_pairs_is_in_order(self):
        self.assertTrue(mdbook.inspect(self.pairs())["ok"])

    def test_a_lost_chapter_shows_up_as_a_thin_number(self):
        """Ровно то, чего человек и ждал: «пропущено четыре»."""
        look = mdbook.inspect(self.pairs(missing=(303, 350, 400, 500)))
        self.assertEqual(look["thin_count"], 4)
        self.assertEqual(look["thin"], ["303", "350", "400", "500"])

    def test_a_lost_chapter_makes_the_book_not_ok(self):
        self.assertFalse(mdbook.inspect(self.pairs(missing=(303,)))["ok"])

    def test_a_third_chapter_under_a_number_is_not_a_double(self):
        """У главы бывает и три части: в настоящей книге у 298-й их
        именно три. Объявлять третью лишней нельзя — она такая же часть,
        как первые две, и текст у неё свой."""
        book = self.pairs() + self.book(["Глава 300"])
        self.assertEqual(mdbook.inspect(book)["doubles"], [])

    def test_a_number_missing_entirely_is_still_a_gap(self):
        """Ушли обе главы — и номера не стало вовсе."""
        titles = []
        for number in range(294, 583):
            if number != 400:
                titles += [f"Глава {number}"] * 2
        self.assertEqual(mdbook.inspect(self.book(titles))["gaps"], ["400"])


class TestTheRhythmNeedsEvidence(unittest.TestCase):
    """Ритм — это правило книги, а не совпадение двух строк."""

    def book(self, titles):
        return [(mdbook.make_head(title), []) for title in titles]

    def test_a_small_book_has_no_rhythm(self):
        """В книге из двух глав «у каждого номера по две» означает только
        то, что глав всего две."""
        look = mdbook.inspect(self.book(["Глава 5", "Глава 5"]))
        self.assertEqual(look["per_number"], 1)
        self.assertEqual(look["thin"], [])

    def test_a_small_book_still_finds_a_hole(self):
        look = mdbook.inspect(self.book(
            [f"Глава {n}" for n in (1, 2, 2, 4)]))
        self.assertEqual(look["gaps"], ["3"])
        self.assertEqual(look["thin"], [])

    def test_a_ragged_book_has_no_rhythm(self):
        """Разнобой ритмом не считается: иначе случайный перекос объявил
        бы нормой то, что нормой не является."""
        titles = []
        for number in range(1, 21):
            titles += [f"Глава {number}"] * (1 if number % 2 else 3)
        self.assertEqual(mdbook.inspect(self.book(titles))["per_number"], 1)

    def test_an_ordinary_book_is_untouched(self):
        look = mdbook.inspect(self.book(
            [f"Глава {n}" for n in range(1, 30)]))
        self.assertEqual(look["per_number"], 1)
        self.assertTrue(look["ok"])
        self.assertEqual(look["thin"], [])

    def test_parts_are_still_not_doubles_in_a_long_book(self):
        """Книга из частей: «201.1» и «201.2» — две части одной главы."""
        titles = [f"Глава {n}.{part}" for n in range(1, 30) for part in (1, 2)]
        look = mdbook.inspect(self.book(titles))
        self.assertEqual(look["doubles"], [])
        self.assertEqual(look["thin"], [])

    def test_a_missing_part_shows_up(self):
        """У главы 15 осталась одна часть из двух — её и потеряли."""
        titles = [f"Глава {n}.{part}" for n in range(1, 30) for part in (1, 2)
                  if not (n == 15 and part == 2)]
        self.assertEqual(mdbook.inspect(self.book(titles))["thin"], ["15"])



class TestADoubleIsTheChapterNotTheNumber(unittest.TestCase):
    """«Если есть повтор глав, он должен определять дубль по тексту.»

    Совпадение номера этого ещё не значит: книгу, поделённую надвое,
    отдают загрузчику двумя главами под одним номером, и текст у них
    разный. А вот дословно совпавший текст значит ровно одно — глава
    попала в книгу дважды и уедет на сайт дважды.
    """

    def book(self, rows):
        return [(mdbook.make_head(title), list(body)) for title, body in rows]

    def pairs(self, extra=()):
        """Книга парами: у каждого номера две разные главы."""
        rows = []
        for number in range(294, 583):
            rows.append((f"Глава {number}", [f"Первая половина {number}."]))
            rows.append((f"Глава {number}", [f"Вторая половина {number}."]))
        return self.book(rows + list(extra))

    def test_one_number_two_different_chapters_is_not_a_double(self):
        self.assertEqual(mdbook.inspect(self.pairs())["doubles"], [])

    def test_a_book_in_pairs_is_in_order(self):
        self.assertTrue(mdbook.inspect(self.pairs())["ok"])

    def test_the_same_text_twice_is_a_double(self):
        look = mdbook.inspect(self.pairs(
            [("Глава 700", ["Первая половина 400."])]))
        self.assertEqual(look["doubles"], ["400 = 700"])

    def test_a_double_makes_the_book_not_ok(self):
        look = mdbook.inspect(self.pairs(
            [("Глава 700", ["Первая половина 400."])]))
        self.assertFalse(look["ok"])

    def test_the_finding_names_both_places(self):
        """Чинить придётся одну из двух — надо знать, какие это."""
        said = mdbook.inspect(self.pairs(
            [("Глава 700", ["Первая половина 400."])]))["doubles"][0]
        self.assertIn("400", said)
        self.assertIn("700", said)

    def test_spacing_does_not_hide_a_double(self):
        """Лишние пробелы и пустые строки — не разница в тексте."""
        look = mdbook.inspect(self.book([
            ("Глава 1", ["Текст главы."]),
            ("Глава 2", ["", "  Текст главы.  ", ""]),
        ]))
        self.assertEqual(look["doubles"], ["1 = 2"])

    def test_empty_chapters_are_not_all_doubles(self):
        """Пустую главу сравнивать не с чем: пустые совпадают все со
        всеми, и книга без тел глав вышла бы сплошным повтором."""
        look = mdbook.inspect(self.book([("Глава 1", []), ("Глава 2", [])]))
        self.assertEqual(look["doubles"], [])

    def test_a_chapter_without_a_number_is_named_by_its_title(self):
        look = mdbook.inspect(self.book([
            ("Информация", ["Одно и то же."]),
            ("Глава 5", ["Одно и то же."]),
        ]))
        self.assertEqual(look["doubles"], ["Информация = 5"])



class TestNumberingTheUnmarkedParts(unittest.TestCase):
    """У главы бывает две-три части, а пометка стоит не везде.

    Настоящая книга: «Глава 295», следом «Глава 295 (Часть 2)», следом
    две «Главы 296» подряд без всяких пометок, а у 298-й частей три.
    Загрузчику это уедет как одна и та же глава несколько раз, и порядок
    на сайте соберётся наугад.
    """

    def marked(self, taken):
        return mdbook.number_parts(taken)

    def test_two_chapters_of_one_number_become_parts(self):
        got = self.marked([(296, None, "А"), (296, None, "Б")])
        self.assertEqual([(n, p) for n, p, _ in got], [(296, 1), (296, 2)])

    def test_three_chapters_become_three_parts(self):
        got = self.marked([(298, None, "А"), (298, None, "Б"), (298, None, "В")])
        self.assertEqual([p for _, p, _ in got], [1, 2, 3])

    def test_a_lone_chapter_is_left_alone(self):
        """«Глава 300.1» без «300.2» означала бы часть, которой нет."""
        got = self.marked([(300, None, "Одна")])
        self.assertEqual(got, [(300, None, "Одна")])

    def test_a_part_the_person_marked_is_not_touched(self):
        """Она пришла от человека, и знать лучше него нам неоткуда."""
        taken = [(301, 1, "А"), (301, 2, "Б")]
        self.assertEqual(self.marked(taken), taken)

    def test_a_half_marked_run_is_left_alone(self):
        """Хоть у одной части номер есть — значит, разметку вели руками,
        и наша помощь тут только напортит."""
        taken = [(302, None, "А"), (302, 5, "Б")]
        self.assertEqual(self.marked(taken), taken)

    def test_the_same_number_far_apart_is_not_a_part(self):
        """Два одинаковых номера в разных концах книги — чужая ошибка, а
        не части: склеивать их было бы выдумкой."""
        taken = [(400, None, "А"), (401, None, "Б"), (400, None, "В")]
        self.assertEqual(self.marked(taken), taken)

    def test_a_chapter_without_a_number_is_left_alone(self):
        taken = [(None, None, "Информация"), (None, None, "Послесловие")]
        self.assertEqual(self.marked(taken), taken)

    def test_a_missing_number_does_not_join_its_neighbours(self):
        """Номеров в книге не хватает, и это надо учитывать: между 302-й и
        304-й нет 303-й, но частями одной главы они от этого не станут."""
        got = self.marked([(302, None, "А"), (302, None, "Б"),
                           (304, None, "В"), (304, None, "Г")])
        self.assertEqual([(n, p) for n, p, _ in got],
                         [(302, 1), (302, 2), (304, 1), (304, 2)])

    def test_the_hole_stays_a_hole(self):
        """Простановка частей номеров не выдумывает и дыр не закрывает:
        пропущенная глава так и остаётся пропущенной."""
        got = self.marked([(302, None, "А"), (302, None, "Б"),
                           (304, None, "В"), (304, None, "Г")])
        self.assertEqual(sorted({n for n, _, _ in got}), [302, 304])

    def test_a_number_left_with_one_part_keeps_no_part(self):
        """У 303-й половина потерялась. Ставить ей «303.1» значило бы
        обещать «303.2», которой нет; и проверка должна её найти."""
        got = self.marked([(302, None, "А"), (302, None, "Б"),
                           (303, None, "Одна половина"),
                           (304, None, "В"), (304, None, "Г")])
        self.assertEqual(got[2], (303, None, "Одна половина"))

    def test_the_names_survive(self):
        got = self.marked([(296, None, "Разойтись"), (296, None, "Разойтись")])
        self.assertEqual([name for _, _, name in got],
                         ["Разойтись", "Разойтись"])

    def test_every_chapter_gets_its_own_mark(self):
        """Ради чего всё: у каждой главы своя пометка, и загрузчику уже
        не уедет одна и та же глава несколько раз.

        Глав на номер при этом остаётся две — так книга и устроена, — но
        теперь это «294.1» и «294.2», а не «294» дважды.
        """
        book = []
        for number in range(294, 320):
            for half in ("Первая", "Вторая"):
                book.append((mdbook.make_head(f"Глава {number}"),
                             [f"{half} половина {number}."]))
        was = mdbook.inspect(book)
        self.assertEqual(was["per_number"], 2)

        taken = mdbook.number_parts(
            [mdbook.split_mark(head.title) for head, _ in book])
        style = mdbook.TitleStyle()
        fresh = [(mdbook.make_head(style.build(number, name, part=part)), body)
                 for (number, part, name), (_, body) in zip(taken, book)]
        self.assertEqual([head.title for head, _ in fresh][:4],
                         ["Глава 294.1", "Глава 294.2",
                          "Глава 295.1", "Глава 295.2"])
        now = mdbook.inspect(fresh)
        self.assertTrue(now["ok"])
        self.assertEqual(now["doubles"], [])
        self.assertEqual(now["thin"], [])



if __name__ == "__main__":
    unittest.main()


class TestLookingAtTheNumbering(unittest.TestCase):
    """Загрузчик сортирует главы по полю «Порядок», а человек читает
    номер в названии — расходятся они молча, и заметить это можно только
    до отправки на сайт."""

    def book(self, *lines):
        # Тело у каждой главы своё: дубль считается по тексту, и книга,
        # где все главы дословно одинаковы, — это книга из дублей, а не
        # образец порядка.
        text = "".join(f"{line}\nтекст главы {at}\n\n"
                       for at, line in enumerate(lines, 1))
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

    def test_one_number_two_different_chapters_is_not_a_double(self):
        """Настоящая книга: у главы две-три части, номер у них один, а
        текст разный. Считать это дублем — объявлять дублем половину
        книги."""
        look = self.book("# [Глава 5 — А]", "# [Глава 5 — Б]")
        self.assertEqual(look["doubles"], [])

    def test_the_same_chapter_twice_is_found(self):
        """А вот дословный повтор — дубль: такая уедет на сайт дважды."""
        text = ("# [Глава 5 — А]\nодин и тот же текст\n\n"
                "# [Глава 9 — Б]\nодин и тот же текст\n\n")
        look = mdbook.inspect(mdbook.read_book(text)[1])
        self.assertEqual(look["doubles"], ["5 = 9"])

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


class TestWhatToDoWithTheNames(WebBase):
    """То же, что «Переименовать» делает с именами файлов, — но внутри
    одного .md, который поедет на сайт. Наружу его имена не видны, и
    править их можно только там."""

    SOURCE = ("# [Глава 1 — Торговля :|: :|: 1 :|: ]\n\nТекст один.\n\n"
              "# [Глава 2 — Император :|: :|: 1 :|: ]\n\nТекст два.\n\n"
              "# [Пролог :|: :|: 1 :|: ]\n\nТекст три.\n")

    def rewrite(self, **more):
        path = self.root / "исходник.md"
        path.write_text(self.SOURCE, encoding="utf-8")
        payload = {"targets": [str(path)], "base": str(self.root),
                   "name": "готово"}
        payload.update(more)
        job = self.finish(self.app.post("/api/format/retitle", json=payload))
        self.assertIsNone(job.error)
        _, chapters = mdbook.read_book(
            (self.root / "готово.md").read_text(encoding="utf-8"))
        return [head.title for head, _ in chapters]

    def test_the_names_can_be_dropped_leaving_the_number(self):
        """Ровно то, ради чего всё: «оставить только нумерацию»."""
        self.assertEqual(self.rewrite(names="drop")[:2],
                         ["Глава 1", "Глава 2"])

    def test_a_chapter_without_a_number_keeps_its_name(self):
        """«Глава» вместо «Пролога» было бы неправдой."""
        self.assertEqual(self.rewrite(names="drop")[2], "Пролог")

    def test_dropping_the_names_asks_the_model_nothing(self):
        """Ни ключей, ни сети для этого не нужно."""
        self.rewrite(names="drop")
        self.assertEqual(self.llm.asked, [])

    def test_the_names_can_be_kept_and_only_restyled(self):
        got = self.rewrite(names="keep", prefix="Гл.", separator=". ")
        self.assertEqual(got[0], "Гл. 1. Торговля")

    def test_keeping_the_names_asks_the_model_nothing_either(self):
        self.rewrite(names="keep")
        self.assertEqual(self.llm.asked, [])

    def test_translating_is_still_the_default(self):
        """Кнопка была про перевод, и молча менять это нельзя."""
        self.assertTrue(self.rewrite()[0].startswith("Глава 1"))
        self.assertTrue(self.llm.asked)

    def test_an_unknown_way_is_refused(self):
        path = self.root / "исходник.md"
        path.write_text(self.SOURCE, encoding="utf-8")
        got = self.app.post("/api/format/retitle", json={
            "targets": [str(path)], "base": str(self.root),
            "name": "готово", "names": "выбросить всё"})
        self.assertEqual(got.status_code, 400)

    def test_the_price_survives_every_way(self):
        """Заголовок несёт цену главы — её не трогает ни один способ."""
        for way in ("drop", "keep", "translate"):
            with self.subTest(way=way):
                path = self.root / "исходник.md"
                path.write_text(self.SOURCE, encoding="utf-8")
                self.finish(self.app.post("/api/format/retitle", json={
                    "targets": [str(path)], "base": str(self.root),
                    "name": "готово", "names": way}))
                _, chapters = mdbook.read_book(
                    (self.root / "готово.md").read_text(encoding="utf-8"))
                self.assertTrue(all(h.paid == "1" for h, _ in chapters))


class TestRenumberingTheChapters(WebBase):

    SOURCE = ("# [Глава 7 — А]\n\nТекст.\n\n"
              "# [Глава 9 — Б]\n\nТекст.\n\n"
              "# [Глава 40 — В]\n\nТекст.\n")

    def rewrite(self, **more):
        path = self.root / "исходник.md"
        path.write_text(self.SOURCE, encoding="utf-8")
        payload = {"targets": [str(path)], "base": str(self.root),
                   "name": "готово", "names": "keep"}
        payload.update(more)
        self.finish(self.app.post("/api/format/retitle", json=payload))
        _, chapters = mdbook.read_book(
            (self.root / "готово.md").read_text(encoding="utf-8"))
        return [head.title for head, _ in chapters]

    def test_the_numbers_go_in_a_row_from_the_given_one(self):
        self.assertEqual(self.rewrite(renumber=1),
                         ["Глава 1 — А", "Глава 2 — Б", "Глава 3 — В"])

    def test_zero_leaves_the_numbers_alone(self):
        """Они пришли из книги, и врать про них не надо."""
        self.assertEqual(self.rewrite(renumber=0)[0], "Глава 7 — А")

    def test_renumbering_works_together_with_dropping_the_names(self):
        self.assertEqual(self.rewrite(names="drop", renumber=100),
                         ["Глава 100", "Глава 101", "Глава 102"])

    def test_a_chapter_without_a_number_is_not_given_one(self):
        """Из «Пролога» вышла бы «Глава 3», а с «убрать названия» от него
        не осталось бы и имени."""
        source = ("# [Глава 7 — А]\n\nТекст.\n\n"
                  "# [Пролог]\n\nТекст.\n\n"
                  "# [Глава 9 — Б]\n\nТекст.\n")
        path = self.root / "исходник.md"
        path.write_text(source, encoding="utf-8")
        self.finish(self.app.post("/api/format/retitle", json={
            "targets": [str(path)], "base": str(self.root), "name": "готово",
            "names": "keep", "renumber": 1}))
        _, chapters = mdbook.read_book(
            (self.root / "готово.md").read_text(encoding="utf-8"))
        self.assertEqual([h.title for h, _ in chapters],
                         ["Глава 1 — А", "Пролог", "Глава 2 — Б"])

    def test_dropping_the_names_does_not_eat_the_prologue(self):
        source = "# [Глава 7 — А]\n\nТекст.\n\n# [Пролог]\n\nТекст.\n"
        path = self.root / "исходник.md"
        path.write_text(source, encoding="utf-8")
        self.finish(self.app.post("/api/format/retitle", json={
            "targets": [str(path)], "base": str(self.root), "name": "готово",
            "names": "drop", "renumber": 1}))
        _, chapters = mdbook.read_book(
            (self.root / "готово.md").read_text(encoding="utf-8"))
        self.assertEqual([h.title for h, _ in chapters], ["Глава 1", "Пролог"])


class TestTheBookHasNoBlankLines(unittest.TestCase):
    """Книга для загрузчика пишется строка за строкой, без пустых.

    Пустая строка превращается на сайте в пустой абзац, и книга уезжает
    туда с огромными отступами между строками. Так же — без пустых строк
    — пишет книгу и переводчик, из которого её сюда приносят.
    """

    def book(self, count=2):
        from core.models import Chapter

        chapters = [Chapter(number=n, title=f"Глава {n}",
                            paragraphs=[f"Первый абзац {n}.",
                                        f"Второй абзац {n}."])
                    for n in range(1, count + 1)]
        return mdbook.write_book(mdbook.from_chapters(chapters))

    def test_no_empty_line_between_paragraphs(self):
        self.assertNotIn("\n\n", self.book())

    def test_the_text_follows_the_header_at_once(self):
        lines = self.book(1).splitlines()
        self.assertTrue(lines[0].strip().startswith("# ["))
        self.assertEqual(lines[1], "Первый абзац 1.")

    def test_every_paragraph_keeps_its_own_line(self):
        self.assertEqual(self.book(1).splitlines()[1:],
                         ["Первый абзац 1.", "Второй абзац 1."])

    def test_a_chapter_written_without_blanks_can_still_be_divided(self):
        """Абзац — строка. По прежнему правилу («кусок между пустыми
        строками») вся такая глава была одним абзацем, а значит
        неделимой."""
        body = ["Первый.", "Второй.", "Третий.", "Четвёртый."]
        self.assertEqual(mdbook.paragraphs_of(body), body)

    def test_a_book_with_blank_lines_reads_the_same_way(self):
        """Старые книги никуда не делись — их абзац тоже занимает строку."""
        self.assertEqual(
            mdbook.paragraphs_of(["Первый.", "", "Второй.", ""]),
            ["Первый.", "Второй."])


class TestPartsAreNotDoubles(unittest.TestCase):
    """Главу можно поделить на части руками — это не дубль номера.

    Человек делит длинную главу прямо в книге: «Глава 201.1», «Глава
    201.2». Проверка считала обе «главой 201» и объявляла книгу сплошным
    непорядком, а перезапись заголовков превращала обе в «Главу 201» —
    и тогда дубль становился настоящим.
    """

    def look(self, *titles):
        # Тело у каждой главы своё: дубль считается по тексту.
        return mdbook.inspect([(mdbook.make_head(title), [f"текст {at}"])
                               for at, title in enumerate(titles, 1)])

    def test_two_parts_of_one_chapter_are_not_a_double(self):
        look = self.look("Глава 201.1", "Глава 201.2", "Глава 202")
        self.assertEqual(look["doubles"], [])
        self.assertTrue(look["ok"])

    def test_the_same_part_twice_is_not_a_double_by_itself(self):
        """Номер повторился, а текст разный — значит, это разные куски,
        которым просто не поправили пометку."""
        look = self.look("Глава 201.1", "Глава 201.1")
        self.assertEqual(look["doubles"], [])

    def test_the_same_number_without_parts_is_not_a_double_by_itself(self):
        """Две части одной главы часто идут без пометки части вовсе — так
        их отдаёт переводчик. Текст у них разный, и дубля тут нет."""
        look = self.look("Глава 5", "Глава 5")
        self.assertEqual(look["doubles"], [])

    def test_parts_do_not_leave_a_hole_in_the_numbering(self):
        look = self.look("Глава 201.1", "Глава 201.2", "Глава 202")
        self.assertEqual(look["gaps"], [])

    def test_the_part_number_is_read(self):
        self.assertEqual(mdbook.split_mark("Глава 201.2"), (201, 2, ""))
        self.assertEqual(mdbook.split_mark("Глава 82 — Молния"),
                         (82, None, "Молния"))


class TestTheNameInTheTitleWhenCollecting(unittest.TestCase):
    """Собирая книгу из файлов, название в заголовке можно не хотеть.

    Выбор этот был только у второй карточки, которая правит уже готовую
    книгу: собрать сразу «Глава 82», без имени файла в заголовке, было
    нечем.
    """

    def chapter(self, number=82, title="Глава 82 - Пурпурная молния",
                part=None):
        return Chapter(number=number, part=part, title=title,
                       paragraphs=["Текст."])

    def titles(self, chapters, **kw):
        return [head.title for head, _ in mdbook.from_chapters(chapters, **kw)]

    def test_by_default_the_name_stays(self):
        self.assertEqual(self.titles([self.chapter()]),
                         ["Глава 82 — Пурпурная молния"])

    def test_asked_to_drop_it_only_the_number_is_left(self):
        self.assertEqual(self.titles([self.chapter()], names=mdbook.DROP),
                         ["Глава 82"])

    def test_asked_to_keep_it_the_name_is_kept(self):
        self.assertEqual(self.titles([self.chapter()], names=mdbook.KEEP),
                         ["Глава 82 — Пурпурная молния"])

    def test_a_chapter_without_a_number_keeps_its_name_anyway(self):
        """«Глава» вместо «Пролога» — неправда: номера у него нет, и
        убрать имя значило бы стереть главу целиком."""
        prologue = Chapter(title="Пролог", paragraphs=["Текст."])
        self.assertEqual(self.titles([prologue], names=mdbook.DROP), ["Пролог"])

    def test_the_part_number_survives_dropping_the_name(self):
        made = self.titles([self.chapter(part=2, title="Глава 82.2 - Молния")],
                           names=mdbook.DROP)
        self.assertEqual(made, ["Глава 82.2"])

    def test_the_text_is_not_touched(self):
        out = mdbook.from_chapters([self.chapter()], names=mdbook.DROP)
        self.assertEqual(out[0][1], ["Текст."])

    def test_a_part_read_only_from_the_title_survives_too(self):
        """Номера у главы может не быть вовсе — тогда его вынимают из
        названия. Часть должна приехать оттуда же."""
        loose = Chapter(title="Глава 82.3 - Молния", paragraphs=["Текст."])
        self.assertEqual(self.titles([loose]), ["Глава 82.3 — Молния"])


class TestStrippingTheNumberOfAPart(unittest.TestCase):
    """У файла «Глава 201.2 - Название» пометка главы — всё «Глава
    201.2». Пока часть в неё не входила, от неё оставалась «2», и в книге
    выходило «Глава 201.2 — 2 - Название»."""

    def test_the_part_goes_away_with_the_number(self):
        self.assertEqual(mdbook.bare_name("Глава 201.2 - Пурпурная молния",
                                          201),
                         "Пурпурная молния")

    def test_a_name_ending_in_a_number_is_left_alone(self):
        self.assertEqual(mdbook.bare_name("Название 1", None), "Название 1")

    def test_a_different_number_is_not_stripped(self):
        self.assertEqual(mdbook.bare_name("Глава 201.2 - Молния", 55),
                         "Глава 201.2 - Молния")


class TestWhatToDoWithTheNameOverHttp(WebBase):

    def chapters(self):
        folder = self.root / "главы"
        folder.mkdir(exist_ok=True)
        for n in (1, 2):
            (folder / f"Глава {n} - Название {n}.txt").write_text(
                f"Текст главы {n}.", encoding="utf-8")
        return folder

    def collect(self, **extra):
        folder = self.chapters()
        payload = {"targets": [str(folder)], "base": str(self.root),
                   "name": "книга"}
        payload.update(extra)
        return self.app.post("/api/format/collect", json=payload)

    def written(self):
        _, chapters = mdbook.read_book(
            (self.root / "книга.md").read_text(encoding="utf-8"))
        return [head.title for head, _ in chapters]

    def test_the_choice_reaches_the_book(self):
        self.finish(self.collect(names=mdbook.DROP))
        self.assertEqual(self.written(), ["Глава 1", "Глава 2"])

    def test_without_the_choice_nothing_changes(self):
        self.finish(self.collect())
        self.assertEqual(self.written(),
                         ["Глава 1 — Название 1", "Глава 2 — Название 2"])

    def test_an_unknown_choice_is_refused(self):
        res = self.collect(names="выкинуть всё")
        self.assertEqual(res.status_code, 400)
        self.assertIn("названием", res.get_json()["error"])


class TestBringingAnOldBookToStandard(unittest.TestCase):
    """Старая книга приходит такой, какой её отдал прежний конвертер:
    решётка без пробела и пустая строка между абзацами. Пустая строка
    становится на сайте пустым абзацем — отсюда огромные отступы."""

    def book(self):
        return mdbook.read_book(
            "#[Глава 1 :|: :|: 1 :|: ]\n"
            "\n"
            "Первый абзац.\n"
            "\n"
            "Второй абзац.\n")[1]

    def test_the_space_before_the_hash_appears(self):
        out = mdbook.to_standard(self.book())
        self.assertTrue(out[0][0].line().startswith(" # ["))

    def test_the_blank_lines_go_away(self):
        out = mdbook.to_standard(self.book())
        self.assertEqual(out[0][1], ["Первый абзац.", "Второй абзац."])

    def test_the_paragraphs_themselves_survive(self):
        text = mdbook.write_book(mdbook.to_standard(self.book()))
        self.assertIn("Первый абзац.", text)
        self.assertIn("Второй абзац.", text)

    def test_the_price_and_the_volume_are_not_touched(self):
        """Правка вида, а не содержания: поля заголовка значат цену."""
        head, _ = mdbook.to_standard(self.book())[0]
        self.assertEqual(head.title, "Глава 1")
        self.assertEqual(head.paid, "1")
        self.assertTrue(head.line().endswith(":|: ]"))

    def test_a_book_already_standard_stays_as_it_was(self):
        was = " # [Глава 1 :|: :|: 1 :|: ]\nПервый абзац.\n"
        lead, chapters = mdbook.read_book(was)
        self.assertEqual(mdbook.write_book(mdbook.to_standard(chapters), lead),
                         was)


class TestBringingToStandardOverHttp(WebBase):
    """Галка «привести к стандарту» на переписывании заголовков."""

    OLD = ("#[Chapter 1168_ Trade :|: :|: 1 :|: ]\n"
           "\n"
           "Первый абзац главы.\n"
           "\n"
           "Второй абзац главы.\n")

    def book(self):
        path = self.root / "старая.md"
        path.write_text(self.OLD, encoding="utf-8")
        return path

    def retitled(self, **more):
        payload = {"targets": [str(self.book())], "base": str(self.root),
                   "name": "готово"}
        payload.update(more)
        job = self.finish(self.app.post("/api/format/retitle", json=payload))
        self.assertIsNone(job.error)
        return (self.root / "готово.md").read_text(encoding="utf-8")

    def test_asked_to_tidy_the_blank_lines_go_away(self):
        text = self.retitled(tidy=True)
        self.assertNotIn("\n\n", text)

    def test_asked_to_tidy_the_hash_gets_its_space(self):
        text = self.retitled(tidy=True)
        self.assertTrue(text.startswith(" # ["))

    def test_without_the_checkbox_the_book_is_left_as_it_was(self):
        """Чужую книгу молча не переписываем."""
        text = self.retitled()
        self.assertIn("\n\n", text)
        self.assertTrue(text.startswith("#["))

    def test_the_text_survives_the_tidying(self):
        text = self.retitled(tidy=True)
        self.assertIn("Первый абзац главы.", text)
        self.assertIn("Второй абзац главы.", text)

    def test_the_price_survives_the_tidying(self):
        _, chapters = mdbook.read_book(self.retitled(tidy=True))
        self.assertTrue(all(head.paid == "1" for head, _ in chapters))

    def test_the_preview_shows_the_tidied_line(self):
        """Показывать надо тот файл, который выйдет, — иначе человек
        сверяет предпросмотр с чем-то другим."""
        said = self.app.post("/api/format/retitle/preview", json={
            "targets": [str(self.book())], "names": "keep",
            "tidy": True}).get_json()
        self.assertTrue(said["rows"][0]["before"].startswith("#["))
        self.assertTrue(said["rows"][0]["after"].startswith(" # ["))


class TestCuttingEveryChapterInTwo(unittest.TestCase):
    """Поделить главы в готовой книге — работа сама по себе.

    Раньше добраться до неё можно было только попутно, вместе с
    переписыванием заголовков: то есть ценой ключей и с риском заодно
    переписать всю книгу. А нужно бывает ровно одно — границы глав.
    """

    def book(self, chapters: int = 2, blocks: int = 6):
        out = []
        for number in range(1, chapters + 1):
            body = []
            for at in range(blocks):
                body.append(f"Абзац {at + 1} главы {number}.")
                body.append("")
            out.append((mdbook.make_head(f"Глава {number} — Название",
                                         paid="1", volume="2"), body))
        return out

    def test_every_chapter_becomes_two(self):
        cut = mdbook.cut_all(self.book(chapters=3), 2)
        self.assertEqual(len(cut), 6)

    def test_the_parts_are_numbered_inside_the_chapter(self):
        cut = mdbook.cut_all(self.book(chapters=1), 2)
        self.assertEqual([head.title for head, _ in cut],
                         ["Глава 1.1 — Название", "Глава 1.2 — Название"])

    def test_not_a_single_paragraph_is_lost(self):
        """Половина книги, пропавшая молча, — худшее, что тут может быть."""
        book = self.book(chapters=2, blocks=5)
        was = [line for _, body in book for line in body if line.strip()]
        cut = mdbook.cut_all(book, 2)
        now = [line for _, body in cut for line in body if line.strip()]

        self.assertEqual(now, was)

    def test_the_price_and_the_volume_survive_the_cut(self):
        """В заголовке лежит цена главы: поправь её — узнаешь уже на сайте."""
        cut = mdbook.cut_all(self.book(chapters=1), 2)
        for head, _ in cut:
            with self.subTest(head.title):
                self.assertEqual(head.paid, "1")
                self.assertEqual(head.volume, "2")

    def test_a_chapter_too_short_to_cut_stays_whole(self):
        """Это не отказ, а «нечего резать»."""
        short = [(mdbook.make_head("Глава 7 — Коротко"), ["Одна строка."])]
        cut = mdbook.cut_all(short, 2)

        self.assertEqual(len(cut), 1)
        self.assertEqual(cut[0][0].title, "Глава 7 — Коротко")

    def test_more_than_two_parts_works_the_same(self):
        cut = mdbook.cut_all(self.book(chapters=1, blocks=9), 3)
        self.assertEqual([head.title for head, _ in cut],
                         ["Глава 1.1 — Название", "Глава 1.2 — Название",
                          "Глава 1.3 — Название"])

    def test_asking_for_one_part_changes_nothing(self):
        book = self.book(chapters=2)
        self.assertEqual(len(mdbook.cut_all(book, 1)), 2)

    def test_the_book_still_reads_back_after_the_cut(self):
        """Проверка сквозная: записали поделённое — и прочли обратно."""
        cut = mdbook.cut_all(self.book(chapters=2), 2)
        lead, again = mdbook.read_book(mdbook.write_book(cut, ""))

        self.assertEqual(len(again), 4)
        self.assertEqual([head.title for head, _ in again],
                         [head.title for head, _ in cut])


class TestCuttingOverHttp(unittest.TestCase):
    """Маршрут берёт один файл или сколько угодно — человеку без разницы."""

    def setUp(self):
        from tempfile import TemporaryDirectory

        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()

        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.out = self.tmp / "готово"
        self.out.mkdir()

    def write(self, name: str, chapters: int = 2) -> Path:
        lines = []
        for number in range(1, chapters + 1):
            lines.append(f"# [Глава {number} — Название :|: :|: 1 :|: ]")
            for at in range(6):
                lines.append(f"Абзац {at + 1} главы {number}.")
                lines.append("")
        path = self.tmp / name
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def cut(self, **more):
        body = {"base": str(self.out), "parts": 2}
        body.update(more)
        return self.app.post("/api/format/halve", json=body)

    def test_one_book_is_cut(self):
        book = self.write("книга.md", chapters=3)
        got = self.cut(targets=[str(book)]).get_json()

        self.assertEqual(got["chapters"], 3)
        self.assertEqual(got["made"], 6)
        self.assertTrue((self.out / "книга.md").is_file())

    def test_many_books_at_once_are_no_different(self):
        for name in ("одна.md", "вторая.md", "третья.md"):
            self.write(name)
        got = self.cut(targets=[str(self.tmp / "одна.md"),
                                str(self.tmp / "вторая.md"),
                                str(self.tmp / "третья.md")]).get_json()

        self.assertEqual(len(got["files"]), 3)
        self.assertEqual(got["made"], 12)

    def test_a_whole_folder_can_be_given_instead(self):
        for name in ("одна.md", "вторая.md"):
            self.write(name)
        (self.tmp / "заметка.txt").write_text("не книга", encoding="utf-8")

        got = self.cut(targets=[str(self.tmp)]).get_json()
        self.assertEqual(sorted(one["file"] for one in got["files"]),
                         ["вторая.md", "одна.md"])
        # И именно молча: в папке рядом с книгами лежит служебное, и
        # жаловаться на каждый её файл значит утопить настоящие отказы.
        # Тем этот случай и отличается от файла, выбранного руками.
        self.assertEqual(got["failed"], [])

    def test_a_file_chosen_by_hand_that_is_not_md_is_refused(self):
        """Человек указал именно на него — молчать нельзя."""
        other = self.tmp / "заметка.txt"
        other.write_text("не книга", encoding="utf-8")

        res = self.cut(targets=[str(other)])
        self.assertEqual(res.status_code, 400)
        self.assertIn("не книга .md", res.get_json()["error"])

    def test_the_source_is_never_overwritten(self):
        """Не понравится — сверять будет не с чем, а работа необратима."""
        book = self.write("книга.md")
        was = book.read_text(encoding="utf-8")

        res = self.cut(targets=[str(book)], base=str(self.tmp))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(book.read_text(encoding="utf-8"), was)

    def test_a_file_that_is_not_a_loader_book_is_named_not_swallowed(self):
        """Молча пропустить половину выбранного — худшее, что тут можно."""
        good = self.write("книга.md")
        bad = self.tmp / "чужая.md"
        bad.write_text("Просто текст без заголовков.", encoding="utf-8")

        got = self.cut(targets=[str(good), str(bad)]).get_json()
        self.assertEqual([one["file"] for one in got["files"]], ["книга.md"])
        self.assertEqual([one["file"] for one in got["failed"]], ["чужая.md"])

    def test_nothing_chosen_is_a_refusal(self):
        res = self.cut(targets=[])
        self.assertEqual(res.status_code, 400)
        self.assertIn("Выберите", res.get_json()["error"])

    def test_a_missing_output_folder_is_a_refusal(self):
        book = self.write("книга.md")
        res = self.cut(targets=[str(book)], base=str(self.tmp / "нет-такой"))

        self.assertEqual(res.status_code, 400)
        self.assertIn("Папка не найдена", res.get_json()["error"])

    def test_the_number_of_parts_reaches_the_work(self):
        book = self.write("книга.md", chapters=1)
        got = self.cut(targets=[str(book)], parts=3).get_json()

        self.assertEqual(got["made"], 3)

    def test_a_silly_number_of_parts_is_squeezed_into_reason(self):
        """Ноль частей и тысяча — обе бессмыслица, но не повод падать."""
        book = self.write("книга.md", chapters=1)

        self.assertEqual(self.cut(targets=[str(book)],
                                  parts=0).get_json()["parts"], 2)
        self.assertLessEqual(self.cut(targets=[str(book)],
                                      parts=999).get_json()["parts"], 10)
