"""Источник Webnovel: книга, оглавление, глава.

Живьём в песочнице это не проверить: `www.webnovel.com` за пределами
разрешённого списка, шлюз отвечает 403 на любой запрос. Поэтому здесь
подставные страницы той же формы, что и настоящие, — в первую очередь с
той же ловушкой: то, что на странице выглядит как JSON, им не является.
Сайт экранирует обратной косой чертой пробелы и амперсанды, а таких
escape-последовательностей в JSON нет.

Текст глав в заготовках свой, а не с сайта: проверяется разбор, а не
содержание книги.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.api import Chapter, Novel  # noqa: E402
from net import sources  # noqa: E402
from net.sources import webnovel  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402


def escaped(value: str) -> str:
    """Как сайт пишет строку внутри объекта страницы.

    Пробелы, амперсанды и апострофы — через обратную косую. Именно это и
    ломает наивный разбор.
    """
    out = json.dumps(value, ensure_ascii=False)
    for char in (" ", "&", "'"):
        out = out.replace(char, "\\" + char)
    return out


def book_page(code="36543528000922105", name="Marvel: I Steal Powers",
              author="Masked_Narrator", chapters=41, status=30,
              language="en", cover_stamp=1785507367776):
    """Страница книги: объект вперемешку с прочей разметкой."""
    info = (
        '{"bookInfo":{"ES":0,"bookId":"%s","bookName":%s,'
        '"authorName":%s,"chapterNum":%d,"totalChapterNum":%d,'
        '"actionStatus":%d,"languageName":"%s","coverUpdateTime":%d,'
        '"categoryName":%s,"description":%s,"firstChapterId":"98103796139352411"},'
        '"curReadChapter":0}'
        % (code, escaped(name), escaped(author), chapters, chapters, status,
           language, cover_stamp, escaped("Anime & Comics"),
           escaped("Every world has power worth taking."))
    )
    return (
        "<!DOCTYPE html><html><head><title>Книга</title></head><body>"
        "<h1>Заголовок из вёрстки, который брать не надо</h1>"
        "<script>g_data.book= " + info + ',g_data.pageId="qi_p_bookdetail"</script>'
        "</body></html>"
    )


def catalog_page(code="36543528000922105", count=3):
    """Оглавление ссылками — так его видят поисковики."""
    links = "".join(
        '<a href="/book/%s/glava-%d_%d">Chapter %d: Название %d</a>'
        % (code, i, 98103796139352410 + i, i, i)
        for i in range(1, count + 1))
    return ("<html><body>"
            # Ссылка на саму книгу тоже кончается длинным числом.
            '<a href="/book/%s">К книге</a>' % code
            + links + "</body></html>")


def chapter_page(number=1, name="Название главы", paragraphs=None,
                 is_auth=1, css="", contents=None):
    """Страница главы: текст лежит абзац к абзацу в объекте."""
    if contents is None:
        paragraphs = paragraphs if paragraphs is not None else [
            "Первый абзац.", "Второй абзац, подлиннее."]
        contents = [
            '{"content":%s,"paragraphId":"p%d"}'
            % (escaped("<p>" + text + "</p>"), i)
            for i, text in enumerate(paragraphs)]
    info = (
        '{"bookInfo":{"bookId":"36543528000922105"},'
        '"chapterInfo":{"chapterId":"98103796139352411","chapterName":%s,'
        '"chapterIndex":%d,"preChapterId":"-1",'
        '"nextChapterId":"98104321870185155","isAuth":%d,"vipStatus":0,'
        '"price":0,"css":%s,"contents":[%s]}}'
        % (escaped(name), number, is_auth, escaped(css), ",".join(contents))
    )
    return ("<html><body><script>var chapInfo= " + info
            + ";g_data.chapInfo=chapInfo</script></body></html>")


class FakeClient:
    """Отдаёт заготовленные страницы по адресу."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def get_text(self, url, params=None, headers=None):
        self.asked.append(url)
        for mark, page in self.pages.items():
            if mark in url:
                return page
        raise AssertionError("не заготовлена страница для " + url)

    def close(self):
        pass


class TestTheEscapingTrap(unittest.TestCase):
    """Главная ловушка сайта: то, что похоже на JSON, им не является."""

    def test_a_backslash_before_a_space_would_break_a_plain_parser(self):
        """Проверяем саму заготовку: если она разбирается как есть,
        значит, тест ничего не ловит."""
        raw = escaped("Marvel: I Steal Powers")
        with self.assertRaises(ValueError):
            json.loads(raw)

    def test_the_source_reads_it_anyway(self):
        page = book_page(name="Marvel: I Steal Powers")
        got = webnovel._object_after(page, webnovel.BOOK_MARK)
        self.assertEqual(got["bookInfo"]["bookName"], "Marvel: I Steal Powers")

    def test_an_ampersand_survives(self):
        page = book_page()
        got = webnovel._object_after(page, webnovel.BOOK_MARK)
        self.assertEqual(got["bookInfo"]["categoryName"], "Anime & Comics")

    def test_real_escapes_are_left_alone(self):
        """Перевод строки и кавычка внутри строки — настоящие escape."""
        raw = r'{"a":"строка\nс переводом и \"кавычкой\"","b":"сло\ во"}'
        got = json.loads(webnovel._unescape(raw))
        self.assertEqual(got["a"], 'строка\nс переводом и "кавычкой"')
        self.assertEqual(got["b"], "сло во")


class TestFindingTheObject(unittest.TestCase):
    """Скобки считаются вручную — регулярное выражение тут обрезает не там."""

    def test_braces_inside_strings_do_not_end_the_object(self):
        page = 'x = {"a":"} не конец {","b":1} ; конец'
        self.assertEqual(webnovel._object_after(page, "x ="), {"a": "} не конец {", "b": 1})

    def test_an_escaped_quote_does_not_end_the_string(self):
        page = r'x = {"a":"кавычка \" и скобка }","b":2} ;'
        self.assertEqual(webnovel._object_after(page, "x =")["b"], 2)

    def test_a_missing_object_says_the_markup_changed(self):
        with self.assertRaises(SourceBroken):
            webnovel._object_after("<html>пусто</html>", "g_data.book=")

    def test_a_truncated_object_is_not_silently_accepted(self):
        with self.assertRaises(SourceBroken):
            webnovel._object_after('x = {"a":1,"b":', "x =")


class TestBookId(unittest.TestCase):
    """Код книги принимаем в любом виде, в каком он встречается."""

    def setUp(self):
        self.source = webnovel.WebnovelSource()

    def test_a_bare_code(self):
        self.assertEqual(self.source.book_id("36543528000922105"),
                         "36543528000922105")

    def test_a_short_book_url(self):
        self.assertEqual(
            self.source.book_id("https://www.webnovel.com/book/36543528000922105"),
            "36543528000922105")

    def test_a_url_with_a_slug(self):
        self.assertEqual(self.source.book_id(
            "https://www.webnovel.com/book/marvel-i-steal_36543528000922105"),
            "36543528000922105")

    def test_a_chapter_url_gives_the_book_not_the_chapter(self):
        """В адресе главы два длинных числа, и нужное — первое."""
        self.assertEqual(self.source.book_id(
            "https://www.webnovel.com/book/marvel_36543528000922105/"
            "the-death-dealer_98103796139352411"),
            "36543528000922105")

    def test_the_mobile_host_works_too(self):
        self.assertEqual(
            self.source.book_id("https://m.webnovel.com/book/36543528000922105"),
            "36543528000922105")

    def test_something_else_entirely_is_refused(self):
        self.assertEqual(self.source.book_id("https://fanqienovel.com/page/71"), "")
        self.assertEqual(self.source.book_id(""), "")

    def test_a_foreign_link_is_refused_with_an_explanation(self):
        with self.assertRaises(SourceBroken) as caught:
            self.source.find(FakeClient({}), "не ссылка")
        self.assertIn("webnovel.com", str(caught.exception))


class TestFindingTheBook(unittest.TestCase):
    def setUp(self):
        self.source = webnovel.WebnovelSource()
        self.client = FakeClient({"/book/36543528000922105": book_page()})

    def find(self, **kw):
        self.client.pages = {"/book/36543528000922105": book_page(**kw)}
        return self.source.find(self.client, "36543528000922105")

    def test_the_name_comes_from_the_object_not_the_markup(self):
        novel = self.find()
        self.assertEqual(novel.name, "Marvel: I Steal Powers")
        self.assertNotIn("вёрстки", novel.name)

    def test_the_author_and_count_survive(self):
        novel = self.find()
        self.assertEqual(novel.author, "Masked_Narrator")
        self.assertEqual(novel.total_chapters, 41)

    def test_a_finished_book_says_so(self):
        self.assertEqual(self.find(status=50).status, "закончена")

    def test_a_running_book_says_so(self):
        self.assertEqual(self.find(status=30).status, "пишется")

    def test_the_cover_is_addressed_by_the_book_code(self):
        self.assertIn("36543528000922105", self.find().cover)

    def test_a_page_without_the_object_says_the_markup_changed(self):
        self.client.pages = {"/book/": "<html>ничего</html>"}
        with self.assertRaises(SourceBroken):
            self.source.find(self.client, "36543528000922105")


class TestTheCatalogue(unittest.TestCase):
    def setUp(self):
        self.source = webnovel.WebnovelSource()
        self.novel = Novel(code=36543528000922105, name="Книга",
                           slug="36543528000922105", total_chapters=3)

    def toc(self, page, **kw):
        client = FakeClient({"/catalog": page})
        return self.source.toc(client, self.novel, **kw)

    def test_chapters_come_out_in_reading_order(self):
        toc = self.toc(catalog_page(count=3))
        self.assertEqual([c.number for c in toc.chapters], [1, 2, 3])

    def test_the_book_link_is_not_mistaken_for_a_chapter(self):
        """Адрес книги тоже кончается длинным числом."""
        toc = self.toc(catalog_page(count=2))
        self.assertEqual(len(toc.chapters), 2)
        self.assertNotIn("36543528000922105",
                         [c.post_id for c in toc.chapters])

    def test_names_survive(self):
        toc = self.toc(catalog_page(count=1))
        self.assertIn("Название 1", toc.chapters[0].ch_name)

    def test_the_range_is_respected(self):
        toc = self.toc(catalog_page(count=5), first=2, last=4)
        self.assertEqual([c.number for c in toc.chapters], [2, 3, 4])

    def test_a_repeated_link_is_counted_once(self):
        page = catalog_page(count=2) + catalog_page(count=2)
        self.assertEqual(len(self.toc(page).chapters), 2)

    def test_an_empty_catalogue_says_what_broke_and_where(self):
        """«Не получилось» без адреса не даёт даже посмотреть глазами."""
        with self.assertRaises(SourceBroken) as caught:
            self.toc("<html><body>ничего</body></html>")
        said = str(caught.exception)
        self.assertIn("/catalog", said)
        self.assertIn("36543528000922105", said)

    def test_a_script_only_page_is_a_named_failure_not_an_empty_book(self):
        """Так выглядит оглавление, подгружаемое скриптом: разметка есть,
        ссылок на главы нет. Молча отдать пустую книгу тут нельзя."""
        page = ('<html><body><div class="j_catalog_wrap">'
                '<span class="g_loading _on"><i></i></span></div>'
                '<a href="/book/36543528000922105">К книге</a>'
                '</body></html>')
        with self.assertRaises(SourceBroken):
            self.toc(page)


class TestTheChapter(unittest.TestCase):
    def setUp(self):
        self.source = webnovel.WebnovelSource()
        self.chapter = Chapter(number=1, post_id="98103796139352411",
                               link="https://www.webnovel.com/book/1/2")

    def read(self, page):
        return self.source.chapter(FakeClient({"/book/": page}), self.chapter)

    def test_paragraphs_come_out_as_text(self):
        name, text = self.read(chapter_page(
            paragraphs=["Первый абзац.", "Второй абзац."]))
        self.assertEqual(name, "Название главы")
        self.assertIn("Первый абзац.", text)
        self.assertIn("Второй абзац.", text)

    def test_paragraphs_stay_apart(self):
        """Слипшиеся абзацы потом не разделить ничем."""
        _, text = self.read(chapter_page(paragraphs=["Раз.", "Два."]))
        self.assertIn("\n\n", text)

    def test_the_markup_of_a_paragraph_does_not_get_into_the_text(self):
        _, text = self.read(chapter_page(paragraphs=["Обычный абзац."]))
        self.assertNotIn("<p>", text)
        self.assertNotIn("</p>", text)

    def test_an_empty_paragraph_does_not_leave_a_hole(self):
        _, text = self.read(chapter_page(paragraphs=["Есть.", "", "Тоже есть."]))
        self.assertNotIn("\n\n\n", text)

    def test_a_locked_chapter_is_refused_by_name(self):
        page = chapter_page(is_auth=0, contents=[])
        with self.assertRaises(webnovel.ChapterLocked):
            self.read(page)

    def test_a_locked_chapter_says_the_program_will_not_go_around_it(self):
        page = chapter_page(is_auth=0, contents=[])
        with self.assertRaises(webnovel.ChapterLocked) as caught:
            self.read(page)
        self.assertIn("не обходит", str(caught.exception))

    def test_a_chapter_with_its_own_font_is_refused(self):
        """Без шрифта это не буквы — записывать такое нельзя."""
        page = chapter_page(css="@font-face{font-family:Genuine_1}")
        with self.assertRaises(webnovel.ChapterScrambled):
            self.read(page)

    def test_an_empty_but_open_chapter_is_a_markup_change_not_a_paywall(self):
        page = chapter_page(is_auth=1, contents=[])
        with self.assertRaises(SourceBroken) as caught:
            self.read(page)
        self.assertNotIsInstance(caught.exception, webnovel.ChapterLocked)


class TestTheDownloaderKnowsWhatToDoWithThem(unittest.TestCase):
    """Закрытая глава — пропуск, а не падение всей книги."""

    def test_a_locked_chapter_counts_as_skipped(self):
        from mvl.downloader import _is_paid
        self.assertTrue(_is_paid(webnovel.ChapterLocked("платная")))

    def test_a_scrambled_chapter_counts_as_skipped(self):
        from mvl.downloader import _is_paid
        self.assertTrue(_is_paid(webnovel.ChapterScrambled("шрифт")))

    def test_a_real_breakage_still_stops_the_chapter(self):
        from mvl.downloader import _is_paid
        self.assertFalse(_is_paid(SourceBroken("разметка сменилась")))


class TestItIsOfferedInTheDownloader(unittest.TestCase):
    def test_the_source_is_in_the_list(self):
        keys = [s.key for s in sources.all_sources()]
        self.assertIn("webnovel", keys)

    def test_it_can_be_asked_for_by_key(self):
        self.assertIsInstance(sources.get("webnovel"), webnovel.WebnovelSource)

    def test_it_is_not_the_default(self):
        """Часть глав платная — такой размен человек делает сам."""
        self.assertNotEqual(sources.all_sources()[0].key, "webnovel")

    def test_the_hint_warns_about_paid_chapters(self):
        said = sources.get("webnovel").as_dict()
        self.assertIn("латны", said["hint"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
