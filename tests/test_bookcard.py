"""Раскрытие строки рейтинга и кэш карточек (2.4 ТЗ NEUROSTRAZH).

В срезе нет ни описания, ни жанра, а без них непонятно, стоит ли книгу
брать. Подробности со страницы книги подтягиваются лениво — по первому
раскрытию — и кладутся в свой кэш: ходить на сайт при каждом клике
незачем, описание меняется раз в месяц.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources import rank as rank_net  # noqa: E402
from ops import books  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"


def page(book: dict) -> str:
    """Страница книги в том виде, в каком её отдаёт сайт."""
    state = {"page": {"bookInfo": book}}
    return ("<html><body><script>window.__INITIAL_STATE__ = "
            + json.dumps(state, ensure_ascii=False) + ";</script></body></html>")


BOOK = {
    "bookId": "7276663560335001631",
    "bookName": "Приручитель насекомых",
    "author": "Некий Автор",
    "authorId": "9911",
    "abstract": "Юный охотник просыпается в мире приручённых тварей.",
    "category": "Западное фэнтези",
    "tags": ["приручение", "система"],
    "wordNumber": 2540000,
    "serialCount": 1204,
    "creationStatus": "1",
    "lastChapterTitle": "Глава 1204. Развязка",
    "lastChapterUpdateTime": 1723000000,
    "firstOnlineTime": 1690000000,
    "firstChapterId": "111",
    "lastChapterId": "999",
    "thumbUri": "https://site/cover.webp?x-expires=1",
}


class TestBookPage(unittest.TestCase):
    """Разбор страницы книги."""

    def found(self, book=None):
        return rank_net.book_page(page(book if book is not None else BOOK))

    def test_every_field_from_the_spec(self):
        found = self.found()
        self.assertEqual(found["book_id"], "7276663560335001631")
        self.assertEqual(found["name"], "Приручитель насекомых")
        self.assertEqual(found["author"], "Некий Автор")
        self.assertEqual(found["author_id"], "9911")
        self.assertIn("охотник", found["abstract"])
        self.assertEqual(found["category"], "Западное фэнтези")
        self.assertEqual(found["tags"], ["приручение", "система"])
        self.assertEqual(found["words"], 2540000)
        self.assertEqual(found["chapters"], 1204)
        self.assertEqual(found["status"], "продолжается")
        self.assertEqual(found["last_chapter"], "Глава 1204. Развязка")
        self.assertEqual(found["first_chapter_id"], "111")
        self.assertEqual(found["last_chapter_id"], "999")

    def test_a_finished_book_is_marked_so(self):
        self.assertEqual(self.found({**BOOK, "creationStatus": "0"})["status"],
                         "завершена")

    def test_the_link_is_built_from_the_code(self):
        self.assertTrue(self.found()["link"].endswith("7276663560335001631"))

    def test_tags_written_as_one_string_are_split(self):
        found = self.found({**BOOK, "tags": "приручение,система, рост силы"})
        self.assertEqual(found["tags"], ["приручение", "система", "рост силы"])

    def test_a_renamed_field_costs_only_that_field(self):
        """Сайт переименовывает ключи — терять из-за одного всю карточку
        незачем."""
        found = self.found({"bookId": "7", "book_name": "Книга"})
        self.assertEqual(found["book_id"], "7")
        self.assertEqual(found["name"], "Книга")
        self.assertEqual(found["tags"], [])

    def test_an_encrypted_description_is_marked(self):
        """Пустое место вместо описания выглядит как поломка."""
        found = self.found({**BOOK, "abstract": ""})
        self.assertTrue(found["secret"])

    def test_a_page_without_the_state_object_says_so(self):
        with self.assertRaises(rank_net.Diagnosis):
            rank_net.book_page("<html>пусто</html>")


class BooksBase(unittest.TestCase):
    """Кэш подменяется: настоящую папку data трогать нельзя."""

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.was = books.BOOK_DIR
        books.BOOK_DIR = Path(self.dir.name) / "books"
        self.addCleanup(lambda: setattr(books, "BOOK_DIR", self.was))


class TestCache(BooksBase):
    def test_a_card_is_saved_and_read_back(self):
        books.save("123", {"name": "Книга"})
        self.assertEqual(books.load("123")["name"], "Книга")

    def test_it_lands_where_the_spec_says(self):
        books.save("123", {"name": "Книга"})
        self.assertTrue((books.BOOK_DIR / "123.json").exists())

    def test_a_missing_card_is_not_a_crash(self):
        self.assertIsNone(books.load("999"))

    def test_a_stale_card_is_read_again(self):
        books.save("123", {"name": "Книга"})
        path = books.BOOK_DIR / "123.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["saved_at"] = time.time() - 999999
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNone(books.load("123"))

    def test_a_stale_card_can_still_be_taken_on_purpose(self):
        books.save("123", {"name": "Книга"})
        self.assertIsNotNone(books.load("123", max_age_hours=0))

    def test_a_broken_card_is_not_a_crash(self):
        books.BOOK_DIR.mkdir(parents=True, exist_ok=True)
        (books.BOOK_DIR / "123.json").write_text("{это не json",
                                                 encoding="utf-8")
        self.assertIsNone(books.load("123"))

    def test_a_half_written_card_never_appears(self):
        books.save("123", {"name": "Книга"})
        leftovers = [p for p in books.BOOK_DIR.iterdir()
                     if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_a_bad_code_has_no_place_to_go(self):
        self.assertIsNone(books.path_for("../../etc/passwd"))
        self.assertIsNone(books.load("../x"))

    def test_a_card_can_be_thrown_away(self):
        books.save("123", {"name": "Книга"})
        self.assertTrue(books.forget("123"))
        self.assertIsNone(books.load("123"))

    def test_the_cache_can_be_counted(self):
        books.save("123", {"name": "Книга"})
        books.save("124", {"name": "Другая"})
        self.assertEqual(books.state()["count"], 2)


class TestBookRoute(BooksBase):
    @classmethod
    def setUpClass(cls):
        from webapp.app import app

        app.config["TESTING"] = True
        cls.app = app.test_client()

    def test_a_cached_card_does_not_go_to_the_site(self):
        books.save("123", {"name": "Книга", "book_id": "123"})
        body = self.app.get("/api/rank/book/123").get_json()
        self.assertTrue(body["cached"])
        self.assertEqual(body["name"], "Книга")

    def test_a_bad_code_is_refused(self):
        res = self.app.get("/api/rank/book/..%2F..%2Fetc")
        self.assertIn(res.status_code, (400, 404))

    def test_asking_for_fresh_data_skips_the_cache(self):
        """Кэш можно обойти, когда книга явно изменилась."""
        books.save("123", {"name": "Старое", "book_id": "123"})
        res = self.app.get("/api/rank/book/123?fresh=1")
        # Сети в тесте нет, поэтому важен сам факт похода за ней.
        self.assertNotEqual(res.status_code, 200)


class TestExpandUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_a_click_on_the_row_opens_it(self):
        self.assertIn("tr.onclick = () => rkToggle(row, tr)", self.tabs)

    def test_the_card_goes_under_its_row_not_above(self):
        render = self.tabs.split("function rkRender()", 1)[1]
        self.assertLess(render.index("box.append(tr);"),
                        render.index("box.append(rkDetailsBox(row));"))

    def test_only_one_row_is_open_at_a_time(self):
        self.assertIn("if(rkOpenId && rkOpenId !== row.book_id)", self.tabs)

    def test_the_data_is_pulled_lazily(self):
        toggle = self.tabs.split("async function rkToggle", 1)[1]
        self.assertIn("if(!box.dataset.filled)", toggle)
        self.assertIn("/api/rank/book/", toggle)

    def test_opening_is_smooth(self):
        self.assertIn("transition:max-height .28s ease", self.page)

    def test_the_buttons_from_the_spec_are_there(self):
        body = self.tabs.split("function rkCardBody(row, data)", 1)[1]
        for name in ("'Скачать'", "'Открыть на сайте'", "'Скопировать'"):
            with self.subTest(name=name):
                self.assertIn(name, body)

    def test_buttons_inside_the_row_do_not_open_it(self):
        """Иначе «скачать» ещё и раскрывала бы карточку."""
        self.assertIn("get.onclick = e => { e.stopPropagation(); rkPick(row); }",
                      self.tabs)

    def test_an_unreadable_description_is_named_not_left_blank(self):
        self.assertIn("Описание зашифровано шрифтом", self.tabs)

    def test_tags_are_shown_as_chips(self):
        self.assertIn("rkcard-tags", self.tabs)
        self.assertIn("#rkTable .rkcard-tags{", self.page)

    def test_the_bigger_cover_comes_from_the_cache_too(self):
        self.assertIn("cover.src = `/api/rank/cover/", self.tabs)

    def test_calm_mode_turns_the_animation_off(self):
        block = self.page.split("#rkTable .rkcard{", 1)[1]
        self.assertIn("prefers-reduced-motion", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
