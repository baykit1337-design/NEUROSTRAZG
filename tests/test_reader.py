"""Читалка и очередь задач (4.4 и 4.6 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core.models import Chapter  # noqa: E402
from core.readers.base import ReadError  # noqa: E402
from core.text import PrepOptions  # noqa: E402
from ops import queue as queue_op  # noqa: E402
from ops import reader  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def book(self, name="книга", chapters=None):
        chapters = chapters or {
            1: ["Первый абзац первой главы.", "Второй абзац."],
            2: ["Текст второй главы."],
            3: ["Текст третьей главы."],
        }
        path = self.tmp / name
        path.mkdir(parents=True, exist_ok=True)
        for number, paragraphs in chapters.items():
            formats.write(path / f"Глава {number}.txt",
                          [Chapter(number=number, title=f"Глава {number}",
                                   paragraphs=list(paragraphs))],
                          headings=True)
        return str(path)


class TestListing(Base):
    """Список глав — по нему ходят стрелками."""

    def test_all_chapters_are_listed(self):
        data = reader.listing(self.book())
        self.assertEqual(data["total"], 3)
        self.assertEqual([c["title"] for c in data["chapters"]],
                         ["Глава 1", "Глава 2", "Глава 3"])

    def test_entry_knows_its_file(self):
        data = reader.listing(self.book())
        self.assertTrue(data["chapters"][0]["source"].endswith("Глава 1.txt"))

    def test_unreadable_files_do_not_stop_the_list(self):
        book = self.book()
        (Path(book) / "битый.txt").write_bytes(b"\x00\x01\x02")
        data = reader.listing(book)
        self.assertGreaterEqual(data["total"], 3)


class TestOpen(Base):
    """Открытая глава показывается в том виде, что уйдёт в файл."""

    def test_first_chapter_by_default(self):
        page = reader.open_at(self.book()).as_dict()
        self.assertEqual(page["index"], 0)
        self.assertEqual(page["title"], "Глава 1")
        self.assertIn("Первый абзац первой главы.", page["paragraphs"])

    def test_navigation_flags(self):
        book = self.book()
        first = reader.open_at(book, 0)
        middle = reader.open_at(book, 1)
        last = reader.open_at(book, 2)

        self.assertFalse(first.has_prev)
        self.assertTrue(first.has_next)
        self.assertTrue(middle.has_prev)
        self.assertTrue(middle.has_next)
        self.assertFalse(last.has_next)

    def test_index_out_of_range_is_clamped(self):
        """Стрелка на последней главе не должна ронять запрос."""
        page = reader.open_at(self.book(), 99)
        self.assertEqual(page.index, 2)
        self.assertEqual(reader.open_at(self.book(), -5).index, 0)

    def double(self):
        """Глава, у которой название продублировано первым абзацем."""
        path = self.tmp / "Глава 1. Начало пути.txt"
        formats.write(path, [Chapter(
            number=1, title="Глава 1. Начало пути",
            paragraphs=["Глава 1. Начало пути", "Настоящий текст главы."],
        )], headings=True)
        return str(path)

    def test_text_goes_through_the_same_preparation_as_writing(self):
        """Иначе читалка показывала бы одно, а в файл легло бы другое."""
        page = reader.open_at(self.double(), 0, PrepOptions(strip_title=True))
        self.assertEqual(page.paragraphs, ["Настоящий текст главы."])

    def test_settings_reach_the_page(self):
        """Разделитель сцен показывается тем же, каким уйдёт в документ."""
        path = self.tmp / "Глава 4.txt"
        formats.write(path, [Chapter(number=4, title="Глава 4", paragraphs=[
            "До перерыва.", "***", "После перерыва."])], headings=True)

        stars = reader.open_at(str(path), 0, PrepOptions(scene_style="stars"))
        dashes = reader.open_at(str(path), 0, PrepOptions(scene_style="dashes"))
        self.assertIn("* * *", stars.paragraphs)
        self.assertIn("— — —", dashes.paragraphs)

    def test_text_field_joins_paragraphs(self):
        page = reader.open_at(self.book()).as_dict()
        self.assertEqual(page["text"], "\n\n".join(page["paragraphs"]))

    def test_nothing_readable_is_an_error(self):
        empty = self.tmp / "пусто"
        empty.mkdir()
        with self.assertRaises(ReadError):
            reader.open_at(str(empty))


class TestFindings(Base):
    """Находки проверки подсвечиваются прямо в тексте главы."""

    def test_findings_are_attached(self):
        book = self.book("сплошь", {
            1: ["Текст с иероглифом 世界 внутри."],
        })
        page = reader.open_at(book, 0, kinds=["cjk"])
        self.assertTrue(page.findings)
        self.assertEqual(page.findings[0]["kind"], "cjk")

    def test_only_findings_of_this_chapter(self):
        """В одном файле может лежать вся книга — чужое подсвечивать нельзя."""
        path = self.tmp / "вся-книга.fb2"
        formats.write(path, [
            Chapter(number=1, title="Глава 1", paragraphs=["Чисто и по-русски."]),
            Chapter(number=2, title="Глава 2", paragraphs=["Иероглиф 世界 здесь."]),
        ], headings=True)

        first = reader.open_at(str(path), 0, kinds=["cjk"])
        second = reader.open_at(str(path), 1, kinds=["cjk"])
        self.assertEqual(first.findings, [])
        self.assertTrue(second.findings)

    def test_empty_kinds_means_do_not_check(self):
        """Снятая галочка «подсветить находки» — не «проверить всё подряд»."""
        book = self.book("сплошь", {1: ["Текст с иероглифом 世界 внутри."]})
        self.assertEqual(reader.open_at(book, 0, kinds=[]).findings, [])
        self.assertTrue(reader.open_at(book, 0).findings)

    def test_broken_check_does_not_break_reading(self):
        page = reader.open_at(self.book(), 0, kinds=["такой-проверки-нет"])
        self.assertEqual(page.findings, [])
        self.assertTrue(page.paragraphs)


class TestSave(Base):
    """Правка пишется поверх исходника — с копией в корзине."""

    def one(self, text="Исходный текст."):
        path = self.tmp / "Глава 7.txt"
        formats.write(path, [Chapter(number=7, title="Глава 7",
                                     paragraphs=[text])], headings=True)
        return str(path)

    def test_edit_lands_in_the_file(self):
        path = self.one()
        result = reader.save(path, "Новый текст.\n\nВторой абзац.", backup=False)

        self.assertEqual(result["paragraphs"], 2)
        text = Path(path).read_text(encoding="utf-8")
        self.assertIn("Новый текст.", text)
        self.assertIn("Второй абзац.", text)
        self.assertNotIn("Исходный текст.", text)

    def test_title_survives_the_edit(self):
        path = self.one()
        reader.save(path, "Новый текст.", backup=False)
        chapters = formats.read(Path(path))
        self.assertEqual(chapters[0].title, "Глава 7")

    def test_backup_is_made_before_writing(self):
        path = self.one()
        result = reader.save(path, "Новый текст.")
        self.assertTrue(result["backup"])

        copy = Path(result["backup"]) / "Глава 7.txt"
        self.assertIn("Исходный текст.", copy.read_text(encoding="utf-8"))

    def test_backup_copies_the_file_not_the_whole_folder(self):
        """Книга на пятьсот глав не должна копироваться ради одного абзаца."""
        book = Path(self.book())
        target = book / "Глава 2.txt"
        result = reader.save(str(target), "Правка.")

        copies = list(Path(result["backup"]).iterdir())
        self.assertEqual([p.name for p in copies], ["Глава 2.txt"])

    def test_empty_text_is_refused(self):
        path = self.one()
        with self.assertRaises(reader.SaveError):
            reader.save(path, "   \n\n  ", backup=False)
        self.assertIn("Исходный текст.",
                      Path(path).read_text(encoding="utf-8"))

    def test_missing_file_is_refused(self):
        with self.assertRaises(reader.SaveError):
            reader.save(str(self.tmp / "нет.txt"), "Текст", backup=False)

    def test_file_with_many_chapters_is_refused(self):
        """Записать одну главу поверх ста значит стереть девяносто девять."""
        path = self.tmp / "вся-книга.fb2"
        formats.write(path, [
            Chapter(number=1, title="Глава 1", paragraphs=["Раз."]),
            Chapter(number=2, title="Глава 2", paragraphs=["Два."]),
        ], headings=True)

        with self.assertRaises(reader.SaveError) as caught:
            reader.save(str(path), "Только это", backup=False)
        self.assertIn("2 глав", str(caught.exception))
        self.assertIn("Два.", path.read_text(encoding="utf-8"))

    def test_edit_is_written_to_the_journal(self):
        from ops import history

        path = self.one()
        reader.save(path, "Новый текст.", backup=False)
        self.assertEqual(history.records(1)[0].operation, "правка главы")


# ------------------------------------------------------ 4.6 очередь задач


class TestQueueStorage(Base):
    """Очередь сохраняется под именем и запускается снова."""

    def setUp(self):
        super().setUp()
        self._file = queue_op.QUEUE_FILE
        queue_op.QUEUE_FILE = self.tmp / "queues.json"
        self.addCleanup(setattr, queue_op, "QUEUE_FILE", self._file)

    def some(self, name="ночная"):
        return queue_op.Queue(name=name, steps=[
            queue_op.Step(kind="split", params={"base": "/tmp"}, title="Разбить"),
            queue_op.Step(kind="rename", title="Переименовать"),
        ])

    def test_saved_queue_is_read_back(self):
        queue_op.save(self.some())
        found = queue_op.get("ночная")
        self.assertIsNotNone(found)
        self.assertEqual([s.kind for s in found.steps], ["split", "rename"])
        self.assertEqual(found.steps[0].params["base"], "/tmp")

    def test_nameless_queue_is_refused(self):
        with self.assertRaises(queue_op.QueueError):
            queue_op.save(queue_op.Queue(name="  "))

    def test_queues_are_listed_by_name(self):
        queue_op.save(self.some("Ямб"))
        queue_op.save(self.some("абзац"))
        self.assertEqual([q.name for q in queue_op.all_queues()],
                         ["абзац", "Ямб"])

    def test_saving_the_same_name_replaces(self):
        queue_op.save(self.some())
        again = self.some()
        again.steps.pop()
        queue_op.save(again)
        self.assertEqual(len(queue_op.all_queues()), 1)
        self.assertEqual(len(queue_op.get("ночная").steps), 1)

    def test_removal(self):
        queue_op.save(self.some())
        self.assertTrue(queue_op.remove("ночная"))
        self.assertFalse(queue_op.remove("ночная"))
        self.assertEqual(queue_op.all_queues(), [])

    def test_broken_file_starts_over(self):
        queue_op.QUEUE_FILE.write_text("не json", encoding="utf-8")
        self.assertEqual(queue_op.all_queues(), [])

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(queue_op.all_queues(), [])
        self.assertIsNone(queue_op.get("нет такой"))


class TestQueueRun(Base):
    """Шаги выполняются подряд, до первой ошибки."""

    def some(self, count=3):
        return queue_op.Queue(name="прогон", steps=[
            queue_op.Step(kind=f"шаг{n}") for n in range(1, count + 1)
        ])

    def test_all_steps_run_in_order(self):
        seen = []
        result = queue_op.run(self.some(), lambda step: seen.append(step.kind))

        self.assertEqual(seen, ["шаг1", "шаг2", "шаг3"])
        self.assertEqual(result.state, queue_op.DONE)
        self.assertEqual(result.done, 3)

    def test_step_message_is_kept(self):
        result = queue_op.run(self.some(1), lambda step: "Готово: 5 файлов")
        self.assertEqual(result.steps[0].message, "Готово: 5 файлов")

    def test_failure_stops_the_queue(self):
        """Следующий шаг ждёт результата предыдущего — продолжать нельзя."""
        def perform(step):
            if step.kind == "шаг2":
                raise ValueError("папка не найдена")
            return "ок"

        result = queue_op.run(self.some(), perform)

        self.assertEqual(result.state, queue_op.FAILED)
        self.assertEqual(result.steps[0].state, queue_op.DONE)
        self.assertEqual(result.steps[1].state, queue_op.FAILED)
        self.assertIn("папка не найдена", result.steps[1].message)

    def test_steps_after_a_failure_are_marked_skipped(self):
        result = queue_op.run(self.some(), lambda step: 1 / 0)
        self.assertEqual([s.state for s in result.steps],
                         [queue_op.FAILED, queue_op.SKIPPED, queue_op.SKIPPED])

    def test_cancel_stops_before_the_next_step(self):
        stop = threading.Event()
        seen = []

        def perform(step):
            seen.append(step.kind)
            stop.set()

        result = queue_op.run(self.some(), perform, cancel=stop)
        self.assertEqual(seen, ["шаг1"])
        self.assertEqual(result.state, queue_op.SKIPPED)

    def test_progress_is_reported(self):
        states = []
        queue_op.run(self.some(2), lambda step: "ок",
                     on_change=lambda q: states.append((q.current, q.state)))
        self.assertIn((0, queue_op.RUNNING), states)
        self.assertEqual(states[-1][1], queue_op.DONE)

    def test_reset_prepares_a_second_run(self):
        result = queue_op.run(self.some(2), lambda step: 1 / 0)
        result.reset()

        self.assertEqual(result.state, queue_op.WAITING)
        self.assertEqual(result.current, -1)
        self.assertTrue(all(s.state == queue_op.WAITING for s in result.steps))
        self.assertTrue(all(not s.message for s in result.steps))

    def test_empty_queue_finishes_at_once(self):
        result = queue_op.run(queue_op.Queue(name="пусто"), lambda step: None)
        self.assertEqual(result.state, queue_op.DONE)

    def test_round_trip_through_json(self):
        result = queue_op.run(self.some(2), lambda step: "ок")
        again = queue_op.Queue.from_dict(result.as_dict())
        self.assertEqual(again.state, queue_op.DONE)
        self.assertEqual([s.state for s in again.steps],
                         [queue_op.DONE, queue_op.DONE])


if __name__ == "__main__":
    unittest.main(verbosity=2)
