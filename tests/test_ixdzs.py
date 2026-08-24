"""ixdzs8: оглавление приходит отдельным запросом, а не лежит в вёрстке.

На странице книги висят только последние восемь глав — весь список сайт
забирает по `POST /novel/clist/` и рисует его уже в браузере. Разобрать
такую страницу вёрсткой можно; получится восьмиглавая книга, молча и с
отчётом об успехе. Поэтому список берётся оттуда же, откуда его берёт сам
сайт, а запасного пути тут нет намеренно.

Заготовки повторяют устройство живых страниц — имена полей ответа,
селекторы текста, адрес главы вида `/read/{код}/p{номер}.html`, — но текст
в них свой: сайт из окружения разработки недоступен, да и чужая книга
здесь ни к чему.

Отдельная тонкость, ради которой заготовки такие подробные: номер в адресе
— **не** номер главы. У книги 402 главы, а последняя лежит по `p399.html`:
заголовки томов в нумерации адресов не участвуют.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.api import Chapter  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402
from net.sources.novelcms import NovelCmsSource, rule_for  # noqa: E402

BOOK = "https://ixdzs8.com/read/566155/"


def book_page() -> str:
    """Страница книги. В списке — только последние главы, как живьём."""
    latest = "".join(
        f'<li><a href="/read/566155/p{n}.html">第{n + 3}章 Поздняя</a></li>'
        for n in range(5, 9))
    return f"""<!doctype html><html><head><title>Книга — 爱下电子书</title>
      </head><body><main><div class="panel"><div class="novel">
        <div class="n-img"><img src="https://img22.example/обложка.jpg"></div>
        <div class="n-text">
          <h1>Книга про дверь</h1>
          <p>作者:<a href="/author/кто" class="bauthor">Автор Такой-то</a></p>
          <p><span class="lz">连载中</span></p>
        </div>
      </div></div>
      <div class="panel"><ul class="u-chapter cfirst">{latest}
        <li class="catalog-all">查看完整章节目录&gt;&gt;&gt;</li>
      </ul></div></main></body></html>"""


def chapter_list(count=20, volumes=True) -> str:
    """Ответ `/novel/clist/`: тома идут в том же списке, но без адреса.

    Из-за них номер главы и номер в адресе расходятся, и расходятся
    именно так, как на живом сайте: у 异度旅社 «共402章», а последняя
    глава — 第402章 — лежит по `p399.html`. Считать номер главы номером в
    адресе значит скачать не те главы и заметить это только по тексту.
    """
    rows = []
    number = 0            # сквозной счёт строк — он и попадает в название
    order = 0             # счёт одних глав — он и попадает в адрес
    while len(rows) < count:
        number += 1
        if volumes and number in (1, 11):
            rows.append({"ctype": 1, "title": f"Том {number // 10 + 1}"})
            continue
        order += 1
        rows.append({"ctype": 0, "ordernum": order,
                     "title": f"第{number}章 Глава про дверь"})
    return json.dumps({"rs": 200, "data": rows}, ensure_ascii=False)


def chapter_page(number=397, order=394) -> str:
    """Страница главы. Заголовок напечатан трижды и по-разному."""
    body = "".join(f"<p>Абзац {n} про дверь.</p>" for n in range(1, 4))
    return f"""<!doctype html><html><head>
      <title>第{number}章 Про дверь_Книга-爱下电子书</title></head>
      <body class="skin-default"><div id="page" class="page-d">
        <div class="page-d-top">
          <h1 class="page-d-name">第{number}章 Про дверь</h1>
        </div>
        <article class="page-content">
          <h3>第{number}章 Про дверь</h3>
          <section>
            <p>第{number}章Про дверь</p>
            {body}
            <p>(本章完)</p>
          </section>
        </article>
      </div>
      <div class="page-d page-turn"><div class="chapter-act">
        <a href="/read/566155/p{order - 1}.html" class="chapter-pre">上一章</a>
        <a href="/read/566155/">书籍页</a>
        <a href="/read/566155/p{order + 1}.html" class="chapter-next">下一章</a>
      </div></div>
      <input type="hidden" id="bid" value="566155">
      <input type="hidden" id="cid" value="{order}">
      </body></html>"""


class Reply:
    def __init__(self, text):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = 200

    def json(self):
        return json.loads(self.text)


class Site:
    """Сайт, у которого список глав отдаётся только по POST."""

    def __init__(self, pages=None, listing=None, breaks=False):
        self.pages = pages if pages is not None else {"/read/566155/": book_page()}
        self.listing = chapter_list() if listing is None else listing
        self.breaks = breaks
        self.asked: list[str] = []
        self.posted: list[tuple] = []

    def get_text(self, url, params=None, headers=None, cookies=None):
        self.asked.append(url)
        for part, answer in sorted(self.pages.items(),
                                   key=lambda kv: -len(kv[0])):
            if part in url:
                return answer
        raise AssertionError(f"Нет заготовки для {url}")

    def get(self, url, params=None, headers=None, cookies=None):
        return Reply(self.get_text(url))

    def post(self, url, data=None, headers=None, cookies=None):
        self.posted.append((url, data))
        if self.breaks:
            raise OSError("сайт не ответил")
        return Reply(self.listing)


class Base(unittest.TestCase):
    def setUp(self):
        self.source = NovelCmsSource()


class TestTheSiteIsKnown(Base):

    def test_the_plain_address_is_ours(self):
        self.assertEqual(rule_for(BOOK).name, "ixdzs")

    def test_the_other_two_addresses_are_the_same_site(self):
        """Сайт сам перечисляет их в шапке каждой страницы."""
        for host in ("ixdzs.hk", "ixdzs.tw"):
            self.assertEqual(rule_for(f"https://{host}/read/566155/").name,
                             "ixdzs", host)

    def test_the_code_comes_from_the_address(self):
        self.assertEqual(self.source.code_of(BOOK), "566155")

    def test_a_chapter_address_gives_the_same_code(self):
        """Человек копирует из адресной строки что попало."""
        self.assertEqual(
            self.source.code_of("https://ixdzs8.com/read/566155/p394.html"),
            "566155")

    def test_the_hint_names_the_site(self):
        from net import sources

        self.assertIn("ixdzs8.com", sources.get("novelcms").hint)


class TestTheListComesFromTheRequest(Base):

    def test_the_book_page_alone_is_not_believed(self):
        """В вёрстке лежат последние восемь глав. Взять их значило бы
        отдать восьмиглавую книгу — молча и как удачу."""
        site = Site()
        novel = self.source.find(site, BOOK)
        # Двадцать строк списка, две из них — заголовки томов.
        self.assertEqual(novel.total_chapters, 18)

    def test_the_list_is_asked_for_by_post(self):
        site = Site()
        self.source.find(site, BOOK)
        self.assertTrue(site.posted, "список глав не запрашивали вовсе")

    def test_the_request_names_the_book(self):
        site = Site()
        self.source.find(site, BOOK)
        where, data = site.posted[0]
        self.assertIn("/novel/clist/", where)
        self.assertEqual(data, {"bid": "566155"})


class TestTheAddressIsNotTheChapterNumber(Base):
    """У книги 402 главы, а последняя лежит по `p399.html`: заголовки
    томов в нумерации адресов не участвуют. Спутать их — значит скачать
    не те главы, и заметить это только по тексту."""

    def toc(self, site=None):
        site = site or Site()
        novel = self.source.find(site, BOOK)
        return self.source.toc(site, novel)

    def test_a_volume_header_is_not_a_chapter(self):
        found = self.toc()
        self.assertNotIn("Том 1", [c.ch_name for c in found.chapters])

    def test_the_chapter_number_comes_from_its_name(self):
        found = self.toc()
        self.assertEqual(found.chapters[0].number, 2)
        self.assertEqual(found.chapters[-1].number, 20)

    def test_the_address_counts_volumes_out(self):
        """Глава 第12章 идёт после двух заголовков томов, и в адресе у неё
        поэтому номер десять, а не двенадцать."""
        found = self.toc()
        twelfth = [c for c in found.chapters if c.number == 12][0]
        self.assertTrue(twelfth.link.endswith("/read/566155/p10.html"),
                        twelfth.link)

    def test_without_volumes_the_numbers_meet(self):
        found = self.toc(Site(listing=chapter_list(volumes=False)))
        first = found.chapters[0]
        self.assertTrue(first.link.endswith("/read/566155/p1.html"), first.link)


class TestTheBookPageStillGivesTheRest(Base):

    def setUp(self):
        super().setUp()
        self.novel = self.source.find(Site(), BOOK)

    def test_the_name_is_taken(self):
        self.assertEqual(self.novel.name, "Книга про дверь")

    def test_the_author_is_taken(self):
        self.assertEqual(self.novel.author, "Автор Такой-то")

    def test_the_cover_is_taken(self):
        self.assertIn("обложка", self.novel.cover)

    def test_the_full_address_is_kept(self):
        """Код у каждого сайта свой — адреса строятся от него."""
        self.assertEqual(self.novel.slug, BOOK)


class TestWhenTheListDoesNotCome(Base):
    """Запасного пути нет намеренно: лучше громкий отказ, чем тихая
    восьмиглавая книга."""

    def test_a_silent_site_is_named_a_broken_source(self):
        with self.assertRaises(SourceBroken) as caught:
            self.source.find(Site(breaks=True), BOOK)
        self.assertIn("/novel/clist/", str(caught.exception))

    def test_an_answer_without_the_list_is_a_broken_source(self):
        with self.assertRaises(SourceBroken):
            self.source.find(Site(listing='{"rs": 500}'), BOOK)

    def test_an_empty_list_is_a_broken_source(self):
        with self.assertRaises(SourceBroken):
            self.source.find(Site(listing='{"rs": 200, "data": []}'), BOOK)

    def test_the_last_eight_are_not_taken_as_a_consolation(self):
        """Соблазн велик — на странице ведь что-то есть."""
        with self.assertRaises(SourceBroken):
            self.source.find(Site(listing='{"rs": 200, "data": []}'), BOOK)


class TestTheChapterText(Base):

    def read(self, page=None):
        site = Site(pages={"p394.html": page or chapter_page()})
        return self.source.chapter(
            site, Chapter(number=397, post_id="",
                          link="https://ixdzs8.com/read/566155/p394.html"))

    def test_the_text_is_taken(self):
        _, text = self.read()
        self.assertIn("Абзац 1 про дверь.", text)

    def test_the_paragraphs_are_kept_apart(self):
        _, text = self.read()
        self.assertEqual(len(text.split("\n\n")), 3)

    def test_the_title_is_taken(self):
        title, _ = self.read()
        self.assertEqual(title, "第397章 Про дверь")

    def test_the_title_does_not_come_twice(self):
        """Сайт печатает его в шапке через пробел, а первой строкой —
        слитно. Из-за одного пробела заголовок оставался в тексте."""
        _, text = self.read()
        self.assertNotIn("第397章Про дверь", text)

    def test_the_end_of_chapter_mark_is_not_text(self):
        _, text = self.read()
        self.assertNotIn("本章完", text)

    def test_an_empty_chapter_is_a_broken_source(self):
        empty = ('<html><body><article class="page-content">'
                 '<h1 class="page-d-name">第1章 Пусто</h1>'
                 "<section></section></article></body></html>")
        with self.assertRaises(SourceBroken):
            self.read(empty)


if __name__ == "__main__":
    unittest.main()
