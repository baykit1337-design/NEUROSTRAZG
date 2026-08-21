"""Тесты вкладки «Переименование и деление» (раздел 3 ТЗ)."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import rename  # noqa: E402
from mvl.rename import NameFormat  # noqa: E402

BODY = "Абзац текста этой главы, достаточно длинный для деления. " * 4


def make_folder(root: Path, chapters=(201, 202, 203), service=True) -> Path:
    """Папка в том виде, в каком её отдаёт WebToEpub."""
    folder = root / "webtoepub"
    folder.mkdir()
    index = 1
    if service:
        (folder / "0001 - Информация.txt").write_text("Служебная страница.", encoding="utf-8")
        index = 2
    for offset, number in enumerate(chapters):
        text = "\n\n".join(f"Абзац {n}. {BODY}" for n in range(1, 9))
        (folder / f"{index + offset:04d} - Глава {number}. Название {number}.txt").write_text(
            text, encoding="utf-8"
        )
    return folder


class TestParseName(unittest.TestCase):
    def test_examples_from_spec(self):
        cases = {
            "0010 - Глава 209. Частичное приручение паука (1)": (10, 209, "Частичное приручение паука (1)"),
            "0010 - Глава 209: Название": (10, 209, "Название"),
            "0010 - Глава 209 - Название": (10, 209, "Название"),
            "Глава 209. Название": (None, 209, "Название"),
            "Chapter 209. Название": (None, 209, "Название"),
        }
        for stem, (seq, number, title) in cases.items():
            parts = rename.parse_name(stem)
            self.assertEqual((parts.seq, parts.number, parts.title), (seq, number, title), stem)

    def test_name_without_a_second_number_keeps_the_leading_one(self):
        """`0001 - Информация`: дальше числа нет, значит 0001 — это номер.

        Порядковый номер отбрасывается только тогда, когда есть что взять
        вместо него. Понятия «служебный файл» больше нет — из списка не
        выпадает ни один текстовый файл.
        """
        parts = rename.parse_name("0001 - Информация")
        self.assertEqual(parts.number, 1)
        self.assertEqual(parts.title, "Информация")

    def test_sequence_number_is_not_the_chapter_number(self):
        parts = rename.parse_name("0010 - Глава 209. Название")
        self.assertEqual(parts.seq, 10)
        self.assertEqual(parts.number, 209)

    def test_part_number_in_source_name(self):
        parts = rename.parse_name("0012 - Глава 210.2. Часть вторая")
        self.assertEqual((parts.number, parts.part), (210, 2))

    def test_name_without_title(self):
        parts = rename.parse_name("Глава 15")
        self.assertEqual((parts.number, parts.title), (15, ""))

    def test_custom_pattern(self):
        parts = rename.parse_name("### 42 Название", r"^###\s+(?P<number>\d+)\s+(?P<title>.*)$")
        self.assertEqual((parts.number, parts.title), (42, "Название"))

    def test_broken_pattern_reports_clearly(self):
        with self.assertRaises(rename.RenameError):
            rename.parse_name("x", r"(?P<number>\d+")


class TestBuildName(unittest.TestCase):
    """Все рабочие сочетания галочек из ТЗ."""

    def test_number_only(self):
        fmt = NameFormat(number=True, part=False, title=False)
        self.assertEqual(rename.build_name(201, None, "Конец", fmt), "Глава 201")

    def test_number_and_part(self):
        fmt = NameFormat(number=True, part=True, title=False)
        self.assertEqual(rename.build_name(201, 2, "Конец", fmt), "Глава 201.2")

    def test_number_and_title(self):
        fmt = NameFormat(number=True, part=False, title=True)
        # Двоеточие Windows не разрешает, поэтому в имени файла оно читаемо заменено.
        self.assertEqual(rename.build_name(201, 1, "Конец", fmt), "Глава 201 - Конец")

    def test_everything(self):
        fmt = NameFormat(number=True, part=True, title=True)
        self.assertEqual(rename.build_name(201, 1, "Конец", fmt), "Глава 201.1 - Конец")

    def test_title_only_is_deliberate(self):
        """Выкладка без спойлера в номере — осознанный сценарий, не ошибка."""
        fmt = NameFormat(number=False, part=False, title=True)
        self.assertEqual(rename.build_name(201, 1, "Конец", fmt), "Конец")

    def test_whole_chapter_gets_no_part_even_when_checked(self):
        fmt = NameFormat(number=True, part=True, title=False)
        self.assertEqual(rename.build_name(201, None, "Конец", fmt), "Глава 201")

    def test_custom_prefix(self):
        fmt = NameFormat(prefix="Chapter", title=False, part=False)
        self.assertEqual(rename.build_name(7, None, "", fmt), "Chapter 7")

    def test_prefix_can_be_cleared(self):
        fmt = NameFormat(prefix="", title=False, part=False)
        self.assertEqual(rename.build_name(7, None, "", fmt), "7")

    def test_each_separator(self):
        for separator in rename.SEPARATORS:
            fmt = NameFormat(separator=separator, part=False)
            name = rename.build_name(9, None, "Имя", fmt)
            self.assertTrue(name.startswith("Глава 9"), name)
            self.assertTrue(name.endswith("Имя"), name)

    def test_no_checkbox_still_produces_a_name(self):
        fmt = NameFormat(number=False, part=False, title=False)
        self.assertEqual(rename.build_name(201, 1, "Конец", fmt), "201")

    def test_forbidden_characters_replaced_not_dropped(self):
        self.assertEqual(rename.safe_filename("Глава 1: Имя"), "Глава 1 - Имя")
        for char in '\\/:*?"<>|':
            self.assertNotIn(char, rename.safe_filename(f"Имя{char}тут"))


class TestSplitIntoParts(unittest.TestCase):
    def test_halves(self):
        paragraphs = [f"Абзац {i} " + "т" * 100 for i in range(10)]
        parts = rename.split_into_parts(paragraphs, 2)
        self.assertEqual(len(parts), 2)
        self.assertEqual(sum(len(p) for p in parts), 10)

    def test_never_cuts_inside_a_paragraph(self):
        paragraphs = [f"Абзац {i}" for i in range(9)]
        rebuilt = [p for part in rename.split_into_parts(paragraphs, 3) for p in part]
        self.assertEqual(rebuilt, paragraphs)

    def test_parts_are_close_in_size(self):
        paragraphs = ["т" * 100 for _ in range(30)]
        sizes = [sum(len(p) for p in part) for part in rename.split_into_parts(paragraphs, 3)]
        self.assertLessEqual(max(sizes) - min(sizes), 100)

    def test_counts_two_through_six(self):
        paragraphs = [f"Абзац {i} " + "т" * 50 for i in range(24)]
        for count in range(2, 7):
            parts = rename.split_into_parts(paragraphs, count)
            self.assertEqual(len(parts), count)
            self.assertTrue(all(parts))

    def test_scene_break_never_opens_or_closes_a_part(self):
        paragraphs = ["A" * 100, "*", "B" * 100, "C" * 100, "*", "D" * 100]
        for part in rename.split_into_parts(paragraphs, 2):
            self.assertFalse(rename.SCENE_BREAK.match(part[0]), part)
            self.assertFalse(rename.SCENE_BREAK.match(part[-1]), part)

    def test_fewer_paragraphs_than_parts(self):
        self.assertEqual(len(rename.split_into_parts(["один", "два"], 5)), 1)

    def test_single_part_returns_everything(self):
        self.assertEqual(rename.split_into_parts(["a", "b"], 1), [["a", "b"]])


class RenameFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)
        self.folder = make_folder(self.tmp)


class TestScanAndPlan(RenameFolderTest):
    def test_scan_keeps_every_file(self):
        """Ни один текстовый файл из списка не выпадает."""
        chapters = rename.scan(self.folder)
        self.assertEqual(len(chapters), 4)
        self.assertTrue(all(c.number is not None for c in chapters))

    def test_scan_sorts_by_chapter_number(self):
        numbers = [c.number for c in rename.scan(self.folder)]
        self.assertEqual(numbers, [1, 201, 202, 203])

    def test_scan_reports_size_in_characters(self):
        chapter = next(c for c in rename.scan(self.folder) if c.number == 201)
        self.assertGreater(chapter.size, 0)

    def test_empty_folder_reports_clearly(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        with self.assertRaises(rename.RenameError):
            rename.scan(empty)

    def test_plan_takes_every_file_by_default(self):
        """По умолчанию отмечены все — ничего не пропускается само."""
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        self.assertEqual(len(rows), 4)

    def test_plan_honours_the_checkboxes(self):
        chapters = rename.scan(self.folder)
        chosen = {str(c.path) for c in chapters if c.number != 1}
        rows = rename.make_plan(chapters, NameFormat(), chosen=chosen)
        self.assertEqual([r.number for r in rows], [201, 202, 203])

    def test_renumber_from_ignores_numbers_in_names(self):
        rows = rename.make_plan(rename.scan(self.folder), NameFormat(), renumber_from=1)
        self.assertEqual([r.number for r in rows], [1, 2, 3, 4])

    def test_without_renumber_numbers_come_from_names(self):
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        # 1 — это «0001 - Информация»: дальше по имени числа нет, значит
        # порядковый номер и есть номер главы.
        self.assertEqual([r.number for r in rows], [1, 201, 202, 203])

    def test_split_produces_numbered_parts(self):
        chapters = rename.scan(self.folder)
        target = next(c for c in chapters if c.number == 202)
        rows = rename.make_plan(chapters, NameFormat(), splits={str(target.path): 3})
        parts = [r.part for r in rows if r.number == 202]
        self.assertEqual(parts, [1, 2, 3])

    def test_split_and_whole_chapters_coexist(self):
        chapters = rename.scan(self.folder)
        target = next(c for c in chapters if c.number == 202)
        rows = rename.make_plan(chapters, NameFormat(), splits={str(target.path): 2})
        names = [r.new_name for r in rows]
        self.assertIn("Глава 201 - Название 201", names)
        self.assertIn("Глава 202.1 - Название 202", names)


class TestPartsDissolveIntoAStraightCount(unittest.TestCase):
    """Книга, поделённая на части, сводится к сплошной нумерации.

    151.1, 151.2, 151.3 — это триста файлов; при нумерации подряд каждый
    становится отдельной главой: 151, 152, 153. Прежний номер части при
    этом уже ничего не значит, и «Глава 151.1, Глава 152.1» — мусор.
    """

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.folder = Path(self.tmpdir.name) / "части"
        self.folder.mkdir()
        order = 0
        for number in (151, 152, 153):
            for part in (1, 2, 3):
                order += 1
                name = f"{order:04d} - Глава {number}.{part}. Название {number}"
                # Несколько абзацев: из одного нарезать две части нечем.
                body = "\n\n".join(f"Абзац {n} главы {number}.{part}."
                                   for n in range(1, 7))
                (self.folder / f"{name}.txt").write_text(body, encoding="utf-8")

    def plan(self, **kwargs):
        return rename.make_plan(rename.scan(self.folder),
                                NameFormat(part=True), **kwargs)

    def test_the_files_are_counted_one_after_another(self):
        names = [row.new_name for row in self.plan(renumber_from=151)]
        self.assertEqual(names[0], "Глава 151 - Название 151")
        self.assertEqual(names[1], "Глава 152 - Название 151")
        self.assertEqual(names[-1], "Глава 159 - Название 153")

    def test_the_old_part_number_is_gone(self):
        """Даже когда галка «номер части» осталась включённой."""
        for row in self.plan(renumber_from=151):
            with self.subTest(name=row.new_name):
                self.assertIsNone(row.part)
                self.assertNotIn(".1", row.new_name)

    def test_the_order_of_parts_is_kept(self):
        """151.2 не должна оказаться раньше 151.1."""
        rows = self.plan(renumber_from=1)
        came = [Path(row.source).stem.split(" - ", 1)[1] for row in rows]
        self.assertEqual(came, sorted(came))

    def test_nothing_changes_without_renumbering(self):
        """Прежнее поведение трогать нельзя: часть на месте."""
        rows = self.plan()
        self.assertEqual(rows[0].part, 1)
        self.assertIn("151.1", rows[0].new_name)

    def test_a_part_cut_right_now_is_still_kept(self):
        """Иначе куски одной главы получат одно имя и затрут друг друга."""
        first = sorted(self.folder.iterdir())[0]
        rows = self.plan(renumber_from=1, splits={str(first): 2})

        pieces = [row for row in rows if row.source == str(first)]
        self.assertEqual([p.part for p in pieces], [1, 2])
        self.assertEqual(len({p.new_name for p in pieces}), 2)


class TestHeavyFilesAreNotReadForTheList(RenameFolderTest):
    """Список глав строился ценой разбора всей папки.

    `.docx` стоит 46 мс на файл, и папка читалась трижды: на показе
    списка, на предпросмотре имён и на записи. На пятистах главах это
    минуты ожидания перед пустым экраном. Список нужен по именам —
    текст ему не нужен вовсе.
    """

    def docx_folder(self, count=3):
        from core import formats
        from core.models import Chapter as OutChapter

        folder = self.tmp / "docx"
        folder.mkdir()
        body = OutChapter(title="Название",
                          paragraphs=["Первый абзац.", "Второй абзац."])
        for n in range(1, count + 1):
            formats.write(folder / f"{n:04d} - Глава {n}. Название {n}.docx",
                          [body])
        return folder

    def test_the_body_is_not_read_while_listing(self):
        chapters = rename.scan(self.docx_folder())
        self.assertTrue(chapters)
        for chapter in chapters:
            with self.subTest(name=chapter.path.name):
                self.assertFalse(chapter.loaded)
                self.assertEqual(chapter.text_parts, [])

    def test_light_formats_are_still_read_at_once(self):
        """Они стоят меньше двух миллисекунд — прятать нечего."""
        for chapter in rename.scan(self.folder):
            with self.subTest(name=chapter.path.name):
                self.assertTrue(chapter.loaded)
                self.assertIsNotNone(chapter.size)

    def test_the_size_is_honestly_unknown_until_then(self):
        """Лучше прочерк, чем выдуманное число."""
        chapter = rename.scan(self.docx_folder())[0]
        self.assertIsNone(chapter.size)
        self.assertIsNone(chapter.as_dict()["size"])

    def test_asking_for_the_body_reads_it_and_fills_the_size(self):
        chapter = rename.scan(self.docx_folder())[0]
        self.assertIn("Первый абзац.", chapter.body())
        self.assertTrue(chapter.loaded)
        self.assertGreater(chapter.size, 0)

    def test_the_text_still_reaches_the_written_file(self):
        """Главное: ленивое чтение не должно оставить пустые файлы."""
        rows = rename.make_plan(rename.scan(self.docx_folder()), NameFormat())
        out = self.tmp / "из-docx"
        report = rename.apply_plan(rows, out, fmt="txt")

        self.assertEqual(report.written, 3)
        for file in sorted(out.glob("*.txt")):
            with self.subTest(file=file.name):
                self.assertIn("Первый абзац.", file.read_text(encoding="utf-8"))

    def test_a_chapter_to_be_cut_is_read_after_all(self):
        """Резать без текста нечего — эту главу читаем сразу."""
        chapters = rename.scan(self.docx_folder())
        rows = rename.make_plan(chapters, NameFormat(),
                                splits={str(chapters[0].path): 2})

        pieces = [r for r in rows if r.source == str(chapters[0].path)]
        self.assertEqual(len(pieces), 2)
        self.assertTrue(all(r.paragraphs for r in pieces))

    def test_an_empty_chapter_is_not_mistaken_for_an_unread_one(self):
        """Иначе пустой файл молча взял бы текст из исходного."""
        empty = self.tmp / "пусто"
        empty.mkdir()
        (empty / "0001 - Глава 1. Ничего.txt").write_text("", encoding="utf-8")

        rows = rename.make_plan(rename.scan(empty), NameFormat())
        self.assertTrue(rows[0].loaded)


class TestApplyPlan(RenameFolderTest):
    def test_writes_to_new_folder_and_keeps_originals(self):
        before = sorted(p.name for p in self.folder.iterdir())
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        out = self.tmp / "готово"
        report = rename.apply_plan(rows, out)

        self.assertEqual(report.written, 4)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), before)

    def first_line(self, headings: bool) -> str:
        """Первая строка готовой главы 201: у неё известно и то и другое.

        Заголовок — «Название 201», текст начинается с «Абзац 1». По
        первой строке сразу видно, дописали название или нет.
        """
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        out = self.tmp / f"вывод-{headings}"
        rename.apply_plan(rows, out, headings=headings)
        file = next(p for p in out.glob("*.txt") if "201" in p.name)
        return file.read_text(encoding="utf-8").strip().splitlines()[0]

    def test_the_title_can_be_left_out_of_the_file(self):
        """Галки на вкладке не было вовсе, и заголовок писался всегда.

        Сервер брал умолчание `True`, выключить его было нечем: у книги,
        где название главы уже есть в самом тексте, оно оказывалось в
        файле дважды.
        """
        self.assertTrue(self.first_line(False).startswith("Абзац"),
                        self.first_line(False))

    def test_the_title_is_still_written_when_asked(self):
        self.assertIn("Название 201", self.first_line(True))

    def test_docx_output(self):
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        out = self.tmp / "docx"
        rename.apply_plan(rows, out, fmt="docx")
        self.assertEqual(len(list(out.glob("*.docx"))), 4)

    def test_duplicate_names_stop_the_run(self):
        """Совпадение имён — ошибка логики, а не повод дописать «(2)»."""
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        for row in rows:
            row.new_name = "Одно и то же"
        out = self.tmp / "dup"

        with self.assertRaises(rename.NameCollision) as ctx:
            rename.apply_plan(rows, out)
        self.assertIn("Одно и то же", str(ctx.exception))
        # Ничего не записано: остановились до первой записи.
        self.assertFalse(out.exists())

    def test_split_parts_get_distinct_names_without_the_checkbox(self):
        """У разрезанной главы номер части обязателен, иначе файлы затрут друг друга."""
        chapters = rename.scan(self.folder)
        target = next(c for c in chapters if c.number == 202)
        rows = rename.make_plan(
            chapters,
            NameFormat(part=False),           # галочка «номер части» снята
            splits={str(target.path): 2},
        )
        names = [r.new_name for r in rows if r.number == 202]
        self.assertEqual(names, ["Глава 202.1 - Название 202", "Глава 202.2 - Название 202"])
        self.assertEqual(rename.find_collisions(rows), [])

    def test_split_parts_are_written_as_separate_files(self):
        chapters = rename.scan(self.folder)
        target = next(c for c in chapters if c.number == 202)
        rows = rename.make_plan(chapters, NameFormat(part=False),
                                splits={str(target.path): 2})
        out = self.tmp / "parts"
        report = rename.apply_plan(rows, out)
        # Четыре главы, из них 202 разрезана надвое, — итого пять файлов.
        self.assertEqual(report.written, 5)
        self.assertTrue((out / "Глава 202.1 - Название 202.txt").is_file())
        self.assertTrue((out / "Глава 202.2 - Название 202.txt").is_file())
        # Ни одного имени с «(2)» — Windows разруливать конфликт не должен.
        self.assertFalse(any("(2)" in p.name for p in out.glob("*.txt")))

    def test_cancel_stops_writing(self):
        cancel = threading.Event()
        cancel.set()
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        with self.assertRaises(rename.Cancelled):
            rename.apply_plan(rows, self.tmp / "нет", cancel=cancel)

    def test_progress_reported(self):
        seen = []
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        rename.apply_plan(rows, self.tmp / "p", on_progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen, [(1, 4), (2, 4), (3, 4), (4, 4)])

    def test_split_parts_together_hold_the_whole_chapter(self):
        chapters = rename.scan(self.folder)
        target = next(c for c in chapters if c.number == 202)
        whole = sum(len(p) for p in target.text_parts)
        rows = rename.make_plan(chapters, NameFormat(), splits={str(target.path): 3})
        pieces = sum(r.size for r in rows if r.number == 202)
        self.assertEqual(pieces, whole)


class TestRenameWebApi(RenameFolderTest):
    def setUp(self):
        super().setUp()
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()

    def test_scan_endpoint(self):
        res = self.app.post("/api/rename/scan", json={"folder_in": str(self.folder)})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["total"], 4)
        self.assertEqual(body["suspect"], 0)

    def test_scan_requires_folder(self):
        self.assertEqual(self.app.post("/api/rename/scan", json={}).status_code, 400)

    def test_plan_endpoint(self):
        res = self.app.post("/api/rename/plan", json={"folder_in": str(self.folder)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["total"], 4)

    def test_plan_warns_about_forbidden_separator(self):
        res = self.app.post("/api/rename/plan", json={
            "folder_in": str(self.folder), "format": {"separator": ": "}})
        self.assertTrue(res.get_json()["forbidden"])

    def test_plan_writes_nothing(self):
        before = set(self.tmp.iterdir())
        self.app.post("/api/rename/plan", json={"folder_in": str(self.folder)})
        self.assertEqual(set(self.tmp.iterdir()), before)

    def test_apply_uses_edited_names(self):
        from webapp.app import JOBS

        res = self.app.post("/api/rename/apply", json={
            "folder_in": str(self.folder), "base": str(self.tmp), "folder_out": "Правки",
            "names": ["Своё имя A", "Своё имя B", "Своё имя C", "Своё имя D"],
        })
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["job"]["id"]
        JOBS[job_id].thread.join(timeout=60)

        names = sorted(p.stem for p in (self.tmp / "Правки").glob("*.txt"))
        self.assertEqual(
            names, ["Своё имя A", "Своё имя B", "Своё имя C", "Своё имя D"])

    def test_apply_requires_destination(self):
        res = self.app.post("/api/rename/apply", json={"folder_in": str(self.folder)})
        self.assertEqual(res.status_code, 400)

    def test_apply_rejects_bad_start_number(self):
        res = self.app.post("/api/rename/apply", json={
            "folder_in": str(self.folder), "base": str(self.tmp), "folder_out": "x",
            "renumber": True, "renumber_from": "не число",
        })
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
