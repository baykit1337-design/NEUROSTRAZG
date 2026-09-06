"""Карточка книги по-русски.

Каталог отдаёт жанры, теги, статус и язык по-английски, и карточка была
английской целиком: «Ongoing · Chinese», «Accelerated Growth»,
«Overpowered Protagonist». Читает её русскоязычный человек — он про это и
написал.

Словарь, а не модель: список слов у каталога закрытый и повторяется из
книги в книгу. Гонять его через платную модель на каждой книге значило бы
платить за один и тот же перевод сто раз и получать его каждый раз чуть
другим — а теги должны совпадать буквально, по ним ищут.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ru  # noqa: E402
from ops import library  # noqa: E402


class TestTheWordsFromTheScreen(unittest.TestCase):
    """Ровно те слова, что человек прислал на снимке экрана."""

    def test_the_genres_are_russian(self):
        said = ru.genres(["Action", "Adventure", "Fantasy", "Sci-fi"])
        self.assertEqual(said, ["боевик", "приключения", "фэнтези",
                                "фантастика"])

    def test_the_tags_are_russian(self):
        said = ru.tags(["Accelerated Growth", "Advanced technology",
                        "Alternate World", "Overpowered Protagonist",
                        "Transmigration", "Wizards"])
        for one in said:
            self.assertNotRegex(one, r"[A-Za-z]", one)

    def test_the_status_and_language_are_russian(self):
        self.assertEqual(ru.status("Ongoing"), "выходит")
        self.assertEqual(ru.language("Chinese"), "китайский")


class TestHowWordsAreMatched(unittest.TestCase):

    def test_case_does_not_matter(self):
        """Каталог пишет то «Magic», то «magic»."""
        self.assertEqual(ru.word("MAGIC"), ru.word("magic"))

    def test_a_hyphen_and_a_space_are_the_same(self):
        """«Sci-fi», «Sci Fi», «sci_fi» — одно слово."""
        self.assertEqual(ru.word("Sci-fi"), ru.word("Sci Fi"))
        self.assertEqual(ru.word("sci_fi"), "фантастика")

    def test_spaces_around_do_not_matter(self):
        self.assertEqual(ru.word("  Fantasy  "), "фэнтези")

    def test_an_unknown_word_gives_nothing(self):
        """Пусто — значит «такого слова в словаре нет», а не «перевод
        пустой»: на этом и держится решение оставить слово как есть."""
        self.assertEqual(ru.word("Совершенно неизвестный тег"), "")

    def test_an_empty_word_gives_nothing(self):
        self.assertEqual(ru.word(""), "")
        self.assertEqual(ru.word(None), "")


class TestWhatHappensToUnknownWords(unittest.TestCase):
    """Незнакомое остаётся как есть — это честнее выдумки.

    Увидев чужое слово, человек поймёт, что его не перевели. Увидев
    неверный перевод — не поймёт ничего.
    """

    def test_an_unknown_tag_stays_english(self):
        said = ru.tags(["Magic", "Zzz Unknown Tag"])
        self.assertIn("магия", said)
        self.assertIn("Zzz Unknown Tag", said)

    def test_one_unknown_does_not_hide_the_rest(self):
        """Прятать перевод всех остальных из-за одного незнакомого —
        терять то, что уже сделано."""
        said = ru.tags(["Zzz Unknown", "Magic", "Revenge"])
        self.assertEqual(len(said), 3)
        self.assertIn("месть", said)

    def test_an_unknown_status_stays_as_it_came(self):
        self.assertEqual(ru.status("Frozen Solid"), "Frozen Solid")

    def test_empty_rows_are_dropped(self):
        self.assertEqual(ru.tags(["", "  ", "Magic"]), ["магия"])

    def test_nothing_at_all_gives_an_empty_list(self):
        self.assertEqual(ru.genres([]), [])
        self.assertEqual(ru.genres(None), [])


class TestTheDictionaryItself(unittest.TestCase):

    def test_every_translation_is_actually_russian(self):
        """Словарь, где половина слов осталась английской, хуже
        отсутствия словаря: он обещает перевод и не даёт его."""
        for book in (ru.GENRES, ru.TAGS, ru.STATUS, ru.LANGUAGE):
            for word, said in book.items():
                self.assertRegex(said, r"[а-яё]", f"{word} → {said}")

    def test_the_keys_are_written_the_way_they_are_looked_up(self):
        """Ключ с большой буквы или с дефисом не найдётся никогда, и
        слово молча останется английским."""
        for book in (ru.GENRES, ru.TAGS, ru.STATUS, ru.LANGUAGE):
            for word in book:
                self.assertEqual(word, ru._plain(word))

    def test_a_word_from_a_neighbouring_list_is_still_translated(self):
        """Каталог называет одно и то же то жанром, то тегом: «Military»
        бывает и тем и другим, и отказываться от готового перевода из-за
        того, что он в соседнем списке, незачем."""
        self.assertTrue(ru.word("Magic", ru.GENRES))


class TestWhatTheCardShows(unittest.TestCase):
    """Словарь подключён к самой карточке, а не лежит рядом."""

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        was = library.LIBRARY_FILE
        library.LIBRARY_FILE = Path(self.dir.name) / "library.json"
        self.addCleanup(setattr, library, "LIBRARY_FILE", was)

    def book(self, **more):
        fields = dict(name="Книга", genres=["Action", "Fantasy"],
                      site_tags=["Magic", "Revenge"], status="Ongoing",
                      language="Chinese")
        fields.update(more)
        return library.remember("mvl:1", **fields)

    def test_the_genres_reach_the_card_in_russian(self):
        self.assertEqual(self.book().genres_shown, ["боевик", "фэнтези"])

    def test_the_tags_reach_the_card_in_russian(self):
        self.assertEqual(self.book().site_tags_shown, ["магия", "месть"])

    def test_the_status_and_language_reach_the_card_in_russian(self):
        book = self.book()
        self.assertEqual(book.status_shown, "выходит")
        self.assertEqual(book.language_shown, "китайский")

    def test_a_translation_by_the_model_wins_over_the_dictionary(self):
        """За него платили. Словарь бесплатен и уступает."""
        book = self.book(genres_ru=["свой перевод"])
        self.assertEqual(book.genres_shown, ["свой перевод"])

    def test_the_dictionary_translation_is_not_kept_in_the_file(self):
        """Иначе пополнение словаря не дошло бы до уже записанных книг:
        они так и остались бы со вчерашним переводом."""
        self.book()
        kept = json.loads(library.LIBRARY_FILE.read_text(encoding="utf-8"))
        self.assertEqual(kept[0]["genres"], ["Action", "Fantasy"])
        self.assertEqual(kept[0]["genres_ru"], [])
        self.assertNotIn("genres_shown", kept[0])

    def test_no_computed_field_leaks_into_the_file(self):
        """Список считаемых полей один на запись и на чтение: разойдись
        они, лишнее поле тихо осело бы в файле и жило там вечно."""
        self.book()
        kept = json.loads(library.LIBRARY_FILE.read_text(encoding="utf-8"))
        for made in library.MADE:
            self.assertNotIn(made, kept[0], made)

    def test_the_original_is_still_there_to_compare(self):
        """Перевод бывает вольным, и оригинал нужен под рукой."""
        book = self.book()
        self.assertEqual(book.genres, ["Action", "Fantasy"])
        self.assertEqual(book.status, "Ongoing")



class TestTranslatingTheDescription(unittest.TestCase):
    """Описание у каждой книги своё, словарём его не возьмёшь.

    Здесь нужна модель — и она платная, поэтому по кнопке, а не сама.
    """

    def setUp(self):
        from webapp import app as web

        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        was = library.LIBRARY_FILE
        library.LIBRARY_FILE = Path(self.dir.name) / "library.json"
        self.addCleanup(setattr, library, "LIBRARY_FILE", was)

        self.web = web
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()
        self.asked = []

    def answers(self, text, blows=None):
        """Подставная модель. Что именно ей отправили — в `self.asked`."""
        outer = self

        class Model:
            def generate(self, prompt, **rest):
                outer.asked.append(prompt)
                if blows is not None:
                    raise blows
                return text

            def close(self):
                pass

        self.addCleanup(setattr, self.web, "_llm_client", self.web._llm_client)
        self.web._llm_client = lambda *a, **k: Model()

    def book(self, **more):
        fields = dict(name="Книга", about="A wizard analyzes everything.")
        fields.update(more)
        return library.remember("mvl:1", **fields)

    def post(self, **payload):
        return self.client.post("/api/library/translate",
                                json={"key": "mvl:1", **payload})

    def test_the_translation_is_kept(self):
        """Второй раз за один и тот же перевод не платим."""
        self.book()
        self.answers('{"about": "Волшебник всё анализирует."}')
        got = self.post()
        self.assertEqual(got.status_code, 200)
        self.assertEqual(library.get("mvl:1").about_ru,
                         "Волшебник всё анализирует.")

    def test_the_original_survives(self):
        """Перевод бывает вольным, и сверить хочется, не уходя со страницы."""
        self.book()
        self.answers('{"about": "Перевод."}')
        self.post()
        self.assertEqual(library.get("mvl:1").about,
                         "A wizard analyzes everything.")

    def test_the_original_is_what_gets_sent(self):
        self.book()
        self.answers('{"about": "Перевод."}')
        self.post()
        self.assertIn("A wizard analyzes everything.", self.asked[0])

    def test_a_second_press_does_not_pay_again(self):
        self.book(about_ru="Уже переведено.")
        self.answers('{"about": "Ещё раз."}')
        self.post()
        self.assertEqual(self.asked, [])

    def test_but_it_can_be_asked_again_on_purpose(self):
        self.book(about_ru="Уже переведено.")
        self.answers('{"about": "Ещё раз."}')
        self.post(again=True)
        self.assertEqual(library.get("mvl:1").about_ru, "Ещё раз.")

    def test_a_book_without_a_description_is_told_so(self):
        self.book(about="")
        self.answers('{"about": "Ничего."}')
        got = self.post()
        self.assertEqual(got.status_code, 400)
        self.assertEqual(self.asked, [])

    def test_an_unknown_book_is_told_so(self):
        self.answers('{"about": "Ничего."}')
        got = self.client.post("/api/library/translate", json={"key": "нет"})
        self.assertEqual(got.status_code, 404)

    def test_an_answer_wrapped_in_fences_is_still_read(self):
        """Модель нет-нет да обернёт ответ в ```json."""
        self.book()
        self.answers('```json\n{"about": "Перевод."}\n```')
        self.post()
        self.assertEqual(library.get("mvl:1").about_ru, "Перевод.")

    def test_an_empty_answer_does_not_erase_anything(self):
        """Пустой перевод хуже отсутствия перевода: описание пропало бы."""
        self.book()
        self.answers('{"about": "   "}')
        got = self.post()
        self.assertEqual(got.status_code, 502)
        self.assertEqual(library.get("mvl:1").about_ru, "")

    def test_a_refusal_from_the_model_is_passed_on(self):
        """Молчание тут читается как «кнопка не работает»."""
        from llm.client import LlmError

        self.book()
        self.answers("", blows=LlmError("ключ кончился"))
        got = self.post()
        self.assertEqual(got.status_code, 502)
        self.assertIn("ключ кончился", got.get_json()["error"])

if __name__ == "__main__":
    unittest.main()
