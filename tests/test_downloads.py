"""Очередь книг: несколько книг подряд, у каждой свой источник.

Главное, ради чего очередь отделена от очереди операций: книги друг о
друге не знают. Не открылся сайт у третьей — четвёртую качать всё равно
надо. Второе: у каждой строки свой источник и свой адрес, потому что
книгу находят на одном сайте, а качают с другого, а у найденной на
Цидяне качать поначалу вообще не с чего.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import downloads, library  # noqa: E402
from ops.base import Cancelled as OpCancelled  # noqa: E402


class Base(unittest.TestCase):

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        was = downloads.QUEUE_FILE
        downloads.QUEUE_FILE = Path(self.dir.name) / "downloads.json"
        self.addCleanup(setattr, downloads, "QUEUE_FILE", was)

    def book(self, **more):
        """Книга, которую есть чем качать."""
        fields = dict(name="异度旅社", name_ru="Гостиница иного мира",
                      source="novelcms", address="https://x/read/1/",
                      base="/книги", folder="Гостиница")
        fields.update(more)
        return downloads.add(**fields)


class TestWhatGoesIntoTheQueue(Base):

    def test_a_book_with_a_source_is_ready_to_go(self):
        item = self.book()
        self.assertTrue(item.ready)
        self.assertEqual(item.state, downloads.WAITING)

    def test_a_book_found_where_there_is_no_downloading_waits_for_a_link(self):
        """С Цидяня качать нечем: строка ждёт ссылки, а не притворяется
        готовой."""
        item = downloads.add(name="异度旅社", base="/книги", folder="Г",
                             origin={"site": "qidian", "book_id": "104"})
        self.assertFalse(item.ready)
        self.assertEqual(item.state, downloads.NEEDS_LINK)
        self.assertTrue(item.message)

    def test_such_a_book_is_not_thrown_away(self):
        """Выброси её при добавлении — человек потерял бы саму память о
        том, что книгу хотел."""
        downloads.add(name="异度旅社", base="/книги", folder="Г",
                      origin={"site": "qidian", "book_id": "104"})
        self.assertEqual(len(downloads.all_items()), 1)

    def test_a_pasted_link_puts_the_book_in_the_common_row(self):
        item = downloads.add(name="异度旅社", base="/книги", folder="Г",
                             origin={"site": "qidian", "book_id": "104"})
        again = downloads.update(item.id, source="novelcms",
                                 address="https://ixdzs8.com/read/566155/")
        self.assertEqual(again.state, downloads.WAITING)
        self.assertTrue(again.ready)
        self.assertFalse(again.message)

    def test_the_title_shown_prefers_the_translation(self):
        self.assertEqual(self.book().title, "Гостиница иного мира")

    def test_without_a_translation_the_original_is_shown(self):
        self.assertEqual(self.book(name_ru="").title, "异度旅社")


class TestTheSameBookDoesNotDouble(Base):

    def test_the_same_origin_updates_the_row_instead_of_adding_one(self):
        """Иначе очередь качала бы одну книгу дважды в одну папку."""
        origin = {"site": "qidian", "book_id": "104"}
        self.book(origin=origin)
        self.book(origin=origin, folder="Другая папка")
        rows = downloads.all_items()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].folder, "Другая папка")

    def test_the_same_folder_counts_as_the_same_book(self):
        self.book(address="https://x/read/1/")
        self.book(address="https://y/book/2/")
        self.assertEqual(len(downloads.all_items()), 1)

    def test_different_books_stay_different(self):
        self.book(folder="Первая")
        self.book(folder="Вторая")
        self.assertEqual(len(downloads.all_items()), 2)

    def test_a_book_from_qidian_survives_the_move_to_a_leak_site(self):
        """Строка с Цидяня и она же после вставленной ссылки — одна
        книга, а не две."""
        origin = {"site": "qidian", "book_id": "104"}
        first = downloads.add(name="异度旅社", base="/книги", folder="Г",
                              origin=origin)
        second = downloads.add(name="异度旅社", base="/книги", folder="Г",
                               source="novelcms", address="https://x/1/",
                               origin=origin)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(downloads.all_items()), 1)


class TestTheOrderIsTheWholePoint(Base):

    def test_books_keep_the_order_they_were_put_in(self):
        for name in ("Первая", "Вторая", "Третья"):
            self.book(folder=name)
        self.assertEqual([x.folder for x in downloads.all_items()],
                         ["Первая", "Вторая", "Третья"])

    def test_a_book_can_be_moved_up(self):
        rows = [self.book(folder=n) for n in ("Первая", "Вторая", "Третья")]
        self.assertTrue(downloads.move(rows[2].id, -1))
        self.assertEqual([x.folder for x in downloads.all_items()],
                         ["Первая", "Третья", "Вторая"])

    def test_moving_past_the_edge_does_nothing_bad(self):
        rows = [self.book(folder=n) for n in ("Первая", "Вторая")]
        downloads.move(rows[0].id, -5)
        self.assertEqual([x.folder for x in downloads.all_items()],
                         ["Первая", "Вторая"])

    def test_a_book_can_be_taken_out(self):
        rows = [self.book(folder=n) for n in ("Первая", "Вторая")]
        self.assertTrue(downloads.remove(rows[0].id))
        self.assertEqual([x.folder for x in downloads.all_items()], ["Вторая"])

    def test_taking_out_what_is_not_there_is_not_a_crash(self):
        self.assertFalse(downloads.remove("нет такой"))


class TestRunningTheQueue(Base):

    def test_every_book_gets_downloaded(self):
        for name in ("Первая", "Вторая", "Третья"):
            self.book(folder=name)
        seen = []
        downloads.run(lambda item: seen.append(item.folder) or "готово")
        self.assertEqual(seen, ["Первая", "Вторая", "Третья"])
        self.assertTrue(all(x.state == downloads.DONE
                            for x in downloads.all_items()))

    def test_a_broken_book_does_not_cancel_the_rest(self):
        """Ради этого очередь книг и отделена от очереди операций: одна
        закрытая книга съедала бы ночь работы."""
        for name in ("Первая", "Вторая", "Третья"):
            self.book(folder=name)

        def perform(item):
            if item.folder == "Вторая":
                raise RuntimeError("сайт закрыл доступ")
            return "готово"

        rows = downloads.run(perform)
        self.assertEqual([x.state for x in rows],
                         [downloads.DONE, downloads.FAILED, downloads.DONE])

    def test_the_reason_is_kept_on_the_broken_book(self):
        self.book(folder="Первая")
        downloads.run(lambda item: (_ for _ in ()).throw(
            RuntimeError("сайт закрыл доступ")))
        self.assertIn("сайт закрыл доступ", downloads.all_items()[0].message)

    def test_a_book_waiting_for_a_link_is_stepped_over_quietly(self):
        downloads.add(name="Без ссылки", base="/книги", folder="Б")
        self.book(folder="Готовая")
        seen = []
        downloads.run(lambda item: seen.append(item.folder) or "готово")
        self.assertEqual(seen, ["Готовая"])
        self.assertEqual(downloads.all_items()[0].state, downloads.NEEDS_LINK)

    def test_stopping_leaves_the_rest_waiting_not_skipped(self):
        """Очередь продолжают тем же нажатием, что и начали."""
        for name in ("Первая", "Вторая", "Третья"):
            self.book(folder=name)
        stop = threading.Event()

        def perform(item):
            stop.set()
            return "готово"

        rows = downloads.run(perform, cancel=stop)
        self.assertEqual(rows[0].state, downloads.DONE)
        self.assertEqual([x.state for x in rows[1:]],
                         [downloads.WAITING, downloads.WAITING])

    def test_a_book_broken_off_by_the_stop_is_not_blamed(self):
        """Качалка на отмене возбуждает исключение, как и на отказе сайта.
        Пометь мы книгу неудачей — «не вышло: 1» обвиняло бы сайт в том,
        что сделал человек, и книга выпала бы из продолжения."""
        for name in ("Первая", "Вторая"):
            self.book(folder=name)
        stop = threading.Event()

        def perform(item):
            stop.set()
            raise RuntimeError("Cancelled: остановлено")

        rows = downloads.run(perform, cancel=stop)
        self.assertNotEqual(rows[0].state, downloads.FAILED)
        self.assertEqual(downloads.state()["failed"], 0)
        self.assertEqual(rows[0].state, downloads.WAITING)

    def test_a_second_run_starts_from_a_clean_slate(self):
        self.book(folder="Первая")
        downloads.run(lambda item: (_ for _ in ()).throw(RuntimeError("раз")))
        downloads.run(lambda item: "готово")
        self.assertEqual(downloads.all_items()[0].state, downloads.DONE)

    def test_the_progress_is_written_down_as_it_goes(self):
        """Закройся окно посреди ночи — очередь помнит, докуда дошла."""
        for name in ("Первая", "Вторая"):
            self.book(folder=name)
        seen = []

        def perform(item):
            saved = json.loads(downloads.QUEUE_FILE.read_text(encoding="utf-8"))
            seen.append([x["state"] for x in saved])
            return "готово"

        downloads.run(perform)
        self.assertIn(downloads.RUNNING, seen[0])
        self.assertIn(downloads.DONE, seen[1])

    def test_every_turn_of_the_queue_is_told_about(self):
        self.book(folder="Первая")
        heard = []
        downloads.run(lambda item: "готово",
                      on_change=lambda rows, item: heard.append(item.state))
        self.assertEqual(heard, [downloads.RUNNING, downloads.DONE])


class TestTheSummary(Base):

    def test_it_counts_what_the_caption_says(self):
        self.book(folder="Первая")
        self.book(folder="Вторая")
        downloads.add(name="Без ссылки", base="/книги", folder="Б")
        said = downloads.state()
        self.assertEqual(said["books"], 3)
        self.assertEqual(said["waiting"], 2)
        self.assertEqual(said["needs_link"], 1)

    def test_after_a_run_it_counts_what_happened(self):
        self.book(folder="Первая")
        self.book(folder="Вторая")

        def perform(item):
            if item.folder == "Вторая":
                raise RuntimeError("отказ")
            item.done = 12
            return "готово"

        downloads.run(perform)
        said = downloads.state()
        self.assertEqual(said["done"], 1)
        self.assertEqual(said["failed"], 1)
        self.assertEqual(said["chapters"], 12)


class TestCleaning(Base):

    def test_only_the_finished_can_be_swept_out(self):
        self.book(folder="Первая")
        self.book(folder="Вторая")
        downloads.run(lambda item: "готово" if item.folder == "Первая"
                      else (_ for _ in ()).throw(RuntimeError("отказ")))
        downloads.clear(only_done=True)
        self.assertEqual([x.folder for x in downloads.all_items()], ["Вторая"])

    def test_everything_can_be_swept_out(self):
        self.book(folder="Первая")
        downloads.clear()
        self.assertEqual(downloads.all_items(), [])


class TestTheFileSurvivesTrouble(Base):

    def test_a_broken_file_does_not_stop_the_program(self):
        downloads.QUEUE_FILE.write_text("не json вовсе", encoding="utf-8")
        self.assertEqual(downloads.all_items(), [])
        self.book(folder="Первая")
        self.assertEqual(len(downloads.all_items()), 1)

    def test_a_file_of_the_wrong_shape_is_ignored(self):
        downloads.QUEUE_FILE.write_text('{"не": "список"}', encoding="utf-8")
        self.assertEqual(downloads.all_items(), [])

    def test_reading_back_keeps_the_fields(self):
        self.book(first=401, last=402, cover="https://x/о.jpg",
                  origin={"site": "qidian", "book_id": "104"})
        item = downloads.all_items()[0]
        self.assertEqual((item.first, item.last), (401, 402))
        self.assertEqual(item.origin["book_id"], "104")
        self.assertEqual(item.cover, "https://x/о.jpg")

    def test_junk_in_the_numbers_does_not_crash_the_read(self):
        downloads.QUEUE_FILE.write_text(
            json.dumps([{"id": "1", "first": "ниоткуда", "folder": "Г"}]),
            encoding="utf-8")
        self.assertEqual(downloads.all_items()[0].first, 0)

    def test_a_row_without_an_id_is_dropped(self):
        downloads.QUEUE_FILE.write_text(json.dumps([{"folder": "Г"}]),
                                        encoding="utf-8")
        self.assertEqual(downloads.all_items(), [])


class TestBordersAreNotFrozen(Base):

    def test_zero_means_the_program_decides_at_start(self):
        """Заморозь номер при добавлении — за ночь вышло бы ещё три
        главы, а очередь качала бы вчерашний остаток."""
        item = self.book()
        self.assertEqual((item.first, item.last), (0, 0))

    def test_but_a_chosen_border_is_kept(self):
        item = self.book(first=401, last=450)
        self.assertEqual((item.first, item.last), (401, 450))

    def test_borders_can_be_changed_in_the_queue(self):
        item = self.book()
        self.assertEqual(downloads.update(item.id, first=5).first, 5)


class TestSplittingTheFolder(unittest.TestCase):
    """Библиотека помнит папку целиком, очередь просит «где» и «как»."""

    def setUp(self):
        from webapp import app as web
        self.split = web._split_folder

    def test_a_full_path_comes_apart(self):
        self.assertEqual(self.split("/книги/Гостиница"), ("/книги", "Гостиница"))

    def test_a_windows_path_comes_apart_too(self):
        self.assertEqual(self.split(r"D:\книги\Гостиница"),
                         (r"D:\книги", "Гостиница"))

    def test_a_trailing_slash_does_not_eat_the_name(self):
        self.assertEqual(self.split("/книги/Гостиница/"),
                         ("/книги", "Гостиница"))

    def test_a_bare_name_has_nowhere_to_put_it(self):
        self.assertEqual(self.split("Гостиница"), ("", "Гостиница"))

    def test_nothing_stays_nothing(self):
        self.assertEqual(self.split(""), ("", ""))


class WebBase(unittest.TestCase):
    """Очередь через маршруты, со своими файлами очереди и библиотеки."""

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

        was = downloads.QUEUE_FILE
        downloads.QUEUE_FILE = Path(self.dir.name) / "downloads.json"
        self.addCleanup(setattr, downloads, "QUEUE_FILE", was)

        from ops import library
        kept = library.LIBRARY_FILE
        library.LIBRARY_FILE = Path(self.dir.name) / "library.json"
        self.addCleanup(setattr, library, "LIBRARY_FILE", kept)
        self.library = library

        from webapp import app as web
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def put(self, **more):
        fields = dict(name="Книга", source="novelcms",
                      address="https://x/read/1/", base="/книги",
                      folder="Книга")
        fields.update(more)
        return self.client.post("/api/downloads/add", json=fields)


class TestTheQueueOverHttp(WebBase):

    def test_an_empty_queue_is_not_an_error(self):
        got = self.client.get("/api/downloads")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["items"], [])

    def test_a_book_without_a_folder_is_refused(self):
        """Очередь работает сама — спросить, куда класть, будет некого."""
        self.assertEqual(self.put(folder="").status_code, 400)

    def test_a_book_with_nothing_to_download_from_still_gets_in(self):
        said = self.put(source="", address="",
                        origin={"site": "qidian", "book_id": "104"}).get_json()
        self.assertEqual(said["item"]["state"], downloads.NEEDS_LINK)
        self.assertEqual(said["state"]["needs_link"], 1)

    def test_a_pasted_link_makes_it_ready(self):
        item = self.put(source="", address="").get_json()["item"]
        said = self.client.post("/api/downloads/update", json={
            "id": item["id"], "source": "novelcms",
            "address": "https://ixdzs8.com/read/566155/"}).get_json()
        self.assertTrue(said["item"]["ready"])
        self.assertEqual(said["item"]["state"], downloads.WAITING)

    def test_a_link_from_a_known_leak_site_picks_its_own_source(self):
        """Спрашивать «чем качать» после вставленной ссылки значило бы
        переспрашивать то, что уже сказано в адресе."""
        item = self.put(source="", address="").get_json()["item"]
        said = self.client.post("/api/downloads/update", json={
            "id": item["id"],
            "address": "https://ixdzs8.com/read/566155/"}).get_json()
        self.assertEqual(said["item"]["source"], "novelcms")
        self.assertTrue(said["item"]["ready"])

    def test_an_unknown_host_is_not_guessed_at(self):
        """Подстановка наобум увела бы разбор к чужим селекторам."""
        item = self.put(source="", address="").get_json()["item"]
        said = self.client.post("/api/downloads/update", json={
            "id": item["id"],
            "address": "https://совсем-незнакомый.example/книга/1"}).get_json()
        self.assertEqual(said["item"]["source"], "")
        self.assertEqual(said["item"]["state"], downloads.NEEDS_LINK)

    def test_a_source_chosen_by_hand_beats_the_guess(self):
        item = self.put(source="", address="").get_json()["item"]
        said = self.client.post("/api/downloads/update", json={
            "id": item["id"], "source": "webnovel",
            "address": "https://ixdzs8.com/read/566155/"}).get_json()
        self.assertEqual(said["item"]["source"], "webnovel")

    def test_editing_a_book_that_is_not_there_says_so(self):
        got = self.client.post("/api/downloads/update", json={"id": "нет"})
        self.assertEqual(got.status_code, 404)

    def test_the_order_can_be_changed(self):
        first = self.put(folder="Первая").get_json()["item"]
        self.put(folder="Вторая")
        said = self.client.post("/api/downloads/move",
                                json={"id": first["id"], "delta": 1}).get_json()
        self.assertEqual([x["folder"] for x in said["items"]],
                         ["Вторая", "Первая"])

    def test_a_book_can_be_taken_out(self):
        item = self.put().get_json()["item"]
        said = self.client.post("/api/downloads/remove",
                                json={"id": item["id"]}).get_json()
        self.assertTrue(said["gone"])
        self.assertEqual(said["items"], [])

    def test_the_queue_can_be_swept(self):
        self.put()
        said = self.client.post("/api/downloads/clear", json={}).get_json()
        self.assertEqual(said["items"], [])

    def test_starting_an_empty_queue_says_what_is_wrong(self):
        got = self.client.post("/api/downloads/start", json={})
        self.assertEqual(got.status_code, 400)

    def test_a_queue_of_books_waiting_for_links_is_not_startable(self):
        """Ни одной строки, которую есть чем качать, — и запускать нечего."""
        self.put(source="", address="")
        self.assertEqual(
            self.client.post("/api/downloads/start", json={}).status_code, 400)

    def test_the_run_settings_are_checked_the_same_as_for_one_book(self):
        """Иначе в очереди оказалось бы разрешено то, что поштучно
        запрещено."""
        self.put()
        got = self.client.post("/api/downloads/start", json={"threads": 500})
        self.assertEqual(got.status_code, 400)
        self.assertIn("Потоков", got.get_json()["error"])


class TestFillingFromTheLibrary(WebBase):
    """«Докачать всё новое»: очередь строится из библиотеки."""

    def book(self, **more):
        fields = dict(found_site="qidian", found_id="104", name="异度旅社",
                      source="novelcms", address="https://x/read/1/",
                      folder="/книги/Гостиница", chapters=402, last=400)
        fields.update(more)
        return self.library.remember(**fields)

    def test_every_book_brings_its_own_source(self):
        """Ради этого библиотека и помнит, чем книгу качали: общего
        источника у очереди не бывает."""
        self.book()
        self.book(found_id="200", name="Вторая", source="fanqie",
                  address="7143038691944959011", folder="/книги/Вторая",
                  chapters=50, last=40)
        said = self.client.post("/api/downloads/fill", json={}).get_json()
        self.assertEqual(said["added"], 2)
        self.assertEqual({x["source"] for x in said["items"]},
                         {"novelcms", "fanqie"})

    def test_the_folder_comes_apart_into_where_and_what(self):
        self.book()
        item = self.client.post("/api/downloads/fill",
                                json={}).get_json()["items"][0]
        self.assertEqual((item["base"], item["folder"]),
                         ("/книги", "Гостиница"))

    def test_only_books_with_new_chapters_are_taken(self):
        self.book()
        self.book(found_id="200", name="Дочитанная", folder="/книги/Вся",
                  chapters=50, last=50)
        said = self.client.post("/api/downloads/fill", json={}).get_json()
        self.assertEqual(said["added"], 1)

    def test_named_books_are_taken_whether_they_are_fresh_or_not(self):
        book = self.book(found_id="200", name="Дочитанная",
                         folder="/книги/Вся", chapters=50, last=50)
        said = self.client.post("/api/downloads/fill",
                                json={"keys": [book.key]}).get_json()
        self.assertEqual(said["added"], 1)

    def test_a_book_nobody_downloaded_is_reported_not_dropped(self):
        """Молчаливый пропуск читался бы как «поставили» — и человек ждал
        бы книгу, которой в очереди нет."""
        book = self.library.remember(found_site="qidian", found_id="777",
                                     name="Только в рейтинге")
        said = self.client.post("/api/downloads/fill",
                                json={"keys": [book.key]}).get_json()
        self.assertEqual(said["added"], 0)
        self.assertEqual(said["missed"][0]["key"], book.key)
        self.assertTrue(said["missed"][0]["why"])

    def test_filling_twice_does_not_double_the_queue(self):
        self.book()
        self.client.post("/api/downloads/fill", json={})
        said = self.client.post("/api/downloads/fill", json={}).get_json()
        self.assertEqual(len(said["items"]), 1)

    def test_the_origin_travels_into_the_queue(self):
        """Без него скачанная книга легла бы в библиотеку второй раз —
        уже под ключом сайта-слива."""
        self.book()
        item = self.client.post("/api/downloads/fill",
                                json={}).get_json()["items"][0]
        self.assertEqual(item["origin"]["site"], "qidian")
        self.assertEqual(item["origin"]["book_id"], "104")


class TestTheQueueReallyDownloads(unittest.TestCase):
    """Очередь на живом (поддельном) сайте: книги ложатся на диск.

    Всё остальное здесь проверяется на подставном `perform`. Этот класс
    отвечает на другой вопрос: доходит ли строка очереди до качалки —
    источник, папка, границы глав, запись в библиотеку.
    """

    def setUp(self):
        from tests.test_mvl import MockSite
        from mvl import client as client_mod

        self.site = MockSite().__enter__()
        self.addCleanup(self.site.__exit__)
        self.pauses = (client_mod.PAUSE_RANGE, client_mod.SITE_PAUSE_RANGE)
        client_mod.PAUSE_RANGE = client_mod.SITE_PAUSE_RANGE = (0, 0)
        self.addCleanup(self.restore, client_mod)

        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        was = downloads.QUEUE_FILE
        downloads.QUEUE_FILE = Path(self.dir.name) / "downloads.json"
        self.addCleanup(setattr, downloads, "QUEUE_FILE", was)

        from ops import library
        kept = library.LIBRARY_FILE
        library.LIBRARY_FILE = Path(self.dir.name) / "library.json"
        self.addCleanup(setattr, library, "LIBRARY_FILE", kept)
        self.library = library

        from webapp import app as web
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()
        self.web = web

    def restore(self, client_mod):
        client_mod.PAUSE_RANGE, client_mod.SITE_PAUSE_RANGE = self.pauses

    def put(self, folder, **more):
        from tests.test_mvl import NOVEL_SLUG

        fields = dict(name="Книга", source="mvlempyr", address=NOVEL_SLUG,
                      base=self.dir.name, folder=folder, first=1, last=3)
        fields.update(more)
        return self.client.post("/api/downloads/add",
                                json=fields).get_json()["item"]

    def finish(self, **payload):
        said = self.client.post("/api/downloads/start", json=payload)
        self.assertEqual(said.status_code, 200, said.get_json())
        job_id = said.get_json()["job"]["id"]
        self.web.JOBS[job_id].thread.join(timeout=120)
        return self.web.JOBS[job_id]

    def test_two_books_are_downloaded_one_after_another(self):
        self.put("Первая")
        self.put("Вторая")
        job = self.finish()
        self.assertIsNone(job.error)
        for name in ("Первая", "Вторая"):
            got = sorted(int(p.name[:4])
                         for p in (Path(self.dir.name) / name).glob("*.txt"))
            self.assertEqual(got, [1, 2, 3], name)

    def test_the_run_says_how_it_went(self):
        self.put("Первая")
        job = self.finish()
        self.assertEqual(job.report["books"], 1)
        self.assertEqual(job.report["failed"], 0)
        self.assertEqual(job.progress["stage"], "done")

    def test_a_book_with_no_such_source_does_not_stop_the_others(self):
        """Ровно то, ради чего очередь книг отделена от очереди
        операций."""
        self.put("Битая", source="нет такого источника")
        self.put("Целая")
        job = self.finish()
        self.assertIsNone(job.error)
        self.assertEqual(job.report["failed"], 1)
        self.assertEqual(job.report["books"], 1)
        self.assertTrue((Path(self.dir.name) / "Целая").is_dir())

    def test_a_downloaded_book_lands_in_the_library(self):
        self.put("Первая", origin={"site": "qidian", "book_id": "104"})
        self.finish()
        book = self.library.get("qidian:104")
        self.assertIsNotNone(book)
        self.assertEqual(book.source, "mvlempyr")

    def test_the_queue_starts_where_the_folder_left_off(self):
        """Границу считаем в момент запуска: заморозь её при постановке —
        за ночь вышло бы ещё три главы, а очередь качала бы вчерашний
        остаток."""
        self.put("Догоняем", first=1, last=3)
        self.finish()

        downloads.clear()
        self.put("Догоняем", first=0, last=0)
        self.finish()
        got = sorted(int(p.name[:4])
                     for p in (Path(self.dir.name) / "Догоняем").glob("*.txt"))
        # Первые три уже лежали — дошли до конца, не переписав их заново.
        self.assertEqual(got[:3], [1, 2, 3])
        self.assertGreater(len(got), 3)

    def test_stopping_the_queue_leaves_the_rest_waiting(self):
        self.put("Первая")
        self.put("Вторая")
        said = self.client.post("/api/downloads/start", json={}).get_json()
        job = self.web.JOBS[said["job"]["id"]]
        job.cancel.set()
        job.thread.join(timeout=120)
        self.assertFalse(any(x.state == downloads.FAILED
                             for x in downloads.all_items()))

    def test_a_stopped_queue_does_not_call_itself_finished(self):
        """«Пройдена» после остановки — неправда: остальные книги ждут."""
        self.put("Первая")
        self.put("Вторая")
        said = self.client.post("/api/downloads/start", json={}).get_json()
        job = self.web.JOBS[said["job"]["id"]]
        job.cancel.set()
        job.thread.join(timeout=120)
        self.assertEqual(job.progress["stage"], "cancelled")
        self.assertNotIn("пройдена", job.progress["message"])


class TestAQueueBrokenOffMidBook(Base):
    """«Качается» пишется на диск, чтобы очередь пережила закрытие окна.

    Но если программу закрыли посреди книги, эта надпись оставалась
    навсегда: очередь показывала работу, которой нет.
    """

    def stuck(self):
        item = self.book()
        rows = downloads.all_items()
        for one in rows:
            one.state = downloads.RUNNING
        downloads._save(rows)
        return item

    def test_the_stuck_row_goes_back_to_waiting(self):
        self.stuck()
        downloads.recover()
        self.assertEqual(downloads.all_items()[0].state, downloads.WAITING)

    def test_it_says_what_happened(self):
        self.stuck()
        downloads.recover()
        self.assertIn("Прервано", downloads.all_items()[0].message)

    def test_it_stays_fixed_after_a_reread(self):
        """Правка живёт в файле: программу закрывают."""
        self.stuck()
        downloads.recover()
        self.assertEqual(downloads._load()[0].state, downloads.WAITING)

    def test_a_finished_book_is_left_alone(self):
        self.book()
        rows = downloads.all_items()
        rows[0].state = downloads.DONE
        rows[0].message = "скачано 40 глав"
        downloads._save(rows)

        downloads.recover()
        self.assertEqual(downloads.all_items()[0].state, downloads.DONE)
        self.assertEqual(downloads.all_items()[0].message, "скачано 40 глав")

    def test_reading_the_queue_during_a_run_does_not_clear_it(self):
        """Пока очередь работает, «качается» — это правда."""
        self.stuck()
        self.assertEqual(downloads.all_items()[0].state, downloads.RUNNING)


if __name__ == "__main__":
    unittest.main()


class TestSeveralBooksAtOnce(Base):
    """Ждать, пока докачается первая, чтобы начать вторую, незачем.

    Книги независимы, и узкое место у них не общее: одна упирается в
    медленный сайт, другая в разбор. Очередь тут была не устройством, а
    привычкой.
    """

    def three(self):
        for name in ("Первая", "Вторая", "Третья"):
            self.book(folder=name)

    def test_by_default_nothing_changes(self):
        """Прежнее поведение остаётся прежним: книги идут подряд."""
        self.three()
        seen = []
        downloads.run(lambda item: seen.append(item.folder) or "готово")

        self.assertEqual(seen, ["Первая", "Вторая", "Третья"])

    def test_asked_for_three_at_once_all_three_are_in_flight_together(self):
        """Собственно проверка параллельности: все три начались раньше,
        чем кончилась первая."""
        import threading

        self.three()
        started = threading.Barrier(3, timeout=20)

        def perform(item):
            # Барьер отпустит только когда в нём соберутся все трое.
            # Иди книги подряд — первая же ждала бы вечно и упала.
            started.wait()
            return "готово"

        rows = downloads.run(perform, workers=3)
        self.assertTrue(all(x.state == downloads.DONE for x in rows))

    def test_the_order_of_the_list_is_not_shuffled_by_the_run(self):
        """Строки остаются на местах: меняется только то, что несколько
        из них горят «качается» разом."""
        self.three()
        downloads.run(lambda item: "готово", workers=3)

        self.assertEqual([x.folder for x in downloads.all_items()],
                         ["Первая", "Вторая", "Третья"])

    def test_a_broken_book_still_does_not_cancel_the_rest(self):
        self.three()

        def perform(item):
            if item.folder == "Вторая":
                raise RuntimeError("сайт закрыл доступ")
            return "готово"

        rows = downloads.run(perform, workers=3)
        self.assertEqual([x.state for x in rows],
                         [downloads.DONE, downloads.FAILED, downloads.DONE])
        self.assertIn("сайт закрыл доступ", rows[1].message)

    def test_every_book_keeps_its_own_outcome(self):
        """Две книги, кончившие разом, затирали бы записи друг друга."""
        self.three()
        rows = downloads.run(lambda item: f"итог {item.folder}", workers=3)

        self.assertEqual([x.message for x in rows],
                         ["итог Первая", "итог Вторая", "итог Третья"])

    def test_the_outcomes_survive_on_disk_too(self):
        """Записи идут в один файл из трёх потоков сразу."""
        self.three()
        downloads.run(lambda item: f"итог {item.folder}", workers=3)

        self.assertEqual([x.message for x in downloads.all_items()],
                         ["итог Первая", "итог Вторая", "итог Третья"])

    def test_stopping_leaves_the_untouched_books_waiting(self):
        """Не начатое ждёт, а не помечается неудачей: очередь продолжат
        тем же нажатием, что и начали."""
        import threading

        self.three()
        stop = threading.Event()

        def perform(item):
            stop.set()
            raise RuntimeError("оборвано")

        rows = downloads.run(perform, cancel=stop, workers=1)
        self.assertEqual(rows[0].state, downloads.WAITING)
        self.assertEqual(rows[0].message, "")

    def test_more_workers_than_books_is_not_a_problem(self):
        self.book(folder="Одна")
        rows = downloads.run(lambda item: "готово", workers=8)

        self.assertEqual([x.state for x in rows], [downloads.DONE])

    def test_the_number_at_once_is_capped(self):
        """Двадцать книг разом — это сотни глав в минуту с одного адреса:
        сайт закроется, и виноват будет не он."""
        import threading

        for number in range(downloads.MAX_AT_ONCE + 4):
            self.book(folder=f"Книга {number}")

        peak, now = [0], [0]
        guard = threading.Lock()

        def perform(item):
            with guard:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            time.sleep(0.05)
            with guard:
                now[0] -= 1
            return "готово"

        downloads.run(perform, workers=100)
        self.assertLessEqual(peak[0], downloads.MAX_AT_ONCE)

    def test_a_book_waiting_for_a_link_is_still_stepped_over(self):
        downloads.add(name="Без ссылки", base="/книги", folder="Б")
        self.book(folder="Готовая")
        seen = []
        downloads.run(lambda item: seen.append(item.folder) or "готово",
                      workers=4)

        self.assertEqual(seen, ["Готовая"])


class TestTheKnobReachesTheRun(unittest.TestCase):
    """Ручка на экране, не доехавшая до прогона, — самая тихая поломка.

    Число стоит, человек его меняет, а сервер молча берёт своё умолчание.
    Проверяется именно стык: настройки разбираются и доходят до качалки.
    """

    def setUp(self):
        from webapp import app as web

        self.web = web
        web.app.config["TESTING"] = True

    def settings(self, **more):
        return self.web._run_settings({"threads": 3, **more})

    def test_the_number_of_books_is_read_from_the_request(self):
        self.assertEqual(self.settings(books=4).books, 4)

    def test_zero_means_count_it_by_the_proxies(self):
        """Ноль здесь не «ни одной книги», а «считай сам».

        Сколько книг потянет список адресов, человек не знает, пока его
        не проверит, — и заставлять его считать в уме незачем.
        """
        self.assertEqual(self.settings(books=0).books, downloads.AUTO)
        self.assertEqual(self.settings().books, downloads.AUTO)

    def test_a_silly_number_is_refused_with_words(self):
        for bad in (-3, downloads.MAX_AT_ONCE + 1, 500):
            with self.subTest(bad):
                with self.assertRaises(ValueError) as caught:
                    self.settings(books=bad)
                self.assertIn("Книг разом", str(caught.exception))

    def test_a_word_instead_of_a_number_is_refused_too(self):
        with self.assertRaises(ValueError):
            self.settings(books="много")

    def test_never_more_workers_than_there_are_books(self):
        """Пять потоков на одну книгу — это четыре пустых потока."""
        from tempfile import TemporaryDirectory

        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        was_file = downloads.QUEUE_FILE
        downloads.QUEUE_FILE = Path(folder.name) / "downloads.json"
        self.addCleanup(setattr, downloads, "QUEUE_FILE", was_file)

        seen = {}
        was = self.web.downloads_op.run
        self.web.downloads_op.run = lambda perform, on_change=None, \
            cancel=None, workers=1: seen.setdefault("workers", workers) or []
        self.addCleanup(setattr, self.web.downloads_op, "run", was)

        downloads.add(name="Одна", source="novelcms",
                      address="https://x/read/1/", base=folder.name,
                      folder="Одна")
        with self.web.app.test_request_context():
            self.web._downloads_start({"threads": 1, "books": 5})
        for _ in range(200):
            if "workers" in seen:
                break
            time.sleep(0.02)

        self.assertEqual(seen.get("workers"), 1)

    def test_the_number_reaches_the_runner(self):
        """Тот самый стык: из тела запроса — в аргумент прогона."""
        seen = {}
        was = self.web.downloads_op.run

        def spy(perform, on_change=None, cancel=None, workers=1):
            seen["workers"] = workers
            return []

        self.web.downloads_op.run = spy
        self.addCleanup(setattr, self.web.downloads_op, "run", was)

        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        was_file = downloads.QUEUE_FILE
        downloads.QUEUE_FILE = Path(folder.name) / "downloads.json"
        self.addCleanup(setattr, downloads, "QUEUE_FILE", was_file)
        # Книг ровно столько, сколько просим вести разом: план считается
        # и по ним тоже — гнать пять потоков на одну книгу незачем.
        for number in range(5):
            downloads.add(name=f"Книга {number}", source="novelcms",
                          address=f"https://x/read/{number}/",
                          base=folder.name, folder=f"Книга {number}")

        with self.web.app.test_request_context():
            self.web._downloads_start({"threads": 1, "books": 5})

        # Задача уходит в поток; дожидаемся, пока она позовёт прогон.
        for _ in range(200):
            if "workers" in seen:
                break
            time.sleep(0.02)
        self.assertEqual(seen.get("workers"), 5)


class TestTheProgressReachesTheScreen(unittest.TestCase):
    """Что качалка рассказывает о себе — должно доезжать до страницы.

    Беда была тихая и оттого злая: наверх уходили только счётчики, а этап
    и надпись терялись. На экране полчаса висело «Запускаем…», хотя книга
    давно читала оглавление, — и «Остановить» выглядела мёртвой, потому
    что страница по этапу решает, кончилась работа или нет.
    """

    def setUp(self):
        from tempfile import TemporaryDirectory

        from webapp import app as web

        self.web = web
        web.app.config["TESTING"] = True

        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        was = downloads.QUEUE_FILE
        downloads.QUEUE_FILE = self.tmp / "downloads.json"
        self.addCleanup(setattr, downloads, "QUEUE_FILE", was)

        was_lib = library.LIBRARY_FILE
        library.LIBRARY_FILE = self.tmp / "library.json"
        self.addCleanup(setattr, library, "LIBRARY_FILE", was_lib)

        self.said = []          # что качалка рассказала о себе
        self.clients = []       # с какими доводами создавали клиента
        self.made = []          # с какими доводами создавали качалку
        self.threads = 1        # сколько потоков просим с экрана
        self.reported = threading.Event()   # доклад сделан
        # Книг разом бывает несколько, и одного флага на всех мало:
        # дождаться надо каждую, иначе проверка смотрит на полусобранное.
        self.arrived = threading.Semaphore(0)
        self.release = threading.Event()    # можно заканчивать книгу
        self.raises = None                  # чем книга обрывается, если рвётся
        self.breaks = None                  # чем обрывается поиск книги
        self.addCleanup(self.release.set)
        self._fake_world()

    def _fake_world(self):
        """Источник, клиент и качалка — поддельные, стык — настоящий."""
        web = self.web
        outer = self

        class FakeNovel:
            name, slug, author, cover = "Книга", "kniga", "Автор", ""
            code, total_chapters = 1, 5
            about, status, language = "Про охотниц", "выходит", "ru"
            genres, tags = ["Фэнтези"], ["Гарем"]

        class FakeSource:
            key = "novelcms"

            def find(self, client, address):
                if outer.breaks is not None:
                    raise outer.breaks
                return FakeNovel()

        class FakeClient:
            def __init__(self, **kw):
                outer.clients.append(kw)

            def close(self):
                pass

        class FakeDownloader:
            def __init__(self, **kw):
                outer.made.append(kw)
                self.on_progress = kw.get("on_progress")

            def run(self, novel, output_dir, first=1, last=1):
                for one in outer.said:
                    self.on_progress(one)
                # Держим книгу недокачанной, пока проверка не посмотрит:
                # после конца очереди надпись законно перетирается итогом,
                # и проверять там было бы нечего.
                outer.reported.set()
                outer.arrived.release()
                outer.release.wait(timeout=20)
                if outer.raises is not None:
                    raise outer.raises
                return SimpleNamespace(as_dict=lambda: {"downloaded": 1})

        for name, value in (("Client", FakeClient),
                            ("Downloader", FakeDownloader)):
            was = getattr(web, name)
            setattr(web, name, value)
            self.addCleanup(setattr, web, name, was)

        was_get = web.sources.get
        web.sources.get = lambda key: FakeSource()
        self.addCleanup(setattr, web.sources, "get", was_get)

        was_keep = web._prepare
        web._prepare = lambda base, folder, op, only=None: web.Made(
            dir=self.tmp / "вывод")
        self.addCleanup(setattr, web, "_prepare", was_keep)
        (self.tmp / "вывод").mkdir(exist_ok=True)

    def step(self, **fields):
        """Один доклад качалки о себе — как её настоящий `Progress`."""
        return SimpleNamespace(as_dict=lambda: fields)

    def start(self, books: int = 1):
        """Запустить очередь и дождаться доклада качалки о себе."""
        downloads.add(name="Книга", source="novelcms",
                      address="https://x/read/1/", base=str(self.tmp),
                      folder="Книга")
        with self.web.app.test_request_context():
            answer = self.web._downloads_start(
                {"threads": self.threads, "books": books})

        job = self.web.JOBS[answer.get_json()["job"]["id"]]
        self.assertTrue(self.reported.wait(timeout=20), "качалку не позвали")
        return job

    def finish(self, job):
        self.release.set()
        job.thread.join(timeout=30)
        return job

    def test_the_stage_and_the_words_reach_the_job(self):
        """Без них на экране остаётся «Запускаем…» до самого конца."""
        self.said = [self.step(stage="toc", message="Оглавление… 3 из 5",
                               done=3, total=5)]
        job = self.start()

        self.assertEqual(job.progress["message"], "Оглавление… 3 из 5")
        self.assertEqual(job.progress["stage"], "toc")
        self.assertEqual(job.progress["done"], 3)
        self.finish(job)

    def test_the_proxy_and_the_threads_reach_it_too(self):
        """Строка «через такой-то, переключений N» бралась оттуда же."""
        self.said = [self.step(stage="download", proxy="1.2.3.4:8080",
                               switches=2, threads=3)]
        job = self.start()

        self.assertEqual(job.progress["proxy"], "1.2.3.4:8080")
        self.assertEqual(job.progress["threads"], 3)
        self.assertEqual(job.progress["switches"], 2)
        self.finish(job)

    def test_the_end_of_one_book_is_not_the_end_of_the_queue(self):
        """Иначе страница перестанет опрашивать задачу на первой из
        тринадцати и покажет «готово» при двенадцати неначатых."""
        self.said = [self.step(stage="download", done=5, total=5),
                     self.step(stage="done", done=5, total=5)]
        job = self.start()

        # Книга уже сказала «done», а очередь ещё идёт — и на экране это
        # не должно выглядеть законченной работой.
        self.assertEqual(job.progress["stage"], "download")
        self.finish(job)
        # Итоговый этап ставит сам прогон — и только когда очередь вся.
        self.assertEqual(job.progress["stage"], "done")

    def test_one_book_alone_tells_the_client_about_it_too(self):
        """Одна книга или тринадцать — «Остановить» должна доходить до
        повторов одинаково. Путь у них разный, и правку легко внести
        только в один."""
        self.said = []
        # Зовём маршрут тем же способом, каким его зовёт страница.
        answer = self.web.app.test_client().post("/api/start", json={
            "novel": {"code": 1, "name": "Книга", "total_chapters": 3},
            "base": str(self.tmp), "folder": "Книга",
            "threads": 1, "timeout": 30, "connect_timeout": 10})
        self.assertEqual(answer.status_code, 200, answer.get_data(as_text=True))

        job = self.web.JOBS[answer.get_json()["job"]["id"]]
        self.assertTrue(self.reported.wait(timeout=20), "качалку не позвали")
        self.assertTrue(self.clients, "клиента не создавали")
        self.assertIs(self.clients[-1].get("cancel"), job.cancel)
        self.finish(job)

    def test_a_book_lands_in_the_library_before_it_is_downloaded(self):
        """У человека упали все тринадцать книг разом — сайт перестал
        разрешаться по имени. Очередь опустела, в библиотеке не осталось
        ничего, и «докачать» было нечего. А список нужен ровно тогда:
        чтобы вернуться, когда сайт оживёт."""
        self.said = []
        job = self.start()

        rows = library.all_books()
        self.assertEqual([one.name for one in rows], ["Книга"])
        self.assertEqual(rows[0].source, "novelcms")
        self.assertEqual(rows[0].address, "https://x/read/1/")
        self.finish(job)

    def test_it_stays_there_even_when_the_download_falls(self):
        was = self.web.sources.get

        def broken(key):
            raise RuntimeError("сайт не разрешается по имени")

        self.web.sources.get = broken
        self.addCleanup(setattr, self.web.sources, "get", was)

        downloads.add(name="Книга", source="novelcms",
                      address="https://x/read/1/", base=str(self.tmp),
                      folder="Книга")
        with self.web.app.test_request_context():
            answer = self.web._downloads_start({"threads": 1, "books": 1})
        job = self.web.JOBS[answer.get_json()["job"]["id"]]
        job.thread.join(timeout=30)

        self.assertEqual([one.name for one in library.all_books()], ["Книга"])

    def with_proxies(self, usable: int):
        """Проверенный список адресов — столько-то рабочих."""
        pool = SimpleNamespace(checked=True, usable_count=usable)
        was = self.web.POOL
        self.web.POOL = pool
        self.addCleanup(setattr, self.web, "POOL", was)

    def test_the_book_gets_the_threads_the_plan_gave_it(self):
        """Два адреса и три потока на экране — книге достаётся два.

        Число с экрана тут нарочно расходится с расчётом: совпади они,
        проверка не отличила бы одно от другого. Бери книга своё число
        мимо расчёта — она пустила бы три потока на два адреса, и третий
        пошёл бы напрямую, мимо прокси.
        """
        self.with_proxies(2)
        self.threads = 3
        self.said = []
        job = self.start(books=downloads.AUTO)

        self.assertTrue(self.made, "качалку не создавали")
        self.assertEqual(self.made[0].get("threads"), 2)
        self.finish(job)

    def test_the_number_of_books_is_counted_from_the_proxies(self):
        """Ноль на экране значит «посчитай сам»: пять адресов в один
        поток — пять книг разом."""
        self.with_proxies(5)
        seen = {}
        was = self.web.downloads_op.run
        self.web.downloads_op.run = lambda perform, on_change=None, \
            cancel=None, workers=1: seen.setdefault("workers", workers) or []
        self.addCleanup(setattr, self.web.downloads_op, "run", was)

        for number in range(6):
            downloads.add(name=f"Книга {number}", source="novelcms",
                          address=f"https://x/read/{number}/",
                          base=str(self.tmp), folder=f"Книга {number}")
        with self.web.app.test_request_context():
            self.web._downloads_start({"threads": 1, "books": 0})
        for _ in range(200):
            if "workers" in seen:
                break
            time.sleep(0.02)

        self.assertEqual(seen.get("workers"), 5)

    def test_what_the_site_says_about_the_book_is_kept(self):
        """Описание собирается один раз, при скачивании: потом спросить
        будет не у кого — сайт ляжет, а книга в библиотеке останется."""
        self.said = []
        job = self.start()
        self.finish(job)

        book = library.all_books()[0]
        self.assertEqual(book.about, "Про охотниц")
        self.assertEqual(book.genres, ["Фэнтези"])
        self.assertEqual(book.site_tags, ["Гарем"])

    def test_the_book_lands_in_the_library_once_not_twice(self):
        """Запись до качания и запись после должны попасть в одну строку.

        Ключ считается по адресу, а у строки очереди он свой — тот, что
        человек вставил, — тогда как у найденной книги свой слаг. Разойдись
        они, и одна книга легла бы в библиотеку дважды: раз пустой, раз с
        описанием.
        """
        self.said = []
        job = self.start()
        self.finish(job)

        rows = library.all_books()
        self.assertEqual(len(rows), 1, [one.key for one in rows])
        self.assertEqual(rows[0].about, "Про охотниц")

    def test_the_client_is_told_about_the_stop_button(self):
        """Качалка смотрит на флаг между главами, а лесенка повторов
        внутри клиента про него не знала: на мёртвом адресе «Остановить»
        дожидалась конца всех повторов по каждой главе."""
        self.said = []
        job = self.start()

        self.assertTrue(self.clients, "клиента не создавали")
        self.assertIs(self.clients[0].get("cancel"), job.cancel)
        self.finish(job)

    def start_many(self, titles):
        """Поставить несколько книг и дождаться, пока возьмут каждую."""
        for number, title in enumerate(titles, 1):
            downloads.add(name=title, source="novelcms",
                          address=f"https://x/read/{number}/",
                          base=str(self.tmp), folder=title)
        with self.web.app.test_request_context():
            answer = self.web._downloads_start(
                {"threads": self.threads, "books": len(titles)})

        job = self.web.JOBS[answer.get_json()["job"]["id"]]
        for _ in titles:
            self.assertTrue(self.arrived.acquire(timeout=20),
                            "качалку позвали не на все книги")
        return job

    def rows_of(self, job) -> dict:
        """Строки книг, разложенные по названию."""
        return {one["title"]: one for one in job.progress["each"]}

    def test_every_book_says_its_own_numbers(self):
        """Наверху — сумма по всей очереди, и кто чем занят, из неё не
        видно: «Глава 1823 из 1868» при тринадцати книгах читается так,
        будто качается одна."""
        self.said = [self.step(stage="download", done=2, total=5,
                               proxy="1.1.1.1:80", threads=1)]
        job = self.start_many(["Книга А", "Книга Б"])

        rows = self.rows_of(job)
        self.assertEqual(sorted(rows), ["Книга А", "Книга Б"])
        for title, row in rows.items():
            self.assertEqual((row["done"], row["total"]), (2, 5), title)
            self.assertEqual(row["proxy"], "1.1.1.1:80", title)
        self.finish(job)

    def test_the_sum_of_the_rows_is_what_stands_on_top(self):
        """Обе стороны нужны разом: строки говорят, кто где, а сумма —
        сколько осталось всего."""
        self.said = [self.step(stage="download", done=2, total=5,
                               downloaded=2)]
        job = self.start_many(["Книга А", "Книга Б"])

        self.assertEqual(job.progress["done"], 4)
        self.assertEqual(job.progress["total"], 10)
        self.assertEqual(job.progress["downloaded"], 4)
        self.finish(job)

    def test_nothing_of_one_book_is_passed_off_as_the_whole_queue(self):
        """Ровно та жалоба: наверху висело «Качаем главы — Глава 1823 из
        1868» и один адрес прокси, будто книга одна. Этап, надпись и
        адрес принадлежат книге — наверху они принадлежали бы той, что
        отчиталась последней, то есть никому."""
        self.said = [self.step(stage="toc", message="Глава 1823 из 1868",
                               proxy="1.1.1.1:80")]
        job = self.start_many(["Книга А", "Книга Б"])

        self.assertNotEqual(job.progress["message"], "Глава 1823 из 1868")
        self.assertEqual(job.progress["stage"], "download")
        self.assertFalse(job.progress.get("proxy"))
        # А в своей строке книга это же и говорит.
        row = self.rows_of(job)["Книга А"]
        self.assertEqual(row["message"], "Глава 1823 из 1868")
        self.assertEqual(row["stage"], "toc")
        self.finish(job)

    def test_the_only_book_still_speaks_from_the_top(self):
        """Книга одна — говорить наверху больше некому, и молчание там
        вернуло бы «Запускаем…» на полчаса и мёртвую «Остановить»."""
        self.said = [self.step(stage="toc", message="Оглавление… 3 из 5",
                               proxy="1.1.1.1:80")]
        job = self.start()

        self.assertEqual(job.progress["stage"], "toc")
        self.assertEqual(job.progress["message"], "Оглавление… 3 из 5")
        self.assertEqual(job.progress["proxy"], "1.1.1.1:80")
        self.finish(job)

    def test_a_book_still_being_looked_for_already_has_a_row(self):
        """Искать книгу можно долго. Заведись строка только после
        находки — всё это время не было бы видно, что книгу вообще
        взяли: полоса появлялась бы из ниоткуда."""
        looking = threading.Event()
        holding = threading.Event()
        self.addCleanup(holding.set)

        class Slow:
            key = "novelcms"

            def find(self, client, address):
                looking.set()
                holding.wait(timeout=20)
                raise RuntimeError("искали-искали и не нашли")

        was = self.web.sources.get
        self.web.sources.get = lambda key: Slow()
        self.addCleanup(setattr, self.web.sources, "get", was)

        downloads.add(name="Книга А", source="novelcms",
                      address="https://x/read/1/", base=str(self.tmp),
                      folder="Книга А")
        with self.web.app.test_request_context():
            answer = self.web._downloads_start({"threads": 1, "books": 1})
        job = self.web.JOBS[answer.get_json()["job"]["id"]]
        self.assertTrue(looking.wait(timeout=20), "книгу не искали")

        row = self.rows_of(job)["Книга А"]
        self.assertEqual(row["stage"], "search")
        holding.set()
        job.thread.join(timeout=30)

    def test_a_stopped_book_says_stopped_and_not_broken(self):
        """«Остановлено» и «сломалось» — разные вещи. Скажи строка
        «ошибка» на нажатую человеком кнопку, он полез бы чинить
        исправное."""
        self.said = []
        self.raises = OpCancelled()
        job = self.start_many(["Книга А", "Книга Б"])
        self.finish(job)

        for title, row in self.rows_of(job).items():
            self.assertEqual(row["stage"], "cancelled", title)

    def test_a_fallen_book_says_so_in_its_own_row(self):
        """Иначе упавшая книга навсегда осталась бы на «Качаем главы»:
        полоса идёт, а работа давно оборвалась."""
        was = self.web.sources.get
        self.web.sources.get = lambda key: (_ for _ in ()).throw(
            RuntimeError("сайт не разрешается по имени"))
        self.addCleanup(setattr, self.web.sources, "get", was)

        downloads.add(name="Книга А", source="novelcms",
                      address="https://x/read/1/", base=str(self.tmp),
                      folder="Книга А")
        downloads.add(name="Книга Б", source="novelcms",
                      address="https://x/read/2/", base=str(self.tmp),
                      folder="Книга Б")
        with self.web.app.test_request_context():
            answer = self.web._downloads_start({"threads": 1, "books": 2})
        job = self.web.JOBS[answer.get_json()["job"]["id"]]
        job.thread.join(timeout=30)

        rows = self.rows_of(job)
        self.assertEqual(sorted(rows), ["Книга А", "Книга Б"])
        for title, row in rows.items():
            self.assertEqual(row["stage"], "error", title)
            self.assertIn("не разрешается", row["message"], title)

    def test_a_dns_failure_is_put_into_words_the_person_asked_for(self):
        """Человек видит в строке стену английского от curl и спрашивает:
        «я же могу перейти по ссылке, а парсер не может». Ответ в том, что
        хосты разные, — и он должен стоять там же, в строке."""
        from mvl.client import NetworkError

        self.breaks = NetworkError(
            "DNSError: Failed to perform, curl: (6) Could not resolve host: "
            "chap.heliosarchive.online. See https://curl.se/ for more details.")

        downloads.add(name="Книга А", source="novelcms",
                      address="https://x/read/1/", base=str(self.tmp),
                      folder="Книга А")
        with self.web.app.test_request_context():
            answer = self.web._downloads_start({"threads": 1, "books": 1})
        job = self.web.JOBS[answer.get_json()["job"]["id"]]
        job.thread.join(timeout=30)

        said = self.rows_of(job)["Книга А"]["message"]
        self.assertIn("chap.heliosarchive.online", said)
        self.assertIn("браузере", said)
        # Слова curl никуда не деваются: по ним и чинят.
        self.assertIn("Could not resolve host", said)

    def test_a_finished_book_keeps_its_row(self):
        """Строка кончившейся книги — единственный след того, чем она
        кончилась: очередь к тому времени показывает уже следующую."""
        self.said = [self.step(stage="download", done=5, total=5,
                               downloaded=5)]
        job = self.start_many(["Книга А", "Книга Б"])
        self.finish(job)

        rows = self.rows_of(job)
        self.assertEqual(sorted(rows), ["Книга А", "Книга Б"])
        for title, row in rows.items():
            self.assertEqual(row["stage"], "done", title)
            self.assertIn("Скачано глав", row["message"], title)


class TestHowManyBooksTheProxiesAllow(unittest.TestCase):
    """Один поток занимает один прокси — отсюда и весь расчёт.

    Человеку незачем считать это в уме: он проверил список адресов, и
    программа сама знает, сколько книг потянет.
    """

    def test_five_proxies_in_one_thread_are_five_books(self):
        self.assertEqual(downloads.spread(5, 1, 13), [1, 1, 1, 1, 1])

    def test_five_proxies_in_three_threads_are_two_books(self):
        """Одна книга в три потока и вторая в два: больше адресов нет."""
        self.assertEqual(downloads.spread(5, 3, 13), [3, 2])

    def test_the_leftover_proxies_do_not_idle(self):
        """Честным делением вышла бы одна книга, а два проверенных
        адреса простаивали бы без дела."""
        self.assertEqual(sum(downloads.spread(5, 3, 13)), 5)

    def test_fewer_proxies_than_threads_still_start_one_book(self):
        self.assertEqual(downloads.spread(2, 3, 13), [2])

    def test_without_proxies_we_go_straight_and_do_not_divide(self):
        """Делить нечего: одна книга во столько потоков, сколько просили."""
        self.assertEqual(downloads.spread(0, 3, 13), [3])

    def test_never_more_books_than_there_are(self):
        self.assertEqual(downloads.spread(5, 1, 2), [1, 1])

    def test_an_empty_queue_needs_no_plan(self):
        self.assertEqual(downloads.spread(5, 1, 0), [])

    def test_the_ceiling_holds_even_with_a_hundred_proxies(self):
        """Сотня книг разом — это сотни запросов в минуту с одного
        адреса: сайт закроется, и виноват будет не он."""
        plan = downloads.spread(100, 1, 100)
        self.assertEqual(len(plan), downloads.MAX_AT_ONCE)


class TestTheNightGoesTheWholeRound(unittest.TestCase):
    """Ночь должна спросить, добрать и только потом качать.

    Раньше она начиналась сразу с прогона — и гнала пустую очередь: число
    глав записывает прогон, а спросить, вышли ли новые, было некому. Так
    «постоянно качать обновления» работало ровно до тех пор, пока человек
    сам не нажимал две кнопки перед сном.
    """

    def setUp(self):
        from tempfile import TemporaryDirectory

        from webapp import app as web

        self.web = web
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        for module, name in ((downloads, "QUEUE_FILE"),
                             (library, "LIBRARY_FILE")):
            was = getattr(module, name)
            setattr(module, name, self.tmp / f"{name.lower()}.json")
            self.addCleanup(setattr, module, name, was)

    def a_book_with_new_chapters(self):
        library.remember("k", name="Книга", source="novelcms",
                         address="https://x/read/1/",
                         folder=str(self.tmp / "Книга"),
                         chapters=10, last=5)

    def test_the_sites_are_asked_before_anything_is_downloaded(self):
        asked = []
        was = self.web._check_updates
        self.web._check_updates = lambda keys, cancel=None: (
            asked.extend(keys) or ([], []))
        self.addCleanup(setattr, self.web, "_check_updates", was)

        self.a_book_with_new_chapters()
        self.web._nightly_catch_up()

        self.assertEqual(asked, ["k"])

    def test_a_book_with_new_chapters_lands_in_the_queue(self):
        was = self.web._check_updates
        self.web._check_updates = lambda keys, cancel=None: (list(keys), [])
        self.addCleanup(setattr, self.web, "_check_updates", was)

        self.a_book_with_new_chapters()
        added = self.web._nightly_catch_up()

        self.assertEqual(added, 1)
        self.assertEqual([one.name for one in downloads.all_items()],
                         ["Книга"])

    def test_a_book_without_new_chapters_is_left_alone(self):
        was = self.web._check_updates
        self.web._check_updates = lambda keys, cancel=None: (list(keys), [])
        self.addCleanup(setattr, self.web, "_check_updates", was)

        library.remember("k", name="Книга", source="novelcms",
                         address="https://x/read/1/",
                         folder=str(self.tmp / "Книга"),
                         chapters=5, last=5)
        self.assertEqual(self.web._nightly_catch_up(), 0)

    def test_a_book_nobody_knows_how_to_download_is_not_asked_about(self):
        """Спрашивать не у кого: источник у неё не записан."""
        asked = []
        was = self.web._check_updates
        self.web._check_updates = lambda keys, cancel=None: (
            asked.extend(keys) or ([], []))
        self.addCleanup(setattr, self.web, "_check_updates", was)

        library.remember("руками", name="Вписана руками")
        self.web._nightly_catch_up()

        self.assertEqual(asked, [])

    def test_the_tick_catches_up_before_it_starts_the_run(self):
        """Порядок и есть вся суть: спросить, добрать, потом качать.

        Убери первый шаг — очередь останется пустой, и ночь пройдёт
        впустую, ничем себя не выдав.
        """
        order = []
        for name, mark in (("_nightly_catch_up", "добрали"),
                           ("_downloads_start", "погнали")):
            was = getattr(self.web, name)
            setattr(self.web, name, lambda *a, _m=mark, **kw:
                    order.append(_m) or 0)
            self.addCleanup(setattr, self.web, name, was)

        was_due = self.web.schedule_op.due
        was_mark = self.web.schedule_op.mark
        was_get = self.web.schedule_op.get
        self.web.schedule_op.due = lambda: True
        self.web.schedule_op.mark = lambda: None
        self.web.schedule_op.get = lambda: SimpleNamespace(payload={})
        for name, value in (("due", was_due), ("mark", was_mark),
                            ("get", was_get)):
            self.addCleanup(setattr, self.web.schedule_op, name, value)

        self.assertTrue(self.web._schedule_tick())
        self.assertEqual(order, ["добрали", "погнали"])

    def test_nothing_happens_when_the_hour_has_not_come(self):
        was = self.web.schedule_op.due
        self.web.schedule_op.due = lambda: False
        self.addCleanup(setattr, self.web.schedule_op, "due", was)

        self.assertFalse(self.web._schedule_tick())

    def test_one_silent_site_does_not_cost_the_whole_night(self):
        """Прогон всё равно заберёт то, что уже стоит в очереди."""
        was = self.web._check_updates

        def broken(keys, cancel=None):
            raise RuntimeError("сайт молчит")

        self.web._check_updates = broken
        self.addCleanup(setattr, self.web, "_check_updates", was)

        self.a_book_with_new_chapters()
        self.assertEqual(self.web._nightly_catch_up(), 0)


class TestWhatGetsRefreshedInTheLibrary(unittest.TestCase):
    """Что проверка обновлений дописывает в запись, а что трогать не смеет.

    `remember` дополняет запись, а не заменяет, — но одноимённое поле он
    перезапишет, и пустое значение отсюда стёрло бы уже накопленное.
    """

    def setUp(self):
        from webapp import app as web

        self.web = web

    def novel(self, **fields):
        said = {"about": "", "genres": [], "tags": [], "cover": "",
                "status": "", "language": ""}
        said.update(fields)
        return SimpleNamespace(**said)

    def test_the_cover_the_source_knows_is_written_down(self):
        said = self.web._about_fields(self.novel(cover="https://x/6615.webp"),
                                      {})

        self.assertEqual(said["cover"], "https://x/6615.webp")

    def test_a_source_that_knows_no_cover_does_not_erase_the_one_stored(self):
        """У книги, заведённой из рейтинга, обложка была с самого начала,
        а источник её может и не знать: пустая строка отсюда стёрла бы
        картинку при первой же ночной проверке."""
        said = self.web._about_fields(self.novel(), {})

        self.assertNotIn("cover", said)

    def test_the_russian_twins_still_never_come_from_here(self):
        """Перевод, за который заплачено, уходить не должен."""
        said = self.web._about_fields(
            self.novel(about="About the hunters", genres=["Fantasy"]), {})

        self.assertNotIn("about_ru", said)
        self.assertNotIn("genres_ru", said)
        self.assertNotIn("site_tags_ru", said)
        self.assertNotIn("name_ru", said)


class TestWhyTheCheckDidNotGoThrough(unittest.TestCase):
    """«Не ответили: 12» — это не ответ, а отписка.

    Человек жмёт кнопку, в библиотеке ничего не меняется, и виноватой
    выглядит кнопка. Причина же на сервере есть — её просто выбрасывали.
    """

    def setUp(self):
        from webapp import app as web

        self.web = web
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        was = library.LIBRARY_FILE
        library.LIBRARY_FILE = self.tmp / "library.json"
        self.addCleanup(setattr, library, "LIBRARY_FILE", was)

        library.remember("k", name="Книга", source="mvlempyr",
                         address="kniga", chapters=10, last=5)

    def breaks_with(self, trouble):
        """Источник, который на любой вопрос отвечает этой бедой."""
        source = SimpleNamespace(
            key="mvlempyr", name="MVLEMPYR",
            find=lambda client, query: (_ for _ in ()).throw(trouble))
        was = self.web.sources.get
        self.web.sources.get = lambda key: source
        self.addCleanup(setattr, self.web.sources, "get", was)

        was_client = self.web.Client
        self.web.Client = lambda **kw: SimpleNamespace(close=lambda: None)
        self.addCleanup(setattr, self.web, "Client", was_client)

    def test_the_reason_comes_back_with_the_miss(self):
        from mvl.client import HttpError

        self.breaks_with(HttpError("HTTP 502 — каталог молчит"))
        _, missed = self.web._check_updates(["k"])

        self.assertEqual(len(missed), 1)
        self.assertIn("502", missed[0]["why"])

    def test_a_dns_failure_is_explained_here_too(self):
        """Та же беда, что валит качалку, валит и проверку — и объяснять
        её надо теми же словами, а не заново."""
        from mvl.client import NetworkError

        self.breaks_with(NetworkError(
            "curl: (6) Could not resolve host: chap.heliosarchive.online"))
        _, missed = self.web._check_updates(["k"])

        self.assertIn("chap.heliosarchive.online", missed[0]["why"])
        self.assertIn("браузере", missed[0]["why"])

    def test_a_book_that_went_through_is_not_called_a_miss(self):
        """Работающее должно остаться работающим."""
        novel = SimpleNamespace(total_chapters=12, about="", genres=[],
                                tags=[], cover="", status="", language="")
        source = SimpleNamespace(key="mvlempyr", name="MVLEMPYR",
                                 find=lambda client, query: novel)
        was = self.web.sources.get
        self.web.sources.get = lambda key: source
        self.addCleanup(setattr, self.web.sources, "get", was)
        was_client = self.web.Client
        self.web.Client = lambda **kw: SimpleNamespace(close=lambda: None)
        self.addCleanup(setattr, self.web, "Client", was_client)

        checked, missed = self.web._check_updates(["k"])

        self.assertEqual((checked, missed), (["k"], []))
        self.assertEqual(library.get("k").chapters, 12)
