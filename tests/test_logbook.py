"""Журнал в файл и отчёт о проблеме.

До сих пор всё уходило только в консоль, а на Windows она закрывается
вместе с программой. Из-за этого «в рейтинге Цидяня прочерки» висело без
движения: спросить, что написано в консоли, можно, а прочитать нечего.

Главное здесь — не то, что журнал пишется, а то, что отчёт можно
отправить наружу: ключи и пароли из него обязаны исчезать.
"""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import logbook  # noqa: E402
from mvl.proxies import remember_secret  # noqa: E402

KEY = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        # Пишем в свою папку: прогон не должен трогать настоящий журнал.
        self._was = (logbook.LOG_DIR, logbook.LOG_FILE, logbook.PAGE_DIR,
                     logbook._started)
        logbook.LOG_DIR = self.tmp / "logs"
        logbook.LOG_FILE = logbook.LOG_DIR / "neurostrazh.log"
        logbook.PAGE_DIR = logbook.LOG_DIR / "pages"
        logbook._started = False
        self.addCleanup(self._restore)

    def _restore(self):
        (logbook.LOG_DIR, logbook.LOG_FILE, logbook.PAGE_DIR,
         logbook._started) = self._was
        root = logging.getLogger()
        for handler in list(root.handlers):
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                root.removeHandler(handler)
                handler.close()


class TestTheJournalIsKept(Base):
    def test_a_line_reaches_the_file(self):
        logbook.start()
        logging.getLogger("проба").info("что-то случилось")
        self.assertIn("что-то случилось", logbook.tail())

    def test_starting_twice_does_not_double_every_line(self):
        """Второй обработчик писал бы каждую строку дважды."""
        logbook.start()
        logbook.start()
        logging.getLogger("проба").info("однажды")
        self.assertEqual(logbook.tail().count("однажды"), 1)

    def test_no_journal_yet_is_not_an_error(self):
        """Первый запуск: файла ещё нет, а отчёт уже могут попросить."""
        self.assertEqual(logbook.tail(), "")
        self.assertIn("NEUROSTRAZH", logbook.report())

    def test_a_folder_it_cannot_make_does_not_stop_the_program(self):
        """Без журнала программа работает; падать из-за журнала — нет."""
        logbook.LOG_DIR = self.tmp / "файл" / "logs"
        (self.tmp / "файл").write_text("не папка", encoding="utf-8")
        logbook.LOG_FILE = logbook.LOG_DIR / "neurostrazh.log"
        self.assertIsNone(logbook.start())


class TestTheReportLetsNothingOut(Base):
    """Отчёт уходит наружу — в переписку, в issue, куда угодно."""

    def test_a_key_never_leaves(self):
        logbook.start()
        logging.getLogger("проба").info("взяли ключ %s", KEY)
        self.assertNotIn(KEY, logbook.report())

    def test_a_password_in_an_address_never_leaves(self):
        logbook.start()
        logging.getLogger("проба").info("http://vasya:sekret@1.2.3.4:8080")
        said = logbook.report()
        self.assertNotIn("sekret", said)
        # Сам адрес остаётся: без него строка журнала бесполезна.
        self.assertIn("1.2.3.4", said)

    def test_a_password_that_looks_like_a_word_never_leaves(self):
        """По виду такой не отличить от обычного слова — спасает только
        то, что программа его помнит."""
        remember_secret("морковка")
        logbook.start()
        logging.getLogger("проба").info("пароль прокси морковка не подошёл")
        self.assertNotIn("морковка", logbook.report())

    def test_it_says_what_was_being_done(self):
        """Половина разбора — в этой строке."""
        self.assertIn("нажал «Найти»", logbook.report("нажал «Найти»"))

    def test_it_says_version_and_system(self):
        said = logbook.report()
        self.assertIn("NEUROSTRAZH", said)
        self.assertIn("Python", said)


class TestTheReportOverHttp(Base):
    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()

    def test_the_button_gets_a_ready_text(self):
        logbook.start()
        logging.getLogger("проба").info("строка для отчёта")
        got = self.app.post("/api/report", json={"what": "что делали"}).get_json()

        self.assertIn("строка для отчёта", got["text"])
        self.assertIn("что делали", got["text"])
        self.assertTrue(got["kept"])

    def test_it_also_says_where_the_journal_lies(self):
        """Чтобы можно было открыть папку, а не искать её."""
        logbook.start()
        got = self.app.post("/api/report", json={}).get_json()
        self.assertEqual(got["file"], str(logbook.LOG_FILE))


class TestFinishedJobsAreForgotten(unittest.TestCase):
    """Задачи копились в памяти без предела.

    Каждая хранит свой отчёт целиком — со списком ошибок по каждому
    файлу, — а из `JOBS` до сих пор не удалялось ничего и никогда. День
    работы на сотнях книг, и память растёт весь день.
    """

    def setUp(self):
        from webapp import app as web

        self.web = web
        self.held = dict(web.JOBS)
        web.JOBS.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        self.web.JOBS.clear()
        self.web.JOBS.update(self.held)

    def add(self, key, finished=None):
        """`finished` пустой — задача ещё идёт: `running` считается
        по нему, своего поля у неё нет."""
        job = self.web.Job(id=key, kind="проба")
        job.finished = finished
        self.web.JOBS[key] = job
        return job

    def test_a_job_that_finished_long_ago_is_dropped(self):
        import time

        self.add("старая", time.monotonic() - self.web.JOB_TTL - 10)
        self.add("свежая", time.monotonic())
        with self.web.JOBS_LOCK:
            self.web.forget_old()

        self.assertNotIn("старая", self.web.JOBS)
        self.assertIn("свежая", self.web.JOBS)

    def test_a_running_job_is_never_dropped(self):
        """У задачи, которую сейчас показывают, отнимать себя нельзя."""
        import time

        self.add("идёт")
        with self.web.JOBS_LOCK:
            self.web.forget_old()
        self.assertIn("идёт", self.web.JOBS)

    def test_beyond_the_limit_the_oldest_go_first(self):
        import time

        now = time.monotonic()
        for number in range(self.web.KEEP_JOBS + 5):
            self.add(f"№{number}", now - (self.web.KEEP_JOBS + 5 - number))
        with self.web.JOBS_LOCK:
            self.web.forget_old()

        self.assertEqual(len(self.web.JOBS), self.web.KEEP_JOBS)
        self.assertNotIn("№0", self.web.JOBS)
        self.assertIn(f"№{self.web.KEEP_JOBS + 4}", self.web.JOBS)

    def test_a_just_finished_job_survives_long_enough_to_be_shown(self):
        """Интерфейс дорисовывает итог уже после конца работы."""
        import time

        self.add("только что", time.monotonic())
        with self.web.JOBS_LOCK:
            self.web.forget_old()
        self.assertIn("только что", self.web.JOBS)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestTheStumbledPageIsKept(Base):
    """Страница, на которой споткнулся разбор, сохраняется в файл.

    Разбор сайта чинится по странице, а не по сообщению о ней: «не
    нашлось ни одной книги» не отвечает даже на вопрос, пришла ли вообще
    страница сайта. К моменту разбора жалобы ответ давно выброшен, а
    следующего случая можно ждать неделю.
    """

    def test_it_lands_in_a_file(self):
        path = logbook.keep_page("rank", "<html>страница</html>")
        self.assertIsNotNone(path)
        self.assertEqual(path.read_text(encoding="utf-8"), "<html>страница</html>")

    def test_the_name_says_what_it_was(self):
        path = logbook.keep_page("rank", "<html>страница</html>")
        self.assertIn("rank", path.name)
        self.assertTrue(path.name.endswith(".html"))

    def test_a_password_never_reaches_the_file(self):
        """Файл человек отправит наружу — как и отчёт о проблеме."""
        path = logbook.keep_page(
            "rank", "<a href='http://user:s3cret@1.2.3.4:6095/'>прокси</a>")
        self.assertNotIn("s3cret", path.read_text(encoding="utf-8"))

    def test_a_key_never_reaches_the_file(self):
        path = logbook.keep_page("rank", f"<p>{KEY}</p>")
        self.assertNotIn(KEY, path.read_text(encoding="utf-8"))

    def test_a_secret_that_looks_like_a_word_never_reaches_the_file(self):
        remember_secret("ohnetalk")
        path = logbook.keep_page("rank", "<p>пароль ohnetalk внутри</p>")
        self.assertNotIn("ohnetalk", path.read_text(encoding="utf-8"))

    def test_an_empty_page_is_not_saved(self):
        """Пустой файл ничего не расскажет, а папку засорит."""
        self.assertIsNone(logbook.keep_page("rank", "   "))

    def test_a_huge_page_is_cut(self):
        path = logbook.keep_page("rank", "я" * (logbook.PAGE_MAX + 5000))
        self.assertLessEqual(len(path.read_text(encoding="utf-8")),
                             logbook.PAGE_MAX)

    def test_only_the_last_pages_are_kept(self):
        """Иначе папка растёт вечно."""
        import os

        logbook.PAGE_DIR.mkdir(parents=True, exist_ok=True)
        for number in range(logbook.PAGE_KEEP + 4):
            stale = logbook.PAGE_DIR / f"{number:03d}-rank.html"
            stale.write_text("старое", encoding="utf-8")
            os.utime(stale, (1000 + number, 1000 + number))

        logbook.keep_page("rank", "<p>последняя</p>")

        kept = list(logbook.PAGE_DIR.glob("*.html"))
        self.assertLessEqual(len(kept), logbook.PAGE_KEEP)
        # Уцелеть должна свежая, а не первая попавшаяся.
        self.assertTrue(any("последняя" in page.read_text(encoding="utf-8")
                            for page in kept))
        self.assertFalse((logbook.PAGE_DIR / "000-rank.html").exists())

    def test_a_folder_it_cannot_make_does_not_stop_the_program(self):
        """Без сохранённой страницы программа работает; падать нельзя."""
        blocked = self.tmp / "занято"
        blocked.write_text("не папка", encoding="utf-8")
        logbook.PAGE_DIR = blocked / "pages"
        self.assertIsNone(logbook.keep_page("rank", "<p>страница</p>"))
