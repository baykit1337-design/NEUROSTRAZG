"""Одна запись каталога — один разбор на рейтинг и на качалку.

Сети тут нет: каталог отдаёт обычный словарь, и весь этот файл про то,
как из него достают слова о книге.

Беда была тихая и оттого злая. Рейтинг умел доставать из записи описание,
жанры и метки, а качалка с того же самого ответа брала только имя,
автора и число глав. В библиотеке из-за этого раскрывать было нечего —
данные приходили тем же запросом, просто никто их оттуда не доставал.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import wordpress  # noqa: E402
from mvl import api  # noqa: E402
from net.sources import mvlrank  # noqa: E402


def book(**fields) -> dict:
    """Запись каталога: обязательное плюс то, что просят."""
    said = {"novel-code": 6615, "name": "Книга", "slug": "kniga",
            "total-chapters": 97}
    said.update(fields)
    return said


class TestWhereTheWordsLie(unittest.TestCase):
    """Свои поля WordPress кладёт то наверх, то в `acf`, то в `meta`."""

    def test_a_named_field_is_taken_first(self):
        said = wordpress.about_of(book(synopsis="Про охотниц",
                                       content="тело записи"))

        self.assertEqual(said["about"], "Про охотниц")

    def test_the_body_of_the_post_is_the_last_resort(self):
        """Переименуй сайт своё поле — описание всё равно найдётся:
        `content` у WordPress есть всегда."""
        said = wordpress.about_of(book(content="Про охотниц"))

        self.assertEqual(said["about"], "Про охотниц")

    def test_a_field_hidden_in_acf_is_found(self):
        said = wordpress.about_of(book(acf={"description": "Про охотниц"}))

        self.assertEqual(said["about"], "Про охотниц")

    def test_a_field_hidden_in_meta_is_found(self):
        said = wordpress.about_of(book(meta={"summary": "Про охотниц"}))

        self.assertEqual(said["about"], "Про охотниц")

    def test_nothing_to_say_is_said_as_nothing(self):
        said = wordpress.about_of(book())

        self.assertEqual(said, {"about": "", "genres": [], "tags": []})


class TestTheDescriptionComesOutAsText(unittest.TestCase):
    """Тело записи приходит готовым HTML, а в карточке оно текст."""

    def test_the_markup_does_not_reach_the_card(self):
        said = wordpress.about_of(book(
            content="<p>Про <b>охотниц</b></p>"))

        self.assertEqual(said["about"], "Про охотниц")

    def test_paragraphs_stay_apart(self):
        """Без этого описание слипается в простыню без единого разрыва."""
        said = wordpress.about_of(book(
            content="<p>Первый</p><p>Второй</p>"))

        self.assertEqual(said["about"], "Первый\n\nВторой")

    def test_a_line_break_is_a_line_break(self):
        said = wordpress.about_of(book(content="Первый<br>Второй"))

        self.assertIn("\n", said["about"])


class TestGenresAndTagsStayApart(unittest.TestCase):
    """В карточке это разные строки: свали их в кучу — и не понять, что
    из этого жанр."""

    def test_genres_and_tags_do_not_mix(self):
        said = wordpress.about_of(book(genre=["Фэнтези"], tags=["Гарем"]))

        self.assertEqual(said["genres"], ["Фэнтези"])
        self.assertEqual(said["tags"], ["Гарем"])

    def test_tags_are_gathered_from_every_name_they_have(self):
        said = wordpress.about_of(book(tags=["Гарем"], **{"novel-tags":
                                                          ["Академия"]}))

        self.assertEqual(said["tags"], ["Гарем", "Академия"])

    def test_a_comma_separated_line_is_a_list_too(self):
        """Сайт кладёт метки то списком, то одной строкой."""
        said = wordpress.about_of(book(tags="Гарем, Академия"))

        self.assertEqual(said["tags"], ["Гарем", "Академия"])


class TestTheDownloaderReadsWhatTheRatingReads(unittest.TestCase):
    """Главная проверка этого файла.

    Разойдись разбор снова — рейтинг покажет описание, а библиотека
    останется пустой, и заметить это можно будет только глазами.
    """

    ITEM = book(synopsis="<p>Про охотниц и их беды</p>",
                genre=["Фэнтези"], tags=["Гарем"],
                **{"author-name": "국거리장단", "status": "Ongoing",
                   "language": "EN"})

    def rating_says(self) -> dict:
        """Что о книге скажет раскрытая строка рейтинга."""
        answer = SimpleNamespace(json=lambda: [self.ITEM])
        client = SimpleNamespace(get=lambda url, params=None: answer)
        return mvlrank.book(client, "6615", slug="kniga")

    def test_the_description_is_the_same_on_both_sides(self):
        self.assertEqual(api._novel_from_json(self.ITEM).about,
                         self.rating_says()["abstract"])

    def test_so_are_the_genres_and_the_tags(self):
        novel = api._novel_from_json(self.ITEM)

        self.assertEqual(novel.genres + novel.tags,
                         self.rating_says()["tags"])

    def test_and_the_cover_is_built_by_the_same_rule(self):
        """Разойдись правило — в библиотеке была бы битая картинка."""
        self.assertEqual(api._novel_from_json(self.ITEM).cover,
                         self.rating_says()["cover"])


class TestWhatTheDownloaderNowCarries(unittest.TestCase):
    """То, ради чего всё и делалось: библиотеке есть что разворачивать."""

    def test_the_book_carries_its_description(self):
        novel = api._novel_from_json(book(synopsis="Про охотниц"))

        self.assertEqual(novel.about, "Про охотниц")

    def test_the_book_carries_its_genres_and_tags(self):
        novel = api._novel_from_json(book(genre=["Фэнтези"], tags=["Гарем"]))

        self.assertEqual(novel.genres, ["Фэнтези"])
        self.assertEqual(novel.tags, ["Гарем"])

    def test_the_cover_is_built_from_the_code(self):
        """Отдельного поля под обложку в каталоге нет, а картинки лежат
        по одному правилу."""
        novel = api._novel_from_json(book())

        self.assertIn("6615", novel.cover)

    def test_it_all_reaches_the_dictionary_the_page_reads(self):
        said = api._novel_from_json(book(synopsis="Про охотниц",
                                         genre=["Фэнтези"])).to_dict()

        self.assertEqual(said["about"], "Про охотниц")
        self.assertEqual(said["genres"], ["Фэнтези"])

    def test_a_record_without_a_code_is_still_refused(self):
        """Работающее должно остаться работающим: запись без кода —
        не книга, и новые поля этого не меняют."""
        self.assertIsNone(api._novel_from_json({"name": "Книга"}))


if __name__ == "__main__":
    unittest.main()
