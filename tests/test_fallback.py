"""Запасной заход: напрямую не вышло — идём через посредника.

Интернет не нужен. Источник и клиент подставляются, список адресов —
обычный объект с полем `proxies`, как его и читает отбор.

Беда, ради которой всё это писалось, была тихая: человек проверял пять
адресов, все пять проходили, а книга падала на первом же мёртвом —
«после 1 попыток», — и четыре проверенных стояли рядом без дела.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.client import HttpError, NetworkError, explain  # noqa: E402
from webapp import app as web  # noqa: E402


def pool_of(count: int):
    """Проверенный список: столько-то адресов, порядок — как задан."""
    return SimpleNamespace(checked=True, proxies=[
        SimpleNamespace(url=f"http://{n}.{n}.{n}.{n}:8080", usable=True,
                        disabled=False, elapsed=n)
        for n in range(1, count + 1)])


class Source:
    """Источник, который открывается только с определённого адреса."""

    name = "Проба"
    key = "проба"

    def __init__(self, opens_at: str | None = None):
        self.opens_at = opens_at
        self.asked: list[str] = []

    def find(self, client, query):
        where = getattr(client, "proxy_url", None)
        self.asked.append(where)
        if self.opens_at is not None and where == self.opens_at:
            return SimpleNamespace(name="Книга", slug="kniga")
        raise NetworkError(f"через {where} не вышло")


class Client:
    """Клиент, который только помнит адрес и умеет закрываться."""

    made: list = []

    def __init__(self, proxy_url=None, **kw):
        self.proxy_url = proxy_url
        self.closed = False
        Client.made.append(self)

    def close(self):
        self.closed = True


class FallbackTestCase(unittest.TestCase):

    def setUp(self):
        Client.made = []
        was = web.Client
        web.Client = Client
        self.addCleanup(setattr, web, "Client", was)

    def with_pool(self, pool):
        was = web.POOL
        web.POOL = pool
        self.addCleanup(setattr, web, "POOL", was)

    def go(self, source, pool, trouble=None):
        self.with_pool(pool)
        return web._find_via_proxy(source, "запрос",
                                   trouble or NetworkError("напрямую никак"))


class TestItWalksTheListInsteadOfStoppingAtTheFirst(FallbackTestCase):

    def test_a_dead_first_address_does_not_end_the_search(self):
        """Ровно та беда: первый адрес мёртв, а рядом четыре живых."""
        source = Source(opens_at="http://3.3.3.3:8080")
        novel, said = self.go(source, pool_of(5))

        self.assertIsNotNone(novel)
        self.assertEqual(said, "")
        self.assertEqual(source.asked, ["http://1.1.1.1:8080",
                                        "http://2.2.2.2:8080",
                                        "http://3.3.3.3:8080"])

    def test_it_stops_at_the_first_address_that_works(self):
        """Обойти весь список, когда книга уже нашлась, значит подарить
        ожидание ни за что."""
        source = Source(opens_at="http://1.1.1.1:8080")
        novel, _ = self.go(source, pool_of(5))

        self.assertIsNotNone(novel)
        self.assertEqual(len(source.asked), 1)

    def test_every_client_is_closed_behind_it(self):
        """Обход списка без этого протекает ровно во столько раз
        сильнее, во сколько адресов в списке."""
        self.go(Source(), pool_of(3))

        self.assertTrue(Client.made, "клиента не создавали")
        self.assertTrue(all(one.closed for one in Client.made))

    def test_there_is_a_ceiling_on_how_long_it_digs(self):
        """Живой и медленный адрес съедает ожидание соединения целиком, и
        без потолка сотня адресов означала бы полчаса на книгу."""
        source = Source()
        self.go(source, pool_of(20))

        self.assertEqual(len(source.asked), web.PROXIES_TO_TRY)


class TestWhatItSaysWhenNothingWorked(FallbackTestCase):

    def test_it_says_how_many_addresses_were_tried(self):
        """Иначе «тоже не вышло» про один адрес и про пять выглядит
        одинаково, и не понять, обошли ли список вообще."""
        _, said = self.go(Source(), pool_of(4))

        # Спрашиваем со словом, а не одну цифру: цифра есть и в самом
        # адресе, и проверка проходила бы, даже не пиши мы счёт вовсе.
        self.assertIn("пробовали: 4", said)

    def test_a_single_address_is_not_called_a_round(self):
        """Список из одного адреса обошли весь — считать там нечего."""
        _, said = self.go(Source(), pool_of(1))

        self.assertNotIn("Всего адресов", said)

    def test_it_names_the_last_address_without_the_password(self):
        pool = SimpleNamespace(checked=True, proxies=[
            SimpleNamespace(url="http://вася:тайна@9.9.9.9:8080",
                            usable=True, disabled=False, elapsed=1)])
        _, said = self.go(Source(), pool)

        self.assertIn("9.9.9.9:8080", said)
        self.assertNotIn("тайна", said)

    def test_an_empty_list_says_so_instead_of_staying_silent(self):
        _, said = self.go(Source(), SimpleNamespace(checked=True, proxies=[]))

        self.assertIn("живых адресов нет", said)

    def test_trouble_a_new_route_cannot_fix_is_not_carried_around(self):
        """«Страницы нет» — не «не дошли»: другой выход её не создаст, а
        обход списка стоил бы ожидания на ровном месте."""
        source = Source()
        novel, said = self.go(source, pool_of(3),
                              trouble=HttpError("404: страницы нет"))

        self.assertIsNone(novel)
        self.assertEqual(said, "")
        self.assertEqual(source.asked, [])


class TestTheDnsFailureIsPutIntoWords(unittest.TestCase):
    """«Could not resolve host» не отвечает на вопрос, который человек и
    задаёт: почему по ссылке он переходит, а программа нет."""

    def test_it_names_the_host_the_computer_could_not_resolve(self):
        said = explain("curl: (6) Could not resolve host: "
                       "chap.heliosarchive.online. See https://curl.se/")

        self.assertIn("chap.heliosarchive.online", said)

    def test_the_full_stop_does_not_stick_to_the_host(self):
        """С точкой предложения на конце имя выглядит как опечатка в самом
        имени, и человек лезет искать её у себя."""
        said = explain("Could not resolve host: chap.heliosarchive.online.")

        # Своя точка у предложения есть и должна остаться одна: две подряд
        # и значат, что имя утащило чужую.
        self.assertNotIn("online..", said)
        self.assertIn("chap.heliosarchive.online", said)

    def test_it_says_the_browser_proves_nothing_about_this_host(self):
        """Это и есть ответ на «я же могу перейти по ссылке»."""
        said = explain("Could not resolve host: chap.heliosarchive.online")

        self.assertIn("браузере", said)

    def test_other_troubles_get_no_word_of_their_own(self):
        """Приписывать одно и то же к любой ошибке значит обесценить
        приписку."""
        self.assertEqual(explain("Failed to connect to 1.2.3.4 port 8080"), "")
        self.assertEqual(explain("403: доступ закрыт"), "")


if __name__ == "__main__":
    unittest.main()
