"""Страница целиком: открывается, вкладки работают, ошибок в консоли нет.

Три тысячи тестов — все на Python. Страница же, а это семь тысяч строк
скрипта и пять тысяч разметки, проверялась только глазами: сломанный
`id`, опечатка в имени функции или обращение к тому, чего ещё нет, до сих
пор ловились наощупь.

Здесь ровно то, что глазами и проверяют: открылась ли страница, не
ругается ли консоль, открываются ли все вкладки, ведёт ли кнопка ошибки к
отчёту. Тонкие сценарии сюда не нужны — их дешевле проверять на сервере.

Без Playwright и без браузера тесты пропускаются: на машине, где
программой пользуются, их ставить незачем.
"""

from __future__ import annotations

import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover — обычная машина без браузера
    sync_playwright = None
    PlaywrightError = Exception

#: Браузер, поставленный рядом с окружением. Нет его — Playwright ищет
#: свой; нет и того — тесты пропускаются.
CHROMIUM = Path("/opt/pw-browsers/chromium")

#: Файлы страницы. Пара проверок ниже смотрит в сам стиль: правило,
#: которое обязано чего-то НЕ делать, в браузере не увидишь никак.
STATIC = Path(__file__).resolve().parent.parent / "webapp" / "static"

#: Вкладки в том же порядке, что и в шапке.
TABS = ("download", "rank", "library", "split", "merge", "convert",
        "format", "rename", "check", "analyze", "tools", "looks")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipIf(sync_playwright is None, "Playwright не установлен")
class PageTestCase(unittest.TestCase):
    """Поднимает сервер и браузер один раз на весь класс: запуск того и
    другого стоит секунды, а проверок много."""

    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server

        from webapp.app import app

        app.config["TESTING"] = True
        cls.port = free_port()
        cls.server = make_server("127.0.0.1", cls.port, app, threaded=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.home = f"http://127.0.0.1:{cls.port}/"

        cls.play = sync_playwright().start()
        where = {"executable_path": str(CHROMIUM)} if CHROMIUM.exists() else {}
        try:
            cls.browser = cls.play.chromium.launch(**where)
        except PlaywrightError as exc:  # pragma: no cover — нет браузера
            cls.play.stop()
            cls.server.shutdown()
            raise unittest.SkipTest(f"браузер не запустился: {exc}") from exc

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.play.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.trouble: list[str] = []
        self.page.on("pageerror", lambda err: self.trouble.append(str(err)))
        self.page.on("console", self.heard)
        self.page.goto(self.home, wait_until="networkidle")

    def heard(self, msg):
        """Ошибка в консоли — но не всякая красная строка ею является.

        Отказ нашего же маршрута (400 на заведомо неверный путь) браузер
        пишет как «Failed to load resource». Это ожидаемый ответ, а не
        поломка страницы: считать его ошибкой значит запретить себе
        проверять отказы.
        """
        if msg.type != "error":
            return
        if msg.text.startswith("Failed to load resource"):
            return
        self.trouble.append(msg.text)

    def quiet(self):
        """Ни одной ошибки в консоли — иначе видно, какая именно."""
        self.assertEqual(self.trouble, [])


class TestItOpens(PageTestCase):
    def test_the_page_loads_without_a_single_error(self):
        self.quiet()

    def test_the_title_is_the_program(self):
        self.assertIn("NEUROSTRAZH", self.page.title().upper())

    def test_every_tab_opens(self):
        """Двенадцать вкладок, и каждая — свой кусок скрипта."""
        for name in TABS:
            with self.subTest(name):
                self.page.click(f'.tabs button[data-tab="{name}"]')
                self.page.wait_for_timeout(60)
                self.assertFalse(self.page.locator(f"#tab-{name}").is_hidden())
        self.quiet()

    def test_only_one_tab_is_visible_at_a_time(self):
        self.page.click('.tabs button[data-tab="split"]')
        self.page.wait_for_timeout(60)
        shown = self.page.locator('section[id^="tab-"]:not([hidden])')
        self.assertEqual(shown.count(), 1)


class TestNamesDoNotCollide(PageTestCase):
    """`index.html` и `tabs.js` делят один документ и одну область имён.

    Повторённый `id` не ругается ни в браузере, ни при сборке: просто
    вторая карточка молча живёт своей жизнью, а `$('...')` находит первую.
    На этом здесь спотыкались не раз.
    """

    def test_no_id_is_used_twice(self):
        twice = self.page.evaluate("""() => {
          const seen = {}, bad = [];
          for(const el of document.querySelectorAll('[id]')){
            if(seen[el.id]) bad.push(el.id); else seen[el.id] = 1;
          }
          return bad;
        }""")
        self.assertEqual(twice, [])

    def test_every_tab_button_has_its_section(self):
        missing = [name for name in TABS
                   if self.page.locator(f"#tab-{name}").count() != 1]
        self.assertEqual(missing, [])


class TestAnErrorLeadsToTheReport(PageTestCase):
    """Когда что-то ломается, человек на той вкладке, где сломалось, а
    отчёт — в «Инструментах»."""

    def show_an_error(self):
        self.page.click('.tabs button[data-tab="check"]')
        self.page.wait_for_timeout(80)
        self.page.click("#ckStart")
        self.page.wait_for_timeout(300)

    def test_the_message_appears(self):
        self.show_an_error()
        box = self.page.locator(".err:not([hidden])").first
        self.assertTrue(box.count())
        self.assertIn("выберите", box.inner_text().lower())

    def test_the_message_carries_a_report_button(self):
        self.show_an_error()
        self.assertTrue(
            self.page.get_by_role("button", name="Отчёт о проблеме").count())

    def test_the_button_opens_the_report_and_fills_it_in(self):
        self.show_an_error()
        self.page.get_by_role("button", name="Отчёт о проблеме").first.click()
        self.page.wait_for_timeout(1200)

        self.assertFalse(self.page.locator("#tab-tools").is_hidden())
        self.assertNotIn("folded",
                         self.page.locator("#dgCard").get_attribute("class") or "")
        said = self.page.locator("#dgWhat").input_value()
        self.assertIn("Проверить", said)
        self.assertIn("выберите", said.lower())


class TestWhatTheToolsTabShows(PageTestCase):
    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="tools"]')
        self.page.wait_for_timeout(200)

    def test_the_traffic_card_shows_numbers(self):
        self.assertRegex(self.page.locator("#trSession").inner_text(),
                         r"\d")

    def test_the_journal_tells_the_weight_of_the_bin(self):
        # Карточка журнала свёрнута — разворачиваем её так же, как это
        # делает человек: работ на вкладке полтора десятка, и открытыми
        # им всем быть незачем.
        self.page.click("#hsCard .foldhead")
        self.page.click("#hsLoad")
        self.page.wait_for_timeout(500)
        said = self.page.locator("#hsNote").inner_text()
        self.assertIn("вес", said)
        self.assertRegex(said, r"\d+(\.\d+)? (Б|КБ|МБ|ГБ)")

    def test_the_translator_card_says_where_it_is_not(self):
        """Карточка связи с переводчиком — и молчащая консоль при отказе.

        Именно на этом споткнулись: поле пути получило класс `pickpath`,
        а тот — про список выбранных файлов и требует своего контейнера.
        Ошибка вылезала только при нажатии, и до этой проверки её ловить
        было нечем.
        """
        self.page.fill("#tlPath", "/tmp")
        self.page.click("#tlCheck")
        self.page.wait_for_timeout(1500)

        box = self.page.locator(".err:not([hidden])").first
        self.assertTrue(box.count())
        self.assertIn("cli.py", box.inner_text())
        self.quiet()

    def test_the_translate_button_refuses_without_a_book(self):
        """Отказ приходит ответом на нажатие, а не задачей.

        Заведи маршрут задачу сначала — «файла нет» всплыло бы в ней уже
        с полосой и кнопкой «Остановить». Заодно это единственная
        проверка, где скрипт карточки работает целиком: кнопка, запрос,
        показ отказа.
        """
        self.page.click("#tlTranslate")
        self.page.wait_for_timeout(1500)

        box = self.page.locator(".err:not([hidden])").first
        self.assertTrue(box.count())
        self.assertIn("epub", box.inner_text().lower())
        # Кнопки должны вернуться: отказ — не повод запирать карточку.
        self.assertFalse(self.page.locator("#tlTranslate").is_disabled())
        self.quiet()

    def test_the_service_list_refuses_to_invent_its_own_options(self):
        """Список сервисов до опроса переводчика — только «как настроено».

        Свой перечень провайдеров разошёлся бы с его настройками в первый
        же раз, когда он добавит себе сервис. Поэтому в разметке пунктов
        нет: они приходят от него.
        """
        for box in ("#tlProvider", "#tlModel"):
            with self.subTest(box):
                items = self.page.locator(f"{box} .dropdown-item")
                self.assertEqual(items.count(), 1)
                self.assertIn("как настроено", items.first.inner_text())

    def test_the_update_card_offers_one_button(self):
        """Одна кнопка на всё: две заставляли человека делать работу
        программы."""
        self.assertTrue(self.page.locator("#upGo").is_visible())
        self.assertEqual(self.page.locator("#upLook").count(), 0)
        self.assertEqual(self.page.locator("#upApply").count(), 0)


class TestSplittingABookPastedFromASite(PageTestCase):
    """Книга без заголовков, поделённая по разметке, — прямо на вкладке.

    Проверка сквозная нарочно: разбор разметки, ручки вкладки и её
    скрипт проверяются по отдельности, а вот собираются ли они в
    работающую вкладку — видно только в браузере. Ровно так уже ловилась
    поломка: поле с чужим классом роняло скрипт на первом же нажатии, и
    ни один серверный тест этого не видел.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from tempfile import TemporaryDirectory

        from tests.test_blocks import chapter_box, make_docx

        cls.tmpdir = TemporaryDirectory()
        rows = []
        for number in range(1, 4):
            rows += chapter_box(number, size=4) + [("", ())]
        cls.book = make_docx(Path(cls.tmpdir.name) / "вставленное.docx", rows)
        # Та же книга под именем с числом: из него разбирается номер главы,
        # и сервер принимает её за готовую главу, а не за книгу.
        cls.numbered = make_docx(Path(cls.tmpdir.name) / "ОРИГ ЛАБИРИНТ 80-200.docx",
                                 rows)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()
        super().tearDownClass()

    def open_tab(self):
        self.page.click('.tabs button[data-tab="split"]')
        self.page.fill("#spPath", str(self.book))
        self.page.press("#spPath", "Enter")
        self.page.wait_for_timeout(800)

    def pick_way(self, label):
        """Выбирает способ деления в выпадающем списке."""
        self.page.click("#spWay .dropdown-toggle")
        self.page.click(f"#spWay .dropdown-item:text-is('{label}')")
        self.page.wait_for_timeout(900)

    def test_without_a_way_it_asks_how_to_divide(self):
        self.open_tab()
        self.assertTrue(self.page.locator("#spPatternCard").is_visible())
        self.quiet()

    def test_a_number_in_the_file_name_does_not_silence_the_question(self):
        """Книга, которую сервер принял за готовую главу.

        Номер главы разбирается из имени файла, и у книги «ОРИГ 80-200» он
        находится: сервер видит готовую главу и отвечает без возражений —
        одна глава на полтора миллиона знаков. Вкладка при этом молчала, и
        человек упирался в тупик: файл выбран, а дальше ничего.

        Вопрос теперь задаёт сама вкладка, по итогу: из одного файла вышла
        одна глава — значит, разбиение ничего не разбило.
        """
        self.page.click('.tabs button[data-tab="split"]')
        self.page.fill("#spPath", str(self.numbered))
        self.page.press("#spPath", "Enter")
        self.page.wait_for_timeout(900)

        self.assertIn("глав: 1", self.page.inner_text("#spScanned"))
        self.assertTrue(self.page.locator("#spPatternCard").is_visible())
        self.assertIn("делить её нечем", self.page.inner_text("#spWayNote"))
        self.quiet()

    def test_and_the_markup_then_divides_that_book_too(self):
        self.page.click('.tabs button[data-tab="split"]')
        self.page.fill("#spPath", str(self.numbered))
        self.page.press("#spPath", "Enter")
        self.page.wait_for_timeout(900)
        self.pick_way("по разметке — сам определит")
        self.assertIn("глав: 3", self.page.inner_text("#spScanned"))
        self.quiet()

    def test_the_markup_divides_it_and_says_how(self):
        self.open_tab()
        self.pick_way("по разметке — сам определит")
        self.assertIn("глав: 3", self.page.inner_text("#spScanned"))
        self.assertIn("по рамкам", self.page.inner_text("#spScanned"))
        self.quiet()

    def test_the_pattern_field_hides_when_the_markup_divides(self):
        """Регулярное выражение к делению по рамке отношения не имеет."""
        self.open_tab()
        self.pick_way("по рамкам вокруг глав")
        self.assertFalse(self.page.locator("#spWayHead").is_visible())
        self.assertTrue(self.page.locator("#spWayNote").is_visible())
        self.quiet()

    def test_numbering_from_a_given_start_reaches_the_preview(self):
        self.open_tab()
        self.pick_way("по разметке — сам определит")
        self.page.fill("#spFrom", "125")
        self.page.dispatch_event("#spFrom", "change")
        self.page.wait_for_timeout(900)

        self.page.click("#spPreviewCard .foldhead")
        names = self.page.inner_text("#spPreview")
        for expected in ("Глава 125", "Глава 126", "Глава 127"):
            self.assertIn(expected, names)
        self.quiet()


class TestPickingChaptersInARange(PageTestCase):
    """Отметка галочек с Shift — как в проводнике.

    Книгу в полторы тысячи глав размечают промежутками, а не по одной:
    без Shift «отметить главы с 1 по 200» означало двести нажатий.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from tempfile import TemporaryDirectory

        cls.tmpdir = TemporaryDirectory()
        book = Path(cls.tmpdir.name) / "книга.txt"
        body = "Строка главы, достаточно длинная, чтобы её было видно. " * 3
        book.write_text("\n\n".join(f"Глава {n}\n\n{body}"
                                     for n in range(1, 11)), encoding="utf-8")
        cls.book = book

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="split"]')
        self.page.fill("#spPath", str(self.book))
        self.page.press("#spPath", "Enter")
        self.page.wait_for_timeout(900)
        # Карточка глав лежит свёрнутой: раскрываем, иначе ни галочек, ни
        # кнопок под ними не нажать.
        self.page.click("#spChaptersCard .foldhead")
        self.boxes = self.page.locator("#spChapters input[type=checkbox]")
        self.assertEqual(self.boxes.count(), 10)
        self.page.click("#spNone")

    def marked(self):
        return [index for index in range(10)
                if self.boxes.nth(index).is_checked()]

    def test_shift_marks_everything_in_between(self):
        self.boxes.nth(1).click()
        self.boxes.nth(7).click(modifiers=["Shift"])
        self.assertEqual(self.marked(), [1, 2, 3, 4, 5, 6, 7])
        self.quiet()

    def test_it_works_upwards_too(self):
        """Направление неважно — иначе Shift работал бы через раз."""
        self.boxes.nth(8).click()
        self.boxes.nth(3).click(modifiers=["Shift"])
        self.assertEqual(self.marked(), [3, 4, 5, 6, 7, 8])
        self.quiet()

    def test_shift_can_also_clear_a_range(self):
        """Снять двести галочек нужно ровно так же часто, как поставить."""
        self.page.click("#spAll")
        self.boxes.nth(2).click()
        self.boxes.nth(6).click(modifiers=["Shift"])
        self.assertEqual(self.marked(), [0, 1, 7, 8, 9])
        self.quiet()

    def test_a_plain_click_still_marks_just_one(self):
        self.boxes.nth(4).click()
        self.assertEqual(self.marked(), [4])
        self.quiet()

    def test_the_count_follows_the_range(self):
        """Счётчик «отмечено» считает то же, что и кнопки под ним."""
        self.boxes.nth(0).click()
        self.boxes.nth(4).click(modifiers=["Shift"])
        self.assertIn("5", self.page.inner_text("#spPicked"))
        self.quiet()


class TestTheJunkFindingDoesNotHijackThePage(PageTestCase):
    """Находка мусорной шапки — сообщение, а не задача.

    Раньше карточку разворачивали и подводили к ней взгляд: человек
    выбирал файл, чтобы его разбить, а страницу уносило вниз к находке,
    которую он не спрашивал.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from tempfile import TemporaryDirectory

        cls.tmpdir = TemporaryDirectory()
        cls.folder = Path(cls.tmpdir.name)
        body = "Строка главы, достаточно длинная, чтобы её было видно. " * 3
        for number in range(1, 6):
            (cls.folder / f"Глава {number}.txt").write_text(
                f"Читайте на нашем сайте!\n\nГлава {number}\n\n{body}",
                encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()
        super().tearDownClass()

    def test_the_card_stays_folded_and_the_page_stays_put(self):
        self.page.click('.tabs button[data-tab="split"]')
        top = self.page.evaluate("window.scrollY")
        self.page.fill("#spPath", str(self.folder))
        self.page.press("#spPath", "Enter")
        self.page.wait_for_timeout(1500)

        card = self.page.locator("#hdCard")
        self.assertFalse(card.is_hidden(), "карточка должна появиться")
        # Свёрнута: раскрывать её человек будет сам, если захочет.
        self.assertIn("folded", card.get_attribute("class"))
        self.assertEqual(self.page.evaluate("window.scrollY"), top)
        self.quiet()

    def test_one_notification_says_where_to_look(self):
        self.page.click('.tabs button[data-tab="split"]')
        self.page.fill("#spPath", str(self.folder))
        self.page.press("#spPath", "Enter")
        self.page.wait_for_timeout(1500)
        self.assertIn("ниже", self.page.inner_text(".toast"))
        self.quiet()


class TestChoosingWhatHappensToTheName(PageTestCase):
    """Две карточки «Формат» спрашивают про название по-разному.

    «Собрать книгу» берёт имя из файла — и до сих пор брала его всегда;
    «Переписать заголовки» правит уже готовую книгу и умеет заодно
    привести её к стандарту.
    """

    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="format"]')

    def drop(self):
        """Выбрать «убрать, оставить номер» в списке у «Собрать книгу».

        Карточка со стилем заголовка свёрнута — разворачиваем её так же,
        как это делает человек.
        """
        self.page.click("#fmStyle .foldhead")
        self.page.click("#fmCollectNames .dropdown-toggle")
        self.page.click("#fmCollectNames .dropdown-item:has-text('убрать')")
        self.page.wait_for_timeout(200)

    def test_collecting_asks_what_to_do_with_the_name(self):
        self.assertTrue(self.page.locator("#fmCollectNames").count(),
                        "у «Собрать книгу» должен быть выбор названия")
        self.quiet()

    def test_the_sample_follows_the_choice(self):
        self.drop()
        self.assertNotIn("Название", self.page.inner_text("#fmSample"))
        self.quiet()

    def test_the_choice_is_what_will_be_sent(self):
        self.drop()
        self.assertEqual(self.page.evaluate("fmCollectNames()"), "drop")
        self.quiet()

    def test_retitling_offers_to_bring_the_book_to_standard(self):
        box = self.page.locator("#fmTidy")
        self.assertTrue(box.count(), "нужна галка «привести к стандарту»")
        self.assertFalse(box.is_checked(),
                         "чужую книгу молча не переписываем")
        box.check()
        self.assertTrue(box.is_checked())
        self.quiet()


class TestTurningQuotedSpeechIntoDashes(PageTestCase):
    """Карточка «Речь в кавычках» на вкладке «Инструменты».

    Работа берёт любой формат и живёт рядом с остальными правками текста.
    Кнопки «посмотреть, что изменится» у неё нет намеренно: настраивать
    нечего, и лишнее нажатие только откладывает ответ.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from tempfile import TemporaryDirectory

        from core import formats
        from core.models import Chapter

        cls.tmpdir = TemporaryDirectory()
        cls.folder = Path(cls.tmpdir.name)
        cls.src = cls.folder / "исходники"
        cls.src.mkdir()
        formats.write(cls.src / "ОРИГ ЛАБИРИНТ.docx",
                      [Chapter(number=1, title="Глава 1", paragraphs=[
                          "«Я-я в порядке...♥»", "«Быстрее».",
                          "Он читал «Войну и мир»."])],
                      headings=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="tools"]')

    def choose(self, where):
        """Выбрать файлы так же, как это делает кнопка «Выбрать…»."""
        self.page.evaluate("""(dir) => { CHOSEN.rpList = [dir];
            const h = document.getElementById('rpList').dataset.onchange;
            if(h) window[h]();
        }""", str(where))

    def test_the_card_lives_in_the_tools_tab(self):
        self.assertTrue(self.page.locator("#spchCard").count())
        self.quiet()

    def test_there_is_no_button_to_press_first(self):
        """Список строится сам — нажимать было нечего и незачем."""
        self.assertFalse(self.page.locator("#spchLook").count())
        self.quiet()

    def test_the_list_builds_itself_once_files_are_chosen(self):
        self.choose(self.src)
        self.page.wait_for_selector("#spchTable:not([hidden])", timeout=15000)
        shown = self.page.inner_text("#spchTable")
        self.assertIn("— Быстрее.", shown)
        # Не реплика — в список не попадает вовсе.
        self.assertNotIn("Войну и мир", shown)
        self.assertFalse(self.page.locator("#spchPlace").is_hidden())
        self.quiet()

    def test_where_to_save_stays_hidden_until_there_is_something_to_do(self):
        self.assertTrue(self.page.locator("#spchPlace").is_hidden())
        self.quiet()

    def test_a_word_file_is_rewritten_into_a_word_file(self):
        self.choose(self.src)
        self.page.wait_for_selector("#spchTable:not([hidden])", timeout=15000)
        self.page.fill("#spchBase", str(self.folder))
        self.page.fill("#spchFolder", "Через тире")
        self.page.click("#spchStart")
        self.page.wait_for_function(
            "() => document.getElementById('spchSummary')"
            ".textContent.includes('переписано')", timeout=30000)
        made = self.folder / "Через тире" / "ОРИГ ЛАБИРИНТ.docx"
        self.assertTrue(made.is_file(), sorted(
            p.name for p in (self.folder / "Через тире").iterdir()))
        self.quiet()


class TestTheToolsTabIsFoldedUp(PageTestCase):
    """Работ на вкладке полтора десятка, и открытыми им всем быть незачем:
    страница уезжала на несколько экранов вниз."""

    #: Свёрнутыми — те работы, что нужны изредка. Список назван человеком
    #: поимённо, поэтому и проверяется по именам, а не по числу карточек.
    FOLDED = ("Найти и заменить по всей книге", "Словарь автозамен",
              "Сверка оригинала и перевода", "Два слива одной книги",
              "Очередь задач", "Что изменилось",
              "Журнал операций и корзина", "Шапка и подпись в главах")

    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="tools"]')

    def folded_names(self) -> set:
        return set(self.page.eval_on_selector_all(
            "#tab-tools .card.folded > .foldhead",
            "nodes => nodes.map(n => n.textContent.trim())"))

    def test_every_named_work_starts_folded(self):
        missing = sorted(set(self.FOLDED) - self.folded_names())
        self.assertEqual(missing, [], self.folded_names())
        self.quiet()

    def test_a_folded_card_opens_by_its_head(self):
        self.page.click("#rpCard .foldhead")
        self.assertNotIn("folded", self.page.get_attribute("#rpCard", "class"))
        self.quiet()

    def test_the_speech_card_is_open(self):
        """За правкой текста на вкладку и заходят."""
        self.assertNotIn("folded",
                         self.page.get_attribute("#spchCard", "class"))
        self.quiet()


class TestTheProgressStandsWhereItWasStarted(PageTestCase):
    """Полоса прогресса на «Форматировать» стояла последней на вкладке.

    Работ там две, и обе с прогрессом: «Собрать книгу из глав» — самая
    первая карточка, «Заголовки в готовой книге» — четвёртая. Полоса же
    ждала внизу, под «Мусором в главах» и «Объёмом глав»: нажал наверху —
    ищи ответ за краем экрана.

    Карточка прогресса одна: у неё свои счётчики, кнопка «Остановить» и
    журнал перевода, и второй её экземпляр пришлось бы однажды чинить
    дважды. Поэтому она переезжает к той работе, которую запустили.
    """

    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="format"]')

    def place(self, button: str) -> str:
        """Куда встанет прогресс, если работу запустить этой кнопкой."""
        return self.page.evaluate(
            """(id) => {
                fmPlaceProgress(document.getElementById(id));
                const box = document.getElementById('fmProgress');
                return box.previousElementSibling.outerHTML;
            }""", button)

    def test_the_bar_follows_the_button_that_started_the_work(self):
        self.assertIn("Собрать книгу из глав", self.place("fmCollect"))
        self.assertIn("Заголовки в готовой книге", self.place("fmRetitle"))
        self.quiet()

    def test_it_goes_back_up_when_the_first_work_is_started_again(self):
        """Переезд в один конец оставил бы полосу внизу навсегда."""
        self.place("fmRetitle")
        self.assertIn("Собрать книгу из глав", self.place("fmCollect"))
        self.quiet()

    def started_by(self, button: str) -> str:
        """Нажать кнопку по-настоящему, подменив сервер.

        Настоящий путь, а не вызов изнутри: забудь работа попросить о
        переезде — полоса осталась бы там, где её оставила соседняя, и
        `fmPlaceProgress` сам по себе этого не покажет.
        """
        return self.page.evaluate(
            """async (id) => {
                const server = window.call, poll = window.pollJob;
                window.call = async () => (
                    {job: {id: 'проверка', progress: {}, output_dir: ''}});
                window.pollJob = () => {};
                try{
                    document.getElementById(id).click();
                    await new Promise(r => setTimeout(r, 60));
                }finally{
                    window.call = server;
                    window.pollJob = poll;
                }
                return document.getElementById('fmProgress')
                    .previousElementSibling.outerHTML;
            }""", button)

    def test_both_works_move_it_to_themselves(self):
        self.assertIn("Заголовки в готовой книге",
                      self.started_by("fmRetitle"))
        self.assertIn("Собрать книгу из глав", self.started_by("fmCollect"))


class EffectTestCase(PageTestCase):
    """Эффекты проверяются на живой странице, а не по тексту файлов.

    Реестр и подключение файлов сверяет `test_effects.py`. Там видно, что
    эффект объявлен, — но не то, что он хоть на что-то влияет: правило,
    промахнувшееся мимо разметки, выглядит в файле точно так же, как
    попавшее.
    """

    def turn(self, key: str, on: bool = True):
        self.page.evaluate(
            "([k, on]) => document.documentElement.classList.toggle('fx-' + k, on)",
            [key, on])

    def styled(self, selector: str, field: str) -> str:
        return self.page.evaluate(
            """([sel, field]) => {
                const node = document.querySelector(sel);
                return node ? getComputedStyle(node)[field] : '';
            }""", [selector, field])


class TestTheMenuUnfolds(EffectTestCase):
    """Меню появлялось разом, целиком, — и на месте пустого воздуха вдруг
    оказывался список."""

    def test_the_items_come_out_one_after_another(self):
        self.turn('menu-fold')
        self.page.click('.tabs button[data-tab="format"]')
        self.page.click("#fmNames .dropdown-toggle")
        self.assertEqual(
            self.styled("#fmNames .dropdown-menu .dropdown-item",
                        "animationName"), "fx-menu-fold-item")
        self.quiet()

    def test_a_taken_off_switch_takes_the_movement_off(self):
        self.turn('menu-fold', False)
        self.page.click('.tabs button[data-tab="format"]')
        self.page.click("#fmNames .dropdown-toggle")
        self.assertEqual(
            self.styled("#fmNames .dropdown-menu .dropdown-item",
                        "animationName"), "none")
        self.quiet()

    def test_the_frame_itself_does_not_move(self):
        """Плавающее меню считает себе место сразу после вставки, а размер
        оно берёт с учётом преобразований: сожми мы рамку в первом кадре,
        меню измерило бы себя сжатым и встало бы не туда."""
        css = (STATIC / "css" / "effects" / "menu-fold.css").read_text(
            encoding="utf-8")
        frame = css.split("@keyframes fx-menu-fold-in", 1)[1].split("}", 2)[0]
        self.assertNotIn("transform", frame)


class TestAFilledFieldGlows(EffectTestCase):
    """На карточке бывает шесть полей подряд, и что заполнено, а что ждёт
    ввода, видно только по мелкому серому тексту внутри."""

    def border(self, selector: str, text: str) -> str:
        """Цвет каймы поля с этим содержимым — и без фокуса на нём.

        Фокус снимаем нарочно. У поля в работе своя подсветка, сильнее
        нашей, и сравнивать заполненное-в-фокусе с пустым-без-фокуса
        значило бы мерить не то.
        """
        self.page.fill(selector, text)
        self.page.evaluate("(sel) => document.querySelector(sel).blur()",
                           selector)
        return self.settled(selector)

    def settled(self, selector: str) -> str:
        """Цвет каймы, когда переход уже кончился.

        Кайма меняется не рывком, а за долю секунды: прочитанное сразу —
        это цвет на середине пути, и он не равен ни тому, ни другому.
        """
        self.page.wait_for_timeout(350)
        return self.styled(selector, "borderColor")

    def setUp(self):
        super().setUp()
        self.turn('field-filled')
        self.page.click('.tabs button[data-tab="split"]')

    def test_a_filled_field_differs_from_an_empty_one(self):
        self.assertNotEqual(self.border("#spPath", "C:/книги"),
                            self.border("#spPath", ""))
        self.quiet()

    def test_a_field_being_typed_into_keeps_its_own_light(self):
        """Два свечения в одних пикселях спорят между собой."""
        self.page.fill("#spPath", "C:/книги")   # заполнение оставляет фокус
        lit = self.settled("#spPath")
        self.page.evaluate("() => document.getElementById('spPath').blur()")
        self.assertNotEqual(self.settled("#spPath"), lit)
        self.quiet()

    def test_a_field_without_a_placeholder_is_left_alone(self):
        """У такого поля `:placeholder-shown` не совпадает никогда — а
        значит, пустое горело бы наравне с заполненным."""
        css = (STATIC / "css" / "effects" / "field-filled.css").read_text(
            encoding="utf-8")
        for rule in css.splitlines():
            # Только строки-правила: в пояснении выше псевдокласс тоже
            # назван, и на нём проверка спотыкалась.
            if rule.startswith(".fx-") and ":not(:placeholder-shown)" in rule:
                self.assertIn("[placeholder]", rule, rule)


class TestTheInkDries(EffectTestCase):
    def test_the_path_shows_itself_when_it_appears(self):
        self.turn('ink-dry')
        self.page.click('.tabs button[data-tab="format"]')
        self.assertEqual(self.styled("#fmSummary", "animationName"), "none")

        self.page.evaluate(
            "() => { document.getElementById('fmSummary').textContent = "
            "'Файл: C:/книги/книга.md'; }")
        self.assertEqual(self.styled("#fmSummary", "animationName"),
                         "fx-ink-dry")
        self.quiet()


class TestTheLockedButtonShakes(EffectTestCase):
    """Серая кнопка не отвечала ничем: нажатие проваливалось в пустоту, и
    занятую работой кнопку принимали за сломанную."""

    def poke(self, selector: str) -> bool:
        """Ткнуть в середину кнопки и сказать, дрогнула ли она."""
        return self.page.evaluate(
            """(sel) => {
                const button = document.querySelector(sel);
                const box = button.getBoundingClientRect();
                document.dispatchEvent(new PointerEvent('pointerdown', {
                    bubbles: true,
                    clientX: box.left + box.width / 2,
                    clientY: box.top + box.height / 2,
                }));
                return button.classList.contains('fx-locked');
            }""", selector)

    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="check"]')
        self.page.evaluate(
            "() => { document.getElementById('mnStart').disabled = true; }")

    def test_a_locked_button_answers_the_poke(self):
        self.turn('lock-shake')
        self.assertTrue(self.poke("#mnStart"))
        self.quiet()

    def test_a_working_button_is_not_shaken(self):
        """Дрожь на живой кнопке означала бы отказ там, где его нет."""
        self.turn('lock-shake')
        self.page.evaluate(
            "() => { document.getElementById('mnStart').disabled = false; }")
        self.assertFalse(self.poke("#mnStart"))
        self.quiet()

    def test_the_poke_reaches_the_page_at_all(self):
        """Событий от выключенной кнопки браузер не рассылает вовсе —
        поймать нажатие можно только сняв с неё указатели."""
        self.turn('lock-shake')
        self.assertEqual(self.styled("#mnStart", "pointerEvents"), "none")

    def test_a_taken_off_switch_leaves_the_button_alone(self):
        self.turn('lock-shake', False)
        self.assertFalse(self.poke("#mnStart"))
        self.quiet()


class TestTheWheelPicksUpSpeed(EffectTestCase):
    """«Глав в томе» доходит до двухсот пятидесяти за двести пятьдесят
    щелчков колеса. Столько никто не крутит."""

    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="format"]')
        self.turn('spin-wheel')

    def spin(self, times: int, selector: str = "#fmRenumber") -> int:
        """Крутануть колесо вверх столько раз подряд."""
        return self.page.evaluate(
            """([sel, times]) => {
                const input = document.querySelector(sel);
                input.value = '0';
                input.focus();
                for(let at = 0; at < times; at += 1){
                    input.dispatchEvent(new WheelEvent('wheel', {
                        bubbles: true, cancelable: true, deltaY: -1}));
                }
                return Number(input.value);
            }""", [selector, times])

    def test_the_first_click_moves_by_one(self):
        """Разгон не должен отбирать точную правку на единицу."""
        self.assertEqual(self.spin(1), 1)
        self.quiet()

    def test_spinning_on_goes_faster_than_one_by_one(self):
        self.assertGreater(self.spin(20), 40)
        self.quiet()

    def test_a_field_nobody_clicked_into_is_left_to_the_page(self):
        """Иначе колесо переставало прокручивать страницу каждый раз,
        когда курсор случайно проезжал над числом."""
        got = self.page.evaluate(
            """(sel) => {
                const input = document.querySelector(sel);
                input.value = '0';
                input.blur();
                const event = new WheelEvent('wheel', {
                    bubbles: true, cancelable: true, deltaY: -1});
                input.dispatchEvent(event);
                return {value: Number(input.value), stopped: event.defaultPrevented};
            }""", "#fmRenumber")
        self.assertEqual(got["value"], 0)
        self.assertFalse(got["stopped"])
        self.quiet()

    def test_a_taken_off_switch_gives_the_wheel_back(self):
        self.turn('spin-wheel', False)
        self.assertEqual(self.spin(20), 0)
        self.quiet()


class TestTheTabSlidesFromTheSideItWasPressed(EffectTestCase):
    def side(self, tab: str) -> str:
        self.page.click(f'.tabs button[data-tab="{tab}"]')
        return self.page.evaluate(
            """() => {
                const shown = document.querySelector('section:not([hidden])');
                return [...shown.classList].find(c => c.startsWith('fx-slide-')) || '';
            }""")

    def test_it_comes_from_the_right_going_right(self):
        self.turn('tab-slide')
        self.page.click('.tabs button[data-tab="download"]')
        self.assertEqual(self.side("check"), "fx-slide-from-right")
        self.quiet()

    def test_it_comes_from_the_left_going_back(self):
        self.turn('tab-slide')
        self.page.click('.tabs button[data-tab="check"]')
        self.assertEqual(self.side("download"), "fx-slide-from-left")
        self.quiet()

    def test_growing_stands_down_while_sliding(self):
        """Два разных движения на одном содержимом дерутся между собой."""
        self.turn('tab-slide')
        self.turn('tab-grow')
        self.page.click('.tabs button[data-tab="check"]')
        self.assertFalse(self.page.evaluate(
            "() => document.querySelector('section:not([hidden])')"
            ".classList.contains('fx-enter')"))
        self.quiet()

    def test_a_taken_off_switch_leaves_the_tab_still(self):
        self.turn('tab-slide', False)
        self.assertEqual(self.side("check"), "")
        self.quiet()


#: Прозрачная точка. Обложки приходят с сайта, а его тут нет: чтобы
#: полёту было чем лететь, строке подставляется картинка, которую не надо
#: ниоткуда качать.
PIXEL = ("data:image/gif;base64,"
         "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


class RankEffectTestCase(EffectTestCase):
    """Рейтинг с подставленным срезом.

    Сайтов отсюда не видно, а эффекты живут на строках. Поэтому кладём
    свой срез в ту же переменную, откуда его берёт вкладка, и зовём ту же
    отрисовку: путь от списка до строки — настоящий, чужого в нём только
    сам список.
    """

    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="rank"]')

    def seed(self, books):
        rows = [{"place": at, "book_id": book, "name": f"Книга {book}",
                 "readers": 1000 - at, "day": 0, "week": 0, "diff": 0,
                 "is_new": at == 1, "holding": 3, "site": "", "cover": ""}
                for at, book in enumerate(books, 1)]
        self.page.evaluate("(rows) => { rkRows = rows; rkRender(); }", rows)

    def at_place(self, place: str, field: str) -> str:
        """Что у номера места с этим значением."""
        return self.page.evaluate(
            """([place, field]) => {
                for(const node of document.querySelectorAll('#rkTable .place')){
                    if(node.textContent !== place) continue;
                    return field.startsWith('--')
                        ? node.style.getPropertyValue(field)
                        : getComputedStyle(node)[field];
                }
                return '';
            }""", [place, field])

    def dealt(self) -> int:
        return self.page.locator("#rkTable .tr.fx-dealt").count()


class TestThePlaceBurnsByItsHeight(RankEffectTestCase):
    """Колонка мест — двадцать одинаковых серых чисел в столбик."""

    def test_the_heat_falls_from_the_first_place_down(self):
        self.seed([f"b{n}" for n in range(1, 23)])
        self.assertEqual(self.at_place("1", "--fx-place-heat"), "1.00")
        self.assertEqual(self.at_place("20", "--fx-place-heat"), "0.05")
        self.assertEqual(self.at_place("22", "--fx-place-heat"), "0.00")
        self.quiet()

    def test_the_light_follows_the_heat(self):
        self.turn('place-glow')
        self.seed([f"b{n}" for n in range(1, 23)])
        self.assertNotEqual(self.at_place("1", "textShadow"),
                            self.at_place("15", "textShadow"))
        self.quiet()

    def test_a_taken_off_switch_leaves_the_column_grey(self):
        self.turn('place-glow', False)
        self.seed([f"b{n}" for n in range(1, 23)])
        self.assertEqual(self.at_place("1", "textShadow"),
                         self.at_place("15", "textShadow"))
        self.quiet()


class TestTheTopBreathes(RankEffectTestCase):
    def marked(self) -> str:
        return self.page.evaluate(
            """() => {
                const rows = document.querySelectorAll('#rkTable .tr.fx-top');
                if(rows.length !== 1) return `отмечено строк: ${rows.length}`;
                return rows[0].querySelector('.place').textContent;
            }""")

    def test_the_book_on_top_is_the_one_marked(self):
        self.seed(["a", "b", "c"])
        self.assertEqual(self.marked(), "1")
        self.quiet()

    def test_the_mark_goes_by_the_place_not_by_the_row(self):
        """Первое место — не первая строка: список сортируют и по числу
        читающих, и по движению за сутки."""
        self.seed(["a", "b", "c"])
        self.page.evaluate(
            """() => {
                const places = document.querySelectorAll('#rkTable .place');
                places[0].textContent = '2';
                places[1].textContent = '1';
                rlMark();
            }""")
        self.assertEqual(self.marked(), "1")
        self.assertFalse(self.page.evaluate(
            "() => document.querySelector('#rkTable .tr').classList"
            ".contains('fx-top')"))
        self.quiet()

    def test_the_cover_breathes(self):
        self.turn('top-breath')
        self.seed(["a", "b", "c"])
        self.assertEqual(
            self.styled("#rkTable .tr.fx-top .cover", "animationName"),
            "fx-top-breath")
        self.quiet()

    def test_it_holds_its_breath_under_the_cursor(self):
        """«Живые обложки» в этот момент отклоняют обложку вслед за
        курсором, а анимация просто затёрла бы их преобразование."""
        self.turn('top-breath')
        self.seed(["a", "b", "c"])
        # Мышью, а не `hover`: тот ждёт, пока цель замрёт, а цель как раз
        # дышит — и ждать он будет вечно.
        box = self.page.locator("#rkTable .tr.fx-top .cover").bounding_box()
        self.page.mouse.move(box["x"] + box["width"] / 2,
                             box["y"] + box["height"] / 2)
        self.assertEqual(
            self.styled("#rkTable .tr.fx-top .cover", "animationName"), "none")
        self.quiet()


class TestTheRibbonUnrolls(RankEffectTestCase):
    def test_the_mark_in_the_rating_unrolls(self):
        self.turn('tag-unroll')
        self.seed(["a", "b"])
        self.assertEqual(self.styled("#rkTable .tr .tag", "animationName"),
                         "fx-tag-unroll")
        self.quiet()

    def test_a_mark_anywhere_else_is_left_alone(self):
        """Метка с этим же именем стоит и в находках проверки, и в замере
        потоков, где никакой новизны она не означает."""
        self.turn('tag-unroll')
        self.seed(["a", "b"])
        self.assertEqual(self.page.evaluate(
            """() => {
                const tag = document.createElement('span');
                tag.className = 'tag';
                tag.textContent = 'не про рейтинг';
                document.getElementById('tab-check').append(tag);
                return getComputedStyle(tag).animationName;
            }"""), "none")
        self.quiet()


class TestTheBoardIsDealtAgain(RankEffectTestCase):
    """Досок четырнадцать, и переключаются они соседними кнопками. Список
    подменялся целиком и молча."""

    def setUp(self):
        super().setUp()
        self.turn('board-shuffle')

    def test_another_board_is_dealt_row_by_row(self):
        self.seed(["a", "b", "c"])
        self.seed(["x", "y", "z"])
        self.assertEqual(self.dealt(), 3)
        self.quiet()

    def test_a_fresh_slice_of_the_same_board_is_not_dealt(self):
        """Там книги те же, и их перемещение показывает «переезд строк»."""
        self.seed(["a", "b", "c"])
        self.seed(["a", "b", "c"])
        self.assertEqual(self.dealt(), 0)
        self.quiet()

    def test_the_very_first_showing_is_not_a_change_of_board(self):
        """Списка до него не было вовсе — меняться было нечему."""
        self.seed(["a", "b", "c"])
        self.assertEqual(self.dealt(), 0)
        self.quiet()

    def test_a_taken_off_switch_leaves_the_list_still(self):
        self.turn('board-shuffle', False)
        self.seed(["a", "b", "c"])
        self.seed(["x", "y", "z"])
        self.assertEqual(self.dealt(), 0)
        self.quiet()


class TestTheCoverFliesToTheDownloader(RankEffectTestCase):
    def setUp(self):
        super().setUp()
        self.turn('cover-flight')
        self.seed(["a", "b"])
        # Обложка приходит с сайта, которого отсюда не видно. Подставляем
        # картинку: лететь должно чему-то настоящему, иначе проверять
        # нечего.
        self.page.evaluate(
            """(pixel) => {
                const cover = document.querySelector('#rkTable .tr .cover');
                cover.replaceChildren();
                const img = document.createElement('img');
                img.src = pixel;
                img.style.width = '34px';
                img.style.height = '46px';
                cover.append(img);
            }""", PIXEL)

    def press(self, name: str):
        self.page.get_by_role("button", name=name).first.click()
        self.page.wait_for_timeout(400)

    def test_the_cover_leaves_when_the_downloader_opens(self):
        self.press("скачать")
        self.assertEqual(self.page.locator(".fx-flying").count(), 1)

    def test_it_is_headed_for_the_downloader_tab(self):
        """Смотрим, куда копию отправили, а не где она сейчас: летит она
        полсекунды, и на любом замере посреди пути она где-то между.

        Сходится по горизонтали: страница после перехода прокручивается к
        форме качалки, и высота вкладки к моменту замера уже другая, а
        столбец — тот же.
        """
        self.press("скачать")
        self.assertLess(self.page.evaluate(
            """() => {
                const ghost = document.querySelector('.fx-flying');
                const tab = document.querySelector('.tabs button[data-tab="download"]');
                const to = tab.getBoundingClientRect();
                return Math.abs(parseFloat(ghost.style.left)
                                - (to.left + to.width / 2));
            }"""), 20)

    def test_it_never_lands_off_the_screen(self):
        """Строка вкладок не липкая: в длинном рейтинге её на экране может
        не быть вовсе, и обложка улетала бы за верхний край — в никуда."""
        self.page.evaluate(
            "() => document.querySelector('.tabs')"
            ".style.transform = 'translateY(-900px)'")
        self.press("скачать")
        self.assertTrue(self.page.evaluate(
            """() => {
                const ghost = document.querySelector('.fx-flying');
                const top = parseFloat(ghost.style.top);
                const left = parseFloat(ghost.style.left);
                return top >= 0 && left >= 0
                    && top <= window.innerHeight && left <= window.innerWidth;
            }"""))

    def test_nothing_flies_where_nobody_went(self):
        """Кнопка рядом открывает меню копирования и никуда не переходит.
        Полёт туда, куда не перешли, был бы враньём."""
        self.press("скопировать")
        self.assertEqual(self.page.locator(".fx-flying").count(), 0)

    def test_a_taken_off_switch_grounds_it(self):
        self.turn('cover-flight', False)
        self.press("скачать")
        self.assertEqual(self.page.locator(".fx-flying").count(), 0)


class NetEffectTestCase(EffectTestCase):
    """Связь показывается тем же путём, каким живёт дождь: качалка на
    каждом опросе рассказывает, что происходит, а эффекты решают, как это
    показать. Через эту же дверь их и проверяем."""

    def tune(self, **state):
        base = {"busy": True, "held": False, "proxies": 0, "switches": 0,
                "done": 0, "failed": 0}
        base.update(state)
        self.page.evaluate("(state) => netTune(state)", base)

    def seen(self) -> dict:
        return self.page.evaluate("() => netState()")


class TestTheAddressesAreDots(NetEffectTestCase):
    """Строка «3 потока · 3 прокси» правду говорит, но вчерашнюю: адрес
    отваливается посреди работы, а адресов по-прежнему три."""

    def setUp(self):
        super().setUp()
        self.turn('proxy-dots')

    def test_there_are_as_many_dots_as_addresses(self):
        self.tune(proxies=3)
        self.assertEqual(self.seen()["dots"], 3)
        self.quiet()

    def test_working_without_proxies_is_one_dot_not_none(self):
        """Ноль точек не отличить от снятой галочки."""
        self.tune(proxies=0)
        self.assertEqual(self.seen()["dots"], 1)
        self.assertIn("напрямую", self.page.get_attribute("#fxNet .fxnet-dots",
                                                          "title"))
        self.quiet()

    def test_a_long_list_does_not_become_a_line_of_dots(self):
        self.tune(proxies=200)
        self.assertLessEqual(self.seen()["dots"], 12)
        self.quiet()

    def test_a_swapped_address_puts_a_dot_out(self):
        self.tune(proxies=3)
        self.assertEqual(self.seen()["gone"], 0)
        self.tune(proxies=3, switches=1)
        self.assertEqual(self.seen()["gone"], 1)
        self.quiet()

    def test_the_dots_go_when_the_work_does(self):
        self.tune(proxies=3)
        self.tune(busy=False)
        self.assertEqual(self.seen()["dots"], 0)
        self.quiet()

    def test_a_taken_off_switch_leaves_no_dots(self):
        self.turn('proxy-dots', False)
        self.tune(proxies=3)
        self.assertEqual(self.seen()["dots"], 0)
        self.quiet()


class TestTheChaptersSpark(NetEffectTestCase):
    def setUp(self):
        super().setUp()
        self.turn('request-pulse')

    def sparks(self) -> dict:
        # Искры пришедших глав пускаются с задержкой друг за другом, а
        # живут меньше секунды: считаем, когда вылетели все и не улетел
        # никто.
        self.page.wait_for_timeout(420)
        return self.seen()

    def test_a_chapter_that_came_sparks(self):
        self.tune(done=0)
        self.tune(done=2)
        self.assertEqual(self.sparks()["sparks"], 2)
        self.quiet()

    def test_a_chapter_that_did_not_come_sparks_red(self):
        self.tune(failed=0)
        self.tune(failed=1)
        self.assertEqual(self.sparks()["bad"], 1)
        self.quiet()

    def test_a_flood_does_not_become_a_stripe(self):
        """Искра — указатель жизни, а не счётчик."""
        self.tune(done=0)
        self.tune(done=200)
        self.assertLessEqual(self.sparks()["sparks"], 4)
        self.quiet()

    def test_a_paused_run_is_quiet(self):
        """Обмена нет — искрам взяться неоткуда."""
        self.tune(done=0)
        self.tune(done=5, held=True)
        self.assertEqual(self.sparks()["sparks"], 0)
        self.quiet()

    def test_what_arrived_during_the_pause_does_not_pour_out_after_it(self):
        self.tune(done=0)
        self.tune(done=5, held=True)
        self.tune(done=5)
        self.assertEqual(self.sparks()["sparks"], 0)
        self.quiet()

    def test_a_taken_off_switch_takes_the_wire_too(self):
        self.turn('request-pulse', False)
        self.tune(done=1)
        self.assertFalse(self.seen()["wire"])
        self.quiet()


class TestTheTrafficIsDrawn(NetEffectTestCase):
    def setUp(self):
        super().setUp()
        self.turn('traffic-line')

    def test_the_graph_shows_up_while_the_work_runs(self):
        self.tune()
        self.assertTrue(self.seen()["graph"])
        self.quiet()

    def test_it_goes_when_the_work_does(self):
        """Постоянно висящая в углу панель мешала бы."""
        self.tune()
        self.tune(busy=False)
        self.assertFalse(self.seen()["graph"])
        self.quiet()

    def test_it_stays_out_of_the_way_of_what_is_under_it(self):
        """Это указатель, а не орган управления."""
        self.tune()
        self.assertEqual(self.styled("#fxTraffic", "pointerEvents"), "none")
        self.quiet()

    def test_a_taken_off_switch_leaves_the_corner_empty(self):
        self.turn('traffic-line', False)
        self.tune()
        self.assertFalse(self.seen()["graph"])
        self.quiet()


class TestTheStripKeepsOutOfTheWay(NetEffectTestCase):
    """Пустая строка между способом и кнопками выглядит как забытый
    отступ."""

    def test_nothing_switched_on_leaves_no_empty_row(self):
        for key in ('proxy-dots', 'request-pulse', 'traffic-line'):
            self.turn(key, False)
        self.tune(proxies=3, done=2)
        self.assertEqual(self.page.locator("#fxNet").count(), 0)
        self.quiet()

    def test_the_row_goes_away_with_what_was_in_it(self):
        """Заведена полоска была не зря — а вот остаться пустой не должна."""
        self.turn('proxy-dots')
        self.tune(proxies=3)
        self.assertEqual(self.page.locator("#fxNet").count(), 1)

        self.tune(busy=False)
        self.assertEqual(self.page.locator("#fxNet").count(), 0)
        self.quiet()


class TestNoFieldFallsOutOfTheTheme(PageTestCase):
    """Поле времени в очереди книг было белым с чёрным текстом посреди
    тёмной страницы.

    Виновато было перечисление: правила писались на `text`, `number` и
    `password`, а `time` в список не попал. Следующий новый тип попал бы
    туда же — поэтому теперь типы не перечисляются, а исключаются те, у
    которых своя внешность.
    """

    def paint(self, selector: str) -> dict:
        return self.page.eval_on_selector(selector, """n => {
            const s = getComputedStyle(n);
            return {background: s.backgroundColor, color: s.color};
        }""")

    def light(self, colour: str) -> bool:
        """Светлое ли это на глаз — поверх тёмной карточки.

        Прозрачность считаем: белый на четырёх процентах — это чуть
        подсвеченная темнота, а не белое поле. Без этого «rgba(255, 255,
        255, .04)» сошло бы за белизну, и тест ругался бы на правильное.
        """
        nums = [float(x) for x in colour.replace(",", " ")
                .replace("(", " ").replace(")", " ").split()
                if x.replace(".", "", 1).isdigit()]
        if len(nums) < 3:
            return False
        alpha = nums[3] if len(nums) > 3 else 1.0
        return sum(nums[:3]) / 3 * alpha > 128

    def test_the_time_field_is_dark_like_the_rest(self):
        got = self.paint("#dqPlanAt")
        self.assertFalse(self.light(got["background"]), got)
        self.assertTrue(self.light(got["color"]), got)

    def test_every_kind_of_field_is_painted_the_same(self):
        """Сверяем с обычным текстовым полем: у них один вид, и
        расхождение здесь и есть та самая белая заплатка."""
        plain = self.paint("#dqPlanAt")
        for other in ("input[type=text]", "input[type=number]"):
            with self.subTest(other):
                self.assertEqual(self.paint(other), plain)

    def test_the_night_run_line_reads_as_a_checkbox(self):
        """Класса `check` в стилях нет вовсе, и строка набиралась как
        заголовок раздела — в разрядку и капслоком."""
        said = self.page.eval_on_selector(
            "#dqPlanRow label",
            "n => getComputedStyle(n).textTransform")
        self.assertEqual(said, "none")


if __name__ == "__main__":
    unittest.main()


class TestTheLibraryCardOpens(PageTestCase):
    """Нажал на работу — развернулось описание, жанры и теги.

    Библиотека здесь временная: настоящую трогать нельзя, а без книги
    проверять нечего.
    """

    @classmethod
    def setUpClass(cls):
        from tempfile import TemporaryDirectory

        from ops import library

        cls.store = TemporaryDirectory()
        cls.was_file = library.LIBRARY_FILE
        library.LIBRARY_FILE = Path(cls.store.name) / "library.json"
        cls.library = library

        library.remember(
            "проба", name="Hunter Counselor", name_ru="Советник охотниц",
            author="국거리장단", source="dreamy", address="ibatcffhwusd",
            about="About the hunters", about_ru="Про охотниц и их беды",
            genres=["Fantasy"], genres_ru=["Фэнтези", "Драма"],
            site_tags=["Harem"], site_tags_ru=["Гарем"],
            status="выходит", chapters=97, last=97,
            folder=str(Path(cls.store.name) / "книга"))
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.library.LIBRARY_FILE = cls.was_file
        cls.store.cleanup()

    def open_library(self):
        self.page.click('[data-tab="library"]')
        self.page.wait_for_selector("#lbList .lb", timeout=10000)

    def test_the_description_is_hidden_until_it_is_asked_for(self):
        """В списке на две сотни книг описания превратили бы его в
        простыню, а нужны они по одному."""
        self.open_library()
        self.assertFalse(self.page.locator("#lbList .lb-more").is_visible())

    def test_clicking_the_name_opens_the_card(self):
        self.open_library()
        self.page.click("#lbList .lb-name")

        more = self.page.locator("#lbList .lb-more")
        self.assertTrue(more.is_visible())
        self.assertIn("Про охотниц", more.inner_text())

    def test_the_russian_is_shown_when_there_is_russian(self):
        """Ради этого перевод и хранится: чтобы не переводить заново."""
        self.open_library()
        self.page.click("#lbList .lb-name")
        said = self.page.locator("#lbList .lb-more").inner_text()

        self.assertIn("Фэнтези", said)
        self.assertIn("Гарем", said)
        # Пометка говорит именно про описание, а не про карточку вообще.
        # Прежнее «по-русски» появлялось и от одного переведённого
        # названия — при английском описании прямо под ним.
        self.assertIn("описание переведено", said)

    def test_the_original_is_one_click_away(self):
        """Перевод бывает вольным, и сверить хочется, не уходя со
        страницы."""
        self.open_library()
        self.page.click("#lbList .lb-name")
        self.page.click("#lbList .lb-more .lbchip")

        said = self.page.locator("#lbList .lb-about").inner_text()
        self.assertIn("About the hunters", said)

    def test_it_folds_back(self):
        self.open_library()
        self.page.click("#lbList .lb-name")
        self.page.click("#lbList .lb-name")

        self.assertFalse(self.page.locator("#lbList .lb-more").is_visible())

    def test_the_console_stays_quiet(self):
        self.open_library()
        self.page.click("#lbList .lb-name")
        self.quiet()

    def checked_with(self, answer) -> str:
        """Нажать «Проверить обновления», подменив ответ сервера."""
        self.open_library()
        return self.page.evaluate(
            """async (answer) => {
                const server = window.call;
                window.call = async () => answer;
                try{ await libCheck('lbNote', 'lbCheck'); }
                finally{ window.call = server; }
                return document.getElementById('lbNote').textContent;
            }""", answer)

    def test_the_reason_is_shown_and_not_just_the_count(self):
        """«Не ответили: 12» — не ответ: человек жмёт кнопку, ничего не
        меняется, и виноватой выглядит кнопка."""
        said = self.checked_with({
            "checked": [], "left": 0, "books": [], "state": {},
            "missed": [{"key": "проба",
                        "why": "Ваш компьютер не узнал адрес chap.example"}]})

        self.assertIn("Не ответили: 1", said)
        self.assertIn("не узнал адрес chap.example", said)
        self.quiet()

    def test_one_reason_is_enough_for_the_whole_batch(self):
        """Причина у всех непрошедших обычно одна, и двенадцать её копий
        превратили бы заметку в простыню."""
        said = self.checked_with({
            "checked": [], "left": 0, "books": [], "state": {},
            "missed": [{"key": str(n), "why": "каталог молчит"}
                       for n in range(12)]})

        self.assertEqual(said.count("каталог молчит"), 1)
        self.quiet()

    def test_a_check_that_went_through_says_nothing_extra(self):
        """Красная строка там, где всё получилось, пугала бы на ровном
        месте."""
        said = self.checked_with({
            "checked": ["проба"], "left": 0, "books": [], "state": {},
            "missed": []})

        self.assertNotIn("Не ответили", said)
        self.assertEqual(
            self.page.locator("#lbNote .lb-why").count(), 0)
        self.quiet()


class TestEveryBookHasItsOwnBar(PageTestCase):
    """Одна полоса на всю очередь не отвечала, кто чем занят.

    «Глава 1823 из 1868» при тринадцати книгах читается так, будто
    качается одна: по какой из них идёт эта глава, из строки не узнать.
    """

    def draw(self, rows) -> None:
        self.page.evaluate("(rows) => pbDraw(rows)", rows)

    def book(self, **fields) -> dict:
        """Строка книги — такая же, какую отдаёт задача."""
        row = {"id": fields.get("title", "к"), "title": "Книга",
               "stage": "download", "total": 10, "done": 4}
        row.update(fields)
        return row

    def test_each_book_gets_a_line_with_its_own_name_and_count(self):
        self.draw([self.book(title="Книга А", done=2, total=10),
                   self.book(title="Книга Б", done=9, total=10)])

        rows = self.page.locator("#pbList .pb")
        self.assertEqual(rows.count(), 2)
        first = rows.nth(0).inner_text()
        self.assertIn("Книга А", first)
        self.assertIn("глава 2 из 10", first)
        self.assertIn("осталось 8", first)
        self.assertIn("Книга Б", rows.nth(1).inner_text())
        self.quiet()

    def test_the_bar_of_each_book_stands_where_that_book_stands(self):
        """Иначе полосы одинаковые, и список ничего не добавляет к
        одной полосе наверху."""
        self.draw([self.book(title="Книга А", done=2, total=10),
                   self.book(title="Книга Б", done=9, total=10)])

        got = self.page.evaluate(
            """() => [...document.querySelectorAll('#pbList .pb .bar > i')]
                     .map(one => one.style.width)""")
        self.assertEqual(got, ["20%", "90%"])
        self.quiet()

    def folded(self) -> bool:
        """Убран ли список.

        Спрашиваем именно про `hidden`, а не про видимость: вся карточка
        прогресса до запуска спрятана, и «не видно» там ответило бы «да»
        на любой вопрос — проверка вышла бы пустой.
        """
        return self.page.evaluate("() => document.getElementById('pbList').hidden")

    def test_one_book_needs_no_list(self):
        """Список из одной строки повторил бы полосу над собой слово в
        слово."""
        self.draw([self.book(title="Книга А")])
        self.assertTrue(self.folded())
        self.quiet()

    def test_two_books_do_need_it(self):
        """Иначе «убрать лишнее» легко превращается в «не показывать
        никогда»."""
        self.draw([self.book(title="Книга А"), self.book(title="Книга Б")])
        self.assertFalse(self.folded())
        self.quiet()

    def test_a_book_that_has_no_count_yet_gets_a_running_bar(self):
        """Сколько глав всего — известно только после оглавления. До него
        процентов взять неоткуда, и нарисованный ноль был бы враньём."""
        self.draw([self.book(title="Книга А", stage="search", total=0,
                             done=0),
                   self.book(title="Книга Б")])

        self.assertEqual(
            self.page.locator("#pbList .pb").nth(0)
                .locator(".bar.waiting").count(), 1)
        self.quiet()

    def test_a_book_that_fell_says_why_right_there(self):
        """Строка упавшей книги — единственный след того, чем она
        кончилась: очередь к тому времени показывает уже следующую."""
        self.draw([self.book(title="Книга А", stage="error",
                             message="сайт не разрешается по имени"),
                   self.book(title="Книга Б")])

        bad = self.page.locator("#pbList .pb").nth(0)
        self.assertIn("сайт не разрешается", bad.inner_text())
        self.assertEqual(bad.locator(".pb-msg.bad").count(), 1)
        self.quiet()

    def test_a_book_that_finished_is_not_called_broken(self):
        """Цвет тут — половина сообщения: красная строка у пройденной
        книги отправила бы человека чинить исправное."""
        self.draw([self.book(title="Книга А", stage="done",
                             message="Скачано глав: 10", done=10),
                   self.book(title="Книга Б")])

        good = self.page.locator("#pbList .pb").nth(0)
        self.assertIn("Скачано глав: 10", good.inner_text())
        self.assertEqual(good.locator(".pb-msg.bad").count(), 0)
        self.quiet()

    def tick_with(self, progress) -> str:
        """Один опрос задачи с подменённым сервером — и что вышло в строке
        под полосой."""
        return self.page.evaluate(
            """async (progress) => {
                const server = window.call;
                window.call = async () => ({job: {id: 'проверка', progress}});
                try{ await tick(); }finally{ window.call = server; }
                return document.getElementById('sMethod').textContent;
            }""", progress)

    def test_the_line_about_threads_gives_way_to_the_count_of_books(self):
        """Потоки при нескольких книгах у каждой свои, и раздают их по
        расчёту, а не поровну: одна строка на всех врала бы."""
        said = self.tick_with({
            "stage": "download", "at_once": 2, "threads": 1,
            "each": [self.book(title="Книга А"),
                     self.book(title="Книга Б")]})
        self.assertIn("2 книги разом", said)

        # Пройденная книга не «разом»: она уже никуда не идёт, а список
        # её строку держит — он же и история прогона.
        said = self.tick_with({
            "stage": "download", "at_once": 2, "threads": 1,
            "each": [self.book(title="Книга А"),
                     self.book(title="Книга Б", stage="done")]})
        self.assertIn("1 книга разом", said)
        self.quiet()

    def test_one_book_still_gets_the_line_about_threads(self):
        """Книга одна — считать нечего, и старая строка остаётся той же:
        ради неё этот расчёт когда-то и делали."""
        said = self.tick_with({
            "stage": "download", "at_once": 1, "threads": 3, "proxies": 3})
        self.assertIn("3 потока", said)
        self.quiet()

    def test_the_list_goes_away_when_the_run_does(self):
        """Полосы прошлого прогона над новым — хуже, чем ничего."""
        self.draw([self.book(title="Книга А"), self.book(title="Книга Б")])
        self.draw([])

        self.assertTrue(self.folded())
        self.assertEqual(self.page.locator("#pbList .pb").count(), 0)
        self.quiet()


class TestTheDnsKnob(PageTestCase):
    """Куда спрашивать имена сайтов — выбором, а не правкой файла.

    Настройка нужна ровно тогда, когда ничего не качается, и лезть в
    этот момент в `config.json` человеку негде и некогда.
    """

    ANSWER = {"url": "", "choices": [
        {"key": "", "name": "как в системе", "url": ""},
        {"key": "cloudflare", "name": "Cloudflare",
         "url": "https://cloudflare-dns.com/dns-query"}]}

    def filled(self, answer=None):
        """Нарисовать выбор так, как его рисует ответ сервера."""
        self.page.evaluate("(data) => dnsFill(data)", answer or self.ANSWER)

    def items(self) -> list:
        """Пункты списка. Спрашиваем их, а не видимый текст: свёрнутый
        список показывает одну выбранную строку, и по ней о содержимом
        не судят."""
        return self.page.evaluate(
            """() => [...document.querySelectorAll('#dlDns .dropdown-item')]
                     .map(one => one.textContent)""")

    def test_the_choices_reach_the_list(self):
        self.filled()
        said = self.items()

        self.assertIn("как в системе", said)
        self.assertIn("Cloudflare", said)

    def test_your_own_address_is_always_offered(self):
        """Известные адреса закрывают там же, где и всё остальное."""
        self.filled()
        self.assertIn("свой адрес", self.items())

    def chosen(self) -> str:
        """Что выбрано в списке. Список свой, и `value` у него своё."""
        return self.page.evaluate("() => dnsMenu && dnsMenu.value")

    def pick(self, name: str) -> None:
        """Выбрать пункт так, как это делает человек: нажать и нажать."""
        self.page.click("#dlDns .dropdown-toggle")
        self.page.click(f"#dlDns .dropdown-item:text-is('{name}')")

    def test_the_field_for_your_own_shows_only_when_it_is_chosen(self):
        self.filled()
        self.assertTrue(self.page.evaluate(
            "() => document.getElementById('dlDnsOwn').hidden"))

        self.pick("свой адрес")
        self.assertFalse(self.page.evaluate(
            "() => document.getElementById('dlDnsOwn').hidden"))
        self.quiet()

    def test_a_saved_address_is_shown_as_chosen(self):
        """Иначе рабочая настройка выглядит как «как в системе», и
        человек меняет то, что уже работает."""
        self.filled({**self.ANSWER,
                     "url": "https://cloudflare-dns.com/dns-query"})

        self.assertEqual(self.chosen(), "cloudflare")

    def test_an_address_nobody_offers_is_shown_as_your_own(self):
        """Спрячь мы его под «как в системе» — соврали бы про рабочую
        настройку, и найти её было бы негде."""
        self.filled({**self.ANSWER, "url": "https://свой.example/dns-query"})

        self.assertEqual(self.chosen(), "свой")
        self.assertIn("свой.example", self.page.evaluate(
            "() => document.getElementById('dlDnsOwn').value"))

    def sent_after(self, prepare: str) -> dict:
        """Что уйдёт на сервер, если перед нажатием сделать вот это."""
        return self.page.evaluate(
            """async (prepare) => {
                const server = window.call;
                let body = null;
                window.call = async (url, payload) => {
                    body = payload;
                    return {url: payload.url, choices: []};
                };
                try{
                    eval(prepare);
                    await document.getElementById('dlDnsSave').onclick();
                }finally{ window.call = server; }
                return body;
            }""", prepare)

    def test_the_chosen_address_is_what_gets_sent(self):
        self.filled()
        sent = self.sent_after("dnsMenu.set('cloudflare')")

        self.assertEqual(sent["url"], "https://cloudflare-dns.com/dns-query")
        self.quiet()

    def test_your_own_address_is_what_gets_sent_when_chosen(self):
        self.filled()
        sent = self.sent_after(
            "dnsMenu.set('свой');"
            "document.getElementById('dlDnsOwn').value ="
            " '  https://свой.example/dns-query  ';")

        # Пробелы по краям человек вставляет вместе с адресом постоянно.
        self.assertEqual(sent["url"], "https://свой.example/dns-query")
        self.quiet()


class TestTheCountersSayOutOfHowMany(PageTestCase):
    """«Скачано 9» не отвечало на единственный вопрос, который в это время
    и задают: сколько ещё ждать.

    Ни «из скольки», ни «сколько осталось» на экране не было — только
    проценты, а из них главы в уме не считают.
    """

    def stats(self, progress) -> dict:
        """Один опрос задачи с подменённым сервером — и что вышло в
        строке счётчиков."""
        return self.page.evaluate(
            """async (progress) => {
                const server = window.call;
                window.call = async () => ({job: {id: 'проверка', progress}});
                try{ await tick(); }finally{ window.call = server; }
                return {
                    line: document.querySelector('#progress .stats').textContent,
                    of: document.getElementById('sOf').textContent,
                    left: document.getElementById('sLeft').textContent};
            }""", progress)

    def test_it_says_out_of_how_many_and_how_many_are_left(self):
        got = self.stats({"stage": "download", "downloaded": 9,
                          "done": 9, "total": 41})

        self.assertIn("скачано 9 из 41", got["line"])
        self.assertIn("осталось глав 32", got["line"])
        self.quiet()

    def test_the_skipped_and_the_fallen_are_not_still_awaited(self):
        """Пропущенная глава и упавшая — тоже позади. Считай мы остаток
        по одним скачанным, он застрял бы и до нуля не дошёл."""
        got = self.stats({"stage": "download", "downloaded": 5,
                          "skipped": 3, "failed": 2, "done": 10,
                          "total": 41})

        self.assertIn("осталось глав 31", got["line"])
        self.quiet()

    def test_the_word_is_not_the_same_as_the_stopwatch_uses(self):
        """Рядом идёт секундомер со своим «осталось 02:12». Два
        одинаковых слова про разное на одной строке путали бы сильнее,
        чем отсутствие второго."""
        got = self.stats({"stage": "download", "downloaded": 9,
                          "done": 9, "total": 41})

        self.assertNotIn("осталось 32", got["left"])
        self.assertIn("глав", got["left"])
        self.quiet()

    def test_before_the_table_of_contents_there_is_nothing_to_say(self):
        """Сколько глав в отрезке — известно только после оглавления.
        «Из 0» и «осталось глав 0» до него были бы враньём."""
        got = self.stats({"stage": "toc", "downloaded": 0, "done": 0,
                          "total": 0})

        self.assertFalse(got["of"])
        self.assertFalse(got["left"])
        self.quiet()

    def test_the_count_is_of_this_run_not_of_the_whole_book(self):
        """Качаем мы отрезок. У книги в 1868 глав, с которой берут сорок
        одну последнюю, «из 1868» было бы враньём — а взять это число
        задача никуда и не даёт: в `total` лежат главы прогона."""
        got = self.stats({"stage": "download", "downloaded": 9, "done": 9,
                          "total": 41, "message": "Глава 1832 из 1868"})

        self.assertIn("из 41", got["of"])
        self.quiet()


class TestTheRunSettingsAreAlwaysReachable(PageTestCase):
    """Потоки, таймауты и «книг разом» лежали в карточке «куда сохранять».

    А та показывается только после того, как книгу нашли поиском. Кто
    качает очередью — а очередь и есть главный способ, когда книг много, —
    до этих полей не добирался вовсе: числа применялись, но менять их
    было негде.
    """

    def visible(self, name: str) -> bool:
        return self.page.evaluate(
            "(id) => { const e = document.getElementById(id);"
            " return !!e && e.offsetParent !== null; }", name)

    def test_they_are_visible_without_finding_a_book_first(self):
        for name in ("dlThreads", "dlBooks", "tmRead", "tmConnect"):
            self.assertTrue(self.visible(name), name)
        self.quiet()

    def test_the_multithreading_mode_is_reachable_too(self):
        """Без него «всегда N потоков» не выбрать, а он и есть ответ на
        «почему качает в один поток»."""
        self.assertTrue(self.page.evaluate(
            "() => { const b = document.querySelector('#runCard .pickmode');"
            " return !!b && b.offsetParent !== null; }"))
        self.quiet()

    def test_the_queue_sends_how_many_books_at_once(self):
        """Ручку добавили, а в запрос очереди вписать забыли: своё число
        не работало, сервер каждый раз считал сам."""
        sent = self.page.evaluate("() => dqRunSettings()")

        self.assertIn("books", sent)
        self.quiet()

    def test_zero_books_stays_zero_and_does_not_become_one(self):
        """Ноль тут значащий: он и означает «посчитай сам по прокси».
        Подставь мы вместо него единицу — расчёт бы никогда не включился."""
        sent = self.page.evaluate(
            """() => { document.getElementById('dlBooks').value = '0';
                       return dqRunSettings(); }""")

        self.assertEqual(sent["books"], 0)
        self.quiet()

    def test_a_number_typed_by_hand_reaches_the_queue(self):
        sent = self.page.evaluate(
            """() => { document.getElementById('dlBooks').value = '4';
                       return dqRunSettings(); }""")

        self.assertEqual(sent["books"], 4)
        self.quiet()


class TestTheCheckupOffersToFixWhatItFound(PageTestCase):
    """Осмотр говорил, что не так, и на этом обрывался.

    Дальше человек оставался с папкой в несколько сотен файлов и списком
    имён — без единой кнопки, которая бы что-нибудь с ними сделала.
    """

    def draw(self, kind, where=("0042 - Имя.txt",)):
        """Рисуем находку того рода, что интересует, и смотрим на кнопки."""
        return self.page.evaluate(
            """([kind, where]) => {
                 cuShow({troubles: [{kind, kind_name: 'Находка',
                                     where, count: where.length}]});
                 const box = document.getElementById('cuFound');
                 return [...box.querySelectorAll('button')]
                        .map(b => b.className + '|' + b.textContent);
               }""", [kind, list(where)])

    def test_a_cut_chapter_can_have_its_head_taken_off(self):
        """То самое: осмотр спотыкается о название книги и заголовок."""
        self.assertTrue(any("cu-head" in one for one in self.draw("cut")))
        self.quiet()

    def test_a_cut_chapter_can_be_downloaded_again(self):
        self.assertTrue(any("cu-again" in one for one in self.draw("cut")))
        self.quiet()

    def test_missing_chapters_are_offered_a_download(self):
        """«Ну и типа если пропущены главы пусть они скачиваются»."""
        said = self.draw("missing", ["7–9"])
        self.assertTrue(any("cu-again" in one for one in said))
        self.quiet()

    def test_missing_chapters_are_not_offered_a_head_cut(self):
        """Снимать шапку с главы, которой нет, не с чего."""
        said = self.draw("missing", ["7–9"])
        self.assertFalse(any("cu-head" in one for one in said))
        self.quiet()

    def test_a_finding_about_names_gets_no_buttons(self):
        """«Общий хвост имён» ни докачкой, ни шапкой не чинится, и кнопка
        под ним обещала бы починку, которой нет."""
        self.assertEqual(self.draw("tail", ["- глава"]), [])
        self.quiet()

    def test_the_buttons_say_what_they_do(self):
        """Кнопка без слов — это кнопка, которую боятся нажать."""
        for one in self.draw("cut"):
            self.assertTrue(one.split("|", 1)[1].strip(), one)
        self.quiet()


class TestTheRunSettingsLineUp(PageTestCase):
    """Подписи полей разной длины, и поля от этого разъезжались.

    «Таймаут соединения, с» в четверть ширины не помещается: подпись
    переносится на вторую строку, вопросик — на третью, колонка растёт, а
    соседние поля остаются наверху. Два поля на одной высоте, два ниже на
    строку — читается как поломка, и человек об этом написал.
    """

    FIELDS = ("tmRead", "tmConnect", "dlThreads", "dlBooks")

    def tops(self):
        return self.page.evaluate(
            "(ids) => ids.map(id => Math.round("
            " document.getElementById(id).getBoundingClientRect().top))",
            list(self.FIELDS))

    def widths(self):
        return self.page.evaluate(
            "(ids) => ids.map(id => Math.round("
            " document.getElementById(id).getBoundingClientRect().width))",
            list(self.FIELDS))

    def test_all_four_fields_stand_at_one_height(self):
        tops = self.tops()
        self.assertEqual(len(set(tops)), 1, tops)
        self.quiet()

    def test_the_fields_are_of_one_width(self):
        """Четыре ручки в ряд, и одна вдвое шире соседки — та же
        небрежность, только по горизонтали."""
        wide = self.widths()
        self.assertLessEqual(max(wide) - min(wide), 2, wide)
        self.quiet()

    def test_the_long_label_really_does_wrap(self):
        """Иначе проверка выше ничего не проверяет: подписи в одну строку
        выровнялись бы и без нас."""
        rows = self.page.evaluate(
            """() => { const l = document.querySelector(
                         '#runCard label[for=tmConnect]');
                       const one = parseFloat(
                         getComputedStyle(l).lineHeight) || 16;
                       return l.getBoundingClientRect().height / one; }""")
        self.assertGreater(rows, 1.5)
        self.quiet()


class TestTheLibraryCardTalksToTheQueue(PageTestCase):
    """Карточка звала «в качалку» книгу, которая в качалке уже стояла.

    Библиотека и очередь жили порознь: кнопка заполняла форму поиска,
    книга при этом качалась прямо сейчас, и человек спросил, взаимодействуют
    ли они вообще.
    """

    def deed(self, **book):
        row = dict(key="k", name="Книга", source="mvlempyr",
                   address="https://x/y", folder="/книги/тут",
                   chapters=0, last=0, fresh=0, queued="")
        row.update(book)
        return self.page.evaluate("(b) => libDeed(b)", row)

    def test_a_book_being_downloaded_says_so(self):
        said = self.deed(queued="running", last=100, chapters=500)
        self.assertIn("качается", said["text"].lower())
        self.assertTrue(said["standing"])

    def test_a_book_waiting_in_the_queue_says_so(self):
        said = self.deed(queued="waiting")
        self.assertIn("очеред", said["text"].lower())
        self.assertTrue(said["standing"])

    def test_a_half_downloaded_book_is_offered_to_continue(self):
        """Это не «вышли новые главы», а прерванный прогон, и слово тут
        другое — человек ждёт именно его."""
        said = self.deed(last=300, chapters=530)
        self.assertIn("продолжить", said["text"].lower())
        self.assertFalse(said["standing"])

    def test_new_chapters_are_offered_by_their_number(self):
        said = self.deed(last=789, chapters=794, fresh=5)
        self.assertIn("5", said["text"])
        self.assertFalse(said["standing"])

    def test_a_book_never_downloaded_is_offered_a_download(self):
        said = self.deed(chapters=530)
        self.assertIn("скачать", said["text"].lower())

    def test_a_finished_book_is_not_called_unfinished(self):
        """Скачана целиком — «продолжить» на ней было бы неправдой."""
        said = self.deed(last=546, chapters=546)
        self.assertNotIn("продолжить", said["text"].lower())
        self.assertFalse(said["standing"])

    def test_a_queued_book_is_never_offered_a_second_go(self):
        """Поставить её второй раз — это то, на что человек и жаловался."""
        for state in ("waiting", "running"):
            said = self.deed(queued=state, fresh=5, last=789, chapters=794)
            self.assertTrue(said["standing"], state)


class TestTheRunSaysHowFastAndWhy(PageTestCase):
    """Счётчик глав замирает — и по нему не понять, работа идёт или встала.

    При тринадцати книгах разом общая цифра не отвечает ни на «быстро или
    медленно», ни на «чего ждём»: своё состояние есть у каждой книги, а
    наверху его не видно. Замерший счётчик читается как «зависло».
    """

    def draw(self, **one):
        """Текст первой строки. Книг всегда две: при одной список строк
        не рисуется вовсе — там всё говорит общая полоса."""
        row = dict(id="a", title="Книга", stage="download", total=100,
                   done=40, downloaded=40)
        row.update(one)
        other = dict(id="b", title="Соседка", stage="download", total=10,
                     done=1)
        return self.page.evaluate(
            "(rows) => { pbDraw(rows);"
            " return document.querySelector('#pbList .pb').innerText; }",
            [row, other])

    def test_the_speed_is_shown(self):
        self.assertIn("глав/мин", self.draw(speed=12.5))
        self.quiet()

    def test_how_long_is_left_for_this_book(self):
        """Общее «осталось» складывает книгу, которая летит, с той, что
        стоит на повторах."""
        said = self.draw(eta=600)
        self.assertRegex(said, r"~\s*10 мин")
        self.quiet()

    def test_what_it_weighed(self):
        self.assertIn("МБ", self.draw(bytes=5 * 1024 * 1024))
        self.quiet()

    def test_a_finished_book_is_not_told_it_has_speed(self):
        """У законченной книги «12 глав/мин» — вчерашняя правда."""
        said = self.draw(stage="done", speed=12.5, eta=600)
        self.assertNotIn("глав/мин", said)
        self.quiet()

    def test_switches_and_retries_hide_in_the_tip(self):
        """В строке они шум, а при разборе беды — первое, что нужно."""
        tip = self.page.evaluate(
            """(rows) => { pbDraw(rows);
                 const via = document.querySelector('#pbList .pb-via');
                 return via ? via.title : ''; }""",
            [dict(id="a", title="Книга", stage="download", total=100, done=40,
                  proxy="10.0.0.1:8080", switches=2, retries=7),
             dict(id="b", title="Соседка", stage="download")])
        self.assertIn("2", tip)
        self.assertIn("7", tip)
        self.quiet()

    def test_a_clean_address_says_so_plainly(self):
        tip = self.page.evaluate(
            """(rows) => { pbDraw(rows);
                 const via = document.querySelector('#pbList .pb-via');
                 return via ? via.title : ''; }""",
            [dict(id="a", title="Книга", stage="download",
                  proxy="10.0.0.1:8080"),
             dict(id="b", title="Соседка", stage="download")])
        self.assertNotIn("повторов", tip)
        self.quiet()


class TestTheLogIsOnTheScreen(PageTestCase):
    """Журнал писался всегда, но на экран не выходил.

    Чтобы узнать, через что качалась книга и почему встала, надо было
    лезть в файл. А очередь из тринадцати книг пишет вперемешку.
    """

    def load(self, lines):
        return self.page.evaluate(
            """(lines) => { DG_LINES = lines; DG_ONLY = ''; dgLogDraw();
                 return document.getElementById('dgLog').innerText; }""",
            lines)

    def rows(self):
        return [
            {"at": "10:00", "kind": "info", "book": "Одна", "text": "первая"},
            {"at": "10:01", "kind": "warn", "book": "Другая", "text": "вторая"},
            {"at": "10:02", "kind": "info", "book": "Одна", "text": "третья"},
        ]

    def test_all_the_books_are_shown_at_first(self):
        said = self.load(self.rows())
        self.assertIn("первая", said)
        self.assertIn("вторая", said)
        self.quiet()

    def test_a_click_leaves_one_book(self):
        self.load(self.rows())
        said = self.page.evaluate(
            """(who) => { dgLogOnly(who);
                 return document.getElementById('dgLog').innerText; }""",
            "Одна")
        self.assertIn("первая", said)
        self.assertNotIn("вторая", said)
        self.quiet()

    def test_clicking_the_same_book_again_shows_everything(self):
        """Иначе снять отбор было бы нечем."""
        self.load(self.rows())
        said = self.page.evaluate(
            """(who) => { dgLogOnly(who); dgLogOnly(who);
                 return document.getElementById('dgLog').innerText; }""",
            "Одна")
        self.assertIn("вторая", said)
        self.quiet()

    def test_the_book_name_is_not_repeated_in_a_filtered_list(self):
        """Там оно стояло бы в каждой строке и мешало читать."""
        self.load(self.rows())
        count = self.page.evaluate(
            """(who) => { dgLogOnly(who);
                 return document.querySelectorAll('#dgLog .ln-book').length; }""",
            "Одна")
        self.assertEqual(count, 0)
        self.quiet()

    def test_whose_line_it_is_shows_when_everything_is_shown(self):
        self.load(self.rows())
        count = self.page.evaluate(
            "() => document.querySelectorAll('#dgLog .ln-book').length")
        self.assertEqual(count, 3)
        self.quiet()


class TestTheRunEndsWithAnAnswer(PageTestCase):
    """«Скачано книг: 10 из 13» не говорит, какие три и почему."""

    def sum(self, each):
        return self.page.evaluate(
            """(each) => { dgSummary({each});
                 const box = document.getElementById('dgSum');
                 return box.hidden ? '' : box.innerText; }""", each)

    def test_the_books_that_failed_are_named(self):
        said = self.sum([
            {"title": "Одна", "stage": "done"},
            {"title": "Другая", "stage": "error", "message": "сайт не ответил"},
        ])
        self.assertIn("Другая", said)
        self.assertIn("сайт не ответил", said)
        self.quiet()

    def test_a_clean_run_does_not_invent_troubles(self):
        said = self.sum([{"title": "Одна", "stage": "done"},
                         {"title": "Другая", "stage": "done"}])
        self.assertNotIn("Не вышло", said)
        self.quiet()

    def test_it_says_what_to_do_next(self):
        """Список бед без ответа «и что теперь» — половина ответа."""
        said = self.sum([{"title": "Одна", "stage": "error", "message": "беда"}])
        self.assertIn("очередь", said.lower())
        self.quiet()

    def test_nothing_at_all_shows_nothing(self):
        self.assertEqual(self.sum([]), "")
        self.quiet()


class TestWhereTheHalvedBooksGo(PageTestCase):
    """«Поделить главы» отвечало «Выберите, куда сохранить».

    Человек выбирал книгу, жал кнопку и получал отказ — и читал его как
    «не работает». Поле «куда сохранить» стояло пустым, и заполнить его
    было неоткуда: рядом с исходником писать нельзя, а куда ещё —
    программа не подсказывала.
    """

    def fill(self, chosen, was=""):
        return self.page.evaluate(
            """([chosen, was]) => {
                 CHOSEN.fmCutList = chosen;
                 document.getElementById('fmCutBase').value = was;
                 fmCutFill();
                 return document.getElementById('fmCutBase').value;
               }""", [chosen, was])

    def test_the_folder_is_filled_in_from_the_book(self):
        said = self.fill(["/книги/Работа/книга.md"])
        self.assertTrue(said.startswith("/книги/Работа/"))
        self.assertNotEqual(said, "/книги/Работа")

    def test_it_is_not_the_folder_of_the_book_itself(self):
        """Писать поверх исходника нельзя: не понравится — сверять будет
        не с чем, а работа необратима."""
        self.assertNotEqual(self.fill(["/книги/Работа/книга.md"]),
                            "/книги/Работа")

    def test_a_windows_path_stays_windows(self):
        said = self.fill(["C:\\Книги\\Работа\\книга.md"])
        self.assertIn("\\", said)
        self.assertNotIn("/", said)

    def test_what_the_person_typed_is_not_overwritten(self):
        self.assertEqual(self.fill(["/книги/Работа/книга.md"], "/своё/место"),
                         "/своё/место")

    def test_nothing_chosen_fills_nothing(self):
        self.assertEqual(self.fill([]), "")


class TestWhyTheHalvingFailed(PageTestCase):
    """Отказ без причины читается как «не работает».

    Сервер называет причину по каждой книге, но когда не поделилась ни
    одна, ответ приезжает отказом — и весь этот список пропадал вместе с
    ним. На экране оставалось «Ни одну книгу поделить не вышло»: правда,
    по которой чинить нечего.
    """

    def refuse(self, failed, message="Поделить не вышло"):
        """Прогоняем деление, где сервер отвечает отказом с причинами."""
        return self.page.evaluate(
            """async ([failed, message]) => {
                 window.call = async () => {
                   const err = new Error(message);
                   err.failed = failed;
                   throw err;
                 };
                 await fmCutRun();
                 const table = document.getElementById('fmCutTable');
                 return {shown: !table.hidden, text: table.innerText,
                         note: document.getElementById('fmCutNote').innerText};
               }""", [failed, message])

    def test_the_reason_is_on_the_screen(self):
        said = self.refuse([{"file": "книга.md", "error": "нет заголовков"}])
        self.assertTrue(said["shown"])
        self.assertIn("книга.md", said["text"])
        self.assertIn("нет заголовков", said["text"])
        self.quiet()

    def test_every_book_is_named(self):
        said = self.refuse([{"file": "одна.md", "error": "нет заголовков"},
                            {"file": "вторая.md", "error": "не читается"}])
        self.assertIn("одна.md", said["text"])
        self.assertIn("вторая.md", said["text"])
        self.quiet()

    def test_an_old_answer_is_not_left_on_the_screen(self):
        """Строки прошлого прогона рядом с новым отказом — вранье."""
        self.page.evaluate(
            """() => { const table = document.getElementById('fmCutTable');
                       table.innerHTML = '<div class="tr">старое</div>';
                       table.hidden = false; }""")
        said = self.refuse([{"file": "книга.md", "error": "нет заголовков"}])
        self.assertNotIn("старое", said["text"])
        self.quiet()

    def test_a_refusal_without_details_shows_no_empty_table(self):
        said = self.refuse([])
        self.assertFalse(said["shown"])
        self.quiet()


class TestWhereTheCutBookLanded(PageTestCase):
    """Книга легла рядом с исходником — найти её надо по новому имени."""

    def show(self, files):
        return self.page.evaluate(
            """async (files) => {
                 window.call = async () => ({files, failed: [],
                                             chapters: 2, made: 4, parts: 2,
                                             output: '/куда'});
                 await fmCutRun();
                 return document.getElementById('fmCutTable').innerText;
               }""", files)

    def test_the_new_name_is_shown(self):
        said = self.show([{"file": "книга.md", "saved": "книга (поделено).md",
                           "was": 2, "now": 4, "output": "/куда/книга (поделено).md"}])
        self.assertIn("книга (поделено).md", said)
        self.quiet()

    def test_the_same_name_is_not_repeated_twice(self):
        """Стрелка «книга.md → книга.md» не говорит ничего."""
        said = self.show([{"file": "книга.md", "saved": "книга.md",
                           "was": 2, "now": 4, "output": "/куда/книга.md"}])
        self.assertNotIn("книга.md →", said)
        self.quiet()


class TestManagingTheQueueByHand(PageTestCase):
    """Строка очереди: отложить, поправить главы, переставить, отобрать."""

    def show(self, items, only=False):
        """Рисуем очередь так, как её отдал бы сервер."""
        return self.page.evaluate(
            """([items, only]) => {
                 dqItems = items;
                 dqState = {books: items.length};
                 document.getElementById('dqOnly').checked = only;
                 document.getElementById('dqList').hidden = false;
                 dqRender();
                 return document.getElementById('dqList').innerText;
               }""", [items, only])

    def book(self, **fields):
        row = {"id": "к1", "title": "Книга", "state": "waiting",
               "source": "mvl", "base": "/книги", "folder": "Книга",
               "first": 0, "last": 0, "ready": True, "origin": {}}
        row.update(fields)
        return row

    def test_a_waiting_book_can_be_put_aside(self):
        self.show([self.book()])
        self.assertIn("Отложить", self.page.locator("#dqList").inner_text())
        self.quiet()

    def test_an_aside_book_is_offered_back(self):
        self.show([self.book(state="skipped")])
        said = self.page.locator("#dqList").inner_text()
        self.assertIn("Вернуть", said)
        self.assertNotIn("Отложить", said)
        self.quiet()

    def test_an_aside_row_is_seen_to_be_aside(self):
        """Подписи мало: строка должна отличаться собой."""
        self.show([self.book(state="skipped")])
        self.assertTrue(self.page.evaluate(
            """() => document.querySelector('#dqList .q')
                             .classList.contains('aside')"""))
        self.quiet()

    def test_the_chapters_are_edited_in_the_row(self):
        """Ради двух чисел возвращаться в форму и терять там книгу дорого."""
        self.show([self.book(first=100, last=200)])
        got = self.page.evaluate(
            """() => [...document.querySelectorAll('#dqList .q-range input')]
                     .map(one => one.value)""")
        self.assertEqual(got, ["100", "200"])
        self.quiet()

    def test_the_chapters_are_empty_when_the_row_decides_for_itself(self):
        """Ноль в поле читался бы как «качать с нулевой главы»."""
        self.show([self.book()])
        got = self.page.evaluate(
            """() => [...document.querySelectorAll('#dqList .q-range input')]
                     .map(one => one.value)""")
        self.assertEqual(got, ["", ""])
        self.quiet()

    def test_every_row_can_be_dragged(self):
        self.show([self.book(id="к1"), self.book(id="к2", folder="Вторая")])
        self.assertEqual(self.page.evaluate(
            """() => [...document.querySelectorAll('#dqList .q-grab')]
                     .filter(one => one.draggable).length"""), 2)
        self.quiet()

    def test_the_filter_leaves_what_still_needs_doing(self):
        """После ночи в списке три книги, которые не вышли, и сорок семь
        готовых — и первые три приходится искать глазами."""
        said = self.show([self.book(id="к1", folder="Готовая", state="done"),
                          self.book(id="к2", folder="Ждущая"),
                          self.book(id="к3", folder="Битая", state="failed"),
                          self.book(id="к4", folder="Отложенная",
                                    state="skipped")], only=True)
        self.assertIn("Ждущая", said)
        self.assertIn("Битая", said)
        self.assertNotIn("Готовая", said)
        self.assertNotIn("Отложенная", said)
        self.quiet()

    def test_it_says_how_many_it_hid(self):
        """Молча спрятать половину списка — худшее, что тут можно."""
        self.show([self.book(id="к1", state="done"),
                   self.book(id="к2")], only=True)
        self.assertIn("1", self.page.locator("#dqHidden").inner_text())
        self.quiet()

    def test_without_the_filter_everything_is_shown(self):
        said = self.show([self.book(id="к1", folder="Готовая", state="done"),
                          self.book(id="к2", folder="Ждущая")])
        self.assertIn("Готовая", said)
        self.assertEqual(self.page.locator("#dqHidden").inner_text(), "")
        self.quiet()


class TestTheLibraryWarnsWhenQueueing(PageTestCase):
    """Ставя книгу в очередь, человек не помнит, качал ли он её."""

    def said(self, known):
        return self.page.evaluate("(known) => dqKnown(known)", known)

    def test_it_says_how_much_is_already_downloaded(self):
        said = self.said({"last": 400, "chapters": 402, "fresh": 2})
        self.assertIn("400", said)
        self.assertIn("2", said)
        self.quiet()

    def test_an_unknown_book_says_nothing(self):
        self.assertEqual(self.said(None), "")
        self.quiet()

    def test_a_book_nobody_finished_downloading_says_nothing(self):
        """Запись есть, а глав на диске нет: говорить не о чем."""
        self.assertEqual(self.said({"last": 0, "chapters": 402, "fresh": 0}),
                         "")
        self.quiet()


class TestTheQueueRowsSpeakForThemselves(PageTestCase):
    """К-F на живой странице: этап на строке и линия скорости."""

    def draw(self, rows):
        self.page.evaluate("(rows) => pbDraw(rows)", rows)

    def book(self, **fields):
        row = {"id": "к", "title": "Книга", "stage": "download",
               "total": 10, "done": 4}
        row.update(fields)
        return row

    def stages(self):
        return self.page.evaluate(
            """() => [...document.querySelectorAll('#pbList .pb')]
                     .map(one => one.dataset.stage)""")

    def test_the_stage_is_on_the_row(self):
        self.draw([self.book(title="А", stage="download"),
                   self.book(title="Б", stage="error")])
        self.assertEqual(self.stages(), ["download", "error"])
        self.quiet()

    def test_only_the_downloading_one_is_alive(self):
        """«Ищем книгу» — тоже не кончила, а работы за ней никакой."""
        self.draw([self.book(title="А", stage="download"),
                   self.book(title="Б", stage="search"),
                   self.book(title="В", stage="done")])
        got = self.page.evaluate(
            """() => [...document.querySelectorAll('#pbList .pb')]
                     .map(one => one.classList.contains('live'))""")
        self.assertEqual(got, [True, False, False])
        self.quiet()

    def sparks(self):
        return self.page.locator("#pbList .pb-spark").count()

    def test_one_measurement_draws_nothing(self):
        """Линия из одной точки — это точка."""
        self.draw([self.book(title="А", speed=5), self.book(title="Б")])
        self.assertEqual(self.sparks(), 0)
        self.quiet()

    def test_the_line_appears_once_there_is_something_to_draw(self):
        for speed in (5, 7, 6, 9):
            self.draw([self.book(title="А", speed=speed),
                       self.book(title="Б", speed=speed)])
        self.assertEqual(self.sparks(), 2)
        self.quiet()

    def test_a_stall_is_marked(self):
        for speed in (9, 7, 5, 0):
            self.draw([self.book(title="А", speed=speed),
                       self.book(title="Б", speed=speed)])
        self.assertEqual(
            self.page.locator("#pbList .pb-spark.stalled").count(), 2)
        self.quiet()

    def test_a_finished_book_gets_no_line(self):
        """У кончившей рисовать нечего: она кончила."""
        for speed in (5, 7, 6):
            self.draw([self.book(title="А", speed=speed),
                       self.book(title="Б", speed=speed)])
        self.draw([self.book(title="А", stage="done"),
                   self.book(title="Б", stage="done")])
        self.assertEqual(self.sparks(), 0)
        self.quiet()

    def test_a_finished_book_stops_being_measured(self):
        """Её нули дорисовали бы падение, которого не было: книга не
        встала, а кончилась. Запустят ту же — линия начнётся с провала."""
        for speed in (5, 7, 6):
            self.draw([self.book(title="А", speed=speed)])
        for _ in range(4):
            self.draw([self.book(title="А", stage="done")])

        self.assertEqual(
            self.page.evaluate("() => PB_SPEED['А'].length"), 3)
        self.quiet()

    def test_redrawing_does_not_add_measurements(self):
        """Щелчок по строке перерисовывает список — и записал бы те же
        цифры ещё раз, растянув линию из ничего."""
        self.draw([self.book(title="А", speed=5), self.book(title="Б")])
        self.page.evaluate("() => { pbDraw(); pbDraw(); pbDraw(); }")
        self.assertEqual(self.sparks(), 0)
        self.quiet()


class TestSortingOutTheLibrary(PageTestCase):
    """Сотня книг в порядке скачивания — сотня книг в случайном порядке."""

    def show(self, books, **more):
        """Рисуем библиотеку так, как её отдал бы сервер."""
        return self.page.evaluate(
            """([books, more]) => {
                 libBooks = books;
                 libState = {};
                 libPick = '';
                 libKinds = new Set(more.kinds || []);
                 libTicked = new Set(more.ticked || []);
                 libSort = more.sort || 'fresh';
                 libGroup = more.group || 'none';
                 document.getElementById('lbFilter').value = more.word || '';
                 document.getElementById('lbPickOn').checked = !!more.picking;
                 libShow();
                 return [...document.querySelectorAll('#lbList .lb')]
                        .map(one => one.dataset.book);
               }""", [books, more])

    def book(self, key, **fields):
        row = {"key": key, "title": key, "name": key, "author": "",
               "folder": "/книги/" + key, "marks": [], "auto": [],
               "mark_names": [], "auto_names": [], "tags": [],
               "genres_shown": [], "site_tags_shown": [],
               "chapters": 0, "last": 0, "fresh": 0}
        row.update(fields)
        return row

    def test_the_ones_with_new_chapters_come_first(self):
        """Ради них в библиотеку и заходят."""
        got = self.show([self.book("А"), self.book("Б", fresh=5),
                         self.book("В", fresh=1)])
        self.assertEqual(got[:2], ["Б", "В"])
        self.quiet()

    def test_by_name_is_by_name(self):
        got = self.show([self.book("Ярость"), self.book("Астра"),
                         self.book("Небо")], sort="title")
        self.assertEqual(got, ["Астра", "Небо", "Ярость"])
        self.quiet()

    def test_by_chapters_is_the_longest_first(self):
        got = self.show([self.book("А", chapters=10),
                         self.book("Б", chapters=900),
                         self.book("В", chapters=100)], sort="chapters")
        self.assertEqual(got, ["Б", "В", "А"])
        self.quiet()

    def test_a_book_that_never_ran_goes_last(self):
        """«Неизвестно когда» — не то же самое, что «давно»."""
        got = self.show([self.book("А"),
                         self.book("Б", last_run="2026-01-01 10:00"),
                         self.book("В", last_run="2026-09-01 10:00")],
                        sort="last_run")
        self.assertEqual(got, ["В", "Б", "А"])
        self.quiet()

    def groups(self):
        return self.page.evaluate(
            """() => [...document.querySelectorAll('#lbList .lb-group')]
                     .map(one => one.textContent)""")

    def test_books_are_laid_out_in_groups(self):
        self.show([self.book("А", source="mvl"),
                   self.book("Б", source="fanqie"),
                   self.book("В", source="mvl")], group="source")
        said = self.groups()
        self.assertEqual(len(said), 2)
        self.assertTrue(any("mvl · 2" in one for one in said))
        self.quiet()

    def test_a_book_without_the_field_still_gets_a_group(self):
        """Иначе она пропала бы из списка вовсе."""
        got = self.show([self.book("А", author="Автор"), self.book("Б")],
                        group="author")
        self.assertEqual(sorted(got), ["А", "Б"])
        self.assertEqual(len(self.groups()), 2)
        self.quiet()

    def test_no_grouping_means_no_headings(self):
        self.show([self.book("А"), self.book("Б")])
        self.assertEqual(self.groups(), [])
        self.quiet()

    def test_the_word_reaches_the_description(self):
        """Название китайское, автор незнакомый, а «культивация» человек
        помнит."""
        got = self.show([self.book("А", about_ru="история про культивацию"),
                         self.book("Б", about_ru="жизнь в городе")],
                        word="культивац")
        self.assertEqual(got, ["А"])
        self.quiet()

    def test_the_word_reaches_the_genres(self):
        got = self.show([self.book("А", genres_shown=["боевые искусства"]),
                         self.book("Б", genres_shown=["романтика"])],
                        word="боев")
        self.assertEqual(got, ["А"])
        self.quiet()

    def test_several_genres_mean_all_of_them(self):
        """«Боевые искусства» и «романтика» вместе — это просьба показать
        то, где есть и то и другое, а не свалить два списка в один."""
        got = self.show([
            self.book("А", genres_shown=["боевые искусства", "романтика"]),
            self.book("Б", genres_shown=["боевые искусства"]),
        ], kinds=["боевые искусства", "романтика"])
        self.assertEqual(got, ["А"])
        self.quiet()

    def test_the_genre_list_is_built_from_the_books(self):
        """Жанры у каждого сайта свои, заранее их не перечислить."""
        self.show([self.book("А", genres_shown=["меч"]),
                   self.book("Б", genres_shown=["меч", "магия"])])
        chips = self.page.locator("#lbKinds .lbchip")
        self.assertEqual(chips.count(), 2)
        self.assertIn("меч · 2", chips.nth(0).inner_text())
        self.quiet()


class TestDoingOneThingToManyBooksOnScreen(PageTestCase):
    """Полоса действий: видна, только когда есть что делать."""

    def show(self, books, **more):
        return self.page.evaluate(
            """([books, more]) => {
                 libBooks = books;
                 libState = {};
                 libPick = '';
                 libKinds = new Set();
                 libTicked = new Set(more.ticked || []);
                 libSort = 'title';
                 libGroup = 'none';
                 document.getElementById('lbFilter').value = more.word || '';
                 document.getElementById('lbPickOn').checked = !!more.picking;
                 libShow();
                 return {
                   deeds: !document.getElementById('lbDeeds').hidden,
                   said: document.getElementById('lbPicked').innerText,
                   ticks: document.querySelectorAll('#lbList .lb-tick').length,
                   off: document.getElementById('lbForget').disabled,
                   picked: libTicked.size,
                 };
               }""", [books, more])

    def book(self, key, **fields):
        row = {"key": key, "title": key, "name": key, "author": "",
               "folder": "/книги/" + key, "marks": [], "auto": [],
               "mark_names": [], "auto_names": [], "tags": [],
               "genres_shown": [], "site_tags_shown": [],
               "chapters": 0, "last": 0, "fresh": 0}
        row.update(fields)
        return row

    def test_without_the_tick_there_is_no_bar(self):
        """Пустая полоса — обещание без повода."""
        said = self.show([self.book("А")])
        self.assertFalse(said["deeds"])
        self.assertEqual(said["ticks"], 0)
        self.quiet()

    def test_ticking_shows_the_boxes(self):
        said = self.show([self.book("А"), self.book("Б")], picking=True)
        self.assertTrue(said["deeds"])
        self.assertEqual(said["ticks"], 2)
        self.quiet()

    def test_nothing_picked_leaves_the_deeds_locked(self):
        """Иначе кнопка «Забыть» обещает сделать что-то ни с чем."""
        said = self.show([self.book("А")], picking=True)
        self.assertTrue(said["off"])
        self.quiet()

    def test_it_counts_what_is_picked(self):
        said = self.show([self.book("А"), self.book("Б")],
                         picking=True, ticked=["А", "Б"])
        self.assertIn("2", said["said"])
        self.assertFalse(said["off"])
        self.quiet()

    def test_a_picked_book_outside_the_filter_is_not_lost(self):
        """Человек мог отметить десяток, а потом сузить список, чтобы
        добрать одиннадцатую."""
        said = self.show([self.book("Астра"), self.book("Небо")],
                         picking=True, ticked=["Астра", "Небо"],
                         word="небо")
        self.assertIn("2", said["said"])
        self.assertIn("1", said["said"])
        self.quiet()

    def test_a_book_that_is_gone_stops_being_picked(self):
        """Забытая книга не должна попасть в следующее действие пачкой.

        Считаем сами отметки, а не подпись: в подписи «Отмечено книг: 2
        (из них видно 1)» единица есть и тогда, когда пропавшая книга
        осталась отмеченной.
        """
        said = self.show([self.book("А")], picking=True,
                         ticked=["А", "которой-нет"])
        self.assertEqual(said["picked"], 1)
        self.quiet()
