"""Сайты-сливы: книга лежит открыто, вставил ссылку — качаем.

Разметка в заготовках повторяет живые страницы `novel543.com` и
`timotxt.com`: список глав в `.chaplist`, текст главы в
`#chapterWarp .chapter-content .content` обычными `<p>`, рядом рекламные
блоки. Движок у сайтов один, поэтому правило разбора тоже одно.

Сами сайты из окружения разработки недоступны, поэтому здесь проверяется
разбор, а не сеть: клиент подставляется тестом.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.api import Chapter  # noqa: E402
from net import sources  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402
from net.sources.novelcms import NovelCmsSource  # noqa: E402

BOOK = "https://www.novel543.com/0407653271/"


def book_page(rows=3, more=True) -> str:
    """Страница книги: шапка и список последних глав."""
    items = "".join(
        f'<li><a rel="nofollow" title="кн" href="/0407653271/8096_{1060 + n}.html">'
        f'第{1060 + n}章 Название {n}</a></li>'
        for n in range(rows)
    )
    tail = ('<div class="more"><a href="/0407653271/all.html">查看全部</a></div>'
            if more else "")
    return f"""<html><head><title>Книга - 稷下書院</title></head>
      <body class="topline"><div class="container px-3"><div class="row">
      <div class="col"><section id="detail">
        <div class="media"><h1>Книга про время</h1></div>
        <div>作者： 六個葫蘆</div><div>分類： 都市</div>
        <div class="chaplist"><div class="header"></div>
          <ul class="flex one two-800">{items}</ul>
        </div>{tail}
      </section></div></div></div></body></html>"""


def whole_list() -> str:
    """Полный список глав — за ссылкой «查看全部»."""
    items = "".join(
        f'<li><a href="/0407653271/8096_{1000 + n}.html">第{1000 + n}章 Гл {n}</a></li>'
        for n in range(10)
    )
    return ('<html><body><div class="chaplist"><ul>'
            + items + "</ul></div></body></html>")


def chapter_page(part=1, of=1, following=True) -> str:
    """Страница главы: заголовок, реклама внутри текста и абзацы."""
    nextlink = ('<a href="/0407653271/8096_1056_2.html">下一頁</a>'
                if following and part < of else
                '<a href="/0407653271/8096_1057.html">下一章</a>')
    mark = f" ({part}/{of})" if of > 1 else ""
    return f"""<html><body id="read" class="yellow"><div class="container">
      <div id="chapterWarp" class="warp mb-5">
        <div class="header px-3">{nextlink}</div>
        <div class="chapter-content px-3">
          <h1>第1056章 深淵中分拳{mark}</h1>
          <div class="content py-5">
            <div class="gadBlock" data-ad="onead-banner_1">реклама</div>
            <div id="div-onead-nd-02"></div>
            <script type="text/javascript">var x = 1;</script>
            <p>Абзац {part} первый.</p>
            <p>Абзац {part} второй.</p>
          </div>
        </div>
      </div></div></body></html>"""


class FakeClient:
    """Отдаёт заготовку по совпадению куска адреса."""

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


class TestTheAddressIsRead(Base):
    def test_the_code_comes_from_the_address(self):
        self.assertEqual(self.source.code_of(BOOK), "0407653271")

    def test_the_leading_zero_is_not_lost(self):
        """`0407653271` числом стал бы другим адресом."""
        client = FakeClient({"/0407653271/": book_page()})
        novel = self.source.find(client, BOOK)
        self.assertIn("0407653271", novel.slug)

    def test_the_other_site_works_the_same(self):
        """Движок один — правило одно."""
        other = "https://www.timotxt.com/2005553271/"
        self.assertEqual(self.source.code_of(other), "2005553271")

    def test_a_stranger_site_is_refused_by_name(self):
        with self.assertRaises(SourceBroken) as caught:
            self.source.find(FakeClient({}), "https://example.com/1234/")
        self.assertIn("novel543.com", str(caught.exception))

    def test_a_bare_code_is_not_enough(self):
        """Код у каждого сайта свой — без адреса непонятно, куда идти."""
        with self.assertRaises(SourceBroken):
            self.source.find(FakeClient({}), "0407653271")


class TestTheBook(Base):
    def setUp(self):
        super().setUp()
        self.client = FakeClient({"all.html": whole_list(),
                                  "/0407653271/": book_page()})

    def test_the_name_and_the_author_are_read(self):
        novel = self.source.find(self.client, BOOK)
        self.assertEqual(novel.name, "Книга про время")
        self.assertEqual(novel.author, "六個葫蘆")

    def test_the_whole_list_is_followed_not_guessed(self):
        """На странице книги только последние главы, всё — за ссылкой."""
        novel = self.source.find(self.client, BOOK)
        self.assertEqual(novel.total_chapters, 10)
        self.assertTrue(any("all.html" in url for url in self.client.asked))

    def test_without_that_link_what_there_is_still_counts(self):
        client = FakeClient({"/0407653271/": book_page(more=False)})
        self.assertEqual(self.source.find(client, BOOK).total_chapters, 3)


class TestTheChapterList(Base):
    def setUp(self):
        super().setUp()
        self.client = FakeClient({"all.html": whole_list(),
                                  "/0407653271/": book_page()})
        self.novel = self.source.find(self.client, BOOK)

    def test_numbers_come_from_the_titles(self):
        rows = self.source.toc(self.client, self.novel).chapters
        self.assertEqual(rows[0].number, 1000)
        self.assertEqual(rows[-1].number, 1009)

    def test_every_chapter_keeps_its_own_address(self):
        for row in self.source.toc(self.client, self.novel).chapters:
            with self.subTest(number=row.number):
                self.assertTrue(row.link.startswith("https://www.novel543.com/"))

    def test_the_range_is_honoured(self):
        rows = self.source.toc(self.client, self.novel,
                               first=1002, last=1004).chapters
        self.assertEqual([r.number for r in rows], [1002, 1003, 1004])

    def test_a_page_without_a_list_says_the_source_changed(self):
        client = FakeClient({"/0407653271/": "<html><body>пусто</body></html>"})
        with self.assertRaises(SourceBroken):
            self.source.toc(client, self.novel)


class TestTheChapterText(Base):
    def chapter(self):
        return Chapter(number=1056, ch_name="第1056章",
                       link="https://www.novel543.com/0407653271/8096_1056.html")

    def test_the_paragraphs_come_back(self):
        client = FakeClient({"8096_1056": chapter_page()})
        title, text = self.source.chapter(client, self.chapter())

        self.assertIn("第1056章", title)
        self.assertIn("Абзац 1 первый.", text)
        self.assertIn("Абзац 1 второй.", text)

    def test_the_adverts_inside_the_text_are_dropped(self):
        client = FakeClient({"8096_1056": chapter_page()})
        _, text = self.source.chapter(client, self.chapter())

        self.assertNotIn("реклама", text)
        self.assertNotIn("var x", text)

    def test_a_chapter_split_across_pages_is_collected_whole(self):
        """«(1/2)» в заголовке — это одна глава на двух страницах."""
        client = FakeClient({
            "8096_1056_2": chapter_page(part=2, of=2, following=False),
            "8096_1056": chapter_page(part=1, of=2),
        })
        _, text = self.source.chapter(client, self.chapter())

        self.assertIn("Абзац 1 первый.", text)
        self.assertIn("Абзац 2 первый.", text)

    def test_the_page_number_is_not_kept_in_the_title(self):
        """«Глава 1056 (1/2)» и «(2/2)» — одна глава, а не две."""
        client = FakeClient({
            "8096_1056_2": chapter_page(part=2, of=2, following=False),
            "8096_1056": chapter_page(part=1, of=2),
        })
        title, _ = self.source.chapter(client, self.chapter())
        self.assertNotIn("1/2", title)

    def test_the_next_chapter_is_not_mistaken_for_the_next_page(self):
        """Иначе главы склеятся, а книга соберётся с дырами."""
        client = FakeClient({"8096_1056": chapter_page(part=1, of=1)})
        _, text = self.source.chapter(client, self.chapter())

        self.assertNotIn("Абзац 2", text)
        self.assertEqual(len(client.asked), 1)

    def test_a_chapter_without_an_address_is_refused(self):
        with self.assertRaises(SourceBroken):
            self.source.chapter(FakeClient({}), Chapter(number=1))

    def test_a_page_without_text_says_the_source_changed(self):
        client = FakeClient({"8096_1056": "<html><body>ничего</body></html>"})
        with self.assertRaises(SourceBroken):
            self.source.chapter(client, self.chapter())


if __name__ == "__main__":
    unittest.main()
