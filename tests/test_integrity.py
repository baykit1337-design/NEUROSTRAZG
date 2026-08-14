"""Тесты правок NEUROSTRAZH: целостность, дубли, «В TXT», потоки, оформление."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import api, integrity, textcheck, totxt  # noqa: E402
from mvl.client import Client  # noqa: E402
from mvl.downloader import MAX_THREADS, Downloader  # noqa: E402


class TestNumbering(unittest.TestCase):
    """7.2: целостность нумерации по именам файлов."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)

    def make(self, names) -> list[Path]:
        for name in names:
            (self.tmp / name).write_text("текст", encoding="utf-8")
        return sorted(self.tmp.iterdir())

    def test_clean_run_reports_nothing(self):
        report = integrity.check_numbering(self.make(
            [f"Глава {n}.txt" for n in range(201, 210)]))
        self.assertTrue(report.clean)
        self.assertIn("нумерация целая", report.summary())

    def test_missing_chapter(self):
        report = integrity.check_numbering(self.make(
            ["Глава 201.txt", "Глава 202.txt", "Глава 204.txt"]))
        self.assertEqual(report.missing, [203])

    def test_duplicate_number(self):
        report = integrity.check_numbering(self.make(
            ["Глава 205. А.txt", "Глава 205. Б.txt", "Глава 206.txt"]))
        self.assertEqual(len(report.duplicates), 1)
        self.assertEqual(report.duplicates[0]["number"], 205)

    def test_missing_part(self):
        report = integrity.check_numbering(self.make(
            ["Глава 201.1.txt", "Глава 201.3.txt"]))
        self.assertEqual(report.missing_parts, ["201.2"])

    def test_all_parts_present_is_clean(self):
        report = integrity.check_numbering(self.make(
            ["Глава 201.1.txt", "Глава 201.2.txt"]))
        self.assertEqual(report.missing_parts, [])

    def test_out_of_range_chapter(self):
        names = [f"Глава {n}.txt" for n in range(201, 210)] + ["Глава 999.txt"]
        report = integrity.check_numbering(self.make(names))
        self.assertEqual([row["number"] for row in report.out_of_range], [999])

    def test_outlier_does_not_inflate_missing(self):
        """Глава 999 среди 201–209 не должна давать 790 «пропусков»."""
        names = [f"Глава {n}.txt" for n in range(201, 210)] + ["Глава 999.txt"]
        report = integrity.check_numbering(self.make(names))
        self.assertEqual(report.missing, [])

    def test_unnumbered_files_listed_separately(self):
        report = integrity.check_numbering(self.make(
            ["Глава 201.txt", "Информация.txt"]))
        self.assertEqual(report.unnumbered, ["Информация.txt"])

    def test_summary_format_from_spec(self):
        names = [f"Глава {n}.txt" for n in range(201, 210) if n != 203]
        names += ["Глава 205. Дубль.txt"]
        summary = integrity.check_numbering(self.make(names)).summary()
        self.assertIn("Глав:", summary)
        self.assertIn("пропущено:", summary)
        self.assertIn("дублей:", summary)

    def test_compact_ranges(self):
        self.assertEqual(integrity._compact([1, 2, 3, 7]), "1–3, 7")


class TestDuplicateChapters(unittest.TestCase):
    """7.1: главы с одинаковым или почти одинаковым текстом."""

    BODY = "Это довольно длинный текст главы, который может повториться. " * 8

    def test_exact_duplicate(self):
        pairs = integrity.find_duplicates({"a.txt": self.BODY, "b.txt": self.BODY})
        self.assertEqual(len(pairs), 1)
        self.assertTrue(pairs[0].exact)

    def test_near_duplicate_reported_with_percent(self):
        pairs = integrity.find_duplicates({
            "a.txt": self.BODY,
            "b.txt": self.BODY + " И ещё одно предложение в конце.",
        })
        self.assertEqual(len(pairs), 1)
        self.assertFalse(pairs[0].exact)
        self.assertGreaterEqual(pairs[0].as_dict()["percent"], 90)

    def test_different_chapters_are_not_paired(self):
        pairs = integrity.find_duplicates({
            "a.txt": self.BODY,
            "b.txt": "Совершенно другой текст без единого совпадения. " * 8,
        })
        self.assertEqual(pairs, [])

    def test_normalisation_ignores_case_and_punctuation(self):
        pairs = integrity.find_duplicates({
            "a.txt": self.BODY,
            "b.txt": self.BODY.upper().replace(".", "!"),
        })
        self.assertEqual(len(pairs), 1)
        self.assertTrue(pairs[0].exact)

    def test_short_texts_are_skipped(self):
        pairs = integrity.find_duplicates({"a.txt": "Коротко.", "b.txt": "Коротко."})
        self.assertEqual(pairs, [])

    def test_many_chapters_stay_fast(self):
        """Посимвольное сравнение всех пар вешало книгу из 165 глав."""
        import time

        texts = {f"Глава {n}.txt": f"Уникальный текст главы {n}. " * 40 for n in range(165)}
        texts["dup-a.txt"] = self.BODY
        texts["dup-b.txt"] = self.BODY

        started = time.monotonic()
        pairs = integrity.find_duplicates(texts)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 10, f"проверка заняла {elapsed:.1f} с")
        self.assertTrue(any(p.exact for p in pairs))

    def test_shingles_catch_near_duplicates(self):
        left = integrity.shingles(integrity.normalize(self.BODY))
        right = integrity.shingles(integrity.normalize(self.BODY + " Хвостик."))
        self.assertGreater(integrity.jaccard(left, right), 0.8)

    def test_shingles_separate_different_texts(self):
        left = integrity.shingles(integrity.normalize(self.BODY))
        right = integrity.shingles(integrity.normalize("Совсем другой текст. " * 8))
        self.assertLess(integrity.jaccard(left, right), 0.2)

    def test_pair_reports_both_files(self):
        row = integrity.find_duplicates({"a.txt": self.BODY, "b.txt": self.BODY})[0].as_dict()
        self.assertEqual({row["left"], row["right"]}, {"a.txt", "b.txt"})


class TestIntegrityInCheck(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)

    def test_numbering_reaches_the_report(self):
        for n in (201, 202, 204):
            (self.tmp / f"Глава {n}.txt").write_text("Текст. " * 40, encoding="utf-8")
        report = textcheck.check(self.tmp, ["numbering"])
        self.assertIn("203", report.numbering["summary"])
        self.assertFalse(report.numbering["clean"])

    def test_duplicates_reach_the_report(self):
        body = "Длинный повторяющийся текст главы для сравнения. " * 8
        (self.tmp / "Глава 201.txt").write_text(body, encoding="utf-8")
        (self.tmp / "Глава 202.txt").write_text(body, encoding="utf-8")
        report = textcheck.check(self.tmp, ["dupes"])
        self.assertEqual(len(report.duplicate_pairs), 1)

    def test_both_rules_are_registered(self):
        self.assertIn("numbering", textcheck.ALL_KINDS)
        self.assertIn("dupes", textcheck.ALL_KINDS)


class TestToTxt(unittest.TestCase):
    """Раздел 6: множество файлов → один .txt."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)
        self.src = self.tmp / "главы"
        self.src.mkdir()
        for number in (201, 202, 210):
            (self.src / f"0{number} - Глава {number}. Имя {number}.txt").write_text(
                f"Первый абзац {number}.\n\nВторой абзац {number}.\n", encoding="utf-8"
            )

    def build(self, **kwargs) -> str:
        out = self.tmp / "книга.txt"
        totxt.build([str(self.src)], out, **kwargs)
        return out.read_text(encoding=kwargs.get("encoding", "utf-8"))

    def test_all_chapters_in_one_file(self):
        text = self.build()
        for number in (201, 202, 210):
            self.assertIn(f"Первый абзац {number}.", text)

    def test_headings_added_from_filename(self):
        self.assertIn("Глава 201. Имя 201", self.build(headings=True))

    def test_headings_can_be_switched_off(self):
        self.assertNotIn("Глава 201. Имя 201", self.build(headings=False))

    def test_each_separator(self):
        for key, mark in totxt.SEPARATORS.items():
            if not mark:
                continue
            with self.subTest(key=key):
                self.assertIn(mark, self.build(separator=key))

    def test_custom_separator(self):
        self.assertIn("~~~", self.build(separator="custom", custom_separator="~~~"))

    def test_order_by_chapter_number(self):
        text = self.build(order=totxt.ORDER_NUMBER)
        self.assertLess(text.index("абзац 201"), text.index("абзац 210"))

    def test_windows_1251_encoding(self):
        out = self.tmp / "cp.txt"
        totxt.build([str(self.src)], out, encoding="windows-1251")
        self.assertIn("Глава", out.read_text(encoding="windows-1251"))

    def test_unknown_encoding_refused(self):
        with self.assertRaises(totxt.TxtError):
            totxt.build([str(self.src)], self.tmp / "x.txt", encoding="koi8-r")

    def test_unknown_order_refused(self):
        with self.assertRaises(totxt.TxtError):
            totxt.build([str(self.src)], self.tmp / "x.txt", order="случайно")

    def test_missing_folder_reports_clearly(self):
        with self.assertRaises(totxt.TxtError):
            totxt.build([str(self.tmp / "нет")], self.tmp / "x.txt")

    def test_cancel(self):
        from mvl.booksplit import Cancelled

        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            totxt.build([str(self.src)], self.tmp / "x.txt", cancel=cancel)

    def test_progress_reported(self):
        seen = []
        totxt.build([str(self.src)], self.tmp / "x.txt",
                    on_progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_scan_before_running(self):
        info = totxt.scan([str(self.src)])
        self.assertEqual(info["total"], 3)


class _Handler(BaseHTTPRequestHandler):
    block_from: int | None = None

    def log_message(self, *args):
        pass

    def do_GET(self):
        number = int(self.path.rsplit("-", 1)[-1])
        time.sleep(0.15)
        if _Handler.block_from is not None and number >= _Handler.block_from:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"no")
            return
        body = (
            f'<html><body><h2 id="chapter-name">Глава {number}</h2>'
            f'<div id="chapter"><p>' + "слова " * 40 + "</p></div></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _DownloadCase(unittest.TestCase):
    """Общая обвязка: локальный сервер вместо витрины, восемь глав.

    Отдельным классом, а не наследованием тестов друг от друга: иначе
    каждый набор гоняет ещё и чужие тесты.
    """

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _Handler.block_from = None
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)

        self.novel = api.Novel(code=6615, name="Книга", slug="k", total_chapters=8)
        chapters = [
            api.Chapter(number=n, ch_name=f"Глава {n}",
                        link=f"{self.base}/chapter/6615-{n}")
            for n in range(1, 9)
        ]

        class Toc:
            pass

        toc = Toc()
        toc.chapters = chapters
        toc.missing = []

        self.original_toc = api.fetch_toc
        api.fetch_toc = lambda *a, **k: toc
        self.addCleanup(lambda: setattr(api, "fetch_toc", self.original_toc))

    def run_download(self, threads: int, probe: bool = False, **kwargs):
        # Автопроба здесь выключена: эти тесты проверяют сам механизм пачек.
        # Её собственное поведение проверяется ниже, в TestAutoprobeRun.
        downloader = Downloader(
            client=Client(), site_client=Client(max_attempts=1), threads=threads,
            probe=probe, **kwargs
        )
        downloader.pause_multiplier = 0.01
        return downloader, downloader.run(self.novel, self.tmp, first=1, last=8)


class TestParallelDownload(_DownloadCase):
    """Раздел 5: скачивание пачками."""

    def test_ceiling_is_six(self):
        self.assertEqual(Downloader(threads=99).threads, MAX_THREADS)

    def test_default_is_single_thread(self):
        self.assertEqual(Downloader().threads, 1)

    def test_parallel_downloads_everything(self):
        _, report = self.run_download(3)
        self.assertEqual(report.downloaded, 8)
        self.assertEqual(len(list(self.tmp.glob("*.txt"))), 8)

    def test_parallel_is_faster_than_single(self):
        started = time.monotonic()
        self.run_download(4)
        parallel = time.monotonic() - started

        for path in self.tmp.glob("*"):
            path.unlink()
        started = time.monotonic()
        self.run_download(1)
        single = time.monotonic() - started

        self.assertLess(parallel, single)

    def test_refusal_stops_the_whole_run(self):
        _Handler.block_from = 4
        downloader, report = self.run_download(3)
        self.assertIsNotNone(report.blocked_at)
        self.assertTrue(report.stopped_reason)

    def test_threads_drop_to_one_after_a_refusal(self):
        _Handler.block_from = 4
        downloader, report = self.run_download(3)
        self.assertTrue(report.threads_downgraded)
        self.assertEqual(downloader.threads, 1)

    def test_report_records_thread_count(self):
        _, report = self.run_download(2)
        self.assertEqual(report.threads, 2)


class TestAutoprobeRun(_DownloadCase):
    """A4: способ скачивания подбирается пробным прогоном перед основным."""

    def test_probe_runs_and_reports(self):
        downloader, report = self.run_download(3, probe=True)
        self.assertIsNotNone(downloader.probe_report)
        self.assertTrue(downloader.probe_report.attempts)
        # Что бы проба ни решила, главы должны быть скачаны все.
        self.assertEqual(report.downloaded, 8)

    def test_blocked_site_falls_back_to_sequential(self):
        """403 на пробе — не ошибка: качаем по очереди и говорим об этом."""
        _Handler.block_from = 1
        downloader = Downloader(
            client=Client(), site_client=Client(max_attempts=1), threads=3,
            probe=True,
        )
        downloader.pause_multiplier = 0.01
        downloader.run(self.novel, self.tmp, first=1, last=8)

        probe = downloader.probe_report
        self.assertIsNotNone(probe)
        self.assertFalse(probe.parallel)
        self.assertEqual(downloader.threads, 1)
        self.assertEqual(
            probe.message,
            "Многопоточность недоступна. Скачивание идёт по очереди.")

    def test_manual_mode_skips_the_probe(self):
        """Ручной режим берёт указанное число потоков без пробы."""
        downloader, report = self.run_download(3, probe=False)
        self.assertIsNone(downloader.probe_report)
        self.assertEqual(report.threads, 3)
        self.assertEqual(report.downloaded, 8)

    def test_probe_skipped_for_single_thread(self):
        downloader, _ = self.run_download(1, probe=True)
        self.assertIsNone(downloader.probe_report)

    def test_probe_result_reaches_progress(self):
        seen = []
        downloader = Downloader(
            client=Client(), site_client=Client(max_attempts=1), threads=3,
            probe=True, on_progress=lambda p: seen.append(p.as_dict()),
        )
        downloader.pause_multiplier = 0.01
        downloader.run(self.novel, self.tmp, first=1, last=8)
        # Интерфейс показывает уведомление именно по этому полю.
        self.assertTrue(any(step.get("probe", {}).get("message") for step in seen))


class TestNeurostrazhWebApi(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)
        from webapp.app import app

        app.config["TESTING"] = True
        self.app = app.test_client()

        self.src = self.tmp / "главы"
        self.src.mkdir()
        for number in (201, 202):
            (self.src / f"Глава {number}.txt").write_text(
                f"Текст главы {number}.\n", encoding="utf-8")

    def test_merge_scan(self):
        res = self.app.post("/api/merge/scan", json={"targets": [str(self.src)]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["total"], 2)

    def test_merge_job(self):
        from webapp.app import JOBS

        res = self.app.post("/api/merge/start", json={
            "targets": [str(self.src)], "base": str(self.tmp), "name": "Книга",
            "format": "txt"})
        job_id = res.get_json()["job"]["id"]
        JOBS[job_id].thread.join(timeout=60)

        job = self.app.get(f"/api/job/{job_id}").get_json()["job"]
        self.assertIsNone(job["error"])
        self.assertTrue((self.tmp / "Книга.txt").is_file())

    def test_merge_rejects_unknown_encoding(self):
        res = self.app.post("/api/merge/start", json={
            "targets": [str(self.src)], "base": str(self.tmp),
            "name": "К", "format": "txt", "encoding": "koi8-r"})
        self.assertEqual(res.status_code, 400)

    def test_manual_mode_reaches_the_downloader(self):
        """Переключатель режима должен доходить до качалки, а не теряться."""
        import inspect

        from webapp import app as webapp_app

        source = inspect.getsource(webapp_app.api_start)
        self.assertIn('payload.get("mode")', source)
        self.assertIn("probe=probe", source)

    def test_download_rejects_too_many_threads(self):
        res = self.app.post("/api/start", json={
            "novel": {"code": 1, "name": "x", "total_chapters": 1},
            "base": str(self.tmp), "folder": "т", "threads": 99})
        self.assertEqual(res.status_code, 400)

    def test_numbering_rule_offered_by_the_api(self):
        body = self.app.get("/api/check/rules").get_json()
        keys = {rule["key"] for group in body["groups"] for rule in group["rules"]}
        self.assertIn("numbering", keys)
        self.assertIn("dupes", keys)


class TestNeurostrazhStyles(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent.parent
        self.html = (root / "webapp" / "static" / "index.html").read_text(encoding="utf-8")

    def test_cards_have_base_glow_not_only_on_hover(self):
        block = self.html.split("  .card{")[1].split("}")[0]
        self.assertIn("box-shadow", block)
        self.assertIn("inset", block)

    def test_checkboxes_are_custom(self):
        self.assertIn("input[type=checkbox]{", self.html)
        self.assertIn("appearance:none", self.html)
        self.assertIn("input[type=checkbox]:checked::after", self.html)

    def test_spin_wrapper_is_positioned(self):
        block = self.html.split("  .spin-wrap{")[1].split("}")[0]
        self.assertIn("position:relative", block)

    def test_indicator_has_all_states(self):
        for state in ("running", "done", "error"):
            self.assertIn(f".result-block.{state}", self.html)

    def test_pulse_driven_by_one_variable_on_the_parent(self):
        """Одна анимация на блок — фазы кружка и текста не разъедутся."""
        self.assertIn("@property --glow", self.html)
        self.assertIn(".result-block.running{animation:mvl-glow 1s", self.html)
        self.assertIn(".result-block.done   {animation:mvl-glow 1.9s", self.html)
        self.assertIn("var(--glow)", self.html)

    def test_tabs_never_wrap_to_a_second_line(self):
        """Меню в одну строку при любом числе вкладок — переноса быть не должно."""
        self.assertIn("flex-wrap:nowrap", self.html)
        # Именно у меню, а не где-то ещё.
        block = self.html[self.html.index(".tabs{"):]
        self.assertIn("flex-wrap:nowrap", block[:600])
        self.assertNotIn("flex-wrap:wrap", block[:600])

    def test_icons_give_way_to_labels(self):
        """Девять вкладок в строку влезают только без значков."""
        self.assertIn("@media (max-width:1240px){ .tabs button svg{display:none} }",
                      self.html)

    def test_open_dropdown_covers_the_next_card(self):
        """Карточка размывает фон и делает свой слой: без подъёма самой
        карточки раскрытый список уходил под следующую."""
        self.assertIn(".card:has(.dropdown-menu:not([hidden])){z-index:40}",
                      self.html)

    def test_threads_field_present(self):
        self.assertIn('id="dlThreads"', self.html)

    def test_tabs_are_split_and_merge(self):
        """A1: «В Word» и «В TXT» упразднены, формат стал параметром."""
        for name in ("split", "merge"):
            self.assertIn(f'data-tab="{name}"', self.html)
            self.assertIn(f'id="tab-{name}"', self.html)
        for gone in ("word", "totxt"):
            self.assertNotIn(f'data-tab="{gone}"', self.html)
            self.assertNotIn(f'id="tab-{gone}"', self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
