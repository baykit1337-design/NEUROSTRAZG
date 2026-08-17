"""Оригинал, перевод и переключатель описания (3.1 ТЗ NEUROSTRAZH).

Название на китайском ничего не говорит, один перевод ничего не находит:
по нему книгу не отыскать ни на сайте, ни в поиске. Поэтому видно оба.

Описание — другое дело: их полсотни на срез, а читают из них два-три.
Переводится оно по кнопке и по одной книге, а переведённое помнится по
коду книги — второй раз кнопка не понадобится.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import books, titles  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"

CHINESE = "少年踏上修行之路，一路向北。"
RUSSIAN = "Юноша встаёт на путь совершенствования и идёт на север."


class FakeLlm:
    """Модель, которая всегда отвечает одним и тем же."""

    def __init__(self, answer=RUSSIAN):
        self.answer = answer
        self.calls = 0

    def generate(self, prompt, json_only=True, model="", schema=None):
        self.calls += 1
        self.last = prompt
        return self.answer

    def close(self):
        pass


class AbstractBase(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        saved = titles.ABSTRACTS_FILE
        titles.ABSTRACTS_FILE = Path(self._dir.name) / "abstracts.json"
        self.addCleanup(setattr, titles, "ABSTRACTS_FILE", saved)


class TestAbstractCache(AbstractBase):
    def test_nothing_is_known_at_the_start(self):
        self.assertEqual(titles.abstracts(), {})
        self.assertEqual(titles.abstract_of("123"), "")

    def test_a_translation_is_remembered(self):
        client = FakeLlm()
        got = titles.translate_abstract("123", CHINESE, client)

        self.assertEqual(got, RUSSIAN)
        self.assertEqual(titles.abstract_of("123"), RUSSIAN)

    def test_the_original_goes_to_the_model(self):
        client = FakeLlm()
        titles.translate_abstract("123", CHINESE, client)
        self.assertIn(CHINESE, client.last)

    def test_a_known_translation_is_not_asked_again(self):
        client = FakeLlm()
        titles.translate_abstract("123", CHINESE, client)
        titles.translate_abstract("123", CHINESE, client)
        self.assertEqual(client.calls, 1)

    def test_force_asks_again(self):
        titles.translate_abstract("123", CHINESE, FakeLlm("Первый"))
        again = titles.translate_abstract("123", CHINESE, FakeLlm("Второй"),
                                          force=True)
        self.assertEqual(again, "Второй")
        self.assertEqual(titles.abstract_of("123"), "Второй")

    def test_the_code_is_a_string_even_when_it_came_as_a_number(self):
        """Код книги в девятнадцать разрядов числом не ездит (1.2 ТЗ)."""
        titles.remember_abstract(7143038691944959011, RUSSIAN)
        self.assertEqual(titles.abstract_of("7143038691944959011"), RUSSIAN)

    def test_nothing_to_translate(self):
        with self.assertRaises(ValueError):
            titles.translate_abstract("123", "   ", FakeLlm())

    def test_an_empty_answer_is_not_remembered(self):
        with self.assertRaises(ValueError):
            titles.translate_abstract("123", CHINESE, FakeLlm("   "))
        self.assertEqual(titles.abstract_of("123"), "")

    def test_forgetting_clears_only_the_abstracts(self):
        titles.remember_abstract("123", RUSSIAN)
        titles.forget_abstracts()
        self.assertEqual(titles.abstracts(), {})

    def test_titles_and_abstracts_live_in_different_files(self):
        """Иначе перевод названия затирал бы перевод описания."""
        self.assertNotEqual(titles.TITLES_FILE, titles.ABSTRACTS_FILE)

    def test_a_broken_file_does_not_break_the_page(self):
        titles.ABSTRACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        titles.ABSTRACTS_FILE.write_text("{не json", encoding="utf-8")
        self.assertEqual(titles.abstracts(), {})


class TestAbstractRoutes(AbstractBase):
    @classmethod
    def setUpClass(cls):
        from webapp.app import app

        app.config["TESTING"] = True
        cls.app = app.test_client()

    def setUp(self):
        super().setUp()
        self._books = TemporaryDirectory()
        self.addCleanup(self._books.cleanup)
        saved = books.BOOK_DIR
        books.BOOK_DIR = Path(self._books.name)
        self.addCleanup(setattr, books, "BOOK_DIR", saved)

    def test_the_card_carries_the_translation_it_already_has(self):
        """Переключатель должен сразу знать, есть ли что показывать."""
        books.save("123", {"name": "书", "abstract": CHINESE, "book_id": "123"})
        titles.remember_abstract("123", RUSSIAN)

        body = self.app.get("/api/rank/book/123").get_json()
        self.assertEqual(body["abstract_ru"], RUSSIAN)
        self.assertEqual(body["abstract"], CHINESE)

    def test_no_translation_yet_is_an_empty_string_not_a_missing_key(self):
        books.save("123", {"name": "书", "abstract": CHINESE, "book_id": "123"})
        body = self.app.get("/api/rank/book/123").get_json()
        self.assertEqual(body["abstract_ru"], "")

    def test_a_bad_code_is_refused(self):
        res = self.app.post("/api/rank/abstract", json={"book_id": "../etc"})
        self.assertEqual(res.status_code, 400)

    def test_nothing_to_translate_is_refused(self):
        """Описания нет ни в запросе, ни в кэше карточки."""
        res = self.app.post("/api/rank/abstract", json={"book_id": "123"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("нечего", res.get_json()["error"])


class TestTitlesUi(unittest.TestCase):
    """Что показано в браузере."""

    @classmethod
    def setUpClass(cls):
        cls.page = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_the_found_book_shows_both_titles(self):
        self.assertIn("`${novel.name} / ${novel.translated}`", self.page)

    def test_the_expanded_card_shows_both_titles(self):
        self.assertIn("title.textContent = rkBothTitles({", self.tabs)

    def test_the_switch_state_survives_the_list_being_rebuilt(self):
        """Хранить выбор в самой карточке нельзя: она пересобирается."""
        self.assertIn("const rkLang = {};", self.tabs)
        self.assertIn("rkLang[row.book_id] = 'ru'", self.tabs)
        self.assertIn("rkLang[row.book_id] = 'zh'", self.tabs)

    def test_both_sides_of_the_switch_are_there(self):
        self.assertIn("orig.textContent = '原';", self.tabs)
        self.assertIn("ru_.textContent = 'RU';", self.tabs)

    def test_the_ru_side_is_hidden_until_there_is_a_translation(self):
        self.assertIn("ru_.hidden = !done;", self.tabs)

    def test_there_is_a_button_that_orders_the_translation(self):
        self.assertIn("ask.textContent = 'перевести';", self.tabs)
        self.assertIn("'/api/rank/abstract'", self.tabs)

    def test_the_button_goes_away_once_the_translation_is_there(self):
        self.assertIn("ask.hidden = !!done;", self.tabs)

    def test_a_freshly_ordered_translation_is_shown_at_once(self):
        """Иначе после «перевести» пришлось бы нажимать ещё и «RU»."""
        self.assertIn("rkLang[row.book_id] = 'ru';\n      show();", self.tabs)

    def test_the_switch_does_not_collapse_the_row(self):
        """Клик по строке раскрывает и закрывает её — кнопкам это мешает."""
        self.assertIn("orig.onclick = e => { e.stopPropagation();", self.tabs)
        self.assertIn("ru_.onclick = e => { e.stopPropagation();", self.tabs)

    def test_an_empty_description_still_says_why(self):
        self.assertIn("RK_SECRET_ABOUT", self.tabs)
        self.assertIn("RK_NO_ABOUT", self.tabs)


if __name__ == "__main__":
    unittest.main()
