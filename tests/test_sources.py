"""Второй источник и рейтинг Фанкью (часть 5 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net import sources  # noqa: E402
from net.sources import rank as rank_net  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402
from net.sources.fanqie import FanqieSource, PaidChapter  # noqa: E402
from ops import rank as rank_op  # noqa: E402


class FakeClient:
    """Отдаёт заготовленные ответы по адресу."""

    def __init__(self, pages=None):
        self.pages = pages or {}
        self.asked = []

    def get_text(self, url, params=None, headers=None):
        self.asked.append(url)
        for part, answer in self.pages.items():
            if part in url:
                return answer
        raise AssertionError(f"Нет заготовки для {url}")


def next_data(payload: dict) -> str:
    return ('<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload, ensure_ascii=False) + "</script></html>")


def state_page(payload: dict) -> str:
    """Страница в том виде, в каком её отдаёт сайт сейчас.

    Данные лежат в `window.__INITIAL_STATE__`; прежний `__NEXT_DATA__`
    сайт не отдаёт уже давно, и книга из-за этого приезжала с нулём глав.
    """
    return ("<html><body><script>window.__INITIAL_STATE__="
            + json.dumps(payload, ensure_ascii=False)
            + ";</script></body></html>")


class TestRegistry(unittest.TestCase):
    """Источники перечисляются в одном месте."""

    def test_both_sources_are_listed(self):
        keys = [s.key for s in sources.all_sources()]
        self.assertIn("mvlempyr", keys)
        self.assertIn("fanqie", keys)

    def test_default_is_the_first(self):
        self.assertEqual(sources.get("").key, sources.all_sources()[0].key)

    def test_unknown_source_is_refused(self):
        with self.assertRaises(SourceBroken):
            sources.get("литрес")

    def test_every_source_answers_the_interface(self):
        for source in sources.all_sources():
            data = source.as_dict()
            self.assertTrue(data["name"], source.key)
            self.assertTrue(data["hint"], source.key)


class TestSourceHints(unittest.TestCase):
    """5.1: подсказка и заполнитель зависят от источника."""

    def test_placeholder_differs_by_source(self):
        seen = {s.key: s.as_dict()["placeholder"] for s in sources.all_sources()}
        self.assertEqual(seen["mvlempyr"], "insect-tamers-ascension")
        self.assertEqual(seen["fanqie"], "7143038691944959011")

    def test_explanation_differs_too(self):
        hints = {s.key: s.as_dict()["hint"] for s in sources.all_sources()}
        self.assertIn("слаг", hints["mvlempyr"])
        self.assertIn("/page/", hints["fanqie"])

    def test_placeholder_falls_back_to_the_hint(self):
        """Источник без своего заполнителя не остаётся с пустым полем."""
        from net.sources.base import Source

        class Bare(Source):
            key, name, hint = "голый", "Голый", "что-нибудь"

        self.assertEqual(Bare().as_dict()["placeholder"], "что-нибудь")


class TestRankScreenIsWired(unittest.TestCase):
    """Разметка рейтинга без своего кода — мёртвая."""

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent.parent / "webapp" / "static"
        cls.html = (root / "index.html").read_text(encoding="utf-8")
        cls.js = (root / "tabs.js").read_text(encoding="utf-8")

    def test_every_control_has_a_handler(self):
        for name in ("rkRefresh", "rkTranslate", "rkFilter"):
            self.assertIn(f'id="{name}"', self.html, name)
            self.assertIn(f"$('{name}')", self.js, name)

    def test_downloading_goes_through_the_downloader_tab(self):
        """Своего загрузчика у рейтинга больше нет: он умел меньше, а
        диапазон глав в качалке при этом оставался от прошлого запуска."""
        self.assertIn("function rkPick(row)", self.js)
        self.assertIn("goTab('download')", self.js)

    def test_source_picker_is_filled_by_the_server(self):
        self.assertIn("function loadSources(", self.js)
        self.assertIn("call('/api/sources')", self.js)


class TestFanqieCode(unittest.TestCase):
    """Код книги из ссылки или из самого кода."""

    def setUp(self):
        self.source = FanqieSource()

    def test_link(self):
        self.assertEqual(
            self.source.code_of("https://fanqienovel.com/page/7143038691944959011"),
            "7143038691944959011")

    def test_bare_code(self):
        self.assertEqual(self.source.code_of("7143038691944959011"),
                         "7143038691944959011")

    def test_link_with_tail(self):
        self.assertEqual(
            self.source.code_of("https://fanqienovel.com/page/7143038691944959011?enter_from=main"),
            "7143038691944959011")

    def test_nonsense_is_refused(self):
        for bad in ("", "какая-то книга", "https://example.com/page/x"):
            with self.assertRaises(ValueError):
                self.source.code_of(bad)


class TestFanqieBook(unittest.TestCase):
    def setUp(self):
        self.source = FanqieSource()

    def test_book_is_read_from_the_data_block(self):
        client = FakeClient({"/page/": next_data({
            "props": {"pageProps": {"bookInfo": {
                "bookName": "剑来", "author": "烽火戏诸侯",
                "serialCount": 300, "creationStatus": "连载"}}}})})
        novel = self.source.find(client, "7143038691944959011")

        self.assertEqual(novel.name, "剑来")
        self.assertEqual(novel.author, "烽火戏诸侯")
        self.assertEqual(novel.total_chapters, 300)
        self.assertEqual(novel.language, "zh")

    def test_book_is_read_from_the_shape_the_site_uses_now(self):
        """Сайт отдаёт `__INITIAL_STATE__`, а модуль искал `__NEXT_DATA__`.

        Поиск не находил ничего, уходил в запасной разбор заголовка — и
        книга на тысячу глав приезжала с «0 глав». Качать при этом нечего:
        диапазон получался пустым.
        """
        client = FakeClient({"/page/": state_page({"page": {
            "bookName": "末日生存方案供应商", "author": "板面王仔",
            "creationStatus": 0, "chapterTotal": 1272,
            "chapterListWithVolume": [[
                {"itemId": "7496029406847042073", "title": "第1章"},
                {"itemId": "7496031021620544025", "title": "第2章"},
            ]]}})})
        novel = self.source.find(client, "7496026299845053465")

        self.assertEqual(novel.name, "末日生存方案供应商")
        self.assertEqual(novel.total_chapters, 1272)
        self.assertEqual(novel.author, "板面王仔")

    def test_a_finished_book_is_not_called_ongoing(self):
        """Признак завершённости равен нулю, а ноль — ложь.

        Через `or ""` он превращался в пустоту, и любая книга оказывалась
        «продолжается».
        """
        client = FakeClient({"/page/": state_page({"page": {
            "bookName": "книга", "creationStatus": 0, "chapterTotal": 5}})})
        self.assertEqual(self.source.find(client, "7143038691944959011").status,
                         "завершена")

    def test_chapters_are_counted_when_the_site_gives_no_total(self):
        """Счётчика нет — считаем по оглавлению, но не отдаём ноль."""
        client = FakeClient({"/page/": state_page({"page": {
            "bookName": "книга",
            "chapterListWithVolume": [[
                {"itemId": "700000000000000001", "title": "Раз"},
                {"itemId": "700000000000000002", "title": "Два"},
            ]]}})})
        self.assertEqual(
            self.source.find(client, "7143038691944959011").total_chapters, 2)

    def test_title_is_the_fallback(self):
        client = FakeClient({"/page/": "<html><title>剑来_番茄小说</title></html>"})
        self.assertEqual(self.source.find(client, "7143038691944959011").name, "剑来")

    def test_unreadable_page_says_the_source_changed(self):
        """«Источник изменился» лечится правкой модуля, а не повтором."""
        client = FakeClient({"/page/": "<html><body>ничего</body></html>"})
        with self.assertRaises(SourceBroken):
            self.source.find(client, "7143038691944959011")

    def test_the_cover_comes_along_with_the_book(self):
        """Из рейтинга обложка приходила, а по коду — нет.

        Одна и та же книга выглядела по-разному в зависимости от того,
        как её открыли: карточкой с картинкой или голой строкой.
        """
        client = FakeClient({"/page/": state_page({"page": {
            "bookName": "книга", "chapterTotal": 5,
            "thumbUri": "https://p.example/cover.jpeg"}})})
        novel = self.source.find(client, "7143038691944959011")

        self.assertEqual(novel.cover, "https://p.example/cover.jpeg")
        self.assertEqual(novel.to_dict()["cover"], "https://p.example/cover.jpeg")

    def test_a_book_without_a_cover_is_not_a_breakage(self):
        client = FakeClient({"/page/": state_page({"page": {
            "bookName": "книга", "chapterTotal": 5}})})
        self.assertEqual(self.source.find(client, "7143038691944959011").cover,
                         "")


class TestFanqieToc(unittest.TestCase):
    def setUp(self):
        self.source = FanqieSource()

    def book(self, count=5):
        return next_data({"props": {"pageProps": {"bookInfo": {
            "bookName": "книга", "serialCount": count,
            "chapterListWithVolume": [[
                {"itemId": str(700000000000000000 + n), "title": f"第{n}章"}
                for n in range(1, count + 1)]]}}}})

    def novel_of(self, client):
        return self.source.find(client, "7143038691944959011")

    def test_chapters_are_numbered_in_reading_order(self):
        client = FakeClient({"/page/": self.book(5)})
        toc = self.source.toc(client, self.novel_of(client))

        self.assertEqual([c.number for c in toc.chapters], [1, 2, 3, 4, 5])
        self.assertEqual(toc.chapters[0].ch_name, "第1章")
        self.assertTrue(toc.chapters[0].link.endswith("/reader/700000000000000001"))

    def test_range_is_respected(self):
        client = FakeClient({"/page/": self.book(10)})
        toc = self.source.toc(client, self.novel_of(client), first=3, last=5)
        self.assertEqual([c.number for c in toc.chapters], [3, 4, 5])

    def test_asking_beyond_the_book_is_reported_not_invented(self):
        client = FakeClient({"/page/": self.book(3)})
        toc = self.source.toc(client, self.novel_of(client), first=1, last=6)
        self.assertEqual([c.number for c in toc.chapters], [1, 2, 3])
        self.assertEqual(toc.missing, [4, 5, 6])

    def test_markup_is_the_fallback(self):
        html = ('<html><body>'
                '<a href="/reader/700000000000000001">第1章 начало</a>'
                '<a href="/reader/700000000000000002">第2章 дальше</a>'
                '</body></html>')
        client = FakeClient({"/page/": html})
        from mvl.api import Novel

        toc = self.source.toc(client, Novel(code=1, name="к", slug="1",
                                            total_chapters=2))
        self.assertEqual(len(toc.chapters), 2)

    def test_empty_toc_says_the_source_changed(self):
        client = FakeClient({"/page/": "<html><body>пусто</body></html>"})
        from mvl.api import Novel

        with self.assertRaises(SourceBroken):
            self.source.toc(client, Novel(code=1, name="к", slug="1",
                                          total_chapters=1))


class TestFanqieChapter(unittest.TestCase):
    def setUp(self):
        self.source = FanqieSource()

    def chapter(self, number=1, item_id=700000000000000001):
        from mvl.api import Chapter

        return Chapter(number=number, post_id=item_id, ch_name="第1章")

    def answer(self, content, title="第1章", code=0):
        return json.dumps({"code": code, "data": {"chapterData": {
            "title": title, "content": content}}}, ensure_ascii=False)

    def test_text_is_extracted_from_paragraphs(self):
        client = FakeClient({"/api/reader/full": self.answer(
            "<p>Первый абзац.</p><p>Второй абзац.</p>")})
        title, text = self.source.chapter(client, self.chapter())

        self.assertEqual(title, "第1章")
        self.assertEqual(text, "Первый абзац.\n\nВторой абзац.")

    def test_entities_are_decoded(self):
        client = FakeClient({"/api/reader/full": self.answer(
            "<p>&quot;Привет&quot; &amp; пока</p>")})
        self.assertIn('"Привет" & пока', self.source.chapter(client, self.chapter())[1])

    def test_paid_chapter_is_skipped_not_saved(self):
        """Огрызок вместо главы хуже пропуска: он выглядит как настоящая."""
        client = FakeClient({"/api/reader/full": self.answer("本章为付费章节")})
        with self.assertRaises(PaidChapter):
            self.source.chapter(client, self.chapter())

    def test_empty_content_is_paid_too(self):
        client = FakeClient({"/api/reader/full": self.answer("")})
        with self.assertRaises(PaidChapter):
            self.source.chapter(client, self.chapter())

    def test_error_code_says_the_source_changed(self):
        client = FakeClient({"/api/reader/full": self.answer("<p>текст</p>", code=1)})
        with self.assertRaises(SourceBroken):
            self.source.chapter(client, self.chapter())

    def test_not_json_falls_back_to_the_reading_page(self):
        """Внутренний адрес отвечает то JSON, то страницей входа.

        Ронять на этом всю книгу нельзя: тот же текст лежит на странице
        чтения, только берётся медленнее.
        """
        client = FakeClient({
            "/api/reader/full": "<html>лишь бы не json</html>",
            "/reader/": state_page({"reader": {"chapterData": {
                "title": "Глава 1", "content": "<p>Текст главы.</p>"}}}),
        })
        title, text = self.source.chapter(client, self.chapter())

        self.assertEqual(title, "Глава 1")
        self.assertEqual(text, "Текст главы.")

    def test_when_neither_the_api_nor_the_page_gives_text(self):
        """Оба пути пусты — вот это уже поломка, и о ней надо сказать."""
        client = FakeClient({
            "/api/reader/full": "<html>лишь бы не json</html>",
            "/reader/": "<html>и тут пусто</html>",
        })
        with self.assertRaises((SourceBroken, PaidChapter)):
            self.source.chapter(client, self.chapter())

    def test_chapter_without_an_id_is_refused(self):
        from mvl.api import Chapter

        with self.assertRaises(SourceBroken):
            self.source.chapter(FakeClient(), Chapter(number=1))


def initial_state(payload: dict) -> str:
    """Страница рейтинга: данные лежат в `window.__INITIAL_STATE__`."""
    return ("<html><body><script>window.__INITIAL_STATE__="
            + json.dumps(payload, ensure_ascii=False) + ";</script></body></html>")


def rank_page(count=3, version="1755200000", stats="08-14"):
    return initial_state({"rank": {
        "total_num": 100,
        "defaultPage": 1,
        "rankVersion": version,
        "book_list": [
            {"bookId": f"70000000000000000{n}", "bookName": f"книга {n}",
             "author": f"автор {n}", "read_count": 430187 - n,
             "currentPos": n, "rankPosDiff": n - 2, "wordNumber": 300000 + n,
             "creationStatus": "1", "lastChapterTitle": f"Глава {n}"}
            for n in range(1, count + 1)],
    }}).replace("</body>", f"<div>统计至 {stats} 24:00</div></body>")


class TestRankParsing(unittest.TestCase):
    """5.2: данные берём из объекта страницы, а не из вёрстки."""

    def test_rows_are_read(self):
        found = rank_net.parse(rank_page(3))
        self.assertEqual(len(found["rows"]), 3)
        self.assertEqual(found["rows"][0].name, "книга 1")
        self.assertEqual(found["rows"][0].place, 1)

    def test_exact_reader_count(self):
        """Сайт отдаёт точное число, а не «43万»."""
        self.assertEqual(rank_net.parse(rank_page(1))["rows"][0].readers, 430186)

    def test_site_movement_is_taken_as_is(self):
        """Сайт считает динамику сам — свою поверх городить незачем."""
        rows = rank_net.parse(rank_page(3))["rows"]
        self.assertEqual(rows[0].diff, -1)
        self.assertEqual(rows[2].diff, 1)

    def test_extra_fields_are_kept(self):
        row = rank_net.parse(rank_page(1))["rows"][0]
        self.assertEqual(row.words, 300001)
        self.assertEqual(row.status, "продолжается")
        self.assertEqual(row.last_chapter, "Глава 1")

    def test_version_and_date_are_saved(self):
        """По версии видно, обновился ли рейтинг; дата точнее даты запроса."""
        found = rank_net.parse(rank_page(1, version="177", stats="08-14"))
        self.assertEqual(found["version"], "177")
        self.assertEqual(found["stats_date"], "08-14")

    def test_total_says_how_many_there_are(self):
        self.assertEqual(rank_net.parse(rank_page(10))["total"], 100)

    def test_limit_is_respected(self):
        self.assertEqual(len(rank_net.parse(rank_page(80), limit=50)["rows"]), 50)

    def test_chinese_numbers_are_understood(self):
        """«12.3万» — это сто двадцать три тысячи, а не двенадцать."""
        self.assertEqual(rank_net._readers("12.3万"), 123000)
        self.assertEqual(rank_net._readers("1亿"), 100_000_000)
        self.assertEqual(rank_net._readers(""), 0)

    def test_link_leads_to_the_book(self):
        row = rank_net.parse(rank_page(1))["rows"][0]
        self.assertTrue(row.as_dict()["link"].endswith("/page/700000000000000001"))


class TestRankDiagnosis(unittest.TestCase):
    """Поломка описывается подробностями, а не общими словами."""

    def test_missing_state_says_so(self):
        with self.assertRaises(rank_net.Diagnosis) as caught:
            rank_net.parse("<html><body>ничего похожего</body></html>")
        self.assertFalse(caught.exception.details["state_found"])
        self.assertIn("page_size", caught.exception.details)

    def test_broken_json_is_told_apart(self):
        html = "<html><script>window.__INITIAL_STATE__={сломано};</script></html>"
        with self.assertRaises(rank_net.Diagnosis) as caught:
            rank_net.parse(html)
        self.assertTrue(caught.exception.details["state_found"])

    def test_empty_list_is_not_an_empty_table(self):
        """Пустую таблицу приняли бы за пустой рейтинг."""
        with self.assertRaises(rank_net.Diagnosis) as caught:
            rank_net.parse(initial_state({"rank": {"book_list": []}}))
        self.assertEqual(caught.exception.details["book_list"], 0)

    def test_unknown_audience_is_refused(self):
        with self.assertRaises(ValueError):
            rank_net.fetch(FakeClient(), audience="непонятно")

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            rank_net.fetch(FakeClient(), kind="9")


class TestCategories(unittest.TestCase):
    """Категории забираются с сайта, перевод зашит."""

    def test_address_is_built_from_three_numbers(self):
        from net.sources import categories

        self.assertEqual(categories.path("1", "2", "1141"), "/rank/1_2_1141")

    def test_four_boards(self):
        from net.sources import categories

        self.assertEqual(len(categories.BOARDS), 4)

    def test_names_are_translated_without_the_model(self):
        from net.sources import categories

        found = categories.translate("1141", "西方奇幻")
        self.assertEqual(found["name"], "Западное фэнтези")
        self.assertTrue(found["translated"])

    def test_unknown_category_shows_the_original_and_is_marked(self):
        from net.sources import categories

        found = categories.translate("99999", "新分类")
        self.assertEqual(found["name"], "新分类")
        self.assertFalse(found["translated"])

    def test_list_is_read_from_the_page(self):
        html = initial_state({"rank": {"rankCategoryTypeList": {
            "male": [{"id": 1141, "name": "西方奇幻"}, {"id": 8, "name": "科幻末世"}],
            "female": [{"id": 248, "name": "玄幻言情"}],
        }}})
        found = rank_net.category_list(html)
        self.assertEqual([c["id"] for c in found["1"]], ["1141", "8"])
        self.assertEqual(found["1"][0]["name"], "Западное фэнтези")
        self.assertEqual([c["id"] for c in found["0"]], ["248"])

    def test_menu_is_the_fallback(self):
        html = ('<html><div class="muye-rank-menu">'
                '<a href="/rank/1_2_1141">a</a><a href="/rank/1_2_8">b</a>'
                '<a href="/rank/0_2_248">c</a></div></html>')
        found = rank_net.category_list(html)
        self.assertEqual([c["id"] for c in found["1"]], ["1141", "8"])

    def test_known_list_is_the_last_resort(self):
        """Пустой выбор хуже известного набора."""
        found = rank_net.category_list("<html></html>")
        self.assertTrue(found["1"])
        self.assertTrue(found["0"])


class TestFontDecoding(unittest.TestCase):
    """Три поля зашифрованы шрифтом, всё остальное чистое."""

    def setUp(self):
        from net.sources import fanqiefont

        self.font = fanqiefont
        self.addCleanup(fanqiefont.forget)

    def test_private_area_is_detected(self):
        self.assertTrue(self.font.has_secret("книга\ue123"))
        self.assertFalse(self.font.has_secret("обычное название"))

    def test_decoding_replaces_by_the_table(self):
        table = {"\ue123": "剑", "\ue124": "来"}
        self.assertEqual(self.font.decode("\ue123\ue124", table), "剑来")

    def test_unknown_glyph_stays_as_is(self):
        """Строка с одним пропуском лучше, чем никакой."""
        self.assertEqual(self.font.decode("\ue123\ue999", {"\ue123": "剑"}),
                         "剑\ue999")

    def test_without_a_table_text_is_untouched(self):
        self.assertEqual(self.font.decode("\ue123", None), "\ue123")

    def test_font_address_is_read_from_the_styles(self):
        css = ("@font-face{font-family:'DNMrHsV173Pd4pgy';"
               "src:url(https://lf6-awef.bytetos.com/obj/awesome-font/c/x.woff2)}")
        family, url = self.font.font_of(css)
        self.assertEqual(family, "DNMrHsV173Pd4pgy")
        self.assertTrue(url.endswith(".woff2"))

    def test_missing_package_is_explained(self):
        with self.assertRaises(self.font.FontUnavailable):
            self.font.table_for("никому не известный шрифт")

    def test_rows_are_marked_when_names_stay_secret(self):
        page = initial_state({"rank": {"book_list": [
            {"bookId": "700000000000000001", "bookName": "\ue123\ue124",
             "author": "\ue200", "read_count": 100},
        ]}})
        row = rank_net.parse(page)["rows"][0]
        self.assertTrue(row.secret)
        # Всё остальное приходит чистым и работает без расшифровки.
        self.assertEqual(row.book_id, "700000000000000001")
        self.assertEqual(row.readers, 100)


class TestRankHistory(unittest.TestCase):
    """Своя история: то, чего на сайте нет."""

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._saved = rank_op.RANK_DIR
        rank_op.RANK_DIR = Path(self._dir.name)
        self.addCleanup(setattr, rank_op, "RANK_DIR", self._saved)

    def rows(self, order, readers=None):
        readers = readers or {}
        return [rank_net.RankRow(place=i, book_id=str(book), name=f"книга {book}",
                                 readers=readers.get(book, 1000))
                for i, book in enumerate(order, 1)]

    def test_snapshot_round_trip(self):
        rank_op.save(self.rows([1, 2, 3]), day="2026-01-01")
        found = rank_op.load("2026-01-01")
        self.assertEqual([r.book_id for r in found.rows], ["1", "2", "3"])

    def test_same_day_is_overwritten_not_doubled(self):
        """Иначе «за сутки» считалось бы от случайного среза."""
        rank_op.save(self.rows([1, 2]), day="2026-01-01")
        rank_op.save(self.rows([3]), day="2026-01-01")
        self.assertEqual(rank_op.days(), ["2026-01-01"])
        self.assertEqual(len(rank_op.load("2026-01-01").rows), 1)

    def test_boards_are_kept_apart(self):
        """У мужского и женского рейтинга своя динамика."""
        rank_op.save(self.rows([1]), board="all", day="2026-01-01")
        rank_op.save(self.rows([2]), board="male", day="2026-01-01")
        self.assertEqual(rank_op.days("all"), ["2026-01-01"])
        self.assertEqual(rank_op.days("male"), ["2026-01-01"])
        self.assertEqual(rank_op.load("2026-01-01", "male").rows[0].book_id, "2")

    def test_movement_up_and_down(self):
        rank_op.save(self.rows([1, 2, 3]), day="2026-01-01")
        rank_op.save(self.rows([3, 1, 2]), day="2026-01-02")

        moved = rank_op.movement(today="2026-01-02")
        by_id = {r["book_id"]: r for r in moved["rows"]}
        self.assertEqual(by_id["3"]["day"], 2)    # была третьей, стала первой
        self.assertEqual(by_id["1"]["day"], -1)
        self.assertEqual(by_id["2"]["day"], -1)

    def test_new_in_the_top_is_marked(self):
        rank_op.save(self.rows([1, 2]), day="2026-01-01")
        rank_op.save(self.rows([1, 2, 9]), day="2026-01-02")

        moved = rank_op.movement(today="2026-01-02")
        by_id = {r["book_id"]: r for r in moved["rows"]}
        self.assertTrue(by_id["9"]["is_new"])
        self.assertFalse(by_id["1"]["is_new"])

    def test_week_is_taken_from_the_nearest_older_snapshot(self):
        """Срезы снимаются руками — ровно неделю назад могло не быть."""
        rank_op.save(self.rows([5, 1]), day="2026-01-01")
        rank_op.save(self.rows([1, 5]), day="2026-01-09")

        moved = rank_op.movement(today="2026-01-09")
        by_id = {r["book_id"]: r for r in moved["rows"]}
        self.assertEqual(by_id["1"]["week"], 1)
        self.assertTrue(moved["has_week"])

    def test_readers_gain_is_the_point_not_the_absolute(self):
        rank_op.save(self.rows([1], {1: 10_000}), day="2026-01-01")
        rank_op.save(self.rows([1], {1: 25_000}), day="2026-01-09")

        moved = rank_op.movement(today="2026-01-09")
        self.assertEqual(moved["rows"][0]["readers_gain"], 15_000)

    def test_holding_counts_days_in_a_row(self):
        for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
            rank_op.save(self.rows([1, 2]), day=day)
        moved = rank_op.movement(today="2026-01-03")
        self.assertEqual(moved["rows"][0]["holding"], 3)

    def test_one_day_of_history_says_so(self):
        rank_op.save(self.rows([1]), day="2026-01-01")
        moved = rank_op.movement(today="2026-01-01")
        self.assertFalse(moved["has_week"])
        self.assertIn("несколько дней", moved["note"])

    def test_empty_history_is_not_an_error(self):
        moved = rank_op.movement()
        self.assertEqual(moved["rows"], [])
        self.assertIn("Истории пока нет", moved["note"])

    def test_old_snapshots_are_trimmed(self):
        for n in range(1, 8):
            rank_op.save(self.rows([1]), day=f"2026-01-0{n}")
        rank_op.trim(keep=3)
        self.assertEqual(len(rank_op.days()), 3)


class TestTitles(unittest.TestCase):
    """Перевод названий: кэш по book_id."""

    def setUp(self):
        from ops import titles

        self.titles = titles
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._saved = titles.TITLES_FILE
        titles.TITLES_FILE = Path(self._dir.name) / "titles.json"
        self.addCleanup(setattr, titles, "TITLES_FILE", self._saved)

    class FakeLlm:
        def __init__(self, answer):
            self.answer = answer
            self.calls = 0

        def generate(self, prompt, json_only=True, model=""):
            self.calls += 1
            return self.answer

    def rows(self, count=2):
        return [rank_net.RankRow(book_id=str(n), name=f"书{n}")
                for n in range(1, count + 1)]

    def test_translation_is_remembered(self):
        client = self.FakeLlm('{"1": "Книга один", "2": "Книга два"}')
        result = self.titles.translate(self.rows(2), client)

        self.assertEqual(result["titles"]["1"], "Книга один")
        self.assertEqual(result["translated"], 2)
        self.assertEqual(self.titles.known()["2"], "Книга два")

    def test_known_titles_are_not_asked_again(self):
        client = self.FakeLlm('{"1": "Книга один", "2": "Книга два"}')
        self.titles.translate(self.rows(2), client)
        again = self.FakeLlm("{}")
        result = self.titles.translate(self.rows(2), again)

        self.assertEqual(again.calls, 0)
        self.assertEqual(result["cached"], 2)
        self.assertEqual(result["titles"]["1"], "Книга один")

    def test_force_asks_again(self):
        client = self.FakeLlm('{"1": "Первый", "2": "Второй"}')
        self.titles.translate(self.rows(2), client)
        again = self.FakeLlm('{"1": "Иначе", "2": "И так"}')
        self.titles.translate(self.rows(2), again, force=True)

        self.assertEqual(again.calls, 1)
        self.assertEqual(self.titles.known()["1"], "Иначе")

    def test_cache_key_is_the_id_not_the_name(self):
        """Название на сайте правят, идентификатор — нет."""
        client = self.FakeLlm('{"1": "Книга"}')
        self.titles.translate([rank_net.RankRow(book_id="1", name="书")], client)

        again = self.FakeLlm("{}")
        result = self.titles.translate(
            [rank_net.RankRow(book_id="1", name="书 (исправленное)")], again)
        self.assertEqual(again.calls, 0)
        self.assertEqual(result["titles"]["1"], "Книга")

    def test_broken_answer_does_not_lose_the_cache(self):
        client = self.FakeLlm('{"1": "Книга"}')
        self.titles.translate([rank_net.RankRow(book_id="1", name="书")], client)
        self.titles.translate([rank_net.RankRow(book_id="2", name="书二")],
                              self.FakeLlm("не json вовсе"))
        self.assertEqual(self.titles.known()["1"], "Книга")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestChapterStaysEncrypted(unittest.TestCase):
    """Полузашифрованную главу нельзя класть в файл как удачную.

    Подстановка по шрифту может не сработать целиком — тогда половина
    иероглифов остаётся номерами глифов из приватной зоны. Редактор их не
    рисует, и человек видит пропавший текст, хотя качалка отчиталась об
    успехе. Понимает он это уже через сотню глав.
    """

    def setUp(self):
        self.source = FanqieSource()

    def chapter(self):
        from mvl.api import Chapter

        return Chapter(number=4, post_id="700000000000000001")

    def answer(self, content):
        return json.dumps({"code": 0, "data": {"chapterData": {
            "title": "Глава 4", "content": content}}}, ensure_ascii=False)

    def test_a_readable_chapter_goes_through(self):
        client = FakeClient({"/api/reader/full": self.answer(
            "<p>Обычный текст без всякой приватной зоны.</p>")})
        title, text = self.source.chapter(client, self.chapter())
        self.assertIn("Обычный текст", text)

    def test_a_chapter_full_of_private_glyphs_is_refused(self):
        from net.sources.fanqie import ChapterEncrypted

        secret = "".join(chr(0xE000 + n % 100) for n in range(200))
        client = FakeClient({"/api/reader/full": self.answer(
            f"<p>Начало. {secret}</p>")})
        with self.assertRaises(ChapterEncrypted):
            self.source.chapter(client, self.chapter())

    def test_a_stray_glyph_is_not_a_reason_to_refuse(self):
        """Пара знаков — случайность вёрстки, а не сломанный шрифт."""
        client = FakeClient({"/api/reader/full": self.answer(
            "<p>" + "Текст главы, вполне читаемый. " * 20 + "</p>")})
        title, text = self.source.chapter(client, self.chapter())
        self.assertIn("читаемый", text)

    def test_such_a_chapter_does_not_bring_the_whole_book_down(self):
        """Она пропускается, как платная: повтор её всё равно не спасёт."""
        from mvl.downloader import _is_paid
        from net.sources.fanqie import ChapterEncrypted

        self.assertTrue(_is_paid(ChapterEncrypted("нерасшифрована")))


class TestChapterTextComesFromTheReaderBranch(unittest.TestCase):
    """Текст главы лежит в ветке `reader`, рядом с `page`.

    Разбор книги сужен до `page` — иначе в поле «автор» уезжает объект из
    соседней ветки. Но сузить так весь разборщик страницы нельзя: из-под
    `page` текст главы недостижим, и в файлы ложились две строки заголовка
    без единого абзаца.
    """

    def setUp(self):
        self.source = FanqieSource()

    def test_the_body_is_found_next_to_the_book_branch(self):
        from mvl.api import Chapter

        client = FakeClient({
            "/api/reader/full": "<html>не json</html>",
            "/reader/": state_page({
                "page": {"bookName": "книга", "chapterTotal": 100},
                "reader": {"chapterData": {
                    "title": "Глава 3",
                    "content": "<p>Первый абзац.</p><p>Второй абзац.</p>"}},
            }),
        })
        title, text = self.source.chapter(
            client, Chapter(number=3, post_id="700000000000000001"))

        self.assertEqual(title, "Глава 3")
        self.assertIn("Первый абзац", text)
        self.assertIn("Второй абзац", text)

    def test_the_author_still_does_not_leak_from_its_own_branch(self):
        """Сужение до `page` осталось там, где оно и нужно."""
        client = FakeClient({"/page/": state_page({
            "page": {"bookName": "книга", "author": "六口葫芦",
                     "chapterTotal": 7},
            "author": {"userInfo": {"username": "", "authorize_type": 0}},
        })})
        self.assertEqual(self.source.find(client, "7143038691944959011").author,
                         "六口葫芦")
