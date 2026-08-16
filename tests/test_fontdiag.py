"""Диагностика расшифровки названий (2.5 ТЗ NEUROSTRAZH).

Раньше на неудачу писалось «названия расшифровать не удалось» — и было
непонятно, что чинить: не скачался файл шрифта, не разобрался, обезличены
имена глифов или не хватает пакетов для сверки начертаний. Здесь
проверяется, что на каждый из этих случаев есть внятный ответ.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources import fanqiefont as font  # noqa: E402
from net.sources import rank as rank_net  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"


def make_font(names: dict, family: str = "fq") -> bytes:
    """Крошечный шрифт с заданными именами глифов.

    `names` — «кодовая точка → имя глифа». Настоящий файл нужен затем,
    что разбор идёт через fontTools, а не через подделку.
    """
    from fontTools.fontBuilder import FontBuilder

    order = [".notdef"] + list(names.values())
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(dict(names))
    builder.setupGlyf({name: _empty_glyph() for name in order})
    builder.setupHorizontalMetrics({name: (600, 0) for name in order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": family, "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()

    import io

    buffer = io.BytesIO()
    builder.save(buffer)
    return buffer.getvalue()


def _empty_glyph():
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    pen = TTGlyphPen(None)
    pen.moveTo((100, 100))
    pen.lineTo((100, 700))
    pen.lineTo((500, 700))
    pen.lineTo((500, 100))
    pen.closePath()
    return pen.glyph()


class FontBase(unittest.TestCase):
    def setUp(self):
        font.forget()
        self.addCleanup(font.forget)


class TestCacheByFile(FontBase):
    """Кэш по хешу файла, а не по имени семейства (2.5 ТЗ).

    Сайт может оставить имя прежним, подменив сам файл, — кэш по имени
    молча отдавал бы старую таблицу, и названия «расшифровывались» бы в
    мусор.
    """

    def test_a_table_is_read_from_the_font(self):
        data = make_font({0xE000: "uni4E2D", 0xE001: "uni6587"})
        table = font.table_for("fq", data)
        self.assertEqual(table, {"": "中", "": "文"})

    def test_the_same_file_is_not_parsed_twice(self):
        data = make_font({0xE000: "uni4E2D"})
        first = font.table_for("fq", data)
        self.assertIs(font.table_for("fq", data), first)

    def test_a_new_file_under_the_old_name_is_noticed(self):
        old = make_font({0xE000: "uni4E2D"})
        new = make_font({0xE000: "uni6587"})
        font.table_for("fq", old)
        self.assertEqual(font.table_for("fq", new), {"": "文"})

    def test_the_key_is_the_file_not_the_name(self):
        data = make_font({0xE000: "uni4E2D"})
        font.table_for("одно_имя", data)
        # Тот же файл под другим именем уже разобран — второй раз не надо.
        self.assertEqual(font.table_for("другое_имя", data),
                         {"": "中"})

    def test_the_fingerprint_changes_with_the_file(self):
        one = font.digest_of(make_font({0xE000: "uni4E2D"}))
        two = font.digest_of(make_font({0xE000: "uni6587"}))
        self.assertNotEqual(one, two)

    def test_a_known_family_is_found_without_the_file(self):
        data = make_font({0xE000: "uni4E2D"})
        font.table_for("fq", data)
        self.assertTrue(font.known("fq"))
        self.assertEqual(font.table_for("fq"), {"": "中"})

    def test_an_unknown_family_without_a_file_says_so(self):
        with self.assertRaises(font.FontUnavailable):
            font.table_for("незнакомый")

    def test_forgetting_clears_everything(self):
        font.table_for("fq", make_font({0xE000: "uni4E2D"}))
        font.forget()
        self.assertFalse(font.known("fq"))
        self.assertIsNone(font.report_for(family="fq"))


class TestReport(FontBase):
    """По отчёту должно быть видно, на каком шаге всё встало."""

    def test_a_successful_parse_is_counted(self):
        data = make_font({0xE000: "uni4E2D", 0xE001: "uni6587"})
        font.table_for("fq", data, url="http://site/f.woff2")
        found = font.report_for(family="fq")

        self.assertTrue(found.downloaded)
        self.assertEqual(found.size, len(data))
        self.assertEqual(found.private, 2)
        self.assertEqual(found.mapped, 2)
        self.assertEqual(found.unmapped, 0)
        self.assertEqual(found.method, font.BY_NAMES)
        self.assertTrue(found.ok)

    def test_the_fingerprint_is_in_the_report(self):
        data = make_font({0xE000: "uni4E2D"})
        font.table_for("fq", data)
        self.assertEqual(font.report_for(family="fq").digest,
                         font.digest_of(data))

    def test_glyphs_are_counted(self):
        data = make_font({0xE000: "uni4E2D", 0xE001: "uni6587"})
        font.table_for("fq", data)
        self.assertGreaterEqual(font.report_for(family="fq").glyphs, 2)

    def test_partly_named_glyphs_show_the_leftovers(self):
        """Половина сопоставилась, половина нет — так и надо сказать."""
        data = make_font({0xE000: "uni4E2D", 0xE001: "cid00042"})
        font.table_for("fq", data)
        found = font.report_for(family="fq")
        self.assertEqual(found.mapped, 1)
        self.assertEqual(found.unmapped, 1)

    def test_obscured_names_fall_back_to_shapes(self):
        """Имена ничего не говорят — включается сверка начертаний."""
        data = make_font({0xE000: "cid00042", 0xE001: "cid00043"})
        font.table_for("fq", data)
        found = font.report_for(family="fq")
        self.assertEqual(found.method, font.BY_SHAPE)
        self.assertEqual(found.threshold, font.SHAPE_THRESHOLD)

    def test_a_missing_library_is_named(self):
        """Без Pillow или numpy сверка не работает — и это надо сказать."""
        data = make_font({0xE000: "cid00042"})
        font.table_for("fq", data)
        found = font.report_for(family="fq")
        if found.mapped:
            self.skipTest("сверка начертаний доступна — проверять нечего")
        self.assertTrue(found.error)

    def test_the_report_survives_the_trip_to_the_screen(self):
        font.table_for("fq", make_font({0xE000: "uni4E2D"}))
        found = font.report_for(family="fq").as_dict()
        for key in ("family", "downloaded", "size", "digest", "glyphs",
                    "private", "mapped", "unmapped", "method", "threshold",
                    "error", "ok"):
            with self.subTest(key=key):
                self.assertIn(key, found)

    def test_a_broken_file_says_what_happened(self):
        with self.assertRaises(font.FontUnavailable):
            font.table_for("fq", "это не шрифт".encode("utf-8"))
        found = font.report_for(family="fq")
        self.assertFalse(found.ok)
        self.assertIn("не разобрался", found.error)


class TestReferenceSet(unittest.TestCase):
    """Эталон для сверки начертаний."""

    def test_the_signs_have_no_repeats(self):
        signs = font.common_signs()
        self.assertEqual(len(signs), len(set(signs)))

    def test_there_are_enough_of_them(self):
        self.assertGreater(len(font.common_signs()), 100)

    def test_a_missing_reference_font_is_not_a_crash(self):
        self.assertIn(font.reference_font(), (None, font.reference_font()))


class TestDiagnosisReachesTheSlice(FontBase):
    """Отчёт должен доехать до среза, а не остаться в логе."""

    class Client:
        def __init__(self, html: str, data: bytes | None = None):
            self.html = html
            self.data = data

        def get_text(self, url):
            return self.html

        def get(self, url):
            class Response:
                pass

            found = Response()
            found.content = self.data
            found.status_code = 200
            return found

        def close(self):
            pass

    def page(self, css: str, books: str = "") -> str:
        return ("<html><style>" + css + "</style><script>"
                "window.__INITIAL_STATE__ = {\"rank\": {\"book_list\": ["
                + (books or '{"bookId": "7", "bookName": "Книга",'
                            ' "author": "Автор", "wordNumber": 1000}')
                + "]}}</script></html>")

    def test_no_font_in_the_styles_is_said_plainly(self):
        client = self.Client(self.page("body{color:red}"))
        found = rank_net.fetch(client)
        self.assertIn("нет шрифта", found["font"]["error"])

    def test_a_font_without_an_address_is_said_plainly(self):
        client = self.Client(self.page("@font-face{font-family:'fq'}"))
        found = rank_net.fetch(client)
        self.assertIn("адрес файла не найден", found["font"]["error"])

    def test_an_empty_file_is_said_plainly(self):
        css = "@font-face{font-family:'fq';src:url(http://s/f.woff2)}"
        client = self.Client(self.page(css), data=b"")
        found = rank_net.fetch(client)
        self.assertIn("пустым", found["font"]["error"])

    def test_a_working_font_reports_its_numbers(self):
        css = "@font-face{font-family:'fq';src:url(http://s/f.woff2)}"
        client = self.Client(self.page(css),
                             data=make_font({0xE000: "uni4E2D"}))
        found = rank_net.fetch(client)
        self.assertTrue(found["decoded"])
        self.assertEqual(found["font"]["mapped"], 1)
        self.assertEqual(found["font"]["method"], font.BY_NAMES)


class TestFontUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_there_is_a_place_for_the_details(self):
        self.assertIn('id="rkFont"', self.page)
        self.assertIn('id="rkFontRows"', self.page)

    def test_every_number_from_the_spec_is_shown(self):
        block = self.tabs.split("function rkFont(found)", 1)[1]
        for name in ("файл скачан", "глифов в шрифте", "из них служебных",
                     "сопоставлено", "без пары", "способ", "порог сравнения"):
            with self.subTest(name=name):
                self.assertIn(name, block)

    def test_the_fingerprint_is_shown_too(self):
        self.assertIn("отпечаток файла", self.tabs)

    def test_it_says_where_it_stopped(self):
        self.assertIn("где встало", self.tabs)

    def test_a_full_decode_does_not_nag(self):
        """Всё расшифровалось — подробности только мешают."""
        self.assertIn("if(found.ok && !found.unmapped){ box.hidden = true;",
                      self.tabs)

    def test_the_details_open_themselves_on_a_failure(self):
        self.assertIn("box.open = !found.ok;", self.tabs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
