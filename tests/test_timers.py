"""Таймеры операций рядом с прогресс-баром (часть 2 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "tabs.js").read_text(encoding="utf-8")


class TestStatusBarIsGone(Base):
    """Полоса внизу убрана: содержимое уезжало под неё."""

    def test_no_markup_left(self):
        self.assertNotIn("statusbar", self.html)
        self.assertNotIn("sb-item", self.html)

    def test_no_code_left(self):
        for name in ("sbTick", "sbFirst", "SB_SAMPLES"):
            self.assertNotIn(name, self.js, name)

    def test_no_endpoint_left(self):
        app = (ROOT / "webapp" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('"/api/status"', app)

    def test_the_speed_counter_stayed_removed(self):
        """Скорость больше нигде не показывается — замерять её незачем.

        Счёт скачанного при этом вернулся, но считает он другое и для
        другого: не мегабайты в секунду для полосы внизу, а объём за
        месяц для человека с платным пакетом. Живёт он в `core`.
        """
        self.assertFalse((ROOT / "net" / "traffic.py").exists())
        for name in ("speed", "Скорость", "МБ/с"):
            self.assertNotIn(name, self.js, name)

    def test_page_bottom_padding_back_to_normal(self):
        block = self.html[self.html.index("  body{"):]
        block = block[:block.index("}")]
        self.assertIn("padding:48px 20px 80px", block)


class TestTimersInResultBlocks(Base):
    """2.1: секундомер и прогноз — в блоке результата каждой операции."""

    #: Те, что названы в ТЗ, плюс остальные длительные операции.
    BLOCKS = ("s", "sp", "mg", "rn", "ck", "ckClean", "an", "hd",
              "rp", "sg", "q", "orf")

    def test_every_long_operation_has_a_timer_slot(self):
        for prefix in self.BLOCKS:
            self.assertIn(f'id="{prefix}Timers"', self.html, prefix)

    def test_timers_are_drawn_from_one_place(self):
        """Иначе на каждой вкладке они разъехались бы по виду и формату."""
        self.assertIn("function drawTimers(", self.js)
        self.assertIn("drawTimers(statusId, LAST_JOB)", self.js)

    def test_slot_name_follows_from_the_status_name(self):
        self.assertIn("replace(/Status$/, '') + 'Timers'", self.js)

    def test_eta_uses_the_last_samples_not_the_average(self):
        """Средняя с начала врёт в начале и устаревает после смены прокси."""
        self.assertIn("ETA_SAMPLES = 20", self.js)

    def test_eta_is_a_dash_until_there_is_data(self):
        self.assertIn("осталось <b>${left || '—'}</b>", self.js)

    def test_finished_run_shows_the_total_instead(self):
        self.assertIn("заняло <b>${tookText(job.elapsed)}</b>", self.js)


class TestModeLine(Base):
    """2.2: потоки и прокси — только когда многопоточность включилась."""

    def test_single_thread_shows_nothing(self):
        block = self.js[self.js.index("function modeText("):]
        block = block[:block.index("\n}")]
        self.assertIn("threads < 2", block)
        self.assertIn("return ''", block)

    def test_downloader_reports_threads_and_proxies(self):
        source = (ROOT / "mvl" / "downloader.py").read_text(encoding="utf-8")
        self.assertIn("threads=self.threads, proxies=usable", source)

    def test_progress_carries_the_fields(self):
        from mvl.downloader import Progress

        data = Progress().as_dict()
        self.assertIn("threads", data)
        self.assertIn("proxies", data)


class TestStopwatchOnTheServer(unittest.TestCase):
    """Секундомер считает сервер: перезагрузка вкладки его не сбивает."""

    def test_job_snapshot_has_elapsed_and_running(self):
        from webapp.app import Job

        snapshot = Job(id="проба").snapshot()
        self.assertIn("elapsed", snapshot)
        self.assertTrue(snapshot["running"])

    def test_finished_job_stops_the_clock(self):
        from webapp.app import Job

        job = Job(id="проба")
        job.finished = time.monotonic()
        first = job.elapsed
        time.sleep(0.02)
        self.assertEqual(first, job.elapsed)
        self.assertFalse(job.snapshot()["running"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
