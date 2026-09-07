"""Запуск одним файлом: что делает `Запустить.bat`, кроме зова Python.

Он молчал во всех трёх случаях, когда запуск не удаётся: программа уже
работает и держит порт, папке программы нельзя писать, зависимостей нет
и сети тоже. Со стороны это одно и то же — «двойным щелчком не
запускается, а от имени администратора запускается».
"""

from __future__ import annotations

import socket
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import start  # noqa: E402


class Said(unittest.TestCase):
    """Перехватывает то, что запуск говорит человеку."""

    def setUp(self):
        self.lines: list[str] = []
        was = start.say
        start.say = lambda text="": self.lines.append(str(text))
        self.addCleanup(setattr, start, "say", was)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class TestTheProgramIsAlreadyRunning(Said):
    """Окно браузера закрыли, программа осталась работать, и человек
    запускает её снова. Порт занят — вторая попытка падает с чужой на
    вид ошибкой про адрес."""

    def setUp(self):
        super().setUp()
        self.opened: list[str] = []
        import webbrowser

        was = webbrowser.open
        webbrowser.open = self.opened.append
        self.addCleanup(setattr, webbrowser, "open", was)

    def serving(self):
        """Поднимает что-нибудь на том же порту, что и программа."""
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((start.HOST, 0))
        server.listen(1)
        self.addCleanup(server.close)
        was = start.PORT
        start.PORT = server.getsockname()[1]
        self.addCleanup(setattr, start, "PORT", was)

    def test_a_free_port_means_nothing_is_running(self):
        was = start.PORT
        # Порт, на котором заведомо никто не сидит: занимаем и отпускаем.
        spare = socket.socket()
        spare.bind((start.HOST, 0))
        start.PORT = spare.getsockname()[1]
        spare.close()
        self.addCleanup(setattr, start, "PORT", was)

        self.assertFalse(start.already())

    def test_a_busy_port_is_recognised(self):
        self.serving()
        self.assertTrue(start.already())

    def test_it_says_so_instead_of_falling_over(self):
        self.serving()
        start.already()
        self.assertIn("уже работает", self.text)

    def test_the_browser_is_opened_at_the_running_one(self):
        """Человек нажал «Запустить», потому что хотел увидеть окно."""
        self.serving()
        start.already()
        self.assertEqual(len(self.opened), 1)
        self.assertIn(str(start.PORT), self.opened[0])

    def test_a_browser_that_did_not_open_is_not_a_crash(self):
        import webbrowser

        self.serving()
        webbrowser.open = lambda url: (_ for _ in ()).throw(RuntimeError("нет"))
        self.assertTrue(start.already())
        self.assertIn("руками", self.text)


class TestTheFolderMustBeWritable(Said):
    """Программа держит рядом с собой настройки, прокси, журнал,
    библиотеку и очередь. Папка только для чтения — и всё это молча не
    работает, а «от имени администратора» это обходит."""

    def test_a_normal_folder_passes(self):
        self.assertTrue(start.writable())

    def test_a_folder_that_is_not_there_is_named(self):
        was = start.ROOT
        start.ROOT = Path("/нет/такой/папки")
        self.addCleanup(setattr, start, "ROOT", was)

        self.assertFalse(start.writable())
        self.assertIn("нужна запись", self.text)

    def test_it_says_where_to_put_the_program(self):
        """Отказ без ответа «и что теперь» — половина ответа."""
        was = start.ROOT
        start.ROOT = Path("/нет/такой/папки")
        self.addCleanup(setattr, start, "ROOT", was)
        start.writable()

        self.assertIn("Документы", self.text)

    def test_it_warns_against_running_as_administrator(self):
        """Так «работает», но программа начнёт писать файлы, до которых
        человек потом не дотянется."""
        was = start.ROOT
        start.ROOT = Path("/нет/такой/папки")
        self.addCleanup(setattr, start, "ROOT", was)
        start.writable()

        self.assertIn("администратора", self.text)

    def test_nothing_is_left_behind_after_the_check(self):
        """Проба записи не должна оседать в папке программы файлом."""
        start.writable()
        self.assertFalse((start.ROOT / ".проба-записи").exists())


class TestDependencies(Said):
    """`pip` звался при каждом запуске. На готовой машине это лишние
    секунды, а без сети — минуты: он перебирает зеркала, окно молчит, и
    человек видит «программа не запускается»."""

    def setUp(self):
        super().setUp()
        self.ran: list[list[str]] = []
        was = subprocess.run
        subprocess.run = self.remember
        self.addCleanup(setattr, subprocess, "run", was)
        self.trouble = None

    def remember(self, command, **more):
        self.ran.append(command)
        if self.trouble:
            raise self.trouble
        return subprocess.CompletedProcess(command, 0)

    def test_nothing_is_installed_when_everything_is_here(self):
        self.assertTrue(all(start._here(one) for one in start.MUST),
                        "проверка бессмысленна: пакетов и правда нет")
        start.deps()
        self.assertEqual(self.ran, [])

    def test_a_missing_package_starts_the_install(self):
        was = start.MUST
        start.MUST = ("такого-пакета-нет",)
        self.addCleanup(setattr, start, "MUST", was)

        start.deps()
        self.assertEqual(len(self.ran), 1)
        self.assertIn("pip", self.ran[0])

    def test_a_package_that_is_not_there_is_not_a_crash(self):
        self.assertFalse(start._here("такого-пакета-нет"))

    def test_an_install_without_the_net_does_not_hang_forever(self):
        was = start.MUST
        start.MUST = ("такого-пакета-нет",)
        self.addCleanup(setattr, start, "MUST", was)
        self.trouble = subprocess.TimeoutExpired("pip", start.DEPS_WAIT)

        start.deps()
        self.assertIn("нет сети", self.text)

    def test_the_install_is_given_a_deadline(self):
        was = start.MUST
        start.MUST = ("такого-пакета-нет",)
        self.addCleanup(setattr, start, "MUST", was)
        seen = {}

        def remember(command, **more):
            seen.update(more)
            return subprocess.CompletedProcess(command, 0)

        subprocess.run = remember
        start.deps()
        self.assertTrue(seen.get("timeout"))

    def test_a_failed_install_names_the_likely_reason(self):
        """Права на папку Python — та самая разница, из-за которой «от
        имени администратора работает, а так нет»."""
        was = start.MUST
        start.MUST = ("такого-пакета-нет",)
        self.addCleanup(setattr, start, "MUST", was)
        subprocess.run = lambda command, **more: \
            subprocess.CompletedProcess(command, 1)

        start.deps()
        self.assertIn("--user", self.text)


class TestTheOrderOfTheChecks(Said):
    """Сперва «уже работает», потом «можно ли писать», и только потом
    долгие дела: иначе человек ждёт установку, чтобы узнать, что
    программа и так открыта."""

    def setUp(self):
        super().setUp()
        self.steps: list[str] = []
        for name in ("deps", "proxies", "network", "serve"):
            was = getattr(start, name)
            setattr(start, name, self.step(name))
            self.addCleanup(setattr, start, name, was)

    def step(self, name):
        def done(*args, **more):
            self.steps.append(name)
            return 0
        return done

    def test_a_running_program_stops_everything_else(self):
        was = start.already
        start.already = lambda: True
        self.addCleanup(setattr, start, "already", was)

        self.assertEqual(start.main(), 0)
        self.assertEqual(self.steps, [])

    def test_a_folder_without_write_stops_everything_else(self):
        was_one, was_two = start.already, start.writable
        start.already, start.writable = (lambda: False), (lambda: False)
        self.addCleanup(setattr, start, "already", was_one)
        self.addCleanup(setattr, start, "writable", was_two)

        self.assertEqual(start.main(), 1)
        self.assertEqual(self.steps, [])

    def test_otherwise_everything_runs_in_order(self):
        was_one, was_two = start.already, start.writable
        start.already, start.writable = (lambda: False), (lambda: True)
        self.addCleanup(setattr, start, "already", was_one)
        self.addCleanup(setattr, start, "writable", was_two)

        start.main()
        self.assertEqual(self.steps,
                         ["deps", "proxies", "network", "serve"])


class TestTheLauncherItself(unittest.TestCase):
    """`cmd.exe` читает `.bat` побайтово в текущей кодовой странице."""

    bat = (Path(__file__).resolve().parent.parent
           / "Запустить.bat").read_bytes()

    def test_not_a_single_non_ascii_byte(self):
        """Иначе разбор уезжает на середину строки, `rem` теряется, и
        остаток комментария уходит в исполнение."""
        self.bat.decode("ascii")

    def test_the_window_stays_open_on_a_failure(self):
        """Иначе ошибка мелькает и пропадает — ровно то, что человек
        описывает как «ничего не происходит»."""
        self.assertIn(b"pause", self.bat)


if __name__ == "__main__":
    unittest.main()
