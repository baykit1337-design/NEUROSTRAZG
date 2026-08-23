"""Какие ответы сайта клиент считает удачей.

Успехом считалась ровно двухсотка, и на этом рейтинг Цидяня встал
намертво: его защита отдаёт страницу с кодом 202 «принято» — так она
отвечает всем, кто не похож на браузер, и посреднику, и прямому ходу.
Тело при этом приходит целым. Мы же сверяли код с 200, ответ
выбрасывали не глядя, и на экране висело «сайт не ответил: HTTP 202» —
хотя сайт как раз ответил.

Проверки ниже держат обе стороны: весь второй десяток проходит, а
отказы, запреты и «страницы нет» по-прежнему остаются отказами.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.client import Blocked, Client, HttpError  # noqa: E402


class Reply:
    """Ответ сайта — столько, сколько от него смотрит клиент."""

    def __init__(self, status: int, body: str = "", headers: dict | None = None):
        self.status_code = status
        self.text = body
        self.content = body.encode("utf-8")
        self.headers = headers or {}


class Session:
    """Сессия, отдающая заготовленные ответы по очереди."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.asked: list[str] = []

    def get(self, url, **kwargs):
        self.asked.append(url)
        return self.replies[min(len(self.asked), len(self.replies)) - 1]

    def close(self):
        pass


def client_with(*replies, **kwargs):
    """Клиент, у которого вместо сети — заготовки."""
    session = Session(*replies)
    client = Client(max_attempts=kwargs.pop("max_attempts", 1), **kwargs)
    client._session = lambda: session
    return client, session


PAGE = "<html><body><div class='rank-body'>книги</div></body></html>"


class TestSuccessIsTheWholeSecondTen(unittest.TestCase):

    def test_a_plain_two_hundred_still_works(self):
        client, _ = client_with(Reply(200, PAGE))
        self.assertEqual(client.get_text("https://x/rank/"), PAGE)

    def test_two_hundred_and_two_brings_the_page_through(self):
        """Так отвечает защита Цидяня. Страница при этом целая."""
        client, _ = client_with(Reply(202, PAGE))
        self.assertEqual(client.get_text("https://x/rank/"), PAGE)

    def test_an_empty_body_is_the_parsers_business_not_ours(self):
        """204 «нет содержимого» — тоже удача по мерке HTTP. Годится ли
        такая страница, решает разбор: у него есть чем объяснить пустоту,
        а у клиента — нечем."""
        client, _ = client_with(Reply(204, ""))
        self.assertEqual(client.get_text("https://x/rank/"), "")

    def test_the_answer_is_taken_the_first_time(self):
        """Успех не повод для второго захода."""
        client, session = client_with(Reply(202, PAGE))
        client.get_text("https://x/rank/")
        self.assertEqual(len(session.asked), 1)


class TestRefusalsStayRefusals(unittest.TestCase):
    """Послабление одностороннее: отказы им не задеты."""

    def test_a_closed_door_is_still_closed(self):
        client, _ = client_with(Reply(403, "нельзя"))
        with self.assertRaises(HttpError) as caught:
            client.get_text("https://x/rank/")
        self.assertIn("403", str(caught.exception))

    def test_a_site_that_counts_403_as_a_ban_still_says_so(self):
        """Некоторые источники объявляют 403 запретом отдельно — тогда
        и беда у них своя, чтобы качалка знала: адрес сменить, а не
        повторять."""
        client, _ = client_with(Reply(403, "нельзя"))
        client.block_statuses = frozenset({403})
        with self.assertRaises(Blocked):
            client.get_text("https://x/rank/")

    def test_a_missing_page_is_still_missing(self):
        client, _ = client_with(Reply(404, "нет такой"))
        with self.assertRaises(HttpError):
            client.get_text("https://x/rank/")

    def test_a_page_that_is_not_there_is_not_asked_for_twice(self):
        """Ретраить 404 бессмысленно — страницы просто нет."""
        client, session = client_with(Reply(404, ""), max_attempts=3)
        with self.assertRaises(HttpError):
            client.get_text("https://x/rank/")
        self.assertEqual(len(session.asked), 1)

    def test_a_sick_server_is_still_a_failure(self):
        client, _ = client_with(Reply(500, "ой"))
        with self.assertRaises(HttpError):
            client.get_text("https://x/rank/")

    def test_a_redirect_is_not_success(self):
        """Третий десяток — это «иди в другое место», а не ответ."""
        client, _ = client_with(Reply(301, ""))
        with self.assertRaises(HttpError):
            client.get_text("https://x/rank/")


class TestATruncatedAnswerIsStillTruncated(unittest.TestCase):

    def test_a_short_body_is_not_taken_as_a_page(self):
        """Заголовок обещал больше, чем пришло: соединение оборвалось.
        Проверка эта работала на двухсотке — должна и на прочих."""
        client, _ = client_with(
            Reply(202, "мало", {"Content-Length": "100000"}))
        with self.assertRaises(HttpError):
            client.get_text("https://x/rank/")


if __name__ == "__main__":
    unittest.main()
