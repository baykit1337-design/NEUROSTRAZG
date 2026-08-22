"""Рейтинг MVLEMPYR: разбор каталога и хранение срезов по сайтам.

Живьём в песочнице это не проверить — `chap.heliosarchive.online` за
пределами разрешённого списка, шлюз отвечает 403 на любой запрос. Поэтому
здесь подставной клиент, отдающий ответы той же формы, что и настоящий
WordPress: список записей плюс заголовок с числом страниц.

Числа-настройки (сколько записей за раз, сколько строк в срезе) не
закрепляются: их будут крутить, а тест должен ловить сломанный разбор, а
не изменённую константу.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl.client import HttpError  # noqa: E402
from net.sources import mvlrank  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402


def novel(code, name, weekly=0, monthly=0, alltime=0, **extra):
    """Запись каталога в том виде, в каком её отдаёт сайт."""
    item = {
        "slug": name.lower().replace(" ", "-"),
        "novel-code": str(code),
        "name": name,
        "author-name": "Автор " + str(code),
        "total-chapters": "120",
        "average-review": "4.5",
        "status": "ongoing",
        "language": "CN",
        "genre": ["Fantasy", "Action"],
        "weekly-rank": weekly,
        "monthly-rank": monthly,
        "rank": alltime,
    }
    item.update(extra)
    return item


class Reply:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("не JSON")
        return self._body


class FakeClient:
    """Отдаёт заготовленные страницы каталога и считает запросы."""

    def __init__(self, pages, headers=None, fail_from=None):
        self.pages = pages
        self.headers = headers or {}
        self.fail_from = fail_from
        self.asked = []

    def get(self, url, params=None, headers=None):
        page = int((params or {}).get("page") or 1)
        self.asked.append(page)
        if self.fail_from is not None and page >= self.fail_from:
            raise HttpError("сайт не ответил")
        body = self.pages[page - 1] if page <= len(self.pages) else []
        return Reply(body, self.headers)

    def close(self):
        """Ручка закрывает клиента сама — подставной должен это уметь."""


class TestCatalogue(unittest.TestCase):
    """Каталог забирается целиком, страница за страницей."""

    def test_pages_are_walked_until_the_catalogue_ends(self):
        pages = [[novel(i, f"Книга {i}") for i in range(mvlrank.PAGE)],
                 [novel(9001, "Последняя")]]
        client = FakeClient(pages, headers={"X-WP-TotalPages": "2"})
        found = mvlrank.catalogue(client)
        self.assertEqual(len(found), mvlrank.PAGE + 1)
        self.assertEqual(client.asked, [1, 2])

    def test_a_short_page_means_the_end(self):
        """Записей пришло меньше, чем просили, — дальше ходить незачем."""
        client = FakeClient([[novel(1, "Одна")]])
        mvlrank.catalogue(client)
        self.assertEqual(client.asked, [1])

    def test_the_walk_cannot_run_forever(self):
        """Заголовок с числом страниц пропал, а сайт отдаёт всё подряд."""
        full = [novel(i, f"К{i}") for i in range(mvlrank.PAGE)]
        client = FakeClient([full] * (mvlrank.MAX_PAGES + 5))
        mvlrank.catalogue(client)
        self.assertLessEqual(len(client.asked), mvlrank.MAX_PAGES)

    def test_a_broken_first_page_is_an_error(self):
        """Первая страница не пришла — рейтинга не будет вовсе."""
        with self.assertRaises(HttpError):
            mvlrank.catalogue(FakeClient([], fail_from=1))

    def test_a_broken_later_page_keeps_what_was_collected(self):
        """Неполный список полезнее пустого."""
        pages = [[novel(i, f"К{i}") for i in range(mvlrank.PAGE)]]
        client = FakeClient(pages, headers={"X-WP-TotalPages": "5"},
                            fail_from=2)
        found = mvlrank.catalogue(client)
        self.assertEqual(len(found), mvlrank.PAGE)

    def test_not_a_list_is_a_broken_source(self):
        """Ответ другой формы лечится правкой модуля, а не повтором."""
        with self.assertRaises(SourceBroken):
            mvlrank.catalogue(FakeClient([{"error": "nope"}]))

    def test_not_json_is_a_broken_source(self):
        with self.assertRaises(SourceBroken):
            mvlrank.catalogue(FakeClient(["<html>"]))

    def test_an_empty_catalogue_is_a_broken_source(self):
        with self.assertRaises(SourceBroken):
            mvlrank.catalogue(FakeClient([[]]))


class TestBoards(unittest.TestCase):
    """Места лежат полями внутри книг — сортируем по ним сами."""

    def setUp(self):
        self.items = [
            novel(10, "Третья", weekly=3, monthly=1, alltime=7),
            novel(11, "Первая", weekly=1, monthly=9, alltime=2),
            novel(12, "Вторая", weekly=2, monthly=5, alltime=1),
            novel(13, "Вне рейтинга", weekly=0, monthly=0, alltime=4),
        ]

    def fetch(self, board):
        return mvlrank.fetch(FakeClient([self.items]), board=board)

    def test_weekly_is_sorted_by_the_weekly_place(self):
        rows = self.fetch("weekly")["rows"]
        self.assertEqual([r.name for r in rows],
                         ["Первая", "Вторая", "Третья"])

    def test_each_board_sorts_by_its_own_field(self):
        """Иначе три доски показывали бы один и тот же список."""
        weekly = [r.name for r in self.fetch("weekly")["rows"]]
        monthly = [r.name for r in self.fetch("monthly")["rows"]]
        alltime = [r.name for r in self.fetch("alltime")["rows"]]
        self.assertNotEqual(weekly, monthly)
        self.assertNotEqual(weekly, alltime)

    def test_a_zero_place_means_out_of_this_board_not_first(self):
        rows = self.fetch("weekly")["rows"]
        self.assertNotIn("Вне рейтинга", [r.name for r in rows])
        # А в рейтинге за всё время место у неё есть.
        self.assertIn("Вне рейтинга",
                      [r.name for r in self.fetch("alltime")["rows"]])

    def test_places_are_renumbered_from_the_field(self):
        rows = self.fetch("weekly")["rows"]
        self.assertEqual([r.place for r in rows], [1, 2, 3])

    def test_an_unknown_board_is_refused(self):
        with self.assertRaises(ValueError):
            self.fetch("годовой")

    def test_a_catalogue_without_places_is_a_broken_source(self):
        """Сайт переименовал поля — молча показывать пустоту нельзя."""
        items = [novel(1, "Книга", weekly=0, monthly=0, alltime=0)]
        with self.assertRaises(SourceBroken):
            mvlrank.fetch(FakeClient([items]), board="weekly")

    def test_the_snapshot_is_cut_to_a_sane_length(self):
        many = [novel(i, f"К{i}", weekly=i + 1) for i in range(mvlrank.TOP + 40)]
        rows = mvlrank.fetch(FakeClient([many]), board="weekly")["rows"]
        self.assertEqual(len(rows), mvlrank.TOP)


class TestRowFields(unittest.TestCase):
    """Что именно попадает в строку рейтинга."""

    def row(self, **extra):
        item = novel(6615, "Insect Tamers Ascension", weekly=1, **extra)
        return mvlrank.fetch(FakeClient([[item]]), board="weekly")["rows"][0]

    def test_the_code_is_what_the_downloader_searches_by(self):
        self.assertEqual(self.row().book_id, "6615")

    def test_the_row_remembers_its_site(self):
        """Иначе во вчерашнем срезе не понять, куда вести ссылку."""
        self.assertEqual(self.row().site, mvlrank.SITE_KEY)

    def test_the_link_is_built_from_the_slug_not_the_code(self):
        link = self.row().link
        self.assertIn("insect-tamers-ascension", link)
        self.assertTrue(link.startswith(mvlrank.SITE))

    def test_the_cover_is_named_by_the_code(self):
        self.assertIn("6615", self.row().cover)

    def test_the_score_survives(self):
        self.assertEqual(self.row().score, 4.5)

    def test_no_ratings_is_not_a_zero_score(self):
        """Ноль баллов и «оценок нет» — разные вещи."""
        self.assertIsNone(self.row(**{"average-review": ""}).score)
        self.assertIsNone(self.row(**{"average-review": "0"}).score)

    def test_the_chapter_count_is_kept_apart_from_characters(self):
        row = self.row()
        self.assertEqual(row.chapters, 120)
        self.assertEqual(row.words, 0)

    def test_readers_are_honestly_zero(self):
        """Числа читающих сайт не показывает — подставлять балл нельзя."""
        self.assertEqual(self.row().readers, 0)

    def test_the_status_is_translated(self):
        self.assertEqual(self.row().status, "пишется")

    def test_the_sites_own_typo_in_haitus_is_understood(self):
        """Сайт пишет «haitus», и подгонять его под словарь нечем."""
        self.assertEqual(self.row(status="haitus").status, "заморожена")

    def test_an_unknown_status_shows_as_is(self):
        self.assertEqual(self.row(status="paused").status, "paused")

    def test_only_the_first_genre_goes_into_the_column(self):
        self.assertEqual(self.row().category, "Fantasy")

    def test_fields_are_found_when_wordpress_hides_them_in_acf(self):
        """Свои поля WordPress отдаёт то наверху, то в `acf`."""
        item = {"slug": "x", "acf": {"novel-code": "77", "name": "Из acf",
                                     "weekly-rank": 1, "average-review": "3.1"}}
        row = mvlrank.fetch(FakeClient([[item]]), board="weekly")["rows"][0]
        self.assertEqual(row.name, "Из acf")
        self.assertEqual(row.book_id, "77")
        self.assertEqual(row.score, 3.1)

    def test_a_rendered_title_is_unwrapped(self):
        item = {"slug": "y", "novel-code": "78", "weekly-rank": 1,
                "title": {"rendered": "Из title"}}
        row = mvlrank.fetch(FakeClient([[item]]), board="weekly")["rows"][0]
        self.assertEqual(row.name, "Из title")


class TestVersion(unittest.TestCase):
    """Метка среза отвечает на вопрос «пересчитался ли рейтинг»."""

    def test_the_same_catalogue_gives_the_same_version(self):
        items = [novel(i, f"К{i}", weekly=i + 1) for i in range(5)]
        first = mvlrank.fetch(FakeClient([items]), board="weekly")
        second = mvlrank.fetch(FakeClient([items]), board="weekly")
        self.assertEqual(first["version"], second["version"])

    def test_a_reshuffled_top_changes_the_version(self):
        items = [novel(i, f"К{i}", weekly=i + 1) for i in range(5)]
        first = mvlrank.fetch(FakeClient([items]), board="weekly")
        items[0]["weekly-rank"] = 99
        second = mvlrank.fetch(FakeClient([items]), board="weekly")
        self.assertNotEqual(first["version"], second["version"])


class TestHistoryKeepsSitesApart(unittest.TestCase):
    """Срезы разных сайтов не должны попадать в одну кучу."""

    def setUp(self):
        from ops import rank as rank_op
        self.rank_op = rank_op
        self.tmp = tempfile.TemporaryDirectory()
        self.was = rank_op.RANK_DIR
        rank_op.RANK_DIR = Path(self.tmp.name)

    def tearDown(self):
        self.rank_op.RANK_DIR = self.was
        self.tmp.cleanup()

    def rows(self, *names):
        from net.sources.rank import RankRow
        return [RankRow(place=i + 1, book_id=str(i), name=n)
                for i, n in enumerate(names)]

    def test_two_sites_on_one_day_do_not_overwrite_each_other(self):
        self.rank_op.save(self.rows("Фанкью"), board="1_2", day="2026-08-22")
        self.rank_op.save(self.rows("MVL"), board="weekly", day="2026-08-22",
                          site="mvlempyr")
        fanqie = self.rank_op.load("2026-08-22", "1_2")
        mvl = self.rank_op.load("2026-08-22", "weekly", site="mvlempyr")
        self.assertEqual(fanqie.rows[0].name, "Фанкью")
        self.assertEqual(mvl.rows[0].name, "MVL")

    def test_history_of_one_site_does_not_show_up_in_the_other(self):
        self.rank_op.save(self.rows("MVL"), board="weekly", day="2026-08-22",
                          site="mvlempyr")
        self.assertEqual(self.rank_op.days("weekly"), [])
        self.assertEqual(self.rank_op.days("weekly", site="mvlempyr"),
                         ["2026-08-22"])

    def test_the_old_fanqie_file_names_did_not_change(self):
        """Иначе накопленная история просто перестала бы находиться."""
        self.rank_op.save(self.rows("Старое"), board="1_2", day="2026-08-22")
        self.assertTrue((Path(self.tmp.name) / "2026-08-22_1_2.json").is_file())

    def test_a_saved_snapshot_remembers_its_site(self):
        self.rank_op.save(self.rows("MVL"), board="weekly", day="2026-08-22",
                          site="mvlempyr")
        raw = json.loads(
            (Path(self.tmp.name) / "2026-08-22_mvlempyr-weekly.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(raw["site"], "mvlempyr")

    def test_movement_is_counted_within_one_site(self):
        self.rank_op.save(self.rows("Первая", "Вторая"), board="weekly",
                          day="2026-08-20", site="mvlempyr")
        self.rank_op.save(self.rows("Вторая", "Первая"), board="weekly",
                          day="2026-08-21", site="mvlempyr")
        moved = self.rank_op.movement("weekly", site="mvlempyr")
        self.assertEqual(moved["site"], "mvlempyr")
        self.assertEqual(len(moved["rows"]), 2)

    def test_trimming_counts_days_per_set_not_per_folder(self):
        """Год истории обещан каждому набору, а не всем вместе."""
        for day in ("2026-08-18", "2026-08-19", "2026-08-20"):
            self.rank_op.save(self.rows("Фанкью"), board="1_2", day=day)
        for day in ("2026-08-18", "2026-08-19", "2026-08-20"):
            self.rank_op.save(self.rows("MVL"), board="weekly", day=day,
                              site="mvlempyr")
        self.rank_op.trim(keep=2)
        self.assertEqual(len(self.rank_op.days("1_2")), 2)
        self.assertEqual(len(self.rank_op.days("weekly", site="mvlempyr")), 2)


class TestTheRouteEndToEnd(unittest.TestCase):
    """От нажатия «Обновить срез» до сохранённого файла.

    Сеть подменяется на уровне каталога: всё остальное — выбор доски,
    разбор, запись, подсчёт движения — работает настоящее.
    """

    def setUp(self):
        from ops import rank as rank_op
        from webapp import app as web

        self.rank_op = rank_op
        self.web = web
        self.tmp = tempfile.TemporaryDirectory()
        self.was_dir = rank_op.RANK_DIR
        rank_op.RANK_DIR = Path(self.tmp.name)

        self.was_catalogue = mvlrank.catalogue
        self.was_client = web._rank_client
        items = [novel(i, f"Книга {i}", weekly=i + 1, monthly=5 - i,
                       alltime=i + 1) for i in range(4)]
        mvlrank.catalogue = lambda client, on_progress=None: items
        web._rank_client = lambda: FakeClient([items])

        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def tearDown(self):
        mvlrank.catalogue = self.was_catalogue
        self.web._rank_client = self.was_client
        self.rank_op.RANK_DIR = self.was_dir
        self.tmp.cleanup()

    def test_the_sites_are_listed_for_the_page(self):
        """Список сайтов приходит с сервера, а не вписан в разметку."""
        got = self.client.get("/api/rank/categories").get_json()
        keys = [s["key"] for s in got["sites"]]
        self.assertIn("", keys)
        self.assertIn(mvlrank.SITE_KEY, keys)

    def test_each_site_says_where_to_download_its_books_from(self):
        got = self.client.get("/api/rank/categories").get_json()
        mvl = [s for s in got["sites"] if s["key"] == mvlrank.SITE_KEY][0]
        self.assertEqual(mvl["source"], "mvlempyr")
        self.assertTrue(mvl["boards"])

    def test_a_refresh_saves_a_snapshot_for_that_site(self):
        got = self.client.post("/api/rank/refresh",
                               json={"site": mvlrank.SITE_KEY,
                                     "board": "weekly"}).get_json()
        self.assertEqual(got["saved"], 4)
        self.assertEqual(got["site"], mvlrank.SITE_KEY)
        self.assertEqual(len(self.rank_op.days("weekly",
                                               site=mvlrank.SITE_KEY)), 1)

    def test_the_state_reads_back_what_the_refresh_saved(self):
        self.client.post("/api/rank/refresh",
                         json={"site": mvlrank.SITE_KEY, "board": "weekly"})
        got = self.client.get(
            f"/api/rank/state?site={mvlrank.SITE_KEY}&board=weekly").get_json()
        self.assertEqual(len(got["rows"]), 4)
        self.assertEqual(got["rows"][0]["site"], mvlrank.SITE_KEY)

    def test_two_boards_of_one_site_are_separate_histories(self):
        self.client.post("/api/rank/refresh",
                         json={"site": mvlrank.SITE_KEY, "board": "weekly"})
        self.client.post("/api/rank/refresh",
                         json={"site": mvlrank.SITE_KEY, "board": "monthly"})
        weekly = self.client.get(
            f"/api/rank/state?site={mvlrank.SITE_KEY}&board=weekly").get_json()
        monthly = self.client.get(
            f"/api/rank/state?site={mvlrank.SITE_KEY}&board=monthly").get_json()
        self.assertNotEqual([r["name"] for r in weekly["rows"]],
                            [r["name"] for r in monthly["rows"]])

    def test_an_unknown_board_falls_back_instead_of_failing(self):
        """Опечатка в запросе не должна отдавать пятисотку."""
        got = self.client.post("/api/rank/refresh",
                               json={"site": mvlrank.SITE_KEY,
                                     "board": "годовой"}).get_json()
        self.assertEqual(got["saved"], 4)

    def test_an_unknown_site_is_treated_as_fanqie(self):
        """Так вела себя программа до появления второго рейтинга."""
        got = self.client.get("/api/rank/state?site=novelpia").get_json()
        self.assertEqual(got.get("site", ""), "")

    def test_a_second_refresh_the_same_day_says_nothing_changed(self):
        self.client.post("/api/rank/refresh",
                         json={"site": mvlrank.SITE_KEY, "board": "weekly"})
        again = self.client.post("/api/rank/refresh",
                                 json={"site": mvlrank.SITE_KEY,
                                       "board": "weekly"}).get_json()
        self.assertTrue(again["same_version"])
        self.assertEqual(len(self.rank_op.days("weekly",
                                               site=mvlrank.SITE_KEY)), 1)


class TestOldRowsStillLoad(unittest.TestCase):
    """У строки прибавилось полей — старые срезы должны читаться."""

    def test_a_row_saved_before_the_new_fields_loads_with_defaults(self):
        from net.sources.rank import RankRow
        old = {"place": 1, "book_id": "7143038691944959011", "name": "Книга",
               "readers": 12000}
        row = RankRow.from_dict(old)
        self.assertEqual(row.site, "")
        self.assertEqual(row.chapters, 0)
        self.assertIsNone(row.score)

    def test_a_row_without_its_own_link_still_points_at_fanqie(self):
        from net.sources.rank import RankRow
        row = RankRow(book_id="7143038691944959011")
        self.assertIn("7143038691944959011", row.as_dict()["link"])
        self.assertIn("fanqie", row.as_dict()["link"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
