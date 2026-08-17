"""Оборванный ответ модели (2.1 ТЗ NEUROSTRAZH).

    Глава 395, попытка 1: ValueError: JSON в ответе не закрыт
    Глава 395, попытка 2: ValueError: JSON в ответе не закрыт
    Глава 395 разобрана (с третьего раза)

Модель упиралась в предел длины и обрывала JSON на середине, а обе
попытки уходили на тот же запрос — он и во второй раз не помещался.
Лечится с четырёх сторон: поднять предел, просить формат на уровне API,
достраивать пришедшее и, если не помогло, давать меньше текста.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from llm import client as llm  # noqa: E402
from llm.cache import mend_json, parse_json  # noqa: E402
from ops import analyze as analyze_op  # noqa: E402


class TestOutputLimit(unittest.TestCase):
    """Первое: на разбор главы двух тысяч токенов мало."""

    def test_the_limit_is_eight_thousand(self):
        self.assertEqual(settings.llm.max_output_tokens, 8192)

    def test_the_limit_reaches_the_request(self):
        sent = {}

        class Client(llm.LlmClient):
            def _request(self, path, payload=None):
                sent.update(payload or {})
                return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

        client = Client(key="AIzaX", model="flash")
        client.generate("промпт")
        self.assertEqual(sent["generationConfig"]["maxOutputTokens"], 8192)

    def test_json_is_asked_for_by_the_api_not_by_the_prompt(self):
        sent = {}

        class Client(llm.LlmClient):
            def _request(self, path, payload=None):
                sent.update(payload or {})
                return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

        Client(key="AIzaX", model="flash").generate("промпт")
        self.assertEqual(sent["generationConfig"]["responseMimeType"],
                         "application/json")

    def test_a_schema_can_be_demanded_too(self):
        """Со схемой модель не сможет вернуть ни текст вокруг, ни обрывок."""
        sent = {}

        class Client(llm.LlmClient):
            def _request(self, path, payload=None):
                sent.update(payload or {})
                return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

        shape = {"type": "object"}
        Client(key="AIzaX", model="flash").generate("промпт", schema=shape)
        self.assertEqual(sent["generationConfig"]["responseSchema"], shape)


class TestTruncationIsRecognised(unittest.TestCase):
    """Модель честно пишет об обрыве — гадать по виду JSON незачем."""

    def body(self, reason: str, text: str = '{"a": 1', used: int = 8192):
        return {"candidates": [{"content": {"parts": [{"text": text}]},
                                "finishReason": reason}],
                "usageMetadata": {"candidatesTokenCount": used}}

    def test_max_tokens_is_a_truncation(self):
        with self.assertRaises(llm.Truncated):
            llm._text_of(self.body("MAX_TOKENS"))

    def test_a_normal_finish_is_not(self):
        self.assertEqual(llm._text_of(self.body("STOP", '{"a": 1}')), '{"a": 1}')

    def test_what_came_through_is_kept(self):
        """Часть фактов там уже есть — терять их незачем."""
        try:
            llm._text_of(self.body("MAX_TOKENS", '{"entities": ['))
        except llm.Truncated as cut:
            self.assertEqual(cut.text, '{"entities": [')
        else:
            self.fail("обрыв не распознан")

    def test_the_journal_gets_the_token_count(self):
        """«В журнале писать, сколько токенов пришло» — прямо из ТЗ."""
        with self.assertRaises(llm.Truncated) as caught:
            llm._text_of(self.body("MAX_TOKENS", used=8192))
        self.assertIn("8192", str(caught.exception))


class TestMending(unittest.TestCase):
    """Третье: часто данные ещё спасаются."""

    def test_cut_inside_a_string(self):
        found = mend_json('{"герои": ["Тео", "Элиас"], "события": ["Тео нашёл')
        self.assertEqual(found["герои"], ["Тео", "Элиас"])

    def test_cut_after_a_comma(self):
        found = mend_json('{"герои": ["Тео", "Элиас"], "события": [')
        self.assertEqual(found["герои"], ["Тео", "Элиас"])

    def test_cut_on_a_number(self):
        found = mend_json('{"chapter": 395, "entities": ["Тео"], "сила": 12')
        self.assertEqual(found["chapter"], 395)
        self.assertEqual(found["entities"], ["Тео"])

    def test_cut_inside_a_nested_object(self):
        found = mend_json('{"карточки": [{"имя": "Тео", "роль": "главный"},'
                          ' {"имя": "Эли')
        self.assertEqual(len(found["карточки"]), 1)
        self.assertEqual(found["карточки"][0]["имя"], "Тео")

    def test_a_whole_answer_is_left_alone(self):
        self.assertEqual(mend_json('{"герои": ["Тео"]}'), {"герои": ["Тео"]})

    def test_nothing_to_save_says_so(self):
        self.assertIsNone(mend_json('{"a'))

    def test_not_an_object_at_all(self):
        self.assertIsNone(mend_json("просто текст"))

    def test_the_extractor_mends_by_itself(self):
        """Починка встроена в общий разбор, звать её отдельно не надо."""
        found = parse_json('{"entities": [{"name": "Тео"}], "events": [{"t')
        self.assertEqual(found["entities"], [{"name": "Тео"}])

    def test_hopeless_input_still_raises(self):
        with self.assertRaises(ValueError):
            parse_json('{"a')


class Chapter:
    number = 395
    title = "Глава 395"
    label = "395"
    source = "/книга/395.txt"
    text = "\n".join(f"Абзац {n} про Тео и Элиаса." for n in range(1, 41))


class Model:
    """Модель, которая обрывается, пока кусок длиннее предела."""

    def __init__(self, limit: int, partial: str = ""):
        self.limit = limit
        self.partial = partial
        self.sizes: list[int] = []

    def generate(self, prompt, json_only=True, model="", schema=None):
        size = len([line for line in prompt.splitlines()
                    if line.startswith("Абзац")])
        self.sizes.append(size)
        if size > self.limit:
            raise llm.Truncated("ответ оборван по пределу длины", self.partial)
        return json.dumps({"chapter": 395,
                           "entities": [{"name": f"Тео{size}"}],
                           "events": [{"type": "встреча"}]},
                          ensure_ascii=False)


class TestSplittingInstead(unittest.TestCase):
    """Четвёртое: не тратить попытки на тот же запрос."""

    def setUp(self):
        self.said: list[str] = []

    def say(self, text, kind="info"):
        self.said.append(f"[{kind}] {text}")

    def test_what_came_through_is_used_before_splitting(self):
        partial = ('{"chapter": 395, "entities": [{"name": "Тео"}],'
                   ' "events": [{"type": "вст')
        model = Model(limit=0, partial=partial)
        found = analyze_op._ask(model, Chapter(), "flash", say=self.say)
        self.assertEqual(found["entities"], [{"name": "Тео"}])
        self.assertEqual(len(model.sizes), 1, "делить не понадобилось")
        self.assertTrue(any("достроили" in line for line in self.said))

    def test_the_chapter_is_halved_until_it_fits(self):
        model = Model(limit=12)
        analyze_op._ask(model, Chapter(), "flash", say=self.say)
        self.assertEqual(model.sizes[0], 40)
        self.assertLessEqual(max(model.sizes[1:]), 20)
        self.assertTrue(any("делю кусок пополам" in line for line in self.said))

    def test_the_halves_are_merged(self):
        model = Model(limit=12)
        found = analyze_op._ask(model, Chapter(), "flash", say=self.say)
        # Каждая половина назвала своё лицо — в реестр идут оба.
        self.assertGreater(len(found["entities"]), 1)

    def test_repeats_are_not_doubled_by_the_merge(self):
        """Одно и то же лицо есть в обеих половинах, место ему одно."""
        model = Model(limit=12)
        found = analyze_op._ask(model, Chapter(), "flash", say=self.say)
        self.assertEqual(len(found["events"]), 1)

    def test_it_gives_up_instead_of_splitting_forever(self):
        model = Model(limit=0)
        with self.assertRaises(llm.Truncated):
            analyze_op._ask(model, Chapter(), "flash", say=self.say)
        self.assertEqual(len(model.sizes), analyze_op.MAX_SPLIT)

    def test_the_text_is_cut_at_a_paragraph_not_mid_word(self):
        left, right = analyze_op._halves("первый абзац\nвторой абзац")
        self.assertEqual(left, "первый абзац")
        self.assertEqual(right, "второй абзац")

    def test_a_text_without_line_breaks_is_still_split(self):
        left, right = analyze_op._halves("а" * 100)
        self.assertTrue(left and right)

    def test_merging_keeps_everything_from_both_sides(self):
        left = {"entities": [{"name": "Тео"}], "events": [{"type": "встреча"}]}
        right = {"entities": [{"name": "Тео"}, {"name": "Элиас"}]}
        found = analyze_op._merge_facts(left, right)
        self.assertEqual(len(found["entities"]), 2)
        self.assertEqual(len(found["events"]), 1)


class TestNoWastedRetries(unittest.TestCase):
    """Ровно то, на что жаловались: две попытки на один и тот же результат."""

    def test_truncation_is_not_retried_by_the_outer_loop(self):
        source = (Path(__file__).resolve().parent.parent
                  / "ops" / "analyze.py").read_text(encoding="utf-8")
        body = source.split("def one(chapter)", 1)[1].split("\n    if pending", 1)[0]
        self.assertIn("except Truncated as cut:", body)
        self.assertIn("break", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
