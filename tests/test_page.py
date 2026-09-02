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
