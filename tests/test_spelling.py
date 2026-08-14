"""Проверка орфографии (4.9 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core.models import Chapter  # noqa: E402
from ops import spelling  # noqa: E402

HAVE_DICT = spelling.available()
HAVE_HINTS = spelling.suggestions_available()


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def book(self, chapters, name="книга"):
        path = self.tmp / name
        path.mkdir(parents=True, exist_ok=True)
        for number, paragraphs in chapters.items():
            formats.write(path / f"Глава {number}.txt",
                          [Chapter(number=number, title=f"Глава {number}",
                                   paragraphs=list(paragraphs))],
                          headings=True)
        return str(path)


class TestOwnDictionary(Base):
    """Свой словарь книги: имена и термины, которых нет в русском."""

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(spelling.load_words(self.tmp), [])

    def test_words_survive_a_round_trip(self):
        spelling.save_words(self.tmp, ["Чжан", "цигун"])
        # Порядок алфавитный: «ц» идёт раньше «ч».
        self.assertEqual(spelling.load_words(self.tmp), ["цигун", "Чжан"])

    def test_adding_keeps_what_was_there(self):
        """Кнопка «это имя» дописывает, а не заменяет весь список."""
        spelling.save_words(self.tmp, ["Чжан"])
        result = spelling.add_words(self.tmp, ["Ли Вэй", "Чжан"])
        self.assertEqual(result, ["Ли Вэй", "Чжан"])

    def test_blank_lines_are_dropped(self):
        spelling.dict_path(self.tmp).write_text("Чжан\n\n  \nцигун\n",
                                                encoding="utf-8")
        self.assertEqual(spelling.load_words(self.tmp), ["цигун", "Чжан"])

    def test_state_reports_the_path(self):
        spelling.save_words(self.tmp, ["Чжан"])
        state = spelling.state(self.tmp)
        self.assertEqual(state["count"], 1)
        self.assertTrue(state["path"].endswith(spelling.DICT_FILE))


class TestRegistryWords(Base):
    """Имена из реестра сущностей — не опечатки."""

    def test_no_registry_is_not_an_error(self):
        self.assertEqual(spelling.registry_words(self.tmp), set())

    def test_names_are_split_into_words(self):
        from core.registry import Entity, Registry
        from ops.analyze import save_registry

        registry = Registry()
        registry.add_entity(Entity(name="Секта Пурпурного Облака",
                                   type="организация"))
        save_registry(self.tmp, registry)

        words = spelling.registry_words(self.tmp)
        self.assertIn("Пурпурного", words)
        self.assertIn("Облака", words)


@unittest.skipUnless(HAVE_DICT, "нет pymorphy3")
class TestCheck(Base):
    """Сама проверка."""

    def test_typo_is_found(self):
        book = self.book({1: ["Он сказал превет и ушёл."]})
        report = spelling.check(book).as_dict()
        self.assertIn("превет", [f["word"] for f in report["findings"]])

    def test_correct_text_is_clean(self):
        book = self.book({1: ["Он сказал привет и ушёл домой."]})
        report = spelling.check(book).as_dict()
        self.assertEqual(report["findings"], [])

    def test_repeated_word_is_one_finding(self):
        """Иначе одно имя героя дало бы пятьсот одинаковых строк."""
        book = self.book({
            1: ["Превет.", "Ещё раз превет.", "И снова превет."],
        })
        report = spelling.check(book).as_dict()
        found = [f for f in report["findings"] if f["word"].lower() == "превет"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["count"], 3)

    @unittest.skipUnless(HAVE_HINTS, "нет pyspellchecker")
    def test_suggestion_is_offered(self):
        book = self.book({1: ["Он сказал превет."]})
        report = spelling.check(book).as_dict()
        found = next(f for f in report["findings"] if f["word"] == "превет")
        self.assertIn("привет", found["suggestions"])

    def test_own_dictionary_silences_a_name(self):
        book = self.book({1: ["Мастер Чжаньсюэ поднял меч."]})
        before = spelling.check(book).as_dict()
        self.assertIn("Чжаньсюэ", [f["word"] for f in before["findings"]])

        spelling.add_words(book, ["Чжаньсюэ"])
        after = spelling.check(book).as_dict()
        self.assertNotIn("Чжаньсюэ", [f["word"] for f in after["findings"]])

    def test_registry_names_are_silenced(self):
        from core.registry import Entity, Registry
        from ops.analyze import save_registry

        book = self.book({1: ["Мастер Чжаньсюэ поднял меч."]})
        registry = Registry()
        registry.add_entity(Entity(name="Чжаньсюэ", type="персонаж"))
        save_registry(Path(book), registry)

        report = spelling.check(book).as_dict()
        self.assertNotIn("Чжаньсюэ", [f["word"] for f in report["findings"]])

    def test_registry_can_be_ignored(self):
        from core.registry import Entity, Registry
        from ops.analyze import save_registry

        book = self.book({1: ["Мастер Чжаньсюэ поднял меч."]})
        registry = Registry()
        registry.add_entity(Entity(name="Чжаньсюэ", type="персонаж"))
        save_registry(Path(book), registry)

        report = spelling.check(book, use_registry=False).as_dict()
        self.assertIn("Чжаньсюэ", [f["word"] for f in report["findings"]])

    def test_short_words_are_left_alone(self):
        book = self.book({1: ["Он ел щи."]})
        report = spelling.check(book).as_dict()
        self.assertEqual(report["findings"], [])

    def test_ordinary_word_forms_are_not_errors(self):
        """Список начальных форм тут не годится: «усмехнулся» — не ошибка."""
        book = self.book({1: [
            "Он усмехнулся, поднял длинной рукой пустую чашку и ушёл.",
            "Ученику досталась короткой ночи половина.",
        ]})
        report = spelling.check(book).as_dict()
        self.assertEqual([f["word"] for f in report["findings"]], [])

    def test_numbers_are_not_words(self):
        book = self.book({1: ["Глава 244 началась в 1998 году."]})
        report = spelling.check(book).as_dict()
        self.assertNotIn("244", [f["word"] for f in report["findings"]])

    def test_quote_shows_the_place(self):
        book = self.book({1: ["Он долго думал, а потом сказал превет соседу."]})
        report = spelling.check(book).as_dict()
        found = next(f for f in report["findings"] if f["word"] == "превет")
        self.assertIn("превет", found["quote"])

    def test_frequent_words_come_first(self):
        book = self.book({
            1: ["Превет.", "Превет.", "Превет.", "Дорга."],
        })
        report = spelling.check(book).as_dict()
        self.assertEqual(report["findings"][0]["word"].lower(), "превет")

    def test_counts_are_reported(self):
        book = self.book({1: ["Он сказал привет и ушёл домой."]})
        report = spelling.check(book).as_dict()
        self.assertEqual(report["chapters"], 1)
        self.assertGreater(report["words"], 0)


class TestWithoutDictionary(Base):
    """Без пакета вкладка не ломается, а объясняет, чего не хватает."""

    def test_message_names_the_package(self):
        real = spelling._dictionary

        def broken(extra=None):
            raise spelling.SpellingError(
                "Словарь не установлен. Поставьте пакеты: "
                "pip install pymorphy3 pymorphy3-dicts-ru")

        spelling._dictionary = broken
        self.addCleanup(setattr, spelling, "_dictionary", real)

        book = self.book({1: ["Текст."]})
        with self.assertRaises(spelling.SpellingError) as caught:
            spelling.check(book)
        self.assertIn("pymorphy3", str(caught.exception))

    def test_state_says_whether_the_dictionary_is_there(self):
        self.assertIsInstance(spelling.state(self.tmp)["available"], bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
