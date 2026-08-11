"""Тесты вкладки «Разбить книгу».

Тестовые epub собираются на лету — так проверка не зависит от того, какие
файлы лежат рядом.
"""

from __future__ import annotations

import sys
import threading
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import booksplit  # noqa: E402
from mvl.word import Style, split_paragraphs  # noqa: E402

LONG = "Строка текста этой главы, достаточно длинная, чтобы пройти отсечку. " * 5


def make_epub(path: Path, count: int = 3, with_cover: bool = True) -> Path:
    """Минимальный, но настоящий epub: container.xml, OPF, manifest, spine."""
    items, refs, files = [], [], {}

    if with_cover:
        # Служебная страница: короткая, должна отсечься по длине.
        files["OEBPS/cover.xhtml"] = "<html><body><p>Обложка</p></body></html>"
        items.append('<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
        refs.append('<itemref idref="cover"/>')

    for n in range(1, count + 1):
        body = "".join(f"<p>Абзац {i}. {LONG}</p>" for i in range(1, 4))
        files[f"OEBPS/ch{n}.xhtml"] = (
            f"<html><body><h1>Глава {n}: Название</h1>{body}"
            f"<p>*</p><p>После разделителя. {LONG}</p></body></html>"
        )
        items.append(f'<item id="c{n}" href="ch{n}.xhtml" media-type="application/xhtml+xml"/>')
        refs.append(f'<itemref idref="c{n}"/>')

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>',
        )
        for name, content in files.items():
            archive.writestr(name, content)
        archive.writestr(
            "OEBPS/book.opf",
            f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf">'
            f'<manifest>{"".join(items)}</manifest><spine>{"".join(refs)}</spine></package>',
        )
    return path


def make_txt(path: Path, count: int = 3) -> Path:
    parts = ["Предисловие, которое не должно стать главой.\n"]
    for n in range(1, count + 1):
        parts.append(f"Глава {n}. Название\n\n{LONG}\n\n*\n\nПосле разделителя.\n")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


class SplitTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)
        self.epub = make_epub(self.tmp / "book.epub")
        self.txt = make_txt(self.tmp / "book.txt")


class TestReadChapters(SplitTestCase):
    def test_epub_chapters_in_reading_order(self):
        chapters = booksplit.read_chapters(self.epub)
        self.assertEqual([c.title for c in chapters],
                         ["Глава 1: Название", "Глава 2: Название", "Глава 3: Название"])

    def test_cover_page_filtered_out(self):
        # Обложка короче 200 символов — в главы не попадает.
        self.assertEqual(len(booksplit.read_chapters(self.epub)), 3)

    def test_scene_separator_kept(self):
        text = booksplit.read_chapters(self.epub)[0].text
        self.assertIn("\n\n*\n\n", text)

    def test_txt_chapters(self):
        chapters = booksplit.read_chapters(self.txt)
        self.assertEqual([c.title for c in chapters],
                         ["Глава 1. Название", "Глава 2. Название", "Глава 3. Название"])

    def test_txt_scene_separator_kept(self):
        self.assertIn("\n*\n", booksplit.read_chapters(self.txt)[0].text)

    def test_custom_pattern(self):
        path = self.tmp / "custom.txt"
        path.write_text(f"### 1 Первая\n\n{LONG}\n\n### 2 Вторая\n\n{LONG}\n", encoding="utf-8")
        chapters = booksplit.read_chapters(path, pattern=r"^###\s+\d+.*$")
        self.assertEqual(len(chapters), 2)

    def test_missing_headings_raises_with_pattern(self):
        path = self.tmp / "flat.txt"
        path.write_text("Текст без единого заголовка главы.\n", encoding="utf-8")
        with self.assertRaises(booksplit.HeadingsNotFound) as ctx:
            booksplit.read_chapters(path)
        self.assertEqual(ctx.exception.pattern, booksplit.DEFAULT_PATTERN)

    def test_missing_file_raises_split_error(self):
        with self.assertRaises(booksplit.SplitError):
            booksplit.read_chapters(self.tmp / "nope.epub")

    def test_unknown_extension_rejected(self):
        path = self.tmp / "book.pdf"
        path.write_text("x", encoding="utf-8")
        with self.assertRaises(booksplit.SplitError):
            booksplit.read_chapters(path)

    def test_broken_epub_does_not_raise_systemexit(self):
        """SystemExit из split_book не должен всплывать в сервер."""
        path = self.tmp / "broken.epub"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("nothing.txt", "не epub вовсе")
        with self.assertRaises(booksplit.SplitError):
            booksplit.read_chapters(path)


class TestPreview(SplitTestCase):
    def test_preview_counts_and_first_titles(self):
        preview = booksplit.preview(self.epub)
        self.assertEqual(preview.total, 3)
        self.assertEqual(preview.titles[0], "Глава 1: Название")
        self.assertEqual(preview.kind, "epub")

    def test_preview_caps_titles_at_five(self):
        big = make_epub(self.tmp / "big.epub", count=9)
        self.assertEqual(len(booksplit.preview(big).titles), 5)

    def test_preview_writes_nothing(self):
        before = set(self.tmp.iterdir())
        booksplit.preview(self.epub)
        self.assertEqual(set(self.tmp.iterdir()), before)


class TestWriteChapters(SplitTestCase):
    def test_txt_filenames_zero_padded(self):
        out = self.tmp / "out"
        booksplit.split_book_to_dir(self.epub, out)
        self.assertEqual(
            sorted(p.name for p in out.glob("*.txt")),
            ["0001 - Глава 1 Название.txt",
             "0002 - Глава 2 Название.txt",
             "0003 - Глава 3 Название.txt"],
        )

    def test_width_grows_with_chapter_count(self):
        self.assertEqual(booksplit.name_width(3), 4)
        self.assertEqual(booksplit.name_width(9999), 4)
        self.assertEqual(booksplit.name_width(10000), 5)

    def test_file_starts_with_title_then_blank_line(self):
        out = self.tmp / "out"
        booksplit.split_book_to_dir(self.epub, out)
        lines = (out / "0001 - Глава 1 Название.txt").read_text(encoding="utf-8").split("\n")
        self.assertEqual(lines[0], "Глава 1: Название")
        self.assertEqual(lines[1], "")

    def test_scene_separator_survives_the_write(self):
        out = self.tmp / "out"
        booksplit.split_book_to_dir(self.epub, out)
        body = (out / "0001 - Глава 1 Название.txt").read_text(encoding="utf-8")
        self.assertIn("\n\n*\n\n", body)

    def test_report_counts(self):
        report = booksplit.split_book_to_dir(self.epub, self.tmp / "out")
        self.assertEqual((report.written, report.failed, report.total), (3, 0, 3))

    def test_docx_output(self):
        out = self.tmp / "docx"
        report = booksplit.split_book_to_dir(self.epub, out, fmt=booksplit.FORMAT_DOCX)
        self.assertEqual(report.written, 3)
        self.assertEqual(len(list(out.glob("*.docx"))), 3)

    def test_docx_has_heading_and_paragraphs(self):
        from docx import Document

        out = self.tmp / "docx"
        booksplit.split_book_to_dir(self.epub, out, fmt=booksplit.FORMAT_DOCX)
        document = Document(str(sorted(out.glob("*.docx"))[0]))
        texts = [p.text for p in document.paragraphs if p.text.strip()]
        self.assertEqual(texts[0], "Глава 1: Название")
        self.assertIn("*", texts)  # разделитель сцен на месте

    def test_docx_applies_style(self):
        from docx import Document

        out = self.tmp / "styled"
        booksplit.split_book_to_dir(
            self.epub, out, fmt=booksplit.FORMAT_DOCX, style=Style(font="Arial", size=14)
        )
        document = Document(str(sorted(out.glob("*.docx"))[0]))
        self.assertEqual(document.styles["Normal"].font.name, "Arial")

    def test_bad_chapter_does_not_stop_the_rest(self):
        """Ошибка на одной главе — пропуск с записью в отчёт, остальные пишутся."""
        out = self.tmp / "partial"
        out.mkdir()
        chapters = booksplit.read_chapters(self.epub)
        chapters[1] = booksplit.Chapter(title="Плохая", text="текст")
        # Занимаем имя второй главы папкой — запись в неё не пройдёт.
        (out / "0002 - Плохая.txt").mkdir()

        report = booksplit.write_chapters(chapters, out)
        self.assertEqual(report.written, 2)
        self.assertEqual(report.failed, 1)
        self.assertTrue(report.failed_files[0].startswith("0002 - Плохая.txt"))
        # Первая и третья главы записались, несмотря на сбой второй.
        self.assertTrue((out / "0001 - Глава 1 Название.txt").is_file())
        self.assertTrue((out / "0003 - Глава 3 Название.txt").is_file())

    def test_cancel_stops_writing(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(booksplit.Cancelled):
            booksplit.split_book_to_dir(self.epub, self.tmp / "cancelled", cancel=cancel)

    def test_progress_reported(self):
        seen = []
        booksplit.split_book_to_dir(
            self.epub, self.tmp / "out", on_progress=lambda d, t: seen.append((d, t))
        )
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_forbidden_characters_stripped_from_names(self):
        chapters = [booksplit.Chapter(title='Гл 1: A/B "х" <тег>?', text="текст")]
        booksplit.write_chapters(chapters, self.tmp / "names")
        name = next((self.tmp / "names").glob("*.txt")).name
        for char in '\\/:*?"<>|':
            self.assertNotIn(char, name)


class TestWordHelpers(unittest.TestCase):
    def test_split_paragraphs(self):
        self.assertEqual(split_paragraphs("a\n\nb\n\n\nc"), ["a", "b", "c"])

    def test_split_paragraphs_empty(self):
        self.assertEqual(split_paragraphs(""), [])

    def test_style_defaults_from_spec(self):
        style = Style()
        self.assertEqual(style.font, "Times New Roman")
        self.assertEqual(style.size, 12)
        self.assertEqual(style.line_spacing, 1.5)
        self.assertEqual(style.first_line_indent_cm, 1.25)

    def test_style_from_dict_ignores_junk(self):
        style = Style.from_dict({"font": "Arial", "size": "abc", "line_spacing": 0})
        self.assertEqual(style.font, "Arial")
        self.assertEqual(style.size, 12)
        self.assertEqual(style.line_spacing, 1.5)


class TestSplitWebApi(SplitTestCase):
    def setUp(self):
        super().setUp()
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()

    def test_preview_endpoint(self):
        res = self.app.post("/api/split/preview", json={"path": str(self.epub)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["preview"]["total"], 3)

    def test_preview_requires_path(self):
        self.assertEqual(self.app.post("/api/split/preview", json={}).status_code, 400)

    def test_preview_missing_headings_asks_for_pattern(self):
        flat = self.tmp / "flat.txt"
        flat.write_text("Ни одного заголовка.\n", encoding="utf-8")
        res = self.app.post("/api/split/preview", json={"path": str(flat)})
        self.assertEqual(res.status_code, 422)
        body = res.get_json()
        self.assertTrue(body["need_pattern"])
        self.assertEqual(body["pattern"], booksplit.DEFAULT_PATTERN)

    def test_browse_lists_book_files(self):
        data = self.app.get(
            "/api/browse", query_string={"path": str(self.tmp), "files": "epub,txt"}
        ).get_json()
        names = [f["name"] for f in data["files"]]
        self.assertIn("book.epub", names)
        self.assertIn("book.txt", names)

    def test_browse_hides_files_without_filter(self):
        data = self.app.get("/api/browse", query_string={"path": str(self.tmp)}).get_json()
        self.assertEqual(data["files"], [])

    def test_start_requires_folder(self):
        res = self.app.post(
            "/api/split/start",
            json={"path": str(self.epub), "base": str(self.tmp), "folder": ""},
        )
        self.assertEqual(res.status_code, 400)

    def test_start_rejects_unknown_format(self):
        res = self.app.post(
            "/api/split/start",
            json={"path": str(self.epub), "base": str(self.tmp), "folder": "x", "format": "pdf"},
        )
        self.assertEqual(res.status_code, 400)

    def test_start_does_not_create_folder_on_bad_book(self):
        flat = self.tmp / "flat.txt"
        flat.write_text("Ни одного заголовка.\n", encoding="utf-8")
        res = self.app.post(
            "/api/split/start",
            json={"path": str(flat), "base": str(self.tmp), "folder": "should-not-exist"},
        )
        self.assertEqual(res.status_code, 422)
        self.assertFalse((self.tmp / "should-not-exist").exists())

    def test_full_split_job(self):
        from webapp.app import JOBS

        res = self.app.post(
            "/api/split/start",
            json={"path": str(self.epub), "base": str(self.tmp), "folder": "Книга",
                  "format": "txt"},
        )
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["job"]["id"]
        JOBS[job_id].thread.join(timeout=60)

        job = self.app.get(f"/api/job/{job_id}").get_json()["job"]
        self.assertIsNone(job["error"])
        self.assertEqual(job["progress"]["stage"], "done")
        self.assertEqual(job["report"]["written"], 3)
        self.assertEqual(len(list((self.tmp / "Книга").glob("*.txt"))), 3)

    def test_full_split_job_docx(self):
        from webapp.app import JOBS

        res = self.app.post(
            "/api/split/start",
            json={"path": str(self.epub), "base": str(self.tmp), "folder": "Word",
                  "format": "docx"},
        )
        job_id = res.get_json()["job"]["id"]
        JOBS[job_id].thread.join(timeout=60)
        self.assertEqual(len(list((self.tmp / "Word").glob("*.docx"))), 3)

    def test_job_snapshot_has_kind(self):
        from webapp.app import JOBS

        res = self.app.post(
            "/api/split/start",
            json={"path": str(self.epub), "base": str(self.tmp), "folder": "K"},
        )
        job_id = res.get_json()["job"]["id"]
        # Дожидаемся потока: иначе он пишет в папку, которую уже убрал tearDown.
        JOBS[job_id].thread.join(timeout=60)
        self.assertEqual(res.get_json()["job"]["kind"], "split")


if __name__ == "__main__":
    unittest.main(verbosity=2)
