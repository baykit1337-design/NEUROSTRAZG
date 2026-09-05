"""Источник Dreamy Translations: книга лежит в потоке Next, а не в вёрстке.

Живой сайт из среды разработки закрыт, поэтому проверяется разбор
настоящей страницы, сохранённой человеком, — её структура здесь и
воспроизведена: те же теги `__next_f.push`, то же экранирование, те же
имена полей.

Проверяется наш разбор, а не чужой сайт. Поэтому здесь нет ни одной
проверки вида «а вот на этой книге девяносто семь глав»: сломается это от
любого нового выпуска. Проверяется другое — что оглавление берётся из
потока, а не из заглушек вёрстки, и что пустоту вместо книги мы не
отдаём.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources import dreamy  # noqa: E402
from net.sources.base import Novel, SourceBroken  # noqa: E402


#: Next печатает JSON плотно, без пробелов после двоеточий. Это не
#: мелочь оформления: разбор ищет ключи в тексте потока, и заготовка,
#: напечатанная просторнее настоящего сайта, проверяла бы не то.
TIGHT = (",", ":")


def push(payload: str) -> str:
    """Кусок потока — ровно так, как его пишет Next: строкой в скрипте."""
    return ('<script>self.__next_f.push([1,'
            + json.dumps(payload, ensure_ascii=False) + '])</script>')


#: Книга и оглавление в том виде, в каком их отдаёт сайт.
BOOK = {
    "id": 310,
    "title": "I Became a Counselor",
    "slug": "ibatcffhwusd",
    "synopsis": "Dear hunters...",
    "author": "국거리장단",
    "genres": ["Fantasy", "Drama"],
    "tags": ["Male Protagonist"],
    "status": "dreamy",
    "completed": True,
    "total_chapters": 97,
}

ROWS = [
    {"id": 41892, "title": "A Male Counselor is Needed", "index": 1,
     "free": True},
    {"id": 41895, "title": "Hunters Are People, Too!", "index": 2,
     "free": True},
    {"id": 41899, "title": "Top Secret Counseling", "index": 3,
     "free": False},
]


def novel_page(book=None, rows=None, cover="https://s.example/cover.jpg",
               split: bool = False) -> str:
    """Страница книги: заглушки в вёрстке, настоящие данные — в потоке."""
    body = ('d:["$","$L24",null,'
            + json.dumps({"project": book if book is not None else BOOK,
                          "chapters": ROWS if rows is None else rows,
                          "themeColors": {"R": 255},
                          "coverUrl": cover,
                          "totalViews": 374693,
                          "hasEpub": True},
                         ensure_ascii=False, separators=TIGHT)
            + "]\n")

    # Вёрстка на этом сайте — пустые полоски-заглушки: строк глав в ней
    # нет вовсе, их подставляет браузер из того же потока.
    shell = ('<div class="animate-pulse"></div>' * 10)
    if split:
        # Next режет длинную запись между скриптами: середина одной
        # строки оказывается в следующем `push`.
        half = len(body) // 2
        return shell + push(body[:half]) + push(body[half:])
    return shell + push('24:I[95026,["/x.js"],"default"]\n') + push(body)


class Fake:
    """Клиент, отдающий заранее заготовленные страницы."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.asked = []

    def get_text(self, url, params=None, headers=None, cookies=None):
        self.asked.append(url)
        if url not in self.pages:
            raise AssertionError(f"неожиданный запрос: {url}")
        return self.pages[url]


NOVEL_URL = f"{dreamy.SITE}/novel/ibatcffhwusd"


class TestWhatTheHumanBrings(unittest.TestCase):
    """Человек приносит то, что у него открыто, а открыта чаще глава."""

    def test_a_book_link_gives_the_slug(self):
        self.assertEqual(dreamy.slug_of(NOVEL_URL), "ibatcffhwusd")

    def test_a_chapter_link_gives_the_same_slug(self):
        self.assertEqual(dreamy.slug_of(f"{NOVEL_URL}/chapter/42"),
                         "ibatcffhwusd")

    def test_a_bare_slug_is_taken_as_is(self):
        self.assertEqual(dreamy.slug_of("  ibatcffhwusd  "), "ibatcffhwusd")

    def test_an_empty_input_is_refused_with_words(self):
        with self.assertRaises(SourceBroken) as caught:
            dreamy.slug_of("   ")
        self.assertIn("ссылка", str(caught.exception).lower())

    def test_someone_elses_link_is_refused_not_guessed(self):
        """Иначе из чужого адреса вышел бы слаг, которого там нет."""
        with self.assertRaises(SourceBroken) as caught:
            dreamy.slug_of("https://example.com/books/123")
        self.assertIn("novel", str(caught.exception))


class TestTheStreamIsWhereTheBookLives(unittest.TestCase):
    """Разбирается поток, а не разметка: в разметке глав нет вовсе."""

    def test_the_chapters_are_not_in_the_markup_at_all(self):
        """Проверка самой посылки: разбирай мы вёрстку — вышла бы пустота."""
        page = novel_page()
        shell = page[:page.find("<script>")]

        self.assertNotIn("A Male Counselor", shell)
        self.assertIn("A Male Counselor", dreamy.flight(page))

    def test_a_record_split_between_scripts_is_glued_back(self):
        """Next режет поток по своим границам, и запись рвётся пополам."""
        rows = dreamy.carve(dreamy.flight(novel_page(split=True)),
                            "chapters", "[")
        self.assertEqual(len(rows), len(ROWS))

    def test_a_broken_piece_does_not_cost_us_the_book(self):
        """Ронять книгу из-за одного неразобранного куска незачем."""
        page = novel_page() + '<script>self.__next_f.push([1,"\\q"])</script>'
        self.assertTrue(dreamy.carve(dreamy.flight(page), "project"))

    def test_a_page_without_the_stream_is_a_refusal_with_the_page_attached(self):
        """Чинить разбор по одному «не нашлось» нельзя: непонятно даже,
        пришла ли вообще страница сайта."""
        client = Fake({NOVEL_URL: "<html><body>ничего</body></html>"})
        with self.assertRaises(SourceBroken) as caught:
            dreamy.DreamySource().find(client, NOVEL_URL)

        self.assertIn("Next", str(caught.exception))
        self.assertIn("ничего", caught.exception.page)


class TestTheBookCard(unittest.TestCase):
    def setUp(self):
        self.source = dreamy.DreamySource()
        self.client = Fake({NOVEL_URL: novel_page()})

    def test_the_card_is_read_the_way_the_site_prints_it(self):
        book = self.source.find(self.client, NOVEL_URL)

        self.assertEqual(book.name, "I Became a Counselor")
        self.assertEqual(book.slug, "ibatcffhwusd")
        self.assertEqual(book.author, "국거리장단")
        self.assertEqual(book.total_chapters, 97)
        self.assertEqual(book.cover, "https://s.example/cover.jpg")

    def test_the_description_and_the_genres_come_along(self):
        """Спросить их потом будет не у кого: сайт может лечь, а книга в
        библиотеке останется."""
        book = self.source.find(self.client, NOVEL_URL)

        self.assertEqual(book.about, BOOK["synopsis"])
        self.assertEqual(book.genres, ["Fantasy", "Drama"])
        self.assertEqual(book.tags, ["Male Protagonist"])

    def test_the_site_tags_are_kept_apart_from_our_own(self):
        """В библиотеке теги — метки человека. Складывай мы туда же
        чужие, сайт затирал бы их при каждом обновлении."""
        book = self.source.find(self.client, NOVEL_URL)
        self.assertNotIn("genres", book.tags)

    def test_the_book_is_marked_as_english_not_guessed_later(self):
        """Оттуда книга приходит уже переведённой, и это её свойство."""
        self.assertEqual(self.source.find(self.client, NOVEL_URL).language,
                         "en")

    def test_whether_it_is_finished_is_said_in_words(self):
        going = novel_page(book={**BOOK, "completed": False})
        client = Fake({NOVEL_URL: going})

        self.assertEqual(self.source.find(self.client, NOVEL_URL).status,
                         "завершена")
        self.assertEqual(self.source.find(client, NOVEL_URL).status,
                         "выходит")

    def test_a_card_without_a_title_is_a_refusal_not_a_nameless_book(self):
        client = Fake({NOVEL_URL: novel_page(book={"id": 1})})
        with self.assertRaises(SourceBroken) as caught:
            self.source.find(client, NOVEL_URL)
        self.assertIn("карточк", str(caught.exception))


class TestTheWholeTocInOneRequest(unittest.TestCase):
    """Оглавление на сотню глав стоит одного запроса, а не сотни."""

    def setUp(self):
        self.source = dreamy.DreamySource()
        self.client = Fake({NOVEL_URL: novel_page()})
        self.book = Novel(code=310, name="I Became a Counselor",
                          slug="ibatcffhwusd", total_chapters=97)

    def test_the_whole_list_costs_one_request(self):
        self.source.toc(self.client, self.book)
        self.assertEqual(len(self.client.asked), 1)

    def test_every_chapter_gets_its_number_name_and_address(self):
        toc = self.source.toc(self.client, self.book)
        first = toc.chapters[0]

        self.assertEqual(first.number, 1)
        self.assertEqual(first.ch_name, "A Male Counselor is Needed")
        self.assertEqual(first.link, f"{NOVEL_URL}/chapter/1")

    def test_the_address_is_built_from_the_number_not_the_id(self):
        """В ссылках сайта идентификатор не участвует вовсе."""
        toc = self.source.toc(self.client, self.book)
        for one in toc.chapters:
            with self.subTest(one.number):
                self.assertTrue(one.link.endswith(f"/chapter/{one.number}"))
                self.assertNotIn(str(one.post_id), one.link)

    def test_a_paid_chapter_is_seen_from_the_list(self):
        """Иначе качалка сходит за каждой, чтобы получить отказ."""
        toc = self.source.toc(self.client, self.book)
        locked = [one.number for one in toc.chapters if one.locked]

        self.assertEqual(locked, [3])

    def test_the_range_is_cut_at_home(self):
        """Ходить за диапазоном на сайт незачем: он отдаёт список разом."""
        toc = self.source.toc(self.client, self.book, first=2, last=2)

        self.assertEqual([one.number for one in toc.chapters], [2])
        self.assertEqual(len(self.client.asked), 1)

    def test_a_hole_in_the_numbering_is_reported_as_missing(self):
        holed = [ROWS[0], {**ROWS[2], "index": 3}]
        client = Fake({NOVEL_URL: novel_page(rows=holed)})

        toc = self.source.toc(client, self.book)
        self.assertEqual(toc.missing, [2])

    def test_the_list_comes_out_in_order(self):
        shuffled = [ROWS[2], ROWS[0], ROWS[1]]
        client = Fake({NOVEL_URL: novel_page(rows=shuffled)})

        toc = self.source.toc(client, self.book)
        self.assertEqual([one.number for one in toc.chapters], [1, 2, 3])

    def test_an_empty_list_is_a_refusal_not_a_book_of_nothing(self):
        """Молчаливая полукнига хуже честного отказа."""
        client = Fake({NOVEL_URL: novel_page(rows=[])})
        with self.assertRaises(SourceBroken) as caught:
            self.source.toc(client, self.book)
        self.assertIn("списка глав", str(caught.exception))


class TestTurningMarkupIntoText(unittest.TestCase):
    """Качалке нужен текст, а не вёрстка."""

    def test_paragraphs_are_kept_apart(self):
        got = dreamy.paragraphs_of("<p>Первый</p><p>Второй</p>")
        self.assertEqual(got, "Первый\n\nВторой")

    def test_a_break_inside_a_paragraph_also_parts_the_lines(self):
        self.assertEqual(dreamy.paragraphs_of("Раз<br/>Два"), "Раз\n\nДва")

    def test_a_highlighted_word_does_not_tear_the_sentence(self):
        """Иначе фраза распалась бы по каждому выделенному слову."""
        got = dreamy.paragraphs_of("<p>Он сказал <em>тихо</em> и ушёл</p>")
        self.assertEqual(got, "Он сказал тихо и ушёл")

    def test_the_usual_entities_are_turned_back_into_characters(self):
        got = dreamy.paragraphs_of("<p>Он&#x27;s &amp; она&nbsp;тут</p>")
        self.assertEqual(got, "Он's & она тут")

    def test_empty_paragraphs_do_not_pile_up(self):
        got = dreamy.paragraphs_of("<p>Раз</p><p></p><p>  </p><p>Два</p>")
        self.assertEqual(got, "Раз\n\nДва")


class TestTheSourceIsWiredIn(unittest.TestCase):
    def test_it_is_offered_among_the_others(self):
        from net import sources

        self.assertEqual(sources.get("dreamy").key, "dreamy")
        self.assertIn("dreamy", [one.key for one in sources.all_sources()])

    def test_it_does_not_ask_for_proxies(self):
        """Сайт открытый: гонять его через пул незачем."""
        self.assertFalse(dreamy.DreamySource().needs_proxy)

    def test_its_own_links_are_told_apart(self):
        self.assertTrue(dreamy.host_is_ours(NOVEL_URL))
        self.assertFalse(dreamy.host_is_ours("https://example.com/novel/x"))


if __name__ == "__main__":
    unittest.main()


def chapter_page(body: str = "", title: str = "Глава про кота",
                 stream: dict | None = None) -> str:
    """Страница главы: текст в `.chapter-content`, как у самого сайта."""
    shell = ""
    if body:
        shell = (f'<button class="text-2xl"><span><span>{title}</span>'
                 '</span></button>'
                 f'<div class="chapter-content">{body}</div>')
    tail = ""
    if stream is not None:
        tail = push('e:["$","$L9",null,'
                    + json.dumps({"chapter": stream}, ensure_ascii=False,
                                 separators=TIGHT) + "]\n")
    else:
        tail = push('e:["$","$L9",null,{}]\n')
    return shell + tail


class TestTheChapterRowsAreInTheMarkupToo(unittest.TestCase):
    """Поправка к прежнему заблуждению.

    Сперва здесь стояло, что списка глав в разметке нет вовсе. Это
    неправда: строки лежат в скрытом блоке, а пустые полоски — только то,
    что видно до подстановки. Запасной путь по разметке держится ровно
    на этом.
    """

    def markup(self, rows=((1, "Первая"), (2, "Вторая"))) -> str:
        out = []
        for number, name in rows:
            out.append(
                f'<a data-chapter-index="{number}" '
                f'href="/novel/ibatcffhwusd/chapter/{number}">'
                f'<span class="font-medium">Ch. {number}</span>'
                f'<p class="truncate">{name}</p></a>')
        return '<div hidden id="S:2">' + "".join(out) + "</div>"

    def test_the_rows_are_read_out_of_the_markup(self):
        rows = dreamy.rows_from_markup(self.markup())

        self.assertEqual([one["index"] for one in rows], [1, 2])
        self.assertEqual(rows[0]["title"], "Первая")

    def test_the_number_is_taken_from_the_attribute_not_the_text(self):
        """В тексте ссылки стоит «Ch. 12», и разбирать его незачем."""
        rows = dreamy.rows_from_markup(self.markup(rows=[(12, "Двенадцать")]))
        self.assertEqual(rows[0]["index"], 12)

    def test_the_navigation_links_do_not_become_chapters(self):
        """На настоящей странице ссылок десятки: меню, подвал, «Читать».

        Отбор идёт по атрибуту номера, а не по тому, что это вообще
        ссылка, — иначе в книгу попали бы «Home» и «Privacy».
        """
        page = ('<a href="/">Home</a><a href="/series">Series</a>'
                '<a href="/novel/ibatcffhwusd/chapter/1">Start Reading</a>'
                '<a href="/terms">Terms</a>' + self.markup())
        rows = dreamy.rows_from_markup(page)

        self.assertEqual([one["index"] for one in rows], [1, 2])
        self.assertNotIn("Home", [one["title"] for one in rows])

    def test_a_row_without_a_number_is_skipped_not_guessed(self):
        page = ('<a data-chapter-index="" href="/x"><p>Пусто</p></a>'
                + self.markup(rows=[(3, "Третья")]))
        rows = dreamy.rows_from_markup(page)

        self.assertEqual([one["index"] for one in rows], [3])

    def test_the_markup_saves_the_toc_when_the_stream_is_gone(self):
        """Пропади поток — книга должна собраться по разметке."""
        page = self.markup() + push('24:I[1,["/x.js"],"default"]\n')
        client = Fake({NOVEL_URL: page})
        book = Novel(code=310, name="Проба", slug="ibatcffhwusd",
                     total_chapters=2)

        toc = dreamy.DreamySource().toc(client, book)
        self.assertEqual([one.number for one in toc.chapters], [1, 2])

    def test_the_stream_is_still_preferred_over_the_markup(self):
        """В потоке есть то, чего в разметке нет: метка платной главы."""
        page = novel_page() + self.markup()
        client = Fake({NOVEL_URL: page})
        book = Novel(code=310, name="Проба", slug="ibatcffhwusd",
                     total_chapters=3)

        toc = dreamy.DreamySource().toc(client, book)
        self.assertEqual([one.number for one in toc.chapters], [1, 2, 3])
        self.assertEqual([one.number for one in toc.chapters if one.locked],
                         [3])


class TestTheChapterText(unittest.TestCase):
    def setUp(self):
        self.source = dreamy.DreamySource()
        self.link = f"{NOVEL_URL}/chapter/7"
        self.chapter = dreamy.Chapter(number=7, ch_name="Из оглавления",
                                      link=self.link)

    def ask(self, page: str):
        return self.source.chapter(Fake({self.link: page}), self.chapter)

    def test_the_text_is_taken_from_the_content_block(self):
        page = chapter_page("<p>Первый абзац.</p><p>Второй абзац.</p>")
        title, body = self.ask(page)

        self.assertEqual(body, "Первый абзац.\n\nВторой абзац.")
        self.assertEqual(title, "Глава про кота")

    def test_a_translator_note_does_not_get_into_the_book(self):
        """Внутри абзаца она выглядит случайной цифрой посреди фразы."""
        page = chapter_page(
            '<p>Он взял мантру<sup class="tl-note">1</sup> и ушёл.</p>')
        _, body = self.ask(page)

        self.assertEqual(body, "Он взял мантру и ушёл.")

    def test_the_title_falls_back_to_the_one_from_the_toc(self):
        page = chapter_page("<p>Текст.</p>", title="")
        page = page.replace("<button class=\"text-2xl\"><span><span></span>"
                            "</span></button>", "")
        title, _ = self.ask(page)

        self.assertEqual(title, "Из оглавления")

    def test_the_stream_saves_the_chapter_when_the_markup_changes(self):
        """Если сайт переименует блок, текст всё ещё есть в потоке."""
        page = chapter_page(stream={"title": "Из потока",
                                    "content": "<p>Текст из потока.</p>"})
        title, body = self.ask(page)

        self.assertEqual(body, "Текст из потока.")
        self.assertEqual(title, "Из потока")

    def test_no_text_anywhere_is_a_refusal_not_an_empty_file(self):
        """Иначе качалка молча сложила бы книгу из пустых файлов."""
        with self.assertRaises(SourceBroken) as caught:
            self.ask(chapter_page())

        self.assertIn("chapter-content", str(caught.exception))
        self.assertIn("не нашлось текста", str(caught.exception))

    def test_a_chapter_without_an_address_says_so_plainly(self):
        naked = dreamy.Chapter(number=7, ch_name="Без адреса")
        with self.assertRaises(SourceBroken) as caught:
            self.source.chapter(Fake({}), naked)

        self.assertIn("без адреса", str(caught.exception))


class TestWeKnockLikeABrowser(unittest.TestCase):
    """Сайт рвал соединение на голом запросе, хотя браузеру отвечал."""

    def test_the_request_looks_like_a_navigation(self):
        for name in ("Sec-Fetch-Mode", "Sec-Fetch-Dest", "Accept-Language",
                     "Upgrade-Insecure-Requests"):
            self.assertIn(name, dreamy.HEADERS, name)
        self.assertEqual(dreamy.HEADERS["Sec-Fetch-Mode"], "navigate")

    def test_the_headers_actually_reach_the_request(self):
        seen = {}

        class Watcher(Fake):
            def get_text(self, url, params=None, headers=None, cookies=None):
                seen.update(headers or {})
                return super().get_text(url, params, headers, cookies)

        dreamy.DreamySource().find(Watcher({NOVEL_URL: novel_page()}),
                                   NOVEL_URL)
        self.assertEqual(seen.get("Sec-Fetch-Mode"), "navigate")
