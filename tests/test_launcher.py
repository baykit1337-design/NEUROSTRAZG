"""Запуск одним файлом (часть 5 ТЗ NEUROSTRAZH).

Открывать командную строку и вводить команды каждый раз — лишний обряд.
Файл в корне проекта делает всё сам: доставляет зависимости, создаёт
`proxies.txt` из образца и поднимает программу.

Сама работа — в `start.py`, общем для обеих систем. В `.bat` её нет и
быть не может: `cmd.exe` читает батник побайтово в текущей кодовой
странице и после каждой команды возвращается к запомненному смещению.
Один не-ASCII байт сдвигает смещение, разбор продолжается с середины
строки, `rem` теряется — и остаток русского комментария уходит в
исполнение:

    'ошибке' is not recognized as an internal or external command

Поэтому здесь проверяются байты батника, а не только его слова.
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
START = ROOT / "start.py"


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
        cls.start = START.read_text(encoding="utf-8")
        cls.both = {"Запустить.bat": cls.bat, "Запустить.command": cls.command}


class TestTheBatIsReadableByCmd(ScriptsBase):
    """Байты батника — не придирка, а причина поломки из отчёта."""

    def test_not_a_single_non_ascii_byte(self):
        """Один такой байт сдвигает разбор, и комментарий уходит в запуск."""
        data = BAT.read_bytes()
        bad = [(n, byte) for n, byte in enumerate(data) if byte > 127]
        self.assertEqual(bad, [], f"не-ASCII байты в {BAT.name}: {bad[:5]}")

    def test_the_code_page_is_not_switched_mid_file(self):
        """`chcp` посреди файла и ломал разбор: смещение уезжало.

        Ищем команду, а не слово: в пояснении рядом оно стоит законно.
        """
        commands = [line.strip() for line in self.bat.splitlines()
                    if not line.strip().startswith("rem")]
        self.assertEqual([line for line in commands if "chcp" in line], [])

    def test_lines_end_the_way_cmd_expects(self):
        """На одних LF cmd.exe спотыкается о блок в скобках, а он тут есть."""
        data = BAT.read_bytes()
        self.assertIn(b"(\r\n", data)
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))

    def test_the_mac_one_has_no_carriage_returns(self):
        """`\\r` в конце строки bash уводит в имя команды."""
        self.assertNotIn(b"\r", COMMAND.read_bytes())

    def test_git_is_told_to_leave_the_line_endings_alone(self):
        """Иначе выгрузка на Windows вернула бы LF и поломку с ним."""
        rules = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.bat -text", rules)
        self.assertIn("*.command text eol=lf", rules)


class TestWhatTheyDo(ScriptsBase):
    def test_they_work_from_any_folder(self):
        """Проект кладут куда угодно, и путь запуска бывает чужой."""
        self.assertIn('cd /d "%~dp0"', self.bat)
        self.assertIn('cd "$(dirname "$0")"', self.command)

    def test_both_hand_the_work_to_the_shared_launcher(self):
        """Две копии одного правила разъезжаются — здесь оно одно."""
        for name, text in self.both.items():
            with self.subTest(script=name):
                self.assertIn("start.py", text)

    def test_the_shared_launcher_finds_its_own_folder(self):
        """Двойной клик в Finder запускает из домашней папки."""
        self.assertIn("ROOT = Path(__file__).resolve().parent", self.start)

    def test_dependencies_are_checked_quietly(self):
        self.assertIn('"-r", str(need)', self.start)
        self.assertIn('"--quiet"', self.start)

    def test_a_failed_install_does_not_stop_the_launch(self):
        """Пакеты могли остаться с прошлого раза."""
        self.assertIn("пробую запустить как есть", self.start)

    def test_the_proxy_list_is_created_from_the_example(self):
        """Без файла программа ругается при запуске на пустом месте."""
        self.assertIn("proxies.example.txt", self.start)
        self.assertIn("proxies.txt", self.start)

    def test_an_existing_proxy_list_is_not_overwritten(self):
        """В нём адреса с паролями — затирать его нельзя."""
        self.assertIn("if mine.exists() or not example.is_file():", self.start)

    def test_it_starts_the_program(self):
        self.assertIn('ROOT / "webapp" / "app.py"', self.start)

    def test_the_window_stays_open_on_a_failure(self):
        """Иначе ошибка мелькнёт и окно закроется."""
        self.assertIn("pause", self.bat)
        self.assertIn("read -r -p", self.command)

    def test_a_missing_python_is_explained(self):
        """По-русски сказать некому: питона, который сказал бы, ещё нет."""
        self.assertIn("Python not found", self.bat)
        self.assertIn("Python ne nayden", self.bat)
        self.assertIn("Python не найден", self.command)

    def test_the_browser_is_not_opened_twice(self):
        """Программа открывает его сама, через секунду после старта —
        когда сервер уже отвечает. Второе открытие дало бы лишнюю
        вкладку с ошибкой соединения."""
        self.assertNotIn("start \"\" http", self.bat)
        self.assertNotIn("open http", self.command)
        self.assertNotIn("webbrowser", self.start)


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

    Проверяется то, что делает связка целиком: переход в свою папку,
    создание списка прокси и выход на программу. `requirements.txt` в
    подставную папку не кладём — тогда установка честно пропускается сама,
    без подмены строк в скрипте: она лезла бы в сеть, а тут не проверяется.
    """

    def setUp(self):
        if sys.platform.startswith("win"):
            self.skipTest("на Windows запускается .bat, а не .command")
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

        shutil.copy(COMMAND, self.root / COMMAND.name)
        shutil.copy(START, self.root)
        shutil.copy(ROOT / "proxies.example.txt", self.root)
        (self.root / "webapp").mkdir()
        (self.root / "webapp" / "app.py").write_text(
            'print("подменённый сервер")\n', encoding="utf-8")
        (self.root / COMMAND.name).chmod(0o755)

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
