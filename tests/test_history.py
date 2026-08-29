"""Журнал, корзина и сравнение версий (4.5 и 4.10 ТЗ NEUROSTRAZH).

Журнал и корзина живут рядом с программой, поэтому в тестах их пути
подменяются на временные: настоящую историю пользователя трогать нельзя.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core.models import Chapter  # noqa: E402
from ops import diff, history  # noqa: E402


class HistoryTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        # Журнал и корзина — в свою папку, а не в настоящую.
        self.saved = (history.DATA_DIR, history.HISTORY_FILE, history.BACKUP_DIR)
        history.DATA_DIR = self.tmp / "data"
        history.HISTORY_FILE = history.DATA_DIR / "history.json"
        history.BACKUP_DIR = history.DATA_DIR / "backup"
        self.addCleanup(self.restore)

    def restore(self):
        (history.DATA_DIR, history.HISTORY_FILE, history.BACKUP_DIR) = self.saved

    def folder(self, name, chapters):
        path = self.tmp / name
        path.mkdir(parents=True, exist_ok=True)
        for number, paragraphs in chapters.items():
            formats.write(path / f"Глава {number}.txt",
                          [Chapter(number=number, title=f"Глава {number}",
                                   paragraphs=list(paragraphs))],
                          headings=True)
        return path


class TestJournal(HistoryTestCase):
    """4.10: что, когда, над какой папкой, сколько файлов и ошибок."""

    def test_record_is_written_and_read_back(self):
        history.add("замена", source="/книга", output="/правлено",
                    files=12, failed=1)
        found = history.records()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].operation, "замена")
        self.assertEqual(found[0].files, 12)
        self.assertEqual(found[0].failed, 1)

    def test_fresh_records_come_first(self):
        history.add("первая")
        history.add("вторая")
        self.assertEqual([r.operation for r in history.records()],
                         ["вторая", "первая"])

    def test_time_is_readable(self):
        record = history.add("проба")
        self.assertRegex(record.when, r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}")

    def test_broken_journal_does_not_break_the_run(self):
        history.DATA_DIR.mkdir(parents=True, exist_ok=True)
        history.HISTORY_FILE.write_text("{битый", encoding="utf-8")
        self.assertEqual(history.records(), [])
        history.add("после битого")
        self.assertEqual(len(history.records()), 1)


class TestBackup(HistoryTestCase):
    """4.10: перед перезаписью старая версия уходит в корзину."""

    def test_backup_copies_the_folder(self):
        book = self.folder("книга", {1: ["Было так."], 2: ["И так."]})
        path = history.backup(book, "замена")

        self.assertTrue(path)
        copy = Path(path)
        self.assertTrue(copy.is_dir())
        self.assertEqual(len(list(copy.glob("*.txt"))), 2)

    def test_empty_folder_is_not_copied(self):
        empty = self.tmp / "пусто"
        empty.mkdir()
        self.assertEqual(history.backup(empty), "")

    def test_missing_folder_is_not_an_error(self):
        self.assertEqual(history.backup(self.tmp / "нет-такой"), "")

    def test_only_the_named_files_are_copied(self):
        """Пишущий прямо в выбранную папку не должен утаскивать в корзину
        всё, что там лежало: выбрать могут рабочий стол."""
        book = self.folder("книга", {1: ["Было так."], 2: ["И так."]})
        (book / "чужое.txt").write_text("не наше", encoding="utf-8")

        path = history.backup_files([book / "Глава 1.txt"], "замена")
        self.assertTrue(path)
        self.assertEqual(sorted(p.name for p in Path(path).iterdir()),
                         ["Глава 1.txt"])

    def test_files_that_are_not_there_yet_are_skipped(self):
        """Затереть можно только то, что уже лежит."""
        book = self.folder("книга", {1: ["Было так."]})
        path = history.backup_files(
            [book / "Глава 1.txt", book / "Глава 2.txt"], "замена")
        self.assertEqual([p.name for p in Path(path).iterdir()],
                         ["Глава 1.txt"])

    def test_nothing_to_replace_makes_no_copy(self):
        """Пустая копия в корзине — мусор, за которым потом лезть."""
        book = self.folder("книга", {1: ["Было так."]})
        self.assertEqual(history.backup_files([book / "Глава 9.txt"]), "")

    def test_old_backups_are_removed(self):
        """Папка с копиями книги на пятьсот глав быстро съест диск."""
        book = self.folder("книга", {1: ["Текст."]})
        for _ in range(history.KEEP_BACKUPS + 3):
            history.backup(book, "проба")
        self.assertLessEqual(len(history.backups()), history.KEEP_BACKUPS)

    def test_restore_brings_files_back(self):
        book = self.folder("книга", {1: ["Первая версия."]})
        path = history.backup(book, "до-правки")

        formats.write(book / "Глава 1.txt",
                      [Chapter(number=1, title="Глава 1",
                               paragraphs=["Испорченная версия."])],
                      headings=True)
        self.assertIn("Испорченная",
                      (book / "Глава 1.txt").read_text(encoding="utf-8"))

        count = history.restore(Path(path), book)
        self.assertEqual(count, 1)
        self.assertIn("Первая версия",
                      (book / "Глава 1.txt").read_text(encoding="utf-8"))

    def test_restore_backs_up_the_current_state_first(self):
        """«Восстановить» по ошибке не должно быть необратимым."""
        book = self.folder("книга", {1: ["Первая."]})
        path = history.backup(book, "первая")

        formats.write(book / "Глава 1.txt",
                      [Chapter(number=1, title="Глава 1",
                               paragraphs=["Вторая."])], headings=True)
        before = len(history.backups())
        history.restore(Path(path), book)
        self.assertGreater(len(history.backups()), before)

    def test_restore_of_a_missing_copy_is_reported(self):
        with self.assertRaises(history.RestoreError):
            history.restore(self.tmp / "нет", self.tmp / "куда")

    def test_state_lists_records_and_backups(self):
        book = self.folder("книга", {1: ["Текст."]})
        path = history.backup(book, "проба")
        history.add("проба", source=str(book), backup=path, files=1)

        state = history.state()
        self.assertEqual(len(state["records"]), 1)
        self.assertEqual(len(state["backups"]), 1)
        self.assertTrue(state["records"][0]["restorable"])


class TestDataLocation(unittest.TestCase):
    """Прогон тестов не должен писать в настоящий журнал пользователя."""

    def test_tests_do_not_write_to_the_real_journal(self):
        real = Path(__file__).resolve().parent.parent / "data"
        self.assertNotEqual(history._default_dir().resolve(), real.resolve())

    def test_environment_variable_wins(self):
        import os

        saved = os.environ.get("NEUROSTRAZH_DATA")
        os.environ["NEUROSTRAZH_DATA"] = "/tmp/своя-папка"
        try:
            self.assertEqual(history._default_dir(), Path("/tmp/своя-папка"))
        finally:
            if saved is None:
                os.environ.pop("NEUROSTRAZH_DATA", None)
            else:
                os.environ["NEUROSTRAZH_DATA"] = saved


class TestDiff(HistoryTestCase):
    """4.5: что изменилось после операции."""

    def test_added_and_removed_are_marked(self):
        result = diff.compare_paragraphs(
            ["Первый.", "Второй.", "Третий."],
            ["Первый.", "Другой второй.", "Третий."])
        self.assertEqual(result.added, 1)
        self.assertEqual(result.removed, 1)
        kinds = {l.kind for l in result.lines}
        self.assertEqual(kinds, {"same", "added", "removed"})

    def test_identical_text_shows_no_change(self):
        result = diff.compare_paragraphs(["Одно.", "То же."], ["Одно.", "То же."])
        self.assertFalse(result.changed)
        self.assertEqual(result.added, 0)
        self.assertEqual(result.removed, 0)

    def test_long_unchanged_runs_are_folded(self):
        """В главе на сто абзацев правка в двух иначе теряется."""
        before = [f"Абзац {n}." for n in range(50)]
        after = list(before)
        after[25] = "Изменённый абзац."

        result = diff.compare_paragraphs(before, after, context=2)
        self.assertIn("…", [l.text for l in result.lines])
        self.assertLess(len(result.lines), len(before))

    def test_compare_two_folders(self):
        before = self.folder("до", {1: ["Было."], 2: ["Не менялось."]})
        after = self.folder("после", {1: ["Стало."], 2: ["Не менялось."]})

        report = diff.compare(str(before), str(after))
        self.assertEqual(report.changed, 1)
        data = report.as_dict()
        self.assertEqual(data["total"], 2)
        # В выдачу идут только изменённые главы.
        self.assertEqual(len(data["chapters"]), 1)
        self.assertEqual(data["chapters"][0]["chapter"], "1")

    def test_chapters_present_on_one_side_only(self):
        before = self.folder("до2", {1: ["Есть."], 2: ["Пропала."]})
        after = self.folder("после2", {1: ["Есть."], 3: ["Новая."]})

        report = diff.compare(str(before), str(after))
        self.assertEqual(report.only_left, ["2"])
        self.assertEqual(report.only_right, ["3"])

    def test_compare_two_files(self):
        before = self.folder("ф1", {1: ["Было."]}) / "Глава 1.txt"
        after = self.folder("ф2", {1: ["Стало."]}) / "Глава 1.txt"

        result = diff.compare_files(before, after)
        self.assertTrue(result.changed)
        self.assertEqual(result.added, 1)
        self.assertEqual(result.removed, 1)

    def test_cleanup_that_broke_the_text_is_visible(self):
        """Ради этого пункт и нужен: очистка снесла лишнее."""
        before = self.folder("ц1", {1: ["Название книги", "Первый абзац.",
                                        "Второй абзац."]})
        after = self.folder("ц2", {1: ["Второй абзац."]})

        report = diff.compare(str(before), str(after))
        removed = [l.text for c in report.chapters for l in c.lines
                   if l.kind == "removed"]
        self.assertIn("Первый абзац.", removed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
