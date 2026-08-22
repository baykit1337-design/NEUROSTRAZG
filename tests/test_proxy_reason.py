"""Почему прокси не пропустил — человеческими словами.

В таблице проверки стояла строка

    ProxyError: Failed to perform, curl: (56) CONNECT tunnel failed,
    response 402

и из неё нельзя было понять ни того, что отказал сам посредник, ни того,
что он ответил. Человек прочитал это как «программа сломала прокси» — и
это разумное прочтение: строка не говорит ничего.

Разница принципиальная. Ответ на CONNECT — это ответ посредника **о
себе**: до сайта дело не дошло, сайт этого запроса не видел. Поэтому и
чинится оно не в программе.

Числа-настройки здесь не закрепляются, а тексты закрепляются: текст и
есть то, ради чего всё это написано.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.proxies import Proxy, common_refusal, short_reason  # noqa: E402


def tunnel(code: int) -> str:
    """Ровно то, что отдаёт curl, когда прокси отказал на CONNECT."""
    return ("ProxyError: Failed to perform, curl: (56) CONNECT tunnel "
            f"failed, response {code}")


class TestTheProxyIsNamedAsTheOneWhoRefused(unittest.TestCase):
    def test_the_reason_says_it_was_the_proxy(self):
        self.assertIn("посредник", short_reason(tunnel(402)))

    def test_payment_is_told_apart_from_everything_else(self):
        """402 здесь — про тариф посредника, а не про платную книгу."""
        said = short_reason(tunnel(402))
        self.assertTrue("тариф" in said or "трафик" in said, said)

    def test_a_forbidden_destination_is_not_the_same_as_no_money(self):
        self.assertNotEqual(short_reason(tunnel(402)), short_reason(tunnel(403)))

    def test_an_unknown_code_is_still_shown(self):
        """Кода нет в списке — это не повод молчать: число само по себе
        уже подсказка, с чем идти к поставщику прокси."""
        said = short_reason(tunnel(418))
        self.assertIn("посредник", said)
        self.assertIn("418", said)


class TestItStaysShort(unittest.TestCase):
    """Строка стоит в узкой колонке таблицы: простыня её распирает."""

    def test_the_curl_boilerplate_is_gone(self):
        said = short_reason(tunnel(402))
        for noise in ("curl", "Failed to perform", "CONNECT"):
            self.assertNotIn(noise, said)

    def test_it_fits_a_table_cell(self):
        self.assertLess(len(short_reason(tunnel(402))), 60)


class TestWhenEveryAddressSaysTheSame(unittest.TestCase):
    """Двадцать разных адресов с одним ответом — это не про адреса.

    Раньше на пустой список пригодных писалось «обновите список и
    проверьте снова». В этом случае совет вредный: список в порядке,
    новый даст ровно то же самое, а человек потратит вечер на поиск
    свежих адресов вместо одного письма поставщику.
    """

    def made(self, error: str):
        made = Proxy(host="1.2.3.4", port=8000)
        made.alive = False
        made.error = short_reason(error)
        return made

    def test_one_reason_for_all_is_reported(self):
        said = common_refusal([self.made(tunnel(402)) for _ in range(4)])
        self.assertIn("посредник", said)

    def test_different_reasons_are_not_summed_up(self):
        """Причины разные — обобщать нечего, пусть читают таблицу."""
        mixed = [self.made(tunnel(402)), self.made("Operation timed out")]
        self.assertEqual(common_refusal(mixed), "")

    def test_a_working_address_means_there_is_nothing_to_report(self):
        alive = Proxy(host="9.9.9.9", port=80)
        alive.alive = True
        alive.status = 200
        self.assertEqual(common_refusal([alive]), "")

    def test_the_sites_own_refusal_is_not_blamed_on_the_provider(self):
        """Таймаут у всех — это может быть и сеть, и сайт, и вечер
        пятницы. Про учётную запись говорим только тогда, когда ответил
        сам посредник."""
        alike = [self.made("Operation timed out") for _ in range(4)]
        self.assertEqual(common_refusal(alike), "")


class TestTheOldReasonsSurvive(unittest.TestCase):
    """Разбор туннеля добавлен к остальным, а не вместо них."""

    def test_a_timeout_is_still_a_timeout(self):
        self.assertEqual(
            short_reason("ConnectionError: Failed to perform, curl: (28) "
                         "Operation timed out after 60000 milliseconds"),
            "таймаут")

    def test_a_bad_login_is_still_a_bad_login(self):
        said = short_reason("curl: (56) CONNECT tunnel failed, response 407")
        self.assertIn("логин", said)

    def test_dns_is_still_dns(self):
        self.assertIn("DNS", short_reason(
            "ConnectionError: Could not resolve host: www.example.com"))

    def test_something_unrecognised_comes_through_as_is(self):
        self.assertIn("Странная беда", short_reason("Странная беда"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
