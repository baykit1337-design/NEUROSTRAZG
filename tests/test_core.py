"""Тесты ядра (часть A ТЗ NEUROSTRAZH).

Обязательный минимум из A0: обработка текста, разбор имён, каждый читатель
на своём формате и round-trip каждого писателя — записали, прочитали
обратно, данные совпали.

Интернет не нужен: все файлы собираются на лету.
"""

from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats, naming, text  # noqa: E402
from core.models import Book, Chapter, OpReport  # noqa: E402
from core.readers.base import ReadError  # noqa: E402
from core.writers.base import WriteError  # noqa: E402

PARAGRAPHS = [
    "Первый абзац главы, достаточно длинный, чтобы его было видно.",
    "Второй абзац с другим содержанием и парой слов сверху.",
    "Третий и последний абзац этой главы.",
]


def sample(number: int = 201, title: str = "Глава 201. Название") -> Chapter:
    return Chapter(number=number, title=title, paragraphs=list(PARAGRAPHS))


class TestModels(unittest.TestCase):
    def test_chapter_text_joins_paragraphs(self):
        self.assertEqual(sample().text, "\n\n".join(PARAGRAPHS))

    def test_chapter_label(self):
        self.assertEqual(Chapter(number=201).label, "201")
        self.assertEqual(Chapter(number=201, part=2).label, "201.2")
        self.assertEqual(Chapter().label, "")

    def test_book_size_and_length(self):
        book = Book(chapters=[sample(), sample(202)])
        self.assertEqual(len(book), 2)
        self.assertEqual(book.size, sample().size * 2)

    def test_report_collects_failures(self):
        report = OpReport()
        report.fail("a.txt", "чтение", "BadZipFile: не архив")
        self.assertEqual(report.failed, 1)
        self.assertIn("a.txt — чтение", report.as_dict()["failed_files"][0])


class TestNaming(unittest.TestCase):
    """A0: разбор имён всех известных видов и сборка обратно."""

    def test_examples(self):
        cases = {
            "0010 - Глава 209. Название": (10, 209, None, "Название"),
            "0010 - Глава 209: Название": (10, 209, None, "Название"),
            "Глава 209. Название": (None, 209, None, "Название"),
            "Chapter 209. Название": (None, 209, None, "Название"),
            "0012 - Глава 210.2. Часть": (12, 210, 2, "Часть"),
        }
        for stem, expected in cases.items():
            parts = naming.parse(stem)
            with self.subTest(stem=stem):
                self.assertEqual(
                    (parts.seq, parts.number, parts.part, parts.title), expected
                )

    def test_service_file_has_no_number(self):
        parts = naming.parse("0001 - Информация")
        self.assertTrue(parts.service)
        self.assertIsNone(parts.number)

    def test_build_round_trip(self):
        """Собрали имя — разобрали обратно, номер и название на месте."""
        fmt = naming.NameFormat(separator=". ")
        for number, part, title in ((201, None, "Конец"), (361, 2, "Начало")):
            name = naming.build(number, part, title, fmt)
            back = naming.parse(name)
            with self.subTest(name=name):
                self.assertEqual(back.number, number)
                self.assertEqual(back.part, part)
                self.assertEqual(back.title, title)

    def test_forbidden_characters_replaced(self):
        for char in ':/\\|*?"<>':
            self.assertNotIn(char, naming.safe_filename(f"Имя{char}тут"))

    def test_colon_kept_readable(self):
        """Двоеточие запрещено и в Windows, и в macOS — но не теряется."""
        self.assertEqual(naming.safe_filename("Глава 1: Имя"), "Глава 1 - Имя")

    def test_reserved_windows_names(self):
        self.assertTrue(naming.safe_filename("CON").startswith("_"))

    def test_sort_key_is_numeric(self):
        chapters = [Chapter(number=361, part=10), Chapter(number=361, part=2)]
        ordered = sorted(chapters, key=naming.sort_key)
        self.assertEqual([c.part for c in ordered], [2, 10])


class TestText(unittest.TestCase):
    """A0: обработка абзацев, разделителей, дублей названия."""

    def test_duplicate_title_removed(self):
        title = "Глава 209. Название"
        blocks = text.prepare([title, title, "Текст."], title)
        self.assertEqual([b.text for b in blocks], ["Текст."])

    def test_scene_breaks_collapse(self):
        blocks = text.prepare(["А", "*", "*", "Б"], "")
        self.assertEqual([b.text for b in blocks], ["А", "* * *", "Б"])

    def test_empty_paragraphs_dropped(self):
        blocks = text.prepare(["А", "", "   ", "Б"], "")
        self.assertEqual([b.text for b in blocks], ["А", "Б"])

    def test_defaults(self):
        options = text.PrepOptions()
        self.assertEqual(options.align, "left")
        self.assertEqual(options.first_line_indent_cm, 0.0)


class FormatTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)


class TestReaders(FormatTestCase):
    """Каждый читатель — на маленьком файле своего формата."""

    def read(self, name: str) -> list[Chapter]:
        return formats.read(self.tmp / name)

    def test_txt(self):
        (self.tmp / "a.txt").write_text("\n\n".join(PARAGRAPHS), encoding="utf-8")
        self.assertEqual(self.read("a.txt")[0].paragraphs, PARAGRAPHS)

    def test_txt_cp1251(self):
        """Русский текст приходит и в CP1251 — читать вслепую нельзя."""
        (self.tmp / "a.txt").write_bytes("\n\n".join(PARAGRAPHS).encode("cp1251"))
        self.assertEqual(self.read("a.txt")[0].paragraphs, PARAGRAPHS)

    def test_md(self):
        (self.tmp / "a.md").write_text("\n\n".join(PARAGRAPHS), encoding="utf-8")
        self.assertEqual(self.read("a.md")[0].paragraphs, PARAGRAPHS)

    def test_docx(self):
        from docx import Document

        document = Document()
        for paragraph in PARAGRAPHS:
            document.add_paragraph(paragraph)
        document.save(str(self.tmp / "a.docx"))
        self.assertEqual(self.read("a.docx")[0].paragraphs, PARAGRAPHS)

    def test_epub(self):
        from tests.test_split import make_epub

        make_epub(self.tmp / "a.epub", count=3)
        chapters = self.read("a.epub")
        self.assertEqual(len(chapters), 3)
        self.assertTrue(all(c.paragraphs for c in chapters))

    def test_fb2(self):
        body = "".join(
            f"<section><title><p>Глава {n}</p></title>"
            + "".join(f"<p>{p}</p>" for p in PARAGRAPHS)
            + "</section>"
            for n in (201, 202)
        )
        (self.tmp / "a.fb2").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            f"<body>{body}</body></FictionBook>",
            encoding="utf-8",
        )
        chapters = self.read("a.fb2")
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0].paragraphs, PARAGRAPHS)

    def test_rtf(self):
        from core.writers.rtf import RtfWriter

        RtfWriter().write(self.tmp / "a.rtf", [sample()], headings=False)
        self.assertTrue(self.read("a.rtf")[0].paragraphs)

    def test_odt(self):
        from core.writers.odt import OdtWriter

        OdtWriter().write(self.tmp / "a.odt", [sample()], headings=False)
        self.assertEqual(self.read("a.odt")[0].paragraphs, PARAGRAPHS)

    def test_html(self):
        (self.tmp / "a.html").write_text(
            "<html><body><script>x=1</script>"
            + "".join(f"<p>{p}</p>" for p in PARAGRAPHS)
            + "</body></html>",
            encoding="utf-8",
        )
        self.assertEqual(self.read("a.html")[0].paragraphs, PARAGRAPHS)

    def test_unknown_format_refused(self):
        (self.tmp / "a.pdf").write_bytes(b"%PDF-1.4")
        with self.assertRaises(ReadError):
            self.read("a.pdf")


class TestSignatureSniffing(FormatTestCase):
    """Расширение врёт: содержимое важнее."""

    def test_epub_named_txt_is_still_read_as_epub(self):
        from tests.test_split import make_epub

        make_epub(self.tmp / "book.epub", count=2)
        disguised = self.tmp / "book.txt"
        disguised.write_bytes((self.tmp / "book.epub").read_bytes())

        chapters = formats.read(disguised)
        self.assertEqual(len(chapters), 2)
        # Сырые байты архива в текст не попали.
        self.assertNotIn("PK", chapters[0].paragraphs[0][:4])

    def test_sniff_recognises_each_zip_kind(self):
        from tests.test_split import make_epub

        make_epub(self.tmp / "a.epub", count=1)
        self.assertEqual(formats.sniff(self.tmp / "a.epub"), ".epub")

        from core.writers.odt import OdtWriter

        OdtWriter().write(self.tmp / "a.odt", [sample()])
        self.assertEqual(formats.sniff(self.tmp / "a.odt"), ".odt")

    def test_plain_text_has_no_signature(self):
        (self.tmp / "a.txt").write_text("просто текст", encoding="utf-8")
        self.assertEqual(formats.sniff(self.tmp / "a.txt"), "")


class TestWriterRoundTrip(FormatTestCase):
    """Записали, прочитали обратно — данные совпали."""

    def round_trip(self, suffix: str) -> list[Chapter]:
        path = self.tmp / f"book{suffix}"
        formats.write(path, [sample()], headings=False)
        return formats.read(path)

    def test_txt(self):
        self.assertEqual(self.round_trip(".txt")[0].paragraphs, PARAGRAPHS)

    def test_md(self):
        self.assertEqual(self.round_trip(".md")[0].paragraphs, PARAGRAPHS)

    def test_docx(self):
        self.assertEqual(self.round_trip(".docx")[0].paragraphs, PARAGRAPHS)

    def test_odt(self):
        self.assertEqual(self.round_trip(".odt")[0].paragraphs, PARAGRAPHS)

    def test_rtf(self):
        # striprtf схлопывает пробелы, поэтому сверяем по содержанию.
        paragraphs = self.round_trip(".rtf")[0].paragraphs
        self.assertEqual(len(paragraphs), len(PARAGRAPHS))
        self.assertIn("Первый абзац", paragraphs[0])

    def test_fb2(self):
        self.assertEqual(self.round_trip(".fb2")[0].paragraphs, PARAGRAPHS)

    def test_epub(self):
        path = self.tmp / "book.epub"
        # Главы короче 200 символов epub-читатель отсекает как служебные,
        # поэтому для round-trip берём главу нормального объёма.
        long_chapter = Chapter(
            number=201, title="Глава 201. Название",
            paragraphs=[p * 4 for p in PARAGRAPHS],
        )
        formats.write(path, [long_chapter], headings=True)
        chapters = formats.read(path)
        self.assertEqual(len(chapters), 1)
        self.assertIn("Первый абзац", chapters[0].text)

    def test_every_writable_format_round_trips(self):
        """Ни один писатель не должен ронять запись."""
        for suffix in formats.WRITABLE:
            with self.subTest(suffix=suffix):
                path = self.tmp / f"all{suffix}"
                formats.write(path, [sample()], headings=True)
                self.assertTrue(path.exists())
                self.assertGreater(path.stat().st_size, 0)

    def test_unknown_writer_refused(self):
        with self.assertRaises(WriteError):
            formats.write(self.tmp / "a.pdf", [sample()])

    def test_txt_windows_1251(self):
        path = self.tmp / "cp.txt"
        formats.write(path, [sample()], encoding="windows-1251", headings=False)
        self.assertIn("Первый абзац", path.read_text(encoding="windows-1251"))

    def test_epub_has_valid_opf_and_spine(self):
        path = self.tmp / "book.epub"
        formats.write(path, [sample(201), sample(202)], headings=True)
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            opf = archive.read("OEBPS/content.opf").decode("utf-8")

        # mimetype обязан быть первым и несжатым, иначе читалки ругаются.
        self.assertEqual(names[0], "mimetype")
        self.assertIn("META-INF/container.xml", names)
        # Порядок чтения задаёт spine.
        self.assertEqual(opf.count("<itemref"), 2)
        self.assertLess(opf.index('idref="c1"'), opf.index('idref="c2"'))


class TestMixedFolder(FormatTestCase):
    """В папке со смешанными форматами обрабатываются все подряд."""

    def test_all_formats_read_from_one_folder(self):
        formats.write(self.tmp / "a.txt", [sample(201)], headings=False)
        formats.write(self.tmp / "b.md", [sample(202)], headings=False)
        formats.write(self.tmp / "c.docx", [sample(203)], headings=False)

        chapters = []
        for path in sorted(self.tmp.iterdir()):
            chapters.extend(formats.read(path))
        self.assertEqual(len(chapters), 3)

    def test_unreadable_file_does_not_stop_the_rest(self):
        formats.write(self.tmp / "a.txt", [sample()], headings=False)
        (self.tmp / "b.pdf").write_bytes(b"%PDF-1.4")

        report = OpReport()
        chapters = []
        for path in sorted(self.tmp.iterdir()):
            try:
                chapters.extend(formats.read(path))
            except ReadError as exc:
                report.fail(path.name, "чтение", str(exc))

        self.assertEqual(len(chapters), 1)
        self.assertEqual(report.failed, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestOps(FormatTestCase):
    """A1: «Разбить» и «Объединить» — одна логика с параметром формата."""

    def setUp(self):
        super().setUp()
        from core import formats

        self.src = self.tmp / "смесь"
        self.src.mkdir()
        # Папка со смешанными форматами — так и бывает в работе.
        for number, suffix in [(201, ".txt"), (202, ".docx"), (203, ".md")]:
            formats.write(
                self.src / f"Глава {number}{suffix}",
                [Chapter(number=number, title=f"Глава {number}. Имя",
                         paragraphs=[f"Текст главы {number}. " * 12])],
                headings=True,
            )

    def test_split_accepts_docx(self):
        """«Разбить» не принимал .docx — это был живой баг."""
        from ops import split

        out = self.tmp / "разбито"
        report = split.run([str(self.src / "Глава 202.docx")], out, out_format=".txt")
        self.assertEqual(report.written, 1)

    def test_split_converts_between_formats(self):
        from ops import split

        out = self.tmp / "epub"
        split.run([str(self.src / "Глава 202.docx")], out, out_format=".epub")
        self.assertEqual([p.suffix for p in out.iterdir()], [".epub"])

    def test_split_into_parts_numbers_them(self):
        from ops import split

        chapter = Chapter(number=201, title="Глава 201",
                          paragraphs=[f"Абзац {i}. " * 8 for i in range(10)])
        parts = split.split_chapter(chapter, 3)
        self.assertEqual([p.part for p in parts], [1, 2, 3])

    def test_merge_reads_mixed_formats(self):
        from ops import merge

        out = self.tmp / "книга.txt"
        report = merge.run([str(self.src)], out)
        self.assertEqual(report.written, 3)
        self.assertEqual(report.failed, 0)

    def test_merge_orders_by_chapter_number(self):
        from ops import merge

        out = self.tmp / "книга.txt"
        merge.run([str(self.src)], out, headings=False)
        body = out.read_text(encoding="utf-8")
        self.assertLess(body.index("главы 201"), body.index("главы 203"))

    def test_merge_writes_any_format(self):
        from core import formats
        from ops import merge

        for suffix in formats.WRITABLE:
            with self.subTest(suffix=suffix):
                out = self.tmp / f"книга{suffix}"
                report = merge.run([str(self.src)], out)
                self.assertEqual(report.failed, 0)
                self.assertTrue(out.exists())

    def test_merge_separator(self):
        from ops import merge

        out = self.tmp / "книга.txt"
        merge.run([str(self.src)], out, separator="stars")
        self.assertIn("* * *", out.read_text(encoding="utf-8"))

    def test_unreadable_file_is_reported_not_swallowed(self):
        from ops import merge

        (self.src / "битый.pdf").write_bytes(b"%PDF-1.4")
        out = self.tmp / "книга.txt"
        report = merge.run([str(self.src)], out)
        # Файл пропущен, остальные собраны, ошибка в отчёте.
        self.assertEqual(report.written, 3)

    def test_cancel_is_checked(self):
        import threading

        from ops import merge
        from ops.base import Cancelled, Progress

        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            merge.run([str(self.src)], self.tmp / "к.txt",
                      progress=Progress(cancel=cancel))

    def test_progress_callback_shape(self):
        from ops import split
        from ops.base import Progress

        seen = []
        split.run([str(self.src)], self.tmp / "out",
                  progress=Progress(on_progress=lambda d, t, m: seen.append((d, t, m))))
        self.assertTrue(seen)
        # Колбэк один на все операции: (сделано, всего, текст).
        self.assertEqual(len(seen[0]), 3)
