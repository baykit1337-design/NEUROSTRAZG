"""След для «вернуть как было» принадлежит задаче, а не папке.

Раньше он лежал в общем словаре с ключом-папкой. Две операции над одной
папкой затирали запись друг друга: та, что закончилась первой, писала в
журнал чужую копию — и «вернуть как было» возвращало не своё. А задача,
упавшая до итога, оставляла запись навсегда.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import OpReport  # noqa: E402
from ops import history  # noqa: E402
from webapp import app as web  # noqa: E402


class JobCopyTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        self.saved = (history.DATA_DIR, history.HISTORY_FILE, history.BACKUP_DIR)
        history.DATA_DIR = self.tmp / "data"
        history.HISTORY_FILE = history.DATA_DIR / "history.json"
        history.BACKUP_DIR = history.DATA_DIR / "backup"
        self.addCleanup(self.restore)

        self.book = self.tmp / "книга"
        self.book.mkdir()
        (self.book / "Глава 1.txt").write_text("было", encoding="utf-8")

    def restore(self):
        (history.DATA_DIR, history.HISTORY_FILE, history.BACKUP_DIR) = self.saved

    def prepare(self, operation):
        return web._prepare(str(self.tmp), "книга", operation,
                            only=["Глава 1.txt"])

    def job_for(self, made, kind):
        job = web.Job(id=kind, kind=kind, output_dir=str(made.dir))
        job.keep(made)
        return job


class TestEachJobKeepsItsOwn(JobCopyTestCase):
    def test_two_jobs_over_one_folder_do_not_share_a_copy(self):
        first = self.job_for(self.prepare("split"), "split")
        (self.book / "Глава 1.txt").write_text("стало", encoding="utf-8")
        second = self.job_for(self.prepare("rename"), "rename")

        self.assertTrue(first.backup)
        self.assertTrue(second.backup)
        self.assertNotEqual(first.backup, second.backup)

    def test_the_journal_gets_the_copy_of_that_very_job(self):
        """Главное: закончившая первой пишет свою копию, а не последнюю."""
        first = self.job_for(self.prepare("split"), "split")
        (self.book / "Глава 1.txt").write_text("стало", encoding="utf-8")
        self.job_for(self.prepare("rename"), "rename")

        web._finish(first, OpReport(total=1, written=1), "Записано")

        written = history.records()[0]
        self.assertEqual(written.backup, first.backup)
        self.assertEqual(
            (Path(written.backup) / "Глава 1.txt").read_text(encoding="utf-8"),
            "было")

    def test_what_the_job_will_write_travels_with_it_too(self):
        job = self.job_for(self.prepare("split"), "split")
        web._finish(job, OpReport(total=1, written=1), "Записано")
        self.assertEqual(list(history.records()[0].wrote), ["Глава 1.txt"])


class TestNothingIsLeftBehind(JobCopyTestCase):
    def test_a_job_that_never_finished_leaves_no_record_anywhere(self):
        """Упавшая до итога задача уносит свой след с собой."""
        lost = self.job_for(self.prepare("split"), "split")
        del lost

        fresh = self.job_for(self.prepare("rename"), "rename")
        web._finish(fresh, OpReport(total=1, written=1), "Записано")
        self.assertEqual(history.records()[0].backup, fresh.backup)

    def test_a_job_starts_with_an_empty_trace(self):
        job = web.Job(id="пустая")
        self.assertEqual(job.backup, "")
        self.assertEqual(job.wrote, [])

    def test_two_jobs_do_not_share_the_same_list(self):
        one, two = web.Job(id="один"), web.Job(id="два")
        one.wrote.append("Глава 1.txt")
        self.assertEqual(two.wrote, [])


if __name__ == "__main__":
    unittest.main()
