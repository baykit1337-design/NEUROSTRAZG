"""Рейтинг Цидяня: разбор досок, разделов и страницы книги.

Живой проверки в песочнице не было — `www.qidian.com` за пределами
разрешённого списка, шлюз отвечает 403 на любой запрос. Зато были три
страницы, снятые с живого сайта человеком: главная, раздел `/xuanhuan/`
и страница книги. Заготовки ниже — куски **этой самой** разметки, а не
придуманные по памяти: сохранены и классы, и порядок узлов, и китайские
хвосты в подсказках.

Числа-настройки (сколько строк в срезе) не закрепляются: их будут
крутить. Закрепляется то, что ломается молча, — адреса, коды, названия.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.client import HttpError  # noqa: E402
from net.sources import qidianrank as qd  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402

#: Доска с главной страницы: первая книга крупно, остальные строками.
#: Скопировано с живой страницы — вплоть до `<i>&#183;</i>` между
#: жанром и автором.
HOME = """
<div class="rank-list" data-l2="1"><h3 class="wrap-title lang"><a
href="https://www.qidian.com/rank/yuepiao/">月票榜<i>&#183;</i>VIP新作</a></h3>
<div class="book-list"><ul><li class="unfold" data-rid="1">
<div class="book-wrap cf"><div class="book-info fl"><h3>NO.1</h3><h2><a
href="//www.qidian.com/book/1049534879/" data-bid="1049534879">武道！</a></h2>
<p class="digital"><em>20717</em>月票</p><p class="author"><a class="type"
href="//www.qidian.com/xuanhuan/">玄幻</a><i>&#183;</i><a class="writer"
href="//my.qidian.com/author/403390573/">田隶</a></p></div>
<div class="book-cover"><a class="link" href="//www.qidian.com/book/1049534879/"
data-bid="1049534879"><img
src="//bookcover.yuewen.com/qdbimg/349573/1049534879/90.webp"></a></div></div></li>
<li data-rid="2"><div class="num-box"><span class="num2">2</span></div>
<div class="name-box"><a class="name" href="//www.qidian.com/book/1049745989/"
data-bid="1049745989">急急如律令</a><i class="total">16536</i></div></li>
<li data-rid="3"><div class="num-box"><span class="num3">3</span></div>
<div class="name-box"><a class="name" href="//www.qidian.com/book/1049640386/"
data-bid="1049640386">我绑定了夏弥</a><i class="total">9674</i></div></li>
</ul></div></div>
"""

#: Та же доска со страницы раздела: у ссылок появляется `title` с
#: хвостом сайта, а название лежит внутри `<h2>`.
CHANNEL = """
<div class="rank-list sort-list"><h3 class="wrap-title lang">玄幻畅销榜</h3>
<div class="book-list"><ul><li class="unfold" data-rid="1">
<div class="book-wrap cf"><div class="book-info fl"><h3>NO.1</h3><h2><a
href="//www.qidian.com/book/1040765595/" data-bid="1040765595"
title="夜无疆最新章节在线阅读">夜无疆</a></h2><p class="digital f16">销量冠军</p>
<p class="author"><a class="type"
href="//www.qidian.com/all/chanId21-subCateId8/">东方玄幻</a><i>·</i>
<a class="writer" href="//my.qidian.com/author/4362453/">辰东</a></p></div></div></li>
<li data-rid="2"><div class="num-box"><span class="num2">2</span></div>
<div class="name-box"><a class="name" href="//www.qidian.com/book/1010868264/"
data-bid="1010868264" title="诡秘之主最新章节在线阅读"><h2>诡秘之主</h2></a>
<span class="iconfont">&#xe627;</span></div></li>
</ul></div></div>
"""

#: Главная целиком — с рекламой, «редакция советует» и «недавно
#: обновлённые». Книжных ссылок там под сотню, и рейтинг это далеко не
#: все они.
NOISY = f"""<html><body>
<div class="book-list-wrap"><ul><li><a class="name"
href="//www.qidian.com/book/1049874858/" data-bid="1049874858">旧日上单</a></li></ul></div>
<div class="edit-rec"><h3><a href="//www.qidian.com/book/1049366162/"
data-bid="1049366162">什么叫第五代火影非我莫属</a></h3></div>
{HOME}
<div class="update-list"><table><tr><td><a class="name"
href="//www.qidian.com/book/1049386949/" data-bid="1049386949">我能看到副本攻略</a></td>
</tr></table></div></body></html>"""

BOOK = """<html><head>
<meta property="og:novel:status" content="连载"/>
<meta property="og:novel:author" content="白刃斩春风"/>
<meta property="og:novel:book_name" content="我，赊刀人，斗鬼神"/>
<meta property="og:novel:latest_chapter_name" content="第51章 闺门旦（求追读）"/>
<meta property="og:description" content="запасное описание"/>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
{"@type":"Book","name":"我，赊刀人，斗鬼神",
"author":{"@type":"Person","name":"白刃斩春风"},"genre":"东方玄幻",
"description":"周羊穿越到一个名叫官村的小村子里，这里与世隔绝。",
"dateModified":"2026-08-23T11:00:00+08:00"}]}</script></head><body>
<h1 id="bookName">我，赊刀人，斗鬼神</h1>
<p class="book-attribute"><span>连载</span><a
href="//www.qidian.com/xuanhuan/">玄幻</a><a
href="//www.qidian.com/all/chanId21-subCateId8/">东方玄幻</a></p>
<p class="count"><em>13.33万</em><cite>字</cite><em>1.54万</em><cite>总推荐</cite></p>
<p class="catalog-header-infos"><span class="catalog-header-desc">连载共51章</span></p>
<p id="book-intro-detail">Первый абзац.<br>Второй абзац.</p></body></html>"""


class Fake:
    """Отдаёт заготовку и помнит, о чём спрашивали."""

    def __init__(self, page="", pages=None, fail=False):
        self.page = page
        self.pages = pages or {}
        self.fail = fail
        self.asked: list[str] = []

    def get_text(self, url, **kwargs):
        self.asked.append(url)
        if self.fail:
            raise HttpError("сайт не ответил")
        for mark, page in self.pages.items():
            if mark in url:
                return page
        return self.page

    def close(self):
        """Ручка закрывает клиента сама — подставной должен это уметь."""


class TestTheAddress(unittest.TestCase):
    """Доска и раздел — разные измерения, и оба видны в адресе."""

    def test_a_board_without_a_channel_asks_the_whole_site(self):
        self.assertEqual(qd.url_of("yuepiao"),
                         "https://www.qidian.com/rank/yuepiao/")

    def test_a_channel_is_added_the_way_the_site_does_it(self):
        """Номера разделов взяты из скрипта самого сайта: он переводит
        `/xuanhuan/` в `m.qidian.com/category/catid21/`."""
        self.assertEqual(qd.url_of("yuepiao", "xuanhuan"),
                         "https://www.qidian.com/rank/yuepiao/chn21/")
        self.assertEqual(qd.url_of("hotsales", "dushi"),
                         "https://www.qidian.com/rank/hotsales/chn4/")

    def test_every_board_builds_an_address(self):
        for board in qd.BOARDS:
            with self.subTest(board):
                self.assertTrue(qd.url_of(board).startswith(qd.SITE + "/rank/"))

    def test_every_channel_builds_an_address(self):
        for channel in qd.CHANNELS:
            with self.subTest(channel):
                qd.url_of("yuepiao", channel)

    def test_an_unknown_board_is_refused(self):
        with self.assertRaises(ValueError):
            qd.url_of("годовой")

    def test_an_unknown_channel_is_refused(self):
        """Опечатка в разделе не должна тихо превращаться во «все»."""
        with self.assertRaises(ValueError):
            qd.url_of("yuepiao", "детективы")

    def test_the_board_asked_for_is_the_board_fetched(self):
        client = Fake(NOISY)
        qd.fetch(client, board="collect", channel="lishi")
        self.assertIn("/rank/collect/chn5/", client.asked[0])


class TestTheRows(unittest.TestCase):
    """Что вытаскивается из строки рейтинга."""

    def rows(self, page=NOISY, board="yuepiao"):
        return qd.fetch(Fake(page), board=board)["rows"]

    def test_the_first_book_is_read_although_it_is_laid_out_differently(self):
        """У первой книги доски своя вёрстка: обложка, автор, жанр и
        число крупно. Разбор по классам обёртки её бы и потерял."""
        first = self.rows()[0]
        self.assertEqual(first.name, "武道！")
        self.assertEqual(first.book_id, "1049534879")

    def test_the_short_rows_are_read_too(self):
        names = [row.name for row in self.rows()]
        self.assertIn("急急如律令", names)
        self.assertIn("我绑定了夏弥", names)

    def test_the_number_comes_off_both_layouts(self):
        rows = self.rows()
        self.assertEqual(rows[0].score, 20717)
        self.assertEqual(rows[1].score, 16536)

    def test_the_number_is_signed_with_what_it_is(self):
        """«Билет» у Цидяня покупается подпиской — это не оценка."""
        self.assertIn("билет", self.rows()[0].metric)

    def test_a_board_without_numbers_does_not_invent_them(self):
        rows = qd.fetch(Fake(CHANNEL), board="hotsales")["rows"]
        self.assertIsNone(rows[0].score)
        self.assertEqual(rows[0].metric, "")

    def test_the_name_has_no_site_tail(self):
        """В `title` сайт дописывает своё: «夜无疆最新章节在线阅读»."""
        names = [row.name
                 for row in qd.fetch(Fake(CHANNEL), board="hotsales")["rows"]]
        self.assertIn("夜无疆", names)
        self.assertNotIn("夜无疆最新章节在线阅读", names)

    def test_author_and_genre_come_from_the_first_book(self):
        first = self.rows()[0]
        self.assertEqual(first.author, "田隶")
        self.assertEqual(first.category, "玄幻")

    def test_the_short_rows_do_not_borrow_someone_elses_author(self):
        """У коротких строк автора нет, и подставлять чужого нельзя."""
        self.assertEqual(self.rows()[1].author, "")

    def test_places_run_from_one_without_gaps(self):
        self.assertEqual([row.place for row in self.rows()], [1, 2, 3])

    def test_the_row_remembers_its_site(self):
        self.assertEqual(self.rows()[0].site, qd.SITE_KEY)

    def test_the_link_points_at_the_book(self):
        self.assertEqual(self.rows()[0].link,
                         "https://www.qidian.com/book/1049534879/")

    def test_the_cover_is_built_from_the_code(self):
        self.assertIn("1049534879", self.rows()[0].cover)


class TestOnlyTheRankingIsTaken(unittest.TestCase):
    """Главная — это ещё и реклама, советы редакции и «обновлённые».

    Книжных ссылок там под сотню. Взять их все значило бы выдать за
    рейтинг то, что рейтингом не является, — и человек читал бы этот
    список как «что сейчас читают».
    """

    def test_books_outside_the_ranking_blocks_are_left_alone(self):
        names = [row.name for row in qd.fetch(Fake(NOISY))["rows"]]
        self.assertNotIn("旧日上单", names)             # «本周强推»
        self.assertNotIn("什么叫第五代火影非我莫属", names)  # «编辑推荐»
        self.assertNotIn("我能看到副本攻略", names)        # «最近更新»

    def test_exactly_the_ranking_rows_are_taken(self):
        self.assertEqual(len(qd.fetch(Fake(NOISY))["rows"]), 3)

    def test_one_book_is_not_counted_twice(self):
        """У первой книги две ссылки: с названия и с обложки."""
        rows = qd.fetch(Fake(NOISY))["rows"]
        codes = [row.book_id for row in rows]
        self.assertEqual(len(codes), len(set(codes)))


class TestWhenItBreaks(unittest.TestCase):
    def test_a_page_without_ranking_blocks_is_a_named_failure(self):
        """Разбор написан по блокам с главной и со страницы раздела. На
        самой странице рейтинга вёрстка может быть другой — тогда чинить
        надо разбор, и об этом надо сказать, а не показать пустоту."""
        with self.assertRaises(SourceBroken) as caught:
            qd.fetch(Fake("<html><body><p>ничего</p></body></html>"))
        self.assertIn("rank-list", str(caught.exception))

    def test_a_site_that_does_not_answer_is_a_named_failure(self):
        with self.assertRaises(SourceBroken):
            qd.fetch(Fake(fail=True))


class TestTheVersion(unittest.TestCase):
    """Отпечаток среза: пересчитался рейтинг или нет."""

    def test_the_same_page_gives_the_same_version(self):
        self.assertEqual(qd.fetch(Fake(NOISY))["version"],
                         qd.fetch(Fake(NOISY))["version"])

    def test_a_different_top_changes_the_version(self):
        other = NOISY.replace("1049534879", "1049534880")
        self.assertNotEqual(qd.fetch(Fake(NOISY))["version"],
                            qd.fetch(Fake(other))["version"])


class TestTheBookPage(unittest.TestCase):
    """Раскрытая строка должна показывать больше самой строки."""

    def book(self, page=BOOK):
        return qd.book(Fake(page), "1050267828")

    def test_the_description_comes_back(self):
        self.assertIn("周羊穿越", self.book()["abstract"])

    def test_the_description_key_is_the_one_the_card_reads(self):
        self.assertIn("abstract", self.book())

    def test_the_structured_block_is_preferred_over_the_page(self):
        """`ld+json` сайт кладёт для поисковиков и меняет реже вёрстки."""
        self.assertNotIn("Первый абзац", self.book()["abstract"])

    def test_without_the_structured_block_the_page_still_reads(self):
        page = BOOK.replace('type="application/ld+json"', 'type="text/plain"')
        page = page.replace('property="og:description" content="запасное описание"',
                            'property="og:description" content=""')
        said = qd.book(Fake(page), "1050267828")["abstract"]
        self.assertIn("Первый абзац", said)
        self.assertIn("Второй абзац", said)

    def test_the_chapter_count_is_a_number_not_a_phrase(self):
        """Сайт пишет «连载共51章» — «выходит, всего 51 глава»."""
        self.assertEqual(self.book()["chapters"], 51)

    def test_chinese_numbers_are_understood(self):
        """«13.33万» — это тринадцать с третью десятков тысяч знаков."""
        self.assertEqual(self.book()["words"], 133300)

    def test_the_author_comes_back(self):
        self.assertEqual(self.book()["author"], "白刃斩春风")

    def test_the_genre_and_the_labels_come_back(self):
        tags = self.book()["tags"]
        self.assertIn("东方玄幻", tags)
        self.assertIn("玄幻", tags)

    def test_the_labels_have_no_repeats(self):
        tags = self.book()["tags"]
        self.assertEqual(len(tags), len(set(tags)))

    def test_the_latest_chapter_comes_back(self):
        self.assertIn("第51章", self.book()["last_chapter"])

    def test_a_page_that_does_not_open_is_a_named_failure(self):
        with self.assertRaises(SourceBroken):
            qd.book(Fake(fail=True), "1050267828")


class TestItIsOfferedAsARanking(unittest.TestCase):
    def setUp(self):
        from webapp import app as web

        self.web = web
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def sites(self):
        got = self.client.get("/api/rank/categories").get_json()
        return {site["key"]: site for site in got["sites"]}

    def test_the_site_is_listed(self):
        self.assertIn(qd.SITE_KEY, self.sites())

    def test_its_boards_reach_the_page(self):
        site = self.sites()[qd.SITE_KEY]
        self.assertEqual(len(site["boards"]), len(qd.BOARDS))

    def test_its_channels_reach_the_page(self):
        """Второй список — то, чего нет у остальных сайтов."""
        site = self.sites()[qd.SITE_KEY]
        self.assertEqual(len(site["channels"]), len(qd.CHANNELS))

    def test_other_sites_have_no_channels(self):
        """Пустая выпадашка на экране врёт, что выбор есть."""
        for key, site in self.sites().items():
            if key != qd.SITE_KEY:
                with self.subTest(key):
                    self.assertEqual(site["channels"], [])

    def test_it_says_it_cannot_be_downloaded_from(self):
        """За первыми главами начинается подписка. Обещать скачивание —
        значит отправить человека на вкладку качалки за невнятной
        ошибкой."""
        self.assertEqual(self.sites()[qd.SITE_KEY]["source"], "")

    def test_the_page_is_told_the_row_can_be_opened(self):
        self.assertTrue(self.sites()[qd.SITE_KEY]["details"])

    def test_the_about_says_downloading_is_not_offered(self):
        said = self.sites()[qd.SITE_KEY]["about"]
        self.assertIn("не умеет", said)


class TestTheChannelIsKeptApartInHistory(unittest.TestCase):
    """Срез по «городскому» — не тот же список, что по всем разделам.

    Сложить их в одну историю значило бы считать движение по местам
    между разными списками: книга «поднялась на десять мест», хотя её
    просто сравнили с чужим рейтингом.
    """

    def setUp(self):
        from webapp import app as web

        self.web = web

    def test_the_channel_becomes_the_category_of_the_snapshot(self):
        board, category = self.web._rank_board(
            {"board": "yuepiao", "channel": "dushi"}, qd.SITE_KEY)
        self.assertEqual(board, "yuepiao")
        self.assertEqual(category, "dushi")

    def test_an_unknown_channel_falls_back_to_all(self):
        _, category = self.web._rank_board(
            {"board": "yuepiao", "channel": "детективы"}, qd.SITE_KEY)
        self.assertEqual(category, "")

    def test_a_site_without_channels_ignores_the_field(self):
        from net.sources import mvlrank

        _, category = self.web._rank_board(
            {"board": "weekly", "channel": "dushi"}, mvlrank.SITE_KEY)
        self.assertEqual(category, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
