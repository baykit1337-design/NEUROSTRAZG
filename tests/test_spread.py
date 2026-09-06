"""Сроки по весу ответа и адреса по книгам.

Две беды из одного журнала. Три книги очереди качались «через прокси
31.58.9.4» — все три через один и тот же адрес, потому что каждая брала у
пула `current()`. Список из десяти адресов при этом простаивал.

И срок ожидания стоял один на всё: те же две минуты у страницы главы в
220 КБ и у оглавления — JSON на несколько килобайт, который приходит за
секунду или не приходит вовсе. Молчащий адрес обходился поэтому в три
попытки по две минуты: шесть минут тишины на пустом месте.

Третье оттуда же: отвалившийся адрес лежал отключённым до перезапуска
программы. Очередь из тринадцати книг успевала похоронить весь список, и
кончалось это неправдой «рабочих прокси не осталось».
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import api  # noqa: E402
from mvl import client as client_mod  # noqa: E402
from mvl import proxies as proxies_mod  # noqa: E402
from mvl.client import Client  # noqa: E402
from mvl.downloader import Downloader  # noqa: E402
from mvl.proxies import NoProxiesLeft, Proxy, ProxyPool  # noqa: E402


class TestHowLongWeWait(unittest.TestCase):
    """Лёгкому ответу — лёгкий срок."""

    def sent(self, client, call):
        """С каким сроком ушёл запрос."""
        seen = []

        class Session:
            def get(self, url, **rest):
                seen.append(rest.get("timeout"))
                return client_mod._UrllibResponse(200, b"{}")

        client._session = lambda: Session()
        call(client)
        return seen[0]

    def test_a_chapter_page_keeps_the_long_wait(self):
        """220 КБ на медленном канале двух минут стоят: при тридцати
        секундах ответ обрывался на двадцати двух килобайтах."""
        client = Client(timeout=120)
        self.assertEqual(self.sent(client, lambda c: c.get("https://x/y"))[1],
                         120)

    def test_a_light_answer_gets_a_short_wait(self):
        client = Client(timeout=120)
        waited = self.sent(client, lambda c: c.get_json("https://x/y"))
        self.assertEqual(waited[1], client_mod.LIGHT_TIMEOUT)

    def test_the_short_wait_is_really_shorter(self):
        """Иначе вся правка — переименование."""
        self.assertLess(client_mod.LIGHT_TIMEOUT, client_mod.TIMEOUT)

    def test_a_lowered_read_timeout_wins(self):
        """Человек снизил чтение до двадцати секунд — значит и лёгкий
        ответ ждём не дольше, а не «зато у нас своё число»."""
        client = Client(timeout=20)
        self.assertEqual(client.light_timeout, 20)

    def test_the_connect_wait_is_untouched(self):
        """Соединение либо ставится быстро, либо адрес недоступен."""
        client = Client(timeout=120, connect_timeout=15)
        waited = self.sent(client, lambda c: c.get_json("https://x/y"))
        self.assertEqual(waited[0], 15)


class Source:
    key = "fake"
    name = "Подставной"
    needs_proxy = False
    cancel = None
    timeouts: dict = {}

    def toc(self, client, novel, first=1, last=None, on_progress=None):
        return api.Toc(chapters=[], missing=[])

    def chapter(self, client, chapter):
        return "Глава", "Текст."


class TestEveryBookItsOwnAddress(unittest.TestCase):
    """Три книги на одном адресе — это один адрес, а не три."""

    def pool(self, count=3):
        rows = [Proxy(host=f"10.0.0.{n}", port=8000 + n) for n in range(count)]
        for one in rows:
            one.alive, one.status = True, 200
        return ProxyPool(rows)

    def test_a_book_keeps_the_address_it_was_given(self):
        pool = self.pool()
        mine = pool.proxies[2]
        loader = Downloader(source=Source(), pool=pool, threads=1,
                            probe=False, proxy=mine)
        self.assertIs(loader._my_proxy(), mine)

    def test_without_one_it_takes_the_common_current(self):
        """Замер и проверки зовут качалку без раздачи — им как было."""
        pool = self.pool()
        loader = Downloader(source=Source(), pool=pool, threads=1, probe=False)
        self.assertIs(loader._my_proxy(), pool.current())

    def test_a_dead_address_is_not_held_on_to(self):
        """Сидеть на похороненном адресе значит качать в никуда."""
        pool = self.pool()
        mine = pool.proxies[2]
        loader = Downloader(source=Source(), pool=pool, threads=1,
                            probe=False, proxy=mine)
        mine.disabled = True
        self.assertIsNot(loader._my_proxy(), mine)

    def test_the_row_shows_this_book_and_not_the_queue(self):
        """«Через что качаем» у книги своё: общий `current` тут соврал бы
        про две книги из трёх."""
        pool = self.pool()
        loader = Downloader(source=Source(), pool=pool, threads=1,
                            probe=False, proxy=pool.proxies[2])
        self.assertEqual(loader._proxy_label(), pool.proxies[2].label)
        self.assertNotEqual(loader._proxy_label(), pool.current().label)

    def test_without_a_pool_there_is_no_address(self):
        loader = Downloader(source=Source(), threads=1, probe=False)
        self.assertIsNone(loader._my_proxy())


class TestAddressesComeBack(unittest.TestCase):
    """Отвалившийся адрес — не покойник, а отдыхающий."""

    def pool(self, count=2):
        rows = [Proxy(host=f"10.0.0.{n}", port=8000 + n) for n in range(count)]
        for one in rows:
            one.alive, one.status = True, 200
        return ProxyPool(rows)

    def test_a_rested_address_returns(self):
        pool = self.pool()
        for one in pool.proxies:
            one.disabled = True
            one.disabled_at = 1.0            # давно
        self.assertEqual(pool.revive(after=0), 2)
        self.assertFalse(pool.proxies[0].disabled)

    def test_a_freshly_dropped_one_stays_out(self):
        """Иначе мёртвый адрес брали бы на каждой главе заново."""
        pool = self.pool()
        pool.switch("не ответил")
        self.assertEqual(pool.revive(after=proxies_mod.REVIVE_AFTER), 0)

    def test_the_pool_does_not_die_while_addresses_rest(self):
        """Та самая неправда: «рабочих прокси не осталось» при живом
        списке. Все отдыхают — значит пора будить, а не сдаваться."""
        pool = self.pool()
        for one in pool.proxies:
            one.disabled = True
            one.disabled_at = 1.0
        self.assertIsNotNone(pool.current())

    def test_a_pool_that_never_worked_still_gives_up(self):
        """Адреса, отключённые без отметки времени, не воскресают: они не
        отдыхают, а негодны — и врать про них нельзя."""
        pool = self.pool()
        for one in pool.proxies:
            one.disabled = True
        with self.assertRaises(NoProxiesLeft):
            pool.current()

    def test_dropping_notes_the_time(self):
        """Без отметки некому решить, отдохнул адрес или нет."""
        pool = self.pool()
        pool.switch("не ответил")
        self.assertTrue(pool.proxies[0].disabled_at)


if __name__ == "__main__":
    unittest.main()
