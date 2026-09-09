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


class TestABookThatLiesInAFileNotAFolder(unittest.TestCase):
    """`/book/45540.htm` — книга лежит файлом.

    Общее правило «код это последний кусок пути» отбрасывает файл вместе
    с кодом и оставляет слово «book». Дальше по такому «коду» собирается
    адрес `/book/`, и качалка уходит в никуда — молча, потому что
    страница по нему у сайта есть.
    """

    def setUp(self):
        self.source = NovelCmsSource()

    def test_the_code_survives_the_extension(self):
        self.assertEqual(
            self.source.code_of("https://www.69shuba.com/book/45540.htm"),
            "45540")
        self.assertEqual(
            self.source.code_of("https://twkan.com/book/16711.html"), "16711")

    def test_the_code_is_taken_from_a_chapter_address_too(self):
        """Человек копирует ссылку с той страницы, где читает."""
        self.assertEqual(
            self.source.code_of("https://www.69shuba.com/txt/45540/41064072"),
            "45540")

    def test_the_book_page_is_built_from_the_code(self):
        rule, code, book = self.source._book_url(
            "https://www.69shuba.com/txt/45540/41064072")
        self.assertEqual(rule.name, "69shu")
        self.assertEqual(code, "45540")
        self.assertEqual(book, "https://www.69shuba.com/book/45540.htm")

    def test_a_folder_site_still_keeps_the_pasted_address(self):
        """Правка не должна была тронуть тех, у кого и так работало."""
        _, code, book = self.source._book_url(
            "https://www.novel543.com/0407653271/")
        self.assertEqual(code, "0407653271")
        self.assertEqual(book, "https://www.novel543.com/0407653271/")

    def test_an_address_without_a_code_is_named(self):
        with self.assertRaises(novelcms.SourceBroken):
            self.source._book_url("https://twkan.com/novels/class/1_1.html")


class TestAListThatGoesFromTheNewestChapter(unittest.TestCase):
    """69shuba перечисляет главы от свежей к первой.

    Пока номер стоит в названии каждой главы, порядок задаст он. Но
    стоит он не у каждой — «新年快乐！» номера не имеет вовсе, — и тогда
    порядок остаётся тот, что дал сайт. Не развернуть его значит
    сохранить книгу задом наперёд.
    """

    def setUp(self):
        self.source = NovelCmsSource()

    def rows(self, titles):
        items = "".join(
            '<li><a href="/txt/45540/%d">%s</a></li>' % (900 + n, title)
            for n, title in enumerate(titles))
        book = ('<html><body><div class="booknav2"><h1>Книга</h1></div>'
                '<a class="btn more-btn" href="/book/45540/">полный</a>'
                "</body></html>")
        listing = ('<html><body><div id="catalog"><ul>%s</ul></div>'
                   "</body></html>" % items)
        client = FakeClient({"/book/45540/": listing,
                             "/book/45540.htm": book}, encoding="gb18030")
        where = "https://www.69shuba.com/book/45540.htm"
        return self.source._links(client, rule_for(where), where), client

    def test_chapters_without_numbers_keep_the_sites_order_reversed(self):
        rows, _ = self.rows(["С новым годом!", "Про серебряное море",
                             "Начало"])
        self.assertEqual([title for _, title, _ in rows],
                         ["Начало", "Про серебряное море", "С новым годом!"])
        self.assertEqual([number for number, _, _ in rows], [1, 2, 3])

    def test_the_number_in_the_title_still_wins(self):
        """Развернули — но если номера есть, порядок задают они."""
        rows, _ = self.rows(["第3章 Третья", "第1章 Первая", "第2章 Вторая"])
        self.assertEqual([number for number, _, _ in rows], [1, 2, 3])

    def test_the_full_list_is_asked_for_by_the_sites_own_link(self):
        """На странице книги висят последние пять глав."""
        _, client = self.rows(["Один", "Два"])
        self.assertTrue(any("/book/45540/" in url for url in client.asked))


class TestAListTheSiteFetchesForItself(unittest.TestCase):
    """У twkan страница оглавления показывает начало списка и кнопку
    «ещё». Весь список сайт берёт отдельным куском вёрстки — и мы
    оттуда же, иначе от книги досталась бы сотня глав с бодрым отчётом
    об успехе."""

    def setUp(self):
        self.source = NovelCmsSource()

    def test_the_whole_list_comes_from_the_sites_own_address(self):
        whole = ("<ul>" + "".join(
            '<li><a href="/txt/16711/%d">第%d章 Глава</a></li>' % (500 + n, n)
            for n in range(1, 30)) + "</ul>")
        short = ('<html><body><ul class="qustime">'
                 '<li><a href="/txt/16711/501">第1章 Глава</a></li>'
                 "</ul></body></html>")
        client = FakeClient({"/ajax_novels/chapterlist/16711.html": whole,
                             "/book/16711": short})
        book = "https://twkan.com/book/16711.html"
        rows = self.source._links(client, rule_for(book), book)
        self.assertEqual(len(rows), 29)
        self.assertTrue(any("/ajax_novels/chapterlist/16711.html" in url
                            for url in client.asked))


class TestWhatTheSiteItselfCallsRubbish(unittest.TestCase):
    """Внутри блока с текстом у этих сайтов стоит строка с числом
    прочтений и столбец сбоку. Абзацами они не выглядят, но абзацами
    разбираются — и уезжают в книгу наравне с текстом."""

    def setUp(self):
        self.source = NovelCmsSource()

    def test_the_named_rubbish_does_not_reach_the_book(self):
        page = """<html><body><div class="txtnav">
            <h1>第815章 Глава</h1>
            <div class="txtinfo hide720"><span>прочтений: 1234</span></div>
            <div id="txtright"><p>реклама сбоку</p></div>
            <p>Первый абзац.</p>
            <p>Второй абзац.</p>
            <div class="bottom-ad"><p>реклама снизу</p></div>
          </div></body></html>"""
        client = FakeClient({"/txt/45540/": page}, encoding="gb18030")
        title, text = self.source.chapter(
            client, Chapter(number=815, post_id="", ch_name="",
                            link="https://www.69shuba.com/txt/45540/41064072"))
        self.assertEqual(title, "第815章 Глава")
        self.assertEqual(text, "Первый абзац.\n\nВторой абзац.")

    def test_the_page_is_read_in_the_encoding_the_site_writes_in(self):
        """Сайт объявляет gbk, а пишет в gb18030.

        Проверяем знаком, который есть в gb18030 и которого нет в gbk:
        на общей их части ошибка не видна вовсе, а редкий иероглиф на
        gbk превращается в вопросительный знак — молча и навсегда.
        """
        page = ('<html><body><div class="txtnav"><h1>Глава</h1>'
                "<p>Текст 巫师㐀 про магию.</p></div></body></html>")
        client = FakeClient({"/txt/45540/": page}, encoding="gb18030")
        _, text = self.source.chapter(
            client, Chapter(number=1, post_id="", ch_name="",
                            link="https://www.69shuba.com/txt/45540/1"))
        self.assertIn("巫师㐀", text)

    def test_the_twkan_chapter_text_is_found_where_it_lies(self):
        """У соседа по движку блок с текстом называется иначе, и общие
        запасные селекторы до него не достают."""
        page = """<html><body><div class="mybox"><div class="txtnav">
            <h1>第815章 Глава</h1>
            <div class="txtinfo"><span>прочтений: 12</span></div>
            <div id="txtcontent0">
              <p>Перший абзац.</p>
              <p>Другий абзац.</p>
            </div>
            <div class="txtcenter"><p>реклама</p></div>
          </div></div></body></html>"""
        client = FakeClient({"/txt/16711/": page})
        title, text = self.source.chapter(
            client, Chapter(number=815, post_id="", ch_name="",
                            link="https://twkan.com/txt/16711/56343814"))
        self.assertEqual(title, "第815章 Глава")
        self.assertEqual(text, "Перший абзац.\n\nДругий абзац.")


class TestTheWholeBookInOneFile(unittest.TestCase):
    """У ixdzs8 на странице книги есть кнопка «скачать TXT»: та же книга
    одним файлом. Восемьсот запросов против одного — разница между сорока
    минутами и десятью секундами.

    Заменить архивом оглавление нельзя: внутри главы подписаны авторской
    нумерацией, а она начинается заново в каждом томе. Поэтому архив —
    только ускоритель текста, а раскладываются главы по порядку и лишь
    при совпадении заголовка с тем, что сказал сайт.
    """

    BOOK = "https://ixdzs8.com/read/454442/"

    def setUp(self):
        self.source = NovelCmsSource()
        self.rule = rule_for(self.BOOK)

    def whole(self, chapters=None) -> str:
        """Архив изнутри: шапка, метка начала, главы с отступами."""
        rows = chapters or [("第1章 начало", ["Первый абзац.", "Второй абзац."]),
                            ("第2章 дальше", ["Третий абзац."])]
        out = ["《Книга/作者:Некто》", "《状态:更新到:第2章 дальше》",
               "《内容简介:", "  Описание книги.", "》",
               "Сайт: https://ixdzs8.com",
               "------章节内容开始-------"]
        for title, body in rows:
            out.append(title)
            out.extend("　　" + line for line in body)
        return "\n".join(out)

    def zipped(self, text=None) -> bytes:
        import io
        import zipfile

        box = io.BytesIO()
        with zipfile.ZipFile(box, "w") as pack:
            pack.writestr("454442.txt",
                          (text if text is not None else self.whole())
                          .encode("gb18030", "replace"))
        return box.getvalue()

    def client(self, raw=None, trouble=None):
        source = self

        class Answer:
            def __init__(self, content):
                self.content = content

        class Client:
            def __init__(self):
                self.asked = []

            def get(self, url, params=None, headers=None):
                self.asked.append(url)
                if trouble is not None:
                    raise trouble
                return Answer(raw if raw is not None else source.zipped())

            def get_text(self, url, params=None, headers=None):
                self.asked.append(url)
                return ('<html><body><article class="page-content">'
                        "<section><p>Из сети.</p></section>"
                        "</article></body></html>")

        return Client()

    def ask(self, number, title, asked=100):
        self.source._asked = asked
        return Chapter(number=number, post_id="", ch_name=title,
                       link=f"https://ixdzs8.com/read/454442/p{number}.html")

    # ------------------------------------------------------------ разбор

    def test_the_header_of_the_archive_is_not_a_chapter(self):
        """Название, автор, описание и строка с адресом сайта — не книга."""
        rows = novelcms.read_whole(self.whole())
        self.assertEqual([title for title, _ in rows],
                         ["第1章 начало", "第2章 дальше"])

    def test_the_indented_lines_are_the_text(self):
        rows = novelcms.read_whole(self.whole())
        self.assertEqual(rows[0][1], ("Первый абзац.", "Второй абзац."))

    def test_chapters_keep_the_order_they_lie_in(self):
        """Номер в заголовке авторский и повторяется от тома к тому:
        «第1章» встречается и в начале книги, и в середине. Разложить
        главы по нему значит собрать кашу."""
        rows = novelcms.read_whole(self.whole([
            ("第1章 первая", ["А."]),
            ("第2章 вторая", ["Б."]),
            ("第1章 снова первая", ["В."]),
        ]))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2][0], "第1章 снова первая")
        self.assertEqual(rows[2][1], ("В.",))

    # ------------------------------------------------------- в работе

    def test_a_chapter_comes_out_of_the_archive(self):
        client = self.client()
        title, text = self.source.chapter(client, self.ask(1, "第1章 начало"))
        self.assertEqual(title, "第1章 начало")
        self.assertEqual(text, "Первый абзац.\n\nВторой абзац.")
        self.assertNotIn("Из сети", text)

    def test_the_archive_is_asked_for_once_not_per_chapter(self):
        """В этом весь смысл: один запрос вместо восьмисот."""
        client = self.client()
        self.source.chapter(client, self.ask(1, "第1章 начало"))
        self.source.chapter(client, self.ask(2, "第2章 дальше"))
        self.assertEqual(len([one for one in client.asked if ".zip" in one]), 1)

    def test_it_is_read_in_the_encoding_the_site_writes_in(self):
        rows = [("第1章 начало", ["Текст 巫师㐀 про магию."])]
        client = self.client(raw=self.zipped(self.whole(rows)))
        _, text = self.source.chapter(client, self.ask(1, "第1章 начало"))
        self.assertIn("巫师㐀", text)

    # --------------------------------------------------- когда не берём

    def test_a_title_that_does_not_match_sends_us_to_the_network(self):
        """Архив собран вчера, вышла новая глава — и весь порядок съехал
        на единицу. Лишний запрос лучше сдвинутой книги."""
        client = self.client()
        _, text = self.source.chapter(
            client, self.ask(1, "第1章 совсем другая глава"))
        self.assertEqual(text, "Из сети.")

    def test_a_chapter_the_archive_does_not_reach_comes_from_the_network(self):
        client = self.client()
        _, text = self.source.chapter(client, self.ask(9, "第9章 девятая"))
        self.assertEqual(text, "Из сети.")

    def test_a_short_run_does_not_pay_for_the_archive(self):
        """Три главы из шестимегабайтного архива хуже трёх запросов."""
        client = self.client()
        _, text = self.source.chapter(client, self.ask(1, "第1章 начало",
                                                       asked=3))
        self.assertEqual(text, "Из сети.")
        self.assertEqual([one for one in client.asked if ".zip" in one], [])

    def test_an_archive_that_did_not_come_is_not_a_broken_book(self):
        client = self.client(trouble=OSError("нет сети"))
        _, text = self.source.chapter(client, self.ask(1, "第1章 начало"))
        self.assertEqual(text, "Из сети.")

    def test_something_that_is_not_an_archive_is_not_a_broken_book(self):
        client = self.client(raw=b"<html>404</html>")
        _, text = self.source.chapter(client, self.ask(1, "第1章 начало"))
        self.assertEqual(text, "Из сети.")

    def test_a_site_without_an_archive_works_as_before(self):
        """Правка не должна была тронуть тех, у кого и так работало."""
        self.assertIsNone(rule_for("https://sjks88.com/12345/").archive)

    def test_the_run_says_how_many_chapters_it_wants(self):
        """Без этого источник не знает, стоит ли архив своих мегабайт."""
        listing = {"data": [{"title": f"第{n}章 Глава", "ordernum": n}
                            for n in range(1, 41)]}

        class Client:
            def post(self, url, data=None, headers=None):
                return type("R", (), {"json": lambda self: listing})()

        novel = Novel(code=454442, name="Книга", slug=self.BOOK,
                      total_chapters=40)
        self.source.toc(Client(), novel, first=1, last=30)
        self.assertEqual(self.source._asked, 30)

    def test_closing_lets_the_six_megabytes_go(self):
        client = self.client()
        self.source.chapter(client, self.ask(1, "第1章 начало"))
        self.source.close()
        self.assertIsNone(self.source._whole)

    def test_a_repeated_author_number_does_not_fetch_the_wrong_chapter(self):
        """«第1章» встречается и в начале книги, и в середине тома. Ищи
        мы главу по этому номеру — вернулась бы первая попавшаяся, и
        книга собралась бы кашей, притом молча."""
        text = self.whole([("第1章 первая", ["А."]),
                           ("第2章 вторая", ["Б."]),
                           ("第1章 снова первая", ["В."])])
        client = self.client(raw=self.zipped(text))
        _, got = self.source.chapter(client, self.ask(3, "第1章 снова первая"))
        self.assertEqual(got, "В.")

    def test_a_heading_quoted_inside_the_text_stays_text(self):
        """В тексте главы герои поминают «第5章» — это абзац, а не новая
        глава. Различает их только отступ."""
        text = self.whole([("第1章 начало", ["第5章 — вот о чём он говорил.",
                                             "И замолчал."]),
                           ("第2章 дальше", ["Б."])])
        rows = novelcms.read_whole(text)
        self.assertEqual(len(rows), 2, [t for t, _ in rows])
        self.assertIn("第5章 — вот о чём он говорил.", rows[0][1])

    def test_the_archive_is_asked_for_at_the_address_the_site_gives(self):
        client = self.client()
        self.source.chapter(client, self.ask(1, "第1章 начало"))
        self.assertIn("https://down7.ixdzs8.com/454442.zip", client.asked)

    def test_the_book_is_found_among_the_odds_and_ends(self):
        """Имя файла внутри архива не угадываем — берём самый тяжёлый."""
        import io
        import zipfile

        box = io.BytesIO()
        with zipfile.ZipFile(box, "w") as pack:
            pack.writestr("readme.txt", "Спасибо, что скачали.".encode("gb18030"))
            pack.writestr("kniga.txt", self.whole().encode("gb18030", "replace"))
        client = self.client(raw=box.getvalue())
        _, text = self.source.chapter(client, self.ask(1, "第1章 начало"))
        self.assertEqual(text, "Первый абзац.\n\nВторой абзац.")
