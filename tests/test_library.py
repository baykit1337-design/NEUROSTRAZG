"""Библиотека: одна запись на книгу, а не четыре списка одних и тех же.

Паспорт скачанной книги, история качалки, теги от модели и метки вроде
«потенциальная» — четыре разных списка одних и тех же книг. Порознь они
расходятся на второй неделе: там книгу докачали, тут переименовали, а в
третьем месте она осталась прежней.

Главная тонкость, ради которой всё это и написано: книгу находят на
одном сайте, а качают с другого. На Цидяне рейтинг работает, а
скачивания нет вовсе — книгу ищут на сайте-сливе и вставляют оттуда
адрес. Это одна книга. Разъедься она на две, метка осталась бы на той
половине, которую больше не открывают.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import library  # noqa: E402


class Base(unittest.TestCase):

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        was = library.LIBRARY_FILE
        library.LIBRARY_FILE = Path(self.dir.name) / "library.json"
        self.addCleanup(setattr, library, "LIBRARY_FILE", was)

    def qidian(self, **more):
        """Книга, найденная в рейтинге Цидяня."""
        fields = dict(found_site="qidian", found_id="1041604040",
                      name="异度旅社", cover="https://x/обложка.jpg")
        fields.update(more)
        return library.remember(**fields)


class TestOneBookStaysOneBook(Base):

    def test_a_rating_row_becomes_a_record(self):
        book = self.qidian()
        self.assertEqual(len(library.all_books()), 1)
        self.assertEqual(book.name, "异度旅社")

    def test_downloading_from_a_leak_site_does_not_make_a_second(self):
        """Тот самый случай: нашли на Цидяне, качали с ixdzs8."""
        book = self.qidian()
        library.remember(book.key, source="novelcms",
                         address="https://ixdzs8.com/read/566155/",
                         folder="/книги/异度旅社", chapters=402, last=402)
        self.assertEqual(len(library.all_books()), 1)

    def test_where_it_was_found_survives_the_move(self):
        """Иначе непонятно, откуда книга вообще взялась."""
        book = self.qidian()
        library.remember(book.key, source="novelcms", address="https://x/1/")
        again = library.get(book.key)
        self.assertEqual(again.found_site, "qidian")
        self.assertEqual(again.source, "novelcms")

    def test_a_pasted_address_gets_its_own_key(self):
        """Книга, которую нигде не находили, тоже должна лечь в запись."""
        book = library.remember(source="novelcms", address="https://x/1/",
                                name="Книга")
        self.assertTrue(book.key)
        self.assertEqual(library.get(book.key).name, "Книга")

    def test_two_sites_with_the_same_code_do_not_collide(self):
        """Коды у сайтов свои и независимые: у одного четыре цифры, у
        другого девятнадцать, но совпасть однажды могут."""
        one = library.remember(found_site="qidian", found_id="7", name="Одна")
        two = library.remember(found_site="fanqie", found_id="7", name="Другая")
        self.assertNotEqual(one.key, two.key)
        self.assertEqual(len(library.all_books()), 2)

    def test_a_book_without_anything_to_name_it_is_refused(self):
        with self.assertRaises(ValueError):
            library.remember(name="Безымянная")


class TestNobodyKnowsEverything(Base):
    """Дописываем, а не заменяем.

    Прогон знает про главы и папку, рейтинг — про обложку и перевод
    названия, метки не знает никто, кроме человека. Записывай мы
    целиком — каждый следующий прогон стирал бы то, что положил
    предыдущий.
    """

    def test_a_run_does_not_wipe_the_cover(self):
        book = self.qidian()
        library.remember(book.key, folder="/книги/тут", last=10, chapters=402)
        self.assertIn("обложка", library.get(book.key).cover)

    def test_a_rating_refresh_does_not_wipe_the_folder(self):
        book = self.qidian()
        library.remember(book.key, folder="/книги/тут", last=10)
        library.remember(book.key, cover="https://x/новая.jpg")
        self.assertEqual(library.get(book.key).folder, "/книги/тут")

    def test_marks_survive_everything(self):
        book = self.qidian()
        library.mark(book.key, "want")
        library.remember(book.key, folder="/книги/тут", last=10, chapters=402)
        self.assertIn("want", library.get(book.key).marks)

    def test_the_translated_name_survives_a_run(self):
        book = self.qidian(name_ru="Гостиница иного мира")
        library.remember(book.key, folder="/книги/тут", last=5)
        self.assertEqual(library.get(book.key).name_ru, "Гостиница иного мира")

    def test_what_is_told_anew_does_replace(self):
        book = self.qidian()
        library.remember(book.key, name_ru="Первый перевод")
        library.remember(book.key, name_ru="Второй перевод")
        self.assertEqual(library.get(book.key).name_ru, "Второй перевод")


class TestMarksThatProgramPutsItself(Base):
    """Считаются из записи и руками не двигаются.

    Хранимая метка «скачана» осталась бы на книге, у которой удалили
    папку, и врала бы тем увереннее, чем дольше лежит.
    """

    def test_a_book_never_downloaded_is_not_marked(self):
        book = self.qidian()
        self.assertNotIn("downloaded", book.auto)

    def test_a_downloaded_book_is_marked(self):
        book = self.qidian(folder="/книги/тут", last=402, chapters=402)
        self.assertIn("downloaded", book.auto)

    def test_new_chapters_are_seen(self):
        book = self.qidian(folder="/книги/тут", last=400, chapters=402)
        self.assertEqual(book.fresh, 2)
        self.assertIn("updatable", book.auto)

    def test_nothing_new_is_not_reported_as_new(self):
        book = self.qidian(folder="/книги/тут", last=402, chapters=402)
        self.assertEqual(book.fresh, 0)

    def test_a_book_not_downloaded_has_no_new_chapters(self):
        """У неначатой книги «новых глав» быть не может — они все новые."""
        book = self.qidian(chapters=402)
        self.assertEqual(book.fresh, 0)

    def test_the_count_is_not_kept_in_the_file(self):
        """Сохранённое «есть новые главы» через день соврало бы."""
        self.qidian(folder="/книги/тут", last=400, chapters=402)
        written = json.loads(library.LIBRARY_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("fresh", written[0])
        self.assertNotIn("auto", written[0])


class TestMarksThatThePersonPuts(Base):

    def test_a_mark_is_put_and_taken_off(self):
        book = self.qidian()
        library.mark(book.key, "want")
        self.assertIn("want", library.get(book.key).marks)
        library.mark(book.key, "want", on=False)
        self.assertNotIn("want", library.get(book.key).marks)

    def test_the_same_mark_twice_is_still_one(self):
        book = self.qidian()
        library.mark(book.key, "want")
        library.mark(book.key, "want")
        self.assertEqual(library.get(book.key).marks.count("want"), 1)

    def test_an_invented_mark_is_refused(self):
        """Свободные метки расходятся в написании, и одно и то же
        оказывается в трёх разных кучах."""
        book = self.qidian()
        with self.assertRaises(ValueError):
            library.mark(book.key, "потенц")

    def test_the_programs_own_marks_are_not_put_by_hand(self):
        book = self.qidian()
        with self.assertRaises(ValueError):
            library.mark(book.key, "downloaded")

    def test_marking_an_unknown_book_says_so(self):
        self.assertIsNone(library.mark("qidian:нет такой", "want"))


class TestWhatTheTabWillShow(Base):

    def test_the_summary_counts_what_matters(self):
        self.qidian(folder="/тут", last=400, chapters=402)
        library.remember(found_site="fanqie", found_id="9", name="Вторая")
        library.mark("fanqie:9", "want")

        said = library.state()
        self.assertEqual(said["books"], 2)
        self.assertEqual(said["downloaded"], 1)
        self.assertEqual(said["updatable"], 1)
        self.assertEqual(said["marks"]["want"], 1)

    def test_the_name_shown_is_the_translation_when_there_is_one(self):
        book = self.qidian(name_ru="Гостиница иного мира")
        self.assertEqual(book.title, "Гостиница иного мира")

    def test_without_a_translation_the_original_is_shown(self):
        self.assertEqual(self.qidian().title, "异度旅社")

    def test_the_freshest_comes_first(self):
        library.remember(found_site="fanqie", found_id="1", name="Первая",
                         last_run="2026-01-01 10:00")
        library.remember(found_site="fanqie", found_id="2", name="Вторая",
                         last_run="2026-08-25 10:00")
        self.assertEqual(library.all_books()[0].name, "Вторая")


class TestTheFileSurvivesTrouble(Base):

    def test_a_broken_file_does_not_stop_the_program(self):
        library.LIBRARY_FILE.write_text("не json вовсе", encoding="utf-8")
        self.assertEqual(library.all_books(), [])

    def test_a_broken_file_is_replaced_by_the_next_book(self):
        library.LIBRARY_FILE.write_text("{сломано", encoding="utf-8")
        self.qidian()
        self.assertEqual(len(library.all_books()), 1)

    def test_a_forgotten_book_is_gone(self):
        book = self.qidian()
        self.assertTrue(library.forget(book.key))
        self.assertEqual(library.all_books(), [])

    def test_forgetting_what_is_not_there_is_not_a_crash(self):
        self.assertFalse(library.forget("qidian:нет такой"))

    def test_reading_back_keeps_the_fields(self):
        book = self.qidian(folder="/тут", last=7, chapters=9,
                           tags=["культивация", "попаданец"])
        again = library.get(book.key)
        self.assertEqual(again.tags, ["культивация", "попаданец"])
        self.assertEqual(again.last, 7)


class TestThePassportInTheFolder(Base):
    """Через полгода папка `异度旅社` не говорит ни о чём.

    Ни откуда книга, ни докуда докачана, ни почему в ней дыра на седьмой
    главе. Программа это знает — но знает у себя, а папку человек
    открывает мимо неё: из проводника, на другой машине, через год.
    """

    def full(self, **more):
        fields = dict(
            name="异度旅社", name_ru="Гостиница иного мира", author="远瞳",
            source="novelcms", address="https://ixdzs8.com/read/566155/",
            folder=self.dir.name, chapters=402, last=400, skipped=3,
            last_run="24.08.2026 02:07")
        fields.update(more)
        return self.qidian(**fields)

    def test_the_passport_names_where_the_book_was_found(self):
        said = library.passport(self.full())
        self.assertIn("qidian", said)

    def test_and_where_it_was_actually_taken_from(self):
        """Главный вопрос через полгода: чем эту книгу докачивать."""
        said = library.passport(self.full())
        self.assertIn("ixdzs8.com/read/566155", said)

    def test_the_holes_are_named(self):
        """Дыра в книге иначе обнаруживается при чтении, глав через двести."""
        said = library.passport(self.full())
        self.assertIn("Пропущено: 3", said)

    def test_the_new_chapters_are_named(self):
        self.assertIn("новых глав: 2", library.passport(self.full()))

    def test_the_title_is_the_translated_one(self):
        self.assertIn("Гостиница иного мира", library.passport(self.full()))

    def test_the_original_name_is_not_lost(self):
        """По переводу книгу на сайте не найти."""
        self.assertIn("异度旅社", library.passport(self.full()))

    def test_it_warns_that_it_is_overwritten(self):
        """Иначе однажды в него впишут своё и потеряют при докачке."""
        self.assertIn("перезаписывается", library.passport(self.full()))

    def test_it_lands_in_the_folder(self):
        book = self.full()
        path = library.save_passport(book)
        self.assertTrue(Path(path).is_file())
        self.assertIn("异度旅社", Path(path).read_text(encoding="utf-8"))

    def test_a_missing_folder_is_not_a_failure(self):
        """Книга скачана, а паспорт — удобство: ронять прогон незачем."""
        book = self.full(folder="/нет/такой/папки")
        self.assertEqual(library.save_passport(book), "")

    def test_a_book_never_downloaded_writes_nothing_anywhere(self):
        """`Path("")` — это не «никуда», а текущая папка, и она есть
        всегда. Паспорт книги, которую ещё не качали, лёг бы рядом с
        самой программой."""
        here = set(Path.cwd().iterdir())
        self.assertEqual(library.save_passport(self.qidian()), "")
        self.assertEqual(set(Path.cwd().iterdir()), here)

    def test_a_bare_record_still_makes_a_passport(self):
        """Книга, которую только отметили и ещё не качали."""
        said = library.passport(self.qidian())
        self.assertIn("异度旅社", said)
        self.assertIn("Глав скачано: 0", said)


class TestTheRunLandsInTheLibrary(Base):
    """Качалка кончила прогон — книга должна оказаться в библиотеке сама.

    Заводить её руками человек не станет, а без записи не будет ни
    докачки, ни истории, ни меток.
    """

    def setUp(self):
        super().setUp()
        from mvl.api import Novel
        from webapp import app as web

        self.web = web
        self.Novel = Novel

    def novel(self, **more):
        fields = dict(code=566155, name="异度旅社", slug="566155",
                      total_chapters=402, author="远瞳")
        fields.update(more)
        return self.Novel(**fields)

    def with_state(self, done):
        """Папка книги с её `state.json` — как после настоящего прогона."""
        folder = Path(self.dir.name) / "книга"
        folder.mkdir(exist_ok=True)
        (folder / "state.json").write_text(json.dumps({
            "version": 1, "downloaded": {str(n): f"{n:04d}.txt" for n in done},
        }), encoding="utf-8")
        return folder

    def test_the_book_appears_after_a_run(self):
        folder = self.with_state(range(1, 11))
        self.web._remember_book(self.novel(), "novelcms", folder, {}, {})
        self.assertEqual(len(library.all_books()), 1)

    def test_how_far_it_got_comes_from_the_folder(self):
        """Не из отчёта прогона: книгу качают кусками и возвращаются к
        ней, и сложение отчётов дало бы неверный хвост."""
        folder = self.with_state([1, 2, 3, 400, 401])
        self.web._remember_book(self.novel(), "novelcms", folder, {}, {})
        self.assertEqual(library.all_books()[0].last, 401)

    def test_a_folder_without_a_run_gives_nothing(self):
        folder = Path(self.dir.name) / "пусто"
        folder.mkdir()
        self.web._remember_book(self.novel(), "novelcms", folder, {}, {})
        self.assertEqual(library.all_books()[0].last, 0)

    def test_where_it_was_found_is_kept(self):
        """Тот самый случай: нашли на Цидяне, качали с ixdzs8."""
        folder = self.with_state(range(1, 403))
        self.web._remember_book(
            self.novel(), "novelcms", folder,
            {"site": "qidian", "book_id": "1041604040",
             "link": "https://www.qidian.com/book/1041604040/"}, {})
        book = library.all_books()[0]
        self.assertEqual(book.found_site, "qidian")
        self.assertEqual(book.source, "novelcms")
        self.assertEqual(book.key, "qidian:1041604040")

    def test_the_same_book_twice_is_still_one(self):
        folder = self.with_state(range(1, 11))
        origin = {"site": "qidian", "book_id": "1041604040"}
        self.web._remember_book(self.novel(), "novelcms", folder, origin, {})
        self.web._remember_book(self.novel(), "novelcms", folder, origin, {})
        self.assertEqual(len(library.all_books()), 1)

    def test_the_passport_lands_next_to_the_chapters(self):
        folder = self.with_state(range(1, 11))
        self.web._remember_book(self.novel(), "novelcms", folder, {}, {})
        self.assertTrue((folder / library.PASSPORT).is_file())

    def test_a_broken_library_does_not_break_the_run(self):
        """Книга уже скачана. Ронять прогон из-за незаписанной заметки о
        нём — обмен сделанной работы на удобство."""
        library.LIBRARY_FILE = Path("/нет/такой/папки/library.json")
        folder = self.with_state(range(1, 11))
        self.web._remember_book(self.novel(), "novelcms", folder, {}, {})


class TestTheLibraryOverHttp(Base):

    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def test_an_empty_library_is_not_an_error(self):
        got = self.client.get("/api/library")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["books"], [])

    def test_the_books_come_with_their_summary(self):
        self.qidian(folder="/тут", last=400, chapters=402)
        said = self.client.get("/api/library").get_json()
        self.assertEqual(said["state"]["updatable"], 1)
        self.assertEqual(len(said["books"]), 1)

    def test_the_mark_names_come_from_the_server(self):
        """Держать закрытый список меток вторым экземпляром в разметке
        значило бы однажды разойтись: метка есть, а называть её нечем."""
        said = self.client.get("/api/library").get_json()
        self.assertTrue(any(m["key"] == "want" for m in said["marks"]))

    def test_a_mark_is_put_over_http(self):
        book = self.qidian()
        got = self.client.post("/api/library/mark",
                               json={"key": book.key, "mark": "want"})
        self.assertEqual(got.status_code, 200)
        self.assertIn("Потенциальная", got.get_json()["book"]["mark_names"])

    def test_an_invented_mark_is_refused(self):
        book = self.qidian()
        got = self.client.post("/api/library/mark",
                               json={"key": book.key, "mark": "потенц"})
        self.assertEqual(got.status_code, 400)

    def test_marking_an_unknown_book_says_so(self):
        got = self.client.post("/api/library/mark",
                               json={"key": "нет:такой", "mark": "want"})
        self.assertEqual(got.status_code, 404)

    def test_a_note_is_written_and_erased(self):
        book = self.qidian()
        self.client.post("/api/library/note",
                         json={"key": book.key, "note": "дочитать до 200"})
        self.assertEqual(library.get(book.key).note, "дочитать до 200")

        self.client.post("/api/library/note", json={"key": book.key, "note": ""})
        self.assertEqual(library.get(book.key).note, "")

    def test_a_book_is_forgotten(self):
        book = self.qidian()
        got = self.client.post("/api/library/forget", json={"key": book.key})
        self.assertTrue(got.get_json()["gone"])
        self.assertEqual(library.all_books(), [])

    def test_the_passport_can_be_rewritten_on_demand(self):
        book = self.qidian(folder=self.dir.name, last=5, chapters=9)
        got = self.client.post("/api/library/passport", json={"key": book.key})
        self.assertEqual(got.status_code, 200)
        self.assertTrue(Path(got.get_json()["path"]).is_file())

    def test_a_passport_without_a_folder_says_why(self):
        book = self.qidian()
        got = self.client.post("/api/library/passport", json={"key": book.key})
        self.assertEqual(got.status_code, 400)
        self.assertIn("апк", got.get_json()["error"])


class TestAskingTheSiteForNewChapters(Base):
    """Без переспроса «есть новые главы» не появилось бы никогда.

    Число глав записывает прогон — а прогон и есть то, ради чего мы про
    новые главы спрашиваем.
    """

    def setUp(self):
        super().setUp()
        from mvl.api import Novel
        from webapp import app as web

        self.web = web
        self.was = web.sources.get
        self.addCleanup(setattr, web.sources, "get", self.was)
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

        asked = self.asked = []

        class Site:
            key = "novelcms"
            name = "Сайт-слив"
            needs_proxy = False

            def find(self, client, query):
                asked.append(query)
                return Novel(code=1, name="异度旅社", slug=query,
                             total_chapters=410)

        web.sources.get = lambda key: Site()

    def book(self, **more):
        fields = dict(source="novelcms",
                      address="https://ixdzs8.com/read/566155/",
                      folder="/тут", chapters=402, last=402)
        fields.update(more)
        return self.qidian(**fields)

    def test_the_count_is_refreshed(self):
        book = self.book()
        self.client.post("/api/library/check", json={"key": book.key})
        self.assertEqual(library.get(book.key).chapters, 410)

    def test_and_the_new_chapters_show_up(self):
        book = self.book()
        self.client.post("/api/library/check", json={"key": book.key})
        self.assertEqual(library.get(book.key).fresh, 8)

    def test_the_site_is_asked_by_what_we_downloaded_with(self):
        """У книги с Цидяня спрашивать надо не Цидянь."""
        book = self.book()
        self.client.post("/api/library/check", json={"key": book.key})
        self.assertEqual(self.asked, ["https://ixdzs8.com/read/566155/"])

    def test_a_book_with_no_source_is_not_asked_about(self):
        book = self.qidian()
        said = self.client.post("/api/library/check",
                                json={"key": book.key}).get_json()
        self.assertEqual(self.asked, [])
        self.assertEqual(len(said["missed"]), 1)

    def test_a_silent_site_does_not_break_the_rest(self):
        from mvl.client import NetworkError

        good = self.book()
        bad = library.remember(found_site="fanqie", found_id="9",
                               source="novelcms", address="https://х/нет/",
                               folder="/там", chapters=10, last=10)

        asked = self.asked
        was = self.web.sources.get

        class Moody:
            key = "novelcms"
            name = "Сайт-слив"
            needs_proxy = False

            def find(self, client, query):
                asked.append(query)
                if "нет" in query:
                    raise NetworkError("сайт молчит")
                return was(self.key).find(client, query)

        self.web.sources.get = lambda key: Moody()
        said = self.client.post("/api/library/check",
                                json={"keys": [bad.key, good.key]}).get_json()
        self.assertIn(good.key, said["checked"])
        self.assertEqual(len(said["missed"]), 1)

    def test_too_many_books_are_split_over_several_presses(self):
        """Проверить сотню разом — держать кнопку нажатой полчаса и
        получить в конце «сайт устал»."""
        keys = []
        for n in range(self.web.CHECK_AT_ONCE + 3):
            keys.append(library.remember(
                found_site="fanqie", found_id=str(n), source="novelcms",
                address=f"https://x/{n}/", folder="/тут", chapters=1,
                last=1).key)
        said = self.client.post("/api/library/check",
                                json={"keys": keys}).get_json()
        self.assertEqual(len(said["checked"]), self.web.CHECK_AT_ONCE)
        self.assertEqual(said["left"], 3)


if __name__ == "__main__":
    unittest.main()
