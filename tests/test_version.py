"""Версия программы: одна запись, видна отовсюду.

До этого версия была, но мёртвая: `1.0.0` стояла с первого дня и не
менялась ни разу, хотя за это время прибавилось девять вкладок, четыре
источника и три рейтинга. Показать её человеку было негде, тегов в
репозитории не было вовсе.

Проверяется здесь не само число — его будут поднимать, — а то, что оно
записано в одном месте и доходит до всех, кто его показывает.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent

from mvl import __version__  # noqa: E402


class TestTheNumberItself(unittest.TestCase):
    def test_it_looks_like_a_version(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_it_moved_off_the_one_it_was_born_with(self):
        """`1.0.0` держалась, пока программа выросла впятеро."""
        self.assertNotEqual(__version__, "1.0.0")


class TestItIsWrittenInOnePlace(unittest.TestCase):
    """Две записи однажды разойдутся, и вопрос «какая у меня версия»
    останется без ответа."""

    def test_only_one_file_declares_it(self):
        found = []
        for path in ROOT.rglob("*.py"):
            if "/tests/" in str(path) or path.name == "test_version.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"^__version__\s*=", text, re.M):
                found.append(path.name)
        self.assertEqual(found, ["__init__.py"], found)

    def test_the_number_is_not_repeated_in_code(self):
        """Вписанная руками копия — та самая вторая запись."""
        for path in (ROOT / "webapp" / "app.py",
                     ROOT / "cli.py",
                     ROOT / "webapp" / "static" / "tabs.js",
                     ROOT / "webapp" / "static" / "index.html"):
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn(f'"{__version__}"', text, path.name)
            self.assertNotIn(f"'{__version__}'", text, path.name)


class TestItReachesEveryoneWhoShowsIt(unittest.TestCase):
    def test_the_server_answers_with_it(self):
        from webapp import app as web

        web.app.config["TESTING"] = True
        got = web.app.test_client().get("/api/about").get_json()
        self.assertEqual(got["version"], __version__)
        self.assertEqual(got["name"], "NEUROSTRAZH")

    def test_the_page_asks_the_server_and_does_not_guess(self):
        """Страница кэшируется браузером: вписанная в неё версия
        оставалась бы прошлой ещё сутки после обновления."""
        tabs = (ROOT / "webapp" / "static" / "tabs.js").read_text(
            encoding="utf-8")
        self.assertIn("/api/about", tabs)
        self.assertIn("showVersion()", tabs)

    def test_the_page_has_somewhere_to_put_it(self):
        page = (ROOT / "webapp" / "static" / "index.html").read_text(
            encoding="utf-8")
        self.assertIn('id="appVersion"', page)

    def test_it_is_not_in_the_subtitle(self):
        """Подзаголовок — это про то, что программа делает. Номер сборки
        там ни о чём не говорит и только сбивает первую строку, которую
        человек читает, открыв программу."""
        page = (ROOT / "webapp" / "static" / "index.html").read_text(
            encoding="utf-8")
        subtitle = re.search(r'class="sub"[^>]*>(.*?)</p>', page, re.S)
        self.assertIsNotNone(subtitle)
        self.assertNotIn("appVersion", subtitle.group(1))

    def test_it_sits_at_the_foot_of_the_page(self):
        page = (ROOT / "webapp" / "static" / "index.html").read_text(
            encoding="utf-8")
        spot = page.index('id="appVersion"')
        head = page.index('class="sub"')
        self.assertGreater(spot, head)

    def test_an_empty_label_does_not_hang_in_the_header(self):
        """Сервер не ответил — лучше пусто, чем «версия неизвестна»."""
        page = (ROOT / "webapp" / "static" / "index.html").read_text(
            encoding="utf-8")
        self.assertIn("#appVersion:empty{display:none}", page)

    def test_the_command_line_says_it_too(self):
        done = subprocess.run(
            [sys.executable, str(ROOT / "cli.py"), "--version"],
            capture_output=True, text=True, timeout=120)
        self.assertIn(__version__, done.stdout + done.stderr)


class TestThePapers(unittest.TestCase):
    """История и порядок выпуска — часть работы, а не приложение к ней."""

    def test_the_history_exists_and_names_the_current_version(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(__version__, text)

    def test_the_history_says_what_was_never_checked_live(self):
        """Самый важный раздел: часть источников ни разу не работала с
        живым сайтом, и молчать об этом нельзя."""
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("Чего живьём никто не проверял", text)

    def test_the_release_order_exists(self):
        text = (ROOT / "RELEASE.md").read_text(encoding="utf-8")
        self.assertIn("git tag", text)
        self.assertIn("git archive", text)

    def test_the_release_order_warns_about_secrets(self):
        """Заархивированная папка целиком уносит прокси с паролями и
        ключ от модели — репозиторий публичный."""
        text = (ROOT / "RELEASE.md").read_text(encoding="utf-8")
        self.assertIn("proxies.txt", text)
        self.assertIn("config.json", text)

    def test_the_secrets_are_really_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
        for secret in ("proxies.txt", "config.json", "data/"):
            self.assertIn(secret, ignored, secret)

    def test_finished_books_are_ignored_too(self):
        """Репозиторий публичный, а книги чужие. Две штуки однажды уехали
        сюда «на пробу» и пролежали в открытом доступе всю разработку —
        правило дешевле, чем помнить об этом каждый раз."""
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
        for kind in ("*.epub", "*.fb2", "*.mobi"):
            self.assertIn(kind, ignored, kind)

    def test_no_book_is_lying_in_the_repository(self):
        """Правило в `.gitignore` не убирает то, что уже добавлено
        руками: файл под учётом остаётся под учётом.

        Имена берутся через `-z`, а не построчно. Кириллицу в путях git
        по умолчанию экранирует восьмеричными кодами и оборачивает в
        кавычки — на такой строке проверка «кончается на .epub» не
        срабатывает, и книга с русским именем проходит мимо. Ровно так
        одна из двух и пролежала в репозитории всю разработку.
        """
        import subprocess

        listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        books = [name for name in listed.stdout.split("\0")
                 if name.lower().endswith((".epub", ".fb2", ".mobi"))]
        self.assertEqual(books, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
