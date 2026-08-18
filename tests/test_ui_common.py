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


class TestFoundBookHasACoverToo(UiBase):
    """Из рейтинга обложка приходила, а по вставленному коду — нет.

    Одна и та же книга выглядела по-разному в зависимости от того, как её
    открыли: карточкой с картинкой или голой строкой текста.
    """

    def cover(self):
        return self.page.split("function showCover(novel)", 1)[1].split(
            "\n}", 1)[0]

    def test_the_card_has_a_place_for_it(self):
        card = self.page.split('id="book" hidden', 1)[1].split("</div>\n  </div>",
                                                               1)[0]
        self.assertIn('id="bookCover"', card)

    def test_it_looks_the_same_as_in_the_rank(self):
        """Та же раскладка и тот же размер — иначе это две разные вещи."""
        card = self.page.split('id="book" hidden', 1)[1].split("<!-- 2.1", 1)[0]
        self.assertIn('class="picked-row"', card)

    def test_the_picture_goes_through_our_own_cache(self):
        """Адрес у сайта подписан и протухает, а книгу открывают и через месяц."""
        self.assertIn("/api/rank/cover/", self.cover())

    def test_the_address_is_passed_only_when_the_source_gave_one(self):
        """Без него сервер отдаёт то, что уже в кэше, — это не пустой ответ."""
        self.assertIn("novel.cover ?", self.cover())

    def test_a_picture_that_did_not_load_is_hidden(self):
        """Пустая рамка на месте обложки хуже её отсутствия."""
        self.assertIn("onerror", self.cover())
        self.assertIn("hidden = true", self.cover())

    def test_the_search_asks_for_it(self):
        self.assertIn("showCover(novel);", self.page)

    def test_a_failed_search_takes_the_cover_away(self):
        """Иначе от прошлой книги остаётся одна картинка без имени."""
        find = self.page.split("async function find(fillRange = true){", 1)[1]
        fail = find.split("}catch(err){", 1)[1].split("}finally{", 1)[0]
        self.assertIn("$('bookCover').hidden = true;", fail)


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


class TestTooltipLayer(UiBase):
    """1.4: подсказка не должна упираться в границу карточки."""

    def show(self) -> str:
        return self.page.split("function tipShow(anchor, text)", 1)[1] \
            .split("\n}", 1)[0]

    def test_the_layer_lives_in_the_body(self):
        self.assertIn("document.body.append(TIP_LAYER)", self.page)

    def test_it_is_positioned_by_the_screen_not_by_the_card(self):
        self.assertIn("position:fixed;left:0;top:0;", self.page)

    def test_coordinates_come_from_the_element_it_belongs_to(self):
        self.assertIn("anchor.getBoundingClientRect()", self.show())

    def test_it_flips_down_when_there_is_no_room_above(self):
        self.assertIn("if(top < TIP_EDGE) top = box.bottom + TIP_GAP;",
                      self.show())

    def test_it_slides_left_when_there_is_no_room_right(self):
        self.assertIn("window.innerWidth - size.width - TIP_EDGE", self.show())

    def test_it_never_goes_off_the_left_edge_either(self):
        self.assertIn("Math.max(left, TIP_EDGE)", self.show())

    def test_hovering_is_caught_on_the_whole_document(self):
        """Половина подсказок висит на строках, которых при загрузке нет."""
        self.assertIn("e.target.closest('[data-tip]')", self.page)

    def test_scrolling_takes_the_tooltip_away(self):
        """Элемент уехал — подсказка висела бы в пустоте."""
        self.assertIn("window.addEventListener('scroll', tipHide, true)",
                      self.page)

    def test_there_is_only_one_copy_of_this_code(self):
        """Раньше их было три, и расходились они молча."""
        self.assertNotIn("tip.classList.add('visible')", self.tabs)
        self.assertEqual(self.tabs.count("function attachTip"), 1)

    def test_attach_tip_only_puts_the_text_in_the_attribute(self):
        attach = self.tabs.split("function attachTip(element, text)", 1)[1]
        attach = attach.split("\n}", 1)[0]
        self.assertIn("icon.dataset.tip = text;", attach)
        self.assertNotIn("addEventListener", attach)

    def test_the_suspect_tag_itself_is_the_trigger(self):
        """Целиться мышью в значок «?» внутри пометки — упражнение."""
        self.assertIn("tag.dataset.tip = chapter.suspect_reason;", self.tabs)

    def test_static_tooltips_still_have_their_text(self):
        self.assertIn('data-tip="', self.page)


class TestCopyMenu(UiBase):
    """2.2: из рейтинга нельзя было забрать даже ссылку."""

    def menu(self) -> str:
        return self.tabs.split("function rkCopyMenu(row)", 1)[1] \
            .split("\n}\n", 1)[0]

    def test_every_row_has_the_button(self):
        self.assertIn("tr.append(rkCopyMenu(row))", self.tabs)

    def test_the_menu_has_both_items(self):
        menu = self.menu()
        self.assertIn("'ссылку'", menu)
        self.assertIn("'id'", menu)

    def test_the_link_is_built_from_the_code(self):
        self.assertIn("https://fanqienovel.com/page/", self.tabs)
        self.assertIn("RK_LINK + row.book_id", self.menu())

    def test_copying_says_so(self):
        self.assertIn("toast(await copyText(text) ? said", self.tabs)

    def test_a_failure_says_so_too(self):
        self.assertIn("'Скопировать не вышло'", self.tabs)

    def test_the_menu_does_not_live_inside_the_scrolling_list(self):
        """У списков overflow:auto — край строки обрезал бы меню."""
        self.assertIn("document.body.append(menu)", self.page)
        self.assertIn(".dropdown-menu.floating{", self.page)
        self.assertIn("position:fixed;left:0;top:0;right:auto;", self.page)

    def test_the_menu_flips_up_when_there_is_no_room_below(self):
        opener = self.page.split("function openMenu(button, items)", 1)[1]
        self.assertIn("top = box.top - size.height - 4;", opener)

    def test_the_menu_stays_on_screen_horizontally(self):
        opener = self.page.split("function openMenu(button, items)", 1)[1]
        self.assertIn("window.innerWidth - size.width - TIP_EDGE", opener)

    def test_only_one_menu_at_a_time(self):
        self.assertIn("function openMenu(button, items){\n  closeMenu();",
                      self.page)

    def test_clicking_away_closes_it(self):
        self.assertIn("document.addEventListener('click', closeMenu);",
                      self.page)

    def test_scrolling_closes_it(self):
        """Кнопка уехала — меню висело бы над пустотой."""
        self.assertIn("window.addEventListener('scroll', closeMenu, true)",
                      self.page)

    def test_escape_closes_it(self):
        self.assertIn("if(e.key === 'Escape') closeMenu();", self.page)

    def test_copying_has_one_way_of_doing_it(self):
        """127.0.0.1 браузер защищённым не считает — запасной путь нужен."""
        self.assertEqual(self.tabs.count("async function copyText(text)"), 1)
        self.assertIn("document.execCommand('copy')", self.tabs)
        self.assertIn("await copyText(text)", self.tabs)


class TestThreadsButton(UiBase):
    """Часть 6: замер многопоточности рядом с настройками потоков."""

    def test_the_button_exists_and_is_wired(self):
        self.assertIn('id="thCheck"', self.page)
        self.assertIn("$('thCheck').onclick = thCheck;", self.page)

    def test_it_stands_next_to_the_thread_settings(self):
        block = self.page.split('id="dlThreads"', 1)[1]
        block = block.split('<!-- 4. Прогресс', 1)[0]
        self.assertIn('id="thCheck"', block)

    def test_the_report_has_a_place_for_every_part(self):
        for part in ("thTotals", "thRows", "thWarn"):
            with self.subTest(part=part):
                self.assertIn(f'id="{part}"', self.page)

    def test_the_totals_repeat_the_spec(self):
        for name in ("прогрев", "последовательно (расчёт)", "фактически",
                     "ускорение"):
            with self.subTest(name=name):
                self.assertIn(f"'{name}'", self.page)

    def test_each_row_names_its_proxy_and_chapters(self):
        draw = self.page.split("function thDraw(data)", 1)[1]
        self.assertIn("'поток ' + row.number", draw)
        self.assertIn("row.proxy", draw)
        self.assertIn("row.chapters.join", draw)

    def test_one_address_for_everyone_is_called_out(self):
        """Ровно то, ради чего замер и затевался."""
        self.assertIn("data.shared_address", self.page)
        self.assertIn("параллельности по", self.page)

    def test_it_says_the_download_is_not_kept(self):
        self.assertIn("Скачанное не сохраняется", self.page)


class TestGlowHasRoom(UiBase):
    """1.3: свечение кнопки упиралось в невидимую границу строки."""

    def panel(self) -> str:
        """Правило .tabs целиком: `tabs` тут уже занято текстом tabs.js."""
        return self.page.split("  .tabs{", 1)[1].split("\n  }", 1)[0]

    def test_the_panel_gives_the_glow_room(self):
        self.assertIn("padding:12px 0;", self.panel())

    def test_the_row_still_scrolls_sideways(self):
        """Вкладки идут одной строкой, сколько бы их ни было."""
        self.assertIn("flex-wrap:nowrap", self.panel())
        self.assertIn("overflow-x:auto", self.panel())

    def test_no_wrapper_clips_the_panel(self):
        wrap = self.page.split("  .wrap{", 1)[1].split("}", 1)[0]
        self.assertNotIn("overflow", wrap)


class TestPreviewBuildsItself(UiBase):
    """4.4: предпросмотр не должен ждать, пока тронут галочки."""

    def scan(self) -> str:
        return self.tabs.split("async function rnScan()", 1)[1] \
            .split("\nfunction rnRenderList", 1)[0]

    def test_it_is_built_right_after_the_folder_is_read(self):
        self.assertIn("await rnBuildPreview();", self.scan())

    def test_it_is_built_once_not_twice(self):
        """Две сборки подряд — это два запроса, и экран достаётся тому,
        который вернётся последним."""
        self.assertIn("rnRenderList(false);", self.scan())
        self.assertIn("if(build) rnUpdateChosen();", self.tabs)

    def test_ticking_a_box_still_rebuilds_it(self):
        self.assertIn("function rnRenderList(build = true)", self.tabs)

    def test_a_late_answer_cannot_overwrite_a_fresh_one(self):
        """Ответы приходят не в том порядке, в каком уходили запросы."""
        build = self.tabs.split("async function rnBuildPreview()", 1)[1]
        self.assertIn("const mine = ++rnBuildNo;", build)
        self.assertIn("if(mine !== rnBuildNo) return;", build)

    def test_the_folder_is_read_however_it_was_chosen(self):
        """Через проводник поле заполняет скрипт, а событие само не
        случится — его посылают руками."""
        self.assertIn("input.dispatchEvent(new Event('input'))", self.tabs)


class TestTitleCursor(UiBase):
    """4.2: над заголовком курсор был текстовым, а стал обычным."""

    def rule(self) -> str:
        return self.page.split("  .app-title, .sub{", 1)[1].split("}", 1)[0]

    def test_the_cursor_is_an_arrow(self):
        self.assertIn("cursor:default", self.rule())

    def test_the_title_is_not_selectable(self):
        """Текстовый курсор обещает выделение, а выделять тут нечего."""
        self.assertIn("user-select:none", self.rule())

    def test_the_subtitle_is_covered_too(self):
        self.assertIn(".app-title, .sub{", self.page)


class TestNoSyntaxWarning(unittest.TestCase):
    """4.5: `\-` управляющей последовательностью не является."""

    def test_the_source_compiles_without_warnings(self):
        """Компилируем текст, а не перезагружаем модуль: перезагрузка
        оставила бы в процессе второй экземпляр каждого класса, и чужие
        проверки «это тот же самый класс» развалились бы."""
        import warnings

        source = (ROOT / "core" / "naming.py").read_text(encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compile(source, "core/naming.py", "exec")
        self.assertEqual([str(w.message) for w in caught], [])

    def test_the_stray_backslash_is_gone_from_the_separators(self):
        """Python оставлял его в наборе как обычный символ, а
        разделителем между номером и названием он никогда не был."""
        from core.naming import SEPARATOR_CHARS

        self.assertNotIn("\\", SEPARATOR_CHARS)

    def test_the_real_separators_are_all_still_there(self):
        from core.naming import SEPARATOR_CHARS

        for char in (" ", "\t", ".", ":", "_", "-", "–", "—", ")", "]", "}"):
            with self.subTest(char=repr(char)):
                self.assertIn(char, SEPARATOR_CHARS)

    def test_names_are_still_parsed_the_same(self):
        from core.naming import parse

        found = parse("0012 - Глава 201. Название")
        self.assertEqual(found.number, 201)
        self.assertEqual(found.title, "Название")


if __name__ == "__main__":
    unittest.main(verbosity=2)
