"""Нижняя строка состояния (6.10 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net import traffic  # noqa: E402


class TestTraffic(unittest.TestCase):
    """Счётчик входящего трафика."""

    def setUp(self):
        traffic.reset()
        self.addCleanup(traffic.reset)

    def test_starts_empty(self):
        self.assertEqual(traffic.total(), 0)
        self.assertEqual(traffic.speed(), 0.0)

    def test_bytes_add_up(self):
        traffic.add(1000)
        traffic.add(500)
        self.assertEqual(traffic.total(), 1500)

    def test_speed_is_per_second_not_per_sample(self):
        """Иначе один запрос в конце окна давал бы бесконечную скорость."""
        traffic.add(int(traffic.WINDOW * 1000))
        self.assertAlmostEqual(traffic.speed(), 1000, delta=1)

    def test_old_samples_fall_out_of_the_window(self):
        traffic.add(5000)
        # Подменяем время замера на давнее — ждать окно в тесте незачем.
        traffic._SAMPLES[:] = [(t - traffic.WINDOW - 1, size)
                               for t, size in traffic._SAMPLES]
        self.assertEqual(traffic.speed(), 0.0)
        # Общий счётчик при этом не обнуляется: это разные величины.
        self.assertEqual(traffic.total(), 5000)

    def test_zero_and_negative_are_ignored(self):
        traffic.add(0)
        traffic.add(-10)
        self.assertEqual(traffic.total(), 0)

    def test_reset_clears_everything(self):
        traffic.add(1000)
        traffic.reset()
        self.assertEqual(traffic.state(), {"speed": 0, "total": 0})

    def test_many_threads_do_not_lose_bytes(self):
        import threading

        def work():
            for _ in range(200):
                traffic.add(10)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(traffic.total(), 8 * 200 * 10)


class TestStatusRoute(unittest.TestCase):
    """`/api/status` — одна точка на всю нижнюю строку."""

    def setUp(self):
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()
        traffic.reset()
        self.addCleanup(traffic.reset)

    def test_idle_state(self):
        data = self.app.get("/api/status").get_json()
        self.assertFalse(data["busy"])
        self.assertEqual(data["elapsed"], 0)
        self.assertEqual(data["job"], "")

    def test_running_job_is_reported(self):
        from webapp.app import JOBS, JOBS_LOCK, Job

        job = Job(id="проба", kind="download", meta={"threads": 3})
        job.progress = {"done": 5, "total": 20}
        with JOBS_LOCK:
            JOBS[job.id] = job
        self.addCleanup(lambda: JOBS.pop(job.id, None))

        data = self.app.get("/api/status").get_json()
        self.assertTrue(data["busy"])
        self.assertEqual(data["job"], "проба")
        self.assertEqual(data["done"], 5)
        self.assertEqual(data["total"], 20)
        self.assertEqual(data["threads"], 3)
        self.assertTrue(data["network"])

    def test_finished_job_is_not_busy(self):
        from webapp.app import JOBS, JOBS_LOCK, Job

        job = Job(id="конченная")
        job.finished = time.monotonic()
        with JOBS_LOCK:
            JOBS[job.id] = job
        self.addCleanup(lambda: JOBS.pop(job.id, None))

        self.assertFalse(self.app.get("/api/status").get_json()["busy"])

    def test_speed_only_for_network_work(self):
        """Скорость показывается только там, где есть сеть."""
        from webapp.app import JOBS, JOBS_LOCK, Job

        job = Job(id="разбивка", kind="split")
        with JOBS_LOCK:
            JOBS[job.id] = job
        self.addCleanup(lambda: JOBS.pop(job.id, None))

        self.assertFalse(self.app.get("/api/status").get_json()["network"])

    def test_bytes_do_not_collide_with_item_count(self):
        """«total» строки — это элементы операции, а не байты."""
        traffic.add(4096)
        data = self.app.get("/api/status").get_json()
        self.assertEqual(data["received"], 4096)
        self.assertEqual(data["total"], 0)

    def test_job_snapshot_has_the_stopwatch(self):
        from webapp.app import Job

        job = Job(id="секундомер")
        snapshot = job.snapshot()
        self.assertIn("elapsed", snapshot)
        self.assertTrue(snapshot["running"])


class TestStatusBarMarkup(unittest.TestCase):
    """Разметка и стили полосы."""

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent.parent
        cls.html = (root / "webapp" / "static" / "index.html").read_text(
            encoding="utf-8")
        cls.js = (root / "webapp" / "static" / "tabs.js").read_text(
            encoding="utf-8")

    def test_bar_is_present(self):
        self.assertIn('id="statusBar"', self.html)
        for part in ("sbSpeed", "sbElapsed", "sbLeft", "sbMode"):
            self.assertIn(f'id="{part}"', self.html)

    def test_bar_is_fixed_and_thin(self):
        block = self.html[self.html.index(".statusbar{"):]
        block = block[:block.index("}")]
        self.assertIn("position:fixed", block)
        self.assertIn("height:28px", block)

    def test_page_leaves_room_for_the_bar(self):
        """Иначе полоса накрывала бы последнюю карточку."""
        block = self.html[self.html.index("  body{"):]
        block = block[:block.index("}")]
        bottom = int(block.split("padding:")[1].split(";")[0].split()[-1]
                     .replace("px", ""))
        self.assertGreaterEqual(bottom, 28)

    def test_text_lights_up_on_hover(self):
        self.assertIn(".statusbar:hover{", self.html)

    def test_no_dot_before_the_first_item(self):
        """Соседство в CSS считается по разметке, а не по видимости."""
        self.assertIn(".sb-item.first::before{content:none", self.html)
        self.assertIn("function sbFirst()", self.js)

    def test_duration_lands_in_the_result(self):
        """«заняло 18 мин 42 с» — в блоке результата, полоса к тому времени гаснет."""
        self.assertIn("function addTook(job)", self.js)
        self.assertIn("' · заняло '", self.js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
