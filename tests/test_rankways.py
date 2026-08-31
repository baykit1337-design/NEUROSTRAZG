"""Рейтинг: способов дойти до сайта несколько, и пробуются они по очереди.

Способ был один — первый пригодный посредник. Не понравился он сайту, и
рейтинг не приходил вовсе, хотя рядом лежали ещё адреса и открытый
прямой ход. Снаружи это выглядело как «нажал обновить — 502», и по
такому сообщению нечего было чинить: мёртвый посредник, запрет по
адресу и съехавшая разметка выглядели одинаково.

Здесь закрепляется поведение, а не порядок способов и не их число: их
будут крутить. Закрепляется, что после неудачи берётся следующий, что
удача останавливает перебор, что клиент закрывается в любом случае и
что пароль посредника в отчёт не попадает.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.client import HttpError  # noqa: E402
from mvl.proxies import Proxy  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402
from webapp import app as web  # noqa: E402


class Fake:
    """Клиент, который помнит, что его закрыли."""

    def __init__(self, name=""):
        self.name = name
        self.closed = False

    def close(self):
        self.closed = True


class Ways(unittest.TestCase):
    """Общая обвязка: подменяем список способов своим."""

    def setUp(self):
        self.was = web._rank_ways
        self.made: list[Fake] = []

    def tearDown(self):
        web._rank_ways = self.was

    def ways(self, *names):
        def make(name):
            def build():
                client = Fake(name)
                self.made.append(client)
                return client
            return build

        web._rank_ways = lambda: [(name, make(name)) for name in names]


class TestItTriesUntilItWorks(Ways):

    def test_the_first_way_that_works_ends_the_search(self):
        self.ways("первый", "второй", "третий")
        found, tried = web._rank_run(lambda client: {"rows": [client.name]})
        self.assertEqual(found["rows"], ["первый"])
        self.assertEqual(tried, [])
        self.assertEqual(len(self.made), 1)

    def test_a_refusal_hands_over_to_the_next_way(self):
        self.ways("первый", "второй")

        def snap(client):
            if client.name == "первый":
                raise HttpError("HTTP 403 — доступ закрыт")
            return {"rows": [client.name]}

        found, tried = web._rank_run(snap)
        self.assertEqual(found["rows"], ["второй"])
        self.assertEqual(len(tried), 1)
        self.assertIn("первый", tried[0])

    def test_a_site_that_changed_its_markup_is_also_worth_another_way(self):
        """Разметка от посредника не зависит, но отличить «сайт сменил
        вёрстку» от «этот посредник получил заглушку» можно только
        попробовав другим: заглушку показывают не всем."""
        self.ways("первый", "второй")

        def snap(client):
            if client.name == "первый":
                raise SourceBroken("книг не нашлось")
            return {"rows": [client.name]}

        found, _ = web._rank_run(snap)
        self.assertEqual(found["rows"], ["второй"])

    def test_when_nothing_works_every_attempt_is_in_the_report(self):
        self.ways("первый", "второй", "третий")

        def snap(client):
            raise HttpError(f"беда у «{client.name}»")

        with self.assertRaises(web.RankUnreachable) as caught:
            web._rank_run(snap)
        said = caught.exception.report()
        for name in ("первый", "второй", "третий"):
            self.assertIn(name, said)
        self.assertEqual(len(caught.exception.tried), 3)

    def test_the_client_is_closed_whether_it_worked_or_not(self):
        self.ways("первый", "второй")

        def snap(client):
            if client.name == "первый":
                raise HttpError("не вышло")
            return {"rows": []}

        web._rank_run(snap)
        self.assertTrue(all(client.closed for client in self.made))

    def test_a_wrong_board_is_not_worth_retrying(self):
        """Неверная доска не лечится сменой посредника: спрашивать
        второй раз то же самое — только тянуть время."""
        self.ways("первый", "второй")

        def snap(client):
            raise ValueError("Неизвестная доска рейтинга")

        with self.assertRaises(ValueError):
            web._rank_run(snap)
        self.assertEqual(len(self.made), 1)

    def test_the_details_of_the_first_trouble_survive(self):
        """У разбора Фанкью беда приходит с подробностями, и интерфейс
        показывает их отдельно. Перебор способов не должен их терять."""
        from net.sources.rank import Diagnosis

        self.ways("первый", "второй")

        def snap(client):
            raise Diagnosis("разметка не та", {"page_size": 17})

        with self.assertRaises(web.RankUnreachable) as caught:
            web._rank_run(snap)
        self.assertEqual(getattr(caught.exception.first, "details", None),
                         {"page_size": 17})


class TestTheWaysThemselves(unittest.TestCase):
    """Из чего складывается список способов."""

    def setUp(self):
        self.was = web.POOL

    def tearDown(self):
        web.POOL = self.was

    def pool(self, *proxies):
        class Pool:
            def __init__(self, found):
                self.proxies = list(found)

        web.POOL = Pool(proxies)

    def proxy(self, host, secret=""):
        return Proxy(host=host, port=8000, username="вася" if secret else "",
                     password=secret, alive=True, status=200)

    def test_the_direct_way_comes_after_the_proxies(self):
        self.pool(self.proxy("1.1.1.1"), self.proxy("2.2.2.2"))
        names = [name for name, _ in web._rank_ways()]
        self.assertIn("напрямую", names[-1])
        self.assertGreater(len(names), 1)

    def test_without_proxies_there_is_still_a_way(self):
        self.pool()
        names = [name for name, _ in web._rank_ways()]
        self.assertTrue(names)
        self.assertIn("напрямую", names[0])

    def test_the_password_of_a_proxy_never_shows_up(self):
        """Репозиторий открытый, и логи туда попадают вместе с отчётами."""
        self.pool(self.proxy("1.1.1.1", secret="очень-секретно"))
        names = [name for name, _ in web._rank_ways()]
        self.assertNotIn("очень-секретно", " ".join(names))
        self.assertIn("1.1.1.1", " ".join(names))



class TestThroughTheHandler(unittest.TestCase):
    """Перебор должен работать и через кнопку, а не только сам по себе.

    Проверка ходит настоящей ручкой: между `_rank_run` и ответом лежит
    сохранение среза, и однажды оно уже ломалось молча.
    """

    def setUp(self):
        import tempfile

        from ops import rank as rank_op

        self.rank_op = rank_op
        self.tmp = tempfile.TemporaryDirectory()
        self.was_dir = rank_op.RANK_DIR
        rank_op.RANK_DIR = Path(self.tmp.name)

        self.was_ways = web._rank_ways
        web.app.config["TESTING"] = True
        self.http = web.app.test_client()

    def tearDown(self):
        web._rank_ways = self.was_ways
        self.rank_op.RANK_DIR = self.was_dir
        self.tmp.cleanup()

    def ways(self, pages):
        """Способы, каждый со своим ответом: строка — страница, иначе беда."""

        class Client:
            def __init__(self, answer):
                self.answer = answer

            def get_text(self, url, **kwargs):
                if isinstance(self.answer, Exception):
                    raise self.answer
                return self.answer

            def get(self, url, *args, **kwargs):
                raise HttpError("шрифт не отдался")

            def close(self):
                pass

        web._rank_ways = lambda: [
            (f"способ {number}", lambda answer=answer: Client(answer))
            for number, answer in enumerate(pages, 1)]

    def refresh(self):
        return self.http.post("/api/rank/refresh",
                              json={"site": "qidian", "board": "yuepiao"})

    def test_a_dead_first_way_does_not_sink_the_whole_refresh(self):
        from tests.test_qidianrank import RANK2

        self.ways([HttpError("HTTP 403 — доступ закрыт"), RANK2])
        answer = self.refresh()
        self.assertEqual(answer.status_code, 200)
        body = answer.get_json()
        self.assertEqual(body["saved"], 2)
        self.assertEqual(len(body["tried"]), 1)

    def test_when_every_way_fails_the_answer_names_them_all(self):
        self.ways([HttpError("посредник молчит"),
                   HttpError("HTTP 403 — доступ закрыт")])
        answer = self.refresh()
        self.assertEqual(answer.status_code, 502)
        body = answer.get_json()
        self.assertIn("способ 1", body["error"])
        self.assertIn("способ 2", body["error"])
        self.assertEqual(len(body["details"]["tried"]), 2)


if __name__ == "__main__":
    unittest.main()


class TestTheStumbledPageIsKeptForRepair(Ways):
    """Страница, на которой споткнулся разбор, сохраняется и называется.

    Разбор чинится по странице, а не по сообщению о ней. К моменту
    разбора жалобы ответ давно выброшен, и просить человека поймать тот
    же случай ещё раз — значит ждать неделю.
    """

    def setUp(self):
        super().setUp()
        from tempfile import TemporaryDirectory

        from ops import logbook

        self.logbook = logbook
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._was = logbook.PAGE_DIR
        logbook.PAGE_DIR = Path(self._dir.name) / "pages"
        self.addCleanup(lambda: setattr(logbook, "PAGE_DIR", self._was))

    def broken(self, page=""):
        def run(client):
            raise SourceBroken("разбор не нашёл книг", page=page)
        return run

    def test_the_page_reaches_a_file(self):
        self.ways("первый", "второй")
        with self.assertRaises(web.RankUnreachable):
            web._rank_run(self.broken("<html>то, что пришло</html>"))
        saved = list(self.logbook.PAGE_DIR.glob("*.html"))
        self.assertEqual(len(saved), 1)
        self.assertIn("то, что пришло",
                      saved[0].read_text(encoding="utf-8"))

    def test_the_report_names_the_file(self):
        """Иначе человек не знает, что прислать, и файл лежит зря."""
        self.ways("первый", "второй")
        with self.assertRaises(web.RankUnreachable) as caught:
            web._rank_run(self.broken("<html>то, что пришло</html>"))
        saved = list(self.logbook.PAGE_DIR.glob("*.html"))
        self.assertIn(saved[0].name, " ".join(caught.exception.tried))

    def test_only_one_copy_for_all_the_ways(self):
        """Каждый способ принесёт ту же страницу — хранить её надо однажды."""
        self.ways("первый", "второй", "третий", "четвёртый")
        with self.assertRaises(web.RankUnreachable):
            web._rank_run(self.broken("<html>то же самое</html>"))
        self.assertEqual(len(list(self.logbook.PAGE_DIR.glob("*.html"))), 1)

    def test_a_refusal_without_a_page_saves_nothing(self):
        """Сетевой отказ страницы не приносит — и пустых файлов не плодит."""
        self.ways("первый", "второй")
        with self.assertRaises(web.RankUnreachable):
            web._rank_run(self.broken(""))
        self.assertFalse(list(self.logbook.PAGE_DIR.glob("*.html"))
                         if self.logbook.PAGE_DIR.exists() else [])

    def test_a_password_never_reaches_the_saved_page(self):
        self.ways("первый",)
        with self.assertRaises(web.RankUnreachable):
            web._rank_run(self.broken(
                "<a href='http://user:s3cret@1.2.3.4:6095/'>x</a>"))
        saved = list(self.logbook.PAGE_DIR.glob("*.html"))
        self.assertNotIn("s3cret", saved[0].read_text(encoding="utf-8"))
