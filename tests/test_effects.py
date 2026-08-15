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
    """3.3: глитч как момент переключения, градиент как состояние после."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (CSS / "title-glitch.css").read_text(encoding="utf-8")

    def test_glitch_only_on_hover(self):
        self.assertIn(":hover::before", self.css)

    def test_glitch_runs_once(self):
        """Постоянно дёргающееся название читать невозможно."""
        for line in self.css.splitlines():
            if "fx-glitch-" in line and "animation:" in line:
                self.assertNotIn("infinite", line, line)

    def test_two_coloured_twins(self):
        self.assertIn("#ff3b6b", self.css)
        self.assertIn("#3bf0ff", self.css)

    def test_glitch_is_short(self):
        self.assertIn(".25s", self.css)

    def test_inversion_is_gone(self):
        """Тёмные буквы на ярком фоне читались как выделенный текст."""
        self.assertNotIn("color:#12101a", self.css)
        self.assertNotIn("background:var(--neon", self.css)

    def test_gradient_flows_by_the_letters(self):
        self.assertIn("background-clip:text", self.css)
        self.assertIn("@keyframes fx-title-flow", self.css)

    def test_gradient_cycle_is_three_seconds(self):
        self.assertIn("fx-title-flow 3s", self.css)

    def test_gradient_starts_after_the_glitch(self):
        """Иначе перетекание и дёрганье накладываются друг на друга."""
        self.assertIn("fx-title-flow 3s linear .25s", self.css)

    def test_title_carries_its_text_for_the_twins(self):
        self.assertIn("content:attr(data-text)", self.css)
        self.assertIn("dataset.text", self.settings)


class TestSubtitle(Base):
    """1.3: блик по строке под названием и искры."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (CSS / "subtitle.css").read_text(encoding="utf-8")
        cls.js = (JS / "subtitle.js").read_text(encoding="utf-8")

    def test_sweep_runs_over_the_letters(self):
        """Подсветка прямоугольником поверх строки выглядела бы наклейкой."""
        self.assertIn("background-clip:text", self.css)
        self.assertIn("@keyframes fx-subtitle-sweep", self.css)

    def test_sweep_lasts_six_tenths(self):
        self.assertIn("fx-subtitle-sweep .6s", self.css)

    def test_sparks_are_small_and_purple(self):
        self.assertIn("width:2px", self.css)
        self.assertIn("#c084fc", self.js)

    def test_sparks_do_not_catch_clicks(self):
        block = self.css[self.css.index(".fx-subtitle .spark{"):]
        self.assertIn("pointer-events:none", block[:block.index("}")])

    def test_a_dozen_at_most(self):
        self.assertIn("SPARK_MIN = 8", self.js)
        self.assertIn("SPARK_MAX = 12", self.js)

    def test_once_per_hover_not_in_a_stream(self):
        """Непрерывный фонтанчик мельтешит и тянет взгляд на себя."""
        self.assertIn("if(inside || !sparksOn()) return", self.js)
        self.assertIn("mouseleave", self.js)

    def test_sparks_are_removed_afterwards(self):
        """Иначе за вечер в теле страницы накопятся тысячи точек."""
        self.assertIn("spark.remove()", self.js)


class TestStars(Base):
    """3.2: звёздное поле с параллаксом."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (CSS / "stars.css").read_text(encoding="utf-8")
        cls.js = (JS / "stars.js").read_text(encoding="utf-8")

    def test_count_is_from_the_spec(self):
        self.assertIn("STARS_MIN = 120", self.js)
        self.assertIn("STARS_MAX = 180", self.js)

    def test_no_twinkling(self):
        """Мельтешение на фоне отвлекает от текста."""
        self.assertNotIn("@keyframes", self.css)
        self.assertNotIn("animation", self.css)

    def test_parallax_is_gentle(self):
        """На тысяче пикселей прокрутки это несколько десятков."""
        self.assertIn("STARS_PARALLAX = 0.035", self.js)

    def test_moved_by_transform_not_by_top(self):
        self.assertIn("translate3d(0,", self.js)
        self.assertNotIn("style.top =", self.js.split("function paint")[1])

    def test_recomputed_once_per_frame(self):
        self.assertIn("requestAnimationFrame(paint)", self.js)

    def test_placed_once_and_not_reshuffled(self):
        """Звёзды, прыгающие при прокрутке, выглядят поломкой."""
        self.assertIn("if(layer) return layer", self.js)

    def test_layer_is_behind_and_deaf(self):
        block = self.css[self.css.index(".fx-stars .starfield{"):]
        block = block[:block.index("}")]
        self.assertIn("z-index:-1", block)
        self.assertIn("pointer-events:none", block)

    def test_every_tenth_is_violet(self):
        self.assertIn("STARS_VIOLET = 10", self.js)
        self.assertIn(".violet", self.css)


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


class TestRemovedEffects(Base):
    """3.1: неприжившиеся эффекты убраны, а не просто выключены."""

    GONE = ("aurora", "grain", "spotlight", "cursor")

    def test_files_are_deleted(self):
        for name in self.GONE:
            self.assertFalse((CSS / f"{name}.css").exists(), name)

    def test_not_in_the_registry(self):
        for name in self.GONE:
            self.assertNotIn(f"key: '{name}'", self.settings, name)

    def test_not_linked_from_the_page(self):
        for name in self.GONE:
            self.assertNotIn(f"effects/{name}.css", self.html, name)

    def test_no_dead_code_left(self):
        """Мёртвый код хуже отсутствующего — он выглядит рабочим."""
        pointer = (JS / "pointer.js").read_text(encoding="utf-8")
        for mark in ("fxSpotlight", "--mx", "fx-away"):
            self.assertNotIn(mark, pointer, mark)

    def test_the_rest_survived(self):
        stayed = ("title-glitch", "button-press", "progress-life", "done-flash",
                  "counter", "skeleton", "magnetic", "row-sweep", "tab-grow",
                  "static-cards")
        for name in stayed:
            self.assertIn(f"key: '{name}'", self.settings, name)


class TestMagnetic(Base):
    """6.4: магнитные кнопки остаются."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = (JS / "pointer.js").read_text(encoding="utf-8")

    def test_pull_is_small(self):
        self.assertIn("FX_MAGNET = 4", self.js)

    def test_vertical_pull_is_smaller(self):
        """Кнопки верхней панели стоят вплотную к краю строки."""
        self.assertIn("FX_MAGNET_Y = 3", self.js)

    def test_small_buttons_are_skipped(self):
        self.assertIn("FX_MAGNET_MIN", self.js)

    def test_returns_with_a_spring(self):
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
