"""Копия по мере надобности и длинные пути Windows.

Качалка копировала папку книги целиком перед каждым прогоном. У книги на
две тысячи глав это две тысячи файлов ради пяти новых — минуты ожидания
на каждом запуске. И всё впустую дважды: перезаписывать в обычном прогоне
нечего (готовые главы пропускаются), а записи в журнал скачивание не
делает вовсе — то есть до этой копии не дотянулось бы и «вернуть как
было».

Вторая беда оттуда же. Путь копии складывается из папки книги и имени
главы, а имена бывают в полторы строки: «Chapter 111: Thirty Years East
of the River, Thirty Years West of the River, Don't Bully the Poor Son of
a Concubine». Windows режет на 260 знаках и отвечает «Системе не удается
найти указанный путь» — читается как «файла нет», хотя файл на месте.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import longpath  # noqa: E402
from mvl import api  # noqa: E402
from mvl import client as client_mod  # noqa: E402
from mvl.downloader import Downloader  # noqa: E402
from ops import history as history_op  # noqa: E402


class Source:
    key = "fake"
    name = "Подставной"
    needs_proxy = False
    cancel = None
    timeouts: dict = {}

    def __init__(self, total=4):
        self.total = total

    def toc(self, client, novel, first=1, last=None, on_progress=None):
        rows = [api.Chapter(number=n, post_id=str(n))
                for n in range(first, (last or self.total) + 1)]
        return api.Toc(chapters=rows, missing=[])

    def chapter(self, client, chapter):
        return f"Глава {chapter.number}", f"Текст главы {chapter.number}."


class Base(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, client_mod, "SITE_PAUSE_RANGE",
                        client_mod.SITE_PAUSE_RANGE)
        client_mod.SITE_PAUSE_RANGE = (0, 0)

        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = Path(self.dir.name) / "книга"
        self.folder.mkdir()

        self.addCleanup(setattr, history_op, "BACKUP_DIR",
                        history_op.BACKUP_DIR)
        history_op.BACKUP_DIR = Path(self.dir.name) / "корзина"

    def trash(self) -> list:
        """Что лежит в корзине."""
        if not history_op.BACKUP_DIR.is_dir():
            return []
        return sorted(history_op.BACKUP_DIR.iterdir())


class TestNothingIsCopiedForNothing(Base):
    """Прогон, которому нечего перезаписывать, не копирует ничего."""

    def test_a_clean_folder_leaves_the_trash_alone(self):
        spare = history_op.Sparing("download")
        loader = Downloader(source=Source(), threads=1, probe=False,
                            spare=spare)
        loader.run(api.Novel(code=1, name="Книга", slug="k",
                             total_chapters=4), self.folder)

        self.assertEqual(spare.kept, 0)
        self.assertEqual(self.trash(), [])

    def test_the_folder_is_not_even_made(self):
        """Пустая папка в корзине — это обещание копии, которой нет."""
        spare = history_op.Sparing("download")
        spare.keep(self.folder / "нет такого файла.txt")
        self.assertEqual(spare.where, "")
        self.assertFalse(history_op.BACKUP_DIR.exists())

    def test_the_chapters_are_still_written(self):
        """Отказ от копии не должен отменить саму работу."""
        loader = Downloader(source=Source(), threads=1, probe=False,
                            spare=history_op.Sparing("download"))
        report = loader.run(api.Novel(code=1, name="Книга", slug="k",
                                      total_chapters=4), self.folder)
        self.assertEqual(report.downloaded, 4)


class TestOnlyWhatWeOverwrite(Base):
    """Бережём ровно тот файл, поверх которого пишем."""

    def test_an_existing_file_is_kept(self):
        spare = history_op.Sparing("download")
        one = self.folder / "0001 - Глава 1.txt"
        one.write_text("прежнее", encoding="utf-8")

        spare.keep(one)
        self.assertEqual(spare.kept, 1)
        kept = Path(spare.where) / one.name
        self.assertEqual(kept.read_text(encoding="utf-8"), "прежнее")

    def test_the_neighbours_are_not_touched(self):
        """Прежде уезжала вся папка. Теперь — только то, что заменяем."""
        spare = history_op.Sparing("download")
        (self.folder / "0001 - Глава 1.txt").write_text("а", encoding="utf-8")
        (self.folder / "0002 - Глава 2.txt").write_text("б", encoding="utf-8")

        spare.keep(self.folder / "0001 - Глава 1.txt")
        self.assertEqual(list(Path(spare.where).iterdir()),
                         [Path(spare.where) / "0001 - Глава 1.txt"])

    def test_a_rerun_over_ready_chapters_keeps_them(self):
        """state.json потеряли, файлы остались: качалка пишет поверх — и
        вот тут копия и нужна."""
        for number in (1, 2, 3, 4):
            (self.folder / f"{number:04d} - Глава {number}.txt").write_text(
                "старое", encoding="utf-8")

        spare = history_op.Sparing("download")
        loader = Downloader(source=Source(), threads=1, probe=False,
                            spare=spare)
        loader.run(api.Novel(code=1, name="Книга", slug="k",
                             total_chapters=4), self.folder)

        self.assertEqual(spare.kept, 4)
        saved = Path(spare.where) / "0001 - Глава 1.txt"
        self.assertEqual(saved.read_text(encoding="utf-8"), "старое")

    def test_a_run_without_sparing_still_works(self):
        """Качалку зовут и из проверок, и из замера — без страховки."""
        loader = Downloader(source=Source(), threads=1, probe=False)
        report = loader.run(api.Novel(code=1, name="Книга", slug="k",
                                      total_chapters=4), self.folder)
        self.assertEqual(report.downloaded, 4)

    def test_a_broken_trash_does_not_break_the_run(self):
        """Копия — страховка, а не работа: ронять из-за неё уже скачанную
        главу значило бы менять дело на страховку."""
        # Корзина «внутри» файла: папку там не завести ни на одной системе.
        blocked = Path(self.dir.name) / "не папка"
        blocked.write_text("файл, а не папка", encoding="utf-8")
        history_op.BACKUP_DIR = blocked / "корзина"

        spare = history_op.Sparing("download")
        one = self.folder / "0001 - Глава 1.txt"
        one.write_text("прежнее", encoding="utf-8")

        spare.keep(one)
        self.assertEqual(spare.kept, 0)
        self.assertEqual(spare.where, "")

    def test_a_copy_that_fails_does_not_break_the_run(self):
        """Папка корзины завелась, а сам файл не скопировался.

        Диск кончился, файл заняли, имя не легло — причин много, и все
        они снаружи. Глава при этом уже скачана: ронять её из-за
        неудавшейся страховки значило бы менять дело на страховку.
        Отказ подставляем прямо: перебрать все причины на живом диске
        нельзя, а нужна тут ровно одна ветка — что будет после отказа.
        """
        spare = history_op.Sparing("download")
        one = self.folder / "0001 - Глава 1.txt"
        one.write_text("прежнее", encoding="utf-8")

        def refuses(source, target, **rest):
            raise OSError("на диске нет места")

        was = shutil.copy2
        shutil.copy2 = refuses
        self.addCleanup(setattr, shutil, "copy2", was)

        spare.keep(one)                      # не должно бросить наружу
        self.assertEqual(spare.kept, 0)
        self.assertTrue(one.is_file())


class TestLongWindowsPaths(unittest.TestCase):
    """Приставка `\\\\?\\` снимает предел в 260 знаков."""

    def setUp(self):
        self.addCleanup(setattr, longpath, "windows", longpath.windows)

    def onWindows(self, yes=True):
        longpath.windows = lambda: yes

    def test_a_windows_path_gets_the_prefix(self):
        self.onWindows()
        self.assertTrue(longpath.wide("C:\\Книги\\глава.txt")
                        .startswith("\\\\?\\"))

    def test_a_network_path_gets_its_own_prefix(self):
        """Просто приписать `\\\\?\\` к сетевому пути нельзя — получится
        имя, которого нет."""
        self.onWindows()
        said = longpath.wide("\\\\сервер\\шара\\глава.txt")
        self.assertTrue(said.startswith("\\\\?\\UNC\\"))
        self.assertIn("сервер", said)

    def test_the_prefix_is_not_added_twice(self):
        self.onWindows()
        once = longpath.wide("C:\\Книги\\глава.txt")
        self.assertEqual(longpath.wide(once), once)

    def test_elsewhere_the_path_is_left_alone(self):
        """На остальных системах предела нет, а приставка стала бы частью
        имени файла."""
        self.onWindows(False)
        self.assertEqual(longpath.wide("/книги/глава.txt"),
                         "/книги/глава.txt")

    def test_copying_goes_the_long_way_on_windows(self):
        """Само копирование обязано идти через приставку.

        На этой системе разницы не видно: `wide` тут ничего не делает, и
        копия проходит одинаково с ним и без него. А на Windows без него
        она и упирается в предел — ровно та беда, ради которой всё это.
        Поэтому спрашиваем прямо: с чем ушёл вызов.
        """
        self.onWindows()
        seen = []
        was = shutil.copy2
        shutil.copy2 = lambda source, target, **rest: seen.append(
            (str(source), str(target)))
        self.addCleanup(setattr, shutil, "copy2", was)

        history_op._copy("C:\\Книги\\глава.txt", "C:\\Копия\\глава.txt")

        self.assertEqual(len(seen), 1)
        for one in seen[0]:
            self.assertTrue(one.startswith("\\\\?\\"), one)

    def test_a_really_long_name_is_copied(self):
        """Настоящий файл с длинным именем — не разговор о приставке, а
        проверка, что копирование его берёт."""
        with tempfile.TemporaryDirectory() as where:
            root = Path(where)
            was = history_op.BACKUP_DIR
            history_op.BACKUP_DIR = root / "корзина"
            self.addCleanup(setattr, history_op, "BACKUP_DIR", was)

            name = ("0134 - Chapter 111_ Thirty Years East of the River, "
                    "Thirty Years West of the River, Don't Bully the Poor "
                    "Son of a Concubine.txt")
            one = root / name
            one.write_text("текст главы", encoding="utf-8")

            spare = history_op.Sparing("download")
            spare.keep(one)
            self.assertEqual(spare.kept, 1)
            self.assertEqual((Path(spare.where) / name)
                             .read_text(encoding="utf-8"), "текст главы")


if __name__ == "__main__":
    unittest.main()
