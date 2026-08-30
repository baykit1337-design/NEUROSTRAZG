"""Проглоченная ошибка — это ложь на экране.

`except Exception: pass` не оставляет следа нигде: операция не сделала
ничего, а человек видит «готово». Пока таких мест было восемьдесят
шесть, разбирать поломку по рассказу человека было нечем.

Здесь проверяется не текст сообщений, а само правило: у каждого широкого
перехвата должен остаться след — запись в журнал, поднятое исключение,
строка в отчёте или показанная причина.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent

#: Куда не смотрим: тесты сами ловят что угодно, окружение — не наш код.
SKIP = ("tests", ".venv", "__pycache__", "build", "dist")


def sources() -> list[Path]:
    return [p for p in sorted(ROOT.rglob("*.py"))
            if not any(part in SKIP for part in p.relative_to(ROOT).parts)]


def _catches_everything(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    names = [kind] if not isinstance(kind, ast.Tuple) else list(kind.elts)
    return any(isinstance(n, ast.Name) and n.id == "Exception" for n in names)


def _leaves_a_trace(handler: ast.ExceptHandler) -> bool:
    """Остался ли от перехваченного хоть какой-то след."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            spoken = ast.unparse(node.func)
            # Журнал, отчёт, сообщение человеку — всё это след.
            if spoken.startswith("log.") or spoken == "print":
                return True
            if any(word in spoken for word in
                   ("fail", "append", "add_error", "warn", "say", "_say")):
                return True
        # Причина, записанная в поле, которое дальше покажут, — или
        # отданная наверх возвратом: разбирает её тогда вызывающий.
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.Return)) \
                and handler.name and node is not handler:
            spoken = ast.unparse(node.value) if node.value is not None else ""
            if handler.name in spoken or (
                    isinstance(node, ast.Assign)
                    and handler.name in ast.unparse(node)):
                return True
    return False


class TestNothingIsSwallowedInSilence(unittest.TestCase):
    def test_every_wide_catch_leaves_a_trace(self):
        silent = []
        for path in sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if _catches_everything(node) and not _leaves_a_trace(node):
                    silent.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(silent, [], "перехват без следа:\n" + "\n".join(silent))

    def test_the_check_itself_can_see_a_silent_catch(self):
        """Иначе проверка была бы зелёной при любом коде."""
        tree = ast.parse("try:\n    x = 1\nexcept Exception:\n    pass\n")
        found = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
        self.assertTrue(_catches_everything(found[0]))
        self.assertFalse(_leaves_a_trace(found[0]))


if __name__ == "__main__":
    unittest.main()
