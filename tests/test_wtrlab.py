"""WTR-LAB: книга приходит уже переведённой, но не страницей.

Оглавление в вёрстку не попадает вовсе, а текст главы приходит
POST-запросом списком абзацев, где вместо имён стоят метки `※7⛬`. Всё
это проверяется здесь: не подставить имена значит положить в книгу текст
с закорючками вместо имён и заметить это только при чтении.

Правила разбора (адреса запросов, вид тела и имена полей ответа) взяты
из расширения `WebToEpub` (GPL-3.0). Тексты в заготовках свои:
проверяется разбор, а не книги.

Сайт из окружения разработки недоступен, поэтому сеть подставляется
тестом.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.api import Chapter, Novel  # noqa: E402
from net import sources  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402
from net.sources.wtrlab import ChapterNotTranslated, WtrlabSource  # noqa: E402

BOOK = "https://wtr-lab.com/en/novel/8093/the-wizard-is-chasing-the-truth"


def book_page(title="The wizard is chasing the truth", count=829) -> str:
    """Страница книги: вся начинка в одном скрипте, как у Next.js."""
    begin = {"props": {"pageProps": {"serie": {"serie_data": {
        "raw_id": 8093,
        "chapter_count": count,
        "data": {"title": title, "author": "Gan Fan",
                 "image": "https://img.wtr-lab.com/cdn/series/x.webp"},
    }}}}}
    return ('<html><body><h1>Что-то</h1>'
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(begin) + "</script></body></html>")


def chapter_list(count=3) -> dict:
    return {"chapters": [
        {"serie_id": 7993, "id": 100 + n, "order": n,
         "title": f"Глава {n}", "name": f"第{n}章"}
        for n in range(1, count + 1)]}


def chapter_body(rows, terms=(), patch=(), title="Глава 829") -> dict:
    return {"chapter": {"title": title},
            "data": {"data": {"body": list(rows),
                              "glossary_data": {"terms": list(terms)},
                              "patch": list(patch)}}}


class Reply:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeClient:
    """Три пути сразу: страница книги, список глав и текст главы."""

    def __init__(self, page="", listing=None, body=None):
        self.page = page
        self.listing = listing
        self.body = body
        self.asked: list[str] = []
        self.posted: list[tuple] = []

    def get_text(self, url, params=None, headers=None):
        self.asked.append(url)
        return self.page

    def get(self, url, params=None, headers=None):
        self.asked.append(url)
        return Reply(self.listing)

    def post(self, url, data=None, headers=None, cookies=None):
        self.posted.append((url, data, headers))
        if isinstance(self.body, Exception):
            raise self.body
        return Reply(self.body)


class TestItIsOfferedAsItsOwnSource(unittest.TestCase):
    def test_the_source_is_in_the_list(self):
        self.assertIn("wtrlab", [one.key for one in sources.all_sources()])

    def test_it_is_not_the_default(self):
        """Перевод чужой — размен делает человек, а не программа."""
        self.assertNotEqual(sources.get("").key, "wtrlab")

    def test_the_hint_warns_it_is_slow(self):
        """Книга на восемьсот глав качается отсюда часами, и узнать об
        этом лучше до запуска, а не наутро."""
        said = sources.get("wtrlab").hint
        self.assertIn("пауза", said.lower())

    def test_the_hint_says_the_translation_is_not_ours(self):
        self.assertIn("англ", sources.get("wtrlab").hint.lower())

    def test_it_needs_no_proxy(self):
        self.assertFalse(sources.get("wtrlab").needs_proxy)

    def test_it_asks_for_a_longer_pause_than_the_rest(self):
        """Сервер переводит главу в момент запроса: на общей паузе
        главы приходят пустыми."""
        from mvl import client as client_mod

        _, high = client_mod.SITE_PAUSE_RANGE
        self.assertGreater(sources.get("wtrlab").pause, high)

    def test_the_others_keep_the_common_pause(self):
        others = [one.key for one in sources.all_sources()
                  if one.key != "wtrlab" and one.pause]
        self.assertEqual(others, [])


class TestTheAddress(unittest.TestCase):
    def setUp(self):
        self.source = WtrlabSource()

    def test_a_book_address_is_taken_apart(self):
        self.assertEqual(self.source._parts(BOOK),
                         ("en", "8093", "the-wizard-is-chasing-the-truth"))

    def test_a_chapter_address_gives_the_same_book(self):
        """Человек копирует ссылку с той страницы, где читает."""
        self.assertEqual(self.source._parts(BOOK + "/chapter-829"),
                         ("en", "8093", "the-wizard-is-chasing-the-truth"))

    def test_a_tab_in_the_address_is_not_part_of_the_slug(self):
        self.assertEqual(self.source._parts(BOOK + "?tab=toc")[2],
                         "the-wizard-is-chasing-the-truth")

    def test_a_stranger_address_is_refused_by_name(self):
        with self.assertRaises(SourceBroken) as caught:
            self.source._demand_parts("https://example.com/book/1")
        self.assertIn("wtr-lab.com", str(caught.exception))


class TestTheBook(unittest.TestCase):
    def setUp(self):
        self.source = WtrlabSource()

    def test_the_book_is_read_from_the_page_filling(self):
        """Разбирать вёрстку нечего: оглавление в неё не попадает."""
        found = self.source.find(FakeClient(page=book_page()), BOOK)
        self.assertEqual(found.name, "The wizard is chasing the truth")
        self.assertEqual(found.code, 8093)
        self.assertEqual(found.author, "Gan Fan")
        self.assertEqual(found.total_chapters, 829)
        self.assertIn("img.wtr-lab.com", found.cover)
        self.assertEqual(found.language, "en")

    def test_the_whole_address_is_kept(self):
        """Язык и слаг из кода не выводятся — потерять их нельзя."""
        found = self.source.find(FakeClient(page=book_page()), BOOK)
        self.assertEqual(found.slug, BOOK)

    def test_a_page_without_filling_is_refused_with_the_page_attached(self):
        """Чинить разбор по одному «не нашлось» нельзя: непонятно даже,
        пришла ли страница."""
        with self.assertRaises(SourceBroken) as caught:
            self.source.find(FakeClient(page="<html>ничего</html>"), BOOK)
        self.assertIn("__NEXT_DATA__", str(caught.exception))
        self.assertIn("ничего", caught.exception.page)

    def test_filling_that_is_not_json_is_refused(self):
        page = ('<script id="__NEXT_DATA__" type="application/json">'
                "{это не json}</script>")
        with self.assertRaises(SourceBroken):
            self.source.find(FakeClient(page=page), BOOK)


class TestTheChapterList(unittest.TestCase):
    def setUp(self):
        self.source = WtrlabSource()
        self.novel = Novel(code=8093, name="Книга", slug=BOOK,
                           total_chapters=3)

    def test_the_list_comes_from_its_own_request(self):
        client = FakeClient(listing=chapter_list())
        toc = self.source.toc(client, self.novel)
        self.assertEqual(len(toc.chapters), 3)
        self.assertTrue(any("/api/chapters/8093" in url
                            for url in client.asked))

    def test_every_chapter_gets_the_address_it_is_read_at(self):
        toc = self.source.toc(FakeClient(listing=chapter_list()), self.novel)
        self.assertEqual(toc.chapters[0].link, BOOK + "/chapter-1")
        self.assertEqual(toc.chapters[0].ch_name, "Глава 1")

    def test_the_range_is_honoured(self):
        toc = self.source.toc(FakeClient(listing=chapter_list(9)),
                              self.novel, first=3, last=5)
        self.assertEqual([one.number for one in toc.chapters], [3, 4, 5])

    def test_an_empty_list_is_a_refusal_not_an_empty_book(self):
        with self.assertRaises(SourceBroken):
            self.source.toc(FakeClient(listing={"chapters": []}), self.novel)

    def test_a_list_where_no_row_has_a_number_is_a_refusal(self):
        """Список пришёл, а номеров в нём нет: адрес главы строится по
        номеру, и без него книга собралась бы из нуля глав — молча."""
        listing = {"chapters": [{"id": 5, "title": "Глава"},
                                {"id": 6, "title": "Ещё"}]}
        with self.assertRaises(SourceBroken) as caught:
            self.source.toc(FakeClient(listing=listing), self.novel)
        self.assertIn("номер", str(caught.exception))

    def test_an_answer_of_another_shape_is_a_refusal(self):
        with self.assertRaises(SourceBroken):
            self.source.toc(FakeClient(listing={"data": []}), self.novel)

    def test_a_book_without_a_kept_address_says_so(self):
        naked = Novel(code=8093, name="Книга", slug="", total_chapters=3)
        with self.assertRaises(SourceBroken) as caught:
            self.source.toc(FakeClient(listing=chapter_list()), naked)
        self.assertIn("найдите её заново", str(caught.exception))


class TestTheChapterText(unittest.TestCase):
    def setUp(self):
        self.source = WtrlabSource()
        self.chapter = Chapter(number=829, post_id=829, ch_name="Глава",
                               link=BOOK + "/chapter-829")

    def get(self, payload):
        return self.source.chapter(FakeClient(body=payload), self.chapter)

    def test_the_paragraphs_become_the_chapter(self):
        title, text = self.get(chapter_body(["Первый.", "Второй."]))
        self.assertEqual(title, "Глава 829")
        self.assertEqual(text, "Первый.\n\nВторой.")

    def test_the_request_says_what_the_site_expects(self):
        client = FakeClient(body=chapter_body(["Абзац."]))
        self.source.chapter(client, self.chapter)
        url, body, headers = client.posted[0]
        self.assertIn("/api/reader/get", url)
        sent = json.loads(body)
        self.assertEqual(sent["raw_id"], "8093")
        self.assertEqual(sent["chapter_no"], "829")
        self.assertEqual(sent["language"], "en")
        self.assertEqual(sent["translate"], "ai")
        self.assertIn("json", headers["Content-Type"])

    def test_the_marks_are_replaced_by_the_names(self):
        """Не подставить имена значит положить в книгу закорючки и
        заметить это только при чтении."""
        _, text = self.get(chapter_body(
            ["※0⛬ смотрел на ※1⛬."],
            terms=[["Wilde"], ["Ashen"]]))
        self.assertEqual(text, "Wilde смотрел на Ashen.")

    def test_the_other_closing_mark_works_too(self):
        """Сайт ставит то один знак, то другой."""
        _, text = self.get(chapter_body(["※0〓 ушёл."], terms=[["Wilde"]]))
        self.assertEqual(text, "Wilde ушёл.")

    def test_a_mark_without_a_name_stays_visible(self):
        """Съесть имя молча хуже, чем оставить метку на виду."""
        _, text = self.get(chapter_body(["※0⛬ ушёл."], terms=[[]]))
        self.assertIn("※0⛬", text)

    def test_the_patches_are_applied_after_the_names(self):
        _, text = self.get(chapter_body(
            ["※0⛬ сказал 巫师 негромко."],
            terms=[["Wilde"]], patch=[{"zh": "巫师", "en": "wizard"}]))
        self.assertIn("Wilde", text)
        self.assertIn("wizard", text)
        self.assertNotIn("巫师", text)

    def test_pictures_do_not_become_paragraphs(self):
        _, text = self.get(chapter_body(["Первый.", "[image]", "Второй."]))
        self.assertEqual(text, "Первый.\n\nВторой.")

    def test_a_chapter_the_machine_has_not_done_is_a_skip(self):
        """Повторять нечего: перевода просто нет."""
        with self.assertRaises(ChapterNotTranslated):
            self.get({"code": "CHAPTER_LOCKED"})

    def test_an_empty_chapter_is_a_skip_too(self):
        """Так сайт отвечает, когда его торопят."""
        with self.assertRaises(ChapterNotTranslated):
            self.get(chapter_body([]))

    def test_a_robot_check_is_named_for_what_it_is(self):
        with self.assertRaises(SourceBroken) as caught:
            self.get({"requireTurnstile": True})
        self.assertIn("не робот", str(caught.exception))

    def test_a_skipped_chapter_does_not_bring_the_book_down(self):
        """Качалка отмечает такую главу пропуском и идёт дальше."""
        from mvl.downloader import _is_paid

        self.assertTrue(_is_paid(ChapterNotTranslated("нет перевода")))


class Waits:
    """Флажок остановки, который запоминает, сколько его просили ждать."""

    def __init__(self):
        self.waited: list[float] = []

    def wait(self, seconds):
        self.waited.append(seconds)
        return False


class TestTheSourceCanAskToSlowDown(unittest.TestCase):
    """Пауза между главами общая — 2-4 секунды. Здесь её мало: сервер
    переводит главу в момент запроса, и на общей паузе главы приходят
    пустыми. Проверяем, что просьба источника доезжает до качалки — и
    что притормозить он может, а разогнать нет."""

    def setUp(self):
        from mvl import client as client_mod
        from mvl.downloader import Downloader

        self.pause = Downloader._pause
        self.was = client_mod.SITE_PAUSE_RANGE
        client_mod.SITE_PAUSE_RANGE = (2.0, 4.0)
        self.addCleanup(setattr, client_mod, "SITE_PAUSE_RANGE", self.was)

    def waited(self, asked, multiplier=1.0):
        import types

        source = types.SimpleNamespace(pause=asked)
        cancel = Waits()
        self.pause(types.SimpleNamespace(
            source=source, cancel=cancel, pause_multiplier=multiplier))
        return cancel.waited[0]

    def test_a_slow_source_is_waited_out(self):
        self.assertGreaterEqual(self.waited(WtrlabSource.pause),
                                WtrlabSource.pause)

    def test_a_source_cannot_make_the_pause_shorter(self):
        """Источник вправе притормозить, но не вправе разогнать."""
        self.assertGreaterEqual(self.waited(0.1), 2.0)

    def test_a_source_that_asks_for_nothing_keeps_the_common_pause(self):
        seen = self.waited(0.0)
        self.assertGreaterEqual(seen, 2.0)
        self.assertLessEqual(seen, 4.0)

    def test_the_429_multiplier_still_applies_on_top(self):
        """После серии отказов пауза растёт — и у медленного тоже."""
        self.assertGreaterEqual(self.waited(WtrlabSource.pause, multiplier=2.0),
                                WtrlabSource.pause * 2)


if __name__ == "__main__":
    unittest.main()
