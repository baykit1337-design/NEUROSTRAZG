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
        """Двух рисовалок журнала быть не должно — разъедутся.

        Журналов на экране уже три: разбор глав, перевод заголовков и
        проверка ключа. Проверяем, что рисовалка одна, а не что её зовут
        из какого-то одного места: мест становится больше.
        """
        self.assertEqual(self.tabs.count("function logDraw("), 1)

    def test_the_polling_of_the_log_is_shared_too(self):
        """Свой опрос у каждого журнала разошёлся бы с чужим, а чинить
        пришлось бы оба."""
        self.assertEqual(self.tabs.count("function logWatch("), 1)
        self.assertEqual(self.tabs.count("/log?since="), 1)

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

    def test_a_fanqie_row_becomes_the_mirror(self):
        """Обычный способ на этих книгах — сплошные пропуски.

        У книги на тысячу двести глав открыто десять: прогон вырождается
        в перечень недоступных. Посредник отдаёт их все, и способ виден
        в поле «Источник» — меняется одним щелчком.
        """
        pick = self.pick()
        self.assertIn("'fanqie-mirror'", pick)
        self.assertIn("srcMenu.set(source, {notify: true})", pick)

    def test_a_row_from_another_rating_takes_its_own_source(self):
        """Иначе строка с MVLEMPYR уехала бы качаться с китайского сайта."""
        pick = self.pick()
        self.assertIn("row.site", pick)
        self.assertIn("rkSites.find(", pick)

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
        self.assertIn('id="book"', self.page)
        for part in ("bookCover", "bookName", "bookMeta"):
            with self.subTest(part=part):
                self.assertIn(f'id="{part}"', self.page)

    def test_there_is_only_one_card_for_the_book(self):
        """Две карточки подряд с одинаковыми обложками — одна и та же книга.

        Откуда она взялась — выбрана в срезе или код вставлен руками —
        читателю безразлично, а картинок он видел две.
        """
        self.assertNotIn('id="rkCard"', self.page)
        self.assertNotIn('id="rkCardCover"', self.page)
        self.assertEqual(self.page.count('class="book-name"'), 1)

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
        self.assertIn("$('book').hidden = true;", self.page)


class TestTheHintInflatesLikeABubble(UiBase):
    """Подсказка должна вылетать пузырём из самого кружка с вопросом."""

    def show(self):
        return self.page.split("function tipShow(anchor, text)", 1)[1].split(
            "\n}", 1)[0]

    def test_it_grows_from_a_small_size(self):
        self.assertIn("transform:scale(.2)", self.page)
        self.assertIn(".tooltip.visible{opacity:1;transform:scale(1)}",
                      self.page)

    def curve(self):
        """Кривая роста пузыря: длительность и четыре числа."""
        found = re.search(
            r"transform ([\d.]+)s cubic-bezier\(([^)]+)\)", self.page)
        self.assertIsNotNone(found, "кривой роста нет вовсе")
        return float(found.group(1)), [float(n) for n in
                                       found.group(2).split(",")]

    def test_it_overshoots_a_little_on_the_way(self):
        """Без перелёта пузырь не надувается, а просто вырастает.

        Сами числа подбираются на глаз и меняются; важно, что вторая
        опорная точка забирается выше единицы — это и есть перелёт.
        """
        _, points = self.curve()
        self.assertGreater(points[3], 1.0, "перелёта нет, пузырь не надувается")

    def test_the_growing_is_slow_enough_to_be_seen(self):
        """За треть секунды рост не читается: «навёл — и сразу готово»."""
        seconds, _ = self.curve()
        self.assertGreaterEqual(seconds, 0.5)

    def test_the_colour_does_not_arrive_before_the_size(self):
        """Иначе пузырь уже виден целиком, а надувается будто впустую."""
        fade = re.search(r"transition:opacity ([\d.]+)s", self.page)
        self.assertIsNotNone(fade)
        seconds, _ = self.curve()
        self.assertLessEqual(float(fade.group(1)), seconds)

    def test_it_grows_out_of_the_circle_and_not_out_of_its_own_middle(self):
        self.assertIn("transform-origin:var(--tip-x) 100%", self.page)
        self.assertIn("--tip-x", self.show())

    def test_turned_down_it_grows_from_the_other_side(self):
        """Кружок сверху — значит, и расти надо сверху вниз."""
        self.assertIn(".tooltip.below{transform-origin:var(--tip-x) 0}",
                      self.page)
        self.assertIn("classList.toggle('below', below)", self.show())

    def test_there_is_a_tail_pointing_at_the_circle(self):
        self.assertIn(".tooltip::after", self.page)
        self.assertIn("left:var(--tip-x)", self.page)

    def test_the_tail_does_not_slide_off_the_corner(self):
        """У края экрана подсказку сдвигает, и центр кружка уходит за неё."""
        self.assertIn("TIP_TAIL_EDGE", self.show())

    def test_the_size_is_measured_before_it_starts_growing(self):
        """`getBoundingClientRect` вернул бы размер сжатого пузыря.

        Подсказка встала бы мимо места: ширина в момент замера — пятая
        часть настоящей.
        """
        body = self.show()
        self.assertIn("tip.offsetWidth", body)
        self.assertIn("tip.offsetHeight", body)
        self.assertNotIn("tip.getBoundingClientRect()", body)

    def test_it_is_placed_before_it_is_shown(self):
        """Иначе пузырь надувается на старом месте и прыгает на новое."""
        body = self.show()
        self.assertLess(body.index("tip.style.top"),
                        body.index("classList.add('visible')"))

    def test_motion_can_be_turned_off_by_the_system(self):
        block = self.page.split("@media (prefers-reduced-motion: reduce){", 1)
        self.assertIn(".tooltip{transform:none", block[1][:400])


class TestTheMeasurementHasItsOwnStop(UiBase):
    """Замер живёт отдельно от прогона, а кнопки у него не было.

    «Остановить» у скачивания до него не дотягивается: после отмены
    прогона замер крутился ещё три минуты и помечал прокси нерабочими —
    теми самыми, которыми потом качать.
    """

    def test_the_button_is_there(self):
        self.assertIn('id="thStop"', self.page)

    def test_it_is_hidden_until_the_measurement_starts(self):
        row = self.page.split('id="thStop"', 1)[1].split(">", 1)[0]
        self.assertIn("hidden", row)

    def test_it_appears_together_with_the_measurement(self):
        body = self.page.split("async function thCheck()", 1)[1]
        start = body.split("try{", 1)[0]
        self.assertIn("$('thStop').hidden = false;", start)

    def test_it_goes_away_when_the_measurement_ends(self):
        body = self.page.split("async function thCheck()", 1)[1]
        end = body.split("}finally{", 1)[1].split("\n  }", 1)[0]
        self.assertIn("$('thStop').hidden = true;", end)

    def test_pressing_it_asks_the_server_to_stop(self):
        body = self.page.split("$('thStop').onclick", 1)[1]
        self.assertIn("/api/threads/cancel", body)


class TestThePartCanBeWrittenTwoWays(UiBase):
    """«Глава 22.2» или «Глава 22. Часть 2» — на выбор."""

    def test_there_is_a_choice_on_the_tab(self):
        self.assertIn('id="rnPartStyle"', self.page)
        self.assertIn("Глава 22. Часть 2", self.page)

    def test_the_choice_is_sent_to_the_server(self):
        body = self.tabs.split("function rnFormat()", 1)[1].split("\n}", 1)[0]
        self.assertIn("part_style:", body)

    def test_the_live_example_shows_the_same_thing(self):
        """Пример обязан совпадать с тем, что окажется на диске."""
        body = self.tabs.split("function rnUpdateExample()", 1)[1]
        self.assertIn("fmt.part_style === 'word'", body.split("\n}", 1)[0])

    def test_changing_it_redraws_the_preview(self):
        self.assertIn("rnPartMenu", self.tabs)


class TestTheDownloadCarriesItsSettings(UiBase):
    """Настройки прогона до сервера не доходили.

    В запрос на запуск уходили только книга, папка и диапазон. Числа
    потоков там не было вовсе, сервер брал умолчание — один, — и
    выставленное на экране не влияло ни на что.
    """

    def payload(self):
        body = self.page.split("await call('/api/start', {", 1)[1]
        return body.split("});", 1)[0]

    def test_the_number_of_threads_is_sent(self):
        self.assertIn("threads:", self.payload())
        self.assertIn("dlThreads", self.payload())

    def test_the_chosen_mode_is_sent(self):
        """Ручной режим пропускает автопробу — сервер должен знать о нём."""
        self.assertIn("mode: dlMode", self.payload())

    def test_the_waiting_times_are_sent_too(self):
        body = self.payload()
        self.assertIn("timeout:", body)
        self.assertIn("connect_timeout:", body)

    def test_the_screen_says_how_many_threads_actually_work(self):
        """Прежняя строка показывала вердикт пробы и только в авторежиме."""
        self.assertIn("$('sMethod').textContent = many", self.page)
        self.assertIn("'в один поток'", self.page)

    def test_a_single_thread_is_marked_out(self):
        """Это не поломка, но и не то, о чём просили."""
        self.assertIn(".pnow.warn{", self.page)
        self.assertIn("classList.toggle('warn', !many)", self.page)


class TestTheRunCanBeHeldInstead(UiBase):
    """Обрыв сети заканчивал книгу на середине — теперь её можно держать."""

    def test_the_button_stands_by_the_bar(self):
        card = self.page.split('id="progress"', 1)[1].split("</div>\n  </div>",
                                                            1)[0]
        self.assertIn('id="hold"', card)

    def test_it_asks_the_server_to_hold_and_to_carry_on(self):
        body = self.page.split("async function hold()", 1)[1].split("\n}", 1)[0]
        self.assertIn("resume", body)
        self.assertIn("pause", body)

    def test_the_label_changes_with_the_state(self):
        body = self.page.split("function showHold()", 1)[1].split("\n}", 1)[0]
        self.assertIn("Продолжить", body)
        self.assertIn("Пауза", body)

    def test_a_pause_is_not_the_end_of_the_work(self):
        """Иначе опрос прекратится и продолжения никто не дождётся."""
        self.assertIn("paused:'Пауза'", self.page)
        terminal = self.page.split("const TERMINAL = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("paused", terminal)

    def test_the_state_is_taken_from_the_server(self):
        """Перезагрузка страницы не должна врать про идущую работу."""
        self.assertIn("job.paused !== held", self.page)

    def test_a_finished_run_has_nothing_to_hold(self):
        self.assertIn("$('hold').hidden = true;", self.page)


class TestEveryTabCanTurnOffTheTitle(UiBase):
    """В «Переименовать» галки не было, и заголовок писался всегда.

    Сервер брал умолчание `True`, выключить его было нечем: у книги, где
    название главы уже есть в самом тексте, оно попадало в файл дважды.
    """

    def test_all_three_tabs_have_the_tick(self):
        for box in ("spHeadings", "mgHeadings", "rnHeadings"):
            with self.subTest(box=box):
                self.assertIn(f'id="{box}"', self.page)

    def test_the_rename_tab_sends_it_to_the_server(self):
        payload = self.tabs.split("function rnPayload()", 1)[1].split("\n}", 1)[0]
        self.assertIn("headings: $('rnHeadings').checked,", payload)

    def test_the_other_two_still_send_theirs(self):
        for box in ("spHeadings", "mgHeadings"):
            with self.subTest(box=box):
                self.assertIn(f"headings: $('{box}').checked", self.tabs)


class TestPickingFilesLooksTheSameEverywhere(UiBase):
    """Выбор файлов устроен одинаково, а выглядел по-разному.

    В «Переименовать» — поле пути и кнопка «Выбрать…» справа. В
    «Разбить» и «Объединить» — голая кнопка во всю строку. Функция одна
    и та же, и разнобой тут ничем не оправдан.
    """

    #: Поля, у которых должен быть одинаковый вид.
    #:
    #: `fmBookPath` сюда не входит нарочно: там выбирают не «файлы или
    #: папку», а одну готовую книгу, и заполнитель у него свой. Вид
    #: строки при этом тот же — поле и «Выбрать…» рядом.
    FIELDS = ("spPath", "mgPath", "cvPath", "rnIn", "fmPath")

    def row_of(self, field):
        """Строка разметки с этим полем и кнопкой рядом."""
        before = self.page.split(f'id="{field}"', 1)[0]
        return before.rsplit('<div class="row"', 1)[1] \
            + self.page.split(f'id="{field}"', 1)[1].split("</div>", 1)[0]

    def test_every_tab_has_a_path_field(self):
        for field in self.FIELDS:
            with self.subTest(field=field):
                self.assertIn(f'id="{field}"', self.page)

    def test_the_button_stands_beside_it_and_not_across_the_row(self):
        """`flex:1` растягивал кнопку на всю строку — оттуда и разнобой."""
        for field in self.FIELDS:
            with self.subTest(field=field):
                row = self.row_of(field)
                self.assertIn("Выбрать…", row)
                self.assertNotIn('style="flex:1"', row)

    def test_they_all_say_the_same_thing(self):
        """«Путь к папке от WebToEpub» — про чужую программу и про папку.

        Про саму WebToEpub на вкладке речь всё же идёт: кнопка «Ссылки»
        собирает список именно для неё. Поэтому смотрим на заполнители
        полей, а не на всю страницу.

        Число берётся из `FIELDS`, а не пишется цифрой: вкладок с выбором
        файлов становится больше, и новая должна попадать в проверку, а
        не ронять её.
        """
        self.assertEqual(self.page.count('placeholder="Путь к файлу или папке"'),
                         len(self.FIELDS))
        for field in self.FIELDS:
            with self.subTest(field=field):
                self.assertNotIn("WebToEpub", self.row_of(field))

    def test_the_field_is_kept_in_step_with_the_choice(self):
        self.assertIn("syncPickPath(listId);", self.tabs)
        chosen = self.tabs.split("function renderChosen(listId)", 1)[1]
        self.assertIn("syncPickPath(listId)", chosen.split("\n}", 1)[0])

    def test_a_path_typed_by_hand_counts_as_chosen(self):
        """Окно выбора может не открыться — иначе это тупик."""
        body = self.tabs.split(".pickpath').forEach", 1)[1]
        self.assertIn("CHOSEN[listId] = typed ? [typed] : [];", body)
        self.assertIn("renderChosen(listId)", body)

    def test_our_own_counter_is_not_mistaken_for_a_path(self):
        """«выбрано 12 путей» — это наш текст, а не адрес на диске."""
        body = self.tabs.split(".pickpath').forEach", 1)[1]
        self.assertIn("/^выбрано \\d+ /.test(typed)", body)

    def test_typing_is_not_interrupted_by_a_refresh(self):
        body = self.tabs.split("function syncPickPath(listId)", 1)[1]
        self.assertIn("field === document.activeElement", body)


class TestHiddenReallyHides(UiBase):
    """`hidden` не работал на всём, у чего задан свой `display`.

    Атрибут прячет через `display:none` из браузерного набора правил, а
    он слабее любого авторского. В «Разбить» и «Объединить» над формой
    из-за этого висела пустая полоса `.schema` и кнопка «Очистить
    список» в `.row` — при том, что выбирать было ещё нечего.
    """

    def test_there_is_one_rule_for_the_whole_page(self):
        self.assertIn("[hidden]{display:none !important}", self.page)

    def test_the_blocks_that_showed_through_are_marked_hidden(self):
        """Разметка была права — не работало правило."""
        for part in ("spSchema", "mgSchema", "spListBar", "mgListBar"):
            with self.subTest(part=part):
                block = self.page.split(f'id="{part}"', 1)[1].split(">", 1)[0]
                self.assertIn("hidden", block)

    def test_those_blocks_still_declare_their_own_display(self):
        """Иначе тест зелёный, а причина ушла — и вернётся с новым блоком."""
        self.assertIn(".schema{margin-top:12px;", self.page)
        self.assertIn(".row{display:flex", self.page)


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

    def test_the_same_address_twice_does_not_hide_it_forever(self):
        """Из рейтинга карточку заполняют дважды: срезом и поиском.

        Второй `onload` на тот же src браузер не пришлёт, и обложка
        осталась бы спрятанной навсегда.
        """
        body = self.cover()
        self.assertIn("cover.getAttribute('src') === src", body)
        self.assertIn("cover.complete && cover.naturalWidth", body)

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
        """Сверху не поместилась — уходит под элемент, а не за край."""
        body = self.show()
        self.assertIn("top < TIP_EDGE", body)
        self.assertIn("box.bottom + TIP_GAP", body)

    def test_it_slides_left_when_there_is_no_room_right(self):
        self.assertIn("window.innerWidth", self.show())
        self.assertIn("TIP_EDGE", self.show())

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

    def test_the_link_comes_from_the_row(self):
        """Раньше ссылка складывалась из кода прямо здесь.

        Сайт был один, и это работало. У второго рейтинга адрес книги
        строится из слага, а не из кода, и вычислить его на странице уже
        нечем — готовую ссылку кладёт в строку сервер. Поэтому проверяем
        не формулу, а то, что меню берёт ссылку у строки.
        """
        self.assertIn("rkLink(row)", self.menu())

    def test_a_row_without_its_own_link_still_points_at_fanqie(self):
        """Срезы лежат месяцами: в старых поля `link` нет вовсе."""
        block = self.tabs.split("function rkLink(row)", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("row.link", block)
        self.assertIn("RK_LINK + row.book_id", block)
        self.assertIn("https://fanqienovel.com/page/", self.tabs)

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


class TestTabRowHasRoomForEveryTab(UiBase):
    """Строке вкладок не хватало ширины, и края кнопок пропадали.

    Причин было две, и обе видны только в браузере. Первая: строка была
    заперта потолком в 1340 пикселей, и на экране в 1920 десяти вкладкам
    не хватало места, хотя рядом пустовало почти шестьсот. Вторая: завеса
    по краям висела всегда, и крайняя кнопка теряла край даже тогда,
    когда прокручивать было нечего.
    """

    def panel(self) -> str:
        return self.page.split("  .tabs{", 1)[1].split("\n  }", 1)[0]

    def test_the_row_is_not_kept_narrower_than_the_window(self):
        """Потолок остаётся — но выше того, что нужно десяти вкладкам."""
        import re

        found = re.search(r"width:min\(100vw - \d+px,\s*(\d+)px\)",
                          self.panel())
        self.assertIsNotNone(found, "ширина строки задаётся не так")
        self.assertGreaterEqual(int(found.group(1)), 1500)

    def test_the_fade_width_is_set_from_the_scroll_position(self):
        """Постоянная завеса и была тем, что откусывало край кнопки."""
        panel = self.panel()
        self.assertIn("var(--fade-left)", panel)
        self.assertIn("var(--fade-right)", panel)
        self.assertIn("--fade-left:0px", panel)
        self.assertIn("--fade-right:0px", panel)

    def test_the_fade_follows_the_real_scroll(self):
        body = self.page.split("function tabsEdges()", 1)[1] \
            .split("\n}", 1)[0]
        self.assertIn("nav.scrollLeft", body)
        self.assertIn("nav.scrollWidth - nav.clientWidth", body)
        self.assertIn("setProperty('--fade-left'", body)
        self.assertIn("setProperty('--fade-right'", body)

    def test_it_is_recounted_when_something_moves(self):
        """Иначе завеса остаётся от прежнего размера окна."""
        self.assertIn("addEventListener('scroll', tabsEdges", self.page)
        self.assertIn("addEventListener('resize', tabsEdges)", self.page)

    def test_it_is_counted_at_the_start_too(self):
        """До первой прокрутки завеса тоже должна быть верной."""
        self.assertIn("\ntabsEdges();", self.page)

    def test_a_tab_beyond_the_edge_is_brought_into_view(self):
        """В узком окне строка всё же прокручивается — и нажатая кнопка
        не должна остаться наполовину за краем."""
        self.assertIn("btn.scrollIntoView({block: 'nearest'", self.page)

    def test_icons_leave_before_the_row_starts_scrolling(self):
        """Порог взят по замеру: со значками десять вкладок влезают
        начиная примерно с 1440."""
        import re

        found = re.search(r"@media \(max-width:(\d+)px\)\{ \.tabs button svg",
                          self.page)
        self.assertIsNotNone(found, "значки прячутся не так")
        self.assertGreaterEqual(int(found.group(1)), 1400)


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


class TestTabsOpenReadyToWork(UiBase):
    """Умолчания и свёрнутые карточки на всех вкладках.

    Каждая вкладка открывалась требуя настройки: снять галочки, выбрать
    формат, придумать имя папке. Вокруг главного лежали карточки, в
    которые обычно не заглядывают, и на своей же вкладке было непонятно,
    куда нажимать.
    """

    def card(self, name):
        start = self.page.index(f'id="{name}"')
        return self.page[self.page.rindex("<div", 0, start):
                         self.page.index(">", start) + 1]

    def box(self, name):
        start = self.page.index(f'id="{name}"')
        return self.page[self.page.rindex("<input", 0, start):
                         self.page.index(">", start) + 1]

    def test_the_side_cards_are_folded_on_every_tab(self):
        """Оформление и обработка текста — не работа вкладки, а её
        настройки."""
        for name in ("mgStyle", "mgPrep",          # объединить
                     "cvStyle", "cvPrep",          # конвертировать
                     "spStyle", "spPrep",          # разбить
                     "rnPatternCard", "rnListCard",  # переименовать
                     "rnPreviewCard", "rnVolCard"):
            with self.subTest(name):
                self.assertIn("folded", self.card(name))
                self.assertIn("data-fold", self.card(name))

    def test_the_chapter_name_is_not_repeated_inside_the_text(self):
        """Название уже стоит в имени файла. Галка стояла сама, и в
        каждой главе название оказывалось дважды."""
        for name in ("cvHeadings", "rnHeadings", "spHeadings"):
            with self.subTest(name):
                self.assertNotIn("checked", self.box(name))

    def test_renaming_ticks_only_the_chapter_number(self):
        """«Глава 99» — и всё. Остальное человек поставит сам."""
        self.assertIn("checked", self.box("rnNum"))
        for name in ("rnPart", "rnTitle"):
            with self.subTest(name):
                self.assertNotIn("checked", self.box(name))

    def test_the_part_number_switches_itself_on_when_chapters_are_divided(self):
        """Без него части главы получают одно имя, и запись встаёт на
        совпадении имён."""
        start = self.tabs.index("function rnApplySplit")
        body = self.tabs[start:self.tabs.index("\n}", start)]
        self.assertIn("rnPart", body)

    def body(self, name):
        """Тело функции — до следующей на верхнем уровне."""
        start = self.tabs.index(name)
        rest = self.tabs.find("\n}\n", start)
        return self.tabs[start:rest if rest > 0 else len(self.tabs)]

    def test_the_output_format_follows_the_source_everywhere(self):
        """Вопрос «какой формат у исходника» на всех вкладках один, и
        отвечает на него одна функция: три ответа разошлись бы."""
        self.assertIn("function guessFormat", self.tabs)
        for name in ("async function spScan", "async function mgScan",
                     "async function rnScan"):
            with self.subTest(name):
                self.assertIn("uessFormat", self.body(name))

    def test_where_to_save_needs_no_invented_folder_name(self):
        """Человек уже выбрал, куда положить. Имя папки — по желанию."""
        for name in ("spOwnFolder", "rnOwnFolder"):
            with self.subTest(name):
                self.assertIn(f'id="{name}"', self.page)


class TestTheHeadingStyleIsAttachedToItsWork(UiBase):
    """«Как выглядит заголовок» висело в самом верху «Форматировать», до
    обеих работ, и было непонятно, к чему оно вообще относится."""

    def order(self):
        """Заголовки карточек вкладки — сверху вниз."""
        start = self.page.index('id="tab-format"')
        end = self.page.index("</section>", start)
        return re.findall(r'<label[^>]*>([^<]+)', self.page[start:end])

    def test_it_stands_between_the_two_works_it_governs(self):
        names = self.order()
        collect = next(i for i, one in enumerate(names)
                       if "Собрать книгу из глав" in one)
        style = next(i for i, one in enumerate(names)
                     if "Как выглядит заголовок" in one)
        retitle = next(i for i, one in enumerate(names)
                       if "Заголовки в готовой книге" in one)
        self.assertLess(collect, style)
        self.assertLess(style, retitle)

    def test_it_says_out_loud_what_it_governs(self):
        """Вопрос «а это к чему?» должен закрываться на самой карточке."""
        start = self.page.index('id="fmStyle"')
        card = self.page[start:self.page.index("</div>\n\n", start)]
        self.assertIn("обе работы", card)

    def test_there_is_still_only_one_of_it(self):
        """Копия разъехалась бы с оригиналом на первой же правке."""
        self.assertEqual(self.page.count('id="fmPrefix"'), 1)
        self.assertEqual(self.page.count('id="fmStyle"'), 1)


class TestTheProgramRemembersWhereYouSave(UiBase):
    """Между запусками не помнилось ничего, кроме галочек эффектов.

    Папку назначения приходилось набирать заново каждый раз и на каждой
    вкладке отдельно. При работе «в два клика» это самая дорогая потеря
    времени из всех.
    """

    def field(self, name):
        start = self.page.index(f'id="{name}"')
        return self.page[self.page.rindex("<input", 0, start):
                         self.page.index(">", start) + 1]

    def test_every_destination_folder_is_remembered(self):
        for name in ("spBase", "rnBase", "mgBase", "cvBase", "fmBase",
                     "fmOutBase", "fmJunkBase", "hdBase", "rpBase",
                     "sgBase", "ckBase"):
            with self.subTest(name):
                self.assertIn("data-keep", self.field(name))

    def test_only_marked_fields_are_remembered(self):
        """Правило нарочно от обратного: попади сюда поле ключа или
        ссылка на книгу, они молча осели бы в хранилище браузера."""
        self.assertIn("[data-keep]", self.tabs)
        self.assertNotIn("data-keep", self.field("llmKey"))

    def test_the_key_field_is_not_marked(self):
        """Ключ в хранилище браузера — это ключ, отданный любому скрипту
        на этой странице."""
        start = self.page.index('id="llmKey"')
        block = self.page[self.page.rindex("<textarea", 0, start):
                          self.page.index(">", start) + 1]
        self.assertNotIn("data-keep", block)

    def test_restoring_wakes_the_labels(self):
        """На событии висят подписи «главы лягут в…» и схемы. Молча
        подставленное значение оставило бы их пустыми, и человек решил
        бы, что поле не заполнено."""
        start = self.tabs.index("function keepLoad")
        body = self.tabs[start:self.tabs.index("\n}", start)]
        self.assertIn("dispatchEvent", body)

    def test_the_recent_folders_list_has_a_limit(self):
        """Список, в котором надо искать, — уже не подсказка."""
        self.assertIn("FOLDERS_KEPT", self.tabs)
        start = self.tabs.index("function folderUsed")
        self.assertIn("slice(0, FOLDERS_KEPT)",
                      self.tabs[start:self.tabs.index("\n}", start)])

    def test_a_repeated_folder_rises_instead_of_piling_up(self):
        """Список из одной папки в трёх экземплярах бесполезен."""
        start = self.tabs.index("function folderUsed")
        body = self.tabs[start:self.tabs.index("\n}", start)]
        self.assertIn("filter", body)
        self.assertIn("unshift", body)

    def test_a_closed_storage_does_not_break_the_page(self):
        """Приватное окно или запрет на хранение: живём без памяти, но
        живём."""
        for name in ("function keepRead", "function keepWrite"):
            with self.subTest(name):
                start = self.tabs.index(name)
                self.assertIn("catch",
                              self.tabs[start:self.tabs.index("\n}", start)])

    def test_the_native_picker_also_counts_as_a_choice(self):
        """Выбор в системном окне — такое же решение человека, как
        набранный руками путь, и запомниться должен так же."""
        start = self.tabs.index("async function pickPath")
        body = self.tabs[start:self.tabs.index("\n}", start)]
        self.assertIn("new Event('change')", body)


class TestShortcutsAndNotice(UiBase):
    """Горячих клавиш на всю программу было две, а долгую работу
    приходилось сторожить глазами."""

    def body(self, name):
        start = self.tabs.index(name)
        rest = self.tabs.find("\n}\n", start)
        return self.tabs[start:rest if rest > 0 else len(self.tabs)]

    def test_keys_are_read_by_code_not_by_letter(self):
        """На кириллице Ctrl+O — это Ctrl+Щ, и по букве он не поймается."""
        self.assertIn("event.code === 'KeyO'", self.tabs)
        self.assertIn("event.code === 'KeyZ'", self.tabs)

    def test_the_button_is_found_on_the_tab_not_by_a_table(self):
        """Таблица «вкладка → кнопка» устаревает молча, стоит
        переименовать один `id`."""
        self.assertIn("function tabNow", self.tabs)
        self.assertIn("button.primary", self.body("function tabPress")
                      + self.tabs[self.tabs.index("event.code === 'Enter'"):
                                  self.tabs.index("event.code === 'Enter'") + 400])

    def test_a_button_behind_a_closed_window_is_not_pressed(self):
        """На «Разбить» первой в разметке идёт `primary` из закрытого окна
        «Разделить», и Ctrl+Enter нажимал бы её вместо «Разбить». Свой
        `hidden` этого не ловит — спрятан родитель."""
        self.assertIn("function onScreen", self.tabs)
        self.assertIn("offsetParent", self.body("function onScreen"))
        self.assertIn("onScreen", self.body("function tabPress"))

    def test_undo_does_not_steal_undo_from_text_fields(self):
        """Там своя отмена, и отнимать её у набора текста нельзя."""
        self.assertIn("function typing", self.tabs)
        self.assertIn("if(typing()) return;", self.tabs)

    def test_finishing_is_told_only_when_nobody_is_looking(self):
        """Сообщать о готовом тому, кто смотрит на прогресс, — шум."""
        self.assertIn("if(!document.hidden) return;", self.body("function jobDone"))

    def test_the_tab_title_says_it_without_asking_permission(self):
        """Заголовок виден всегда и ничего не спрашивает; настоящее
        уведомление — только если человек его разрешил."""
        self.assertIn("function titleSay", self.tabs)
        body = self.body("function jobDone")
        self.assertIn("titleSay", body)
        self.assertIn("Notification.permission", body)

    def test_the_title_comes_back_when_looked_at(self):
        self.assertIn("visibilitychange", self.tabs)
        self.assertIn("TITLE_WAS", self.tabs)

    def test_every_job_gets_it_not_just_one_tab(self):
        """Опрос задач общий — там и место, иначе половина вкладок
        промолчала бы."""
        self.assertIn("jobDone(job)", self.body("function pollJob"))


class TestTheRatingShowsItIsWorking(UiBase):
    """Пока рейтинг идёт с сайта, было видно только «Запрашиваем…».

    Полоса отвечает на вопрос, который в это время и возникает:
    работает оно или подвисло.
    """

    def body(self, name):
        start = self.tabs.index(name)
        rest = self.tabs.find("\n}\n", start)
        return self.tabs[start:rest if rest > 0 else len(self.tabs)]

    def test_there_is_a_bar_and_it_starts_hidden(self):
        self.assertIn('id="rkBar"', self.page)
        start = self.page.index('id="rkBar"')
        self.assertIn("hidden", self.page[start:self.page.index(">", start)])

    def test_it_promises_no_percentage(self):
        """Процентов взять неоткуда: рейтинг приходит одной страницей за
        один запрос, делить нечего. Нарисованное число было бы враньём."""
        self.assertIn(".bar.waiting", self.page)
        # У полосы ожидания ширина своя и постоянная — она не притворяется
        # долей сделанного.
        rule = self.page[self.page.index(".bar.waiting > i{"):]
        self.assertIn("width:35%", rule[:rule.index("}")])

    def test_it_is_shown_while_the_site_is_asked(self):
        self.assertIn("rkWaiting(true)", self.body("async function rkRefresh"))

    def test_it_goes_away_even_when_the_site_refuses(self):
        """Полоса, застрявшая после отказа, выглядит как вечная загрузка."""
        body = self.body("async function rkRefresh")
        self.assertIn("finally", body)
        self.assertIn("rkWaiting(false)", body[body.index("finally"):])

    def test_reading_from_memory_does_not_flash_it(self):
        """Разделы из памяти приходят мгновенно — полоса там была бы
        миганием на ровном месте."""
        body = self.body("async function rkLoadCategories")
        self.assertIn("if(fetchFromSite) rkWaiting(true)", body)

    def test_it_respects_the_wish_for_less_movement(self):
        rule = self.page[self.page.index(".bar.waiting"):]
        self.assertIn("prefers-reduced-motion: no-preference",
                      rule[:rule.index("@keyframes bar-wait")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
