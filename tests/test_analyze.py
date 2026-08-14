"""Смысловой анализ (часть 3 ТЗ NEUROSTRAZH).

Интернет и ключ не нужны: модель подменяется заглушкой, которая отдаёт
заранее заготовленные факты. Так проверяется вся цепочка — сбор, кэш,
реестр, поиск противоречий — без единого запроса наружу.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core.models import Chapter  # noqa: E402
from core.registry import (  # noqa: E402
    Entity,
    Event,
    Link,
    Registry,
    looks_same,
)
from llm.cache import FactsCache, parse_json  # noqa: E402
from ops import analyze, contradictions, glossary  # noqa: E402
from ops.base import Cancelled, Progress  # noqa: E402


class FakeModel:
    """Модель, которая отдаёт заготовленный ответ на каждую главу.

    Ответы задаются по номеру главы; чего нет — пустой разбор.
    """

    def __init__(self, by_chapter=None, fail_times=0, answer=None):
        self.by_chapter = by_chapter or {}
        self.fail_times = fail_times
        self.answer = answer
        self.calls = []
        self._lock = threading.Lock()

    def generate(self, prompt, json_only=True, model=""):
        with self._lock:
            self.calls.append(prompt)
            if self.fail_times > 0:
                self.fail_times -= 1
                raise RuntimeError("модель не ответила")

        if self.answer is not None:
            return self.answer

        number = None
        for line in prompt.splitlines():
            if line.startswith("Номер главы:"):
                try:
                    number = int(line.split(":", 1)[1].strip())
                except ValueError:
                    number = None
                break
        facts = self.by_chapter.get(number, {"chapter": number, "entities": [],
                                             "links": [], "events": []})
        return json.dumps(facts, ensure_ascii=False)

    def close(self):
        pass


def facts(number, entities=(), links=(), events=()):
    return {
        "chapter": number,
        "entities": list(entities),
        "links": list(links),
        "events": list(events),
    }


class AnalyzeTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.book = self.tmp / "книга"
        self.book.mkdir()

    def write(self, numbers, body="Текст главы. " * 20):
        for number in numbers:
            formats.write(
                self.book / f"Глава {number}.txt",
                [Chapter(number=number, title=f"Глава {number}",
                         paragraphs=[body])],
                headings=True)
        return str(self.book)


class TestCollect(AnalyzeTestCase):
    """3.2: сбор фактов, кэш, повторы, отмена."""

    def test_every_chapter_is_parsed_and_cached(self):
        targets = self.write([201, 202, 203])
        model = FakeModel()
        report = analyze.collect(targets, model, root=self.book, concurrency=2)

        self.assertEqual(report.total, 3)
        self.assertEqual(report.parsed, 3)
        self.assertEqual(report.failed, 0)
        self.assertEqual(FactsCache(self.book).count(), 3)

    def test_second_run_uses_the_cache(self):
        """Разбор стоит денег — заново шлём только новое."""
        targets = self.write([201, 202])
        analyze.collect(targets, FakeModel(), root=self.book)

        again = FakeModel()
        report = analyze.collect(targets, again, root=self.book)
        self.assertEqual(report.cached, 2)
        self.assertEqual(report.parsed, 0)
        self.assertEqual(again.calls, [])

    def test_changed_chapter_is_parsed_again(self):
        """Главу почистили — факты по ней собираются заново."""
        targets = self.write([201])
        analyze.collect(targets, FakeModel(), root=self.book)

        formats.write(self.book / "Глава 201.txt",
                      [Chapter(number=201, title="Глава 201",
                               paragraphs=["Совсем другой текст главы."])],
                      headings=True)
        model = FakeModel()
        report = analyze.collect(targets, model, root=self.book)
        self.assertEqual(report.parsed, 1)
        self.assertEqual(report.cached, 0)

    def test_force_ignores_the_cache(self):
        targets = self.write([201])
        analyze.collect(targets, FakeModel(), root=self.book)
        report = analyze.collect(targets, FakeModel(), root=self.book, force=True)
        self.assertEqual(report.parsed, 1)

    def test_unparsable_answer_is_retried_then_given_up(self):
        """Ответ не разобрался — повтор, потом глава помечается."""
        targets = self.write([201])
        model = FakeModel(answer="это не JSON вовсе")
        report = analyze.collect(targets, model, root=self.book, retries=2)

        self.assertEqual(report.failed, 1)
        self.assertEqual(report.parsed, 0)
        # Одна попытка плюс два повтора.
        self.assertEqual(len(model.calls), 3)

    def test_retry_succeeds_after_a_hiccup(self):
        targets = self.write([201])
        model = FakeModel(fail_times=1)
        report = analyze.collect(targets, model, root=self.book, retries=2)
        self.assertEqual(report.parsed, 1)
        self.assertEqual(report.failed, 0)

    def test_one_bad_chapter_does_not_stop_the_rest(self):
        targets = self.write([201, 202, 203])
        model = FakeModel(fail_times=3)
        report = analyze.collect(targets, model, root=self.book,
                                 retries=0, concurrency=1)
        self.assertEqual(report.failed, 3)

        model = FakeModel(fail_times=1)
        report = analyze.collect(targets, model, root=self.book,
                                 retries=0, concurrency=1)
        self.assertEqual(report.parsed, 2)
        self.assertEqual(report.failed, 1)

    def test_progress_and_cancel(self):
        targets = self.write([201, 202, 203])
        seen = []
        progress = Progress(on_progress=lambda d, t, m: seen.append((d, t)))
        analyze.collect(targets, FakeModel(), root=self.book, progress=progress)
        self.assertTrue(seen)
        self.assertEqual(seen[-1][1], 3)

        cancel = threading.Event()
        cancel.set()
        stopped = Progress(cancel=cancel)
        with self.assertRaises(Cancelled):
            analyze.collect(targets, FakeModel(), root=self.book,
                            progress=stopped, force=True)

    def test_scan_reports_what_is_pending(self):
        targets = self.write([201, 202])
        info = analyze.scan(targets, root=self.book)
        self.assertEqual(info["total"], 2)
        self.assertEqual(info["cached"], 0)
        self.assertEqual(info["estimate"]["to_send"], 2)

        analyze.collect(targets, FakeModel(), root=self.book)
        info = analyze.scan(targets, root=self.book)
        self.assertEqual(info["cached"], 2)
        self.assertEqual(info["estimate"]["to_send"], 0)


class TestRegistryBuild(AnalyzeTestCase):
    """3.3: факты сводятся в реестр, правка человека не затирается."""

    def collect_with(self, by_chapter):
        targets = self.write(sorted(by_chapter))
        analyze.collect(targets, FakeModel(by_chapter), root=self.book)
        return analyze.rebuild(self.book)

    def test_entities_links_and_events_land_in_the_registry(self):
        registry = self.collect_with({
            12: facts(12,
                      entities=[{"name": "Тео", "type": "персонаж"},
                                {"name": "богомол", "type": "существо"}],
                      links=[{"from": "богомол", "to": "Тео",
                              "type": "принадлежит"}],
                      events=[{"type": "получение", "actor": "Тео",
                               "object": "богомол", "quote": "Тео получил богомола"}]),
        })
        self.assertIsNotNone(registry.find("Тео"))
        self.assertEqual(registry.owner_of(registry.find("богомол").id),
                         registry.find("Тео").id)
        self.assertEqual(len(registry.events), 1)

    def test_first_chapter_is_the_earliest_one(self):
        registry = self.collect_with({
            5: facts(5, entities=[{"name": "Тео", "type": "персонаж"}]),
            9: facts(9, entities=[{"name": "Тео", "type": "персонаж"}]),
        })
        self.assertEqual(registry.find("Тео").first_chapter, 5)

    def test_name_variants_are_merged(self):
        """«Тео» и «Тэо» — одна сущность, второй вариант в aliases."""
        registry = self.collect_with({
            1: facts(1, entities=[{"name": "Тео", "type": "персонаж"}]),
            2: facts(2, entities=[{"name": "Тэо", "type": "персонаж"}]),
        })
        entity = registry.find("Тео")
        self.assertIn("Тэо", entity.aliases)
        self.assertEqual(len(registry.of_type("персонаж")), 1)

    def test_confirmed_records_survive_a_rebuild(self):
        """Человек уже сказал, как правильно, — переубеждать незачем."""
        registry = self.collect_with({
            1: facts(1, entities=[{"name": "Тео", "type": "персонаж"}]),
        })
        entity = registry.find("Тео")
        entity.confirmed = True
        entity.attributes["ранг"] = "барон"
        analyze.save_registry(self.book, registry)

        again = analyze.rebuild(self.book)
        kept = again.find("Тео")
        self.assertTrue(kept.confirmed)
        self.assertEqual(kept.attributes["ранг"], "барон")

    def test_registry_saves_next_to_the_book(self):
        self.collect_with({1: facts(1, entities=[{"name": "Тео"}])})
        self.assertTrue((self.book / "analysis" / "registry.json").is_file())

    def test_broken_registry_does_not_break_the_run(self):
        path = self.book / "analysis" / "registry.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{битый", encoding="utf-8")
        self.assertEqual(analyze.load_registry(self.book).entities, {})


class TestContradictions(AnalyzeTestCase):
    """3.4: восемь проверок, все универсальные."""

    def build(self, by_chapter):
        targets = self.write(sorted(by_chapter))
        analyze.collect(targets, FakeModel(by_chapter), root=self.book)
        return analyze.rebuild(self.book)

    def kinds(self, registry, **kwargs):
        report = contradictions.check(registry, self.book, **kwargs)
        return [f.kind for f in report.findings], report

    def test_foreign_entity(self):
        """Тот самый случай из ТЗ: призвал чужого питомца."""
        registry = self.build({
            12: facts(12,
                      entities=[{"name": "Тео", "type": "персонаж"},
                                {"name": "Элиас", "type": "персонаж"},
                                {"name": "обезьяна", "type": "существо"}],
                      links=[{"from": "обезьяна", "to": "Элиас",
                              "type": "принадлежит"}]),
            209: facts(209,
                       entities=[{"name": "Тео", "type": "персонаж"}],
                       events=[{"type": "использование", "actor": "Тео",
                                "object": "обезьяна",
                                "quote": "Тео призвал свою обезьяну"}]),
        })
        kinds, report = self.kinds(registry, kinds=["foreign_entity"])
        self.assertIn("foreign_entity", kinds)
        finding = next(f for f in report.findings if f.kind == "foreign_entity")
        self.assertEqual(finding.chapter, 209)
        self.assertIn("Элиас", finding.message)
        self.assertIn("обезьяну", finding.quote)

    def test_owner_using_their_own_is_not_a_finding(self):
        registry = self.build({
            12: facts(12,
                      entities=[{"name": "Тео", "type": "персонаж"},
                                {"name": "богомол", "type": "существо"}],
                      links=[{"from": "богомол", "to": "Тео",
                              "type": "принадлежит"}],
                      events=[{"type": "использование", "actor": "Тео",
                               "object": "богомол", "quote": "Тео призвал богомола"}]),
        })
        kinds, _ = self.kinds(registry, kinds=["foreign_entity"])
        self.assertEqual(kinds, [])

    def test_action_after_death(self):
        registry = self.build({
            10: facts(10, entities=[{"name": "Варн", "type": "персонаж",
                                     "status": "мёртв"}]),
            11: facts(11,
                      entities=[{"name": "Варн", "type": "персонаж",
                                 "status": "мёртв"}],
                      events=[{"type": "встреча", "actor": "Варн",
                               "object": "", "quote": "Варн шагнул вперёд"}]),
        })
        kinds, _ = self.kinds(registry, kinds=["after_death"])
        self.assertIn("after_death", kinds)

    def test_foreign_ability(self):
        registry = self.build({
            5: facts(5,
                     entities=[{"name": "Тео", "type": "персонаж"},
                               {"name": "Элиас", "type": "персонаж"},
                               {"name": "частичное приручение",
                                "type": "способность"}],
                     links=[{"from": "частичное приручение", "to": "Элиас",
                             "type": "принадлежит"}]),
            30: facts(30,
                      entities=[{"name": "Тео", "type": "персонаж"}],
                      events=[{"type": "использование", "actor": "Тео",
                               "object": "частичное приручение",
                               "quote": "Тео применил частичное приручение"}]),
        })
        kinds, report = self.kinds(registry, kinds=["foreign_ability"])
        self.assertIn("foreign_ability", kinds)
        self.assertIn("способность",
                      next(f for f in report.findings).message)

    def test_name_variants_are_reported(self):
        registry = Registry()
        registry.add_entity(Entity(name="Тео", type="персонаж"), merge=False)
        registry.add_entity(Entity(name="Тэо", type="персонаж"), merge=False)
        kinds, _ = self.kinds(registry, kinds=["name_variants"])
        self.assertIn("name_variants", kinds)

    def test_attribute_change_without_an_event(self):
        registry = self.build({
            1: facts(1, entities=[{"name": "Тео", "type": "персонаж",
                                   "attributes": {"пол": "мужской"}}]),
            40: facts(40, entities=[{"name": "Тео", "type": "персонаж",
                                     "attributes": {"пол": "женский"}}]),
        })
        kinds, report = self.kinds(registry, kinds=["attribute_change"])
        self.assertIn("attribute_change", kinds)
        self.assertIn("пол", report.findings[0].message)

    def test_link_conflict(self):
        """Слуга внезапно назван братом."""
        registry = self.build({
            3: facts(3,
                     entities=[{"name": "Тео", "type": "персонаж"},
                               {"name": "Элиас", "type": "персонаж"}],
                     links=[{"from": "Элиас", "to": "Тео", "type": "слуга"}]),
            60: facts(60,
                      entities=[{"name": "Тео", "type": "персонаж"},
                                {"name": "Элиас", "type": "персонаж"}],
                      links=[{"from": "Элиас", "to": "Тео",
                              "type": "родственник"}]),
        })
        kinds, _ = self.kinds(registry, kinds=["link_conflict"])
        self.assertIn("link_conflict", kinds)

    def test_too_early(self):
        registry = self.build({
            50: facts(50, entities=[{"name": "Кайрен", "type": "персонаж"}]),
        })
        # Реестр говорит, что появляется в 50-й, а в фактах она есть и в 10-й.
        registry.find("Кайрен").first_chapter = 90
        kinds, _ = self.kinds(registry, kinds=["too_early"])
        self.assertIn("too_early", kinds)

    def test_location_clash(self):
        registry = self.build({
            7: facts(7,
                     entities=[{"name": "Тео", "type": "персонаж"},
                               {"name": "Столица", "type": "локация"},
                               {"name": "Пустошь", "type": "локация"}],
                     links=[{"from": "Тео", "to": "Столица",
                             "type": "находится_в"},
                            {"from": "Тео", "to": "Пустошь",
                             "type": "находится_в"}],
                     events=[{"type": "встреча", "actor": "Тео",
                              "object": "", "quote": "Тео огляделся"}]),
        })
        kinds, _ = self.kinds(registry, kinds=["location_clash"])
        self.assertIn("location_clash", kinds)

    def test_clean_book_has_no_findings(self):
        registry = self.build({
            1: facts(1,
                     entities=[{"name": "Тео", "type": "персонаж"},
                               {"name": "богомол", "type": "существо"}],
                     links=[{"from": "богомол", "to": "Тео",
                             "type": "принадлежит"}],
                     events=[{"type": "использование", "actor": "Тео",
                              "object": "богомол", "quote": "Тео позвал богомола"}]),
        })
        report = contradictions.check(registry, self.book)
        self.assertEqual(report.findings, [])

    def test_quote_is_trimmed(self):
        long_quote = "А" * 500
        registry = self.build({
            1: facts(1,
                     entities=[{"name": "Тео", "type": "персонаж"},
                               {"name": "Элиас", "type": "персонаж"},
                               {"name": "обезьяна", "type": "существо"}],
                     links=[{"from": "обезьяна", "to": "Элиас",
                             "type": "принадлежит"}],
                     events=[{"type": "использование", "actor": "Тео",
                              "object": "обезьяна", "quote": long_quote}]),
        })
        report = contradictions.check(registry, self.book,
                                      kinds=["foreign_entity"])
        self.assertLessEqual(len(report.findings[0].quote), 200)


class TestGlossary(unittest.TestCase):
    """3.3 импорт и 3.5 выгрузка."""

    def test_every_input_format(self):
        cases = {
            "Тео = Theo\nЭлиас = Elias\n": 2,
            '{"Тео": "Theo", "Элиас": "Elias"}': 2,
            '[{"name": "Тео", "translation": "Theo"}]': 1,
            "имя,перевод\nТео,Theo\nЭлиас,Elias\n": 2,
            "| имя | перевод |\n|---|---|\n| Тео | Theo |\n": 1,
            "Тео → Theo\n": 1,
        }
        for text, count in cases.items():
            with self.subTest(text=text[:24]):
                self.assertEqual(len(glossary.parse(text)), count)

    def test_comments_and_blank_lines_are_skipped(self):
        pairs = glossary.parse("# заголовок\n\nТео = Theo\n// ещё\n")
        self.assertEqual(pairs, [("Тео", "Theo")])

    def test_imported_records_are_confirmed_at_once(self):
        registry = Registry()
        glossary.load_into(registry, "Тео = Theo")
        entity = registry.find("Тео")
        self.assertTrue(entity.confirmed)
        self.assertEqual(entity.attributes["перевод"], "Theo")

    def test_import_does_not_rename_the_entity(self):
        """Имя — то, как сущность зовут в тексте; подменять его нельзя."""
        registry = Registry()
        registry.add_entity(Entity(name="Тео", type="персонаж"))
        glossary.load_into(registry, "Тео = Theo")
        self.assertEqual(registry.find("Тео").name, "Тео")
        self.assertIn("Theo", registry.find("Тео").aliases)

    def test_export_points_variants_at_the_canonical_name(self):
        """«Тэо = Тео», а не наоборот.

        Смысл выгрузки — чтобы имена перестали плавать. Обратная запись
        велела бы переводчику писать вариант, то есть ровно то, от чего
        уходим.
        """
        registry = Registry()
        registry.add_entity(Entity(name="Тео", type="персонаж",
                                   aliases=["Тэо"]), merge=False)
        text = glossary.dump(registry, "txt")
        self.assertIn("Тэо = Тео", text)
        self.assertNotIn("Тео = Тэо", text)

    def test_export_prefers_the_translation(self):
        registry = Registry()
        registry.add_entity(Entity(name="богомол", type="существо",
                                   aliases=["мантис"],
                                   attributes={"перевод": "Mantis"}), merge=False)
        text = glossary.dump(registry, "txt")
        self.assertIn("богомол = Mantis", text)
        self.assertIn("мантис = Mantis", text)

    def test_export_round_trip(self):
        registry = Registry()
        glossary.load_into(registry, "Тео = Theo\nЭлиас = Elias")
        for fmt in ("txt", "json", "csv", "md"):
            with self.subTest(fmt=fmt):
                text = glossary.dump(registry, fmt)
                back = Registry()
                glossary.load_into(back, text)
                self.assertIsNotNone(back.find("Тео"), fmt)

    def test_cards_carry_links_and_chapters(self):
        registry = Registry()
        registry.add_entity(Entity(name="Тео", type="персонаж", first_chapter=1))
        registry.add_entity(Entity(name="Элиас", type="персонаж"))
        registry.add_link(Link(source="элиас", target="тео", type="слуга"))
        registry.add_event(Event(chapter=9, actor="тео", type="встреча"))

        # Карточки идут по алфавиту, поэтому ищем по имени, а не по месту.
        card = next(c for c in glossary.cards(registry, "персонаж")
                    if c["name"] == "Тео")
        self.assertEqual(card["chapters"], [9])
        self.assertTrue(card["links"])
        self.assertIn("Тео", glossary.cards_text(registry))


class TestRegistryPieces(unittest.TestCase):
    """Мелочи реестра, на которых держится всё остальное."""

    def test_short_names_are_not_merged(self):
        """«Ли» и «Ло» — разные люди, хотя различие в один символ."""
        self.assertFalse(looks_same("Ли", "Ло"))
        self.assertTrue(looks_same("Тео", "Тэо"))

    def test_merge_moves_links_and_events(self):
        registry = Registry()
        keep = registry.add_entity(Entity(name="Тео", type="персонаж"), merge=False)
        drop = registry.add_entity(Entity(name="Тэодор", type="персонаж"), merge=False)
        registry.add_link(Link(source=drop.id, target="кто-то", type="слуга"))
        registry.add_event(Event(chapter=3, actor=drop.id))

        registry.merge(keep.id, drop.id)
        self.assertNotIn(drop.id, registry.entities)
        self.assertEqual(registry.links[0].source, keep.id)
        self.assertEqual(registry.events[0].actor, keep.id)
        self.assertIn("Тэодор", keep.aliases)

    def test_save_and_load(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = Registry()
            registry.add_entity(Entity(name="Тео", type="персонаж", confirmed=True))
            registry.add_link(Link(source="тео", target="х", type="слуга"))
            registry.save(path)

            back = Registry.load(path)
            self.assertTrue(back.find("Тео").confirmed)
            self.assertEqual(len(back.links), 1)

    def test_json_is_extracted_from_a_wrapped_answer(self):
        self.assertEqual(parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json('Вот: {"q": "скобка } внутри"}')["q"],
                         "скобка } внутри")
        with self.assertRaises(ValueError):
            parse_json("никакого json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
