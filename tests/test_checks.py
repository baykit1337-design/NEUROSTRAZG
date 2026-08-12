"""Тесты расширенной проверки и очистки (разделы 13 и 14 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import checks, cleanup, textcheck  # noqa: E402

FILLER = "Обычный абзац русского текста, достаточно длинный для проверки. " * 6


class RuleTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)

    def check(self, text: str, kinds, **kwargs):
        path = self.tmp / "a.txt"
        path.write_text(text, encoding="utf-8")
        return textcheck.check(path, kinds, **kwargs).findings

    def kinds_of(self, findings) -> set:
        return {f.kind for f in findings}


class TestRegistry(unittest.TestCase):
    def test_four_groups(self):
        groups = checks.grouped()
        self.assertEqual(
            [g["group"] for g in groups],
            [checks.GROUP_TRANSLATION, checks.GROUP_PUNCTUATION,
             checks.GROUP_STRUCTURE, checks.GROUP_TECH],
        )

    def test_every_rule_has_a_tip(self):
        for rule in checks.RULES:
            with self.subTest(rule=rule.key):
                self.assertTrue(rule.tip.strip(), rule.key)

    def test_presets(self):
        self.assertEqual(set(checks.PRESET_KEYS["full"]), set(checks.ALL_KEYS))
        self.assertTrue(checks.PRESET_KEYS["quick"])
        self.assertTrue(checks.PRESET_KEYS["translation"])

    def test_quick_preset_is_only_technical(self):
        tech = {r.key for r in checks.RULES if r.group == checks.GROUP_TECH}
        self.assertEqual(set(checks.PRESET_KEYS["quick"]), tech)

    def test_textcheck_knows_every_rule(self):
        self.assertEqual(set(textcheck.ALL_KINDS), set(checks.ALL_KEYS))


class TestTranslationChecks(RuleTestCase):
    def test_homoglyph_found(self):
        """Латинская «o» внутри русского слова — самая коварная ошибка."""
        found = self.check(f"Слово сoбака тут.\n{FILLER}", ["homoglyph"])
        self.assertEqual(len(found), 1)
        self.assertIn("сoбака", found[0].context)

    def test_clean_russian_word_is_not_flagged(self):
        self.assertEqual(self.check(f"Слово собака тут.\n{FILLER}", ["homoglyph"]), [])

    def test_pure_latin_word_is_not_a_homoglyph(self):
        self.assertEqual(self.check(f"Слово system тут.\n{FILLER}", ["homoglyph"]), [])

    def test_untranslated_sentence(self):
        found = self.check(
            f"This sentence is entirely in english and quite long.\n{FILLER}",
            ["untranslated"])
        self.assertEqual(len(found), 1)

    def test_russian_sentence_with_one_latin_word_is_fine(self):
        self.assertEqual(
            self.check(f"Он открыл файл manager и ушёл домой обедать.\n{FILLER}",
                       ["untranslated"]), [])

    def test_name_variants_grouped(self):
        text = "Он сказал Тео.\nПотом Тэо ответил.\nСнова Тео вошёл.\nИ Тэо кивнул.\n"
        path = self.tmp / "a.txt"
        path.write_text(text + FILLER, encoding="utf-8")
        report = textcheck.check(path, ["names"])
        self.assertEqual(len(report.name_groups), 1)
        words = {row["word"] for row in report.name_groups[0]}
        self.assertEqual(words, {"Тео", "Тэо"})

    def test_single_spelling_is_not_a_variant(self):
        path = self.tmp / "a.txt"
        path.write_text("Он сказал Тео.\nСнова Тео вошёл.\n" + FILLER, encoding="utf-8")
        self.assertEqual(textcheck.check(path, ["names"]).name_groups, [])

    def test_glossary_mismatch(self):
        (self.tmp / "glossary.txt").write_text("Sword = Меч\n", encoding="utf-8")
        found = self.check(f"Он поднял Sword с земли.\n{FILLER}", ["glossary"])
        self.assertEqual(len(found), 1)
        self.assertIn("Меч", found[0].fragment)

    def test_glossary_respected_is_clean(self):
        (self.tmp / "glossary.txt").write_text("Sword = Меч\n", encoding="utf-8")
        self.assertEqual(self.check(f"Он поднял Меч с земли.\n{FILLER}", ["glossary"]), [])

    def test_imperial_units(self):
        found = self.check(f"Он прошёл 5 миль и весил 200 фунтов.\n{FILLER}", ["imperial"])
        self.assertEqual(len(found), 2)

    def test_metric_units_are_fine(self):
        self.assertEqual(
            self.check(f"Он прошёл 5 километров и весил 90 килограммов.\n{FILLER}",
                       ["imperial"]), [])


class TestPunctuationChecks(RuleTestCase):
    def test_dialog_dash(self):
        found = self.check(f"- Привет, сказал он.\n{FILLER}", ["dialog_dash"])
        self.assertEqual(len(found), 1)

    def test_proper_dash_is_fine(self):
        self.assertEqual(self.check(f"— Привет, сказал он.\n{FILLER}", ["dialog_dash"]), [])

    def test_three_dots(self):
        self.assertEqual(len(self.check(f"Пауза...\n{FILLER}", ["three_dots"])), 1)

    def test_ellipsis_is_fine(self):
        self.assertEqual(self.check(f"Пауза…\n{FILLER}", ["three_dots"]), [])

    def test_double_space_and_space_before_punctuation(self):
        self.assertTrue(self.check(f"Двойной  пробел.\n{FILLER}", ["spaces"]))
        self.assertTrue(self.check(f"Пробел перед точкой .\n{FILLER}", ["spaces"]))

    def test_missing_space_after_punctuation(self):
        self.assertEqual(len(self.check(f"Конец.Начало снова.\n{FILLER}", ["no_space"])), 1)

    def test_multiple_punctuation(self):
        self.assertTrue(self.check(f"Что?!! правда\n{FILLER}", ["multi_punct"]))

    def test_edge_spaces(self):
        self.assertTrue(self.check(f"   Абзац с краю.\n{FILLER}", ["edge_space"]))

    def test_hyphen_used_as_dash(self):
        self.assertTrue(self.check(f"Он сказал - и замолчал.\n{FILLER}", ["hyphen_dash"]))

    def test_quote_mix_reported_once_per_book(self):
        path = self.tmp / "a.txt"
        path.write_text(f'«ёлочки» и "прямые" вперемешку.\n{FILLER}', encoding="utf-8")
        report = textcheck.check(path, ["quotes"])
        self.assertEqual(len(report.quote_kinds), 2)

    def test_single_quote_kind_is_clean(self):
        path = self.tmp / "a.txt"
        path.write_text(f"Только «ёлочки» тут.\n{FILLER}", encoding="utf-8")
        self.assertEqual(textcheck.check(path, ["quotes"]).findings, [])


class TestStructureChecks(RuleTestCase):
    def test_repeated_word(self):
        self.assertEqual(len(self.check(f"Он в в лесу гулял.\n{FILLER}", ["repeated_word"])), 1)

    def test_paragraph_without_final_mark(self):
        self.assertTrue(self.check("Абзац без знака в конце\n", ["no_end"]))

    def test_paragraph_with_final_mark_is_clean(self):
        self.assertEqual(self.check("Абзац со знаком в конце.\n", ["no_end"]), [])

    def test_long_paragraph(self):
        self.assertTrue(self.check("а" * 1600 + "\n", ["long_paragraph"]))

    def test_all_caps_line(self):
        self.assertTrue(self.check("ЭТО ОЧЕНЬ ДЛИННАЯ СТРОКА ЦЕЛИКОМ КАПСОМ ТУТ\n",
                                   ["caps_line"]))

    def test_short_caps_is_fine(self):
        self.assertEqual(self.check("КОРОТКО\n", ["caps_line"]), [])

    def test_empty_chapter(self):
        found = self.check("\n\n", ["empty_chapter"])
        self.assertEqual(len(found), 1)
        self.assertIn("пустая", found[0].fragment)

    def test_single_paragraph_chapter(self):
        found = self.check("Единственный абзац.\n", ["empty_chapter"])
        self.assertIn("одного абзаца", found[0].fragment)

    def test_capital_mid_sentence(self):
        self.assertTrue(self.check(f"он пошёл Домой вечером.\n{FILLER}", ["mid_capital"]))


class TestCleanupAdditions(unittest.TestCase):
    """Раздел 14: новые безопасные автозамены."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)
        self.src = self.tmp / "in"
        self.src.mkdir()

    def clean(self, text: str, kinds) -> str:
        (self.src / "a.txt").write_text(text, encoding="utf-8")
        out = self.tmp / "out"
        cleanup.clean(self.src, list(kinds), out)
        return (out / "a.txt").read_text(encoding="utf-8")

    def test_three_dots_become_ellipsis(self):
        self.assertIn("Пауза…", self.clean("Пауза...", ["ellipsis"]))

    def test_double_spaces_collapse(self):
        self.assertIn("Один пробел", self.clean("Один  пробел", ["spaces"]))

    def test_space_before_punctuation_removed(self):
        self.assertIn("точкой.", self.clean("Перед точкой .", ["spaces"]))

    def test_dialog_hyphen_becomes_dash(self):
        self.assertTrue(self.clean("- Привет", ["dialog_dash"]).startswith("—"))

    def test_edge_spaces_trimmed(self):
        result = self.clean("   Абзац   ", ["edge_space"])
        self.assertEqual(result.strip("\n"), "Абзац")

    def test_multiple_punctuation_reduced(self):
        self.assertIn("Что!", self.clean("Что!!!", ["multi_punct"]))
        self.assertIn("Как?", self.clean("Как???", ["multi_punct"]))

    def test_homoglyphs_are_never_fixed_automatically(self):
        """Машинальная правка гомоглифов потеряет текст — только показываем."""
        self.assertNotIn("homoglyph", cleanup.ALL_KINDS)
        self.assertNotIn("names", cleanup.ALL_KINDS)
        self.assertNotIn("glossary", cleanup.ALL_KINDS)

    def test_cjk_and_latin_still_untouched(self):
        result = self.clean("Текст 修炼 и manager тут.", cleanup.ALL_KINDS)
        self.assertIn("修炼", result)
        self.assertIn("manager", result)

    def test_counts_reported_per_kind(self):
        (self.src / "a.txt").write_text("Пауза... и  двойной пробел", encoding="utf-8")
        report = cleanup.clean(self.src, ["ellipsis", "spaces"], self.tmp / "out")
        counts = {row["kind"]: row["count"] for row in report.as_dict()["counts"]}
        self.assertEqual(counts.get("ellipsis"), 1)
        self.assertGreater(counts.get("spaces", 0), 0)


class TestChecksWebApi(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()

    def test_rules_endpoint_returns_groups_and_presets(self):
        body = self.app.get("/api/check/rules").get_json()
        self.assertEqual(len(body["groups"]), 4)
        self.assertEqual(
            sum(len(g["rules"]) for g in body["groups"]), len(checks.ALL_KEYS)
        )
        self.assertEqual({p["key"] for p in body["presets"]}, set(checks.PRESETS))

    def test_rules_endpoint_lists_cleanup_kinds(self):
        body = self.app.get("/api/check/rules").get_json()
        self.assertEqual(
            {row["key"] for row in body["clean_kinds"]}, set(cleanup.ALL_KINDS)
        )

    def test_new_check_runs_through_the_api(self):
        from webapp.app import JOBS

        folder = self.tmp / "книга"
        folder.mkdir()
        (folder / "a.txt").write_text(f"Слово сoбака тут.\n{FILLER}", encoding="utf-8")

        res = self.app.post("/api/check/start",
                            json={"targets": [str(folder)], "kinds": ["homoglyph"]})
        job_id = res.get_json()["job"]["id"]
        JOBS[job_id].thread.join(timeout=60)

        report = self.app.get(f"/api/job/{job_id}").get_json()["job"]["report"]
        self.assertEqual(report["total"], 1)

    def test_new_cleanup_runs_through_the_api(self):
        from webapp.app import JOBS

        folder = self.tmp / "гряз"
        folder.mkdir()
        (folder / "a.txt").write_text("Пауза... и  двойной", encoding="utf-8")

        res = self.app.post("/api/clean/start", json={
            "targets": [str(folder)], "base": str(self.tmp), "folder": "Чисто",
            "kinds": ["ellipsis", "spaces"]})
        job_id = res.get_json()["job"]["id"]
        JOBS[job_id].thread.join(timeout=60)

        job = self.app.get(f"/api/job/{job_id}").get_json()["job"]
        self.assertIsNone(job["error"])
        self.assertIn("…", (self.tmp / "Чисто" / "a.txt").read_text(encoding="utf-8"))


class TestBranding(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent.parent
        self.html = (root / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
        self.fonts = root / "webapp" / "static" / "fonts"

    def test_latin_name(self):
        self.assertIn("<title>NEUROSTRAZH 2.0</title>", self.html)
        self.assertIn("NEUROSTRAZH 2.0</h1>", self.html)

    def test_font_is_local_not_cdn(self):
        """Через интернет тянуть нельзя — не загрузится и съедет на системный."""
        self.assertIn("@font-face", self.html)
        self.assertIn("/static/fonts/", self.html)
        self.assertNotIn("fonts.googleapis.com", self.html)
        self.assertNotIn("fonts.gstatic.com", self.html)

    def test_font_files_present(self):
        files = list(self.fonts.glob("*.woff2"))
        self.assertTrue(files, "нет файлов шрифта в static/fonts")
        for path in files:
            self.assertGreater(path.stat().st_size, 1000, path.name)

    def test_no_native_selects_left(self):
        self.assertNotIn("<select", self.html)

    def test_no_green_left(self):
        for colour in ("#9cffc4", "#7dffb0"):
            self.assertNotIn(colour, self.html)

    def test_number_spin_buttons_hidden(self):
        self.assertIn("-webkit-inner-spin-button", self.html)
        self.assertIn("appearance:textfield", self.html)

    def test_buttons_glow_on_hover(self):
        block = self.html.split("button:hover:not(:disabled){")[1].split("}")[0]
        self.assertIn("text-shadow", block)
        self.assertIn("color:#ffffff", block)

    def test_cards_have_neon_border(self):
        """Рамка стала чуть плотнее в NEUROSTRAZH — свечение проверяет
        tests/test_integrity.py."""
        block = self.html.split("  .card{")[1].split("}")[0]
        self.assertIn("rgba(140,84,255,", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
