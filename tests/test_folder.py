"""Имя папки книги и карточка выбранного в рейтинге (3.2 ТЗ NEUROSTRAZH).

Иероглиф в имени папки — не косметика. Часть файловых систем (FAT32 на
флешке, сетевой диск, старый архиватор) хранит имена в своей кодировке, и
путь разъезжается на части, а собрать его обратно нечем. Поэтому имя
папки считает сервер — у него есть перевод названия, — а браузер только
подставляет готовое.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import naming  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"

#: Название настоящей книги с Фанкью и её код в девятнадцать разрядов.
CHINESE = "斗破苍穹"
CODE = "7143038691944959011"


class TestHasCjk(unittest.TestCase):
    """Что считается иероглифом."""

    def test_chinese(self):
        self.assertTrue(naming.has_cjk(CHINESE))

    def test_japanese_kana(self):
        self.assertTrue(naming.has_cjk("ハンター"))

    def test_korean(self):
        self.assertTrue(naming.has_cjk("한국어"))

    def test_rare_signs_beyond_the_basic_plane(self):
        """Редкие иероглифы лежат за пределами первых 65 тысяч знаков."""
        self.assertTrue(naming.has_cjk("\U00020000"))

    def test_russian_is_not(self):
        self.assertFalse(naming.has_cjk("Расколотая битвой синева"))

    def test_latin_is_not(self):
        self.assertFalse(naming.has_cjk("Battle Through the Heavens"))

    def test_nothing_is_not(self):
        self.assertFalse(naming.has_cjk(""))
        self.assertFalse(naming.has_cjk(None))


class TestFolderName(unittest.TestCase):
    """Порядок: перевод, латиница, код — но никогда иероглифы."""

    def test_translation_wins(self):
        name = naming.folder_name(CHINESE, code=CODE,
                                  translated="Расколотая битвой синева")
        self.assertEqual(name, "Расколотая битвой синева")

    def test_translation_is_cleaned_of_forbidden_characters(self):
        """Двоеточие Windows не примет, и оно заменяется, а не выбрасывается."""
        name = naming.folder_name(CHINESE, code=CODE,
                                  translated="Том 1: Начало")
        self.assertEqual(name, "Том 1 - Начало")
        for char in ':/\\|*?"<>':
            self.assertNotIn(char, name)

    def test_own_name_is_used_when_it_is_not_hieroglyphs(self):
        name = naming.folder_name("Battle Through the Heavens", code=CODE)
        self.assertEqual(name, "Battle Through the Heavens")

    def test_hieroglyphs_never_reach_the_folder_name(self):
        name = naming.folder_name(CHINESE, code=CODE)
        self.assertFalse(naming.has_cjk(name))
        self.assertEqual(name, f"book-{CODE}")

    def test_hieroglyphs_do_not_survive_inside_the_translation_either(self):
        """Модель иногда возвращает название неперевёденным."""
        name = naming.folder_name(CHINESE, code=CODE, translated=CHINESE)
        self.assertEqual(name, f"book-{CODE}")

    def test_latin_part_of_a_mixed_name_is_kept(self):
        """«SSS级战神» без «SSS» превратилось бы в безликое book-…"""
        self.assertEqual(naming.folder_name("SSS级战神", code=CODE), "SSS")

    def test_a_scrap_of_latin_is_not_enough(self):
        """Из «第1章» остался бы один знак — такое имя ничего не говорит."""
        self.assertEqual(naming.folder_name("第1章", code=CODE), f"book-{CODE}")

    def test_code_is_taken_as_a_string(self):
        """Код книги в девятнадцать разрядов числом не ездит (1.2 ТЗ)."""
        self.assertEqual(naming.folder_name(CHINESE, code=int(CODE)),
                         f"book-{CODE}")

    def test_nothing_at_all(self):
        self.assertEqual(naming.folder_name("", code=""), "")

    def test_name_fits_the_file_system_limit(self):
        long = "Очень длинное название " * 20
        self.assertLessEqual(len(naming.folder_name(long, code=CODE)),
                             naming.MAX_NAME)


class TestServerBuildsTheName(unittest.TestCase):
    """Считает имя сервер: перевод лежит у него, правило должно быть одно."""

    def setUp(self):
        from ops import titles

        self.titles = titles
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        saved = titles.TITLES_FILE
        titles.TITLES_FILE = Path(self._dir.name) / "titles.json"
        self.addCleanup(setattr, titles, "TITLES_FILE", saved)

    def book(self):
        from mvl import api

        return api.Novel(code=int(CODE), name=CHINESE, slug=CODE,
                         total_chapters=1204, author="作者")

    def found(self):
        from webapp.app import _found

        return _found(self.book())

    def test_the_answer_carries_a_ready_folder_name(self):
        self.assertEqual(self.found()["folder"], f"book-{CODE}")

    def test_the_translation_reaches_the_folder_name(self):
        self.titles.remember({CODE: "Расколотая битвой синева"})
        data = self.found()

        self.assertEqual(data["translated"], "Расколотая битвой синева")
        self.assertEqual(data["folder"], "Расколотая битвой синева")

    def test_no_translation_is_an_empty_string_not_a_missing_key(self):
        """Иначе в браузере вместо названия встало бы «undefined»."""
        self.assertEqual(self.found()["translated"], "")

    def test_the_code_still_leaves_as_a_string(self):
        """Девятнадцать разрядов JavaScript точно не хранит (1.2 ТЗ)."""
        self.assertEqual(self.found()["code"], CODE)


class TestBrowserOnlyFillsItIn(unittest.TestCase):
    """В браузере своего правила нет — иначе копии разъедутся."""

    @classmethod
    def setUpClass(cls):
        cls.page = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_folder_comes_from_the_answer(self):
        self.assertIn("$('folder').value = novel.folder || novel.name;",
                      self.page)

    def test_the_old_line_with_the_raw_name_is_gone(self):
        self.assertNotIn("$('folder').value = novel.name;", self.page)

    def test_picking_a_book_clears_the_previous_folder(self):
        """Иначе главы новой книги легли бы в папку прошлой."""
        self.assertIn("$('folder').value = '';", self.tabs)

    def test_the_card_shows_the_original_and_the_translation(self):
        self.assertIn("$('bookName').textContent = rkBothTitles(row);",
                      self.tabs)
        self.assertIn("return `${own} / ${ru_}`;", self.tabs)

    def test_the_card_falls_back_to_what_there_is(self):
        """Перевода может не быть, а название — прийти нерасшифрованным."""
        self.assertIn("return own || ru_ || `книга ${row.book_id}`;", self.tabs)


if __name__ == "__main__":
    unittest.main()
