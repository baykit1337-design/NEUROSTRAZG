"""Пускать только свою страницу.

Сервер локальный, но «локальный» браузер не считает поводом кому-то
отказывать: запрос на 127.0.0.1 может отправить любая открытая вкладка,
а сайт, чей домен указывает на 127.0.0.1, для браузера ещё и тот же
источник — ему видны ответы. Здесь проверяется, что чужое имя и чужой
источник до маршрутов не доходят.
"""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webapp.app import ALLOWED_NAMES, HOME_NAMES, app, open_to  # noqa: E402


class TestOwnPageOnly(unittest.TestCase):
    """Свои запросы проходят, чужие — нет."""

    def setUp(self):
        self.was = set(ALLOWED_NAMES)
        self.app = app.test_client()

    def tearDown(self):
        ALLOWED_NAMES.clear()
        ALLOWED_NAMES.update(self.was)

    def test_our_own_page_gets_through(self):
        answer = self.app.get("/api/about", headers={"Host": "127.0.0.1:8765"})
        self.assertEqual(answer.status_code, 200)

    def test_localhost_is_the_same_program(self):
        answer = self.app.get("/api/about", headers={"Host": "localhost:8765"})
        self.assertEqual(answer.status_code, 200)

    def test_a_foreign_name_pointing_at_us_is_turned_away(self):
        """Подмена DNS: домен чужой, адрес наш."""
        answer = self.app.get("/api/about", headers={"Host": "evil.example:8765"})
        self.assertEqual(answer.status_code, 403)

    def test_a_page_from_another_site_is_turned_away(self):
        answer = self.app.get(
            "/api/about",
            headers={"Host": "127.0.0.1:8765", "Origin": "http://evil.example"})
        self.assertEqual(answer.status_code, 403)

    def test_our_own_origin_is_fine(self):
        answer = self.app.get(
            "/api/about",
            headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"})
        self.assertEqual(answer.status_code, 200)

    def test_a_write_route_is_guarded_too(self):
        """Проверка стоит до маршрутов, а не только на чтении."""
        answer = self.app.post("/api/history/undo",
                               json={}, headers={"Host": "evil.example"})
        self.assertEqual(answer.status_code, 403)

    def test_the_refusal_says_where_to_go(self):
        answer = self.app.get("/api/about", headers={"Host": "evil.example"})
        self.assertIn("127.0.0.1", answer.get_json()["error"])


class TestNames(unittest.TestCase):
    """Разбор заголовка `Host` и настройка под адрес запуска."""

    def setUp(self):
        self.was = set(ALLOWED_NAMES)

    def tearDown(self):
        ALLOWED_NAMES.clear()
        ALLOWED_NAMES.update(self.was)

    def test_a_home_address_keeps_the_check(self):
        open_to("127.0.0.1")
        self.assertEqual(ALLOWED_NAMES, set(HOME_NAMES))

    def test_going_outside_lifts_the_check(self):
        """Наружу ходят по адресу сети — имя у каждого своё."""
        open_to("0.0.0.0")
        self.assertFalse(ALLOWED_NAMES)

    def test_with_the_check_lifted_anyone_gets_through(self):
        open_to("0.0.0.0")
        answer = app.test_client().get("/api/about",
                                       headers={"Host": "192.168.1.5:8765"})
        self.assertEqual(answer.status_code, 200)

    def test_the_sixth_version_of_the_address_is_ours(self):
        answer = app.test_client().get("/api/about", headers={"Host": "[::1]:8765"})
        self.assertEqual(answer.status_code, 200)


if __name__ == "__main__":
    unittest.main()
