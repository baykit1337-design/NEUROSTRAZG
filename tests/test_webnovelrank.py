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


class TestBookDetails(unittest.TestCase):
    """Подробности книги для раскрытой строки.

    Раскрытая строка Webnovel показывала ровно то, что и так стоит в
    самой строке: то же название, то же число, те же кнопки. Раскрывают,
    чтобы узнать больше.

    Страницу книги разбирает сам источник — здесь берётся его же разбор,
    и заготовка страницы взята оттуда же, чтобы формы не разошлись.
    """

    def setUp(self):
        from tests.test_webnovel import FakeClient, book_page

        self.page = book_page
        self.client = FakeClient({"/book/36543528000922105": book_page()})

    def look(self, client=None):
        return wnrank.book(client or self.client, "36543528000922105")

    def test_the_description_comes_back(self):
        """То, ради чего строку и раскрывают."""
        self.assertIn("Every world has power", self.look()["abstract"])

    def test_the_key_is_the_same_as_on_other_sites(self):
        """Карточку рисует один и тот же код на все рейтинги: своё имя
        поля здесь означало бы свою ветку в отрисовке."""
        self.assertIn("abstract", self.look())

    def test_the_rest_of_the_card_comes_too(self):
        found = self.look()
        self.assertEqual(found["author"], "Masked_Narrator")
        self.assertEqual(found["chapters"], 41)
        self.assertTrue(found["cover"])
        self.assertTrue(found["link"].endswith("36543528000922105"))

    def test_the_genre_becomes_a_tag(self):
        self.assertIn("Anime & Comics", self.look()["tags"])

    def test_a_page_without_the_object_is_a_broken_source(self):
        """«Сайт не ответил» лечится повтором, «разметка другая» — нет."""
        from tests.test_webnovel import FakeClient

        client = FakeClient({"/book/": "<html><body>ничего</body></html>"})
        with self.assertRaises(SourceBroken):
            self.look(client)

    def test_a_page_with_the_mark_but_no_book_is_told_apart(self):
        """Метка на месте, а книги в ней нет: сайт поменял не адрес, а
        содержимое. Отдать пустую карточку значило бы показать человеку
        пустое место вместо причины."""
        from tests.test_webnovel import FakeClient

        page = ("<html><body><script>g_data.book= "
                '{"curReadChapter":0},g_data.pageId="qi_p_bookdetail"'
                "</script></body></html>")
        with self.assertRaises(SourceBroken):
            self.look(FakeClient({"/book/": page}))

    def test_an_empty_code_says_so(self):
        with self.assertRaises(SourceBroken):
            wnrank.book(self.client, "")

    def test_a_book_without_a_description_does_not_break_the_card(self):
        """Описание есть не у каждой книги, и это не поломка разбора."""
        from tests.test_webnovel import FakeClient, escaped

        # Сайт экранирует строки по-своему, поэтому вырезаем описание тем
        # же кодом, каким заготовка его туда положила.
        page = self.page().replace(
            escaped("Every world has power worth taking."), '""')
        found = wnrank.book(FakeClient({"/book/": page}),
                            "36543528000922105")
        self.assertEqual(found["abstract"], "")
        self.assertEqual(found["author"], "Masked_Narrator")


if __name__ == "__main__":
    unittest.main(verbosity=2)


def div_row(place=1, code="36543528000922105", slug="marvel-i-steal-powers",
            name="Marvel: I Steal Powers", value="132.4K",
            category="Anime & Comics"):
    """Та же строка, свёрстанная дивами: списка на странице нет вовсе."""
    return (
        '<div class="_rank_item">'
        '<span class="ff_number">%02d</span>'
        '<a href="/book/%s_%s"><img src="//book-pic.webnovel.com/bookcover/%s"></a>'
        '<div><h3><a href="/book/%s_%s">%s</a></h3>'
        '<p><a href="/stories/novel-fantasy-male">%s</a></p>'
        '<strong class="ff_number">%s<span>Power</span></strong>'
        '</div></div>'
        % (place, slug, code, code, slug, code, name, category, value)
    )


class TestARedesignWithoutLists(unittest.TestCase):
    """Рейтинг, переверстанный дивами.

    Разбор по `<li>` держится на том, что доска свёрстана списком. Стоит
    сайту от списка отказаться — и разбор не находит ничего, хотя книги
    на странице никуда не делись: ссылка `/book/{код}` есть в любой
    вёрстке, иначе на книгу нельзя было бы перейти.
    """

    def fetch(self, body):
        return wnrank.fetch(FakeClient(body), "hot")

    def body(self, count=3):
        rows = [div_row(place=number, code=f"3654352800092210{number}",
                        name=f"Книга {number}")
                for number in range(1, count + 1)]
        return "<html><body><div class='rank'>" + "".join(rows) + "</div></body></html>"

    def test_the_books_are_found_anyway(self):
        found = self.fetch(self.body())
        self.assertEqual([row.name for row in found["rows"]],
                         ["Книга 1", "Книга 2", "Книга 3"])

    def test_the_order_of_the_page_is_kept(self):
        found = self.fetch(self.body())
        self.assertEqual([row.place for row in found["rows"]], [1, 2, 3])

    def test_the_number_of_the_board_still_arrives(self):
        found = self.fetch(self.body())
        self.assertEqual(found["rows"][0].score, 132_400)

    def test_one_book_twice_is_still_counted_once(self):
        """Обложка и заголовок — две ссылки на одну книгу в каждой строке."""
        found = self.fetch(self.body(count=2))
        self.assertEqual(len(found["rows"]), 2)

    def test_the_section_survives(self):
        found = self.fetch(self.body())
        self.assertEqual(found["rows"][0].category, "Anime & Comics")

    def test_the_list_is_tried_first(self):
        """Разбор по списку точнее: он знает, где кончается одна книга.

        Свёрстано списком — им и разбираем, к запасному пути не переходим.
        """
        found = wnrank.fetch(FakeClient(page([row()])), "hot")
        self.assertEqual(len(found["rows"]), 1)

    def test_menu_links_are_still_not_books(self):
        body = ("<html><body><div><a href='/ranking/hot'>Rankings</a>"
                "<a href='/stories/novel-fantasy-male'>Fantasy</a>"
                "<a href='/profile/4504916647'>Автор</a></div></body></html>")
        with self.assertRaises(SourceBroken):
            self.fetch(body)


class TestTheRefusalCarriesEvidence(unittest.TestCase):
    """Отказ должен говорить, что пришло, а не что мы про это думаем.

    Прежнее сообщение утверждало причину — «сайт переделал рейтинг на
    подгрузку скриптом», — которой знать не могло. С тем же успехом это
    могла быть страница входа, заглушка посредника или пустой ответ. Так
    уверенная догадка уводит чинить не то.
    """

    def refuse(self, body):
        with self.assertRaises(SourceBroken) as caught:
            wnrank.fetch(FakeClient(body), "hot")
        return caught.exception

    def test_it_does_not_name_a_cause_it_cannot_know(self):
        said = str(self.refuse("<html><body><p>Пусто</p></body></html>"))
        self.assertNotIn("переделал", said)
        self.assertNotIn("подгрузку скриптом", said)

    def test_it_tells_how_much_came(self):
        said = str(self.refuse("<html><body><p>Пусто</p></body></html>"))
        self.assertIn("байт", said)

    def test_it_tells_the_window_title(self):
        """По заголовку окна видно и вход, и заглушку, и пустую страницу."""
        said = str(self.refuse(
            "<html><head><title>Log in — Webnovel</title></head>"
            "<body></body></html>"))
        self.assertIn("Log in", said)

    def test_it_counts_what_it_looked_for(self):
        said = str(self.refuse(
            "<html><body><ul><li>Меню</li><li>Ещё</li></ul></body></html>"))
        self.assertIn("2", said)
        self.assertIn("ссылок на книги: 0", said)

    def test_it_names_the_objects_it_saw(self):
        """Приметы того, что список уехал в скрипт, — но как приметы."""
        said = str(self.refuse(
            "<html><body><script>window.__NEXT_DATA__={}</script></body></html>"))
        self.assertIn("__NEXT_DATA__", said)

    def test_the_page_travels_with_the_refusal(self):
        """Иначе чинить разбор нечем: ответ к разбору жалобы выброшен."""
        body = "<html><body><p>Совсем не то</p></body></html>"
        self.assertEqual(self.refuse(body).page, body)

    def test_a_wall_is_still_told_apart_from_a_redesign(self):
        """Стену объявляем стеной: разметка тут ни при чём."""
        wall = "<html><body><h1>Just a moment...</h1></body></html>"
        self.assertIn("Cloudflare", str(self.refuse(wall)))


#: Строка рейтинга ровно в том виде, в каком её отдаёт сайт. Взята со
#: страницы `/ranking/fanfic/bi_annual/power_rank`; сокращены только
#: описание и часть меток — устройство строки сохранено полностью.
#:
#: Живьём из песочницы этот сайт не открыть, и разбор писался вслепую по
#: догадке о вёрстке. Догадка не сошлась: строки оказались не `<li>`, а
#: `<section>`. Поэтому заготовка здесь настоящая, а не сочинённая.
REAL_ROW = '''<section class="df g_hr pt16 pb16"><i class="w40 h40 ff_number tac \
fw700 lh20 fs16 ls0.15 mr8 pt12 c_danger">001</i><a \
href="/book/marvel-terror-stream_35895681908097305" class="g_thumb _48 mr8" \
title="Marvel: Terror Stream" data-report-did="35895681908097305"><img \
data-original="//book-pic.webnovel.com/bookcover/35895681908097305?imageMogr2\
/thumbnail/150&imageId=1783614889353" width="60" height="80" alt="Marvel: \
Terror Stream"/></a><div class="f1"><p class="mb4 pt4 oh h16 mb8"><a \
class="fw600 lh16 fs12 ttu ls1 mr12 wsn" href="/tags/action-novel" \
title="ACTION"># ACTION</a><a class="fw600 lh16 fs12 ttu ls1 mr12 wsn" \
href="/tags/marvel-novel" title="MARVEL"># MARVEL</a></p><h3 class="fw700 lh20 \
fs16 ls0.15 ells _2 mb4"><a class="c_l" \
href="/book/marvel-terror-stream_35895681908097305" title="Marvel: Terror \
Stream" data-report-did="35895681908097305">Marvel: Terror Stream</a></h3><p \
class="fw400 lh20 fs14 ls0.2 c_s ells _2 mb4">Luke woke up in the Marvel \
Universe.</p><p><strong class="c_m fs0 ff_number vam"><svg viewBox="0 0 24 24" \
fill="none" class="mr4 fs16"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 \
2z" fill="#000"></path></svg><span class="vam fw400 lh16 fs12">586</span>\
</strong><i class="c_xs vam ml8 mr8">|</i><a href="/stories/fanfic-anime-comics" \
title="Anime &amp; Comics" class="c_m vam fw400 lh16 fs12">Anime &amp; Comics\
</a>·<strong class="c_l vam fw400 lh16 fs12">Marveller</strong></p></div><div \
class="ml8"><a class="bt _s _link fs0 j_add_to_library add_to_library _mini " \
data-bookid="35895681908097305" href="###" title="Add to library"><span \
class="vam fw600 lh16 fs12 ttu ls1">Add</span></a><a \
href="/book/marvel-terror-stream_35895681908097305/96367413607592963" \
title="Read" class="ml8 bt _s">Read</a></div></section>'''

#: Та же строка с доски «дописано за неделю»: число там без значка и в
#: тысячах, а имя автора начинается с цифры — проверка на то, что автор
#: не сойдёт за число доски.
REAL_WORDS_ROW = '''<section class="df g_hr pt16 pb16"><i class="w40 h40 \
ff_number tac fw700 lh20 fs16 ls0.15 mr8 pt12 c_danger">001</i><a \
href="/book/douluo-twin-dragons_36785303708811405" class="g_thumb _48 mr8" \
title="Douluo"><img data-original="//book-pic.webnovel.com/bookcover\
/36785303708811405?imageMogr2/thumbnail/150" width="60" height="80" \
alt="Douluo"/></a><div class="f1"><h3 class="fw700 lh20 fs16 ls0.15 ells _2 \
mb4"><a class="c_l" href="/book/douluo-twin-dragons_36785303708811405" \
title="Douluo">Douluo: Twin Golden and Silver Dragons</a></h3><p \
class="fw400 lh20 fs14 ls0.2 c_s ells _2 mb4">Transmigrating to the \
continent.</p><p><strong class="c_m fs0 ff_number vam"><span class="vam fw400 \
lh16 fs12">46.3K</span></strong><i class="c_xs vam ml8 mr8">|</i><a \
href="/stories/fanfic-anime-comics" title="Anime &amp; Comics" class="c_m vam \
fw400 lh16 fs12">Anime &amp; Comics</a>·<strong class="c_l vam fw400 lh16 \
fs12">56kanwa</strong></p></div></section>'''

#: Боковое меню досок — оно на странице свёрстано именно списком, и
#: разбор обязан пройти мимо него.
REAL_SIDEBAR = '''<div class="mr24" style="width: 200px;"><form><a \
href="/ranking/hot" title="Hot Ranking" class="df jcsb aic g_hr"><h3 \
class="fw700 lh24 fs20 ell">Hot Ranking</h3></a><div class="m-accordion-bd"><ul \
class="pt16"><li class="dib vat mb8"><a data-rankid="power_rank" \
href="/ranking/fanfic/bi_annual/power_rank" title="Power" \
class="m-accordion-item">Power</a></li><li class="dib vat mb8"><a \
data-rankid="collection_rank" href="/ranking/fanfic/all_time/collection_rank" \
title="Collect" class="m-accordion-item">Collect</a></li></ul></div></form>\
</div>'''


def real_page(rows):
    return ("<html><head><title>Power Ranking in Fan-fic Rankings</title></head>"
            "<body>" + REAL_SIDEBAR
            + '<div class="j_rank_wrapper">' + "".join(rows) + "</div>"
            + "</body></html>")



#: Строка рейтинга комиксов — с настоящей страницы.
#:
#: Отличие от романов ровно одно, и оно решающее: книга живёт в разделе
#: `/comic/`, а не `/book/`. Разбор искал только `/book/` и честно
#: сообщал «ссылок на книги: 0» — он был прав, просто искал не там.
COMIC_ROW = '''<section class="df g_hr pt16 pb16"><i class="w40 h40 ff_number \
tac fw700 lh20 fs16 ls0.15 mr8 pt12 c_danger">001</i><a \
href="/comic/shadow-slave_36706727700938701" class="g_thumb _48 mr8" \
title="Shadow Slave" data-report-did="36706727700938701"><img \
data-original="//book-pic.webnovel.com/bookcover/36706727700938701?imageMogr2\
/thumbnail/150&imageId=1787109174634" width="60" height="80" alt="Shadow \
Slave"/></a><div class="f1"><h3 class="fw700 lh20 fs16 ls0.15 ells _2 mb4"><a \
class="c_l" href="/comic/shadow-slave_36706727700938701" title="Shadow Slave" \
data-report-did="36706727700938701">Shadow Slave</a></h3><p class="fw400 lh20 \
fs14 ls0.2 c_s ells _2 mb4">Growing up in poverty, Sunny never expected \
anything good from life.</p><p><strong class="c_m fs0 ff_number vam"><svg \
viewBox="0 0 24 24" fill="none" class="mr4 fs16"><path d="M12 22c5.523 0 \
10-4.477 10-10z" fill="#000"></path></svg><span class="vam fw400 lh16 fs12">\
150</span></strong><strong class="c_l vam fw400 lh16 fs12">Aethon &amp; Laurel \
Pursuit</strong></p></div><div class="ml8"><a class="bt _s _link fs0 \
j_add_to_library" data-bookid="36706727700938701" href="###" title="Add to \
library"><span class="vam fs12">Add</span></a><a \
href="/comic/shadow-slave_36706727700938701/98535426125524015" title="Read" \
class="ml8 bt _s">Read</a></div></section>'''

#: Подвал настоящей страницы. В нём спрятана ссылка на книгу — не строка
#: рейтинга, а реклама, и в рейтинг ей попадать нельзя.
COMIC_FOOTER = ('<div class="g_footer"><p class="g_ft_links">'
                '<a href="https://www.webnovel.com/book/22196546206090805" '
                'title="Shadow Slave" class="dn">Shadow Slave</a></p></div>')


def comic_page(rows):
    """Страница комиксов: боковое меню, строки рейтинга и подвал."""
    return ("<html><head><title>Power Ranking in Comics Rankings</title></head>"
            "<body>" + REAL_SIDEBAR
            + '<div class="j_rank_wrapper">' + "".join(rows) + "</div>"
            + COMIC_FOOTER + "</body></html>")


class TestTheComicsBoard(unittest.TestCase):
    """Рейтинг комиксов не разбирался вовсе.

    На живом запуске он отвечал «не нашлось ни одной книги» при 85 КБ
    страницы и правильном заголовке окна. Книги на ней были — просто в
    разделе `/comic/`, которого шаблон ссылки не знал.
    """

    def fetch(self, body, board="comic-power"):
        return wnrank.fetch(FakeClient(body), board)

    def test_a_comic_becomes_a_book(self):
        found = self.fetch(comic_page([COMIC_ROW]))
        first = found["rows"][0]
        self.assertEqual(first.book_id, "36706727700938701")
        self.assertEqual(first.name, "Shadow Slave")

    def test_the_link_keeps_the_comic_section(self):
        """Ссылку берём со страницы, а не собираем из кода: собранная
        вела бы в раздел романов, где комикса нет."""
        found = self.fetch(comic_page([COMIC_ROW]))
        self.assertEqual(found["rows"][0].link,
                         "https://www.webnovel.com/comic/"
                         "shadow-slave_36706727700938701")

    def test_the_number_of_the_board_arrives(self):
        found = self.fetch(comic_page([COMIC_ROW]))
        self.assertEqual(found["rows"][0].score, 150)

    def test_the_read_link_is_not_a_second_book(self):
        """«Читать» ведёт на главу: `/comic/{имя}_{код}/{глава}`. Сочти
        разбор номер главы кодом — и в рейтинге завелась бы книга-призрак
        с тем же названием."""
        found = self.fetch(comic_page([COMIC_ROW]))
        self.assertEqual(len(found["rows"]), 1)

    def test_the_book_hidden_in_the_footer_does_not_get_in(self):
        """В подвале страницы висит ссылка на книгу — реклама, а не
        строка рейтинга."""
        found = self.fetch(comic_page([COMIC_ROW]))
        self.assertEqual([row.book_id for row in found["rows"]],
                         ["36706727700938701"])

    def test_a_novel_still_parses(self):
        """Комиксы добавлены, романы не отняты."""
        found = wnrank.fetch(FakeClient(real_page([REAL_ROW])), "fanfic-power")
        self.assertEqual(found["rows"][0].book_id, "35895681908097305")


class TestTheRealPage(unittest.TestCase):
    """Разбор настоящей страницы сайта, а не догадки о ней.

    Первый живой запуск разбора не дал ни одной книги. Причина оказалась
    ровно одна: строки рейтинга свёрстаны `<section>`, а искали их среди
    `<li>` — и единственные `<li>` на странице лежат в боковом меню.
    """

    def fetch(self, body, board="fanfic-power"):
        return wnrank.fetch(FakeClient(body), board)

    def test_the_row_becomes_a_book(self):
        found = self.fetch(real_page([REAL_ROW, REAL_WORDS_ROW]))
        first = found["rows"][0]
        self.assertEqual(first.book_id, "35895681908097305")
        self.assertEqual(first.name, "Marvel: Terror Stream")

    def test_the_place_comes_from_the_page(self):
        """Место сайт печатает с ведущими нулями: «001»."""
        found = self.fetch(real_page([REAL_ROW]))
        self.assertEqual(found["rows"][0].place, 1)

    def test_the_number_of_the_board_arrives(self):
        found = self.fetch(real_page([REAL_ROW]))
        self.assertEqual(found["rows"][0].score, 586)
        self.assertEqual(found["rows"][0].metric, "голосов")

    def test_the_author_is_not_mistaken_for_the_number(self):
        """Имя автора лежит в таком же `<strong>`, что и число доски."""
        found = self.fetch(real_page([REAL_WORDS_ROW]), "fanfic-update")
        self.assertEqual(found["rows"][0].score, 46_300)

    def test_the_section_survives(self):
        found = self.fetch(real_page([REAL_ROW]))
        self.assertEqual(found["rows"][0].category, "Anime & Comics")

    def test_the_link_and_the_cover(self):
        first = self.fetch(real_page([REAL_ROW]))["rows"][0]
        self.assertEqual(
            first.link,
            "https://www.webnovel.com/book/marvel-terror-stream_35895681908097305")
        self.assertIn("35895681908097305", first.cover)

    def test_the_read_link_is_not_a_second_book(self):
        """В строке три ссылки на одну книгу: обложка, заголовок и «Read»."""
        found = self.fetch(real_page([REAL_ROW, REAL_WORDS_ROW]))
        self.assertEqual(len(found["rows"]), 2)

    def test_the_main_parse_finds_the_row_itself(self):
        """Основной разбор обязан находить строку сам.

        Запасной путь от ссылок вытянет её и без этого — он для того и
        заведён. Но тогда основной разбор оставался бы сломанным и молчал
        бы об этом, а чинили бы его в следующий раз опять вслепую.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(real_page([REAL_ROW]), "lxml")
        rows = wnrank._rows_from_list(soup, "голосов")
        self.assertEqual([row.name for row in rows], ["Marvel: Terror Stream"])

    def test_the_side_menu_is_not_a_book(self):
        with self.assertRaises(SourceBroken):
            self.fetch(real_page([]))

    def test_every_fanfic_board_has_an_address_and_a_label(self):
        """Человек прислал разметку всех пяти досок фанфиков — все и нужны."""
        fanfic = [key for key in wnrank.BOARDS if key.startswith("fanfic-")]
        self.assertEqual(len(fanfic), 5)
        for board in fanfic:
            with self.subTest(board):
                self.assertIn("/ranking/fanfic/", wnrank.url_of(board))
                self.assertTrue(wnrank.METRICS[board])
