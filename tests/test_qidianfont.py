"""Цифры Цидяня: расшифровка шрифта-антибота.

Настоящего файла шрифта у нас нет — сайт за пределами разрешённого
списка. Поэтому проверка идёт на подделке: берём обычный системный
шрифт, оставляем в нём десять цифр, переносим их под коды из
неназначенной области Unicode и стираем имена глифов. Это ровно то, что
делает сайт, и на такой подделке видно и то, что разбор работает, и то,
что он делает, когда не работает.

Гарнитуры нарочно берутся разные, в том числе не входящие в набор
образцов. Совпасть с самим собой умеет и сломанный разбор; ценность
проверки — в том, что глиф антиквы находит свою цифру, сверяясь с
гротеском.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources import qidianfont as qf  # noqa: E402

#: Куда уводить цифры. Первый код — тот самый, что стоит на живой
#: странице рейтинга: 𘠢 (0x18822).
BASE = 0x18820

#: Гарнитуры для проверки. Часть из них — образцы, с которыми идёт
#: сверка, часть нет: «шрифт нашёл себя же» проверкой не считается.
FACES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
)


def faces() -> list[str]:
    return [path for path in FACES if Path(path).exists()]


def anti_spider(source: str, shift: int = 3, blank_names: bool = True):
    """Подделка под шрифт Цидяня. Возвращает файл и верную таблицу.

    `shift` сдвигает соответствие «код → цифра», чтобы разбор нельзя было
    пройти, просто вернув цифры по порядку кодов.
    """
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

    font = TTFont(source)
    cut = subset.Subsetter(options=subset.Options(
        glyph_names=True, layout_features=[], name_IDs=[], hinting=False))
    cut.populate(text="0123456789")
    cut.subset(font)

    by_digit = {digit: font.getBestCmap()[ord(digit)] for digit in "0123456789"}
    truth, pairs = {}, {}
    for index, digit in enumerate("0123456789"):
        code = BASE + (index * shift) % 10
        truth[chr(code)] = digit
        pairs[code] = by_digit[digit]

    if blank_names:
        for tag in ("GDEF", "GSUB", "GPOS", "kern"):
            if tag in font:
                del font[tag]
        order = font.getGlyphOrder()
        rename = {name: f"g{index:02d}" for index, name in enumerate(order)
                  if name in by_digit.values()}
        font.setGlyphOrder([rename.get(name, name) for name in order])
        font["glyf"].glyphs = {rename.get(k, k): v
                               for k, v in font["glyf"].glyphs.items()}
        font["glyf"].glyphOrder = font.getGlyphOrder()
        font["hmtx"].metrics = {rename.get(k, k): v
                                for k, v in font["hmtx"].metrics.items()}
        if "post" in font:
            font["post"].glyphOrder = None
        pairs = {code: rename.get(name, name) for code, name in pairs.items()}

    wide = CmapSubtable.newSubtable(12)
    wide.platformID, wide.platEncID, wide.format = 3, 10, 12
    wide.reserved, wide.length, wide.language, wide.nGroups = 0, 0, 0, 0
    wide.cmap = pairs
    font["cmap"].tables = [wide]

    out = io.BytesIO()
    font.save(out)
    return out.getvalue(), truth


def same_glyph_twice(source: str) -> bytes:
    """Подделка с изъяном: две подмены нарисованы одним глифом, и имена
    глифов стёрты, так что разбору остаётся только сверка начертаний.

    Именно в такой шрифт сверка и упирается: две картинки одинаковы,
    значит и цифру она обеим найдёт одну. Что делать дальше — вопрос не
    праздный. Если бы имена глифов были целы, две подмены на одну цифру
    были бы законным замыслом сайта: так шифр только крепче. Но когда
    цифру мы **угадываем**, совпадение означает промах сверки, и таблице
    после него верить нельзя.
    """
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

    font = TTFont(source)
    cut = subset.Subsetter(options=subset.Options(
        glyph_names=True, layout_features=[], name_IDs=[], hinting=False))
    cut.populate(text="0123456789")
    cut.subset(font)

    seven = font.getBestCmap()[ord("7")]
    for tag in ("GDEF", "GSUB", "GPOS", "kern"):
        if tag in font:
            del font[tag]
    order = font.getGlyphOrder()
    rename = {name: f"g{index:02d}" for index, name in enumerate(order)
              if name != ".notdef"}
    font.setGlyphOrder([rename.get(name, name) for name in order])
    font["glyf"].glyphs = {rename.get(k, k): v
                           for k, v in font["glyf"].glyphs.items()}
    font["glyf"].glyphOrder = font.getGlyphOrder()
    font["hmtx"].metrics = {rename.get(k, k): v
                            for k, v in font["hmtx"].metrics.items()}
    if "post" in font:
        font["post"].glyphOrder = None
    seven = rename.get(seven, seven)

    wide = CmapSubtable.newSubtable(12)
    wide.platformID, wide.platEncID, wide.format = 3, 10, 12
    wide.reserved, wide.length, wide.language, wide.nGroups = 0, 0, 0, 0
    wide.cmap = {BASE: seven, BASE + 1: seven}
    font["cmap"].tables = [wide]

    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


class TestWhereTheFontIs(unittest.TestCase):
    """Адрес шрифта берётся из стилей рядом с числом."""

    STYLE = ("@font-face { font-family: qXUqdlfe; "
             "src: url('https://x/qXUqdlfe.eot?') format('eot'); "
             "src: url('https://x/qXUqdlfe.woff') format('woff'), "
             "url('https://x/qXUqdlfe.ttf') format('truetype'); }")

    def test_the_family_name_is_found(self):
        self.assertEqual(qf.font_of(self.STYLE)[0], "qXUqdlfe")

    def test_the_simplest_format_wins(self):
        """`.eot` сайт ставит первым, но это формат для старого IE, а
        `.woff2` сжат brotli. Разбирать проще всего `.ttf`."""
        self.assertTrue(qf.font_of(self.STYLE)[1].endswith(".ttf"))

    def test_nothing_in_the_styles_means_nothing_to_fetch(self):
        self.assertEqual(qf.font_of("body { color: red }"), ("", ""))


class TestTheTable(unittest.TestCase):
    """Таблица «подмена → цифра» из самого файла шрифта."""

    def setUp(self):
        qf.forget()
        if not faces():
            self.skipTest("в системе нет шрифта, из которого сделать подделку")

    def test_glyph_names_are_enough_when_they_are_left_alone(self):
        data, truth = anti_spider(faces()[0], blank_names=False)
        table = qf.table_for("q", data, "https://x/q.ttf")
        self.assertEqual(table, truth)
        self.assertEqual(qf.report_for("q").method, qf.BY_NAMES)

    def test_blanked_names_are_read_by_shape(self):
        """Имена сайт может обезличить — тогда остаётся начертание."""
        for face in faces():
            with self.subTest(face=Path(face).name):
                qf.forget()
                data, truth = anti_spider(face)
                table = qf.table_for("q", data, "https://x/q.ttf")
                self.assertEqual(table, truth)
                self.assertEqual(qf.report_for("q").method, qf.BY_SHAPE)

    def test_the_same_file_is_parsed_once(self):
        data, _ = anti_spider(faces()[0])
        first = qf.table_for("q", data, "https://x/q.ttf")
        self.assertIs(qf.table_for("q", data, "https://x/q.ttf"), first)

    def test_a_new_file_under_the_old_name_is_parsed_again(self):
        """Имя семейства сайт может повторить, подменив файл. Кэш по
        имени отдал бы старую таблицу — и числа стали бы другими."""
        one, first = anti_spider(faces()[0], shift=3)
        two, second = anti_spider(faces()[0], shift=7)
        self.assertNotEqual(first, second)
        self.assertEqual(qf.table_for("q", one, "https://x/q.ttf"), first)
        self.assertEqual(qf.table_for("q", two, "https://x/q.ttf"), second)

    def test_rubbish_instead_of_a_font_is_a_named_refusal(self):
        with self.assertRaises(qf.FontUnavailable):
            qf.table_for("q", b"not a font at all", "https://x/q.ttf")
        self.assertTrue(qf.report_for("q").error)


class TestItRefusesRatherThanGuesses(unittest.TestCase):
    """Неверное число в рейтинге выглядит достоверно — и потому опаснее
    пустоты. Разбор обязан отказываться, а не додумывать."""

    def setUp(self):
        qf.forget()

    def test_two_substitutions_on_one_digit_void_the_table(self):
        """Шрифт прячет десять разных цифр, и каждая в нём одна. Если
        сверка свела две подмены к одной цифре, она где-то ошиблась — и
        мы не знаем где. Проверяем шрифтом, где две подмены нарисованы
        одним и тем же глифом: сверка честно найдёт для обеих одну цифру,
        и таблице после этого верить нельзя."""
        if not faces():
            self.skipTest("в системе нет шрифта, из которого сделать подделку")
        data = same_glyph_twice(faces()[0])
        table = qf.table_for("q", data, "https://x/q.ttf")
        self.assertEqual(table, {})
        self.assertTrue(qf.report_for("q").error)

    def test_an_unknown_sign_stays_as_it_was(self):
        """Дыра в числе видна сразу. Тихо подставленная цифра — нет."""
        self.assertEqual(qf.decode("1?3", {"1": "1", "3": "3"}), "1?3")

    def test_a_number_that_did_not_decode_is_not_a_zero(self):
        self.assertIsNone(qf.number_of("\U00018822\U00018823", {}))

    def test_a_decoded_number_comes_back_as_a_number(self):
        table = {"\U00018822": "2", "\U00018823": "5"}
        self.assertEqual(qf.number_of("\U00018822\U00018823", table), 25)


class TestTheWholeWay(unittest.TestCase):
    """Что видит рейтинг: строка со страницы и число из неё."""

    def setUp(self):
        qf.forget()
        if not faces():
            self.skipTest("в системе нет шрифта, из которого сделать подделку")

    def test_a_page_number_reads_back_as_it_was_written(self):
        for face in faces():
            with self.subTest(face=Path(face).name):
                qf.forget()
                data, truth = anti_spider(face)
                table = qf.table_for("q", data, "https://x/q.ttf")
                back = {digit: sign for sign, digit in truth.items()}
                shown = "".join(back[digit] for digit in "20717")
                self.assertEqual(qf.number_of(shown, table), 20717)


if __name__ == "__main__":
    unittest.main()
