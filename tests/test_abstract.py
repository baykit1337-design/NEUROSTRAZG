"""Оригинал, перевод и переключатель описания (3.1 ТЗ NEUROSTRAZH).

Название на китайском ничего не говорит, один перевод ничего не находит:
по нему книгу не отыскать ни на сайте, ни в поиске. Поэтому видно оба.

Описание — другое дело: их полсотни на срез, а читают из них два-три.
Переводится оно по кнопке и по одной книге, а переведённое помнится по
коду книги — второй раз кнопка не понадобится.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import books, titles  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"

CHINESE = "少年踏上修行之路，一路向北。"
RUSSIAN = "Юноша встаёт на путь совершенствования и идёт на север."


class FakeLlm:
    """Модель, которая всегда отвечает одним и тем же."""

    def __init__(self, answer=RUSSIAN):
        self.answer = answer
        self.calls = 0

    def generate(self, prompt, json_only=True, model="", schema=None):
        self.calls += 1
        self.last = prompt
        return self.answer

    def close(self):
        pass


class AbstractBase(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        saved = titles.ABSTRACTS_FILE
        titles.ABSTRACTS_FILE = Path(self._dir.name) / "abstracts.json"
        self.addCleanup(setattr, titles, "ABSTRACTS_FILE", saved)


class TestAbstractCache(AbstractBase):
    def test_nothing_is_known_at_the_start(self):
        self.assertEqual(titles.abstracts(), {})
        self.assertEqual(titles.abstract_of("123"), "")

    def test_a_translation_is_remembered(self):
        client = FakeLlm()
        got = titles.translate_abstract("123", CHINESE, client)

        self.assertEqual(got, RUSSIAN)
        self.assertEqual(titles.abstract_of("123"), RUSSIAN)

    def test_the_original_goes_to_the_model(self):
        client = FakeLlm()
        titles.translate_abstract("123", CHINESE, client)
        self.assertIn(CHINESE, client.last)

    def test_a_known_translation_is_not_asked_again(self):
        client = FakeLlm()
        titles.translate_abstract("123", CHINESE, client)
        titles.translate_abstract("123", CHINESE, client)
        self.assertEqual(client.calls, 1)

    def test_force_asks_again(self):
        titles.translate_abstract("123", CHINESE, FakeLlm("Первый"))
        again = titles.translate_abstract("123", CHINESE, FakeLlm("Второй"),
                                          force=True)
        self.assertEqual(again, "Второй")
        self.assertEqual(titles.abstract_of("123"), "Второй")

    def test_the_code_is_a_string_even_when_it_came_as_a_number(self):
        """Код книги в девятнадцать разрядов числом не ездит (1.2 ТЗ)."""
        titles.remember_abstract(7143038691944959011, RUSSIAN)
        self.assertEqual(titles.abstract_of("7143038691944959011"), RUSSIAN)

    def test_nothing_to_translate(self):
        with self.assertRaises(ValueError):
            titles.translate_abstract("123", "   ", FakeLlm())

    def test_an_empty_answer_is_not_remembered(self):
        with self.assertRaises(ValueError):
            titles.translate_abstract("123", CHINESE, FakeLlm("   "))
        self.assertEqual(titles.abstract_of("123"), "")

    def test_forgetting_clears_only_the_abstracts(self):
        titles.remember_abstract("123", RUSSIAN)
        titles.forget_abstracts()
        self.assertEqual(titles.abstracts(), {})

    def test_titles_and_abstracts_live_in_different_files(self):
        """Иначе перевод названия затирал бы перевод описания."""
        self.assertNotEqual(titles.TITLES_FILE, titles.ABSTRACTS_FILE)

    def test_a_broken_file_does_not_break_the_page(self):
        titles.ABSTRACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        titles.ABSTRACTS_FILE.write_text("{не json", encoding="utf-8")
        self.assertEqual(titles.abstracts(), {})


class TestAbstractRoutes(AbstractBase):
    @classmethod
    def setUpClass(cls):
        from webapp.app import app

        app.config["TESTING"] = True
        cls.app = app.test_client()

    def setUp(self):
        super().setUp()
        self._books = TemporaryDirectory()
        self.addCleanup(self._books.cleanup)
        saved = books.BOOK_DIR
        books.BOOK_DIR = Path(self._books.name)
        self.addCleanup(setattr, books, "BOOK_DIR", saved)

    def test_the_card_carries_the_translation_it_already_has(self):
        """Переключатель должен сразу знать, есть ли что показывать."""
        books.save("123", {"name": "书", "abstract": CHINESE, "book_id": "123"})
        titles.remember_abstract("123", RUSSIAN)

        body = self.app.get("/api/rank/book/123").get_json()
        self.assertEqual(body["abstract_ru"], RUSSIAN)
        self.assertEqual(body["abstract"], CHINESE)

    def test_no_translation_yet_is_an_empty_string_not_a_missing_key(self):
        books.save("123", {"name": "书", "abstract": CHINESE, "book_id": "123"})
        body = self.app.get("/api/rank/book/123").get_json()
        self.assertEqual(body["abstract_ru"], "")

    def test_a_bad_code_is_refused(self):
        res = self.app.post("/api/rank/abstract", json={"book_id": "../etc"})
        self.assertEqual(res.status_code, 400)

    def test_nothing_to_translate_is_refused(self):
        """Описания нет ни в запросе, ни в кэше карточки."""
        res = self.app.post("/api/rank/abstract", json={"book_id": "123"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("нечего", res.get_json()["error"])


class TestOneButtonForEverything(AbstractBase):
    """Пункт 13: одной кнопкой и названия, и описания.

    Раньше описания переводились строго по одному, по кнопке в раскрытой
    строке. Возражение было про цену — запрос на каждое описание, — и
    пачками оно снимается: полсотни описаний стоят девяти запросов.
    """

    @classmethod
    def setUpClass(cls):
        from webapp.app import app

        app.config["TESTING"] = True
        cls.app = app.test_client()

    def setUp(self):
        super().setUp()
        from net.sources import rank as rank_net
        from ops import rank as rank_op
        from webapp import app as web

        self.rank_net = rank_net

        self._data = TemporaryDirectory()
        self.addCleanup(self._data.cleanup)
        kept = rank_op.RANK_DIR
        rank_op.RANK_DIR = Path(self._data.name)
        self.addCleanup(setattr, rank_op, "RANK_DIR", kept)
        self.rank_op = rank_op

        held = titles.TITLES_FILE
        titles.TITLES_FILE = Path(self._data.name) / "titles.json"
        self.addCleanup(setattr, titles, "TITLES_FILE", held)

        self._books = TemporaryDirectory()
        self.addCleanup(self._books.cleanup)
        saved = books.BOOK_DIR
        books.BOOK_DIR = Path(self._books.name)
        self.addCleanup(setattr, books, "BOOK_DIR", saved)

        # Модель подменяем целиком: ключей в тестах нет, а спрашивать
        # надо именно то, что маршрут ей отдаёт.
        self.llm = FakeLlm('{"1": "перевод"}')
        was = web._llm_client
        web._llm_client = lambda *a, **kw: self.llm
        self.addCleanup(setattr, web, "_llm_client", was)
        self.web = web

    def snapshot(self, rows, day="2026-01-01"):
        """Срез той доски, которую маршрут и станет искать.

        Сохранить его под `all` мало: у Фанкью доска складывается из пола
        и вида, и по умолчанию маршрут смотрит именно туда.
        """
        from net.sources import categories as rank_cats

        board = rank_cats.board_key(rank_cats.MALE, rank_cats.READING)
        self.rank_op.save(rows, board=board, day=day)
        return day

    def row(self, book_id, about=""):
        return self.rank_net.RankRow(place=1, book_id=book_id,
                                     name=f"книга {book_id}", about=about)

    def test_descriptions_are_translated_along_with_the_titles(self):
        self.snapshot([self.row("1", about=CHINESE)])
        said = self.app.post("/api/rank/translate",
                             json={"abstracts": True}).get_json()
        self.assertIn("abouts", said)
        self.assertEqual(said["abouts"]["abstracts"]["1"], "перевод")

    def test_without_asking_the_descriptions_are_left_alone(self):
        """Кнопка «перевести всё» — не единственный путь сюда: за
        названиями ходят и мимо неё."""
        self.snapshot([self.row("1", about=CHINESE)])
        said = self.app.post("/api/rank/translate", json={}).get_json()
        self.assertNotIn("abouts", said)

    def test_the_qidian_description_comes_from_the_row_itself(self):
        """Цидянь печатает описание прямо в строке доски — ходить за ним
        на сайт второй раз незачем."""
        self.snapshot([self.row("1", about=CHINESE)])
        self.app.post("/api/rank/translate", json={"abstracts": True})
        self.assertIn(CHINESE, self.llm.last)

    def test_for_other_sites_it_comes_from_the_opened_card(self):
        books.save("1", {"name": "书", "abstract": CHINESE, "book_id": "1"})
        self.snapshot([self.row("1")])
        self.app.post("/api/rank/translate", json={"abstracts": True})
        self.assertIn(CHINESE, self.llm.last)

    def test_a_book_whose_card_has_no_description_is_counted(self):
        """«Переведено 1 из 80» без этого числа читалось бы поломкой.

        Карточку забирали, описания в ней нет — это ответ сайта, и
        делать дальше нечего.
        """
        books.save("2", {"name": "书", "abstract": "", "book_id": "2"})
        self.snapshot([self.row("1", about=CHINESE), self.row("2")])
        said = self.app.post("/api/rank/translate",
                             json={"abstracts": True}).get_json()
        self.assertEqual(said["abouts"]["absent"], 1)
        self.assertEqual(said["abouts"]["unknown"], 0)

    def test_a_book_whose_card_was_never_fetched_is_told_apart(self):
        """Раньше такие книги считались как «без описания на сайте», и
        кнопка молча пропускала половину среза. Описание у них может
        быть — мы за ним просто не ходили, и это наше, а не ответ сайта.
        """
        self.snapshot([self.row("1", about=CHINESE), self.row("2")])
        said = self.app.post("/api/rank/translate",
                             json={"abstracts": True}).get_json()
        self.assertEqual(said["abouts"]["unknown"], 1)
        self.assertEqual(said["abouts"]["absent"], 0)

    def test_the_counts_of_titles_and_descriptions_stay_apart(self):
        """Складывать их в одно число значило бы прятать цену: названия
        и описания стоят разного числа запросов."""
        self.snapshot([self.row("1", about=CHINESE)])
        said = self.app.post("/api/rank/translate",
                             json={"abstracts": True}).get_json()
        self.assertIn("translated", said)
        self.assertIn("translated", said["abouts"])

    def test_nothing_to_translate_is_not_an_error(self):
        self.snapshot([self.row("1")])
        res = self.app.post("/api/rank/translate", json={"abstracts": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["abouts"]["translated"], 0)


class TestTitlesUi(unittest.TestCase):
    """Что показано в браузере."""

    @classmethod
    def setUpClass(cls):
        cls.page = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_the_found_book_shows_both_titles(self):
        self.assertIn("`${novel.name} / ${novel.translated}`", self.page)

    def test_the_expanded_card_shows_both_titles(self):
        self.assertIn("title.textContent = rkBothTitles({", self.tabs)

    def test_the_switch_state_survives_the_list_being_rebuilt(self):
        """Хранить выбор в самой карточке нельзя: она пересобирается."""
        self.assertIn("const rkLang = {};", self.tabs)
        self.assertIn("rkLang[row.book_id] = 'ru'", self.tabs)
        self.assertIn("rkLang[row.book_id] = 'zh'", self.tabs)

    def test_both_sides_of_the_switch_are_there(self):
        self.assertIn("orig.textContent = '原';", self.tabs)
        self.assertIn("ru_.textContent = 'RU';", self.tabs)

    def test_the_ru_side_is_hidden_until_there_is_a_translation(self):
        self.assertIn("ru_.hidden = !done;", self.tabs)

    def test_there_is_a_button_that_orders_the_translation(self):
        self.assertIn("ask.textContent = 'перевести';", self.tabs)
        self.assertIn("'/api/rank/abstract'", self.tabs)

    def test_the_button_goes_away_once_the_translation_is_there(self):
        self.assertIn("ask.hidden = !!done;", self.tabs)

    def test_a_freshly_ordered_translation_is_shown_at_once(self):
        """Иначе после «перевести» пришлось бы нажимать ещё и «RU»."""
        self.assertIn("rkLang[row.book_id] = 'ru';\n      show();", self.tabs)

    def test_the_switch_does_not_collapse_the_row(self):
        """Клик по строке раскрывает и закрывает её — кнопкам это мешает."""
        self.assertIn("orig.onclick = e => { e.stopPropagation();", self.tabs)
        self.assertIn("ru_.onclick = e => { e.stopPropagation();", self.tabs)

    def test_an_empty_description_still_says_why(self):
        self.assertIn("RK_SECRET_ABOUT", self.tabs)
        self.assertIn("RK_NO_ABOUT", self.tabs)


class TestFetchingTheMissingDescriptions(TestOneButtonForEverything):
    """«Перевести всё» сначала забирает описания, которых ещё нет.

    Раньше кнопка переводила только те книги, чью карточку уже забирали
    с сайта, и молча пропускала половину среза. Ходить за полусотней
    страниц внутри перевода нельзя — это минута с виду зависшей кнопки,
    поэтому прогон вынесен в задачу.
    """

    def setUp(self):
        super().setUp()
        self.asked = []
        self.broken = set()

        def card(client, site, book_id, slug=""):
            self.asked.append(book_id)
            if book_id in self.broken:
                from net.sources.base import SourceBroken

                raise SourceBroken(f"книги {book_id} больше нет")
            return books.save(book_id, {"name": f"книга {book_id}",
                                        "abstract": CHINESE})

        kept = self.web._fetch_card
        self.web._fetch_card = card
        self.addCleanup(setattr, self.web, "_fetch_card", kept)

        held = self.web._rank_client
        self.web._rank_client = lambda *a, **kw: FakeLlm()
        self.addCleanup(setattr, self.web, "_rank_client", held)

    def run_job(self, payload=None):
        from webapp.app import JOBS

        said = self.app.post("/api/rank/abouts/start",
                             json=payload or {}).get_json()
        job = JOBS[said["job"]["id"]]
        job.thread.join(timeout=30)
        return job

    def test_it_fetches_the_books_that_have_no_description(self):
        self.snapshot([self.row("1"), self.row("2")])
        job = self.run_job()

        self.assertEqual(sorted(self.asked), ["1", "2"])
        self.assertEqual(job.report["got"], 2)

    def test_what_it_fetched_becomes_translatable(self):
        """Ради этого прогон и затевается: после него кнопка переводит
        то, что раньше пропускала."""
        self.snapshot([self.row("1")])
        self.run_job()

        said = self.app.post("/api/rank/translate",
                             json={"abstracts": True}).get_json()
        self.assertEqual(said["abouts"]["abstracts"]["1"], "перевод")
        self.assertEqual(said["abouts"]["unknown"], 0)

    def test_a_book_already_in_the_cache_is_not_asked_again(self):
        books.save("1", {"name": "книга 1", "abstract": CHINESE})
        self.snapshot([self.row("1"), self.row("2")])
        self.run_job()

        self.assertEqual(self.asked, ["2"])

    def test_a_description_printed_in_the_row_needs_no_trip(self):
        """Цидянь печатает описание прямо в строке доски."""
        self.snapshot([self.row("1", about=CHINESE), self.row("2")])
        self.run_job()

        self.assertEqual(self.asked, ["2"])

    def test_one_closed_book_does_not_stop_the_rest(self):
        """Книгу могли убрать с сайта после того, как срез был снят."""
        self.broken = {"1"}
        self.snapshot([self.row("1"), self.row("2"), self.row("3")])
        job = self.run_job()

        self.assertEqual(job.report["got"], 2)
        self.assertEqual(job.report["missed"], 1)
        self.assertIsNone(job.error)

    def test_stopping_really_stops_and_keeps_what_was_fetched(self):
        """«Остановить» должно останавливать: прогон на полсотни книг
        иначе не бросить."""
        import threading

        stop, ready = [], threading.Event()

        def card(client, site, book_id, slug=""):
            # Ждём, пока тест отдаст нам саму задачу: поток стартует
            # раньше, чем запрос успевает вернуть её номер.
            ready.wait(10)
            self.asked.append(book_id)
            # Первая книга приезжает, после неё жмём «Остановить».
            stop[0].cancel.set()
            return books.save(book_id, {"name": "книга", "abstract": CHINESE})

        self.web._fetch_card = card
        self.snapshot([self.row(str(n)) for n in range(1, 6)])

        from webapp.app import JOBS

        said = self.app.post("/api/rank/abouts/start", json={}).get_json()
        job = JOBS[said["job"]["id"]]
        stop.append(job)
        ready.set()
        job.thread.join(timeout=30)

        self.assertIsNone(job.error)
        # Остановились на первой, а не прошли все пять.
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(job.report["got"], 1)

    def test_nothing_to_fetch_is_said_plainly(self):
        """«Забрано описаний: 0» читалось бы как поломка."""
        books.save("1", {"name": "книга 1", "abstract": CHINESE})
        self.snapshot([self.row("1")])
        job = self.run_job()

        self.assertEqual(self.asked, [])
        self.assertIn("уже", job.progress["message"])

    def test_without_a_snapshot_it_says_so(self):
        answer = self.app.post("/api/rank/abouts/start", json={})
        self.assertEqual(answer.status_code, 400)


class TestTheOpenedRowRemembersTheCard(AbstractBase):
    """Раскрытая строка должна оставлять описание в кэше.

    У Фанкью карточка сохранялась, а у остальных сайтов — нет: их ветка
    отдавала ответ прямо со страницы, мимо кэша. Из-за этого «Перевести
    всё» не видело их описаний никогда, сколько строк ни раскрывай.
    """

    @classmethod
    def setUpClass(cls):
        from webapp.app import app

        app.config["TESTING"] = True
        cls.app = app.test_client()

    def setUp(self):
        super().setUp()
        from webapp import app as web

        self._books = TemporaryDirectory()
        self.addCleanup(self._books.cleanup)
        saved = books.BOOK_DIR
        books.BOOK_DIR = Path(self._books.name)
        self.addCleanup(setattr, books, "BOOK_DIR", saved)

        self.web = web
        held = web._rank_client
        web._rank_client = lambda *a, **kw: FakeLlm()
        self.addCleanup(setattr, web, "_rank_client", held)

        # Подменяем читателя подробностей у одного сайта — на сеть не идём.
        self.site = "mvlempyr"
        kept = web.RANK_SITES[self.site].get("book")
        # Подпись та же, что у настоящих читателей: разойдись она, и
        # подмена перестала бы проверять то, что вызывается на самом деле.
        web.RANK_SITES[self.site]["book"] = \
            lambda client, code, slug="", section="": {
                "name": "книга", "abstract": CHINESE, "author": "кто-то"}
        self.addCleanup(lambda: web.RANK_SITES[self.site].__setitem__("book",
                                                                     kept))

    def test_the_card_lands_in_the_cache(self):
        self.app.get(f"/api/rank/book/777?site={self.site}")
        saved = books.load("777")

        self.assertIsNotNone(saved)
        self.assertEqual(saved["abstract"], CHINESE)

    def test_the_answer_carries_the_translation_it_already_has(self):
        """Переключатель «原/RU» должен сразу знать, есть ли что
        показывать по второй кнопке."""
        titles.remember_abstract("777", RUSSIAN)
        body = self.app.get(f"/api/rank/book/777?site={self.site}").get_json()
        self.assertEqual(body["abstract_ru"], RUSSIAN)


if __name__ == "__main__":
    unittest.main()
