"""Общие части интерфейса: вставка, сообщения об ошибке, подсказки.

Тут проверяется не поведение в браузере — его проверяет человек, — а то,
что разметка и обработчики на месте. Именно эти мелочи и ломались молча:
кнопка без обработчика выглядит рабочей, а сообщение об ошибке в блоке
наверху страницы выглядит так, будто нажатие не сработало вовсе.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"


class UiBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")


class TestPaste(UiBase):
    """1.1: Ctrl+V должен работать, чем бы ни была раскладка."""

    def test_key_field_is_a_plain_textarea(self):
        """Поле с маской ввода или contenteditable вставку и ломает."""
        self.assertRegex(self.page, r'<textarea id="llmKey"')

    def test_nothing_forbids_pasting(self):
        self.assertNotIn("onpaste", self.page)
        self.assertNotIn("'paste'", self.tabs)

    def test_shortcut_is_recognised_by_the_key_not_by_the_letter(self):
        """На кириллице Ctrl+V — это Ctrl+М; спасает только `code`."""
        self.assertIn("e.code !== 'KeyV'", self.page)

    def test_latin_layout_is_left_to_the_browser(self):
        """Иначе текст вставится дважды."""
        self.assertIn("if(e.key === 'v' || e.key === 'V') return;", self.page)

    def test_there_is_a_button_that_does_not_depend_on_a_shortcut(self):
        self.assertIn('id="llmPaste"', self.page)
        self.assertIn("$('llmPaste').onclick", self.tabs)

    def test_paste_reports_the_change(self):
        """Без события input подписи и кнопки рядом не обновятся."""
        self.assertIn("new Event('input', {bubbles: true})", self.page)


class TestErrorPlacement(UiBase):
    """1.2: сообщение — под карточкой, где нажали кнопку."""

    def test_show_error_takes_the_place_to_put_it(self):
        self.assertIn("function showError(msg, near)", self.page)

    def test_message_goes_inside_the_card(self):
        self.assertIn("near.closest('.card')", self.page)

    def test_local_message_has_its_own_look(self):
        self.assertIn(".err.local{", self.page)

    def test_only_one_message_at_a_time(self):
        """Два сообщения на экране — и непонятно, какое про эту кнопку."""
        self.assertIn("if(ERR_SPOT){ ERR_SPOT.hidden = true;", self.page)

    def test_top_block_stays_for_the_cases_without_a_card(self):
        self.assertIn('id="error"', self.page)

    def test_key_buttons_say_where_they_failed(self):
        for button in ("llmCheck", "llmAdd", "llmSave", "llmEstimate"):
            with self.subTest(button=button):
                self.assertRegex(
                    self.tabs, r"showError\([^)]*\$\('" + button + r"'\)\)")


class TestCheckLog(UiBase):
    """1.1: журнал проверки ключа — рядом с кнопкой, а не в чужой карточке."""

    def test_log_block_lives_in_the_keys_card(self):
        """Журнал разбора спрятан внутри блока прогресса, а тот при
        проверке ключа ещё не показан — писать было бы некуда."""
        card = self.page.split('<label for="llmKey">', 1)[1]
        card = card.split('<div class="card"', 1)[0]
        self.assertIn('id="llmLogBox"', card)

    def test_draw_is_shared_with_the_job_log(self):
        """Двух рисовалок журнала быть не должно — разъедутся."""
        self.assertIn("function logDraw(box, lines)", self.tabs)
        self.assertIn("logDraw($('anLog'), lines)", self.tabs)

    def test_check_shows_what_the_server_answered(self):
        self.assertIn("llmLog(data.log)", self.tabs)

    def test_refusal_shows_the_log_too(self):
        """Как раз при отказе журнал и нужен."""
        self.assertIn("llmLog(err.log)", self.tabs)

    def test_log_travels_with_the_refusal(self):
        self.assertIn("err.log = data.log;", self.page)

    def test_each_check_starts_with_a_clean_log(self):
        self.assertRegex(self.tabs, r"\$\('llmLog'\)\.innerHTML = '';")


class TestNoSecondSourceOfTruth(UiBase):
    """1.1: одиночное поле ключа убрано, работа идёт по списку."""

    def test_key_is_not_read_from_the_old_setting(self):
        app = (ROOT / "webapp" / "app.py").read_text(encoding="utf-8")
        check = app.split("def api_llm_check", 1)[1].split("\n@app.", 1)[0]
        self.assertIn("keystore", check)

    def test_empty_list_says_so_in_words(self):
        app = (ROOT / "webapp" / "app.py").read_text(encoding="utf-8")
        self.assertIn("Ключей в списке нет", app)

    def test_client_gets_the_list_when_nothing_is_typed(self):
        app = (ROOT / "webapp" / "app.py").read_text(encoding="utf-8")
        maker = app.split("def _llm_client", 1)[1].split("\n@app.", 1)[0]
        self.assertIn("keys=None if typed else keystore", maker)


class TestRankHandsOverToTheDownloader(UiBase):
    """2.1: «скачать» в рейтинге настраивает качалку, а не качает сама."""

    def pick(self) -> str:
        return self.tabs.split("async function rkPick(row)", 1)[1] \
            .split("\n}\n", 1)[0]

    def test_the_rank_has_no_downloader_of_its_own(self):
        """Свой маленький загрузчик умел меньше и жил своей жизнью."""
        for gone in ("rkPlace", "rkStart", "rkBase", "rkFolder"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, self.page)
                self.assertNotIn(gone, self.tabs)

    def test_it_switches_to_the_downloader(self):
        self.assertIn("goTab('download')", self.pick())

    def test_switching_goes_through_the_tab_button(self):
        """Обработчик кнопки не только показывает вкладку, но и
        останавливает работу покидаемой — своей ветки быть не должно."""
        self.assertIn("button.click()", self.page)

    def test_the_source_becomes_fanqie(self):
        self.assertIn("srcMenu.set('fanqie', {notify: true})", self.pick())

    def test_the_hint_changes_with_the_source(self):
        """Без `notify` заполнитель поля остался бы от прошлого источника."""
        self.assertIn("if(options_.notify && onChange) onChange(value);",
                      self.tabs)

    def test_the_code_goes_into_the_query_field(self):
        self.assertIn("$('q').value = row.book_id", self.pick())

    def test_the_range_is_cleared(self):
        pick = self.pick()
        self.assertIn("$('first').value = '';", pick)
        self.assertIn("$('last').value = '';", pick)

    def test_the_range_is_cleared_before_the_search_not_after(self):
        """Поиск идёт секунды: до него поля успевают показать чужие числа."""
        pick = self.pick()
        self.assertLess(pick.index("$('first').value = '';"),
                        pick.index("await find(false)"))

    def test_the_search_does_not_refill_the_range(self):
        self.assertIn("if(fillRange) $('last').value = novel.total_chapters;",
                      self.page)

    def test_the_chosen_book_is_shown(self):
        self.assertIn('id="rkCard"', self.page)
        for part in ("rkCardCover", "rkCardName", "rkCardMeta"):
            with self.subTest(part=part):
                self.assertIn(f'id="{part}"', self.page)

    def test_the_card_says_what_the_rank_knows(self):
        card = self.tabs.split("function rkShowCard(row)", 1)[1]
        for field in ("readers", "words", "status", "place", "book_id"):
            with self.subTest(field=field):
                self.assertIn(field, card)

    def test_the_card_is_scrolled_to_and_highlighted(self):
        flash = self.tabs.split("function rkCardFlash()", 1)[1].split("\n}", 1)[0]
        self.assertIn("scrollIntoView", flash)
        self.assertIn("classList.add('flash')", flash)

    def test_the_highlight_restarts_on_every_pick(self):
        """Без чтения раскладки браузер снятие и возврат класса не заметит."""
        self.assertIn("void card.offsetWidth;", self.tabs)

    def test_the_card_goes_away_when_the_link_is_edited_by_hand(self):
        self.assertIn("$('rkCard').hidden = true;", self.page)


class TestRangeMessage(UiBase):
    """2.1: про неверный диапазон говорится у самих полей."""

    def test_there_is_a_place_for_it_next_to_the_fields(self):
        self.assertIn('id="rangeErr"', self.page)

    def test_the_check_happens_before_the_request(self):
        start = self.page.split("async function start()", 1)[1]
        start = start.split("await call('/api/start'", 1)[0]
        self.assertIn("rangeNote(", start)

    def test_the_message_names_both_numbers(self):
        self.assertIn("Конечная глава (${last}) меньше начальной (${first})",
                      self.page)

    def test_empty_fields_mean_the_whole_book(self):
        self.assertIn("Пустые поля — вся книга целиком.", self.page)

    def test_an_empty_range_is_not_an_error(self):
        """`last` пуст — берём всю книгу, а не ноль глав."""
        self.assertIn("last: Number($('last').value) || total,", self.page)

    def test_starting_without_a_book_is_not_a_crash(self):
        self.assertIn("if(!novel){", self.page)


class TestPreviewGatesTheButton(UiBase):
    """1.5: кнопка идёт за предпросмотром, а не за галочками."""

    def test_the_caption_counts_the_preview(self):
        self.assertIn("— в предпросмотре ${shown} из ${total}", self.tabs)

    def test_a_mismatch_is_shown_when_there_is_one(self):
        self.assertIn(", отмечено ${rnChosen.size}", self.tabs)

    def test_the_button_follows_the_preview(self):
        self.assertIn("$('rnApply').disabled = !data.rows.length;", self.tabs)

    def test_an_empty_preview_says_why(self):
        why = self.tabs.split("function rnWhyEmpty()", 1)[1].split("\n}", 1)[0]
        self.assertIn("не нашлось ни одного файла", why)
        self.assertIn("Сняты все галочки", why)
        self.assertIn("разбор имён", why)

    def test_a_broken_preview_says_so_at_the_button(self):
        self.assertIn("Предпросмотр не построился: ", self.tabs)


class TestChosenPaths(unittest.TestCase):
    """1.5: пустой список галочек и отсутствие списка — разные вещи."""

    @classmethod
    def setUpClass(cls):
        from webapp.app import app

        app.config["TESTING"] = True
        cls.app = app.test_client()

    def setUp(self):
        from tempfile import TemporaryDirectory

        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        for number in range(1, 6):
            (self.root / f"Глава {number}.txt").write_text(
                f"Текст {number}.\n", encoding="utf-8")
        # Файл, чьё имя не разбирается: он и есть тот самый «проверьте».
        (self.root / "аннотация.txt").write_text("Пара слов.\n",
                                                 encoding="utf-8")

    def plan(self, **extra):
        return self.app.post("/api/rename/plan",
                             json={"folder_in": str(self.root), **extra}).get_json()

    def paths(self):
        found = self.app.post("/api/rename/scan",
                              json={"folder_in": str(self.root)}).get_json()
        return [chapter["path"] for chapter in found["chapters"]]

    def test_no_list_at_all_means_all_of_them(self):
        self.assertEqual(len(self.plan()["rows"]), 6)

    def test_an_empty_list_means_none_of_them(self):
        """Иначе снятие всех галочек переименовывало всю папку."""
        self.assertEqual(self.plan(chosen=[])["rows"], [])

    def test_a_partial_list_means_exactly_those(self):
        rows = self.plan(chosen=self.paths()[:3])["rows"]
        self.assertEqual(len(rows), 3)

    def test_the_suspect_file_is_in_the_preview(self):
        """1.5: без него счётчики расходятся, а кнопка отказывается."""
        rows = self.plan(chosen=self.paths())["rows"]
        self.assertIn("аннотация.txt", [row["old_name"] for row in rows])

    def test_the_suspect_file_gets_a_number(self):
        found = self.app.post("/api/rename/scan",
                              json={"folder_in": str(self.root)}).get_json()
        suspect = [c for c in found["chapters"] if c["name"] == "аннотация.txt"]
        self.assertTrue(suspect)
        self.assertIsNotNone(suspect[0]["number"])

    def test_the_preview_matches_the_checkbox_count(self):
        paths = self.paths()
        self.assertEqual(len(self.plan(chosen=paths)["rows"]), len(paths))


class TestErrorFindsItsButton(UiBase):
    """1.2: якорь по нажатой кнопке — иначе сотню вызовов не обойти."""

    def test_the_pressed_button_is_remembered(self):
        self.assertIn("LAST_PRESS = {button, at: Date.now()}", self.page)

    def test_it_is_remembered_on_the_way_down(self):
        """Обработчик кнопки может убрать её со страницы — тогда всплытия
        уже не будет, и запоминать станет нечего."""
        self.assertIn("}, true);", self.page)

    def test_show_error_uses_it_when_nothing_is_passed(self):
        self.assertIn("errSpot(near || freshPress())", self.page)

    def test_a_stale_press_is_not_used(self):
        fresh = self.page.split("function freshPress()", 1)[1].split("\n}", 1)[0]
        self.assertIn("PRESS_MEMORY", fresh)

    def test_a_button_that_left_the_page_is_not_used(self):
        fresh = self.page.split("function freshPress()", 1)[1].split("\n}", 1)[0]
        self.assertIn("isConnected", fresh)

    def test_a_button_on_another_tab_is_not_used(self):
        fresh = self.page.split("function freshPress()", 1)[1].split("\n}", 1)[0]
        self.assertIn("section.hidden", fresh)

    def test_long_jobs_say_it_at_their_own_card(self):
        """Задача идёт минутами: к моменту отказа нажатие давно забыто."""
        for anchor in ("rnSummary", "spSummary", "mgSummary", "hdSummary",
                       "rpSummary", "sgProgress", "qStop", "ckStop"):
            with self.subTest(anchor=anchor):
                self.assertIn(f"showError(job.error, $('{anchor}'))", self.tabs)

    def test_no_job_reports_its_failure_to_the_top_of_the_page(self):
        self.assertNotIn("if(job.error) showError(job.error);", self.tabs)
        self.assertNotIn("if(job.error){ showError(job.error); return; }",
                         self.tabs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
