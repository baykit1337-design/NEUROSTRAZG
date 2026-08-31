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
    """Карточка «Речь в кавычках» на вкладке «Форматировать».

    Работа необратимая по смыслу — правит текст книги, — поэтому кнопка
    записи показывается только после того, как человек увидел список
    «до и после».
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from tempfile import TemporaryDirectory

        cls.tmpdir = TemporaryDirectory()
        cls.folder = Path(cls.tmpdir.name)
        cls.quiet_book = cls.folder / "тире.md"
        cls.quiet_book.write_text(
            " # [Глава 1 :|: :|: 1 :|: ]\n"
            "— Уже через тире.\n",
            encoding="utf-8")
        cls.book = cls.folder / "книга.md"
        cls.book.write_text(
            " # [Глава 1 :|: :|: 1 :|: ]\n"
            "«Я-я в порядке...♥»\n"
            "«Быстрее».\n"
            "Он читал «Войну и мир».\n",
            encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.page.click('.tabs button[data-tab="format"]')

    def look_at(self, path):
        self.page.fill("#fmBookPath", str(path))
        self.page.press("#fmBookPath", "Enter")
        self.page.wait_for_timeout(800)
        self.page.click("#fmSpeechLook")

    def test_the_card_is_there(self):
        self.assertTrue(self.page.locator("#fmSpeechCard").count())
        self.quiet()

    def test_where_to_save_stays_hidden_until_it_is_looked_at(self):
        self.assertTrue(self.page.locator("#fmSpeechWhere").is_hidden())
        self.quiet()

    def test_it_shows_every_line_before_and_after(self):
        self.look_at(self.book)
        self.page.wait_for_selector("#fmSpeechTable:not([hidden])",
                                    timeout=10000)
        shown = self.page.inner_text("#fmSpeechTable")
        self.assertIn("— Быстрее.", shown)
        # Не реплика — в список не попадает вовсе.
        self.assertNotIn("Войну и мир", shown)
        self.assertIn("2", self.page.inner_text("#fmSpeechNote"))
        self.assertFalse(self.page.locator("#fmSpeechWhere").is_hidden())
        self.quiet()

    def test_a_book_without_quoted_speech_offers_no_button(self):
        """Кнопка, которой нечего делать, обещает работу, которой не
        будет."""
        self.look_at(self.quiet_book)
        self.page.wait_for_function(
            "() => document.getElementById('fmSpeechNote')"
            ".textContent.includes('не нашлось')", timeout=10000)
        self.assertTrue(self.page.locator("#fmSpeechWhere").is_hidden())
        self.assertTrue(self.page.locator("#fmSpeechTable").is_hidden())
        self.quiet()


if __name__ == "__main__":
    unittest.main()
