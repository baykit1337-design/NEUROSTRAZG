"""Раскладка работы по ядрам.

Пятьсот глав в Word писались восемнадцать секунд — при полусекунде на
любой другой формат. Работа эта посильная любому ядру и ни одному
заданию не нужно знать о соседях, так что её раскладывают.

Главное здесь — не ускорение само по себе, а то, что от него ничего не
поменялось: порядок, счёт ошибок, прогресс и «Остановить».
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from ops.base import Cancelled, Progress, spread  # noqa: E402
from ops import base as base_op  # noqa: E402


def double(job):
    """Задание уровня модуля: иначе его не отправить в другой процесс."""
    return "" if job % 2 == 0 else f"нечётное: {job}"


def blow_up(job):
    raise RuntimeError(f"сломалось на {job}")


def whoami(job):
    """Кто считал. Единственная примета, по которой снаружи видно, завели
    процессы или обошлись: побочный эффект в чужом процессе до нас не
    доходит, а номер процесса — доходит, ответом."""
    return str(os.getpid())


class TestWhichFormatsAreHeavy(unittest.TestCase):
    """Раскладывать имеет смысл не всё.

    Замерено на главе в сорок абзацев: `.txt`, `.md`, `.fb2` — меньше
    миллисекунды на файл, `.docx` — сорок. Заводить процессы ради `.txt`
    дороже, чем его написать.
    """

    def test_word_and_epub_are_heavy(self):
        self.assertTrue(formats.is_heavy(".docx"))
        self.assertTrue(formats.is_heavy(".epub"))

    def test_plain_formats_are_not(self):
        for suffix in (".txt", ".md", ".fb2", ".rtf", ".odt"):
            with self.subTest(suffix):
                self.assertFalse(formats.is_heavy(suffix))

    def test_an_unknown_format_is_not_heavy(self):
        """Спрашивают и про то, чего мы не пишем, — это не повод падать."""
        self.assertFalse(formats.is_heavy(".странное"))

    def test_the_dot_is_optional(self):
        self.assertTrue(formats.is_heavy("docx"))


class TestSpreadingTheWork(unittest.TestCase):

    def test_the_order_of_answers_matches_the_order_of_jobs(self):
        """Задания кончаются вразнобой, а отвечать надо по порядку:
        иначе беда прилипла бы к чужому файлу."""
        got = spread(double, [0, 1, 2, 3, 4], heavy=False)
        self.assertEqual(got, ["", "нечётное: 1", "", "нечётное: 3", ""])

    def test_every_job_is_done(self):
        self.assertEqual(len(spread(double, list(range(50)), heavy=False)), 50)

    def test_a_broken_job_does_not_stop_the_rest(self):
        """Сбой одного файла не повод бросать остальные."""
        got = spread(blow_up, [1, 2], heavy=False)
        self.assertEqual(len(got), 2)
        self.assertTrue(all("RuntimeError" in line for line in got), got)

    def test_it_says_how_far_it_got(self):
        said = []
        spread(double, [0, 1, 2],
               Progress(on_progress=lambda d, t, m: said.append((d, t))),
               heavy=False)
        self.assertEqual(said[-1], (3, 3))

    def test_stopping_works(self):
        stop = threading.Event()

        def watch(done, total, message):
            stop.set()

        with self.assertRaises(Cancelled):
            spread(double, list(range(50)),
                   Progress(on_progress=watch, cancel=stop), heavy=False)

    def test_an_empty_list_is_not_an_error(self):
        self.assertEqual(spread(double, [], heavy=False), [])


class TestWhenTheCoresAreUsed(unittest.TestCase):
    """Процессы стоят денег: на Windows каждый заводится с нуля и заново
    импортирует наши модули. На коротком списке эта плата съела бы весь
    выигрыш."""

    def setUp(self):
        self.was = base_op.MANY
        self.addCleanup(setattr, base_op, "MANY", self.was)

    def test_a_short_list_is_done_on_the_spot(self):
        self.assertLess(len(range(10)), base_op.MANY)

    def test_a_light_job_stays_in_this_process(self):
        """Даже тысяча `.txt` пишется быстрее, чем заводятся процессы."""
        base_op.MANY = 2
        got = spread(whoami, [0, 1, 2, 3], heavy=False)
        self.assertEqual(set(got), {str(os.getpid())})

    def test_a_short_list_stays_in_this_process_even_if_heavy(self):
        base_op.MANY = 10 ** 9
        got = spread(whoami, [0, 1, 2, 3], heavy=True)
        self.assertEqual(set(got), {str(os.getpid())})

    def test_heavy_work_really_leaves_this_process(self):
        """Иначе «ускорили» означало бы только то, что мы так думаем."""
        base_op.MANY = 2
        got = spread(whoami, list(range(8)), heavy=True)
        self.assertNotIn(str(os.getpid()), got)
        self.assertGreater(len(set(got)), 1)

    def test_no_more_workers_than_agreed(self):
        """Машина человека — не наша: он ею в это время пользуется."""
        self.assertLessEqual(base_op.cores(), base_op.MOST)
        self.assertGreaterEqual(base_op.cores(), 1)


class TestTheCoresGiveTheSameAnswer(unittest.TestCase):
    """Ускорение не должно менять ответ. Гоняем ту же работу обоими
    путями и сверяем."""

    def setUp(self):
        self.was = base_op.MANY
        self.addCleanup(setattr, base_op, "MANY", self.was)

    def test_processes_answer_exactly_as_the_single_thread(self):
        jobs = list(range(120))
        base_op.MANY = 10 ** 9
        alone = spread(double, jobs, heavy=True)
        base_op.MANY = 100
        together = spread(double, jobs, heavy=True)
        self.assertEqual(together, alone)


if __name__ == "__main__":
    unittest.main()
