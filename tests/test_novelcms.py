"""Сайты-сливы: книга лежит открыто, вставил ссылку — качаем.

Заготовки повторяют то, что записано в разборщиках `WebToEpub`
(GPL-3.0) для этих сайтов: полный список глав по адресу `/{код}/dir`, у
`novel543` он вторым списком в `div.chaplist`, у `timotxt` — в `ul.all`;
текст главы в `.chapter-content`; продолжение главы отличается от
следующей главы по адресу файла.

Сайты из окружения разработки недоступны, поэтому проверяется разбор, а
не сеть: клиент подставляется тестом.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.api import Chapter  # noqa: E402
from net import sources  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402
from net.sources.novelcms import NovelCmsSource, rule_for  # noqa: E402

BOOK = "https://www.novel543.com/0407653271/"
TIMO = "https://www.timotxt.com/2005553271/"


def book_page(cover=True) -> str:
    """Страница книги: шапка с автором и обложкой."""
    picture = ('<div class="cover"><img src="/thumb/0407653271.jpg"></div>'
               if cover else "")
    return f"""<html><head><title>Книга про время - 稷下書院</title></head>
      <body><section id="detail">
        {picture}
        <h1 class="title">Книга про время</h1>
        <span class="author">六個葫蘆</span>
      </section></body></html>"""


def dir_page(site="novel543", count=10) -> str:
    """Полный список глав — страница `/dir`.

    У `novel543` списков два: первый с последними главами, второй со
    всеми. У `timotxt` он один и помечен классом.
    """
    def items(low, high, prefix="8096_"):
        return "".join(
            f'<li><a href="/0407653271/{prefix}{n}.html">第{n}章 Глава {n}</a></li>'
            for n in range(low, high))

    if site == "novel543":
        return (f'<html><body><div class="chaplist">'
                f'<ul class="latest">{items(1000 + count - 3, 1000 + count)}</ul>'
                f'<ul class="all">{items(1000, 1000 + count)}</ul>'
                f"</div></body></html>")
    return (f'<html><body><div class="chaplist">'
            f'<ul class="all">{items(1000, 1000 + count, prefix="")}</ul>'
            f"</div></body></html>")


def chapter_page(part=1, of=1, base="8096_1000") -> str:
    """Страница главы: заголовок, реклама внутри текста и подвал.

    Последняя ссылка подвала ведёт либо на продолжение той же главы,
    либо уже на следующую — по адресу их и различаем.
    """
    following = (f"/0407653271/{base}_{part + 1}.html" if part < of
                 else "/0407653271/8096_1001.html")
    mark = f" ({part}/{of})" if of > 1 else ""
    return f"""<html><body id="read"><div class="container">
      <div id="chapterWarp" class="warp">
        <div class="chapter-content px-3">
          <h1 class="title">第1000章 Глубина{mark}</h1>
          <div class="content">
            <div class="gadBlock" data-ad="onead-banner_1">реклама</div>
            <script type="text/javascript">var x = 1;</script>
            <p>第1000章 Глубина</p>
            <p>Абзац {part} первый.</p>
            <p>Абзац {part} второй.</p>
          </div>
        </div>
        <div class="foot-nav">
          <a href="/0407653271/8096_999.html">上一章</a>
          <a href="/0407653271/dir">目錄</a>
          <a href="{following}">下一頁</a>
        </div>
      </div></div></body></html>"""


class FakeClient:
    """Отдаёт заготовку по совпадению куска адреса. Порядок важен."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.asked: list[str] = []

    def get_text(self, url, params=None, headers=None):
        self.asked.append(url)
        for part, answer in self.pages.items():
            if part in url:
                return answer
        raise AssertionError(f"Нет заготовки для {url}")


class Base(unittest.TestCase):
    def setUp(self):
        self.source = NovelCmsSource()

    def client(self, site="novel543"):
        return FakeClient({"/dir": dir_page(site), "/0407653271/": book_page(),
                           "/2005553271/": book_page()})


class TestItIsOfferedAsItsOwnSource(unittest.TestCase):
    def test_the_source_is_in_the_list(self):
        self.assertIn("novelcms", [s.key for s in sources.all_sources()])

    def test_it_is_not_the_default(self):
        """Сайт сторонний и живёт своей жизнью — выбирается руками."""
        self.assertNotEqual(sources.get("").key, "novelcms")

    def test_the_hint_shows_what_to_paste(self):
        source = sources.get("novelcms")
        self.assertIn("novel543.com", source.hint + source.placeholder)

    def test_it_needs_no_proxy(self):
        """Сайты открытые: гнать их через китайские прокси незачем."""
        self.assertFalse(sources.get("novelcms").needs_proxy)


class TestTheSiteIsRecognised(Base):
    def test_both_sites_are_known(self):
        self.assertEqual(rule_for(BOOK).name, "novel543")
        self.assertEqual(rule_for(TIMO).name, "timotxt")

    def test_the_second_address_of_the_same_engine_counts(self):
        """У движка два адреса — так записано в разборщике WebToEpub."""
        self.assertEqual(rule_for("https://twbook.cc/123/").name, "novel543")

    def test_a_stranger_site_is_not_ours(self):
        self.assertIsNone(rule_for("https://example.com/1234/"))

    def test_the_code_comes_from_the_address(self):
        self.assertEqual(self.source.code_of(BOOK), "0407653271")

    def test_the_leading_zero_is_not_lost(self):
        """`0407653271` числом стал бы другим адресом."""
        novel = self.source.find(self.client(), BOOK)
        self.assertIn("0407653271", novel.slug)

    def test_a_stranger_site_is_refused_by_name(self):
        with self.assertRaises(SourceBroken) as caught:
            self.source.find(FakeClient({}), "https://example.com/1234/")
        self.assertIn("novel543.com", str(caught.exception))

    def test_a_bare_code_is_not_enough(self):
        """Код у каждого сайта свой — без адреса непонятно, куда идти."""
        with self.assertRaises(SourceBroken):
            self.source.find(FakeClient({}), "0407653271")


class TestTheBook(Base):
    def test_the_name_and_the_author_are_read(self):
        novel = self.source.find(self.client(), BOOK)
        self.assertEqual(novel.name, "Книга про время")
        self.assertEqual(novel.author, "六個葫蘆")

    def test_the_cover_comes_back_as_a_full_address(self):
        novel = self.source.find(self.client(), BOOK)
        self.assertEqual(novel.cover,
                         "https://www.novel543.com/thumb/0407653271.jpg")

    def test_the_whole_list_is_taken_from_the_dir_page(self):
        """Страница книги показывает только последние главы."""
        client = self.client()
        novel = self.source.find(client, BOOK)

        self.assertEqual(novel.total_chapters, 10)
        self.assertTrue(any(url.endswith("/dir") for url in client.asked))

    def test_the_second_list_is_the_full_one(self):
        """Первый список на странице — последние главы, а нужен весь."""
        rows = self.source.toc(self.client(),
                               self.source.find(self.client(), BOOK)).chapters
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0].number, 1000)


class TestTheChapterList(Base):
    def rows(self, site="novel543", **kwargs):
        client = self.client(site)
        address = BOOK if site == "novel543" else TIMO
        novel = self.source.find(client, address)
        return self.source.toc(client, novel, **kwargs).chapters

    def test_numbers_come_from_the_titles(self):
        rows = self.rows()
        self.assertEqual(rows[0].number, 1000)
        self.assertEqual(rows[-1].number, 1009)

    def test_the_other_site_is_read_by_its_own_rule(self):
        """У `timotxt` список один и помечен классом."""
        rows = self.rows("timotxt")
        self.assertEqual(len(rows), 10)

    def test_every_chapter_keeps_its_own_address(self):
        for row in self.rows():
            with self.subTest(number=row.number):
                self.assertTrue(row.link.startswith("https://www.novel543.com/"))

    def test_the_range_is_honoured(self):
        rows = self.rows(first=1002, last=1004)
        self.assertEqual([r.number for r in rows], [1002, 1003, 1004])

    def test_a_page_without_a_list_says_the_source_changed(self):
        client = FakeClient({"/dir": "<html><body>пусто</body></html>",
                             "/0407653271/": book_page()})
        novel = self.source.find(self.client(), BOOK)
        with self.assertRaises(SourceBroken):
            self.source.toc(client, novel)


class TestTheChapterText(Base):
    def chapter(self):
        return Chapter(number=1000, ch_name="第1000章",
                       link="https://www.novel543.com/0407653271/8096_1000.html")

    def test_the_paragraphs_come_back(self):
        client = FakeClient({"8096_1000": chapter_page()})
        title, text = self.source.chapter(client, self.chapter())

        self.assertIn("第1000章", title)
        self.assertIn("Абзац 1 первый.", text)
        self.assertIn("Абзац 1 второй.", text)

    def test_the_adverts_inside_the_text_are_dropped(self):
        client = FakeClient({"8096_1000": chapter_page()})
        _, text = self.source.chapter(client, self.chapter())

        self.assertNotIn("реклама", text)
        self.assertNotIn("var x", text)

    def test_the_title_is_not_repeated_by_the_first_line(self):
        """Иначе название главы окажется в файле дважды."""
        client = FakeClient({"8096_1000": chapter_page()})
        _, text = self.source.chapter(client, self.chapter())
        self.assertFalse(text.startswith("第1000章 Глубина\n"))

    def test_a_chapter_split_across_pages_is_collected_whole(self):
        """«(1/2)» в заголовке — это одна глава на двух страницах."""
        client = FakeClient({
            "8096_1000_2": chapter_page(part=2, of=2),
            "8096_1000": chapter_page(part=1, of=2),
        })
        _, text = self.source.chapter(client, self.chapter())

        self.assertIn("Абзац 1 первый.", text)
        self.assertIn("Абзац 2 первый.", text)

    def test_the_page_number_is_not_kept_in_the_title(self):
        client = FakeClient({
            "8096_1000_2": chapter_page(part=2, of=2),
            "8096_1000": chapter_page(part=1, of=2),
        })
        title, _ = self.source.chapter(client, self.chapter())
        self.assertNotIn("1/2", title)

    def test_the_next_chapter_is_not_mistaken_for_the_next_page(self):
        """Продолжение — «8096_1000_2», следующая глава — «8096_1001».

        Не различить их значит склеить главы и собрать книгу с дырами.
        """
        client = FakeClient({"8096_1000": chapter_page(part=1, of=1)})
        _, text = self.source.chapter(client, self.chapter())

        self.assertNotIn("Абзац 2", text)
        self.assertEqual(len(client.asked), 1)

    def test_a_site_without_paging_is_not_walked(self):
        """У `timotxt` глав по страницам нет — ходить некуда."""
        client = FakeClient({"1000.html": chapter_page(part=1, of=2)})
        self.source.chapter(client, Chapter(
            number=1000,
            link="https://www.timotxt.com/2005553271/1000.html"))
        self.assertEqual(len(client.asked), 1)

    def test_a_chapter_without_an_address_is_refused(self):
        with self.assertRaises(SourceBroken):
            self.source.chapter(FakeClient({}), Chapter(number=1))

    def test_a_page_without_text_says_the_source_changed(self):
        client = FakeClient({"8096_1000": "<html><body>ничего</body></html>"})
        with self.assertRaises(SourceBroken):
            self.source.chapter(client, self.chapter())


if __name__ == "__main__":
    unittest.main()
