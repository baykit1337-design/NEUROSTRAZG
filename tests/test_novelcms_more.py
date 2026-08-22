"""Сайты-сливы: остальные китайские адреса и их особенности.

Раньше модуль знал два сайта, устроенных одинаково. Теперь их дюжина, и
одинаковы они только в общих чертах: у одних полный список глав лежит на
странице книги, у других по приписке `/dir`, у третьих по ссылке,
которую сайт даёт сам; у четвёртых он разложен по страницам, а у пятых
вся страница отдана в gb2312.

Проверяется здесь именно это — что разбор подбирается по адресу и что
каждая особенность доезжает до дела. Сайты из окружения разработки
недоступны, поэтому сеть подставляется тестом.

Правила разбора (адреса и селекторы) взяты из расширения `WebToEpub`
(GPL-3.0). Тексты в заготовках свои: проверяется разбор, а не книги.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.api import Chapter, Novel  # noqa: E402
from net.sources import novelcms  # noqa: E402
from net.sources.novelcms import NovelCmsSource, rule_for  # noqa: E402


class Reply:
    def __init__(self, text: str, encoding: str = "utf-8"):
        self.content = text.encode(encoding, "replace")
        self.text = text


class FakeClient:
    """Отдаёт заготовку по совпадению куска адреса.

    Умеет и `get_text`, и `get`: сайтам в gb2312 текст отдаётся байтами,
    и подмена должна повторять оба пути, иначе кодировку не проверить.
    """

    def __init__(self, pages: dict, encoding: str = "utf-8"):
        self.pages = pages
        self.encoding = encoding
        self.asked: list[str] = []

    def _find(self, url: str) -> str:
        self.asked.append(url)
        for part, answer in self.pages.items():
            if part in url:
                return answer
        raise AssertionError(f"Нет заготовки для {url}")

    def get_text(self, url, params=None, headers=None):
        return self._find(url)

    def get(self, url, params=None, headers=None):
        return Reply(self._find(url), self.encoding)

    def close(self):
        pass


class TestTheRuleIsPickedByTheAddress(unittest.TestCase):
    """«Опа, ага, разбор на этот сайт» — по хосту, без переборов."""

    def test_every_known_host_finds_its_rule(self):
        for rule in novelcms.SITES:
            for host in rule.hosts:
                found = rule_for(f"https://{host}/12345/")
                self.assertIsNotNone(found, host)
                self.assertEqual(found.name, rule.name, host)

    def test_www_is_ignored(self):
        self.assertEqual(rule_for("https://www.ddxs.com/1/").name, "ddxs")

    def test_an_exact_host_beats_a_tail_match(self):
        """`m.38xs.com` не должен доставаться правилу от `38xs.com`,
        если у мобильной версии окажется своё."""
        names = [rule.name for rule in novelcms.SITES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(rule_for("https://38xs.com/1/").name, "230book")

    def test_an_unknown_site_has_no_rule(self):
        self.assertIsNone(rule_for("https://example.com/1/"))
        self.assertIsNone(rule_for("не адрес"))

    def test_no_host_is_claimed_by_two_rules(self):
        seen = set()
        for rule in novelcms.SITES:
            for host in rule.hosts:
                self.assertNotIn(host, seen, host)
                seen.add(host)

    def test_the_hint_names_every_site_it_knows(self):
        """Добавленный сайт, о котором никто не знает, бесполезен."""
        said = NovelCmsSource().hint
        for rule in novelcms.SITES:
            for host in rule.hosts:
                self.assertIn(host, said, host)


class TestWhereTheChapterListLies(unittest.TestCase):
    """Три способа добраться до полного списка — и все три нужны."""

    def setUp(self):
        self.source = NovelCmsSource()

    def links(self, host, pages):
        book = f"https://www.{host}/12345/"
        client = FakeClient(pages)
        rows = self.source._links(client, rule_for(book), book)
        return rows, client

    def test_a_list_right_on_the_book_page(self):
        page = ('<html><body><div class="list">'
                '<a href="/12345/1.html">Глава один</a>'
                '<a href="/12345/2.html">Глава два</a>'
                "</div></body></html>")
        rows, client = self.links("sjks88.com", {"/12345/": page})
        self.assertEqual(len(rows), 2)
        # За приписками никуда не ходили — списка на них нет.
        self.assertTrue(all("/dir" not in url for url in client.asked))

    def test_a_list_behind_a_known_suffix(self):
        page = ('<html><body><div class="chaplist"><ul></ul>'
                '<ul><a href="/12345/1.html">Глава</a></ul>'
                "</div></body></html>")
        rows, client = self.links("novel543.com",
                                  {"/dir": page, "/12345/": "<html></html>"})
        self.assertEqual(len(rows), 1)
        self.assertTrue(any(url.endswith("/dir") for url in client.asked))

    def test_a_list_behind_a_link_the_site_gives(self):
        """Адрес оглавления не угадать — сайт говорит его сам."""
        book = ('<html><body><a class="chapterlist" href="/list/12345/">'
                "оглавление</a></body></html>")
        listing = ('<html><body><div class="booklist"><ul>'
                   '<a href="/12345/1.html">Глава</a></ul></div></body></html>')
        rows, client = self.links("biquge.tw",
                                  {"/list/12345/": listing, "/12345/": book})
        self.assertEqual(len(rows), 1)
        self.assertTrue(any("/list/12345/" in url for url in client.asked))

    def test_the_mobile_version_is_asked_when_the_rule_says_so(self):
        """У части сайтов полный список есть только на `m.`."""
        page = ('<html><body><div class="read">'
                '<a href="/12345/1.html">Глава</a></div></body></html>')
        rows, client = self.links("ilwxs.com", {"/12345/": page})
        self.assertEqual(len(rows), 1)
        self.assertTrue(any(url.startswith("https://m.") for url in client.asked))


class TestAListSplitOverPages(unittest.TestCase):
    """Полукнига — худший исход: она выглядит целой."""

    def setUp(self):
        self.source = NovelCmsSource()

    def page(self, low, high, last_page=3):
        rows = "".join('<a href="/12345/%d.html">Глава %d</a>' % (n, n)
                       for n in range(low, high))
        # Страницы оглавления адресуются приписыванием `_N` к адресу
        # книги без слеша: `/12345` → `/12345_2`. Так их строит и сайт.
        return ('<html><body>'
                '<div class="caption"><span>'
                '<a href="/12345_1">首页</a>'
                '<a href="/12345_%d">尾页</a>'
                "</span></div>"
                '<div class="read">%s</div></body></html>' % (last_page, rows))

    def test_chapters_are_collected_from_every_page(self):
        client = FakeClient({
            "/12345_2": self.page(3, 5),
            "/12345_3": self.page(5, 7),
            "/12345/": self.page(1, 3),
        })
        book = "https://www.ilwxs.com/12345/"
        rows = self.source._links(client, rule_for(book), book)
        self.assertEqual(len(rows), 6)

    def test_the_pages_are_walked_in_order(self):
        client = FakeClient({
            "/12345_2": self.page(3, 5),
            "/12345_3": self.page(5, 7),
            "/12345/": self.page(1, 3),
        })
        book = "https://www.ilwxs.com/12345/"
        self.source._links(client, rule_for(book), book)
        walked = [url for url in client.asked if url.endswith(("_2", "_3"))]
        self.assertEqual(len(walked), 2)

    def test_one_page_of_list_asks_for_nothing_more(self):
        """Ссылки «в конец» нет — значит, список и был один."""
        only = ('<html><body><div class="read">'
                '<a href="/12345/1.html">Глава</a></div></body></html>')
        client = FakeClient({"/12345/": only})
        book = "https://www.ilwxs.com/12345/"
        self.source._links(client, rule_for(book), book)
        self.assertEqual(len(client.asked), 1)


class TestTheEncoding(unittest.TestCase):
    """gb2312 и gbk: угадывать нельзя — молча выйдут вопросительные знаки."""

    def setUp(self):
        self.source = NovelCmsSource()

    def test_a_gb2312_page_is_read_as_gb2312(self):
        page = ('<html><body><div class="list">'
                '<a href="/12345/1.html">第一章 测试</a></div></body></html>')
        client = FakeClient({"/12345/": page}, encoding="gb2312")
        book = "https://www.sjks88.com/12345/"
        rows = self.source._links(client, rule_for(book), book)
        self.assertIn("测试", rows[0][1])

    def test_a_utf8_site_is_not_forced_through_a_decoder(self):
        rule = rule_for("https://www.ddxs.com/1/")
        self.assertEqual(rule.encoding, "")

    def test_every_rule_names_a_decoder_python_knows(self):
        import codecs

        for rule in novelcms.SITES:
            if rule.encoding:
                codecs.lookup(rule.encoding)


class TestTheNextPageOfTheSameChapter(unittest.TestCase):
    """Спутать продолжение со следующей главой — самая дорогая ошибка."""

    def test_a_continuation_is_recognised(self):
        self.assertTrue(novelcms._continues(
            "https://x/1/8096_1000.html", "https://x/1/8096_1000_2.html"))

    def test_the_next_chapter_is_not_a_continuation(self):
        """У этих сайтов имя файла само из двух чисел: 8096 книга, 1000
        глава. Сравнивая с предыдущей страницей, легко принять 8096_1001
        за третью страницу — главы склеились бы попарно."""
        self.assertFalse(novelcms._continues(
            "https://x/1/8096_1000.html", "https://x/1/8096_1001.html"))

    def test_the_third_page_is_compared_with_the_first_not_the_second(self):
        self.assertTrue(novelcms._continues(
            "https://x/1/8096_1000.html", "https://x/1/8096_1000_3.html"))

    def test_a_short_name_works_the_same(self):
        self.assertTrue(novelcms._continues("https://x/1/456.html",
                                            "https://x/1/456_2.html"))
        self.assertFalse(novelcms._continues("https://x/1/456.html",
                                             "https://x/1/457.html"))

    def test_the_same_address_is_not_a_continuation(self):
        self.assertFalse(novelcms._continues("https://x/1/456.html",
                                             "https://x/1/456.html"))

    def test_a_site_with_its_own_selector_is_followed(self):
        """У каждого сайта ссылка «дальше» лежит в своём месте."""
        source = NovelCmsSource()
        page = novelcms._soup(
            '<html><body><div class="pager">'
            '<a href="/12345/1.html">上一页</a>'
            '<a href="/12345/1_2.html">下一页</a>'
            "</div></body></html>")
        rule = rule_for("https://www.ilwxs.com/12345/")
        here = "https://www.ilwxs.com/12345/1.html"
        self.assertTrue(source._next_page(page, here, here, rule)
                        .endswith("/1_2.html"))

    def test_a_link_pointing_at_the_next_chapter_is_refused(self):
        source = NovelCmsSource()
        page = novelcms._soup(
            '<html><body><div class="pager">'
            '<a href="/12345/2.html">下一页</a></div></body></html>')
        rule = rule_for("https://www.ilwxs.com/12345/")
        here = "https://www.ilwxs.com/12345/1.html"
        self.assertEqual(source._next_page(page, here, here, rule), "")


class TestTheBookAddress(unittest.TestCase):
    """Адрес книги берётся из вставленного, а не собирается из кода."""

    def setUp(self):
        self.source = NovelCmsSource()

    def test_a_book_in_the_root(self):
        self.assertEqual(
            self.source.code_of("https://www.novel543.com/0407653271/"),
            "0407653271")

    def test_a_book_in_a_subfolder(self):
        """Раньше отсюда доставалось слово «book» вместо кода."""
        self.assertEqual(self.source.code_of("https://biquge.tw/book/12345/"),
                         "12345")

    def test_a_chapter_address_still_finds_the_book(self):
        rule, code, book = self.source._book_url(
            "https://www.novel543.com/0407653271/8096_1000.html")
        self.assertEqual(code, "0407653271")
        self.assertTrue(book.endswith("/0407653271/"))

    def test_a_subfolder_book_keeps_its_folder(self):
        _, _, book = self.source._book_url("https://biquge.tw/book/12345/")
        self.assertTrue(book.endswith("/book/12345/"))

    def test_a_foreign_address_is_refused_and_lists_what_is_known(self):
        from net.sources.base import SourceBroken

        with self.assertRaises(SourceBroken) as caught:
            self.source._book_url("https://example.com/1/")
        self.assertIn("novel543.com", str(caught.exception))


class TestAChapterFromANewSite(unittest.TestCase):
    """Сквозная проверка на одном из добавленных сайтов."""

    def setUp(self):
        self.source = NovelCmsSource()

    def test_a_book_is_found_and_its_chapters_listed(self):
        book_page = ('<html><head><title>Название - сайт</title></head>'
                     '<body><div class="pic"><img src="/i/1.jpg"></div>'
                     '<table><tr><td>служебная</td></tr></table>'
                     '<table><tr>'
                     '<a href="/12345/1.html">Глава один</a>'
                     '<a href="/12345/2.html">Глава два</a>'
                     "</tr></table></body></html>")
        client = FakeClient({"/12345/": book_page})
        novel = self.source.find(client, "https://www.ddxs.com/12345/")
        self.assertEqual(novel.total_chapters, 2)
        self.assertEqual(novel.name, "Название")
        self.assertIn("/i/1.jpg", novel.cover)

    def test_the_text_of_a_chapter_comes_out(self):
        page = ('<html><body><dd><h1>Глава один</h1></dd>'
                '<div id="contents">'
                "<p>Первый абзац.</p><p>Второй абзац.</p>"
                "</div></body></html>")
        client = FakeClient({"/12345/1.html": page})
        chapter = Chapter(number=1, link="https://www.ddxs.com/12345/1.html")
        name, text = self.source.chapter(client, chapter)
        self.assertEqual(name, "Глава один")
        self.assertIn("Первый абзац.", text)
        self.assertIn("\n\n", text)

    def test_an_empty_chapter_is_a_refusal_not_an_empty_file(self):
        from net.sources.base import SourceBroken

        client = FakeClient({"/12345/1.html": "<html><body></body></html>"})
        chapter = Chapter(number=1, link="https://www.ddxs.com/12345/1.html")
        with self.assertRaises(SourceBroken):
            self.source.chapter(client, chapter)

    def test_a_book_without_a_chapter_list_is_a_refusal(self):
        from net.sources.base import SourceBroken

        client = FakeClient({"/12345/": "<html><body>пусто</body></html>"})
        novel = Novel(code=12345, name="Книга",
                      slug="https://www.ddxs.com/12345/", total_chapters=0)
        with self.assertRaises(SourceBroken):
            self.source.toc(client, novel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
