"""Глоссарий имён: варианты написания сводятся в словарь автозамен.

У машинного перевода имя плавает от главы к главе — Юй Шэн в первой
сотне и Ю Шен в третьей. Реестр «Анализа» про это уже знает; здесь
накопленное превращается в словарь для замены по словарю.

Две вещи, которые здесь легко сломать и дорого чинить. Первая: прозвище
— не вариант написания, и заменять его нельзя, иначе программа перепишет
книгу. Вторая: короткое имя сидит внутри обычных слов, и правило без
границ слова превратит «Лиза» в «Ли Минза».
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.registry import Entity, Registry  # noqa: E402
from ops import names, replace  # noqa: E402


def registry(*entities) -> Registry:
    """Реестр без слияния: записи ложатся ровно так, как описаны."""
    found = Registry()
    for entity in entities:
        found.entities[entity.id] = entity
    return found


def person(name, aliases=(), **more):
    return Entity(name=name, aliases=list(aliases), type="персонаж", **more)


class TestWhatCountsAsTheSameName(unittest.TestCase):

    def test_two_spellings_become_one_group(self):
        found = names.groups(registry(person("Юй Шэн", ["Ю Шен"])))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].variants, ["Ю Шен"])

    def test_a_nickname_is_not_a_spelling(self):
        """«Учитель Ю» — тот же человек, но заменить его на имя значит
        переписать книгу."""
        found = names.groups(registry(person("Юй Шэн", ["Учитель Ю"])))
        self.assertEqual(found, [])

    def test_a_nickname_does_not_travel_with_a_real_variant(self):
        found = names.groups(
            registry(person("Юй Шэн", ["Ю Шен", "Учитель Ю"])))
        self.assertEqual(found[0].variants, ["Ю Шен"])

    def test_one_spelling_alone_is_not_a_group(self):
        """Менять нечего, а в списке такая запись была бы шумом."""
        self.assertEqual(names.groups(registry(person("Юй Шэн"))), [])

    def test_two_records_of_one_person_come_together(self):
        """Разбор идёт кусками, и вторая запись заводится в другом куске."""
        found = names.groups(registry(person("Юй Шэн"), person("Юй Шен")))
        self.assertEqual(len(found), 1)
        self.assertEqual(sorted(found[0].names), ["Юй Шен", "Юй Шэн"])

    def test_records_of_different_kinds_stay_apart(self):
        """Человек и место с похожими именами — разные вещи."""
        town = Entity(name="Юй Шен", type="место")
        found = names.groups(registry(person("Юй Шэн"), town))
        self.assertEqual(found, [])

    def test_short_names_are_not_merged_by_one_letter(self):
        """«Ли» и «Ло» — разные люди, хотя различие в один символ."""
        self.assertEqual(names.groups(registry(person("Ли"), person("Ло"))), [])


class TestWhichSpellingWins(unittest.TestCase):

    def test_the_confirmed_record_sets_the_spelling(self):
        """Человек уже сказал, как правильно."""
        found = names.groups(registry(
            person("Ю Шен", ["Юй Шэн"], confirmed=True)))
        self.assertEqual(found[0].canonical, "Ю Шен")

    def test_without_confirmation_the_fuller_spelling_wins(self):
        """У имён с китайского выпадают как раз буквы."""
        found = names.groups(registry(person("Ю Шен", ["Юй Шэн"])))
        self.assertEqual(found[0].canonical, "Юй Шэн")

    def test_the_answer_does_not_depend_on_the_order_of_records(self):
        one = names.groups(registry(person("Юй Шэн"), person("Юй Шен")))
        two = names.groups(registry(person("Юй Шен"), person("Юй Шэн")))
        self.assertEqual(one[0].canonical, two[0].canonical)

    def test_the_canonical_is_never_among_the_variants(self):
        found = names.groups(registry(person("Ю Шен", ["Юй Шэн"])))
        self.assertNotIn(found[0].canonical, found[0].variants)


class TestTheDictionaryItWrites(unittest.TestCase):

    def dictionary(self, *entities):
        return names.as_dictionary(names.groups(registry(*entities)))

    def test_a_rule_says_what_to_what(self):
        text = self.dictionary(person("Юй Шэн", ["Ю Шен"]))
        self.assertIn("Ю Шен", text)
        self.assertIn("= Юй Шэн", text)

    def test_nothing_to_replace_writes_nothing(self):
        """Пустой словарь с одной шапкой выглядел бы как сделанная работа."""
        self.assertEqual(self.dictionary(person("Юй Шэн")), "")

    def test_the_file_says_where_it_came_from(self):
        text = self.dictionary(person("Юй Шэн", ["Ю Шен"]))
        self.assertTrue(text.startswith("#"))

    def test_the_rules_are_read_back_by_the_replacement(self):
        """Словарь пишется для `ops/replace` — и должен им читаться."""
        text = self.dictionary(person("Юй Шэн", ["Ю Шен"]))
        rules = replace.parse_dictionary(text)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].replace, "Юй Шэн")


class TestTheReplacementDoesNotSpoilTheText(unittest.TestCase):
    """Здесь проверяется само обещание: что замена делает с текстом."""

    def rules(self, *entities):
        return replace.parse_dictionary(
            names.as_dictionary(names.groups(registry(*entities))))

    def apply(self, text, *entities):
        for rule in self.rules(*entities):
            text, _ = rule.apply(text)
        return text

    def test_the_wandering_spelling_is_brought_to_one(self):
        got = self.apply("Ю Шен вошёл в дом.", person("Юй Шэн", ["Ю Шен"]))
        self.assertEqual(got, "Юй Шэн вошёл в дом.")

    def test_a_variant_inside_a_longer_word_is_left_alone(self):
        """«Тэо» и «Тео» — одно имя, а «Тэодор» — другое. Без границ
        слова замена залезла бы внутрь и сделала из него «Теодор»."""
        got = self.apply("Тэодор позвал Тэо.", person("Тео", ["Тэо"]))
        self.assertIn("Тэодор", got)
        self.assertIn("Тео.", got)

    def test_the_short_variant_inside_a_word_survives(self):
        rules = self.rules(person("Юй Шэн", ["Ю Шен"]))
        text = "Ю Шеном звали его."
        for rule in rules:
            text, _ = rule.apply(text)
        # «Ю Шеном» — то же имя в творительном падеже; границы слова его
        # не трогают, и это честнее, чем склеить «Юй Шэном» наугад.
        self.assertIn("Ю Шеном", text)

    def test_a_dot_in_a_name_means_a_dot(self):
        """Правило уходит выражением, и точка в нём должна значить
        точку, а не «любой символ»: иначе «Дж. Смит» поймает «ДжХСмит»."""
        rules = replace.parse_dictionary(names.as_dictionary(
            names.from_dicts([{"canonical": "Джон Смит",
                               "variants": ["Дж. Смит"]}])))
        text = "ДжХСмит и Дж. Смит"
        for rule in rules:
            text, _ = rule.apply(text)
        self.assertIn("ДжХСмит", text)
        self.assertIn("Джон Смит", text)


class TestWhatThePageSendsBack(unittest.TestCase):

    def test_the_persons_choice_is_what_gets_written(self):
        """Человек мог сменить главное написание — словарь собирается по
        его выбору, а не по нашему предложению."""
        chosen = names.from_dicts([{"canonical": "Ю Шен",
                                    "variants": ["Юй Шэн"]}])
        self.assertIn("= Ю Шен", names.as_dictionary(chosen))

    def test_a_group_without_a_main_spelling_is_dropped(self):
        self.assertEqual(names.from_dicts([{"variants": ["Юй Шэн"]}]), [])

    def test_the_main_spelling_is_not_replaced_by_itself(self):
        chosen = names.from_dicts([{"canonical": "Юй Шэн",
                                    "variants": ["Юй Шэн", "Ю Шен"]}])
        self.assertEqual(chosen[0].variants, ["Ю Шен"])


class TestTheSummary(unittest.TestCase):

    def test_it_counts_names_and_spellings_apart(self):
        found = names.groups(registry(
            person("Юй Шэн", ["Ю Шен", "Юй Шен"]),
            person("Ли Мин", ["Ли Мнн"])))
        said = names.summary(found)
        self.assertEqual(said["names"], 2)
        self.assertEqual(said["variants"], 3)


class TestWritingIntoAnExistingDictionary(unittest.TestCase):
    """Словарь книги — не наш: там лежат замены, внесённые руками."""

    def fresh(self):
        return names.as_dictionary(names.from_dicts(
            [{"canonical": "Юй Шэн", "variants": ["Ю Шен"]}]))

    def test_what_a_person_wrote_by_hand_survives(self):
        was = "чёрт = чёрт\n"
        text, added = names.merge_into(was, self.fresh())
        self.assertIn("чёрт = чёрт", text)
        self.assertEqual(added, 1)

    def test_the_same_rule_is_not_added_twice(self):
        """Иначе список рос бы с каждым нажатием."""
        text, _ = names.merge_into("", self.fresh())
        again, added = names.merge_into(text, self.fresh())
        self.assertEqual(added, 0)
        self.assertEqual(again, text)

    def test_an_empty_dictionary_gets_the_header(self):
        text, _ = names.merge_into("", self.fresh())
        self.assertTrue(text.startswith("#"))

    def test_the_result_is_still_a_readable_dictionary(self):
        text, _ = names.merge_into("чёрт = чёрт\n", self.fresh())
        rules = replace.parse_dictionary(text)
        self.assertEqual(len(rules), 2)


class TestTheGlossaryOverHttp(unittest.TestCase):

    def setUp(self):
        from tempfile import TemporaryDirectory

        from ops import analyze as analyze_op
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()
        self.analyze = analyze_op

        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

    def seed(self, *entities):
        self.analyze.save_registry(self.root, registry(*entities))

    def test_the_glossary_is_built_from_the_registry(self):
        self.seed(person("Юй Шэн", ["Ю Шен"]))
        said = self.app.post("/api/names/glossary",
                             json={"root": str(self.root)}).get_json()
        self.assertEqual(said["summary"]["names"], 1)
        self.assertEqual(said["groups"][0]["variants"], ["Ю Шен"])

    def test_an_empty_registry_is_not_an_error(self):
        res = self.app.post("/api/names/glossary",
                            json={"root": str(self.root)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["groups"], [])

    def test_saving_writes_the_dictionary_next_to_the_book(self):
        self.seed(person("Юй Шэн", ["Ю Шен"]))
        said = self.app.post("/api/names/save", json={
            "root": str(self.root),
            "groups": [{"canonical": "Юй Шэн", "variants": ["Ю Шен"]}],
        }).get_json()
        self.assertEqual(said["added"], 1)
        self.assertIn("Юй Шэн",
                      Path(said["path"]).read_text(encoding="utf-8"))

    def test_saving_does_not_wipe_what_was_there(self):
        path = replace.dictionary_path(self.root)
        path.write_text("чёрт = чёрт\n", encoding="utf-8")
        self.app.post("/api/names/save", json={
            "root": str(self.root),
            "groups": [{"canonical": "Юй Шэн", "variants": ["Ю Шен"]}],
        })
        self.assertIn("чёрт = чёрт", path.read_text(encoding="utf-8"))

    def test_saving_nothing_is_refused_rather_than_pretended(self):
        res = self.app.post("/api/names/save",
                            json={"root": str(self.root), "groups": []})
        self.assertEqual(res.status_code, 400)

    def test_the_page_learns_where_the_dictionary_lives(self):
        """Иначе после записи непонятно, куда смотреть."""
        said = self.app.post("/api/names/glossary",
                             json={"root": str(self.root)}).get_json()
        self.assertTrue(said["path"].endswith(replace.DICT_FILE))


if __name__ == "__main__":
    unittest.main()
