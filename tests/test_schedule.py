"""Ночной запуск очереди книг.

Очередь и задумана как ночная работа: поставил десяток книг, ушёл спать,
утром они лежат. Но нажимать «Запустить» приходилось руками — то есть
сидеть до ночи или качать днём, когда канал нужен для другого.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import schedule  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        was = schedule.FILE
        schedule.FILE = Path(self._dir.name) / "schedule.json"
        self.addCleanup(setattr, schedule, "FILE", was)

    def at(self, when: str):
        return datetime.strptime(f"2026-08-30 {when}", "%Y-%m-%d %H:%M")


class TestSettingTheTime(Base):
    def test_nothing_is_set_at_first(self):
        plan = schedule.get()
        self.assertFalse(plan.on)
        self.assertEqual(plan.at, "")

    def test_the_time_is_remembered(self):
        schedule.save("03:00", True)
        self.assertEqual(schedule.get().at, "03:00")
        self.assertTrue(schedule.get().on)

    def test_nonsense_is_refused(self):
        for bad in ("25:00", "3", "три часа", "03:60"):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    schedule.save(bad, True)

    def test_without_a_time_there_is_no_schedule(self):
        """Галочка без времени — обещание, которое некому исполнить."""
        self.assertFalse(schedule.save("", True).on)

    def test_the_run_settings_are_kept_with_it(self):
        """Ночью спросить будет некого."""
        schedule.save("03:00", True, {"threads": 3, "mode": "proxy"})
        self.assertEqual(schedule.get().payload["threads"], 3)

    def test_changing_the_time_keeps_the_settings(self):
        schedule.save("03:00", True, {"threads": 3})
        schedule.save("04:00", True)
        self.assertEqual(schedule.get().payload["threads"], 3)

    def test_a_broken_file_is_not_a_broken_program(self):
        schedule.FILE.parent.mkdir(parents=True, exist_ok=True)
        schedule.FILE.write_text("{не json", encoding="utf-8")
        self.assertFalse(schedule.get().on)


class TestWhenItIsDue(Base):
    def plan(self, **more):
        return schedule.Plan(**{"at": "03:00", "on": True, **more})

    def test_at_the_appointed_minute(self):
        self.assertTrue(schedule.due(self.plan(), self.at("03:00")))

    def test_a_few_minutes_late_is_still_fine(self):
        """Сторож смотрит на часы раз в полминуты, а машина могла спать."""
        self.assertTrue(schedule.due(self.plan(), self.at("03:20")))

    def test_before_the_time_it_waits(self):
        self.assertFalse(schedule.due(self.plan(), self.at("02:59")))

    def test_long_after_it_does_not_start_by_itself(self):
        """Программу включили в десять утра — «три часа уже прошло» не
        повод занимать канал сейчас."""
        self.assertFalse(schedule.due(self.plan(), self.at("10:00")))

    def test_switched_off_means_off(self):
        self.assertFalse(schedule.due(self.plan(on=False), self.at("03:00")))

    def test_without_a_time_it_never_comes(self):
        self.assertFalse(schedule.due(self.plan(at=""), self.at("03:00")))

    def test_once_a_night_and_no_more(self):
        self.assertFalse(schedule.due(self.plan(last="2026-08-30"),
                                      self.at("03:10")))

    def test_yesterdays_run_does_not_block_today(self):
        self.assertTrue(schedule.due(self.plan(last="2026-08-29"),
                                     self.at("03:00")))

    def test_marking_it_stops_a_second_start(self):
        schedule.save("03:00", True)
        schedule.mark(self.at("03:00"))
        self.assertFalse(schedule.due(schedule.get(), self.at("03:10")))


class TestOverHttp(Base):
    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()
        self.web = web

    def test_it_says_what_is_set(self):
        got = self.app.get("/api/downloads/schedule").get_json()
        self.assertIn("at", got)
        self.assertIn("on", got)

    def test_saving_and_reading_back(self):
        self.app.post("/api/downloads/schedule",
                      json={"at": "04:30", "on": True,
                            "run": {"threads": 2}})
        got = self.app.get("/api/downloads/schedule").get_json()
        self.assertEqual(got["at"], "04:30")
        self.assertTrue(got["on"])

    def test_nonsense_is_refused_with_a_word(self):
        res = self.app.post("/api/downloads/schedule",
                            json={"at": "четверть третьего", "on": True})
        self.assertEqual(res.status_code, 400)
        self.assertIn("03:00", res.get_json()["error"])

    def test_the_watchman_runs_the_same_start_as_the_button(self):
        """Иначе ночной запуск повторял бы восемьдесят строк и разошёлся
        бы с кнопкой на второй правке."""
        self.assertTrue(callable(self.web._downloads_start))


if __name__ == "__main__":
    unittest.main()
