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

    def test_title_is_the_fallback(self):
        client = FakeClient({"/page/": "<html><title>剑来_番茄小说</title></html>"})
        self.assertEqual(self.source.find(client, "7143038691944959011").name, "剑来")

    def test_unreadable_page_says_the_source_changed(self):
        """«Источник изменился» лечится правкой модуля, а не повтором."""
        client = FakeClient({"/page/": "<html><body>ничего</body></html>"})
        with self.assertRaises(SourceBroken):
            self.source.find(client, "7143038691944959011")


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

    def test_not_json_says_the_source_changed(self):
        client = FakeClient({"/api/reader/full": "<html>лишь бы не json</html>"})
        with self.assertRaises(SourceBroken):
            self.source.chapter(client, self.chapter())

    def test_chapter_without_an_id_is_refused(self):
        from mvl.api import Chapter

        with self.assertRaises(SourceBroken):
            self.source.chapter(FakeClient(), Chapter(number=1))


class TestRankParsing(unittest.TestCase):
    """Разбор страницы рейтинга."""

    def page(self, count=3):
        return next_data({"props": {"pageProps": {"rankList": [
            {"bookId": f"70000000000000000{n}", "bookName": f"книга {n}",
             "author": f"автор {n}", "readCount": f"{n}.5万",
             "category": "фэнтези", "rank": n}
            for n in range(1, count + 1)]}}})

    def test_rows_are_read(self):
        rows = rank_net.parse(self.page(3))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].name, "книга 1")
        self.assertEqual(rows[0].place, 1)
        self.assertEqual(rows[0].category, "фэнтези")

    def test_chinese_numbers_are_understood(self):
        """«12.3万» — это сто двадцать три тысячи, а не двенадцать."""
        self.assertEqual(rank_net._readers("12.3万"), 123000)
        self.assertEqual(rank_net._readers("1亿"), 100_000_000)
        self.assertEqual(rank_net._readers("1,234"), 1234)
        self.assertEqual(rank_net._readers(""), 0)

    def test_place_is_filled_when_missing(self):
        html = next_data({"props": {"rankList": [
            {"bookId": "700000000000000001", "bookName": "книга"},
            {"bookId": "700000000000000002", "bookName": "вторая"}]}})
        rows = rank_net.parse(html)
        self.assertEqual([r.place for r in rows], [1, 2])

    def test_limit_is_respected(self):
        self.assertEqual(len(rank_net.parse(self.page(80), limit=50)), 50)

    def test_link_leads_to_the_book(self):
        rows = rank_net.parse(self.page(1))
        self.assertTrue(rows[0].as_dict()["link"].endswith("/page/700000000000000001"))

    def test_unparsable_page_is_an_error_not_an_empty_table(self):
        """Пустую таблицу приняли бы за пустой рейтинг."""
        with self.assertRaises(SourceBroken):
            rank_net.parse("<html><body>ничего похожего</body></html>")

    def test_markup_is_the_fallback(self):
        html = ('<html><body>'
                '<a href="/page/700000000000000001"><span>книга</span>'
                '<span>автор</span><span>12.3万</span></a>'
                '<a href="/page/700000000000000002"><span>вторая</span></a>'
                '</body></html>')
        rows = rank_net.parse(html)
        self.assertEqual([r.name for r in rows], ["книга", "вторая"])
        self.assertEqual(rows[0].readers, 123000)

    def test_unknown_board_is_refused(self):
        with self.assertRaises(ValueError):
            rank_net.fetch(FakeClient(), "непонятный")


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
