"""Перевод названий рейтинга: неразобравшийся ответ больше не пропадает.

Пачка из двадцати пяти названий, ответ на которую не разобрался, раньше
просто выбрасывалась. На экране это выглядело хуже всего, что можно
придумать: подпись честно говорила «переведено 55», а первые двадцать пять
строк — те самые, на которые человек и смотрит, — оставались китайскими.

Теперь пачку переспрашивают, а потом делят пополам, и разобранное по
дороге не теряется. Проверки ниже держат обе стороны: и то, что перевод
доходит, и то, что чужой перевод не встанет к чужой книге.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources.rank import RankRow  # noqa: E402
from ops import titles as titles_op  # noqa: E402


class Model:
    """Модель, отвечающая заготовками по очереди.

    Последняя заготовка повторяется: так проще описать «всегда отвечает
    мусором», не выписывая ответ на каждую попытку.
    """

    def __init__(self, *answers):
        self.answers = list(answers) or [""]
        self.asked: list[str] = []

    def generate(self, prompt, json_only=True, model=""):
        self.asked.append(prompt)
        at = min(len(self.asked), len(self.answers)) - 1
        answer = self.answers[at]
        return answer(prompt) if callable(answer) else answer

    @property
    def calls(self) -> int:
        return len(self.asked)


def honest(prefix="ПЕРЕВОД "):
    """Ответ, который честно переводит всё, о чём спросили."""

    def answer(prompt):
        out = {}
        for line in prompt.splitlines():
            line = line.strip()
            number, _, name = line.partition(". ")
            if number.isdigit() and name:
                out[number] = prefix + name
        return json.dumps(out, ensure_ascii=False)

    return answer


def rows(count, first=1):
    return [RankRow(book_id=str(n), name=f"书{n}")
            for n in range(first, first + count)]


class Base(unittest.TestCase):

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        was = titles_op.TITLES_FILE
        titles_op.TITLES_FILE = Path(self.dir.name) / "titles.json"
        self.addCleanup(setattr, titles_op, "TITLES_FILE", was)


class TestABrokenAnswerIsAskedAgain(Base):

    def test_the_second_try_saves_the_batch(self):
        model = Model("извините, вот перевод:", honest())
        found = titles_op.translate(rows(3), model)
        self.assertEqual(found["translated"], 3)
        self.assertEqual(found["broken"], 0)

    def test_the_same_batch_is_asked_the_second_time(self):
        """Переспрашиваем именно то же самое — иначе это уже не повтор."""
        model = Model("мусор", honest())
        titles_op.translate(rows(3), model)
        self.assertEqual(model.asked[0], model.asked[1])

    def test_a_good_answer_is_not_asked_twice(self):
        model = Model(honest())
        titles_op.translate(rows(3), model)
        self.assertEqual(model.calls, 1)


class TestAStubbornBatchIsSplit(Base):
    """Не разобралось и со второго раза — делим пополам."""

    def answers_only_short(self, limit):
        """Отвечает только на пачки не длиннее `limit`."""

        def answer(prompt):
            asked = [line for line in prompt.splitlines()
                     if line.strip()[:1].isdigit() and ". " in line]
            return honest()(prompt) if len(asked) <= limit else "мусор"

        return answer

    def test_halves_get_through_where_the_whole_did_not(self):
        model = Model(self.answers_only_short(6))
        found = titles_op.translate(rows(12), model)
        self.assertEqual(found["translated"], 12)

    def test_the_smallest_batch_is_not_split_to_pieces(self):
        """Иначе двадцать пять названий стали бы полусотней запросов."""
        model = Model("мусор")
        titles_op.translate(rows(titles_op.SMALLEST), model)
        self.assertEqual(model.calls, titles_op.TRIES)

    def test_a_hopeless_batch_stops_asking(self):
        """Дробление конечно: иначе кнопка висела бы вечно."""
        model = Model("мусор")
        titles_op.translate(rows(25), model)
        self.assertLess(model.calls, 40)


class TestAPartialAnswerIsFinished(Base):

    def test_what_the_answer_missed_is_asked_separately(self):
        """Модель ответила про половину строк и замолчала. Раньше вторая
        половина оставалась китайской молча."""
        def half(prompt):
            found = honest()(prompt)
            data = json.loads(found)
            keep = {k: v for k, v in data.items() if int(k) <= len(data) // 2}
            return json.dumps(keep, ensure_ascii=False)

        model = Model(half, honest())
        found = titles_op.translate(rows(8), model)
        self.assertEqual(found["broken"], 0)
        self.assertEqual(found["translated"], 8)


class TestTheAnswerIsReadForgivingly(Base):

    def ask(self, answer, count=2):
        return titles_op.translate(rows(count), Model(answer))

    def test_a_key_with_a_dot_still_counts(self):
        found = self.ask('{"1.": "Первая", "2.": "Вторая"}')
        self.assertEqual(found["titles"]["1"], "Первая")

    def test_the_chinese_name_as_a_key_still_counts(self):
        found = self.ask('{"书1": "Первая", "书2": "Вторая"}')
        self.assertEqual(found["titles"]["2"], "Вторая")

    def test_a_nested_answer_still_counts(self):
        found = self.ask('{"1": {"ru": "Первая"}, "2": {"ru": "Вторая"}}')
        self.assertEqual(found["titles"]["1"], "Первая")

    def test_a_plain_list_is_read_in_order(self):
        found = self.ask('["Первая", "Вторая"]')
        self.assertEqual(found["titles"]["2"], "Вторая")


class TestNoTranslationBeatsAWrongOne(Base):
    """Чужой перевод под чужой книгой выглядит достоверно и потому хуже
    китайского названия: по нему человек примет решение и ошибётся."""

    def test_a_short_list_is_refused_instead_of_shifted(self):
        model = Model('["Первая", "Вторая"]')
        found = titles_op.translate(rows(3), model)
        self.assertEqual(found["translated"], 0)

    def test_an_empty_translation_is_not_stored(self):
        model = Model('{"1": "", "2": "Вторая"}')
        found = titles_op.translate(rows(2), model)
        self.assertEqual(found["titles"]["1"], "")
        self.assertEqual(found["titles"]["2"], "Вторая")


class TestTheCountIsAboutTitlesNotBatches(Base):

    def test_untranslated_titles_are_counted_one_by_one(self):
        model = Model("мусор")
        found = titles_op.translate(rows(3), model)
        self.assertEqual(found["broken"], 3)
        self.assertEqual(found["translated"], 0)

    def test_the_complaint_names_what_stayed_chinese(self):
        """«Не перевелось 25» без имён не даёт ничего сделать."""
        model = Model("мусор")
        found = titles_op.translate(rows(3), model)
        self.assertIn("书1", found["missing"])

    def test_the_names_of_the_missing_do_not_flood_the_answer(self):
        model = Model("мусор")
        found = titles_op.translate(rows(40), model)
        self.assertLessEqual(len(found["missing"]), 10)

    def test_a_half_success_counts_both_sides(self):
        """Модель знает одно название и молчит про второе, сколько её ни
        переспрашивай."""
        def knows_one(prompt):
            found = json.loads(honest()(prompt))
            return json.dumps({k: v for k, v in found.items()
                               if v.endswith("书1")}, ensure_ascii=False)

        model = Model(knows_one)
        found = titles_op.translate(rows(2), model)
        self.assertEqual(found["translated"], 1)
        self.assertEqual(found["broken"], 1)


class TestWhatWorkedKeepsWorking(Base):

    def test_the_cache_still_answers_without_the_model(self):
        titles_op.translate(rows(2), Model(honest()))
        again = Model("мусор")
        found = titles_op.translate(rows(2), again)
        self.assertEqual(again.calls, 0)
        self.assertEqual(found["cached"], 2)

    def test_a_broken_run_does_not_wipe_what_was_translated(self):
        titles_op.translate(rows(2), Model(honest()))
        titles_op.translate(rows(2, first=3), Model("мусор"))
        self.assertEqual(len(titles_op.known()), 2)

    def test_force_asks_again_even_for_the_known(self):
        titles_op.translate(rows(2), Model(honest()))
        again = Model(honest("ИНАЧЕ "))
        found = titles_op.translate(rows(2), again, force=True)
        self.assertTrue(found["titles"]["1"].startswith("ИНАЧЕ"))


def abouts(count, first=1):
    """Описания: абзац на книгу, а не строка."""
    return {str(n): f"简介 {n}\n\n第二段 {n}" for n in range(first, first + count)}


#: Пронумерованная строка запроса. По разделителю запрос не разберёшь:
#: `---` стоит и в самом задании, до описаний.
NUMBERED = re.compile(r"^(\d+)\. (.+)$", re.M)


def honest_about(prefix="ПЕРЕВОД ", skip=()):
    """Ответ, переводящий описания. `skip` — номера, которые «не дались»."""

    def answer(prompt):
        return json.dumps(
            {number: prefix + text
             for number, text in NUMBERED.findall(prompt)
             if number not in skip},
            ensure_ascii=False)

    return answer


class AboutBase(Base):

    def setUp(self):
        super().setUp()
        was = titles_op.ABSTRACTS_FILE
        titles_op.ABSTRACTS_FILE = Path(self.dir.name) / "abstracts.json"
        self.addCleanup(setattr, titles_op, "ABSTRACTS_FILE", was)


class TestDescriptionsGoInBatches(AboutBase):
    """Возражение было про запрос на описание, а не про перевод как
    таковой: пачкой полсотни описаний стоят девяти запросов."""

    def test_a_batch_is_one_request_not_one_per_description(self):
        model = Model(honest_about())
        titles_op.translate_all_abstracts(abouts(titles_op.ABOUT_BATCH), model)
        self.assertEqual(model.calls, 1)

    def test_more_than_a_batch_is_split_by_the_batch_size(self):
        model = Model(honest_about())
        titles_op.translate_all_abstracts(
            abouts(titles_op.ABOUT_BATCH * 2), model)
        self.assertEqual(model.calls, 2)

    def test_a_batch_of_descriptions_is_smaller_than_of_titles(self):
        """Двадцать пять абзацев в одном запросе модель обрывает."""
        self.assertLess(titles_op.ABOUT_BATCH, titles_op.BATCH)

    def test_paragraphs_reach_the_model_whole(self):
        model = Model(honest_about())
        titles_op.translate_all_abstracts({"1": "первый\n\nвторой"}, model)
        self.assertIn("второй", model.asked[0])

    def test_descriptions_do_not_run_together(self):
        """Без разделителя два описания слипаются в одно, и модель
        возвращает один перевод на двоих. Смотрим между ними: `---` есть
        и в самом задании, до описаний."""
        model = Model(honest_about())
        titles_op.translate_all_abstracts(abouts(2), model)
        asked = model.asked[0]
        between = asked[asked.index("1. "):asked.index("2. ")]
        self.assertIn("\n---\n", between)


class TestDescriptionsAreRemembered(AboutBase):

    def test_the_translation_is_kept(self):
        titles_op.translate_all_abstracts(abouts(2), Model(honest_about()))
        self.assertTrue(titles_op.abstract_of("1").startswith("ПЕРЕВОД"))

    def test_the_known_are_not_asked_again(self):
        titles_op.translate_all_abstracts(abouts(2), Model(honest_about()))
        again = Model("мусор")
        found = titles_op.translate_all_abstracts(abouts(2), again)
        self.assertEqual(again.calls, 0)
        self.assertEqual(found["cached"], 2)

    def test_force_asks_again(self):
        titles_op.translate_all_abstracts(abouts(1), Model(honest_about()))
        again = Model(honest_about("ИНАЧЕ "))
        found = titles_op.translate_all_abstracts(abouts(1), again, force=True)
        self.assertTrue(found["abstracts"]["1"].startswith("ИНАЧЕ"))

    def test_the_single_translation_and_the_bulk_one_share_a_cupboard(self):
        """Иначе описание, переведённое по кнопке в раскрытой строке,
        общий перевод запросил бы заново."""
        titles_op.remember_abstract("1", "уже переведено")
        model = Model("мусор")
        found = titles_op.translate_all_abstracts(abouts(1), model)
        self.assertEqual(model.calls, 0)
        self.assertEqual(found["abstracts"]["1"], "уже переведено")


class TestDescriptionsSurviveTrouble(AboutBase):

    def test_a_book_without_a_description_is_not_asked_about(self):
        model = Model(honest_about())
        found = titles_op.translate_all_abstracts({"1": "", "2": "  "}, model)
        self.assertEqual(model.calls, 0)
        self.assertEqual(found["translated"], 0)

    def test_a_stubborn_batch_does_not_swallow_the_rest(self):
        """Та же механика, что у названий: пачку переспрашивают и делят."""
        found = titles_op.translate_all_abstracts(
            abouts(3), Model(honest_about(skip=("1",))))
        self.assertEqual(found["broken"], 1)
        self.assertTrue(found["abstracts"]["2"])
        self.assertTrue(found["abstracts"]["3"])

    def test_what_did_not_come_back_is_named(self):
        found = titles_op.translate_all_abstracts(abouts(2), Model("мусор"))
        self.assertEqual(sorted(found["missing"]), ["1", "2"])

    def test_a_broken_run_keeps_what_was_already_translated(self):
        titles_op.translate_all_abstracts(abouts(1), Model(honest_about()))
        titles_op.translate_all_abstracts(abouts(1, first=2), Model("мусор"))
        self.assertTrue(titles_op.abstract_of("1"))


if __name__ == "__main__":
    unittest.main()
