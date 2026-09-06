"""Оглавление из памяти, прерываемая пауза и память автопробы.

Три места, где программа делала одну и ту же работу заново при каждом
запуске.

Оглавление книги на тысячу триста глав — это тринадцать запросов с
паузами между ними, и так каждый раз, хотя менялся у книги только хвост в
пять глав. Пауза между пачками была обычным `sleep`: «Остановить»
замечалось не сразу. А проба способа многопоточности качала по пять глав
на каждую книгу — на очереди из тринадцати это шестьдесят пять запросов
ради ответа, который вчера уже получили.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from mvl import api  # noqa: E402
from mvl import client as client_mod  # noqa: E402
from mvl.downloader import Downloader, State  # noqa: E402
from net import pool as netpool  # noqa: E402


class Source:
    """Источник, который считает, о чём его спрашивали."""

    key = "fake"
    name = "Подставной"
    needs_proxy = False
    cancel = None
    timeouts: dict = {}

    def __init__(self, total=10):
        self.total = total
        #: Какие диапазоны спрашивали у оглавления.
        self.asked: list = []

    def toc(self, client, novel, first=1, last=None, on_progress=None):
        last = last or self.total
        self.asked.append((first, last))
        rows = [api.Chapter(number=n, post_id=f"p{n}", ch_name=f"Глава {n}")
                for n in range(first, last + 1)]
        return api.Toc(chapters=rows, missing=[])

    def chapter(self, client, chapter):
        return f"Глава {chapter.number}", f"Текст {chapter.number}."


class Base(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, client_mod, "SITE_PAUSE_RANGE",
                        client_mod.SITE_PAUSE_RANGE)
        client_mod.SITE_PAUSE_RANGE = (0, 0)
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def novel(self, total=10):
        return api.Novel(code=1, name="Книга", slug="k", total_chapters=total)

    def run_once(self, source, total=10):
        loader = Downloader(source=source, threads=1, probe=False)
        return loader.run(self.novel(total), self.folder)


class TestTheTocIsRemembered(Base):
    """Второй прогон не переспрашивает то, что уже лежит на диске."""

    def test_a_second_run_asks_for_nothing(self):
        source = Source(total=10)
        self.run_once(source)
        source.asked.clear()

        self.run_once(source)
        self.assertEqual(source.asked, [])

    def test_only_the_tail_is_asked_for(self):
        """Ради этого всё и затевалось: вышло пять глав — спрашиваем
        пять, а не тысячу триста."""
        source = Source(total=10)
        self.run_once(source)
        source.asked.clear()

        source.total = 13
        self.run_once(source, total=13)
        self.assertEqual(source.asked, [(11, 13)])

    def test_a_hole_is_asked_for_again(self):
        """Ненаскачанной главе память не верит: `post_id` мог устареть, и
        по нему скачалась бы не та глава."""
        source = Source(total=10)
        self.run_once(source)
        (self.folder / "0005 - Глава 5.txt").unlink()
        source.asked.clear()

        self.run_once(source)
        self.assertEqual(source.asked, [(5, 5)])

    def test_the_first_run_asks_for_everything(self):
        source = Source(total=10)
        self.run_once(source)
        self.assertEqual(source.asked, [(1, 10)])

    def test_the_chapters_are_all_there_after_the_tail(self):
        """Склейка запомненного со свежим не должна терять главы."""
        source = Source(total=10)
        self.run_once(source)
        source.total = 13
        report = self.run_once(source, total=13)
        self.assertEqual(report.downloaded, 3)
        self.assertTrue((self.folder / "0013 - Глава 13.txt").is_file())

    def test_the_memory_lands_in_the_state_file(self):
        source = Source(total=4)
        self.run_once(source, total=4)
        kept = json.loads((self.folder / "state.json")
                          .read_text(encoding="utf-8"))
        self.assertIn("toc", kept)
        self.assertEqual(kept["toc"]["1"]["post_id"], "p1")

    def test_a_record_of_the_old_shape_is_simply_re_asked(self):
        """Поля разошлись — не беда: спросим эту главу заново."""
        source = Source(total=4)
        self.run_once(source, total=4)
        state = State(self.folder / "state.json")
        state.data["toc"]["2"] = {"чего-то_такого": 1}
        state.save()
        source.asked.clear()

        self.run_once(source, total=4)
        self.assertEqual(source.asked, [(2, 2)])


class TestThePauseCanBeStopped(unittest.TestCase):
    """Оглавление на тринадцать пачек — это тринадцать пауз."""

    def test_a_raised_flag_cuts_the_pause_short(self):
        stop = threading.Event()
        stop.set()
        self.assertTrue(client_mod.polite_pause(stop))

    def test_without_a_flag_it_just_waits(self):
        was = client_mod.PAUSE_RANGE
        client_mod.PAUSE_RANGE = (0, 0)
        self.addCleanup(setattr, client_mod, "PAUSE_RANGE", was)
        self.assertFalse(client_mod.polite_pause())

    def test_a_quiet_flag_does_not_stop_anything(self):
        was = client_mod.PAUSE_RANGE
        client_mod.PAUSE_RANGE = (0, 0)
        self.addCleanup(setattr, client_mod, "PAUSE_RANGE", was)
        self.assertFalse(client_mod.polite_pause(threading.Event()))


class TestTheProbeIsRemembered(unittest.TestCase):
    """Проба качает по пять глав на книгу. Дважды за сутки — незачем."""

    def setUp(self):
        for name in ("last_download_method", "last_download_at"):
            self.addCleanup(setattr, settings, name, getattr(settings, name))
        self.addCleanup(setattr, settings.threads, "remember_hours",
                        settings.threads.remember_hours)
        # Настоящий файл настроек не трогаем.
        self.addCleanup(setattr, settings, "save", settings.save)
        settings.save = lambda *a, **k: None

    def test_a_fresh_answer_is_reused(self):
        netpool.remember(netpool.OWN_SESSION)
        self.assertEqual(netpool.recent(), netpool.OWN_SESSION)

    def test_a_stale_answer_is_not(self):
        """То, что работало месяц назад, сегодня может не работать."""
        settings.last_download_method = netpool.OWN_SESSION
        settings.last_download_at = (datetime.now() - timedelta(days=30)) \
            .strftime(netpool.WHEN)
        self.assertEqual(netpool.recent(), "")

    def test_settings_without_a_time_are_not_trusted(self):
        """Прежние настройки времени не хранили — значит верить нечему."""
        settings.last_download_method = netpool.OWN_SESSION
        settings.last_download_at = ""
        self.assertEqual(netpool.recent(), "")

    def test_a_broken_time_is_not_trusted_either(self):
        settings.last_download_method = netpool.OWN_SESSION
        settings.last_download_at = "позавчера"
        self.assertEqual(netpool.recent(), "")

    def test_nothing_remembered_means_probe(self):
        settings.last_download_method = ""
        settings.last_download_at = ""
        self.assertEqual(netpool.recent(), "")

    def test_how_long_to_trust_is_a_setting(self):
        netpool.remember(netpool.OWN_SESSION)
        self.assertEqual(netpool.recent(within_hours=0), "")

    def test_remembering_notes_the_time(self):
        settings.last_download_at = ""
        netpool.remember(netpool.SHARED_SESSION)
        self.assertTrue(settings.last_download_at)


if __name__ == "__main__":
    unittest.main()
