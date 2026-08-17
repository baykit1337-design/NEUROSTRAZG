"""Запуск одним файлом (часть 5 ТЗ NEUROSTRAZH).

Открывать командную строку и вводить команды каждый раз — лишний обряд.
Файл в корне проекта делает всё сам: доставляет зависимости, создаёт
`proxies.txt` из образца и поднимает программу.

Проверяется содержимое скриптов, а не их выполнение: `.bat` на этой
машине запускать нечем, а сравнивать поведение двух файлов между собой
всё равно надо.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
BAT = ROOT / "Запустить.bat"
COMMAND = ROOT / "Запустить.command"


class TestBothExist(unittest.TestCase):
    def test_windows(self):
        self.assertTrue(BAT.exists())

    def test_mac(self):
        self.assertTrue(COMMAND.exists())

    def test_the_mac_one_can_be_double_clicked(self):
        """Без бита выполнения Finder его просто не запустит."""
        import os

        self.assertTrue(os.access(COMMAND, os.X_OK))

    def test_the_mac_one_says_which_shell(self):
        self.assertTrue(COMMAND.read_text(encoding="utf-8")
                        .startswith("#!/bin/bash"))


class ScriptsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bat = BAT.read_text(encoding="utf-8")
        cls.command = COMMAND.read_text(encoding="utf-8")
        cls.both = {"Запустить.bat": cls.bat, "Запустить.command": cls.command}


class TestWhatTheyDo(ScriptsBase):
    def test_they_work_from_any_folder(self):
        """Проект кладут куда угодно, и путь запуска бывает чужой."""
        self.assertIn('cd /d "%~dp0"', self.bat)
        self.assertIn('cd "$(dirname "$0")"', self.command)

    def test_the_console_speaks_russian(self):
        """Без этого русские буквы превращаются в кашу."""
        self.assertIn("chcp 65001", self.bat)

    def test_dependencies_are_checked_quietly(self):
        for name, text in self.both.items():
            with self.subTest(script=name):
                self.assertIn("pip install -r requirements.txt", text)
                self.assertIn("--quiet", text)

    def test_the_proxy_list_is_created_from_the_example(self):
        """Без файла программа ругается при запуске на пустом месте."""
        self.assertIn("proxies.example.txt", self.bat)
        self.assertIn("proxies.txt", self.bat)
        self.assertIn("proxies.example.txt", self.command)

    def test_an_existing_proxy_list_is_not_overwritten(self):
        """В нём адреса с паролями — затирать его нельзя."""
        self.assertIn("if not exist proxies.txt", self.bat)
        self.assertIn("[ ! -f proxies.txt ]", self.command)

    def test_they_start_the_program(self):
        for name, text in self.both.items():
            with self.subTest(script=name):
                self.assertIn("webapp/app.py", text)

    def test_the_window_stays_open_on_a_failure(self):
        """Иначе ошибка мелькнёт и окно закроется."""
        self.assertIn("pause", self.bat)
        self.assertIn("read -r -p", self.command)

    def test_a_missing_python_is_explained(self):
        for name, text in self.both.items():
            with self.subTest(script=name):
                self.assertIn("Python не найден", text)

    def test_the_browser_is_not_opened_twice(self):
        """Программа открывает его сама, через секунду после старта —
        когда сервер уже отвечает. Второе открытие дало бы лишнюю
        вкладку с ошибкой соединения."""
        self.assertNotIn("start \"\" http", self.bat)
        self.assertNotIn("open http", self.command)


class TestReadme(unittest.TestCase):
    """5.3: в инструкции для Windows не должно быть команд из макоси."""

    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_the_launchers_are_mentioned_first(self):
        self.assertIn("Запустить.bat", self.text)
        self.assertIn("Запустить.command", self.text)

    def test_the_manual_way_is_still_there(self):
        self.assertIn("python webapp/app.py", self.text)

    def test_no_cp_command_is_prescribed_to_windows(self):
        """`cp` в Windows нет, а команда стояла в общей инструкции."""
        self.assertNotIn("cp proxies.example.txt proxies.txt", self.text)

    def test_the_permission_bit_is_mentioned(self):
        self.assertIn("chmod +x", self.text)


class TestItActuallyRuns(unittest.TestCase):
    """Скрипт для макоси и линукса можно и запустить — проверим.

    Проверяется то, что делает сам скрипт: переход в свою папку и
    создание списка прокси. Установку зависимостей и запуск сервера
    подменяем — тесту ни то, ни другое не нужно.
    """

    def setUp(self):
        if sys.platform.startswith("win"):
            self.skipTest("на Windows запускается .bat, а не .command")
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

        shutil.copy(COMMAND, self.root / COMMAND.name)
        shutil.copy(ROOT / "requirements.txt", self.root)
        shutil.copy(ROOT / "proxies.example.txt", self.root)
        (self.root / "webapp").mkdir()
        (self.root / "webapp" / "app.py").write_text(
            'print("подменённый сервер")\n', encoding="utf-8")

        # Установку пакетов вырезаем: она лезет в сеть и тут не проверяется.
        script = self.root / COMMAND.name
        text = script.read_text(encoding="utf-8").replace(
            '"$PY" -m pip install -r requirements.txt'
            ' --quiet --disable-pip-version-check',
            'echo "установка пропущена"')
        script.write_text(text, encoding="utf-8")
        script.chmod(0o755)

    def run_it(self):
        return subprocess.run([str(self.root / COMMAND.name)],
                              cwd=self.root, input="", text=True,
                              capture_output=True, timeout=60)

    def test_it_creates_the_proxy_list(self):
        self.assertFalse((self.root / "proxies.txt").exists())
        self.run_it()
        self.assertTrue((self.root / "proxies.txt").exists())

    def test_the_list_is_a_copy_of_the_example(self):
        self.run_it()
        self.assertEqual((self.root / "proxies.txt").read_text(encoding="utf-8"),
                         (self.root / "proxies.example.txt").read_text(
                             encoding="utf-8"))

    def test_an_existing_list_is_left_alone(self):
        """Там адреса с паролями — затирать нельзя."""
        mine = self.root / "proxies.txt"
        mine.write_text("1.2.3.4:8000:user:secret\n", encoding="utf-8")
        self.run_it()
        self.assertIn("secret", mine.read_text(encoding="utf-8"))

    def test_it_reaches_the_program(self):
        self.assertIn("подменённый сервер", self.run_it().stdout)

    def test_it_works_when_called_from_another_folder(self):
        """Двойной клик в Finder запускает из домашней папки."""
        found = subprocess.run([str(self.root / COMMAND.name)],
                               cwd=str(ROOT), input="", text=True,
                               capture_output=True, timeout=60)
        self.assertIn("подменённый сервер", found.stdout)
        self.assertTrue((self.root / "proxies.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
