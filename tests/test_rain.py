"""Дождь глифов под карточкой скачивания.

Эффект не декоративный: плотность струй — это ответ на вопрос «сколько
потоков сейчас работает». Поэтому проверяется здесь не «красиво ли», а
связь дождя с прогоном: откуда он берёт числа, что делает на паузе, на
ошибке и в конце, и что он не залезает ни на текст карточки, ни на
звёздное поле.

Числа-настройки нарочно не закрепляются: скорость струи, длина хвоста и
порог «полной загрузки» — вещи, которые будут крутиться на глаз. Тест,
знающий их наизусть, ломается от каждой такой правки и ничего при этом
не ловит.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (STATIC / "js" / "effects" / "rain.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "css" / "effects" / "rain.css").read_text(encoding="utf-8")
        cls.settings = (STATIC / "js" / "effects" / "settings.js").read_text(
            encoding="utf-8")
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")

    def body(self, name: str) -> str:
        """Тело функции по имени — от заголовка до строки закрытия."""
        start = self.js.index(f"function {name}(")
        rest = self.js[start:]
        # Функции верхнего уровня внутри модуля закрываются двумя
        # пробелами и скобкой; этого достаточно, чтобы не хватать соседей.
        end = rest.index("\n  }\n")
        return rest[:end]


class TestDensityFollowsThreads(Base):
    """Главное свойство: струй столько, сколько живых потоков."""

    def test_density_is_computed_from_the_thread_count(self):
        block = self.body("want")
        self.assertRegex(block, r"live\.threads\s*/\s*RAIN_FULL")
        self.assertIn("cols", block)

    def test_full_load_is_a_believable_number_of_threads(self):
        """Полная загрузка должна быть достижимой, иначе стены не увидеть."""
        full = int(re.search(r"const RAIN_FULL = (\d+);", self.js).group(1))
        self.assertGreaterEqual(full, 2)
        self.assertLessEqual(full, 32)

    def test_share_never_runs_past_a_full_wall(self):
        """Потоков попросили больше, чем полная загрузка — стена остаётся стеной."""
        self.assertIn("Math.min(1,", self.body("want"))

    def test_work_without_threads_still_shows_something(self):
        """Идёт поиск книги: потоков нет, но работа началась."""
        block = self.body("want")
        self.assertIn("RAIN_LEAST", block)
        self.assertRegex(block, r"if\(!live\.threads\)")

    def test_no_work_means_no_rain(self):
        self.assertRegex(self.body("want"), r"if\(!live\.busy")

    def test_streams_come_and_go_one_by_one(self):
        """Пачкой появившиеся струи читаются как мигание, а не как дождь."""
        block = self.body("balance")
        self.assertIn("leaving", block)

    def test_two_streams_never_share_a_column(self):
        self.assertIn("function freeCol(", self.js)
        self.assertIn("freeCol()", self.body("balance"))


class TestItSaysWhatTheRunIsDoing(Base):
    """Пауза, ошибка и конец прогона видны в дожде."""

    def test_pause_freezes_the_rain(self):
        """Причём не считая кадров: пауза может тянуться сколько угодно,
        а картинка при ней не меняется."""
        block = self.body("frame")
        self.assertRegex(block, r"if\(live\.held\)\{")
        self.assertIn("stop();", block)

    def test_resuming_starts_the_frames_again(self):
        tune = self.js[self.js.index("window.rainTune = "):]
        self.assertIn("start();", tune[:tune.index("};")])

    def test_pause_dims_but_does_not_erase(self):
        """Работа стоит, но не кончена — дождь должен остаться на экране."""
        self.assertIn("RAIN_HELD_DIM", self.js)
        dim = float(re.search(r"const RAIN_HELD_DIM = ([\d.]+);", self.js).group(1))
        self.assertGreater(dim, 0)
        self.assertLess(dim, 1)

    def test_a_failed_chapter_paints_a_stream(self):
        block = self.body("markFails")
        self.assertIn("live.failed", block)
        self.assertIn("RAIN_FAIL_LIFE", block)

    def test_one_bad_chapter_does_not_paint_the_whole_card_red(self):
        self.assertIn("RAIN_FAIL_MAX", self.body("markFails"))
        most = int(re.search(r"const RAIN_FAIL_MAX = (\d+);", self.js).group(1))
        self.assertLessEqual(most, 5)

    def test_a_new_run_resets_the_error_count(self):
        """Счётчик ошибок начинается с нуля — краснеть заново нечему."""
        self.assertRegex(self.body("markFails"),
                         r"if\(live\.failed <= seenFailed\)")

    def test_the_end_fades_instead_of_cutting_off(self):
        block = self.body("fade")
        self.assertIn("opacity", block)
        self.assertIn("transition:opacity", self.css.replace(" ", ""))

    def test_a_run_started_during_the_fade_keeps_the_rain(self):
        self.assertRegex(self.body("fade"), r"if\(live\.busy\) return;")


class TestItDoesNotFightTheRestOfTheScreen(Base):
    """Текст карточки и звёздное поле дождь трогать не должен."""

    def test_the_card_content_stays_above_the_rain(self):
        rule = ".fx-rain #progress > *:not(.glyphrain)"
        self.assertIn(rule, self.css)
        block = self.css[self.css.index(rule):]
        block = block[:block.index("}")]
        self.assertIn("z-index:1", block.replace(" ", ""))

    def test_the_canvas_is_opaque_so_the_stars_do_not_show_through(self):
        """Панель полупрозрачна: без сплошной подложки два поля в одних
        пикселях. Заливка при первом кадре идёт без прозрачности."""
        self.assertRegex(self.js, r"fillStyle = 'rgb\(' \+ RAIN_BASE \+ '\)'")

    def test_the_stars_were_not_touched(self):
        stars = (STATIC / "js" / "effects" / "stars.js").read_text(encoding="utf-8")
        self.assertNotIn("rain", stars.lower())

    def test_the_rain_stays_inside_the_card(self):
        self.assertIn("overflow:hidden", self.css.replace(" ", ""))
        self.assertIn("position:absolute", self.css.replace(" ", ""))

    def test_the_rain_never_catches_clicks(self):
        self.assertIn("pointer-events:none", self.css.replace(" ", ""))

    def test_the_corners_of_the_card_survive(self):
        """Холст непрозрачен и лежал вплотную к краю: чёрный квадрат
        закрашивал фиолетовую линию изнутри, и нижние углы карточки
        выглядели обкусанными. Обрезки родителем тут мало — карточка
        размывает фон, а это отдельный слой, где `overflow` на
        скруглённых углах работает не везде."""
        flat = self.css.replace(" ", "")
        self.assertIn("border-radius:", flat[flat.index(".glyphrain{"):])
        self.assertRegex(flat, r"inset:[1-9]")

    def test_the_canvas_is_told_its_size_and_not_left_to_guess(self):
        """Холст — замещаемый элемент: у него есть собственный размер
        (300×150 по умолчанию), и четырьмя нулями по краям он не
        растягивается, в отличие от обычного блока. Без явного размера
        дождь идёт прямоугольником в левом верхнем углу карточки."""
        flat = self.css.replace(" ", "")
        block = flat[flat.index(".glyphrain{"):]
        block = block[:block.index("}")]
        self.assertIn("width:", block)
        self.assertIn("height:", block)

    def test_the_canvas_measures_itself_not_the_card(self):
        """Карточка на две рамки шире холста: посчитав по ней, дождь
        рисует на два пикселя больше, чем есть места."""
        block = self.body("resize")
        self.assertIn("canvas.getBoundingClientRect()", block)


class TestItCostsNothingWhenOff(Base):
    """Выключенный эффект не должен ни считать, ни рисовать."""

    def test_it_is_off_by_default(self):
        block = self.settings[self.settings.index("key: 'rain'"):]
        block = block[:block.index("},")]
        self.assertIn("on: false", block)

    def test_the_switch_exists_and_explains_itself(self):
        block = self.settings[self.settings.index("key: 'rain'"):]
        block = block[:block.index("},")]
        self.assertIn("hint:", block)
        self.assertIn("поток", block)

    def test_unchecking_stops_the_frames(self):
        watch = self.js[self.js.index("const watch = new MutationObserver"):]
        self.assertIn("stop()", watch)
        self.assertIn("hidden = true", watch)

    def test_a_hidden_tab_stops_the_frames(self):
        block = self.js[self.js.index("visibilitychange"):]
        block = block[:block.index("});")]
        self.assertIn("stop()", block)

    def test_reduced_motion_turns_it_off_entirely(self):
        """У звёзд остаётся мерцание, здесь движение и есть весь эффект."""
        self.assertIn("prefers-reduced-motion", self.js)
        self.assertIn("rainCalm()", self.body("start"))


class TestItIsWiredToTheDownloader(Base):
    """Числа приходят из прогона, а не из собственного опроса."""

    def test_the_poll_tells_the_rain_what_is_happening(self):
        block = self.html[self.html.index("if(window.rainTune) rainTune({"):]
        block = block[:block.index("});")]
        for field in ("busy", "held", "threads", "failed"):
            self.assertIn(field, block)

    def test_the_rain_asks_the_server_nothing(self):
        """Эффекту нечего знать про задачи, запросы и ответы."""
        for word in ("fetch(", "/api/", "XMLHttpRequest"):
            self.assertNotIn(word, self.js)

    def test_the_thread_number_is_the_same_one_the_card_prints(self):
        """Строка «3 потока» и плотность дождя должны врать одинаково
        или не врать вовсе — источник у них один."""
        block = self.html[self.html.index("$('sMethod').textContent = many"):]
        self.assertIn("p.threads", block[:400])
        tune = self.html[self.html.index("if(window.rainTune) rainTune({"):]
        self.assertIn("p.threads", tune[:400])

    def test_starting_a_new_book_clears_the_old_rain(self):
        block = self.html[self.html.index("function reset(){"):]
        block = block[:block.index("\n}")]
        self.assertIn("rainTune", block)
        self.assertIn("busy: false", block)

    def test_the_files_are_loaded_by_the_page(self):
        self.assertIn("/static/js/effects/rain.js", self.html)
        self.assertIn("/static/css/effects/rain.css", self.html)


class TestTheRainEndsWhenTheWorkDoes(Base):
    """Дождь идёт, пока идёт работа. Всё остальное — враньё экрана.

    Жалоба была ровно такая: нажали «Остановить», а дождь льёт как лил,
    и понять, качает оно ещё или уже нет, невозможно.
    """

    def tick(self) -> str:
        block = self.html[self.html.index("async function tick(){"):]
        return block[:block.index("\nasync function stop(){")]

    def test_asking_to_stop_thins_the_rain_at_once(self):
        """Сервер до конца остановки честно отвечает «качаем»: главы
        дописываются. Но новых потоков уже нет, и стена струй в этот
        момент показывает работу, которой не будет."""
        tune = self.tick()[self.tick().index("rainTune({"):]
        tune = tune[:tune.index("});")]
        self.assertIn("stopping", tune)

    def test_the_stop_button_raises_that_flag(self):
        block = self.html[self.html.index("async function stop(){"):]
        block = block[:block.index("\n}")]
        self.assertRegex(block, r"stopping\s*=\s*true")

    def test_a_new_run_lowers_it_again(self):
        """Иначе следующее скачивание пойдёт с дождём в две струи."""
        self.assertRegex(self.html, r"stopping\s*=\s*false")
        block = self.html[self.html.index("function reset(){"):]
        self.assertRegex(block[:block.index("\n}")], r"stopping\s*=\s*false")

    def test_a_broken_poll_does_not_leave_the_rain_running(self):
        """Опрос оборвался — рассказывать дождю о конце работы больше
        некому, и он идёт до перезагрузки страницы."""
        block = self.tick()
        tail = block[block.rindex("}catch(err){"):]
        self.assertIn("rainTune", tail)
        self.assertIn("busy: false", tail)


class TestItCanBeCheckedFromOutside(Base):
    """Холст наружу ничего не показывает — нужен слепок состояния."""

    def test_a_snapshot_is_published(self):
        self.assertIn("window.glyphrainState = ", self.js)

    def test_the_snapshot_says_how_many_streams_against_how_many_wanted(self):
        block = self.js[self.js.index("window.glyphrainState = "):]
        block = block[:block.index("});")]
        for field in ("want", "count", "threads", "held", "running"):
            self.assertIn(field, block)

    def test_the_snapshot_is_a_copy_and_not_the_streams_themselves(self):
        """Через слепок ничего не должно меняться."""
        block = self.js[self.js.index("window.glyphrainState = "):]
        block = block[:block.index("});")]
        self.assertIn("streams.map(", block)
        self.assertNotIn("streams:", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
