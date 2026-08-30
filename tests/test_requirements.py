"""Зависимости с границами сверху.

Пока границ нет, чужой мажорный релиз ломает программу без единого
нашего коммита: код тот же, а на новой машине он уже не заводится.
Здесь проверяется, что граница есть у каждой строки и что она не
разошлась с тем, что стоит на самом деле.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "requirements.txt"

LINE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(.*?)\s*(?:#.*)?$")


def rows() -> list[tuple[str, str]]:
    """Имя пакета и требование к версии, без комментариев и пустот."""
    found = []
    for line in FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = LINE.match(line)
        if match:
            found.append((match.group(1), match.group(2)))
    return found


class TestEveryLineHasACeiling(unittest.TestCase):
    def test_the_file_lists_something(self):
        self.assertTrue(rows())

    def test_none_of_them_is_open_ended(self):
        for name, need in rows():
            self.assertIn("<", need, f"{name}: нет границы сверху — {need!r}")

    def test_none_of_them_is_open_at_the_bottom_either(self):
        """Нижняя граница была всегда; уходить от неё мы не собирались."""
        for name, need in rows():
            self.assertIn(">=", need, f"{name}: нет нижней границы — {need!r}")


class TestTheCeilingMatchesReality(unittest.TestCase):
    """Граница, под которую не подходит стоящее сейчас, — ошибка в файле,
    а не в машине: значит, её забыли поднять после проверки."""

    def test_what_is_installed_fits_what_is_written(self):
        try:
            from importlib.metadata import PackageNotFoundError, version
            from packaging.requirements import Requirement
        except ImportError:  # pragma: no cover — окружение без packaging
            self.skipTest("нет packaging")

        for name, need in rows():
            try:
                have = version(name)
            except PackageNotFoundError:
                continue  # необязательная зависимость просто не стоит
            want = Requirement(f"{name}{need}")
            self.assertIn(have, want.specifier,
                          f"{name} {have} не подходит под {need}")


if __name__ == "__main__":
    unittest.main()
