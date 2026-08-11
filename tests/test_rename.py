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

    def test_service_file_has_no_chapter_number(self):
        """`0001 - Информация` — служебный файл, а не «глава 1»."""
        parts = rename.parse_name("0001 - Информация")
        self.assertIsNone(parts.number)
        self.assertTrue(parts.service)
        self.assertEqual(parts.seq, 1)

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
    def test_scan_finds_files_and_marks_service(self):
        chapters = rename.scan(self.folder)
        self.assertEqual(len(chapters), 4)
        self.assertEqual(sum(c.service for c in chapters), 1)

    def test_scan_sorts_by_chapter_number(self):
        numbers = [c.number for c in rename.scan(self.folder) if not c.service]
        self.assertEqual(numbers, [201, 202, 203])

    def test_scan_reports_size_in_characters(self):
        chapter = next(c for c in rename.scan(self.folder) if c.number == 201)
        self.assertGreater(chapter.size, 0)

    def test_empty_folder_reports_clearly(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        with self.assertRaises(rename.RenameError):
            rename.scan(empty)

    def test_plan_skips_service_by_default(self):
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        self.assertEqual(len(rows), 3)
        self.assertFalse(any(r.service for r in rows))

    def test_plan_can_keep_service_files(self):
        rows = rename.make_plan(rename.scan(self.folder), NameFormat(), skip_service=False)
        self.assertEqual(len(rows), 4)
        self.assertTrue(any(r.service for r in rows))

    def test_renumber_from_ignores_numbers_in_names(self):
        rows = rename.make_plan(rename.scan(self.folder), NameFormat(), renumber_from=1)
        self.assertEqual([r.number for r in rows], [1, 2, 3])

    def test_without_renumber_numbers_come_from_names(self):
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        self.assertEqual([r.number for r in rows], [201, 202, 203])

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


class TestApplyPlan(RenameFolderTest):
    def test_writes_to_new_folder_and_keeps_originals(self):
        before = sorted(p.name for p in self.folder.iterdir())
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        out = self.tmp / "готово"
        report = rename.apply_plan(rows, out)

        self.assertEqual(report.written, 3)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), before)

    def test_docx_output(self):
        rows = rename.make_plan(rename.scan(self.folder), NameFormat())
        out = self.tmp / "docx"
        rename.apply_plan(rows, out, fmt="docx")
        self.assertEqual(len(list(out.glob("*.docx"))), 3)

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
        self.assertEqual(report.written, 4)
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
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

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
        self.assertEqual(body["service"], 1)

    def test_scan_requires_folder(self):
        self.assertEqual(self.app.post("/api/rename/scan", json={}).status_code, 400)

    def test_plan_endpoint(self):
        res = self.app.post("/api/rename/plan", json={"folder_in": str(self.folder)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["total"], 3)

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
            "names": ["Своё имя A", "Своё имя B", "Своё имя C"],
        })
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["job"]["id"]
        JOBS[job_id].thread.join(timeout=60)

        names = sorted(p.stem for p in (self.tmp / "Правки").glob("*.txt"))
        self.assertEqual(names, ["Своё имя A", "Своё имя B", "Своё имя C"])

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
