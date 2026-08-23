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

#: Страница самого рейтинга — `/rank/yuepiao/`. Разметка там совсем не
#: та, что в боковых блоках: у каждой книги описание, автор, поджанр,
#: статус, последняя глава и время. А число месячных билетов написано не
#: цифрами: сайт подменяет их знаками из неназначенной области Unicode и
#: рисует своим шрифтом, объявляя его тут же, в каждой строке.
#:
#: Коды знаков и имя семейства — с живой страницы. Что за цифры за ними
#: стоят, сказать нельзя: у нас есть страница, но нет файла шрифта. Для
#: проверки таблица задаётся ниже, в `SECRET`, и такой же собирается
#: подставной шрифт.
RANK_STYLE = ("<style>@font-face { font-family: qXUqdlfe; "
              "src: url('https://qdfepccdn.qidian.com/gtimg/qd_anti_spider/"
              "qXUqdlfe.eot?') format('eot'); "
              "src: url('https://qdfepccdn.qidian.com/gtimg/qd_anti_spider/"
              "qXUqdlfe.woff') format('woff'), "
              "url('https://qdfepccdn.qidian.com/gtimg/qd_anti_spider/"
              "qXUqdlfe.ttf') format('truetype'); }</style>")

RANK = f"""<html><body><div class="rank-body">
<div class="rank-view-list" id="rank-view-list">
<div class="book-img-text" id="book-img-text"><ul>
<li data-rid="1"><div class="book-img-box"><span class="rank-tag no1 ">1<cite>
</cite></span><a href="//www.qidian.com/book/1041637443/" target="_blank"
data-bid="1041637443"><img
src="//bookcover.yuewen.com/qdbimg/349573/1041637443/150.webp"
alt="捞尸人在线阅读"></a></div>
<div class="book-mid-info"><h2><a href="//www.qidian.com/book/1041637443/"
data-bid="1041637443" title="捞尸人最新章节在线阅读">捞尸人</a></h2>
<p class="author"><img src="//qdfepccdn.qidian.com/images/user.png"><a
class="name" title="纯洁滴小龙" href="//my.qidian.com/author/3780268/"
target="_blank">纯洁滴小龙</a><em>|</em><a href="//www.qidian.com/dushi"
target="_blank">都市</a><i>&#183;</i><a class="go-sub-type" data-typeid="4"
data-subtypeid="74" href="//www.qidian.com/all/chanId4-subCateId74/"
>异术超能</a><em>|</em><span>连载</span></p>
<p class="intro"> 人知鬼恐怖，鬼晓人心毒。这是一本传统灵异小说。 </p>
<p class="update"><a href="//www.qidian.com/chapter/1041637443/923933248/"
target="_blank" data-bid="1041637443">最新更新 第七百二十三章 阴家天才！</a>
<em>&#183;</em><span>2026-08-22 23:56</span></p></div>
<div class="book-right-info"><div class="total"><p><span>{RANK_STYLE}<span
class="qXUqdlfe">&#100386;&#100386;&#100379;&#100382;&#100386;</span></span>
月票</p></div><p class="btn"><a class="red-btn"
href="//www.qidian.com/book/1041637443/" target="_blank">书籍详情</a>
<a class="blue-btn add-book" href="javascript:" data-bookid="1041637443"
>加入书架</a></p></div></li>
<li data-rid="2"><div class="book-img-box"><span class="rank-tag no2 ">2<cite>
</cite></span><a href="//www.qidian.com/book/1035420986/" target="_blank"
data-bid="1035420986"><img
src="//bookcover.yuewen.com/qdbimg/349573/1035420986/150.webp"
alt="玄鉴仙族在线阅读"></a></div>
<div class="book-mid-info"><h2><a href="//www.qidian.com/book/1035420986/"
data-bid="1035420986" title="玄鉴仙族最新章节在线阅读">玄鉴仙族</a></h2>
<p class="author"><img src="//qdfepccdn.qidian.com/images/user.png"><a
class="name" title="季越人" href="//my.qidian.com/author/430784443/"
target="_blank">季越人</a><em>|</em><a href="//www.qidian.com/xianxia"
target="_blank">仙侠</a><i>&#183;</i><a class="go-sub-type"
href="//www.qidian.com/all/chanId22-subCateId18/">修真文明</a><em>|</em>
<span>连载</span></p>
<p class="intro"> 陆江仙熬夜猝死，残魂却附在了一面满是裂痕的青灰色铜镜上。 </p>
<p class="update"><a href="//www.qidian.com/chapter/1035420986/923898739/"
target="_blank">最新更新 剧情＋后续安排</a><em>&#183;</em>
<span>2026-08-22 19:39</span></p></div>
<div class="book-right-info"><div class="total"><p><span>{RANK_STYLE}<span
class="qXUqdlfe">&#100386;&#100381;&#100382;&#100381;&#100386;</span></span>
月票</p></div></li>
</ul></div></div>
<div class="page-box cf"><div class="pagination fr" id="page-container"
data-page="1" data-pagemax="25"><div class="lbf-pagination">
<ul class="lbf-pagination-item-list">
<li class="lbf-pagination-item"><a href="javascript:;"
class="lbf-pagination-prev lbf-pagination-disabled">&lt;</a></li>
<li class="lbf-pagination-item"><a data-page="2"
href="//www.qidian.com/rank/yuepiao/year2026-month08-page2/"
class="lbf-pagination-page">2</a></li>
<li class="lbf-pagination-item"><a
href="//www.qidian.com/rank/yuepiao/year2026-month08-page2/"
class="lbf-pagination-next ">&gt;</a></li>
</ul></div></div></div></div></body></html>"""

#: Вторая страница той же доски: две другие книги и никакой ссылки
#: «вперёд» — дальше листать некуда.
RANK2 = """<html><body><div id="rank-view-list"><div class="book-img-text">
<ul><li data-rid="21"><div class="book-img-box"><span class="rank-tag">21
</span><a href="//www.qidian.com/book/1010868264/" data-bid="1010868264"><img
src="//bookcover.yuewen.com/qdbimg/349573/1010868264/150.webp"></a></div>
<div class="book-mid-info"><h2><a href="//www.qidian.com/book/1010868264/"
data-bid="1010868264" title="诡秘之主最新章节在线阅读">诡秘之主</a></h2>
<p class="author"><a class="name" href="//my.qidian.com/author/4362088/"
>爱潜水的乌贼</a><em>|</em><a href="//www.qidian.com/xuanhuan">玄幻</a>
<em>|</em><span>完本</span></p><p class="intro"> 蒸汽与机械的浪潮中。 </p>
</div><div class="book-right-info"><div class="total"><p><span>1234</span>
月票</p></div></div></li>
<li data-rid="22"><div class="book-img-box"><a
href="//www.qidian.com/book/1735921/" data-bid="1735921"><img
src="//bookcover.yuewen.com/qdbimg/349573/1735921/150.webp"></a></div>
<div class="book-mid-info"><h2><a href="//www.qidian.com/book/1735921/"
data-bid="1735921" title="遮天最新章节在线阅读">遮天</a></h2>
<p class="author"><a class="name" href="//my.qidian.com/author/1/">辰东</a>
<em>|</em><a href="//www.qidian.com/xuanhuan">玄幻</a><em>|</em>
<span>完本</span></p></div><div class="book-right-info"><div class="total">
<p><span>567</span>月票</p></div></div></li>
</ul></div></div></body></html>"""

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


#: Какая подмена какой цифрой оказывается. Сами коды — с живой страницы,
#: а вот что за ними стоит, живьём не видел никто: файла шрифта у нас
#: нет. Поэтому таблицу задаём здесь и такой же собираем шрифт: проверять
#: надо разбор, а не угадывать чужие цифры.
SECRET = {"\U00018822": "2", "\U0001881b": "0",
          "\U0001881e": "7", "\U0001881d": "5"}

#: Что должно получиться из строк заготовки при такой таблице.
FIRST_NUMBER = 22072
SECOND_NUMBER = 25752


def anti_spider(secret: dict) -> bytes:
    """Шрифт, как у Цидяня: цифры под чужими кодами и без имён.

    Собирается из обычного системного шрифта: оставляем в нём десять
    цифр, переносим их под коды со страницы и обезличиваем имена глифов —
    ровно то, что делает сайт. Без такой подделки проверить расшифровку
    нечем: настоящего файла у нас нет.
    """
    import io

    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

    from net.sources import qidianfont

    font = TTFont(str(qidianfont.reference_fonts()[0]))
    cut = subset.Subsetter(options=subset.Options(
        glyph_names=True, layout_features=[], name_IDs=[], hinting=False))
    cut.populate(text="0123456789")
    cut.subset(font)

    by_digit = {digit: font.getBestCmap()[ord(digit)] for digit in "0123456789"}
    pairs = {ord(sign): by_digit[digit] for sign, digit in secret.items()}
    # Оставшиеся цифры тоже кладём в шрифт: сайт прячет все десять, и
    # разбор не должен полагаться на то, что их ровно четыре.
    spare = iter(range(0x18830, 0x18840))
    for digit, name in by_digit.items():
        if name not in pairs.values():
            pairs[next(spare)] = name

    for tag in ("GDEF", "GSUB", "GPOS", "kern"):
        if tag in font:
            del font[tag]
    order = font.getGlyphOrder()
    rename = {name: f"g{index:02d}" for index, name in enumerate(order)
              if name in by_digit.values()}
    font.setGlyphOrder([rename.get(name, name) for name in order])
    glyf = font["glyf"]
    glyf.glyphs = {rename.get(k, k): v for k, v in glyf.glyphs.items()}
    glyf.glyphOrder = font.getGlyphOrder()
    font["hmtx"].metrics = {rename.get(k, k): v
                            for k, v in font["hmtx"].metrics.items()}
    if "post" in font:
        font["post"].glyphOrder = None
    pairs = {code: rename.get(name, name) for code, name in pairs.items()}

    wide = CmapSubtable.newSubtable(12)
    wide.platformID, wide.platEncID, wide.format = 3, 10, 12
    wide.reserved, wide.length, wide.language, wide.nGroups = 0, 0, 0, 0
    wide.cmap = pairs
    font["cmap"].tables = [wide]

    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


class Answer:
    """Ответ на запрос файла — байтами, как у настоящего клиента."""

    def __init__(self, data: bytes):
        self.content = data


class Fake:
    """Отдаёт заготовку и помнит, о чём спрашивали."""

    def __init__(self, page="", pages=None, fail=False, font=b""):
        self.page = page
        self.pages = pages or {}
        self.fail = fail
        self.font = font
        self.asked: list[str] = []
        self.files: list[str] = []

    def get_text(self, url, **kwargs):
        self.asked.append(url)
        if self.fail:
            raise HttpError("сайт не ответил")
        for mark, page in self.pages.items():
            if mark in url:
                return page
        return self.page

    def get(self, url, *args, **kwargs):
        """Файл шрифта. Нет заготовки — значит, сайт его не отдал."""
        self.files.append(url)
        if not self.font:
            raise HttpError("шрифт не отдался")
        return Answer(self.font)

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
        """Страница без единой книги — это поломка, а не пустой рейтинг.
        В сообщении должен быть адрес: по нему видно, какую именно доску
        с каким разделом сайт не отдал."""
        with self.assertRaises(SourceBroken) as caught:
            qd.fetch(Fake("<html><body><p>ничего</p></body></html>"))
        self.assertIn(qd.url_of("yuepiao"), str(caught.exception))

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


class TestTheRankPage(unittest.TestCase):
    """Страница самой доски: там у книги есть всё, кроме числа.

    Боковые блоки на главной отдают три поля — место, название, число.
    На `/rank/…` сайт печатает книгу целиком, и брать оттуда одно
    название значило бы ходить за остальным второй раз, сто раз подряд.
    """

    def setUp(self):
        self.client = Fake(RANK, font=anti_spider(SECRET))
        self.rows = qd.fetch(self.client)["rows"]

    def test_the_books_of_the_board_are_read(self):
        self.assertEqual([r.name for r in self.rows], ["捞尸人", "玄鉴仙族"])

    def test_the_place_is_the_one_the_site_shows(self):
        self.assertEqual([r.place for r in self.rows], [1, 2])

    def test_the_author_comes_from_the_row(self):
        self.assertEqual(self.rows[0].author, "纯洁滴小龙")

    def test_the_genre_keeps_its_subgenre(self):
        """У Цидяня жанр двойной: 都市 · 异术超能. Второе — то, чем эта
        книга отличается от остальных городских, и терять его жалко."""
        self.assertEqual(self.rows[0].category, "都市 · 异术超能")

    def test_the_status_comes_back(self):
        self.assertEqual(self.rows[0].status, "连载")

    def test_the_description_comes_with_the_row(self):
        self.assertIn("人知鬼恐怖", self.rows[0].about)

    def test_the_last_chapter_has_no_service_words(self):
        """Сайт пишет «最新更新 第七百二十三章…» — «последнее обновление»
        тут подпись графы, а не часть названия главы."""
        self.assertEqual(self.rows[0].last_chapter, "第七百二十三章 阴家天才！")

    def test_the_update_time_comes_back(self):
        self.assertEqual(self.rows[0].updated, "2026-08-22 23:56")

    def test_the_link_and_the_cover_are_built_from_the_code(self):
        self.assertEqual(self.rows[0].book_id, "1041637443")
        self.assertIn("1041637443", self.rows[0].link)
        self.assertIn("1041637443", self.rows[0].cover)

    def test_the_name_has_no_site_tail(self):
        """В `title` сайт дописывает «最新章节在线阅读»."""
        for row in self.rows:
            self.assertNotIn("最新章节", row.name)


class TestTheHiddenNumber(unittest.TestCase):
    """Число доски спрятано шрифтом, и врать про него нельзя."""

    def test_the_number_is_read_through_the_font(self):
        rows = qd.fetch(Fake(RANK, font=anti_spider(SECRET)))["rows"]
        self.assertEqual([r.score for r in rows],
                         [FIRST_NUMBER, SECOND_NUMBER])

    def test_the_number_is_signed_the_way_the_site_signs_it(self):
        """Подпись 月票 стоит рядом с числом на странице — берём её
        оттуда, а не из своего списка досок."""
        rows = qd.fetch(Fake(RANK, font=anti_spider(SECRET)))["rows"]
        self.assertEqual(rows[0].metric, qd.UNITS["月票"])

    def test_the_font_is_fetched_once_for_the_whole_page(self):
        """Объявление шрифта сайт повторяет в каждой строке. Качать его
        сто раз на сотню книг незачем."""
        client = Fake(RANK, font=anti_spider(SECRET))
        qd.fetch(client)
        self.assertEqual(len(client.files), 1)

    def test_the_plain_font_is_asked_for_not_the_old_one(self):
        """`.eot` сайт перечисляет первым, но это формат для старого IE,
        и разобрать его нечем. Нужен `.ttf`."""
        client = Fake(RANK, font=anti_spider(SECRET))
        qd.fetch(client)
        self.assertTrue(client.files[0].endswith(".ttf"), client.files)

    def test_without_the_font_there_is_no_number_at_all(self):
        """Ноль здесь соврал бы: «ноль билетов» и «мы не смогли прочитать»
        — разные вещи, и в рейтинге их нельзя показывать одинаково."""
        rows = qd.fetch(Fake(RANK, font=b""))["rows"]
        self.assertEqual([r.score for r in rows], [None, None])
        self.assertEqual([r.metric for r in rows], ["", ""])

    def test_a_number_written_plainly_needs_no_font(self):
        """На части страниц число обычное. Тогда шрифт не нужен вовсе."""
        client = Fake(RANK2)
        rows = qd.fetch(client)["rows"]
        self.assertEqual([r.score for r in rows], [1234, 567])
        self.assertEqual(client.files, [])

    def test_a_plain_number_keeps_its_label_too(self):
        """Подпись стоит рядом с числом и когда цифры не подменены.
        Без неё строка показывала «★ 1234» — звёздочку вместо билетов."""
        rows = qd.fetch(Fake(RANK2))["rows"]
        self.assertEqual(rows[0].metric, qd.UNITS["月票"])

    def test_the_snapshot_counts_the_numbers_it_managed_to_read(self):
        good = qd.fetch(Fake(RANK, font=anti_spider(SECRET)))
        blind = qd.fetch(Fake(RANK, font=b""))
        self.assertEqual(good["decoded"], good["total"])
        self.assertEqual(blind["decoded"], 0)


class TestListingTheBoard(unittest.TestCase):
    """Страница отдаёт двадцать книг, а доска длиннее."""

    def test_the_next_page_is_taken_from_the_page_itself(self):
        """В адресе следующей страницы сидят год и месяц. Складывать его
        самим значило бы гадать, какой месяц сайт считает текущим."""
        client = Fake(pages={"page2": RANK2, "/rank/": RANK})
        rows = qd.fetch(client)["rows"]
        self.assertEqual([r.name for r in rows],
                         ["捞尸人", "玄鉴仙族", "诡秘之主", "遮天"])
        self.assertTrue(client.asked[1].endswith("page2/"), client.asked)

    def test_a_page_without_a_next_link_ends_the_listing(self):
        client = Fake(RANK2)
        qd.fetch(client)
        self.assertEqual(len(client.asked), 1)

    def test_the_place_stays_the_one_the_site_gave(self):
        """На второй странице у книг места 21 и 22 — это их места на
        доске, а не порядок в нашем списке. Перенумеровать их значило бы
        сделать двадцать первую книгу третьей."""
        client = Fake(pages={"page2": RANK2, "/rank/": RANK})
        rows = qd.fetch(client)["rows"]
        self.assertEqual([r.place for r in rows], [1, 2, 21, 22])

    def test_a_broken_second_page_keeps_the_first(self):
        """Половина рейтинга лучше, чем ничего: первая страница уже в
        руках, и терять её из-за оборванного листания незачем."""

        class Flaky(Fake):
            def get_text(self, url, **kwargs):
                self.asked.append(url)
                if "page2" in url:
                    raise HttpError("оборвалось")
                return RANK

        rows = qd.fetch(Flaky(font=anti_spider(SECRET)))["rows"]
        self.assertEqual(len(rows), 2)


class TestWhyItCameBackEmpty(unittest.TestCase):
    """Пустой ответ бывает по трём разным причинам, и лечатся они
    по-разному. Сообщение обязано их различать: «не разобралось» —
    это не ответ, по нему нечего чинить.

    Скрипт капчи в признаки не годится: `turing.captcha.qcloud.com` и
    зонд `probev3.js` висят в шапке **любой** страницы Цидяня, в том
    числе совершенно рабочей. На этом и стоит первая проверка.
    """

    HEAD = ('<script src="/C2WF946J0/probev3.js"></script><head>'
            '<script async src="https://turing.captcha.qcloud.com/TCaptcha.js">'
            '</script><title>{title}</title></head>')

    def guard_page(self):
        """Проверка на робота: капча есть, рейтинга нет."""
        return ("<html>" + self.HEAD.format(title="安全验证")
                + "<body><div>请输入验证码</div></body></html>")

    def changed_page(self):
        """Страница рейтинга целиком — но списка книг в ней нет."""
        return ("<html>" + self.HEAD.format(title="月票榜")
                + '<body><div class="rank-box"><div class="rank-nav-list">'
                + '<a href="/rank/yuepiao/">月票榜</a></div>'
                + '<div class="rank-body"><div class="какая-то-новая-вёрстка">'
                + "книги теперь тут</div></div></div>"
                + "<i>" + "х" * 30_000 + "</i></body></html>")

    def test_a_challenge_is_named_a_challenge(self):
        with self.assertRaises(SourceBroken) as caught:
            qd.fetch(Fake(self.guard_page()))
        said = str(caught.exception)
        self.assertIn("проверк", said.lower())
        self.assertIn("прокси", said.lower())

    def test_a_changed_layout_is_not_blamed_on_the_captcha(self):
        """Тут и капча в шапке, и размер большой — но рамка рейтинга
        на месте, значит сайт ответил нам, а разбирать стало нечем."""
        with self.assertRaises(SourceBroken) as caught:
            qd.fetch(Fake(self.changed_page()))
        said = str(caught.exception)
        self.assertIn("вёрстк", said.lower())
        self.assertNotIn("прокси", said.lower())

    def test_a_missing_page_says_to_try_another_board(self):
        """`/rank/yuepiao/chn4/` сайт отдаёт как «страницы нет». Совет
        тут другой: не менять прокси, а взять другую доску."""
        page = ("<html>" + self.HEAD.format(title="错误页")
                + "<body>页面不存在</body></html>")
        with self.assertRaises(SourceBroken) as caught:
            qd.fetch(Fake(page), board="yuepiao", channel="dushi")
        said = str(caught.exception)
        self.assertIn("раздел", said.lower())
        self.assertNotIn("прокси", said.lower())

    def test_the_message_names_the_address_and_the_size(self):
        """С адресом и размером можно идти дальше; без них — некуда."""
        with self.assertRaises(SourceBroken) as caught:
            qd.fetch(Fake(self.guard_page()), board="readindex")
        said = str(caught.exception)
        self.assertIn(qd.url_of("readindex"), said)
        self.assertIn(str(len(self.guard_page())), said)


class TestHowItKnocks(unittest.TestCase):
    """Цидянь сидит за защитой Tencent, и запрос без единого заголовка
    она встречает проверкой. Приходим как живой читатель."""

    def test_the_page_is_asked_for_with_browser_headers(self):
        class Watching(Fake):
            def __init__(self, page):
                super().__init__(page)
                self.headers = []

            def get_text(self, url, **kwargs):
                self.headers.append(kwargs.get("headers") or {})
                return super().get_text(url, **kwargs)

        client = Watching(RANK2)
        qd.fetch(client)
        sent = client.headers[0]
        self.assertIn("qidian.com", sent.get("Referer", ""))
        self.assertIn("zh", sent.get("Accept-Language", ""))
