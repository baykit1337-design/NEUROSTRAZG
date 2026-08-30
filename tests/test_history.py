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


class TestUndoPutsItBack(HistoryTestCase):
    """«Вернуть как было» — одной кнопкой и по Ctrl+Z.

    Копия перед перезаписью делалась и раньше, но достать её можно было
    только через журнал: страховка, о которой узнаёшь, специально полезши
    за ней, спасает не тогда, когда нужна.
    """

    def test_it_takes_away_what_the_operation_added(self):
        """Главная работа. Копия хранит только заменённое, а операция,
        разложившая книгу по пустой папке, не заменила ничего — одной
        копией её было бы не откатить вовсе.
        """
        book = self.tmp / "книга"
        book.mkdir()
        for number in (1, 2, 3):
            (book / f"Глава {number}.txt").write_text("текст", encoding="utf-8")

        record = history.add(operation="split", output=str(book),
                             wrote=["Глава 1.txt", "Глава 2.txt", "Глава 3.txt"])
        self.assertEqual(history.undo(record), 3)
        self.assertEqual(list(book.glob("*.txt")), [])

    def test_it_does_not_touch_what_it_did_not_write(self):
        """Писали прямо в выбранную папку — там могло лежать чужое."""
        book = self.tmp / "книга"
        book.mkdir()
        (book / "Глава 1.txt").write_text("наше", encoding="utf-8")
        (book / "чужое.txt").write_text("не наше", encoding="utf-8")

        record = history.add(operation="split", output=str(book),
                             wrote=["Глава 1.txt"])
        history.undo(record)

        self.assertFalse((book / "Глава 1.txt").exists())
        self.assertEqual((book / "чужое.txt").read_text(encoding="utf-8"),
                         "не наше")

    def test_a_name_that_is_a_path_is_taken_by_its_name_only(self):
        """Удалять по пути из журнала — последнее дело: путь может вести
        куда угодно."""
        book = self.tmp / "книга"
        book.mkdir()
        (book / "Глава 1.txt").write_text("наше", encoding="utf-8")
        beyond = self.tmp / "постороннее.txt"
        beyond.write_text("не трогать", encoding="utf-8")

        record = history.add(operation="split", output=str(book),
                             wrote=["../постороннее.txt"])
        history.undo(record)
        self.assertTrue(beyond.is_file())

    def test_what_was_replaced_comes_back(self):
        book = self.folder("книга", {1: ["Первая версия."]})
        saved = history.backup(book, "проба")
        formats.write(book / "Глава 1.txt",
                      [Chapter(number=1, title="Глава 1",
                               paragraphs=["Вторая версия."])],
                      headings=True)

        record = history.add(operation="rename", output=str(book), backup=saved)
        history.undo(record)
        self.assertIn("Первая версия",
                      (book / "Глава 1.txt").read_text(encoding="utf-8"))

    def test_the_undo_is_itself_reversible(self):
        """Нажатое по ошибке «вернуть» должно быть так же обратимо, как и
        то, от чего оно спасает."""
        book = self.tmp / "книга"
        book.mkdir()
        (book / "Глава 1.txt").write_text("наше", encoding="utf-8")

        was = len(history.backups())
        history.undo(history.add(operation="split", output=str(book),
                                 wrote=["Глава 1.txt"]))
        self.assertGreater(len(history.backups()), was)

    def test_an_operation_with_nothing_left_is_not_offered(self):
        """Папку могли унести или почистить руками."""
        history.add(operation="split", output=str(self.tmp / "нет-такой"),
                    wrote=["Глава 1.txt"])
        self.assertIsNone(history.last_undo())

    def test_the_freshest_undoable_one_is_taken(self):
        book = self.tmp / "книга"
        book.mkdir()
        (book / "Глава 1.txt").write_text("наше", encoding="utf-8")

        history.add(operation="старая", output=str(self.tmp / "нет-такой"),
                    wrote=["Глава 9.txt"])
        history.add(operation="свежая", output=str(book), wrote=["Глава 1.txt"])
        self.assertEqual(history.last_undo().operation, "свежая")

    def test_an_old_record_without_the_field_still_loads(self):
        """Журнал, записанный прежней версией программы, поля не имеет."""
        got = history.Record.from_dict({"operation": "split"})
        self.assertEqual(got.wrote, [])


class TestTheBinIsWeighed(HistoryTestCase):
    """Счёт по штукам от диска не спасает.

    Десять копий одной правки — это ничто, а десять копий книги на
    пятьсот глав — гигабайты, о которых человек узнаёт от диска, а не от
    программы.
    """

    def fat(self, name, size):
        """Копия в корзине заданного веса."""
        folder = self.tmp / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "глава.txt").write_bytes(b"x" * size)
        return history.backup(folder, name)

    def test_a_folder_is_weighed_with_everything_inside(self):
        folder = self.tmp / "книга"
        (folder / "часть").mkdir(parents=True)
        (folder / "часть" / "1.txt").write_bytes(b"x" * 100)
        (folder / "2.txt").write_bytes(b"x" * 50)
        self.assertEqual(history.weigh(folder), 150)

    def test_missing_folder_weighs_nothing(self):
        self.assertEqual(history.weigh(self.tmp / "нет-такой"), 0)

    def test_the_weight_reaches_the_interface(self):
        self.fat("книга", 2048)
        state = history.state()
        self.assertEqual(state["bytes"], 2048)
        self.assertEqual(state["backups"][0]["bytes"], 2048)

    def test_copies_over_the_cap_are_removed_oldest_first(self):
        for name in ("одна", "две", "три"):
            self.fat(name, 1000)
        self.assertEqual(len(history.backups()), 3)

        history.trim(keep=history.KEEP_BACKUPS, cap=2500)
        left = [p.name for p in history.backups()]
        self.assertEqual(len(left), 2)
        self.assertTrue(any("три" in name for name in left))

    def test_the_freshest_copy_survives_any_cap(self):
        """Свежая копия — это и есть «вернуть как было»."""
        self.fat("одна", 5000)
        history.trim(keep=history.KEEP_BACKUPS, cap=1)
        self.assertEqual(len(history.backups()), 1)

    def test_a_light_bin_is_left_alone(self):
        for name in ("одна", "две"):
            self.fat(name, 10)
        history.trim(keep=history.KEEP_BACKUPS, cap=1000)
        self.assertEqual(len(history.backups()), 2)


class TestStepByStepBack(HistoryTestCase):
    """Шагов назад столько же, сколько операций.

    Одного шага мало: человек замечает неладное не на первой операции, а
    на третьей. Раньше второе нажатие брало ту же самую запись — откат
    стоял на месте.
    """

    def two_operations(self):
        book = self.tmp / "книга"
        book.mkdir()
        (book / "Глава 1.txt").write_text("первая", encoding="utf-8")
        first = history.add(operation="первая", output=str(book),
                            wrote=["Глава 1.txt"])
        (book / "Глава 2.txt").write_text("вторая", encoding="utf-8")
        second = history.add(operation="вторая", output=str(book),
                             wrote=["Глава 2.txt"])
        return book, first, second

    def test_the_second_press_takes_the_operation_before(self):
        book, _, _ = self.two_operations()

        history.undo(history.last_undo())
        self.assertEqual(history.last_undo().operation, "первая")

        history.undo(history.last_undo())
        self.assertIsNone(history.last_undo())
        self.assertEqual(sorted(p.name for p in book.glob("*.txt")), [])

    def test_a_returned_operation_is_not_offered_again(self):
        self.two_operations()
        history.undo(history.last_undo())
        self.assertNotEqual(history.last_undo().operation, "вторая")

    def test_an_operation_with_a_copy_does_not_loop_on_itself(self):
        """Тот самый случай, где шаг назад стоял на месте.

        Копия при перезаписи остаётся на диске и после возврата, поэтому
        запись оставалась откатываемой — и второе нажатие брало её же.
        """
        book = self.folder("книга", {1: ["Первая версия."]})
        older = history.add(operation="старая", output=str(book),
                            wrote=["Глава 1.txt"])
        self.assertTrue(older.undoable)

        saved = history.backup(book, "проба")
        formats.write(book / "Глава 1.txt",
                      [Chapter(number=1, title="Глава 1",
                               paragraphs=["Вторая версия."])],
                      headings=True)
        history.add(operation="перезапись", output=str(book), backup=saved)

        history.undo(history.last_undo())
        self.assertEqual(history.last_undo().operation, "старая")

    def test_the_mark_survives_a_reread_of_the_journal(self):
        """Пометка живёт в файле, а не в памяти: программу закрывают."""
        self.two_operations()
        history.undo(history.last_undo())
        self.assertTrue(
            [r for r in history.records() if r.operation == "вторая"][0].undone)

    def test_how_many_steps_are_left_is_counted(self):
        self.two_operations()
        self.assertEqual(history.steps_back(), 2)
        history.undo(history.last_undo())
        self.assertEqual(history.steps_back(), 1)

    def test_the_count_reaches_the_interface(self):
        self.two_operations()
        self.assertEqual(history.state()["undo_left"], 2)

    def test_an_old_record_is_not_considered_returned(self):
        """У записей прежней версии поля нет — они не «уже возвращены»."""
        self.assertFalse(history.Record.from_dict({"operation": "split"}).undone)


if __name__ == "__main__":
    unittest.main(verbosity=2)
