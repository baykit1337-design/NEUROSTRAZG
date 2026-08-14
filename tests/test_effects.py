"""Оформление: эффекты и их выключатели (часть 6 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"
CSS = STATIC / "css" / "effects"
JS = STATIC / "js" / "effects"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.settings = (JS / "settings.js").read_text(encoding="utf-8")


class TestStructure(Base):
    """6.2: каждый эффект — отдельный файл, любой снимается сам по себе."""

    def test_effect_files_live_in_their_own_folder(self):
        self.assertTrue(CSS.is_dir())
        self.assertTrue(JS.is_dir())
        self.assertTrue(list(CSS.glob("*.css")))

    def test_every_effect_file_is_linked(self):
        for path in CSS.glob("*.css"):
            self.assertIn(f"/static/css/effects/{path.name}", self.html)

    def test_every_effect_file_has_a_switch(self):
        """Файл без галочки нельзя выключить — значит, его нет в реестре."""
        for path in CSS.glob("*.css"):
            self.assertIn(f"key: '{path.stem}'", self.settings, path.name)

    def test_effects_are_scoped_to_their_class(self):
        """Иначе снятая галочка ничего бы не выключала."""
        for path in CSS.glob("*.css"):
            text = path.read_text(encoding="utf-8")
            rules = [line for line in text.splitlines()
                     if line and not line.startswith((" ", "\t", "}", "/*", " *", "@"))
                     and "{" in line and not line.startswith("@keyframes")]
            for rule in rules:
                self.assertIn(f".fx-{path.stem}", rule, f"{path.name}: {rule}")

    def test_settings_tab_exists(self):
        self.assertIn('data-tab="looks"', self.html)
        self.assertIn('id="tab-looks"', self.html)
        self.assertIn('id="fxList"', self.html)

    def test_all_off_is_one_button(self):
        self.assertIn('id="fxNone"', self.html)
        self.assertIn('id="fxAll"', self.html)

    def test_choice_is_remembered(self):
        self.assertIn("localStorage", self.settings)

    def test_reduced_motion_is_respected(self):
        """Системная настройка сильнее галочек."""
        self.assertIn("prefers-reduced-motion", self.settings)
        for path in CSS.glob("*.css"):
            text = path.read_text(encoding="utf-8")
            if "@keyframes" not in text:
                continue
            self.assertIn("prefers-reduced-motion: no-preference", text, path.name)


class TestTitleGlitch(Base):
    """6.5: глитч как момент переключения, инверсия как результат."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (CSS / "title-glitch.css").read_text(encoding="utf-8")

    def test_glitch_only_on_hover_never_looping(self):
        self.assertIn(":hover::before", self.css)
        # Один проход, а не бесконечный цикл.
        self.assertNotIn("infinite", self.css)

    def test_two_coloured_twins(self):
        self.assertIn("#ff3b6b", self.css)
        self.assertIn("#3bf0ff", self.css)

    def test_glitch_is_short(self):
        self.assertIn(".25s", self.css)

    def test_inversion_is_the_resting_state(self):
        block = self.css[self.css.index(".fx-title-glitch .app-title:hover{"):]
        block = block[:block.index("}")]
        self.assertIn("background:var(--neon", block)
        self.assertIn("color:#12101a", block)

    def test_return_is_smooth_and_without_a_second_glitch(self):
        """Обратный переход — по transition, анимация назад не запускается."""
        self.assertIn("transition:background", self.css)

    def test_title_carries_its_text_for_the_twins(self):
        self.assertIn("content:attr(data-text)", self.css)
        self.assertIn("dataset.text", self.settings)


class TestButtonPress(Base):
    """6.6: три эффекта одновременно, всё в 250 мс."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (CSS / "button-press.css").read_text(encoding="utf-8")

    def test_press_scales_down(self):
        self.assertIn("transform:scale(.96)", self.css)

    def test_ring_flashes_and_fades(self):
        self.assertIn("@keyframes fx-press-ring", self.css)
        self.assertIn("fx-press-ring .2s", self.css)

    def test_label_glitches(self):
        self.assertIn("@keyframes fx-press-text", self.css)

    def test_everything_fits_into_the_budget(self):
        """Каждая часть короче 250 мс — иначе нажатие начнёт тормозить."""
        import re

        for length in re.findall(r"fx-press-\w+ (\.\d+)s", self.css):
            self.assertLessEqual(float(length), 0.25, length)

    def test_hover_glow_is_not_overridden(self):
        """6.1: существующая подсветка в приоритете, эффект добавляется поверх."""
        self.assertNotIn(":hover", self.css)


class TestFeedback(Base):
    """6.7: скелетоны, живая полоса, счётчики, вспышка по завершении."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = (JS / "feedback.js").read_text(encoding="utf-8")
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_skeletons_are_used_somewhere(self):
        """Эффект, который никто не вызывает, — мёртвый код."""
        self.assertIn("function fxSkeleton", self.js)
        self.assertIn("fxSkeleton(", self.tabs)

    def test_progress_keeps_its_old_shimmer(self):
        """6.1: блик был раньше, новые эффекты добавляются поверх него."""
        css = (CSS / "progress-life.css").read_text(encoding="utf-8")
        self.assertNotIn("mvl-shimmer", css)
        self.assertIn("mvl-shimmer", self.html)

    def test_spark_sits_on_the_leading_edge(self):
        css = (CSS / "progress-life.css").read_text(encoding="utf-8")
        self.assertIn("::before", css)
        self.assertIn("right:-1px", css)

    def test_counter_rolls_within_half_a_second(self):
        self.assertIn("FX_COUNT_MS = 500", self.js)

    def test_counter_does_not_chase_its_own_tail(self):
        """Эффект сам пишет промежуточные числа — наблюдатель их пропускает."""
        self.assertIn("_fxRolling", self.js)

    def test_only_whole_numbers_roll(self):
        """«18 мин 42 с» прокручивать нельзя."""
        self.assertIn(r"/^\d+$/", self.js)

    def test_flash_happens_once_not_in_a_loop(self):
        css = (CSS / "done-flash.css").read_text(encoding="utf-8")
        self.assertIn("fx-done-wave .62s ease-out 1", css)
        self.assertNotIn("infinite", css)

    def test_flash_can_repeat_on_the_next_run(self):
        """Класс снимается, иначе второй операции вспышки не досталось бы."""
        self.assertIn("classList.remove('fx-flash')", self.js)


class TestBackground(Base):
    """6.3: аврора, зерно, и оба — под содержимым."""

    def test_layers_do_not_fight_for_one_pseudo_element(self):
        """У элемента их два, а фоновых слоёв больше."""
        used = {}
        for name in ("aurora", "grain", "spotlight"):
            text = (CSS / f"{name}.css").read_text(encoding="utf-8")
            head = [line for line in text.splitlines() if line.startswith(".fx-")][0]
            self.assertNotIn(head, used, f"{name} и {used.get(head)} на одном слое")
            used[head] = name

    def test_background_layers_are_behind_and_deaf(self):
        for name in ("aurora", "grain", "spotlight"):
            text = (CSS / f"{name}.css").read_text(encoding="utf-8")
            self.assertIn("z-index:-", text, name)
            self.assertIn("pointer-events:none", text, name)

    def test_aurora_animates_only_transform(self):
        """Иначе браузер пересчитывал бы раскладку двадцать раз в секунду."""
        css = (CSS / "aurora.css").read_text(encoding="utf-8")
        block = css[css.index("@keyframes fx-aurora-drift"):]
        for line in block.splitlines():
            if ":" in line and "{" in line:
                self.assertIn("transform:", line)

    def test_aurora_cycle_is_long(self):
        css = (CSS / "aurora.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"fx-aurora-drift (2[5-9]|30)s")

    def test_grain_is_barely_there(self):
        css = (CSS / "grain.css").read_text(encoding="utf-8")
        self.assertIn("opacity:.03", css)
        # Картинка внутри стиля, а не отдельным запросом.
        self.assertIn("data:image/svg+xml", css)


class TestCursor(Base):
    """6.4: прожектор, свой курсор, магнитные кнопки."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = (JS / "pointer.js").read_text(encoding="utf-8")

    def test_spotlight_position_comes_from_variables(self):
        css = (CSS / "spotlight.css").read_text(encoding="utf-8")
        self.assertIn("var(--mx", css)
        self.assertIn("var(--my", css)

    def test_spotlight_repaints_once_per_frame(self):
        """mousemove приходит чаще, чем экран перерисовывается."""
        self.assertIn("requestAnimationFrame", self.js)

    def test_cursor_keeps_system_ones_where_they_mean_something(self):
        css = (CSS / "cursor.css").read_text(encoding="utf-8")
        self.assertIn("cursor:text", css)
        self.assertIn("cursor:not-allowed", css)

    def test_cursor_is_an_arrow_without_a_trailing_ring(self):
        css = (CSS / "cursor.css").read_text(encoding="utf-8")
        self.assertIn("cursor:url(", css)
        self.assertNotIn("@keyframes", css)

    def test_magnet_pull_is_small(self):
        self.assertIn("FX_MAGNET = 4", self.js)

    def test_magnet_skips_small_buttons(self):
        """Строки списков не магнитим: кнопки там мелкие и стоят вплотную."""
        self.assertIn("FX_MAGNET_MIN", self.js)

    def test_magnet_returns_with_a_spring(self):
        self.assertIn("cubic-bezier(.34,1.56,.64,1)", self.js)


class TestDetails(Base):
    """6.8 и 6.9: строки таблиц, переход между вкладками, статичные формы."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = (JS / "pointer.js").read_text(encoding="utf-8")

    def test_row_sweep_runs_left_to_right(self):
        css = (CSS / "row-sweep.css").read_text(encoding="utf-8")
        block = css[css.index("@keyframes fx-row-sweep"):]
        self.assertIn("translateX(-100%)", block)
        self.assertIn("translateX(100%)", block)

    def test_row_sweep_keeps_the_old_hover(self):
        """6.1: фон строки при наведении был раньше, блик добавляется поверх."""
        css = (CSS / "row-sweep.css").read_text(encoding="utf-8")
        self.assertNotIn("background:rgba(176,108,255,.07)", css)
        self.assertIn(".table .tr:hover{background:rgba(176,108,255,.07)}", self.html)

    def test_tab_grows_from_the_pressed_button(self):
        css = (CSS / "tab-grow.css").read_text(encoding="utf-8")
        self.assertIn("transform-origin:var(--fx-origin", css)
        self.assertIn("--fx-origin", self.js)

    def test_tab_transition_matches_the_spec(self):
        css = (CSS / "tab-grow.css").read_text(encoding="utf-8")
        self.assertIn("scale(.96) translateY(-8px)", css)
        self.assertRegex(css, r"fx-tab-grow \.(2[5-9]|30)s")

    def test_cascade_does_not_grow_without_bound(self):
        """На «Инструментах» блоков больше десяти — задержка не копится."""
        css = (CSS / "tab-grow.css").read_text(encoding="utf-8")
        self.assertIn("nth-child(n+6)", css)

    def test_origin_is_taken_after_the_tab_switched(self):
        """Перехват сработал бы раньше выбора раздела — на старом."""
        self.assertIn("Всплытие, а не перехват", self.js)

    def test_static_cards_light_up_but_stay_arrows(self):
        css = (CSS / "static-cards.css").read_text(encoding="utf-8")
        self.assertIn("cursor:default", css)
        self.assertIn(":hover", css)


class TestExistingLookSurvives(Base):
    """6.1: то, что работало, должно остаться."""

    def test_card_glow_in_two_states(self):
        self.assertIn(".card{", self.html)
        self.assertIn(".card:hover", self.html)

    def test_button_text_still_lights_up_on_hover(self):
        block = self.html[self.html.index("button:hover:not(:disabled){"):]
        block = block[:block.index("}")]
        self.assertIn("text-shadow", block)
        self.assertIn("color:#ffffff", block)

    def test_tabs_are_still_one_line(self):
        block = self.html[self.html.index(".tabs{"):]
        self.assertIn("flex-wrap:nowrap", block[:600])


if __name__ == "__main__":
    unittest.main(verbosity=2)
