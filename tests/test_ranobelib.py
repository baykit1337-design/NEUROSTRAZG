"""Источник RanobeLIB: книга приходит из API, а не со страницы.

Живой сайт для проверки не нужен и недоступен: клиент здесь поддельный и
отвечает так же, как API. Закрепляется разбор — что из какого поля
берётся и что происходит, когда поля нет.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources import get as source_of  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402
from net.sources.ranobelib import RanobeLibSource, paragraphs_of, slug_of  # noqa: E402


class Answer:
    def __init__(self, body):
        self.text = json.dumps(body, ensure_ascii=False)

    def json(self):
        return json.loads(self.text)


class FakeClient:
    """Отвечает по адресу, запоминая, о чём спрашивали."""

    def __init__(self, replies):
        self.replies = replies
        self.asked = []

    def get(self, url, params=None, headers=None, cookies=None):
        self.asked.append((url, params, headers))
        for mark, body in self.replies.items():
            if mark in url:
                return Answer(body)
        raise AssertionError(f"неожиданный запрос: {url}")


BOOK = {
    "id": 12345,
    "slug": "nazvanie",
    "slug_url": "12345--nazvanie",
    "name": "Original Name",
    "rus_name": "Название по-русски",
    "cover": {"default": "https://example.invalid/cover.jpg"},
    "status": {"label": "Выпускается"},
    "authors": [{"name": "Автор Первый"}, {"name": "Автор Второй"}],
}

CHAPTERS = [
    {"volume": "1", "number": "1", "name": "Начало",
     "branches": [{"branch_id": 77, "moderation": {"id": 3}}]},
    {"volume": "1", "number": "2", "name": "Продолжение", "branches": []},
]

DOC = {"type": "doc", "content": [
    {"type": "paragraph", "content": [
        {"type": "text", "text": "Первый абзац главы, "},
        {"type": "bold", "content": [{"type": "text", "text": "с выделением"}]},
        {"type": "text", "text": "."},
    ]},
    {"type": "paragraph", "content": [{"type": "text", "text": "Второй абзац."}]},
]}


class TestSlug(unittest.TestCase):
    def test_a_link_gives_the_slug(self):
        self.assertEqual(
            slug_of("https://ranobelib.me/ru/book/12345--nazvanie"),
            "12345--nazvanie")

    def test_the_number_in_front_is_kept(self):
        """API принимает слаг целиком и по обрезанному отвечает отказом."""
        self.assertEqual(slug_of("12345--nazvanie"), "12345--nazvanie")

    def test_a_link_to_a_chapter_still_gives_the_book(self):
        self.assertEqual(
            slug_of("https://ranobelib.me/ru/book/12345--nazvanie/read/v1/c7"),
            "12345--nazvanie")

    def test_a_link_without_a_book_says_so(self):
        with self.assertRaises(SourceBroken):
            slug_of("https://ranobelib.me/ru/manga/12345--drugoe/nothing")

    def test_an_empty_query_says_so(self):
        with self.assertRaises(SourceBroken):
            slug_of("   ")


class TestParagraphs(unittest.TestCase):
    def test_a_tree_of_nodes_becomes_paragraphs(self):
        self.assertEqual(paragraphs_of(DOC),
                         ["Первый абзац главы, с выделением.", "Второй абзац."])

    def test_marks_inside_a_line_do_not_break_it(self):
        """Жирный и курсив — обёртки вокруг текста. Рвать на них абзац
        значило бы разложить фразу на куски по каждому слову."""
        self.assertEqual(len(paragraphs_of(DOC)), 2)

    def test_a_line_without_a_closing_node_is_not_lost(self):
        loose = {"type": "doc", "content": [
            {"type": "text", "text": "Голая строка без абзаца."}]}
        self.assertEqual(paragraphs_of(loose), ["Голая строка без абзаца."])

    def test_empty_content_gives_nothing(self):
        self.assertEqual(paragraphs_of({"type": "doc", "content": []}), [])


class TestFind(unittest.TestCase):
    def setUp(self):
        self.source = RanobeLibSource()

    def test_it_takes_the_russian_name(self):
        client = FakeClient({"/manga/12345--nazvanie": {"data": BOOK}})
        novel = self.source.find(client, "12345--nazvanie")

        self.assertEqual(novel.name, "Название по-русски")
        self.assertEqual(novel.author, "Автор Первый, Автор Второй")
        self.assertEqual(novel.language, "ru")
        self.assertTrue(novel.cover)

    def test_it_asks_for_the_fields_it_needs(self):
        """API отдаёт только запрошенные поля: без списка описание не
        придёт вовсе."""
        client = FakeClient({"/manga/12345--nazvanie": {"data": BOOK}})
        self.source.find(client, "12345--nazvanie")

        _, params, headers = client.asked[0]
        self.assertIn(("fields[]", "summary"), list(params))
        self.assertIn("ranobelib.me", headers["Referer"])

    def test_an_answer_without_data_is_a_broken_source(self):
        """«Сайт не ответил» лечится повтором, «структура другая» — нет."""
        client = FakeClient({"/manga/": {"whatever": 1}})
        with self.assertRaises(SourceBroken):
            self.source.find(client, "12345--nazvanie")


class TestTocAndChapter(unittest.TestCase):
    def setUp(self):
        self.source = RanobeLibSource()
        self.client = FakeClient({
            "/chapters": {"data": CHAPTERS},
            "/chapter": {"data": {"content": DOC, "name": "Начало"}},
            "/manga/12345--nazvanie": {"data": BOOK},
        })
        self.novel = self.source.find(self.client, "12345--nazvanie")

    def test_the_toc_numbers_chapters_in_a_row(self):
        """Своего сквозного номера у главы нет: у API это том плюс номер
        внутри тома, а качалке нужен один растущий."""
        toc = self.source.toc(self.client, self.novel)
        self.assertEqual([c.number for c in toc.chapters], [1, 2])
        self.assertEqual(toc.chapters[0].ch_name, "Начало")

    def test_the_toc_keeps_volume_and_number_for_the_chapter_request(self):
        toc = self.source.toc(self.client, self.novel)
        self.assertIn("|1|1|77", str(toc.chapters[0].post_id))

    def test_a_range_takes_only_what_was_asked(self):
        toc = self.source.toc(self.client, self.novel, first=2)
        self.assertEqual([c.number for c in toc.chapters], [2])

    def test_the_chapter_comes_back_as_text(self):
        toc = self.source.toc(self.client, self.novel)
        title, text = self.source.chapter(self.client, toc.chapters[0])

        self.assertEqual(title, "Начало")
        self.assertIn("Первый абзац главы, с выделением.", text)
        self.assertIn("\n\n", text)

    def test_the_branch_is_passed_when_there_is_one(self):
        """У книги бывает несколько команд перевода, и глава есть у
        каждой. Без ветки API отдаст не тот перевод."""
        toc = self.source.toc(self.client, self.novel)
        self.source.chapter(self.client, toc.chapters[0])

        _, params, _ = self.client.asked[-1]
        self.assertEqual(params["branch_id"], "77")

    def test_without_a_branch_it_is_not_passed(self):
        toc = self.source.toc(self.client, self.novel)
        self.source.chapter(self.client, toc.chapters[1])

        _, params, _ = self.client.asked[-1]
        self.assertNotIn("branch_id", params)

    def test_a_branch_on_moderation_is_skipped(self):
        """Ветка на модерации — ещё не выложенный перевод."""
        raw = [{"volume": "1", "number": "1", "name": "Начало", "branches": [
            {"branch_id": 5, "moderation": {"id": 0}},
            {"branch_id": 9, "moderation": {"id": 3}},
        ]}]
        client = FakeClient({"/chapters": {"data": raw}})
        toc = self.source.toc(client, self.novel)
        self.assertIn("|9", str(toc.chapters[0].post_id))

    def test_an_old_chapter_without_an_address_says_what_to_do(self):
        from mvl.api import Chapter

        with self.assertRaises(SourceBroken) as caught:
            self.source.chapter(self.client, Chapter(number=1, post_id="1"))
        self.assertIn("оглавление", str(caught.exception))


class TestRegistered(unittest.TestCase):
    def test_the_downloader_knows_it_by_key(self):
        self.assertIsInstance(source_of("ranobelib"), RanobeLibSource)

    def test_it_says_it_needs_no_proxy(self):
        """API открыт и отвечает напрямую. Обещать нужду в прокси значило
        бы гонять человека настраивать список впустую."""
        self.assertFalse(RanobeLibSource().needs_proxy)


if __name__ == "__main__":
    unittest.main()
