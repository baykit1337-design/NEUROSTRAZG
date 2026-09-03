"""Епаб — в книгу для загрузчика: названия, номера и порядок глав.

Человек положил в «Собрать книгу» свой епаб на четыреста сорок шесть глав
и получил «Глава 3 — "Act 3 is about to begin."», а следом «Глава 122»,
«Глава 123», «Глава 124». Ни таких глав, ни такого порядка в книге не
было.

Сошлось сразу три промаха, и каждый проверяется здесь отдельно:

* названия брались из имён файлов внутри архива — а они служебные;
* номер выкапывался из названия по первой попавшейся цифре;
* книга сортировалась по этим номерам, хотя порядок глав в епабе задан
  корешком и известен точно.
"""

from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import naming  # noqa: E402
from core.models import OpReport  # noqa: E402
from ops import base as base_op  # noqa: E402
from ops import mdbook  # noqa: E402


def body(number: int) -> str:
    """Текст главы. Своей длины: слишком короткая считается служебной
    страницей и в книгу не идёт."""
    return f"<p>{'Текст главы. ' * 40}</p><p>Это глава номер {number}.</p>"


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def epub(self, chapters, toc: str = "nav", name: str = "книга.epub") -> Path:
        """Епаб из пар «название в оглавлении, заголовок внутри главы».

        Заголовка внутри может не быть вовсе — так и приходят целые книги,
        и именно на них всё и сломалось. `toc` выбирает вид оглавления:
        `nav` — страница со ссылками (EPUB3), `ncx` — отдельный файл
        (EPUB2), `none` — оглавления нет совсем.
        """
        files, items, spine, links, points = {}, [], [], [], []

        for at, (listed, heading) in enumerate(chapters, 1):
            inside = f"<h1>{heading}</h1>" if heading else ""
            files[f"OEBPS/{at:04d}.xhtml"] = (
                f"<html><body>{inside}{body(at)}</body></html>")
            items.append(f'<item id="c{at}" href="{at:04d}.xhtml"'
                         ' media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="c{at}"/>')
            links.append(f'<li><a href="{at:04d}.xhtml">{listed}</a></li>')
            points.append(
                f'<navPoint id="n{at}"><navLabel><text>{listed}</text></navLabel>'
                f'<content src="{at:04d}.xhtml"/></navPoint>')

        extra, attr = "", ""
        if toc == "nav":
            files["OEBPS/nav.xhtml"] = (
                "<html><body><nav><ol>" + "".join(links) + "</ol></nav></body></html>")
            extra = ('<item id="nav" href="nav.xhtml"'
                     ' media-type="application/xhtml+xml" properties="nav"/>')
        elif toc == "ncx":
            files["OEBPS/toc.ncx"] = (
                "<?xml version='1.0'?>"
                "<ncx xmlns='http://www.daisy.org/z3986/2005/ncx/'><navMap>"
                + "".join(points) + "</navMap></ncx>")
            extra = ('<item id="ncx" href="toc.ncx"'
                     ' media-type="application/x-dtbncx+xml"/>')
            attr = ' toc="ncx"'

        files["OEBPS/content.opf"] = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf"><metadata/>'
            f'<manifest>{"".join(items)}{extra}</manifest>'
            f'<spine{attr}>{"".join(spine)}</spine></package>')
        files["META-INF/container.xml"] = (
            "<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
            "<rootfiles><rootfile full-path='OEBPS/content.opf'/>"
            "</rootfiles></container>")

        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as archive:
            for where, text in files.items():
                archive.writestr(where, text)
        return path

    def read(self, path: Path):
        return base_op.in_reading_order(base_op.read_all([path], OpReport()))

    def headings(self, path: Path, **kw) -> list[str]:
        """Заголовки, какими они лягут в готовый .md."""
        made = mdbook.from_chapters(self.read(path), **kw)
        return [head.title for head, _ in made]


class TestTheNumberInATitleIsNotAlwaysAChapter(unittest.TestCase):
    """Имя файла человек даёт сам, и цифра в нём — почти всегда номер
    главы. Заголовок внутри книги пишет чужая программа, и цифра там чаще
    всего часть названия."""

    def test_a_number_in_the_middle_of_a_sentence_is_not_a_chapter(self):
        self.assertIsNone(
            naming.parse_title('"Act 3 is about to begin."').number)

    def test_a_real_heading_still_gives_its_number(self):
        for text, number in [("Глава 561 — Начало", 561),
                             ("Chapter 122: Something", 122),
                             ("561. Название", 561),
                             ("第 244 章 标题", 244)]:
            with self.subTest(text):
                self.assertEqual(naming.parse_title(text).number, number)

    def test_the_part_comes_along_with_the_number(self):
        found = naming.parse_title("Глава 201.2 — Название")
        self.assertEqual((found.number, found.part), (201, 2))

    def test_a_word_that_is_not_about_chapters_cancels_the_number(self):
        """«Том 3» — это том, а не третья глава."""
        self.assertIsNone(naming.parse_title("Том 3. Глава 12").number)

    def test_the_name_survives_even_without_a_number(self):
        """Иначе глава осталась бы вовсе без названия."""
        found = naming.parse_title('"Act 3 is about to begin."')
        self.assertEqual(found.title, '"Act 3 is about to begin."')

    def test_file_names_are_still_read_the_loose_way(self):
        """Строгость нужна заголовкам, а не именам файлов: там первая
        цифра — это номер, и так было всегда."""
        self.assertEqual(naming.parse("0122 Начало").number, 122)


class TestTheNamesComeFromTheBook(Base):
    """Название главы лежит в епабе в двух местах, и в разных книгах
    заполнено то одно, то другое."""

    def test_a_book_without_headings_inside_is_named_by_its_toc(self):
        """Ради этого всё и затевалось: имена файлов внутри архива
        служебные, и «Глава 122» — это номер файла, а не главы."""
        book = self.epub([(f"Глава {n}", "") for n in range(561, 566)])
        self.assertEqual(self.headings(book),
                         [f"Глава {n}" for n in range(561, 566)])

    def test_an_old_style_toc_works_the_same(self):
        book = self.epub([(f"Глава {n}", "") for n in range(561, 566)],
                         toc="ncx")
        self.assertEqual(self.headings(book),
                         [f"Глава {n}" for n in range(561, 566)])

    def test_a_heading_inside_the_chapter_wins(self):
        """Его писал тот же, кто писал главу; оглавление бывает и на
        уровне томов.

        Заголовок в главе записан своим разделителем, а книга собирается
        общим: по нему и видно, что название прошло через разбор, а не
        просто скопировалось.
        """
        book = self.epub([("Оглавление врёт", "Глава 561: Начало")])
        self.assertEqual(self.headings(book), ["Глава 561 — Начало"])

    def test_without_any_toc_nothing_falls_apart(self):
        """Название взять неоткуда — но книга всё равно собирается, и
        порядок глав в ней прежний."""
        book = self.epub([("", "") for _ in range(3)], toc="none")
        self.assertEqual(len(self.headings(book)), 3)


class TestTheOrderIsTheBooksOwn(Base):
    """Порядок глав в епабе задан корешком и известен точно."""

    def test_a_chapter_without_a_number_stays_in_its_place(self):
        """Прежде она уезжала в самый конец: сортировка ставила главы без
        номера после всех пронумерованных."""
        book = self.epub([("Глава 561", ""),
                          ("Глава 562", '"Act 3 is about to begin."'),
                          ("Глава 563", "")])
        self.assertEqual(
            self.headings(book),
            ["Глава 561", '"Act 3 is about to begin."', "Глава 563"])

    def test_numbers_going_backwards_do_not_reshuffle_the_book(self):
        """Книга бывает и с прологом под номером 900, и с интерлюдией под
        первым: корешок знает, где им место, а числа — нет."""
        book = self.epub([("Глава 900", ""), ("Глава 1", ""), ("Глава 2", "")])
        self.assertEqual(self.headings(book),
                         ["Глава 900", "Глава 1", "Глава 2"])

    def test_files_with_one_chapter_each_are_still_sorted_by_number(self):
        """В папке они лежат по именам, где «Глава 10» встаёт перед
        «Главой 2», — эту сортировку отбирать было нельзя."""
        folder = self.tmp / "главы"
        folder.mkdir()
        for number in (2, 10, 1):
            (folder / f"Глава {number}.txt").write_text(
                f"Текст главы {number}.", encoding="utf-8")

        chapters = base_op.in_reading_order(
            base_op.read_all(sorted(folder.iterdir()), OpReport()))
        self.assertEqual([c.number for c in chapters], [1, 2, 10])


class TestNoNumberIsInvented(Base):
    """Сборка книги докапывалась до номера сама, уже после читалки."""

    def test_a_chapter_whose_title_is_a_sentence_gets_no_number(self):
        book = self.epub([("Глава 561", '"Act 3 is about to begin."')])
        self.assertEqual(self.headings(book), ['"Act 3 is about to begin."'])

    def test_the_order_field_is_still_written_in_a_row(self):
        """Номера главам не досталось — а порядок для сайта всё равно
        должен идти подряд."""
        book = self.epub([("Глава 561", "Первая"), ("Глава 562", "Вторая")])
        made = mdbook.from_chapters(self.read(book), first=1)
        self.assertEqual([head.order for head, _ in made], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
