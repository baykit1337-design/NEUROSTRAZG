"""Оформление: эффекты и их выключатели (часть 6 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import re
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

    def test_the_panel_says_what_the_system_setting_did(self):
        """Замершее поле без пояснения не отличить от поломки (4.1 ТЗ)."""
        self.assertIn("В системе включено «уменьшить движение»", self.settings)
        self.assertIn("продолжает мерцать, но никуда не движется",
                      self.settings)

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
    """Часть 5: живое звёздное поле.

    Точки раньше стояли намертво и двигались только при прокрутке — небо
    от этого выглядело нарисованным.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (CSS / "stars.css").read_text(encoding="utf-8")
        cls.js = (JS / "stars.js").read_text(encoding="utf-8")

    def test_count_is_from_the_spec(self):
        self.assertIn("STARS_MIN = 120", self.js)
        self.assertIn("STARS_MAX = 180", self.js)

    def test_three_depths_with_the_shares_from_the_spec(self):
        block = self.js.split("STARS_DEPTHS = [", 1)[1].split("];", 1)[0]
        self.assertEqual(block.count("share:"), 3)
        for share in ("0.60", "0.30", "0.10"):
            with self.subTest(share=share):
                self.assertIn(f"share: {share}", block)

    def test_each_depth_has_its_own_brightness_and_size(self):
        """Группы различаются яркостью в пике и размером точки."""
        rows = self._depths()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({self._value(r, "bright") for r in rows}), 3)
        self.assertEqual(len({self._value(r, "size") for r in rows}), 3)

    def test_a_star_fades_all_the_way_out(self):
        """Затухание должно доводить точку до невидимости.

        С ненулевой нижней границей она тускнела, но оставалась на месте
        светлым пятном, и «затухание» читалось как перепад яркости, а не
        как исчезновение.
        """
        for row in self._depths():
            with self.subTest(row=row.strip()):
                self.assertEqual(self._value(row, "dim"), 0.0, row)

    def _depths(self) -> list:
        block = self.js.split("STARS_DEPTHS = [", 1)[1].split("];", 1)[0]
        return [line for line in block.splitlines() if "share:" in line]

    @staticmethod
    def _value(row: str, key: str) -> float:
        import re as _re

        found = _re.search(rf"{key}:\s*([\d.]+)", row)
        return float(found.group(1))

    def test_the_nearest_ones_glow(self):
        block = self.js.split("STARS_DEPTHS = [", 1)[1].split("];", 1)[0]
        self.assertEqual(block.count("glow: true"), 1)

    def test_twinkling_stays_slow(self):
        """Короткий цикл превращает фон в гирлянду.

        Ускорять мерцание нельзя: быстрое мигание отвлекает от текста,
        ради которого программа и написана. Заметность даёт не скорость,
        а полное затухание — см. соседнюю проверку.
        """
        self.assertIn("STARS_BLINK_MIN = 4000", self.js)
        self.assertIn("STARS_BLINK_MAX = 12000", self.js)

    def test_every_star_blinks_on_its_own(self):
        """Иначе точки мигают хором, и это читается как поломка."""
        self.assertIn("phase: Math.random() * Math.PI * 2", self.js)
        self.assertIn("cycle: starsBetween(STARS_BLINK_MIN, STARS_BLINK_MAX)",
                      self.js)

    def test_a_star_moves_every_six_to_ten_seconds(self):
        """Переезд — редкое событие: это фон, а не рябь."""
        self.assertIn("STARS_MOVE_MIN = 6000", self.js)
        self.assertIn("STARS_MOVE_MAX = 10000", self.js)

    def test_fading_in_and_out_stays_gradual(self):
        """Точка гаснет и зажигается плавно, а не мигает на кадр."""
        self.assertIn("STARS_FADE_MIN = 2000", self.js)
        self.assertIn("STARS_FADE_MAX = 3000", self.js)

    def test_no_more_than_three_move_at_once(self):
        self.assertIn("STARS_MOVING_MAX = 3", self.js)
        self.assertIn("if(busy >= STARS_MOVING_MAX) return;", self.js)

    def test_a_new_spot_is_not_next_to_a_neighbour(self):
        """Иначе точки собираются в кучки."""
        self.assertIn("STARS_APART = 40", self.js)
        self.assertIn("< STARS_APART", self.js)

    def test_the_whole_field_drifts_by_itself(self):
        """Скорость подбирается на глаз и меняется — важно, что она есть.

        Прежний вариант был прибит к числу, и правка скорости роняла
        тест, хотя дрейф никуда не девался.
        """
        found = re.search(r"STARS_DRIFT = ([\d.]+)", self.js)
        self.assertIsNotNone(found, "дрейфа нет вовсе")
        self.assertGreater(float(found.group(1)), 0)
        self.assertIn("driftAngle", self.js)

    def test_the_drift_is_visible_within_a_run(self):
        """Полтора пикселя в минуту — семь пикселей за прогон книги.

        Это неподвижное поле: снаружи не отличить от застывшего.
        """
        found = re.search(r"STARS_DRIFT = ([\d.]+)", self.js)
        self.assertGreaterEqual(float(found.group(1)), 5)

    def test_the_drift_turns_now_and_then(self):
        self.assertIn("STARS_TURN_MIN = 120000", self.js)
        self.assertIn("if(now >= turnAt)", self.js)

    def test_drift_is_counted_in_pixels_per_minute(self):
        self.assertIn("STARS_DRIFT * (elapsed / 60000)", self.js)

    def test_parallax_is_gentle_and_deeper_for_the_near_ones(self):
        self.assertIn("STARS_PARALLAX = 0.02", self.js)
        self.assertIn("STARS_PARALLAX_DEPTH = 3", self.js)
        self.assertIn("star.depth * (STARS_PARALLAX_DEPTH - 1)", self.js)

    def test_the_whole_field_is_one_canvas(self):
        """Полторы сотни анимированных элементов дороже всей страницы."""
        self.assertIn("createElement('canvas')", self.js)
        self.assertIn("getContext('2d')", self.js)

    def test_drawing_happens_once_per_frame(self):
        self.assertIn("requestAnimationFrame(frame)", self.js)

    def test_an_inactive_tab_stops_the_animation(self):
        self.assertIn("visibilitychange", self.js)
        self.assertIn("if(document.hidden) stop();", self.js)

    def test_calm_mode_moves_nothing(self):
        """Системное «уменьшить движение» останавливает перемещения.

        Раньше оно останавливало вообще всё: поле рисовало один кадр и
        замирало — та самая статичная картинка из 4.1 ТЗ. Настройка,
        однако, про перемещение, а не про яркость.
        """
        self.assertIn("if(calm) return;", self.js)
        self.assertIn("const scroll = calm ? 0 : (window.scrollY || 0);",
                      self.js)

    def test_calm_mode_still_lets_the_field_twinkle(self):
        """Цикл кадров при тихом режиме больше не обрывается."""
        self.assertNotIn("if(starsCalm()){ paint(performance.now()); return; }",
                         self.js)
        start = self.js.split("function start(){", 1)[1].split("\n  }", 1)[0]
        self.assertIn("requestAnimationFrame(frame)", start)
        self.assertNotIn("starsCalm()", start)

    def test_the_system_setting_is_read_once_not_every_frame(self):
        """matchMedia шестьдесят раз в секунду — работа на ровном месте."""
        self.assertIn("let calm = starsCalm();", self.js)
        self.assertIn("addEventListener('change', noted)", self.js)

    def test_a_changed_setting_is_picked_up_without_a_reload(self):
        self.assertIn("calm = watchCalm.matches;", self.js)

    def test_the_old_way_of_watching_the_setting_also_works(self):
        """Safari до 14 знает только addListener."""
        self.assertIn("watchCalm.addListener(noted)", self.js)

    def test_the_field_says_what_it_is_doing(self):
        """Поле на холсте: снаружи не видно ни точек, ни того, идёт ли цикл.

        Дрейф здесь полтора пикселя в минуту — работающее поле от
        застывшего на глаз не отличить, и проверить 4.1 без слепка нечем.
        """
        self.assertIn("window.starfieldState = () => ({", self.js)
        for field in ("running,", "calm,", "frames,", "driftX, driftY"):
            with self.subTest(field=field):
                self.assertIn(field, self.js)

    def test_the_frame_counter_grows_where_frames_are_drawn(self):
        """Иначе по слепку не отличить «идёт» от «встало после первого»."""
        frame = self.js.split("function frame(now){", 1)[1].split("\n  }", 1)[0]
        self.assertIn("frames++;", frame)

    def test_the_snapshot_is_a_copy_not_the_stars_themselves(self):
        """Через слепок менять нечего: он только для чтения."""
        self.assertIn("stars: stars.map(star => ({", self.js)

    def test_the_layer_is_behind_and_deaf(self):
        block = self.css[self.css.index(".fx-stars .starfield{"):]
        block = block[:block.index("}")]
        self.assertIn("z-index:-1", block)
        self.assertIn("pointer-events:none", block)

    def test_the_field_reaches_above_the_screen(self):
        """При прокрутке снизу не должно появляться пустоты."""
        self.assertIn("STARS_MARGIN = 0.3", self.js)

    def test_every_tenth_is_violet(self):
        self.assertIn("STARS_VIOLET = 10", self.js)
        self.assertIn("STARS_LILAC", self.js)

    def test_unchecking_the_box_stops_the_work(self):
        """Погашенное поле не должно продолжать считать кадры."""
        self.assertIn("else{\n      stop();", self.js)


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

    def test_ordinary_buttons_are_not_skipped(self):
        """Порог отсекал всё уже девяноста пикселей, а такой ширины у
        нас «Найти», «Пауза», «скачать» в строке рейтинга и все кнопки
        форматов. Половина кнопок программы стояла мёртвой, и со
        стороны это читалось как поломка, а не как замысел."""
        least = int(re.search(r"FX_MAGNET_MIN = (\d+)", self.js).group(1))
        # Кнопка с коротким словом — это примерно шестьдесят пикселей.
        self.assertLess(least, 60)

    def test_a_small_button_is_pulled_less_than_a_wide_one(self):
        """Отменить порог, оставив всем одну силу, нельзя: четыре
        пикселя у кнопки в сорок пикселей — это десятая часть её
        ширины, и она уезжает с места."""
        block = self.js[self.js.index("function fxPull("):]
        block = block[:block.index("\n}")]
        self.assertIn("width", block)
        self.assertIn("FX_MAGNET", block)

    def test_the_pull_never_runs_past_the_old_limit(self):
        """Крупные кнопки тянутся ровно как тянулись."""
        block = self.js[self.js.index("function fxPull("):]
        self.assertRegex(block[:200], r"Math\.min\(FX_MAGNET\b")

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

    def test_every_muted_class_of_the_page_lights_up(self):
        """Разгорались три класса из десятка, и в одной карточке
        половина текста откликалась, а половина нет — строка книги под
        названием, путь к папке, «здесь пусто». Это заметнее, чем если
        бы эффекта не было вовсе."""
        css = (CSS / "static-cards.css").read_text(encoding="utf-8")
        lit = css[css.index(":hover"):]
        # Правила вида «.что-то { … color:var(--muted) … }» — один класс
        # и никаких вложений: составные разбирать незачем, они и так
        # попадают внутрь карточки через свой корневой класс.
        classes = {
            found.group(1)
            for found in re.finditer(r"\n\s*\.([a-z-]+)\{([^}]*)\}",
                                     self.html, re.S)
            if "color:var(--muted)" in found.group(2).replace(" ", "")
        }
        # Приглушённое, но не про карточки: строки таблицы рейтинга,
        # стрелка раскрытия, подзаголовки выпадающих списков.
        skip = {"num", "arrow", "place", "flat", "said", "formats", "dirs"}
        # Разъедется разбор — список опустеет, и проверка станет пустой.
        self.assertGreater(len(classes - skip), 5)
        for name in sorted(classes - skip):
            with self.subTest(name):
                self.assertIn("." + name, lit)

    def test_the_light_comes_on_smoothly(self):
        """Без перехода текст меняет цвет рывком, и это читается как
        подёргивание, а не как отклик."""
        css = (CSS / "static-cards.css").read_text(encoding="utf-8")
        self.assertIn("transition:color", css.replace(" ", ""))

    def test_the_step_is_big_enough_to_notice(self):
        """#8f8aa3 → #a9a4b8 глазом не ловится: разница меньше, чем
        разброс подсветки экрана."""
        css = (CSS / "static-cards.css").read_text(encoding="utf-8")
        muted = re.search(r"--muted:#([0-9a-f]{6})", self.html).group(1)
        was = int(muted[0:2], 16) + int(muted[2:4], 16) + int(muted[4:6], 16)
        for hit in re.findall(r"color:#([0-9a-f]{6})", css):
            now = int(hit[0:2], 16) + int(hit[2:4], 16) + int(hit[4:6], 16)
            self.assertGreater(now, was + 60, f"#{hit} едва отличим от #{muted}")


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


class TestEveryScriptIsLinkedToo(Base):
    """Правило про файлы стилей молчало про скрипты.

    Эффект, у которого вся суть в скрипте, файлом стилей не проверяется:
    забытый `<script>` даёт ровно то же, что снятая галочка, — тишину.
    Отличить это от «эффект просто не нравится» нечем.
    """

    def test_scripts_are_linked(self):
        for path in JS.glob("*.js"):
            self.assertIn(f"/static/js/effects/{path.name}", self.html,
                          path.name)


class TestTheNewFiveDoNotTouchTheTabs(Base):
    """Переезд строк, живые обложки, перелёт, подсветка и встряска.

    Общее у всех пяти одно: вкладка «Рейтинг» о них не знает. Эффект,
    ради которого пришлось бы править саму вкладку, снимался бы галочкой
    только наполовину — а половина снятого эффекта хуже включённого.
    """

    NEW = ("rank-move", "cover-lift", "card-open", "find-hit", "error-shake")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")
        cls.code = {path.stem: path.read_text(encoding="utf-8")
                    for path in JS.glob("*.js")}

    def test_all_five_are_in_the_registry(self):
        for key in self.NEW:
            self.assertIn(f"key: '{key}'", self.settings, key)

    def test_the_tabs_know_nothing_about_them(self):
        for key in self.NEW:
            self.assertNotIn("fx-" + key, self.tabs, key)

    def test_the_row_is_found_by_a_mark_that_already_existed(self):
        """Своя метка на строке — это правка вкладки. Карточка книги уже
        несёт `data-book` и лежит сразу за строкой; по ней и опознаём."""
        self.assertIn("data-book", self.code["rankmove"])
        self.assertIn("nextElementSibling", self.code["rankmove"])

    def test_every_new_script_checks_its_own_switch(self):
        for name in ("rankmove", "covers", "findhit", "errorshake"):
            self.assertIn("classList.contains('fx-", self.code[name], name)


class TestTheHighlightIsBuiltFromNodes(Base):
    """Название приходит с чужого сайта.

    Склей мы из него разметку строкой — китайская книга с угловой скобкой
    в заголовке превратилась бы в чужой тег прямо в списке.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.code = (JS / "findhit.js").read_text(encoding="utf-8")

    def test_no_markup_is_glued_from_strings(self):
        self.assertNotIn("innerHTML", self.code)

    def test_the_highlight_can_be_taken_off(self):
        """Снятая галочка список не перерисовывает — метки надо снять
        самим, иначе эффект выглядит невыключаемым."""
        self.assertIn("hitClear", self.code)


class TestTheFlightIsADouble(Base):
    """Летит двойник обложки, а не она сама.

    Подвинь мы настоящую миниатюру — строка осталась бы дырявой, если
    карточка почему-либо не откроется.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.code = (JS / "covers.js").read_text(encoding="utf-8")

    def test_a_copy_is_made(self):
        self.assertIn("createElement('img')", self.code)

    def test_the_double_takes_itself_away(self):
        self.assertIn("ghost.remove()", self.code)

    def test_a_late_flight_is_skipped(self):
        """Обложка, взлетевшая через пять секунд после нажатия, читается
        не как продолжение нажатия, а как сбой."""
        self.assertIn("COV_TOO_LATE_MS", self.code)


class TestTheShakeRunsOnEveryRefusal(Base):
    """Главный случай — второе нажатие той же кнопки.

    Текст тот же, блок тот же. Не перезапусти мы анимацию, повторная
    ошибка прошла бы беззвучно — ровно там, где заметность нужнее всего.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.code = (JS / "errorshake.js").read_text(encoding="utf-8")

    def test_the_animation_is_restarted_by_hand(self):
        self.assertIn("offsetHeight", self.code)

    def test_it_hangs_on_the_call_not_on_the_box_appearing(self):
        """Появление можно поймать и стилями, повтор — нет."""
        self.assertIn("showError", self.code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
