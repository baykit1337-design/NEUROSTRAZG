"""Проверка орфографии (4.9 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core.models import Chapter  # noqa: E402
from ops import spelling  # noqa: E402
from ops.base import Cancelled, Progress  # noqa: E402

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


class TestPickingReplacementsDoesNotHang(Base):
    """Здесь проверка «зависала и ничего не делала».

    Перебор похожих написаний на две правки стоит до полусекунды на
    длинное слово. Находок в книге бывают сотни, и на них уходили минуты —
    молча: главы к этому времени прочитаны, полоса стоит на конце.
    """

    #: Слоги, из которых собираются имена. Цифр в них нет нарочно: слово
    #: для проверки — это буквы подряд, и «Чжань1лунь» стало бы двумя
    #: словами, а книга — двумя находками вместо сотни.
    SYLLABLES = ("чжань", "сюэ", "лунь", "тянь", "вэнь", "бай", "линъ")

    def many(self, count=40):
        """Книга, где каждое слово словарю незнакомо."""
        made = []
        for n in range(count):
            first, second, third = (self.SYLLABLES[n % 7],
                                    self.SYLLABLES[n // 7 % 7],
                                    self.SYLLABLES[n // 49 % 7])
            made.append((first + second + third + "ъи" * (n // 343 + 1)).capitalize())
        made = sorted(set(made))
        return self.book({1: [f"Мастер {w} поднял меч." for w in made]})

    def test_the_search_goes_one_edit_deep(self):
        """Две правки — это перебор всех слов, отличающихся двумя
        буквами. Одна лишняя догадка на десять не стоит минут ожидания."""
        self.assertEqual(spelling.EDITS, 1)

    @unittest.skipUnless(HAVE_HINTS, "нет pyspellchecker")
    def test_the_speller_is_told_how_deep_to_look(self):
        """Настройка должна доехать до самого словаря, а не остаться
        числом в модуле."""
        made = spelling._dictionary(set())
        self.assertEqual(made._speller.distance, spelling.EDITS)

    def test_it_says_out_loud_that_it_is_picking_replacements(self):
        """Молчащий кусок работы неотличим от зависшего."""
        said = []
        spelling.check(self.many(),
                       progress=Progress(on_progress=lambda d, t, m: said.append(m)))
        self.assertTrue(any("замены" in line for line in said), said)

    def test_stopping_works_while_replacements_are_picked(self):
        """Раньше отмену здесь не слушали вовсе."""
        stop = threading.Event()
        seen = []

        def watch(done, total, message):
            seen.append(message)
            if "замены" in message:
                stop.set()

        with self.assertRaises(Cancelled):
            spelling.check(self.many(),
                           progress=Progress(on_progress=watch, cancel=stop))

    def test_a_book_full_of_unknown_words_finishes_quickly(self):
        """Мерка грубая нарочно: порог в пять секунд ловит возврат к
        старому поведению, не завися от скорости машины.

        Книга нарочно небольшая. На поиске в две правки сорок незнакомых
        слов считаются секунд двадцать — этого хватает, чтобы порог
        сработал, и при этом упавший тест не держит прогон минутами."""
        start = time.monotonic()
        spelling.check(self.many())
        self.assertLess(time.monotonic() - start, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
