"""Вкладка «Конвертация»: перегон файлов из формата в формат.

Соседи по семье меняют число файлов: «Разбить» — из одного много,
«Объединить» — из многого один. Здесь число не меняется вовсе, и
проверяется прежде всего это: сколько выбрали, столько и вышло.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats  # noqa: E402
from core.models import Chapter  # noqa: E402
from core.text import PrepOptions  # noqa: E402
from ops import convert  # noqa: E402
from ops.base import Cancelled, Progress  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"


def write_chapter(folder: Path, name: str, title: str = "",
                  body: str = "Первый абзац.\n\nВторой абзац.") -> Path:
    """Обычная глава в .txt — то, что лежит в папке после скачивания."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.txt"
    head = f"{title}\n\n" if title else ""
    path.write_text(head + body, encoding="utf-8")
    return path


class ConvertCase(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.src = self.tmp / "исходники"
        self.out = self.tmp / "готовое"


class TestCountDoesNotChange(ConvertCase):
    """Главное свойство вкладки."""

    def test_every_file_gets_its_own(self):
        for number in range(1, 6):
            write_chapter(self.src, f"Глава {number}",
                          title=f"Глава {number}. Проба")
        report = convert.run([self.src], self.out, out_format=".docx")
        self.assertEqual(report.written, 5)
        self.assertEqual(report.total, 5)
        self.assertEqual(len(list(self.out.glob("*.docx"))), 5)

    def test_names_are_kept(self):
        write_chapter(self.src, "Глава 7", title="Глава 7. Дорога")
        convert.run([self.src], self.out, out_format=".fb2")
        self.assertTrue((self.out / "Глава 7.fb2").exists())

    def book(self, suffix: str) -> Path:
        """Книга из двух глав — в формате, который помнит их границы."""
        self.src.mkdir(parents=True, exist_ok=True)
        path = self.src / f"Книга{suffix}"
        formats.write(path, [
            Chapter(number=1, title="Глава 1. Начало",
                    paragraphs=["Текст первой."]),
            Chapter(number=2, title="Глава 2. Продолжение",
                    paragraphs=["Текст второй."]),
        ])
        return path

    def test_chapters_inside_a_file_stay_together(self):
        """Книга целиком остаётся книгой: резать — не эта работа."""
        convert.run([self.book(".epub")], self.out, out_format=".fb2")
        made = list(self.out.glob("*.fb2"))
        self.assertEqual(len(made), 1, "один файл на входе — один на выходе")
        self.assertEqual(len(formats.read(made[0])), 2, "главы не склеились")

    def test_a_flat_format_loses_the_boundaries_but_not_the_text(self):
        """`.docx` и `.txt` границ глав не помнят — это свойство читалок.

        Вкладка сама ничего не склеивает: сколько глав дала читалка,
        столько получит писатель. Но текст обязан доехать весь, иначе
        перегон был бы порчей.
        """
        convert.run([self.book(".epub")], self.out, out_format=".txt")
        written = (self.out / "Книга.txt").read_text(encoding="utf-8")
        self.assertIn("Текст первой.", written)
        self.assertIn("Текст второй.", written)

    def test_text_survives_the_trip(self):
        write_chapter(self.src, "Глава 1", title="Глава 1. Проба",
                      body="Слово, которое должно доехать.")
        convert.run([self.src], self.out, out_format=".docx")
        chapters = formats.read(next(self.out.glob("*.docx")))
        whole = "\n".join(chapter.text for chapter in chapters)
        self.assertIn("Слово, которое должно доехать.", whole)


class TestSameNamesFromDifferentFolders(ConvertCase):
    """У двух книг главы зовутся одинаково — молча затирать нельзя."""

    def test_the_second_gets_a_number(self):
        first = self.src / "первая"
        second = self.src / "вторая"
        write_chapter(first, "Глава 1", body="Из первой книги.")
        write_chapter(second, "Глава 1", body="Из второй книги.")
        report = convert.run([first, second], self.out, out_format=".txt")
        self.assertEqual(report.written, 2)
        self.assertEqual(len(list(self.out.glob("*.txt"))), 2)

    def test_nothing_is_lost(self):
        first = self.src / "первая"
        second = self.src / "вторая"
        write_chapter(first, "Глава 1", body="Из первой книги.")
        write_chapter(second, "Глава 1", body="Из второй книги.")
        convert.run([first, second], self.out, out_format=".txt")
        whole = " ".join(path.read_text(encoding="utf-8")
                         for path in self.out.glob("*.txt"))
        self.assertIn("Из первой книги.", whole)
        self.assertIn("Из второй книги.", whole)


class TestSameFormat(ConvertCase):
    """Перегон .txt в .txt осмыслен — есть обработка и кодировка."""

    def test_it_is_not_refused(self):
        write_chapter(self.src, "Глава 1")
        report = convert.run([self.src], self.out, out_format=".txt")
        self.assertEqual(report.written, 1)

    def test_it_is_counted_apart(self):
        write_chapter(self.src, "Глава 1")
        write_chapter(self.src, "Глава 2")
        report = convert.run([self.src], self.out, out_format=".txt")
        self.assertEqual(report.extra.get("same_format"), 2)

    def test_the_count_reaches_the_interface(self):
        """`extra` раскладывается по верхнему уровню ответа."""
        write_chapter(self.src, "Глава 1")
        report = convert.run([self.src], self.out, out_format=".txt")
        self.assertEqual(report.as_dict().get("same_format"), 1)

    def test_other_formats_are_not_counted(self):
        write_chapter(self.src, "Глава 1")
        report = convert.run([self.src], self.out, out_format=".docx")
        self.assertNotIn("same_format", report.extra)

    def test_sources_are_not_overwritten(self):
        """Пишем в отдельную папку, иначе перегон съел бы сам себя."""
        source = write_chapter(self.src, "Глава 1", body="Исходный текст.")
        convert.run([self.src], self.out, out_format=".txt")
        self.assertIn("Исходный текст.", source.read_text(encoding="utf-8"))


class TestOneBadFileDoesNotStopTheRest(ConvertCase):
    """Из двухсот глав одна битая не должна стоить всей работы."""

    def setUp(self):
        super().setUp()
        for number in (1, 2, 3):
            write_chapter(self.src, f"Глава {number}",
                          title=f"Глава {number}. Проба")
        # Расширение обещает документ, внутри — не документ.
        (self.src / "битая.docx").write_bytes(b"\x00\x01 not a document")

    def test_the_others_are_written(self):
        report = convert.run([self.src], self.out, out_format=".txt")
        self.assertEqual(report.written, 3)

    def test_the_broken_one_is_reported(self):
        report = convert.run([self.src], self.out, out_format=".txt")
        self.assertEqual(report.failed, 1)
        self.assertEqual(report.failures[0].file, "битая.docx")

    def test_the_reason_is_written_out(self):
        """Молчаливых отказов быть не должно."""
        report = convert.run([self.src], self.out, out_format=".txt")
        self.assertTrue(report.failures[0].error.strip())

    def test_an_empty_file_is_not_dropped_in_silence(self):
        """Пустой на входе — пустой на выходе, но он есть и он посчитан."""
        empty = self.tmp / "пусто"
        empty.mkdir()
        (empty / "ничего.txt").write_text("", encoding="utf-8")
        report = convert.run([empty], self.out, out_format=".txt")
        self.assertEqual(report.total, 1)
        self.assertEqual(report.written + report.failed, 1)


class TestRefusals(ConvertCase):
    def test_unwritable_format_is_refused_by_name(self):
        write_chapter(self.src, "Глава 1")
        with self.assertRaises(ValueError) as caught:
            convert.run([self.src], self.out, out_format=".pdf")
        self.assertIn(".pdf", str(caught.exception))

    def test_nothing_chosen_is_refused(self):
        from core.readers.base import ReadError

        empty = self.tmp / "пусто"
        empty.mkdir()
        with self.assertRaises((ReadError, ValueError)):
            convert.run([empty], self.out, out_format=".txt")

    def test_a_format_without_the_dot_is_understood(self):
        write_chapter(self.src, "Глава 1")
        convert.run([self.src], self.out, out_format="docx")
        self.assertTrue(list(self.out.glob("*.docx")))


class TestOptionsReachTheFile(ConvertCase):
    """Настройки вкладки должны доезжать, а не украшать окно."""

    def test_headings_can_be_left_out(self):
        write_chapter(self.src, "Глава 3", title="Глава 3. Заголовок",
                      body="Тело главы.")
        convert.run([self.src], self.out, out_format=".txt", headings=False)
        written = (self.out / "Глава 3.txt").read_text(encoding="utf-8")
        self.assertNotIn("Заголовок", written)
        self.assertIn("Тело главы.", written)

    def test_headings_are_written_when_asked(self):
        write_chapter(self.src, "Глава 3", title="Глава 3. Заголовок",
                      body="Тело главы.")
        convert.run([self.src], self.out, out_format=".txt", headings=True)
        written = (self.out / "Глава 3.txt").read_text(encoding="utf-8")
        self.assertIn("Заголовок", written)

    def test_encoding_is_used(self):
        """Windows-1251 нужна старым читалкам."""
        write_chapter(self.src, "Глава 1", body="Русский текст.")
        convert.run([self.src], self.out, out_format=".txt",
                    encoding="windows-1251")
        raw = (self.out / "Глава 1.txt").read_bytes()
        self.assertIn("Русский текст.", raw.decode("windows-1251"))

    def test_preparation_is_applied(self):
        write_chapter(self.src, "Глава 4", title="Глава 4. Дорога",
                      body="Глава 4. Дорога\n\nПервый абзац.")
        convert.run([self.src], self.out, out_format=".txt",
                    prep=PrepOptions(strip_title=True))
        written = (self.out / "Глава 4.txt").read_text(encoding="utf-8")
        self.assertEqual(written.count("Дорога"), 1)


class TestProgress(ConvertCase):
    def test_every_file_is_counted_out(self):
        for number in range(1, 4):
            write_chapter(self.src, f"Глава {number}")
        seen = []
        convert.run([self.src], self.out, out_format=".txt",
                    progress=Progress(lambda done, total, message="":
                                      seen.append((done, total))))
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_the_stop_button_stops_it(self):
        for number in range(1, 21):
            write_chapter(self.src, f"Глава {number}")
        progress = Progress()
        progress.cancel.set()
        with self.assertRaises(Cancelled):
            convert.run([self.src], self.out, out_format=".txt",
                        progress=progress)


class TestScanIsCheap(ConvertCase):
    """Пересчёт не должен читать содержимое: этот урок уже оплачен.

    В «Переименовать» превью читало каждый файл ради одного числа, и на
    пятистах `.docx` это стоило десяток секунд. Здесь для схемы нужно
    только число файлов.
    """

    def test_it_counts_what_was_chosen(self):
        for number in range(1, 6):
            write_chapter(self.src, f"Глава {number}")
        found = convert.scan([self.src])
        self.assertEqual(found["file_count"], 5)
        self.assertEqual(len(found["files"]), 5)

    def test_foreign_formats_in_a_folder_are_named(self):
        write_chapter(self.src, "Глава 1")
        (self.src / "state.json").write_text("{}", encoding="utf-8")
        found = convert.scan([self.src])
        self.assertEqual(found["file_count"], 1)
        self.assertIn("state.json", " ".join(found["skipped"]))

    def test_a_broken_file_does_not_stop_the_count(self):
        """Читай оно содержимое — сорвалось бы здесь."""
        write_chapter(self.src, "Глава 1")
        (self.src / "битая.docx").write_bytes(b"\x00\x01 not a document")
        self.assertEqual(convert.scan([self.src])["file_count"], 2)

    def test_it_stays_fast_on_a_heavy_folder(self):
        write_chapter(self.src, "Глава 1")
        sample = self.tmp / "образец.docx"
        formats.write(sample, formats.read(self.src / "Глава 1.txt"))
        for number in range(2, 61):
            (self.src / f"Глава {number}.docx").write_bytes(
                sample.read_bytes())
        started = time.monotonic()
        found = convert.scan([self.src])
        spent = time.monotonic() - started
        self.assertEqual(found["file_count"], 60)
        # Порог с большим запасом: чтение этих же файлов заняло бы
        # секунды, пересчёт имён — доли миллисекунды.
        self.assertLess(spent, 1.0)


class TestRoute(ConvertCase):
    def setUp(self):
        super().setUp()
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()

    def finished(self, job_id: str) -> dict:
        for _ in range(100):
            answer = self.app.get(f"/api/job/{job_id}").get_json()["job"]
            if answer.get("running") is False:
                return answer
            time.sleep(0.05)
        self.fail("задача не кончилась")

    def start(self, **extra) -> dict:
        body = {"targets": [str(self.src)], "base": str(self.out),
                "folder": "Перегон", "format": ".docx"}
        body.update(extra)
        answer = self.app.post("/api/convert/start", json=body)
        self.assertEqual(answer.status_code, 200, answer.get_json())
        return self.finished(answer.get_json()["job"]["id"])

    def test_the_whole_way_through(self):
        self.out.mkdir(parents=True)
        for number in range(1, 4):
            write_chapter(self.src, f"Глава {number}")
        job = self.start()
        self.assertEqual(job["report"]["written"], 3)
        self.assertEqual(
            len(list((self.out / "Перегон").glob("*.docx"))), 3)

    def test_the_counters_reach_the_interface(self):
        """Иначе в окне остаются нули при готовой работе."""
        self.out.mkdir(parents=True)
        write_chapter(self.src, "Глава 1")
        job = self.start()
        self.assertEqual(job["progress"]["written"], 1)
        self.assertEqual(job["progress"]["stage"], "done")

    def test_results_go_to_a_subfolder(self):
        """Перегон в тот же формат иначе затёр бы исходники."""
        self.out.mkdir(parents=True)
        write_chapter(self.src, "Глава 1")
        job = self.start(format=".txt", folder="Своя папка")
        self.assertTrue(job["output_dir"].endswith("Своя папка"))

    def test_an_empty_folder_name_still_lands_somewhere(self):
        self.out.mkdir(parents=True)
        write_chapter(self.src, "Глава 1")
        job = self.start(folder="")
        self.assertNotEqual(Path(job["output_dir"]), self.out)
        self.assertEqual(job["report"]["written"], 1)

    def test_nothing_chosen_is_refused(self):
        answer = self.app.post("/api/convert/start",
                               json={"targets": [], "base": str(self.out)})
        self.assertEqual(answer.status_code, 400)

    def test_missing_destination_is_refused(self):
        write_chapter(self.src, "Глава 1")
        answer = self.app.post("/api/convert/start", json={
            "targets": [str(self.src)], "base": "", "format": ".txt"})
        self.assertEqual(answer.status_code, 400)

    def test_unknown_format_is_refused(self):
        self.out.mkdir(parents=True)
        write_chapter(self.src, "Глава 1")
        answer = self.app.post("/api/convert/start", json={
            "targets": [str(self.src)], "base": str(self.out),
            "format": ".pdf"})
        self.assertEqual(answer.status_code, 400)

    def test_scan_answers_with_the_count(self):
        for number in range(1, 5):
            write_chapter(self.src, f"Глава {number}")
        answer = self.app.post("/api/convert/scan",
                               json={"targets": [str(self.src)]})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.get_json()["file_count"], 4)

    def test_scan_without_a_choice_is_refused(self):
        answer = self.app.post("/api/convert/scan", json={"targets": []})
        self.assertEqual(answer.status_code, 400)

    def test_scan_says_where_the_path_is_wrong(self):
        answer = self.app.post("/api/convert/scan",
                               json={"targets": [str(self.tmp / "нет")]})
        self.assertEqual(answer.status_code, 400)
        self.assertIn("error", answer.get_json())


class TestTabIsWired(unittest.TestCase):
    """Разметка и привязка — здесь нечего вызвать, только сверить."""

    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_the_tab_can_be_opened(self):
        self.assertIn('data-tab="convert"', self.html)
        self.assertIn('id="tab-convert"', self.html)

    def test_every_element_the_code_asks_for_exists(self):
        """Опечатка в id — молчаливая поломка: `$()` вернёт null."""
        import re

        asked = set(re.findall(r"\$\('(cv[A-Za-z]+)'\)", self.js))
        asked |= set(re.findall(r"'(cv[A-Za-z]+)'", self.js))
        # Приставка + общее имя: styleOf/prepOf собирают id из кусков.
        asked |= {"cv" + tail for tail in (
            "Font", "FontOther", "Size", "Spacing", "Indent", "Break",
            "StripTitle", "ItalicSystem", "Align", "Scene", "Encoding",
            "List", "Stop", "Start", "Base")}
        asked.discard("cvScan")   # это имя функции, а не элемента
        asked.discard("cvList")   # список строится кодом, id есть в разметке
        missing = [name for name in sorted(asked)
                   if f'id="{name}"' not in self.html]
        self.assertEqual(missing, [], f"нет в разметке: {missing}")

    def test_the_list_is_read_after_the_choice(self):
        self.assertIn("call('/api/convert/scan'", self.js)

    def test_the_run_goes_to_its_own_route(self):
        self.assertIn("call('/api/convert/start'", self.js)

    def test_options_are_shared_with_the_neighbours(self):
        """Свои копии styleOf/prepOf были бы третьим списком настроек."""
        self.assertIn("styleOf('cv'", self.js)
        self.assertIn("prepOf('cv'", self.js)

    def test_the_stop_button_is_bound_like_the_others(self):
        self.assertIn("['cv', cvState, cvUpdateFinal, cvScan]", self.js)


if __name__ == "__main__":
    unittest.main()
