"""Тесты раздела 8 ТЗ v4 — правки по итогам второго теста."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import cleanup, proxies, textcheck  # noqa: E402

LONG = "Обычный абзац русского текста, достаточно длинный для проверки. " * 6


class BracketTestCase(unittest.TestCase):
    """8.4: баланс скобок считается по файлу, а не по абзацу."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)

    def check(self, text: str, **kwargs):
        path = self.tmp / "a.txt"
        path.write_text(text, encoding="utf-8")
        return textcheck.check(path, ["pairs"], **kwargs).findings

    def test_multiline_game_block_is_not_a_finding(self):
        """`{Распределение:` закрывается через два абзаца — это норма."""
        found = self.check("{Распределение:\nсила 10\nловкость 8\n}\nТекст.")
        self.assertEqual(found, [])

    def test_square_game_block_is_not_a_finding(self):
        found = self.check("[Требования:\nуровень 5\n]\nДальше текст.")
        self.assertEqual(found, [])

    def test_genuinely_unclosed_bracket_is_reported(self):
        found = self.check("Открыл «кавычку и не закрыл.\nДальше текст.")
        self.assertEqual(len(found), 1)
        self.assertIn("незакрытой", found[0].fragment)

    def test_finding_points_at_the_opening_line(self):
        found = self.check("Первая строка.\nВторая с «открытой.\nТретья.")
        self.assertEqual(found[0].line, 2)

    def test_closing_without_opening_is_reported(self):
        found = self.check("Текст.\nЗакрыл) без открытия.")
        self.assertEqual(len(found), 1)
        self.assertIn("без открывающей", found[0].fragment)

    def test_block_longer_than_the_limit_is_suspicious(self):
        text = "[Начало:\n" + "\n".join(f"строка {i}" for i in range(12)) + "\n]"
        found = self.check(text)
        self.assertEqual(len(found), 1)
        self.assertIn("растянут", found[0].fragment)

    def test_limit_is_configurable(self):
        text = "[Начало:\n" + "\n".join(f"строка {i}" for i in range(12)) + "\n]"
        self.assertEqual(self.check(text, max_span=50), [])

    def test_apostrophes_inside_words_are_ignored(self):
        """Одиночные апострофы часто встречаются внутри слов."""
        self.assertEqual(self.check("Слово don't и l'homme тут."), [])

    def test_odd_straight_quotes_counted_per_file(self):
        found = self.check('Он сказал "привет и ушёл.')
        self.assertEqual(len(found), 1)
        self.assertIn("кавычек", found[0].fragment)

    def test_balanced_straight_quotes_are_clean(self):
        self.assertEqual(self.check('Он сказал "привет" и ушёл.'), [])

    def test_a_whole_book_of_game_blocks_has_no_bracket_noise(self):
        """Проверка на целой книге, а не на одном абзаце.

        Раньше здесь лежала настоящая скачанная книга: на ней игровые
        блоки давали 44 ложных находки. Книгу убрали — чужой текст в
        публичном репозитории, — а вместе с ней ушла и проверка: тест
        молча пропускался, и было незаметно, что он ничего не сторожит.

        Теперь книга собирается прямо здесь. Важно не то, что она
        настоящая, а то, чем она отличается от абзацев выше: полторы
        сотни глав, чтение через разбор epub, а не голый текст, и
        блоки, которые открываются в одной главе и закрываются в ней же
        через несколько абзацев. Ровно на этом счёт по абзацам и
        рассыпался.
        """
        import zipfile

        block = ("<p>[Статус:</p><p>уровень 12</p><p>сила 40</p>"
                 "<p>ловкость 31</p><p>]</p>")
        talk = ("<p>«Опять эта дрянь», — сказал он и сплюнул.</p>"
                "<p>{Награда:</p><p>эссенция ×3</p><p>}</p>")
        pages, items, refs = {}, [], []
        for number in range(1, 151):
            pages[f"OEBPS/ch{number}.xhtml"] = (
                f"<html><body><h1>Глава {number}</h1>"
                f"<p>Обычный абзац. {LONG}</p>{block}{talk}"
                f"<p>Ещё абзац (со скобкой внутри) и хвост. {LONG}</p>"
                "</body></html>")
            items.append(f'<item id="c{number}" href="ch{number}.xhtml" '
                         f'media-type="application/xhtml+xml"/>')
            refs.append(f'<itemref idref="c{number}"/>')

        book = self.tmp / "книга.epub"
        with zipfile.ZipFile(book, "w") as archive:
            archive.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:'
                'opendocument:xmlns:container"><rootfiles>'
                '<rootfile full-path="OEBPS/book.opf"/></rootfiles></container>')
            for name, content in pages.items():
                archive.writestr(name, content)
            archive.writestr(
                "OEBPS/book.opf",
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf">'
                f'<manifest>{"".join(items)}</manifest>'
                f'<spine>{"".join(refs)}</spine></package>')

        self.assertEqual(textcheck.check(book, ["pairs"]).findings, [])


class TestFindingDetails(unittest.TestCase):
    """8.6: находке нужны полный абзац и путь к файлу."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)

    def test_finding_carries_full_paragraph_and_path(self):
        path = self.tmp / "a.txt"
        long_line = "Начало абзаца. " * 12 + "тут 修炼 иероглиф. " + "Хвост абзаца. " * 12
        path.write_text(f"{long_line}\n{LONG}", encoding="utf-8")

        finding = textcheck.check(path, ["cjk"]).findings[0].as_dict()
        self.assertLess(len(finding["fragment"]), len(finding["context"]))
        self.assertIn("修炼", finding["context"])
        self.assertEqual(finding["path"], str(path))

    def test_context_present_for_file_wide_checks(self):
        path = self.tmp / "a.txt"
        path.write_text("Текст.\nСтрока с «открытой скобкой.\n" + LONG, encoding="utf-8")
        finding = textcheck.check(path, ["pairs"]).findings[0].as_dict()
        self.assertTrue(finding["context"])
        self.assertTrue(finding["path"])


class TestFullwidthCleanup(unittest.TestCase):
    """8.5: полноширинные знаки заменяются на обычные."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)
        self.src = self.tmp / "in"
        self.src.mkdir()

    def clean(self, text: str, kinds=("fullwidth",)) -> str:
        (self.src / "a.txt").write_text(text, encoding="utf-8")
        out = self.tmp / "out"
        cleanup.clean(self.src, list(kinds), out)
        return (out / "a.txt").read_text(encoding="utf-8")

    def test_each_pair_from_spec(self):
        cases = {
            "【Применено】": "[Применено]",
            "（скобки）": "(скобки)",
            "《книга》": "«книга»",
            "текст，ещё。": "текст,ещё.",
            "а：б；в": "а:б;в",
            "да！нет？": "да!нет?",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertIn(expected, self.clean(source))

    def test_fullwidth_space_becomes_ordinary(self):
        result = self.clean("слово　слово")
        self.assertNotIn("　", result)
        self.assertIn("слово слово", result)

    def test_counts_every_replacement(self):
        (self.src / "a.txt").write_text("【а】（б）", encoding="utf-8")
        report = cleanup.clean(self.src, ["fullwidth"], self.tmp / "out")
        self.assertEqual(report.counts["fullwidth"], 4)

    def test_cjk_itself_is_still_untouched(self):
        """Знаки — да, иероглифы — нет."""
        result = self.clean("Текст 修炼 и【скобки】", kinds=cleanup.ALL_KINDS)
        self.assertIn("修炼", result)
        self.assertIn("[скобки]", result)

    def test_listed_in_available_kinds(self):
        self.assertIn("fullwidth", cleanup.ALL_KINDS)


class TestProxyTimeout(unittest.TestCase):
    """8.3: таймаут проверки прокси больше не захардкожен."""

    def test_default_is_sixty(self):
        self.assertEqual(proxies.CHECK_TIMEOUT, 60)

    def test_ceiling_is_three_hundred(self):
        self.assertEqual(proxies.MAX_TIMEOUT, 300)

    def test_check_proxy_accepts_timeout(self):
        import inspect

        self.assertIn("timeout", inspect.signature(proxies.check_proxy).parameters)

    def test_check_all_accepts_timeout(self):
        import inspect

        self.assertIn("timeout", inspect.signature(proxies.ProxyPool.check_all).parameters)


class TestSecondPassWebApi(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()

    def test_proxy_check_rejects_timeout_above_limit(self):
        res = self.app.post("/api/proxies/check", json={"timeout": 301})
        self.assertEqual(res.status_code, 400)

    def test_proxy_check_rejects_non_numeric_timeout(self):
        res = self.app.post("/api/proxies/check", json={"timeout": "быстро"})
        self.assertEqual(res.status_code, 400)

    def test_open_requires_path(self):
        self.assertEqual(self.app.post("/api/open", json={}).status_code, 400)

    def test_open_reports_missing_file(self):
        res = self.app.post("/api/open", json={"path": str(self.tmp / "нет.txt")})
        self.assertEqual(res.status_code, 404)

    def test_clean_preview_includes_fullwidth(self):
        folder = self.tmp / "гряз"
        folder.mkdir()
        (folder / "a.txt").write_text("【тест】", encoding="utf-8")
        res = self.app.post("/api/clean/preview",
                            json={"targets": [str(folder)], "kinds": ["fullwidth"]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["total"], 2)

    def test_findings_carry_context_and_path_through_the_api(self):
        from webapp.app import JOBS

        folder = self.tmp / "книга"
        folder.mkdir()
        (folder / "a.txt").write_text(f"Строка с 修炼 знаком.\n{LONG}", encoding="utf-8")

        res = self.app.post("/api/check/start",
                            json={"targets": [str(folder)], "kinds": ["cjk"]})
        job_id = res.get_json()["job"]["id"]
        JOBS[job_id].thread.join(timeout=60)

        finding = self.app.get(f"/api/job/{job_id}").get_json()["job"]["report"]["findings"][0]
        self.assertTrue(finding["context"])
        self.assertTrue(finding["path"])


class TestBranding(unittest.TestCase):
    """8.1 и 8.2: название и цвет полос прокрутки."""

    def setUp(self):
        self.html = (
            Path(__file__).resolve().parent.parent / "webapp" / "static" / "index.html"
        ).read_text(encoding="utf-8")

    def test_program_name(self):
        """Название теперь латиницей — подробности в tests/test_checks.py."""
        self.assertIn("NEUROSTRAZH 2.0", self.html)
        self.assertNotIn("MVLEMPYR</h1>", self.html)

    def test_scrollbar_is_flat_interface_colour(self):
        self.assertIn("scrollbar-color:#8c54ff #15151d", self.html)
        self.assertIn("background:#8c54ff", self.html)
        # Никаких градиентов на ползунке.
        thumb = self.html.split("*::-webkit-scrollbar-thumb{")[1].split("}")[0]
        self.assertNotIn("gradient", thumb)


if __name__ == "__main__":
    unittest.main(verbosity=2)
