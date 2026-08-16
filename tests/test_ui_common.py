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


if __name__ == "__main__":
    unittest.main(verbosity=2)
