"""Откат на один поток, когда в несколько не идёт.

Откат был ровно один: сайт ответил отказом — 403 или 429, — и прогон
останавливался целиком, а следующему запуску назначался один поток.

Обычный сетевой обрыв под это не подходил. Три потока, каждая глава
отваливается с «Connection was reset» — и прогон честно шёл до конца
книги, складывая в «не скачано» все триста глав подряд. Число потоков при
этом так и стояло «3»: на экране всё выглядело работающим.

Теперь пачка, из которой не пришло ни одной главы, переводит прогон в
один поток и работа продолжается. Медленно, зато с главами.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import api  # noqa: E402
from mvl import downloader as downloader_mod  # noqa: E402
from mvl.client import NetworkError  # noqa: E402
from mvl.downloader import Downloader  # noqa: E402


class Source:
    """Источник, который отдаёт главы по заданному списку исходов."""

    key = "fake"
    name = "Подставной"
    needs_proxy = False
    cancel = None
    timeouts: dict = {}

    def __init__(self, total=9, broken=()):
        self.total = total
        #: Номера глав, которые не придут.
        self.broken = set(broken)
        #: Сколько потоков работало на каждой главе — по этому и видно,
        #: сбавила ли качалка обороты.
        self.seen: list[int] = []

    def toc(self, client, novel, first=1, last=None, on_progress=None):
        rows = [api.Chapter(number=n, post_id=str(n))
                for n in range(first, (last or self.total) + 1)]
        return api.Toc(chapters=rows, missing=[])

    def chapter(self, client, chapter):
        self.seen.append(chapter.number)
        if chapter.number in self.broken:
            raise NetworkError("Connection was reset")
        return f"Глава {chapter.number}", "Текст главы."


class Said(NamedTuple):
    """Снимок того, что ушло на экран одним сообщением."""

    threads: int
    message: str


class Base(unittest.TestCase):
    def setUp(self):
        # Паузы между пачками ни к чему: проверяется решение, а не темп.
        self.addCleanup(setattr, downloader_mod, "BATCH_PAUSE_RANGE",
                        downloader_mod.BATCH_PAUSE_RANGE)
        downloader_mod.BATCH_PAUSE_RANGE = (0, 0)

        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def run_with(self, source, threads=3):
        # Качалка правит один и тот же объект прогресса и его же отдаёт —
        # складывать ссылки на него бессмысленно, все они окажутся
        # последним состоянием. Снимаем то, что проверяем.
        said = []

        def note(progress):
            said.append(Said(threads=progress.threads,
                             message=progress.message or ""))

        loader = Downloader(source=source, threads=threads, probe=False,
                            on_progress=note)
        novel = api.Novel(code=1, name="Книга", slug="k",
                          total_chapters=source.total)
        report = loader.run(novel, self.folder)
        return loader, report, said


class TestABatchThatBringsNothing(Base):
    def test_the_run_drops_to_one_thread(self):
        source = Source(total=9, broken=range(1, 4))
        loader, _, _ = self.run_with(source, threads=3)
        self.assertEqual(loader.threads, 1)

    def test_the_rest_of_the_book_is_still_downloaded(self):
        """Главное: прогон продолжается, а не кончается на первой пачке."""
        source = Source(total=9, broken=range(1, 4))
        _, report, _ = self.run_with(source, threads=3)
        self.assertEqual(report.downloaded, 6)

    def test_the_screen_is_told_the_threads_changed(self):
        """Строка «3 потока» при одном работающем — это враньё."""
        source = Source(total=9, broken=range(1, 4))
        _, _, said = self.run_with(source, threads=3)
        self.assertIn(1, [p.threads for p in said if p.threads])

    def test_the_drop_comes_with_words(self):
        """Число потоков молча меняться не должно: человек смотрит на
        экран и должен прочитать, почему стало медленнее. Что именно
        там написано — дело текста, а не проверки."""
        source = Source(total=9, broken=range(1, 4))
        _, _, said = self.run_with(source, threads=3)
        before = [p.message for p in said if p.threads and p.threads > 1]
        drop = next(p for p in said if p.threads == 1)
        self.assertTrue(drop.message.strip())
        self.assertNotIn(drop.message, before)

    def test_the_report_marks_the_downgrade(self):
        source = Source(total=9, broken=range(1, 4))
        _, report, _ = self.run_with(source, threads=3)
        self.assertTrue(report.threads_downgraded)


class TestItDoesNotFireWithoutReason(Base):
    """Сбавлять обороты на ровном месте — терять скорость даром."""

    def test_a_clean_run_keeps_its_threads(self):
        source = Source(total=9)
        loader, report, _ = self.run_with(source, threads=3)
        self.assertEqual(loader.threads, 3)
        self.assertEqual(report.downloaded, 9)
        self.assertFalse(report.threads_downgraded)

    def test_one_bad_chapter_in_a_batch_is_not_enough(self):
        """Одна осечка — это осечка, а не «сайт не тянет»."""
        source = Source(total=9, broken=(2,))
        loader, _, _ = self.run_with(source, threads=3)
        self.assertEqual(loader.threads, 3)

    def test_a_single_threaded_run_has_nothing_to_drop_to(self):
        source = Source(total=4, broken=(1,))
        loader, report, _ = self.run_with(source, threads=1)
        self.assertEqual(loader.threads, 1)
        self.assertFalse(report.threads_downgraded)


class TestEverythingIsStillCounted(Base):
    """Откат не должен ни потерять главы, ни посчитать их дважды."""

    def test_the_numbers_add_up(self):
        source = Source(total=9, broken=range(1, 4))
        _, report, _ = self.run_with(source, threads=3)
        self.assertEqual(report.downloaded + len(report.failed_chapters), 9)

    def test_no_chapter_is_asked_for_twice(self):
        source = Source(total=9, broken=range(1, 4))
        self.run_with(source, threads=3)
        self.assertEqual(len(source.seen), len(set(source.seen)))

    def test_every_chapter_is_asked_for_once(self):
        source = Source(total=9, broken=range(1, 4))
        self.run_with(source, threads=3)
        self.assertEqual(sorted(source.seen), list(range(1, 10)))

    def test_the_failed_ones_are_named(self):
        source = Source(total=9, broken=range(1, 4))
        _, report, _ = self.run_with(source, threads=3)
        self.assertEqual(sorted(report.failed_chapters), [1, 2, 3])


class TestTheWholeBookFailing(Base):
    """Сайт не отдаёт вообще ничего — прогон обязан кончиться, а не
    крутиться до последней главы, повторяя одну и ту же ошибку."""

    def test_it_finishes_and_says_nothing_was_downloaded(self):
        source = Source(total=6, broken=range(1, 7))
        _, report, _ = self.run_with(source, threads=3)
        self.assertEqual(report.downloaded, 0)
        self.assertEqual(len(report.failed_chapters), 6)

    def test_it_still_dropped_to_one_thread_on_the_way(self):
        source = Source(total=6, broken=range(1, 7))
        loader, _, _ = self.run_with(source, threads=3)
        self.assertEqual(loader.threads, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
