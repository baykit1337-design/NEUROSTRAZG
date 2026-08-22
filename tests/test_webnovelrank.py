"""Рейтинг Webnovel: разбор страницы досок.

Живьём в песочнице это не проверить — `www.webnovel.com` за пределами
разрешённого списка. Здесь заготовки той же формы, что и настоящая
страница: список, в каждой строке место, обложка, заголовок, ссылка на
книгу, раздел и число доски.

Служебные классы сайта в заготовках оставлены (`df pt8 pb8 pr`), но
разбор на них нарочно не смотрит: они меняются с каждой правкой вида.
Тесты это и проверяют — строка без единого знакомого класса обязана
разобраться.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources import webnovelrank as wnrank  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402


def row(place=1, code="36543528000922105", slug="marvel-i-steal-powers",
        name="Marvel: I Steal Powers", value="132.4K",
        category="Anime & Comics", classes="df pt8 pb8 pr _thumb_hover"):
    """Одна строка рейтинга в той же форме, что и на сайте."""
    return (
        '<li class="%s">'
        '<i class="w20 h20 ff_number">%02d</i>'
        '<a href="/book/%s_%s"><img src="//book-pic.webnovel.com/bookcover/%s"></a>'
        '<div><h3><a href="/book/%s_%s">%s</a></h3>'
        '<p><a href="/stories/novel-fantasy-male">%s</a></p>'
        '<strong class="c_m ff_number">%s<span>Power</span></strong>'
        '</div></li>'
        % (classes, place, slug, code, code, slug, code, name, category, value)
    )


def page(rows, extra=""):
    return ("<html><body>"
            '<ul class="ranking-list">' + "".join(rows) + "</ul>"
            + extra + "</body></html>")


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.asked = []

    def get_text(self, url, params=None, headers=None):
        self.asked.append(url)
        return self.body

    def close(self):
        pass


class TestAddresses(unittest.TestCase):
    """Досок у сайта под сотню — здесь отобран рабочий десяток."""

    def test_the_hot_board_is_its_own_page(self):
        self.assertTrue(wnrank.url_of("hot").endswith("/ranking/hot"))

    def test_the_other_boards_follow_one_rule(self):
        said = wnrank.url_of("novel-power")
        self.assertIn("/ranking/novel/season/power_rank", said)

    def test_every_board_has_an_address_and_a_name(self):
        for key in wnrank.BOARDS:
            self.assertIn(key, wnrank.PATHS, key)
            self.assertTrue(wnrank.BOARDS[key], key)

    def test_every_board_says_what_its_number_means(self):
        """Иначе число в строке не подписать, а подписать надо."""
        for key in wnrank.BOARDS:
            self.assertTrue(wnrank.METRICS.get(key), key)

    def test_an_unknown_board_is_refused(self):
        with self.assertRaises(ValueError):
            wnrank.url_of("годовой")


class TestParsing(unittest.TestCase):
    def fetch(self, body, board="hot"):
        return wnrank.fetch(FakeClient(body), board=board)

    def test_a_row_becomes_a_book(self):
        got = self.fetch(page([row()]))
        found = got["rows"][0]
        self.assertEqual(found.book_id, "36543528000922105")
        self.assertEqual(found.name, "Marvel: I Steal Powers")
        self.assertEqual(found.site, "webnovel")

    def test_places_come_from_the_page(self):
        rows = self.fetch(page([row(place=1), row(place=2, code="1" * 18),
                                row(place=3, code="2" * 18)]))["rows"]
        self.assertEqual([r.place for r in rows], [1, 2, 3])

    def test_places_are_renumbered_when_the_page_repeats_them(self):
        """Сайт печатает место не у каждой строки — тогда считаем сами."""
        rows = self.fetch(page([row(place=1), row(place=1, code="1" * 18),
                                row(place=1, code="2" * 18)]))["rows"]
        self.assertEqual([r.place for r in rows], [1, 2, 3])

    def test_the_link_keeps_the_slug_the_site_gave(self):
        found = self.fetch(page([row()]))["rows"][0]
        self.assertIn("marvel-i-steal-powers", found.link)
        self.assertTrue(found.link.startswith("https://www.webnovel.com"))

    def test_the_cover_is_addressed_by_the_book_code(self):
        found = self.fetch(page([row()]))["rows"][0]
        self.assertIn("36543528000922105", found.cover)

    def test_the_section_survives(self):
        self.assertEqual(self.fetch(page([row()]))["rows"][0].category,
                         "Anime & Comics")

    def test_a_short_number_is_expanded(self):
        """«132.4K» — это сто тридцать две тысячи, а не сто тридцать два."""
        found = self.fetch(page([row(value="132.4K")]))["rows"][0]
        self.assertEqual(found.score, 132_400)

    def test_a_plain_number_with_separators_survives(self):
        found = self.fetch(page([row(value="12,300")]))["rows"][0]
        self.assertEqual(found.score, 12_300)

    def test_the_number_comes_with_a_label(self):
        """Без подписи голоса читались бы как оценка."""
        found = self.fetch(page([row()]), board="novel-power")["rows"][0]
        self.assertEqual(found.metric, wnrank.METRICS["novel-power"])

    def test_the_label_is_not_invented_when_there_is_no_number(self):
        body = page(['<li><h3><a href="/book/slug_%s">Книга</a></h3></li>'
                     % ("3" * 18)])
        found = self.fetch(body)["rows"][0]
        self.assertIsNone(found.score)
        self.assertEqual(found.metric, "")

    def test_readers_are_honestly_zero(self):
        """Числа читающих сайт не показывает — подставлять голоса нельзя."""
        self.assertEqual(self.fetch(page([row()]))["rows"][0].readers, 0)


class TestItSurvivesARedesign(unittest.TestCase):
    """Служебные классы сайта меняются — разбор на них не смотрит."""

    def fetch(self, body):
        return wnrank.fetch(FakeClient(body), board="hot")

    def test_a_row_without_a_single_familiar_class_still_parses(self):
        found = self.fetch(page([row(classes="совершенно другие классы")]))
        self.assertEqual(len(found["rows"]), 1)

    def test_a_row_without_a_heading_falls_back_to_the_link_text(self):
        body = page(['<li><a href="/book/slug_%s">Название из ссылки</a></li>'
                     % ("4" * 18)])
        self.assertEqual(self.fetch(body)["rows"][0].name, "Название из ссылки")

    def test_menu_and_footer_links_are_not_mistaken_for_books(self):
        junk = ('<li><a href="/ranking/hot">Rankings</a></li>'
                '<li><a href="/stories/novel-fantasy-male">Fantasy</a></li>'
                '<li><a href="/profile/4504916647">Автор</a></li>')
        got = self.fetch(page([row()], extra="<ul>" + junk + "</ul>"))
        self.assertEqual(len(got["rows"]), 1)

    def test_one_book_twice_on_a_page_is_counted_once(self):
        got = self.fetch(page([row(), row()]))
        self.assertEqual(len(got["rows"]), 1)

    def test_a_chapter_link_is_not_a_book(self):
        """В адресе главы после кода книги идёт ещё один кусок."""
        body = page(['<li><h3><a href="/book/slug_%s/chapter_%s">Глава</a>'
                     '</h3></li>' % ("5" * 18, "6" * 18)])
        with self.assertRaises(SourceBroken):
            self.fetch(body)

    def test_a_page_without_books_says_what_broke_and_where(self):
        with self.assertRaises(SourceBroken) as caught:
            self.fetch("<html><body><p>ничего</p></body></html>")
        said = str(caught.exception)
        self.assertIn("/ranking/hot", said)

    def test_the_list_is_cut_to_a_sane_length(self):
        many = [row(place=i + 1, code=str(10 ** 17 + i))
                for i in range(wnrank.TOP + 30)]
        self.assertEqual(len(self.fetch(page(many))["rows"]), wnrank.TOP)


class TestVersion(unittest.TestCase):
    def test_the_same_page_gives_the_same_version(self):
        body = page([row(), row(place=2, code="7" * 18)])
        first = wnrank.fetch(FakeClient(body))["version"]
        second = wnrank.fetch(FakeClient(body))["version"]
        self.assertEqual(first, second)

    def test_a_reshuffled_top_changes_the_version(self):
        one = page([row(), row(place=2, code="7" * 18)])
        two = page([row(place=1, code="7" * 18), row(place=2)])
        self.assertNotEqual(wnrank.fetch(FakeClient(one))["version"],
                            wnrank.fetch(FakeClient(two))["version"])


class TestTheRouteEndToEnd(unittest.TestCase):
    """От запроса до сохранённого среза, с подменённой сетью."""

    def setUp(self):
        import tempfile

        from ops import rank as rank_op
        from webapp import app as web

        self.rank_op = rank_op
        self.web = web
        self.tmp = tempfile.TemporaryDirectory()
        self.was_dir = rank_op.RANK_DIR
        rank_op.RANK_DIR = Path(self.tmp.name)

        self.was_client = web._rank_client
        body = page([row(place=i + 1, code=str(10 ** 17 + i),
                         name="Книга %d" % i) for i in range(5)])
        web._rank_client = lambda: FakeClient(body)

        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def tearDown(self):
        self.web._rank_client = self.was_client
        self.rank_op.RANK_DIR = self.was_dir
        self.tmp.cleanup()

    def test_the_site_is_offered_on_the_page(self):
        got = self.client.get("/api/rank/categories").get_json()
        keys = [s["key"] for s in got["sites"]]
        self.assertIn("webnovel", keys)

    def test_its_books_are_downloaded_from_webnovel(self):
        got = self.client.get("/api/rank/categories").get_json()
        site = [s for s in got["sites"] if s["key"] == "webnovel"][0]
        self.assertEqual(site["source"], "webnovel")

    def test_every_site_explains_itself_from_the_server(self):
        """Страница однажды уже соврала: под Webnovel показывалось
        пояснение от MVLEMPYR — «своей страницы рейтинга у сайта нет», —
        при том, что у него она как раз есть. Развилка «Фанкью или не
        Фанкью» на странице повторила бы это с третьим сайтом."""
        got = self.client.get("/api/rank/categories").get_json()
        for site in got["sites"]:
            self.assertTrue(site.get("about"), site["key"])
        texts = [s["about"] for s in got["sites"]]
        self.assertEqual(len(set(texts)), len(texts))

    def test_the_page_does_not_guess_the_explanation_itself(self):
        tabs = (Path(__file__).resolve().parent.parent / "webapp" / "static"
                / "tabs.js").read_text(encoding="utf-8")
        block = tabs.split("function rkApplySite()", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("site.about", block)

    def test_a_refresh_saves_a_snapshot(self):
        got = self.client.post("/api/rank/refresh",
                               json={"site": "webnovel",
                                     "board": "hot"}).get_json()
        self.assertEqual(got["saved"], 5)
        self.assertEqual(len(self.rank_op.days("hot", site="webnovel")), 1)

    def test_the_label_of_the_number_reaches_the_page(self):
        self.client.post("/api/rank/refresh",
                         json={"site": "webnovel", "board": "novel-power"})
        got = self.client.get(
            "/api/rank/state?site=webnovel&board=novel-power").get_json()
        self.assertEqual(got["rows"][0]["metric"],
                         wnrank.METRICS["novel-power"])

    def test_three_sites_keep_three_separate_histories(self):
        self.client.post("/api/rank/refresh",
                         json={"site": "webnovel", "board": "hot"})
        self.assertEqual(self.rank_op.days("hot"), [])
        self.assertEqual(self.rank_op.days("hot", site="mvlempyr"), [])
        self.assertEqual(len(self.rank_op.days("hot", site="webnovel")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
