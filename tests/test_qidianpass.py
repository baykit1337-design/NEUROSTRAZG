"""Пропуск Цидяня: кука `w_tsfp`.

Цидянь отвечал заглушкой на две сотни байт всем подряд — и через
китайский прокси, и напрямую, и с самыми браузерными заголовками. Значит,
дело было не в адресе выхода и не в заголовках: без куки `w_tsfp` защита
не пускает никого. Кука считается из адреса, времени и отпечатка гостя;
проверки ниже держат её сборку и то, что рейтинг её действительно носит.

Проверить это на живом сайте отсюда нечем — из песочницы Цидянь
недоступен. Поэтому здесь проверяется не «сайт пустил», а «пропуск собран
по правилу»: подпись пересчитывается заново и сверяется, а не сравнивается
с записанной строкой — записанная строка проверяла бы только саму себя.
"""

from __future__ import annotations

import base64
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from net.sources import qidianpass as qp  # noqa: E402
from net.sources import qidianrank as qd  # noqa: E402

from test_qidianrank import RANK2, Fake  # noqa: E402

ADDRESS = "https://www.qidian.com/rank/yuepiao/chn21/"


def signed(token: str) -> dict:
    """Что внутри пропуска."""
    return qp.unpack(token)


class TestTheCipher(unittest.TestCase):

    def test_what_is_scrambled_unscrambles_back(self):
        data = "рейтинг 月票榜".encode("utf-8")
        self.assertEqual(qp.cipher(qp.cipher(data)), data)

    def test_scrambling_actually_changes_the_bytes(self):
        data = b"x" * 64
        self.assertNotEqual(qp.cipher(data), data)

    def test_another_key_gives_another_result(self):
        data = "одно и то же".encode("utf-8")
        self.assertNotEqual(qp.cipher(data), qp.cipher(data, b"another key"))


class TestWhatIsInsideThePass(unittest.TestCase):

    def setUp(self):
        self.keeper = qp.Pass()
        self.inside = signed(self.keeper.token(ADDRESS))

    def test_the_pass_can_be_read_back(self):
        """Иначе сверять нечего: пропуск был бы просто набором букв."""
        self.assertTrue(self.inside)

    def test_it_carries_a_fingerprint_a_mark_a_time_and_a_signature(self):
        for field in ("fingerprint", "abnormal", "loadts", "timestamp",
                      "checksum"):
            self.assertIn(field, self.inside, field)

    def test_the_signature_is_the_address_the_time_and_the_fingerprint(self):
        """Это и привязывает пропуск к странице: подпись, снятая с
        другого адреса, здесь не годится."""
        comb = (f"{ADDRESS}{self.inside['loadts']}"
                f"{self.inside['fingerprint']}")
        self.assertEqual(self.inside["checksum"],
                         hashlib.md5(comb.encode()).hexdigest())

    def test_the_page_was_loading_for_a_believable_while(self):
        """Мгновенная загрузка у всех наших запросов выглядела бы как
        раз машинно. Разброс должен быть, и в пределах секунды."""
        spent = self.inside["timestamp"] - self.inside["loadts"]
        self.assertGreater(spent, 0)
        self.assertLessEqual(spent, 1000)

    def test_a_guest_with_no_history_has_no_black_marks(self):
        self.assertEqual(set(self.inside["abnormal"]), {"0"})

    def test_the_time_is_now_and_not_some_stored_moment(self):
        import time
        self.assertLess(abs(self.inside["loadts"] - int(time.time() * 1000)),
                        60_000)


class TestOnePassPerAddress(unittest.TestCase):

    def test_another_address_gets_another_signature(self):
        keeper = qp.Pass()
        one = signed(keeper.token(ADDRESS))
        two = signed(keeper.token(ADDRESS + "?page=2"))
        self.assertNotEqual(one["checksum"], two["checksum"])

    def test_the_guest_stays_the_same_guest(self):
        """Отпечаток, который скачет от страницы к странице, защите как
        раз и подозрителен: браузер его не перевыдумывает."""
        keeper = qp.Pass()
        one = signed(keeper.token(ADDRESS))
        two = signed(keeper.token(ADDRESS + "?page=2"))
        self.assertEqual(one["fingerprint"], two["fingerprint"])

    def test_two_guests_are_two_different_guests(self):
        self.assertNotEqual(qp.Pass().fingerprint, qp.Pass().fingerprint)

    def test_a_fingerprint_looks_like_a_fingerprint(self):
        made = qp.Pass().fingerprint
        self.assertEqual(len(made), 32)
        int(made, 16)  # шестнадцатеричное — иначе бы упало


class TestTheCookie(unittest.TestCase):

    def test_the_pass_travels_under_its_own_name(self):
        self.assertIn("w_tsfp", qp.Pass().cookies(ADDRESS))

    def test_the_cookie_holds_the_pass_itself(self):
        keeper = qp.Pass()
        value = keeper.cookies(ADDRESS)["w_tsfp"]
        self.assertEqual(signed(value)["fingerprint"], keeper.fingerprint)

    def test_it_is_a_cookie_and_not_a_header_written_by_hand(self):
        """Заголовок `Cookie`, поставленный руками, не заменяет тот, что
        складывает curl из своей банки, — он к нему добавляется. Сайт
        получил бы две строки `Cookie`, и первой ушла бы кука, которую он
        сам выдал вместе с заглушкой."""
        self.assertNotIn("Cookie", qp.Pass().cookies(ADDRESS))


class TestTheOtherFormOfTheSignature(unittest.TestCase):
    """Что защита кладёт в подпись — адрес целиком или один путь — мы
    знаем не наверняка, живьём проверить отсюда нечем. Поэтому форм две,
    и вторая должна быть именно другой, а гость — тем же."""

    def test_the_other_form_signs_differently(self):
        keeper = qp.Pass()
        one = signed(keeper.token(ADDRESS))
        two = signed(keeper.other().token(ADDRESS))
        self.assertNotEqual(one["checksum"], two["checksum"])

    def test_the_other_form_keeps_the_same_guest(self):
        keeper = qp.Pass()
        self.assertEqual(keeper.other().fingerprint, keeper.fingerprint)

    def test_the_short_form_signs_the_path_alone(self):
        keeper = qp.Pass(whole=False)
        inside = signed(keeper.token(ADDRESS))
        comb = f"/rank/yuepiao/chn21/{inside['loadts']}{keeper.fingerprint}"
        self.assertEqual(inside["checksum"],
                         hashlib.md5(comb.encode()).hexdigest())

    def test_switching_twice_comes_back(self):
        keeper = qp.Pass()
        self.assertEqual(keeper.other().other().whole, keeper.whole)


class TestLearningFromTheSite(unittest.TestCase):
    """Свой отпечаток сайт присылает не всегда, но если прислал — носить
    надо его."""

    def test_the_fingerprint_comes_from_the_sites_own_cookie(self):
        theirs = qp.Pass()
        mine = qp.Pass()
        self.assertTrue(mine.learn(theirs.token(ADDRESS)))
        self.assertEqual(mine.fingerprint, theirs.fingerprint)

    def test_nonsense_is_not_learned(self):
        keeper = qp.Pass()
        was = keeper.fingerprint
        self.assertFalse(keeper.learn("это вообще не кука"))
        self.assertEqual(keeper.fingerprint, was)

    def test_an_empty_cookie_is_not_learned(self):
        keeper = qp.Pass()
        self.assertFalse(keeper.learn(""))

    def test_a_readable_cookie_without_a_fingerprint_is_not_learned(self):
        """Расшифровалось — ещё не значит, что там есть что брать."""
        empty = base64.b64encode(qp.cipher(b'{"loadts":1}')).decode()
        keeper = qp.Pass()
        was = keeper.fingerprint
        self.assertFalse(keeper.learn(empty))
        self.assertEqual(keeper.fingerprint, was)


class Watching(Fake):
    """Клиент, который помнит не только адреса, но и заголовки."""

    def __init__(self, page="", pages=None):
        super().__init__(page, pages=pages)
        self.sent: list[dict] = []
        self.jars: list[dict] = []

    def get_text(self, url, **kwargs):
        self.sent.append(kwargs.get("headers") or {})
        self.jars.append(kwargs.get("cookies") or {})
        return super().get_text(url, **kwargs)

    def passes(self) -> list[dict]:
        return [qp.unpack(jar["w_tsfp"]) for jar in self.jars
                if jar.get("w_tsfp")]


class TestTheRatingCarriesThePass(unittest.TestCase):

    def test_the_board_is_asked_for_with_a_pass(self):
        client = Watching(RANK2)
        qd.fetch(client)
        self.assertTrue(client.passes(), "рейтинг ушёл без пропуска")

    def test_the_pass_does_not_replace_the_browser_headers(self):
        """Пропуск добавляется к тому, с чем приходит живой читатель, а
        не вместо него."""
        client = Watching(RANK2)
        qd.fetch(client)
        self.assertIn("qidian.com", client.sent[0].get("Referer", ""))

    def test_the_book_page_carries_a_pass_too(self):
        """Страница книги стоит за той же защитой, что и рейтинг."""
        client = Watching("<html><body>книга</body></html>")
        qd.book(client, "1043294775")
        self.assertTrue(client.passes(), "страница книги ушла без пропуска")


class TestWhenThePassIsNotAccepted(unittest.TestCase):

    HEAD = ('<script src="/C2WF946J0/probev3.js"></script>'
            "<head><title>安全验证</title></head>")

    def guard_page(self):
        return ("<html>" + self.HEAD
                + "<body><div>请输入验证码</div></body></html>")

    def changed_page(self):
        return ("<html>" + self.HEAD
                + '<body><div class="rank-box"><div class="rank-nav-list">'
                + "</div><div class=\"rank-body\">новая вёрстка</div></div>"
                + "<i>" + "х" * 30_000 + "</i></body></html>")

    def test_a_stub_makes_the_second_form_of_the_signature_be_tried(self):
        """Одна форма подписи — это одна догадка. Не пустили — пробуем
        вторую, прежде чем объявлять сайт закрытым."""
        from net.sources.base import SourceBroken

        client = Watching(self.guard_page())
        with self.assertRaises(SourceBroken):
            qd.fetch(client, board="vipup")  # у этой доски мобильного зеркала нет
        self.assertGreaterEqual(len(client.passes()), 2)

    def test_the_second_try_is_the_same_guest(self):
        from net.sources.base import SourceBroken

        client = Watching(self.guard_page())
        with self.assertRaises(SourceBroken):
            qd.fetch(client, board="vipup")
        prints = {one["fingerprint"] for one in client.passes()}
        self.assertEqual(len(prints), 1)

    def test_a_real_page_is_not_asked_for_twice(self):
        """Пришла целая страница рейтинга — пропуск приняли. Что разбор
        не нашёл в ней книг, форма подписи не исправит."""
        from net.sources.base import SourceBroken

        client = Watching(self.changed_page())
        with self.assertRaises(SourceBroken):
            qd.fetch(client, board="vipup")
        self.assertEqual(len(client.passes()), 1)

    def test_the_complaint_says_the_pass_was_sent(self):
        """Иначе следующий читающий лог начнёт с того, что уже сделано."""
        from net.sources.base import SourceBroken

        with self.assertRaises(SourceBroken) as caught:
            qd.fetch(Watching(self.guard_page()), board="vipup")
        self.assertIn("w_tsfp", str(caught.exception))


class TestTheRealStub(unittest.TestCase):
    """Заглушка, снятая с живого ответа Цидяня, — все 209 байт.

    Раньше её узнавали по размеру: «меньше двадцати тысяч байт — значит,
    проверка». Догадка верная, но по ней нельзя сказать, **что** пришло.
    Теперь заглушка узнаётся дословно, и сообщение говорит прямо.
    """

    STUB = ('<!DOCTYPE html><html> <head> <meta charset="UTF-8"> <script> '
            'var buid = "fffffffffffffffffff" </script> <script '
            'src="/C2WF946J0/probe.js?v=vc1jasc"></script> </head> '
            "<body></body> </body> </html>")

    def complaint(self):
        from net.sources.base import SourceBroken

        with self.assertRaises(SourceBroken) as caught:
            qd.fetch(Watching(self.STUB), board="vipup")
        return str(caught.exception)

    def test_the_stub_is_named_for_what_it_is(self):
        self.assertIn("probe.js", self.complaint())

    def test_it_says_the_pass_was_offered_and_refused(self):
        self.assertIn("w_tsfp", self.complaint())

    def test_it_does_not_send_the_reader_hunting_for_another_proxy(self):
        """Заглушка приходит одинаково и через прокси, и напрямую —
        советовать сменить прокси значило бы гонять человека зря."""
        said = self.complaint().lower()
        self.assertIn("не в адресе выхода", said)

    def test_a_page_with_the_rating_frame_is_not_called_a_stub(self):
        """Зонд висит в шапке и совершенно рабочей страницы, поэтому по
        одному его адресу судить нельзя."""
        alive = ('<html><head><script src="/C2WF946J0/probe.js"></script>'
                 '</head><body><div class="rank-body">книги</div></body>'
                 "</html>")
        self.assertFalse(qd._guarded(alive))


class Noted:
    """Сессия, которая ничего не делает, но помнит, о чём её просили."""

    def __init__(self):
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append(kwargs)

        class Reply:
            status_code = 200
            text = "<html></html>"
            content = b"<html></html>"
            headers: dict = {}

        return Reply()

    def close(self):
        pass


class TestTheClientCarriesCookiesApart(unittest.TestCase):
    """Кука уходит кукой, а не строкой в заголовках.

    Заголовок `Cookie`, поставленный руками, curl не заменяет своим — он
    его **добавляет**, и сайт получает две строки `Cookie` подряд. Для
    Цидяня это и есть разница между «пропуск принят» и «не принят»: в
    банке лежит кука, которую он выдал вместе с заглушкой, и первой
    уходит она.
    """

    def client(self):
        from mvl.client import Client

        session = Noted()
        client = Client(max_attempts=1)
        client._session = lambda: session
        return client, session

    def test_a_cookie_is_asked_for_as_a_cookie(self):
        client, session = self.client()
        client.get_text("https://x/rank/", cookies={"w_tsfp": "пропуск"})
        self.assertEqual(session.calls[0].get("cookies"), {"w_tsfp": "пропуск"})

    def test_a_cookie_is_not_smuggled_into_the_headers(self):
        client, session = self.client()
        client.get_text("https://x/rank/", cookies={"w_tsfp": "пропуск"})
        self.assertNotIn("Cookie", session.calls[0].get("headers") or {})

    def test_without_cookies_nothing_extra_is_asked_for(self):
        """Сессия бывает какая угодно — лишний довод ей ни к чему."""
        client, session = self.client()
        client.get_text("https://x/rank/")
        self.assertNotIn("cookies", session.calls[0])

    def test_the_headers_still_go_as_before(self):
        client, session = self.client()
        client.get_text("https://x/rank/", headers={"Referer": "https://x/"},
                        cookies={"w_tsfp": "пропуск"})
        self.assertEqual(
            (session.calls[0].get("headers") or {}).get("Referer"),
            "https://x/")


class TestTheLastResortAlsoCarriesThem(unittest.TestCase):
    """Запасной ход на стандартной библиотеке молча выбрасывал всё, о чём
    его просили: сюда приходили и Referer, и язык, и пропуск, а уходил
    один User-Agent."""

    def asked(self, **kwargs):
        import urllib.request

        from mvl.client import _UrllibSession

        seen = {}

        class Answer:
            status = 200
            headers: dict = {}

            def read(self):
                return b"ok"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def catch(req, timeout=None):
            seen["headers"] = dict(req.headers)
            return Answer()

        was = urllib.request.urlopen
        urllib.request.urlopen = catch
        try:
            _UrllibSession().get("https://x/rank/", **kwargs)
        finally:
            urllib.request.urlopen = was
        # urllib приводит имена заголовков к Заглавному-Виду.
        return {name.lower(): value for name, value in seen["headers"].items()}

    def test_the_asked_for_headers_are_sent(self):
        sent = self.asked(headers={"Referer": "https://x/"})
        self.assertEqual(sent.get("referer"), "https://x/")

    def test_the_cookie_is_sent_too(self):
        sent = self.asked(cookies={"w_tsfp": "пропуск"})
        self.assertIn("w_tsfp=пропуск", sent.get("cookie", ""))

    def test_several_cookies_go_in_one_line(self):
        """Двух строк `Cookie` в запросе быть не должно."""
        sent = self.asked(cookies={"one": "1", "two": "2"})
        self.assertEqual(sent.get("cookie"), "one=1; two=2")

    def test_the_browser_name_is_still_there(self):
        sent = self.asked(headers={"Referer": "https://x/"})
        self.assertTrue(sent.get("user-agent"))


if __name__ == "__main__":
    unittest.main()
