"""Словарь имён собственных при переводе заголовков.

Заголовки уходят к модели пачками по двадцать пять, каждая пачка — свой
запрос, и модель не помнит, как назвала героя в прошлой. Отсюда «Ли Сяо»
в одной главе и «Ли Сяон» в соседней.

Проверяется не то, что словарь сохраняется, а то, ради чего он заведён:
что написание доходит до модели и что за уже решённое не платят второй
раз — квота у ключей суточная.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import titles  # noqa: E402


class FakeClient:
    """Модель, которая всё переводит одинаково и помнит, о чём спросили."""

    def __init__(self, answer=None):
        self.asked: list[str] = []
        self.answer = answer

    def generate(self, prompt, model=""):
        self.asked.append(prompt)
        if self.answer is not None:
            return self.answer
        # По строке на каждый номер: сколько спросили, столько и вернём.
        lines = [one for one in prompt.splitlines()
                 if one[:1].isdigit() and ". " in one]
        return "{" + ", ".join(f'"{i}": "перевод {i}"'
                               for i in range(1, len(lines) + 1)) + "}"

    def close(self):
        pass


class Row:
    """Строка рейтинга — столько, сколько от неё нужно переводу."""

    def __init__(self, book_id, name):
        self.book_id, self.name = book_id, name


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        tmp = Path(self._dir.name)

        # Свои файлы: прогон не должен трогать ни настоящий словарь, ни
        # кэши переводов.
        self._was = (titles.NAMES_FILE, titles.HEADINGS_FILE,
                     titles.TITLES_FILE)
        titles.NAMES_FILE = tmp / "names.json"
        titles.HEADINGS_FILE = tmp / "headings.json"
        titles.TITLES_FILE = tmp / "titles.json"
        self.addCleanup(self._restore)

    def _restore(self):
        (titles.NAMES_FILE, titles.HEADINGS_FILE,
         titles.TITLES_FILE) = self._was


class TestTheGlossaryItself(Base):
    def test_it_remembers_what_it_was_told(self):
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        self.assertEqual(titles.spellings(), {"Li Xiao": "Ли Сяо"})

    def test_it_takes_pairs_as_well_as_a_dictionary(self):
        """Глоссарий от переводчика приходит парами."""
        titles.remember_spellings([("Yun Che", "Юнь Че")])
        self.assertEqual(titles.spellings()["Yun Che"], "Юнь Че")

    def test_half_a_pair_is_not_a_pair(self):
        titles.remember_spellings({"Li Xiao": "  ", "": "Ли Сяо"})
        self.assertEqual(titles.spellings(), {})

    def test_clearing_leaves_nothing(self):
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        titles.forget_spellings()
        self.assertEqual(titles.spellings(), {})


class TestWhatGoesToTheModel(Base):
    def test_only_the_names_from_this_batch(self):
        """Словарь бывает на сотни имён, а в пачке двадцать пять коротких
        заголовков: слать весь список к каждой — платить за него сотню
        раз."""
        titles.remember_spellings({"Li Xiao": "Ли Сяо", "Yun Che": "Юнь Че"})
        said = titles.hint_for(["Li Xiao goes home"])

        self.assertIn("Ли Сяо", said)
        self.assertNotIn("Юнь Че", said)

    def test_no_names_here_means_no_glossary_at_all(self):
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        self.assertEqual(titles.hint_for(["Trade at dawn"]), "")

    def test_the_name_is_found_whatever_the_case(self):
        """Заголовки приходят и «LI XIAO», и «Li Xiao»."""
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        self.assertIn("Ли Сяо", titles.hint_for(["LI XIAO RETURNS"]))

    def test_a_huge_glossary_does_not_swallow_the_request(self):
        """Книга, где в заголовках одни имена, иначе утащила бы в запрос
        весь словарь."""
        many = {f"Name{n}": f"Имя{n}" for n in range(titles.NAMES_IN_PROMPT * 3)}
        titles.remember_spellings(many)
        said = titles.hint_for([" ".join(many)])
        self.assertLessEqual(said.count(" = "), titles.NAMES_IN_PROMPT)

    def test_the_glossary_reaches_the_model_with_the_batch(self):
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        client = FakeClient()
        titles.translate_headings(["Li Xiao meets Yun"], client)

        self.assertTrue(client.asked)
        self.assertIn("Ли Сяо", client.asked[0])

    def test_other_kinds_are_asked_without_a_glossary(self):
        """У названий книг и описаний в шаблоне для него и места нет —
        лишний довод `format` молча пропускает, но проверить стоит."""
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        client = FakeClient(answer='{"1": "Рассвет"}')
        titles.translate([Row("7", "Li Xiao")], client)

        self.assertNotIn("Имена собственные пиши строго так", client.asked[0])


class TestWhatIsNotAskedTwice(Base):
    def test_a_heading_that_is_in_the_glossary_is_not_asked_at_all(self):
        """Написание уже выбрано человеком: переспрашивать модель значит
        платить за ответ, который мы и так знаем, да ещё рискуя получить
        другой."""
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        client = FakeClient()
        got = titles.translate_headings(["Li Xiao"], client)

        self.assertEqual(got["names"]["Li Xiao"], "Ли Сяо")
        self.assertEqual(client.asked, [])
        self.assertEqual(got["from_glossary"], 1)

    def test_the_rest_is_still_asked(self):
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        client = FakeClient()
        titles.translate_headings(["Li Xiao", "Trade"], client)

        rows = [one for one in client.asked[0].splitlines()
                if one.startswith(("1. ", "2. "))]
        self.assertEqual(rows, ["1. Trade"])

    def test_the_glossary_beats_the_cache(self):
        """Кэш мог остаться от прошлого перевода, где имя вышло иначе.
        Выбор человека важнее."""
        titles.remember_headings({"Li Xiao": "Ли Сяон"})
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        got = titles.translate_headings(["Li Xiao"], FakeClient())
        self.assertEqual(got["names"]["Li Xiao"], "Ли Сяо")

    def test_taken_from_the_glossary_is_counted_apart(self):
        """За него не платили вовсе, и складывать его с кэшем значило бы
        прятать, сколько словарь сберёг."""
        titles.remember_spellings({"Li Xiao": "Ли Сяо"})
        got = titles.translate_headings(["Li Xiao"], FakeClient())
        self.assertEqual(got["from_glossary"], 1)
        self.assertEqual(got["cached"], 0)


class TestOverHttp(Base):
    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()

    def test_it_takes_the_shapes_the_glossary_module_knows(self):
        """Своего разбора формата здесь нет намеренно: два понимания
        одного файла однажды разъедутся."""
        for text in ("Li Xiao = Ли Сяо",
                     "Li Xiao -> Ли Сяо",
                     "Li Xiao,Ли Сяо",
                     '{"Li Xiao": "Ли Сяо"}'):
            with self.subTest(text):
                titles.forget_spellings()
                got = self.app.post("/api/titles/spellings",
                                    json={"text": text}).get_json()
                self.assertEqual(got["total"], 1, got)

    def test_nothing_recognisable_is_said_out_loud(self):
        res = self.app.post("/api/titles/spellings",
                            json={"text": "просто строка без пары"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("пары", res.get_json()["error"])

    def test_saving_replaces_what_the_field_shows(self):
        """Поле показывает словарь целиком, и человек правит его как
        текст: дописывать значило бы, что удалённая строка возвращается
        сама."""
        self.app.post("/api/titles/spellings", json={"text": "A = А\nB = Б"})
        got = self.app.post("/api/titles/spellings",
                            json={"text": "A = А", "replace": True}).get_json()
        self.assertEqual(got["total"], 1)

    def test_it_can_be_emptied(self):
        self.app.post("/api/titles/spellings", json={"text": "A = А"})
        got = self.app.post("/api/titles/spellings",
                            json={"clear": True}).get_json()
        self.assertEqual(got["total"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
