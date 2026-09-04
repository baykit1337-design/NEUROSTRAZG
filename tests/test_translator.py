"""Связь с переводчиком EPUB — чужой программой, стоящей рядом.

Настоящий переводчик сюда не поставить: он тянет PyQt6, google-genai и
браузер, и ему нужны ключи. Поэтому здесь поддельный — папка с
`gemini_translator/cli.py`, который печатает JSON в stdout и логи в
stderr, ровно как настоящий. Проверяется наш разбор и наш запуск, а не
чужая программа: запуск при этом настоящий, отдельным процессом.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from ops import translator  # noqa: E402
from ops.base import Cancelled  # noqa: E402

#: Ответ, похожий на настоящий: провайдеры, ключи, сохранённые настройки.
ANSWER = {
    "ok": True,
    "providers": [
        {"id": "gemini", "name": "Google Gemini Free", "keys": 69,
         "models": 12},
        {"id": "deepseek", "name": "Deepseek API", "keys": 0, "models": 3},
    ],
    "settings": {"provider": "gemini", "model": "Gemini 3.0 Flash Preview"},
    "projects": [{"name": "БЕГИТЕ"}, {"name": "ПИТОМЦЫ"}],
}


def fake_translator(folder: Path, prints=None, noise="", code=0) -> Path:
    """Папка, которую наш код примет за переводчик."""
    package = folder / "gemini_translator"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    body = json.dumps(ANSWER if prints is None else prints, ensure_ascii=False)
    (package / "cli.py").write_text(
        "import sys\n"
        f"print({noise!r}, file=sys.stderr)\n"
        f"sys.stdout.write({body!r})\n"
        f"raise SystemExit({code})\n",
        encoding="utf-8")
    return folder


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        was = (settings.translator.path, settings.translator.python)
        self.addCleanup(self.restore, was)
        # Свой Python: у поддельного переводчика окружения рядом нет.
        settings.translator.python = sys.executable
        settings.translator.path = ""

    def restore(self, was):
        settings.translator.path, settings.translator.python = was


class TestFindingTheProgram(Base):
    def test_a_folder_with_the_cli_is_the_translator(self):
        self.assertTrue(translator.looks_right(fake_translator(self.tmp)))

    def test_any_other_folder_is_not(self):
        self.assertFalse(translator.looks_right(self.tmp / "пусто"))

    def test_an_empty_path_is_not(self):
        self.assertFalse(translator.looks_right(""))

    def test_its_own_environment_wins_over_the_settings(self):
        """Рядом с переводчиком стоят его зависимости, а у нас их нет."""
        home = fake_translator(self.tmp)
        where = home / ".venv" / "bin"
        where.mkdir(parents=True)
        (where / "python").write_text("", encoding="utf-8")
        self.assertEqual(translator.python_for(home), str(where / "python"))

    def test_without_its_own_environment_we_take_what_is_named(self):
        settings.translator.python = "/opt/python"
        self.assertEqual(translator.python_for(fake_translator(self.tmp)),
                         "/opt/python")


class TestTalkingToIt(Base):
    def test_the_answer_is_read(self):
        said = translator.status(str(fake_translator(self.tmp)))
        self.assertEqual(said["providers"][0]["keys"], 69)

    def test_logs_in_stderr_do_not_break_the_reading(self):
        """У настоящего логи идут в stderr именно ради этого."""
        home = fake_translator(self.tmp, noise="INFO: поднимаю движок")
        self.assertTrue(translator.status(str(home))["ok"])

    def test_the_summary_is_what_the_person_sees(self):
        short = translator.short(translator.status(str(fake_translator(self.tmp))))
        self.assertEqual(short["keys"], 69)
        self.assertEqual(short["provider"], "gemini")
        self.assertEqual(short["projects"], 2)
        self.assertEqual(len(short["providers"]), 2)

    def test_a_changed_format_does_not_break_us(self):
        """Формат чужой и может поменяться — падать на этом нельзя."""
        home = fake_translator(self.tmp, prints={"ok": True, "что-то": "иное"})
        short = translator.short(translator.status(str(home)))
        self.assertEqual(short["keys"], 0)
        self.assertEqual(short["providers"], [])


class TestWhenItGoesWrong(Base):
    def why(self, path):
        with self.assertRaises(translator.TranslatorError) as caught:
            translator.status(str(path))
        return str(caught.exception)

    def test_no_path_is_explained(self):
        self.assertIn("Не указано", self.why(""))

    def test_a_missing_folder_is_explained(self):
        self.assertIn("Папки нет", self.why(self.tmp / "нет-такой"))

    def test_a_wrong_folder_names_what_is_missing(self):
        (self.tmp / "чужая").mkdir()
        said = self.why(self.tmp / "чужая")
        self.assertIn("gemini_translator/cli.py", said)
        self.assertIn("не папка переводчика", said)

    def test_an_old_version_is_not_called_a_wrong_folder(self):
        """Та же беда с другим лечением.

        У переводчика работа без окна появилась не сразу: в копиях
        постарше `cli.py` нет вовсе, хотя `main.py` и `run.bat` на месте.
        Отказ «это не папка переводчика» отправлял человека искать то,
        что у него и так лежит перед глазами.
        """
        home = self.tmp / "старая"
        (home / "gemini_translator").mkdir(parents=True)
        (home / "gemini_translator" / "__init__.py").write_text(
            "", encoding="utf-8")
        (home / "main.py").write_text("", encoding="utf-8")
        (home / "run.bat").write_text("", encoding="utf-8")

        said = self.why(home)
        self.assertIn("версия переводчика старая", said)
        self.assertIn("Обновите", said)
        # И сразу успокаиваем про то, что обычно и держит от обновления.
        self.assertIn(".epub_translator", said)
        self.assertTrue(translator.looks_old(home))

    def built(self, where: str = "") -> Path:
        """Собранная версия: нутро PyInstaller вместо исходников."""
        home = self.tmp / "сборка"
        inside = home / where if where else home
        inside.mkdir(parents=True)
        (inside / translator.BUILT_MARK).write_text("", encoding="utf-8")
        # Папки чужих пакетов в сборке есть, а `.py` в них нет.
        (inside / "gemini_translator").mkdir()
        return home

    def test_a_built_version_is_not_called_a_wrong_folder(self):
        """Третья беда с третьим лечением.

        Человек скачал релиз, а не исходники. Питон в сборке уже
        скомпилирован, и `cli.py` там нет ни на одном уровне — совет
        «возьмите папку выше» тут тупик, а прежний отказ отправлял
        искать файл, которого у него в принципе нет.
        """
        said = self.why(self.built("_internal"))

        # Не по словам отказа, а по тому, что он называет: примету сборки
        # и файл, которого в ней нет.
        self.assertIn(translator.BUILT_MARK, said)
        self.assertIn(translator.MARK.as_posix(), said)
        self.assertNotIn("не папка переводчика", said)
        # И сразу говорим, что делать, и чем это не грозит.
        self.assertIn("исходник", said)
        self.assertIn(".epub_translator", said)

    def test_the_inner_folder_of_a_build_is_recognised_too(self):
        """Указать могут и саму `_internal` — так и вышло."""
        self.assertTrue(translator.looks_built(self.built() ))
        self.assertTrue(translator.looks_built(self.built("_internal")))

    def test_a_folder_with_sources_is_not_called_a_build(self):
        self.assertFalse(translator.looks_built(fake_translator(self.tmp)))

    def test_a_fresh_version_is_not_called_old(self):
        home = fake_translator(self.tmp)
        (home / "main.py").write_text("", encoding="utf-8")
        self.assertFalse(translator.looks_old(home))

    def test_not_json_is_shown_as_it_came(self):
        """Молчаливое «что-то пошло не так» здесь бесполезно."""
        home = self.tmp / "битый"
        package = home / "gemini_translator"
        package.mkdir(parents=True)
        (package / "cli.py").write_text("print('Traceback: беда')",
                                        encoding="utf-8")
        self.assertIn("беда", self.why(home))

    def test_silence_is_explained_by_the_last_log_line(self):
        home = self.tmp / "молчун"
        package = home / "gemini_translator"
        package.mkdir(parents=True)
        (package / "cli.py").write_text(
            "import sys\nprint('ModuleNotFoundError: PyQt6', file=sys.stderr)",
            encoding="utf-8")
        self.assertIn("PyQt6", self.why(home))

    def test_a_refusal_in_the_answer_is_a_refusal(self):
        home = fake_translator(self.tmp, prints={"ok": False,
                                                 "error": "нет ключей"})
        self.assertIn("нет ключей", self.why(home))

    def test_a_missing_python_says_what_to_do(self):
        settings.translator.python = "/нет/такого/python"
        home = fake_translator(self.tmp)
        self.assertIn("run.bat", self.why(home))


class TestOverHttp(Base):
    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()

    def test_the_state_is_empty_until_a_path_is_given(self):
        got = self.app.get("/api/translator/state").get_json()
        self.assertFalse(got["found"])

    def test_a_wrong_folder_is_refused_at_once(self):
        """Сказать «не та папка» при выборе полезнее, чем через полчаса."""
        (self.tmp / "чужая").mkdir()
        res = self.app.post("/api/translator/path",
                            json={"path": str(self.tmp / "чужая")})
        self.assertEqual(res.status_code, 400)
        self.assertIn("cli.py", res.get_json()["error"])

    def test_an_old_version_is_told_apart_over_http_too(self):
        home = self.tmp / "старая"
        (home / "gemini_translator").mkdir(parents=True)
        (home / "gemini_translator" / "__init__.py").write_text(
            "", encoding="utf-8")
        (home / "main.py").write_text("", encoding="utf-8")

        got = self.app.post("/api/translator/path",
                            json={"path": str(home)}).get_json()
        self.assertTrue(got["old"])
        self.assertIn("старая", got["error"])

    def test_a_right_folder_is_remembered(self):
        home = fake_translator(self.tmp)
        got = self.app.post("/api/translator/path",
                            json={"path": str(home)}).get_json()
        self.assertTrue(got["found"])
        self.assertEqual(settings.translator.path, str(home))

    def test_the_check_shows_the_keys(self):
        home = fake_translator(self.tmp)
        got = self.app.post("/api/translator/check",
                            json={"path": str(home)}).get_json()
        self.assertEqual(got["keys"], 69)
        self.assertEqual(got["providers"][0]["name"], "Google Gemini Free")

    def test_a_broken_check_answers_with_words(self):
        res = self.app.post("/api/translator/check",
                            json={"path": str(self.tmp / "нет-такой")})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Папки нет", res.get_json()["error"])


class TestWeStoreNothingOfItsOwn(unittest.TestCase):
    """Глоссарий, промпты и ключи остаются у переводчика.

    Стоит нам завести своё хранилище — и оно разойдётся с его. Здесь
    проверяется, что мы даже не пытаемся: в модуле нет ни чтения его
    папок, ни записи в них.
    """

    def test_we_do_not_touch_its_home_folder(self):
        body = Path(translator.__file__).read_text(encoding="utf-8")
        for name in ("epub_translator", "project_glossary", "prompts.json",
                     "settings.json"):
            # Упоминание в пояснении — не обращение: смотрим на код.
            code = "\n".join(line for line in body.splitlines()
                             if not line.strip().startswith("#"))
            self.assertNotIn(f'"{name}', code, name)


if __name__ == "__main__":
    unittest.main()


class TestAMissingPackageIsExplained(Base):
    """Голое `ModuleNotFoundError: No module named 'fs'` в карточке —
    тупик: человек видит чужую питоновскую ошибку и не знает ни чей это
    пакет, ни куда его ставить.

    А беда обычная: взяли исходники и не поставили им зависимости.
    """

    def why(self, home) -> str:
        settings.translator.path = str(home)
        with self.assertRaises(translator.TranslatorError) as caught:
            translator.status(str(home))
        return str(caught.exception)

    def test_the_refusal_names_the_package_and_the_cure(self):
        home = fake_translator(
            self.tmp,
            prints={"ok": False,
                    "error": "ModuleNotFoundError: No module named 'fs'"})
        said = self.why(home)

        self.assertIn("fs", said)
        self.assertIn(translator.NEEDS, said)

    def test_silence_with_the_same_cause_gets_the_same_cure(self):
        """Нехватка пакета валит команду и до JSON, и молча."""
        home = self.tmp / "молчун"
        package = home / "gemini_translator"
        package.mkdir(parents=True)
        (package / "cli.py").write_text(
            "import sys\n"
            "print(\"ModuleNotFoundError: No module named 'fs'\", file=sys.stderr)",
            encoding="utf-8")

        self.assertIn(translator.NEEDS, self.why(home))

    def test_other_refusals_are_left_as_they_came(self):
        """Не всякий отказ лечится установкой пакетов."""
        home = fake_translator(self.tmp,
                               prints={"ok": False, "error": "нет ключей"})
        said = self.why(home)

        self.assertIn("нет ключей", said)
        self.assertNotIn(translator.NEEDS, said)


#: Как выглядит ответ `plan` у настоящего переводчика. Снято с живого
#: прогона: словарь чужой, и выдумывать его форму нельзя.
PLAN = {
    "ok": True,
    "epub": "/книги/проба.epub",
    "project": "/книги/проект",
    "plan": {
        "task_count": 5,
        "chapter_count": 3,
        "chapters": ["OEBPS/0001.xhtml", "OEBPS/0002.xhtml",
                     "OEBPS/0003.xhtml"],
        "total_source_tokens": 987,
        "total_source_chars": 987,
    },
    "settings": {
        "provider": "gemini",
        "model": "Gemini 3.7 Flash",
        "model_config": {"rpm": 5, "rpd": 20},
    },
}


class TestThePlanBeforeThePay(Base):
    """План — это «до и после» для перевода.

    Цена тут не в деньгах, а в квоте ключей, и промахнуться дороже всего:
    узнать, что взялась вся книга вместо десяти глав, посреди прогона
    поздно.
    """

    def setUp(self):
        super().setUp()
        self.book = self.tmp / "проба.epub"
        self.book.write_bytes(b"PK\x03\x04")

    def echoing(self) -> Path:
        """Переводчик, который печатает то, о чём его попросили."""
        home = self.tmp / "эхо"
        package = home / "gemini_translator"
        package.mkdir(parents=True)
        (package / "cli.py").write_text(
            "import json, sys\n"
            "print(json.dumps({'ok': True, 'плану сказали': sys.argv[1:]}))\n",
            encoding="utf-8")
        return home

    def why(self, **kw) -> str:
        with self.assertRaises(translator.TranslatorError) as caught:
            translator.plan(**kw)
        return str(caught.exception)

    def test_a_missing_book_is_refused_before_the_translator_is_started(self):
        said = self.why(epub=str(self.tmp / "нет.epub"), project="п",
                        path=str(fake_translator(self.tmp)))
        self.assertIn("Файла нет", said)

    def test_no_book_at_all_is_refused(self):
        self.assertIn("epub", self.why(epub="", project="п", path=""))

    def test_no_project_folder_is_refused_and_explained(self):
        """Переводчику некуда складывать — и он об этом молчит."""
        said = self.why(epub=str(self.book), project="",
                        path=str(fake_translator(self.tmp)))
        self.assertIn("папка проекта", said.lower())

    def test_an_unknown_scope_is_refused(self):
        said = self.why(epub=str(self.book), project="п", scope="абы что",
                        path=str(fake_translator(self.tmp)))
        self.assertIn("какие главы", said)

    def test_the_translator_is_asked_exactly_what_was_chosen(self):
        home = self.echoing()
        said = translator.plan(str(self.book), str(self.tmp / "проект"),
                               translator.WHOLE, str(home))
        asked = said["плану сказали"]

        self.assertEqual(asked[0], "plan")
        self.assertIn("--epub", asked)
        self.assertEqual(asked[asked.index("--epub") + 1], str(self.book))
        self.assertEqual(asked[asked.index("--chapters") + 1], translator.WHOLE)

    def test_the_answer_is_read_into_what_the_page_shows(self):
        short = translator.short_plan(PLAN)

        self.assertEqual(short["chapters"], 3)
        self.assertEqual(short["tasks"], 5)
        self.assertEqual(short["chars"], 987)
        self.assertEqual(short["provider"], "gemini")
        self.assertEqual(short["model"], "Gemini 3.7 Flash")
        # Квота — то, ради чего план и смотрят.
        self.assertEqual((short["rpm"], short["rpd"]), (5, 20))
        self.assertEqual(len(short["sample"]), 3)

    def test_a_changed_format_does_not_break_us(self):
        """Формат чужой и может поменяться — падать на этом нельзя."""
        short = translator.short_plan({"ok": True, "что-то": "иное"})

        self.assertEqual(short["chapters"], 0)
        self.assertEqual(short["provider"], "")
        self.assertEqual(short["sample"], [])

    def test_a_long_book_is_not_listed_whole(self):
        """На пятистах главах список перестаёт быть ответом."""
        many = dict(PLAN)
        many["plan"] = dict(PLAN["plan"])
        many["plan"]["chapters"] = [f"{n}.xhtml" for n in range(300)]
        short = translator.short_plan(many)

        self.assertEqual(len(short["sample"]), translator.SHOW_CHAPTERS)
        self.assertEqual(short["more"], 300 - translator.SHOW_CHAPTERS)


class TestThePlanOverHttp(Base):
    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()
        self.book = self.tmp / "проба.epub"
        self.book.write_bytes(b"PK\x03\x04")

    def ask(self, **kw):
        body = {"path": str(fake_translator(self.tmp, prints=PLAN)),
                "epub": str(self.book), "project": str(self.tmp / "проект")}
        body.update(kw)
        return self.app.post("/api/translator/plan", json=body)

    def test_the_plan_reaches_the_page(self):
        got = self.ask().get_json()
        self.assertTrue(got["ok"])
        self.assertEqual(got["chapters"], 3)
        self.assertEqual(got["rpd"], 20)

    def test_a_missing_book_is_a_refusal_not_a_crash(self):
        res = self.ask(epub=str(self.tmp / "нет.epub"))
        self.assertEqual(res.status_code, 400)
        self.assertIn("Файла нет", res.get_json()["error"])

    def test_the_plan_is_counted_for_the_chosen_model(self):
        """Иначе план отвечает про чужую квоту.

        Ответ плана мы показываем разобранным, и аргументы в нём не
        видны. Поэтому поддельный переводчик кладёт их туда, где список
        глав, — единственное окно, через которое их отсюда видно.
        """
        home = self.tmp / "эхо-план"
        (home / "gemini_translator").mkdir(parents=True)
        (home / "gemini_translator" / "cli.py").write_text(
            "import json, sys\n"
            # Только эта пара: список глав в ответе обрезается, и клади мы
            # туда все аргументы, проверка ломалась бы от каждого нового
            # флага — по причине, к сервису и модели не относящейся.
            "a = sys.argv[1:]\n"
            "pair = ('--provider', '--model')\n"
            "want = [x for i, x in enumerate(a)\n"
            "        if x in pair or (i and a[i - 1] in pair)]\n"
            "print(json.dumps({'ok': True, 'plan': {'chapters': want}}))\n",
            encoding="utf-8")

        got = self.ask(path=str(home), provider="deepseek",
                       model="Кот 9.0").get_json()
        asked = got["sample"]

        self.assertEqual(asked[asked.index("--provider") + 1], "deepseek")
        self.assertEqual(asked[asked.index("--model") + 1], "Кот 9.0")

    def test_a_refusal_from_the_translator_is_passed_on(self):
        # В своей папке: подделка по умолчанию живёт в `self.tmp` и
        # перезаписала бы эту, а проверялся бы тогда не отказ.
        upset = self.tmp / "отказ"
        upset.mkdir()
        res = self.ask(path=str(fake_translator(
            upset, prints={"ok": False, "error": "нет ключей"})))
        self.assertEqual(res.status_code, 400)
        self.assertIn("нет ключей", res.get_json()["error"])


class TestTheLongWork(Base):
    """Перевод книги — это часы. Всё это время экран не должен быть немым,
    а кнопка «Остановить» — должна останавливать.
    """

    def setUp(self):
        super().setUp()
        self.book = self.tmp / "проба.epub"
        self.book.write_bytes(b"PK\x03\x04")

    def talkative(self, lines: int = 3, pause: str = "0") -> Path:
        """Переводчик, который пишет журнал и в конце отдаёт итог."""
        home = self.tmp / "болтун"
        package = home / "gemini_translator"
        package.mkdir(parents=True, exist_ok=True)
        (package / "cli.py").write_text(
            "import sys, json, time\n"
            f"for n in range({lines}):\n"
            "    print(f'глава {n+1} готова', file=sys.stderr, flush=True)\n"
            f"    time.sleep({pause})\n"
            "sys.stdout.write(json.dumps("
            "{'ok': True, 'translated': 2, 'сказали': sys.argv[1:]}))\n",
            encoding="utf-8")
        return home

    def asked(self, doing, **kw) -> list:
        """Чем позвали переводчика."""
        home = self.talkative()
        said = doing(str(self.book), str(self.tmp / "проект"),
                     path=str(home), **kw)
        return said["сказали"]

    def test_the_log_comes_out_line_by_line(self):
        """Иначе часы работы проходят при пустом экране."""
        seen = []
        translator.translate(str(self.book), str(self.tmp / "проект"),
                             path=str(self.talkative()), note=seen.append)
        self.assertEqual(seen, ["глава 1 готова", "глава 2 готова",
                                "глава 3 готова"])

    def test_stopping_does_not_wait_for_the_next_line(self):
        """Между строками у перевода бывают минуты: жди мы строку —
        «Остановить» доходило бы только вместе с ней."""
        import threading
        import time

        home = self.tmp / "молчун"
        package = home / "gemini_translator"
        package.mkdir(parents=True)
        (package / "cli.py").write_text(
            "import time\ntime.sleep(60)\n", encoding="utf-8")

        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        began = time.monotonic()
        # Отмена — не поломка: у неё свой тип, общий на весь проект, и
        # показывают её иначе, чем отказ переводчика.
        with self.assertRaises(Cancelled) as caught:
            translator.translate(str(self.book), str(self.tmp / "проект"),
                                 path=str(home), stop=stop)

        self.assertIn("Остановлено", str(caught.exception))
        # Меньше срока добивания: значит, процесс ушёл сам, по-хорошему, а
        # не был убит по истечении отсрочки. Убийство посреди главы теряет
        # её перевод — за него уже заплачено квотой.
        self.assertLess(time.monotonic() - began, translator.GRACE)

    def test_the_verbose_flag_goes_only_where_it_is_known(self):
        """`consistency` и `build-epub` его не знают и падают на нём."""
        self.assertIn("--verbose", self.asked(translator.translate))
        self.assertIn("--verbose", self.asked(translator.glossary))
        self.assertNotIn("--verbose", self.asked(translator.consistency))
        self.assertNotIn("--verbose", self.asked(translator.build_epub))

    def test_every_command_is_called_by_its_own_name(self):
        for doing, name in [(translator.translate, "translate"),
                            (translator.glossary, "glossary-generate"),
                            (translator.consistency, "consistency"),
                            (translator.build_epub, "build-epub")]:
            with self.subTest(name):
                self.assertEqual(self.asked(doing)[0], name)

    def test_the_keys_are_his_own(self):
        """Своего склада ключей для перевода у нас нет и не будет."""
        self.assertIn("--all-keys", self.asked(translator.translate))
        # Сборке ключи не нужны вовсе: она складывает уже готовое.
        self.assertNotIn("--all-keys", self.asked(translator.build_epub))

    def test_what_was_not_named_is_not_passed(self):
        """Пустая ручка отсюда затёрла бы его же настройку своим нулём."""
        asked = self.asked(translator.translate)

        for flag in ("--workers", "--rpm", "--temperature", "--prompt-file"):
            self.assertNotIn(flag, asked, flag)

    def test_what_was_named_reaches_the_translator(self):
        asked = self.asked(translator.translate, workers=3, rpm=5,
                           temperature=0.7)

        self.assertEqual(asked[asked.index("--workers") + 1], "3")
        self.assertEqual(asked[asked.index("--rpm") + 1], "5")
        self.assertEqual(asked[asked.index("--temperature") + 1], "0.7")

    def test_the_built_book_goes_where_it_was_told(self):
        asked = self.asked(translator.build_epub, output=str(self.tmp / "го.epub"))
        self.assertEqual(asked[asked.index("--output") + 1],
                         str(self.tmp / "го.epub"))

    def test_the_glossary_is_gathered_over_the_whole_book(self):
        """Имена должны совпадать от первой главы до последней."""
        asked = self.asked(translator.glossary)
        self.assertEqual(asked[asked.index("--chapters") + 1], translator.WHOLE)

    def test_the_check_looks_at_what_is_already_translated(self):
        asked = self.asked(translator.consistency)
        self.assertEqual(asked[asked.index("--chapters") + 1], translator.DONE)


class TestTheLongWorkOverHttp(Base):
    """Четыре долгие команды — задачей, как и всё долгое в программе.

    Отвечать на них сразу нельзя: перевод книги идёт часами, и страница
    столько не ждёт. Значит, ответ — номер задачи, а дальше опрос.
    """

    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()
        self.book = self.tmp / "проба.epub"
        self.book.write_bytes(b"PK\x03\x04")

    def home(self) -> str:
        """Переводчик, который пишет строку в журнал и отдаёт итог."""
        home = self.tmp / "болтун"
        package = home / "gemini_translator"
        package.mkdir(parents=True, exist_ok=True)
        (package / "cli.py").write_text(
            "import sys, json\n"
            "print('глава 1 готова', file=sys.stderr, flush=True)\n"
            "sys.stdout.write(json.dumps("
            "{'ok': True, 'сказали': sys.argv[1:]}))\n",
            encoding="utf-8")
        return str(home)

    def start(self, what: str, **kw):
        body = {"path": self.home(), "epub": str(self.book),
                "project": str(self.tmp / "проект")}
        body.update(kw)
        return self.app.post(f"/api/translator/{what}", json=body)

    def finished(self, what: str, **kw) -> dict:
        """Дождаться задачи и вернуть её последний снимок."""
        import time

        job = self.start(what, **kw).get_json()["job"]
        until = time.monotonic() + 30
        while time.monotonic() < until:
            got = self.app.get(f"/api/job/{job['id']}").get_json()["job"]
            if not got["running"]:
                return got
            time.sleep(0.05)
        self.fail(f"задача {what} не закончилась")

    def test_each_command_starts_a_job_and_calls_its_own_name(self):
        for what, name in [("translate", "translate"),
                           ("glossary", "glossary-generate"),
                           ("consistency", "consistency"),
                           ("build", "build-epub")]:
            with self.subTest(what):
                got = self.finished(what)
                self.assertIsNone(got["error"])
                self.assertEqual(got["report"]["сказали"][0], name)

    def test_the_log_of_the_translator_reaches_the_page(self):
        """Иначе полоса стоит на месте и непонятно, жива ли работа."""
        got = self.finished("translate")
        self.assertIn("глава 1 готова", got["progress"]["lines"])

    def test_a_missing_book_is_refused_before_a_job_is_made(self):
        """Задача, падающая сразу после запуска, — худший способ сказать
        «нет такого файла»: её ещё надо открыть, чтобы прочитать."""
        for what in ("translate", "glossary", "consistency", "build"):
            with self.subTest(what):
                res = self.start(what, epub=str(self.tmp / "нет.epub"))
                self.assertEqual(res.status_code, 400)
                self.assertIn("Файла нет", res.get_json()["error"])

    def test_the_knobs_from_the_page_reach_the_translator(self):
        said = self.finished("translate", workers=4, rpm=7)["report"]["сказали"]
        self.assertEqual(said[said.index("--workers") + 1], "4")
        self.assertEqual(said[said.index("--rpm") + 1], "7")

    def test_the_chapter_pick_reaches_the_translator_over_http(self):
        """Строка «0012, 0013» со страницы — два отдельных фильтра."""
        said = self.finished("translate", pick="0012, 0013",
                             limit=5)["report"]["сказали"]
        found = [said[i + 1] for i, one in enumerate(said)
                 if one == "--chapter"]

        self.assertEqual(found, ["0012", "0013"])
        self.assertEqual(said[said.index("--limit") + 1], "5")

    def test_the_build_takes_the_pick_too(self):
        said = self.finished("build", pick="0012")["report"]["сказали"]
        self.assertEqual(said[said.index("--chapter") + 1], "0012")

    def test_the_chosen_service_and_model_reach_the_translator(self):
        """Самое видное в его окне — и самое обидное было бы потерять."""
        said = self.finished("translate", provider="deepseek",
                             model="Кот 9.0")["report"]["сказали"]

        self.assertEqual(said[said.index("--provider") + 1], "deepseek")
        self.assertEqual(said[said.index("--model") + 1], "Кот 9.0")

    def test_stopping_a_job_is_told_apart_from_a_breakdown(self):
        """Остановка — не ошибка: человек нажал сам."""
        import time

        home = self.tmp / "молчун"
        (home / "gemini_translator").mkdir(parents=True)
        (home / "gemini_translator" / "cli.py").write_text(
            "import time\ntime.sleep(60)\n", encoding="utf-8")

        job = self.start("translate", path=str(home)).get_json()["job"]
        self.app.post(f"/api/job/{job['id']}/cancel")

        until = time.monotonic() + 30
        while time.monotonic() < until:
            got = self.app.get(f"/api/job/{job['id']}").get_json()["job"]
            if not got["running"]:
                break
            time.sleep(0.05)
        self.assertFalse(got["running"], "остановка не дошла")
        self.assertIsNone(got["error"], "остановка показана поломкой")
        self.assertEqual(got["progress"]["stage"], "cancelled")
        self.assertIn("станов", got["progress"]["message"].lower())

    def test_a_long_log_does_not_grow_without_end(self):
        """Перевод пишет строки тысячами, а смотрят всегда в конец."""
        home = self.tmp / "многослов"
        (home / "gemini_translator").mkdir(parents=True)
        (home / "gemini_translator" / "cli.py").write_text(
            "import sys, json\n"
            "for n in range(400):\n"
            "    print(f'строка {n}', file=sys.stderr, flush=True)\n"
            "sys.stdout.write(json.dumps({'ok': True}))\n",
            encoding="utf-8")

        rows = self.finished("translate", path=str(home))["progress"]["lines"]
        self.assertLessEqual(len(rows), 200)
        self.assertEqual(rows[-1], "строка 399")

    def test_the_current_line_is_shown_while_the_work_goes_on(self):
        """Строка журнала — и есть весь наш прогресс.

        Сколько глав впереди, переводчик по ходу не сообщает, так что
        полоса стоит на месте, а живой её делает только эта надпись.
        """
        import time

        home = self.tmp / "неспешный"
        (home / "gemini_translator").mkdir(parents=True)
        (home / "gemini_translator" / "cli.py").write_text(
            "import sys, time\n"
            "print('глава 1 готова', file=sys.stderr, flush=True)\n"
            "time.sleep(60)\n", encoding="utf-8")

        job = self.start("translate", path=str(home)).get_json()["job"]
        try:
            until = time.monotonic() + 20
            while time.monotonic() < until:
                got = self.app.get(f"/api/job/{job['id']}").get_json()["job"]
                if "глава 1 готова" in got["progress"]["message"]:
                    return
                time.sleep(0.05)
            self.fail(f"на экране осталось: {got['progress']['message']!r}")
        finally:
            self.app.post(f"/api/job/{job['id']}/cancel")

    def test_a_refusal_after_hours_of_work_is_not_called_done(self):
        """Отказ он сообщает полем в ответе, а не кодом возврата."""
        home = self.tmp / "отказ"
        (home / "gemini_translator").mkdir(parents=True)
        (home / "gemini_translator" / "cli.py").write_text(
            "import sys, json\n"
            "sys.stdout.write(json.dumps("
            "{'ok': False, 'error': 'кончились ключи'}))\n",
            encoding="utf-8")

        got = self.finished("translate", path=str(home))
        self.assertIn("кончились ключи", got["error"])
        self.assertNotIn("Готово", got["progress"]["message"])


#: Ответы `providers` и `models` в том виде, в каком их печатает сам
#: переводчик. Сняты с его `cli.py`, а не выдуманы: разойдись форма — и
#: списки в карточке молча опустели бы.
PROVIDERS = {
    "ok": True,
    "providers": [
        {"id": "gemini", "display_name": "Google Gemini Free", "visible": True,
         "requires_api_key": True, "configured_keys": 69, "model_count": 12,
         "file_suffix": "_gemini.html", "browser_based": False,
         "dynamic_model_discovery": False, "discovery_checked": False},
        {"id": "local", "display_name": "Локальная модель", "visible": True,
         "requires_api_key": False, "configured_keys": 0, "model_count": 2,
         "file_suffix": None, "browser_based": True,
         "dynamic_model_discovery": True, "discovery_checked": False},
    ],
    "diagnose": False,
}

MODELS = {
    "ok": True,
    "provider": "gemini",
    "saved_model": "Gemini 3.0 Flash Preview",
    "models": [
        {"name": "Gemini 3.0 Flash Preview", "id": "gemini-3.0-flash",
         "provider": "gemini", "rpm": 5, "rpd": 20,
         "max_output_tokens": 8192, "context_window": 1048576,
         "supports_thinking": True},
        {"name": "Gemini 2.5 Pro", "id": "gemini-2.5-pro", "provider": "gemini",
         "rpm": 2, "rpd": 50, "max_output_tokens": 8192,
         "context_window": 2097152, "supports_thinking": False},
    ],
}


class TestTheServiceAndTheModel(Base):
    """Сервис и модель — самое видное в его окне, и списки у них его.

    Свой перечень провайдеров разошёлся бы с его настройками в первый же
    раз, когда он добавит себе сервис. Поэтому спрашиваем каждый раз.
    """

    def setUp(self):
        super().setUp()
        self.book = self.tmp / "проба.epub"
        self.book.write_bytes(b"PK\x03\x04")

    def echoing(self, name: str) -> str:
        """Переводчик, который печатает, о чём его попросили."""
        home = self.tmp / name
        package = home / "gemini_translator"
        package.mkdir(parents=True, exist_ok=True)
        (package / "cli.py").write_text(
            "import json, sys\n"
            "print(json.dumps({'ok': True, 'сказали': sys.argv[1:]}))\n",
            encoding="utf-8")
        return str(home)

    def test_the_services_are_read_the_way_he_prints_them(self):
        rows = translator.short_providers(PROVIDERS)

        self.assertEqual(rows[0]["name"], "Google Gemini Free")
        self.assertEqual(rows[0]["keys"], 69)
        self.assertEqual(rows[0]["models"], 12)

    def test_a_browser_service_is_told_apart_from_one_without_keys(self):
        """«Ключей 0» у браузерного — норма, а не беда: ключ ему не нужен."""
        rows = translator.short_providers(PROVIDERS)

        self.assertTrue(rows[1]["browser"])
        self.assertFalse(rows[1]["needs_key"])
        self.assertFalse(rows[0]["browser"])

    def test_the_models_come_with_their_quota(self):
        """Ради квоты модель и выбирают: хватит ли её на книгу разом."""
        got = translator.short_models(MODELS)

        self.assertEqual(got["models"][0]["name"], "Gemini 3.0 Flash Preview")
        self.assertEqual((got["models"][0]["rpm"], got["models"][0]["rpd"]),
                         (5, 20))
        # С какой открывать список: с той, что выбрана у него самого.
        self.assertEqual(got["saved"], "Gemini 3.0 Flash Preview")

    def test_a_changed_format_empties_the_list_but_does_not_break_us(self):
        self.assertEqual(translator.short_providers({"ok": True}), [])
        self.assertEqual(translator.short_models({"ok": True})["models"], [])

    def test_the_service_is_asked_by_its_own_command(self):
        said = translator.providers(self.echoing("сервисы"))
        self.assertEqual(said["сказали"][0], "providers")

    def test_the_models_are_asked_for_the_chosen_service(self):
        asked = translator.models("deepseek", self.echoing("модели"))["сказали"]

        self.assertEqual(asked[0], "models")
        self.assertEqual(asked[asked.index("--provider") + 1], "deepseek")

    def test_no_service_named_means_his_own_saved_one(self):
        """Пустой `--provider` отсюда спросил бы не про то."""
        asked = translator.models("", self.echoing("сами"))["сказали"]
        self.assertNotIn("--provider", asked)

    def test_a_refusal_is_explained_not_swallowed(self):
        home = self.tmp / "отказ"
        home.mkdir()
        fake_translator(home, prints={"ok": False, "error": "нет настроек"})

        with self.assertRaises(translator.TranslatorError) as caught:
            translator.providers(str(home))
        self.assertIn("нет настроек", str(caught.exception))

    def test_the_chosen_service_and_model_reach_every_command(self):
        home = self.echoing("работа")
        for doing in (translator.plan, translator.translate,
                      translator.glossary, translator.consistency):
            with self.subTest(doing.__name__):
                asked = doing(str(self.book), str(self.tmp / "проект"),
                              path=home, provider="deepseek",
                              model="Кот 9.0")["сказали"]
                self.assertEqual(asked[asked.index("--provider") + 1],
                                 "deepseek")
                self.assertEqual(asked[asked.index("--model") + 1], "Кот 9.0")

    def test_what_was_not_chosen_leaves_his_settings_alone(self):
        """Пустой сервис отсюда затёр бы его же выбор пустотой."""
        asked = translator.translate(str(self.book), str(self.tmp / "проект"),
                                     path=self.echoing("пусто"))["сказали"]

        self.assertNotIn("--provider", asked)
        self.assertNotIn("--model", asked)


class TestTheListsOverHttp(Base):
    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()

    def test_the_services_reach_the_page(self):
        home = fake_translator(self.tmp, prints=PROVIDERS)
        got = self.app.post("/api/translator/providers",
                            json={"path": str(home)}).get_json()

        self.assertEqual(got["providers"][0]["name"], "Google Gemini Free")
        self.assertEqual(got["providers"][0]["keys"], 69)

    def test_the_models_reach_the_page_with_the_saved_one_marked(self):
        home = fake_translator(self.tmp, prints=MODELS)
        got = self.app.post("/api/translator/models",
                            json={"path": str(home)}).get_json()

        self.assertEqual(got["saved"], "Gemini 3.0 Flash Preview")
        self.assertEqual(got["models"][1]["rpd"], 50)

    def test_a_broken_translator_answers_with_words(self):
        for what in ("providers", "models"):
            with self.subTest(what):
                res = self.app.post(f"/api/translator/{what}",
                                    json={"path": str(self.tmp / "нет")})
                self.assertEqual(res.status_code, 400)
                self.assertIn("Папки нет", res.get_json()["error"])


class TestPickingWhichChapters(Base):
    """Отбор поверх «все / непереведённые / переведённые».

    Нужен затем же, зачем и план: взять десяток глав на пробу, а не книгу
    целиком. Ошибка тут стоит квоты ключей, а не времени.
    """

    def setUp(self):
        super().setUp()
        self.book = self.tmp / "проба.epub"
        self.book.write_bytes(b"PK\x03\x04")
        self.home = self.tmp / "эхо"
        package = self.home / "gemini_translator"
        package.mkdir(parents=True)
        (package / "cli.py").write_text(
            "import json, sys\n"
            "print(json.dumps({'ok': True, 'сказали': sys.argv[1:]}))\n",
            encoding="utf-8")

    def asked(self, doing=None, **kw) -> list:
        doing = doing or translator.translate
        return doing(str(self.book), str(self.tmp / "проект"),
                     path=str(self.home), **kw)["сказали"]

    def test_each_chapter_gets_its_own_flag(self):
        """Одной строкой «0012,0013» вышел бы фильтр, не совпадающий ни с
        чем: флаг у переводчика повторяемый."""
        asked = self.asked(pick="0012, 0013")
        found = [asked[i + 1] for i, one in enumerate(asked)
                 if one == "--chapter"]

        self.assertEqual(found, ["0012", "0013"])

    def test_the_separators_people_actually_use_all_work(self):
        """Гадать, какой из них «правильный», незачем."""
        asked = self.asked(pick="а; б\nв,г")
        found = [asked[i + 1] for i, one in enumerate(asked)
                 if one == "--chapter"]

        self.assertEqual(found, ["а", "б", "в", "г"])

    def test_a_trailing_comma_does_not_become_a_match_all_filter(self):
        """Пустой `--chapter` переводчик понял бы как «совпадает со всем»
        — то есть тихо взял бы книгу целиком."""
        asked = self.asked(pick="0012, ,")
        found = [asked[i + 1] for i, one in enumerate(asked)
                 if one == "--chapter"]

        self.assertEqual(found, ["0012"])

    def test_a_ready_list_works_the_same_as_a_typed_line(self):
        self.assertEqual(self.asked(pick=["а", "б"]),
                         self.asked(pick="а, б"))

    def test_nothing_picked_means_no_filter_at_all(self):
        self.assertNotIn("--chapter", self.asked())
        self.assertNotIn("--chapter", self.asked(pick="  "))

    def test_the_limit_and_the_offset_reach_the_translator(self):
        asked = self.asked(offset=30, limit=10)

        self.assertEqual(asked[asked.index("--offset") + 1], "30")
        self.assertEqual(asked[asked.index("--limit") + 1], "10")

    def test_the_build_takes_the_same_pick_without_a_scope(self):
        """Собрать половину книги нужно, когда вторая ещё переводится.

        Сервиса, модели и `--chapters` у сборки нет вовсе — она их не
        знает и на них падает.
        """
        asked = self.asked(translator.build_epub, pick="0012", limit=5)

        self.assertEqual(asked[asked.index("--chapter") + 1], "0012")
        self.assertEqual(asked[asked.index("--limit") + 1], "5")
        self.assertNotIn("--chapters", asked)
        self.assertNotIn("--provider", asked)

    def test_the_plan_is_asked_about_the_same_chapters(self):
        """План про десять глав и план про книгу — разные ответы."""
        asked = self.asked(translator.plan, pick="0012", limit=10)

        self.assertEqual(asked[asked.index("--chapter") + 1], "0012")
        self.assertEqual(asked[asked.index("--limit") + 1], "10")


#: Ответ `untranslated-scan` в том виде, в каком его печатает переводчик.
SCAN = {
    "ok": True,
    "epub": "/книга.epub",
    "project": "/проект",
    "checked_chapters": 120,
    "missing_translations": ["0119.xhtml", "0120.xhtml"],
    "problem_chapters": 2,
    "problem_count": 5,
    "issues": [
        {"chapter": "Глава 12", "file": "0012_gemini.html",
         "untranslated_words": ["修炼", "灵气"], "mixed_script": [],
         "problem_count": 2},
        {"chapter": "Глава 40", "file": "0040_gemini.html",
         "untranslated_words": ["境界"], "mixed_script": ["Линьчжэнь法"],
         "problem_count": 3},
    ],
}


class TestTheUntranslatedLeftovers(Base):
    """Остатки — беда отдельная от сверки.

    Там расходятся имена и смысл, а тут прямо в готовом переводе остались
    чужие слова: модель пропустила кусок. Ищется без ключей, чинится с
    ключами, и путать одно с другим дорого.
    """

    def setUp(self):
        super().setUp()
        self.book = self.tmp / "проба.epub"
        self.book.write_bytes(b"PK\x03\x04")
        self.home = self.tmp / "эхо"
        package = self.home / "gemini_translator"
        package.mkdir(parents=True)
        (package / "cli.py").write_text(
            "import json, sys\n"
            "print(json.dumps({'ok': True, 'сказали': sys.argv[1:]}))\n",
            encoding="utf-8")

    def asked(self, doing, **kw) -> list:
        return doing(str(self.book), str(self.tmp / "проект"),
                     path=str(self.home), **kw)["сказали"]

    def test_the_search_looks_at_translated_chapters_by_default(self):
        """Искать остатки там, где перевода ещё нет, нечего."""
        asked = self.asked(translator.scan_untranslated)

        self.assertEqual(asked[0], "untranslated-scan")
        self.assertEqual(asked[asked.index("--chapters") + 1], translator.DONE)

    def test_the_search_is_not_given_the_flags_it_does_not_know(self):
        """Ни сервиса, ни модели, ни ключей: в сеть оно не ходит вовсе, а
        на незнакомом флаге команда падает."""
        asked = self.asked(translator.scan_untranslated)

        for flag in ("--provider", "--model", "--all-keys", "--workers",
                     "--verbose", "--temperature"):
            self.assertNotIn(flag, asked, flag)

    def test_the_mixed_words_are_asked_by_a_straight_question(self):
        """У переводчика флаг обратный — выключающий. Спрашиваем прямо."""
        self.assertNotIn("--no-mixed-script",
                         self.asked(translator.scan_untranslated, mixed=True))
        self.assertIn("--no-mixed-script",
                      self.asked(translator.scan_untranslated, mixed=False))

    def test_the_search_takes_the_same_chapter_pick(self):
        asked = self.asked(translator.scan_untranslated, pick="0012", limit=5)

        self.assertEqual(asked[asked.index("--chapter") + 1], "0012")
        self.assertEqual(asked[asked.index("--limit") + 1], "5")

    def test_the_findings_are_read_with_the_words_themselves(self):
        """По словам и видно, находка это или в главе просто имя латиницей."""
        got = translator.short_scan(SCAN)

        self.assertEqual(got["checked"], 120)
        self.assertEqual(got["found"], 5)
        self.assertIn("修炼", got["rows"][1]["words"])
        self.assertIn("Линьчжэнь法", got["rows"][0]["mixed"])

    def test_the_worst_chapters_come_first(self):
        """На книге в пятьсот глав список читают сверху и до скуки."""
        got = translator.short_scan(SCAN)
        self.assertEqual([row["count"] for row in got["rows"]], [3, 2])

    def test_a_chapter_without_a_translation_is_not_a_leftover(self):
        """Это пропуск, и лечится он переводом, а не починкой."""
        got = translator.short_scan(SCAN)

        self.assertEqual(got["missing"], ["0119.xhtml", "0120.xhtml"])
        self.assertNotIn("0119.xhtml",
                         [row["chapter"] for row in got["rows"]])

    def test_a_changed_format_does_not_break_the_findings(self):
        got = translator.short_scan({"ok": True, "иное": 1})
        self.assertEqual(got["rows"], [])
        self.assertEqual(got["found"], 0)

    def test_the_repair_asks_for_keys_and_a_log(self):
        """Починка — уже работа с моделью, в отличие от поиска."""
        asked = self.asked(translator.fix_untranslated)

        self.assertEqual(asked[0], "untranslated-fix")
        self.assertIn("--all-keys", asked)
        self.assertIn("--verbose", asked)

    def test_the_dry_run_is_the_only_guard_over_finished_chapters(self):
        """Перезапись готовых глав необратима, и за неё уже заплачено."""
        self.assertIn("--dry-run",
                      self.asked(translator.fix_untranslated, dry=True))
        self.assertNotIn("--dry-run",
                         self.asked(translator.fix_untranslated))

    def test_the_repair_knobs_reach_the_translator(self):
        asked = self.asked(translator.fix_untranslated, batch=20, context=900,
                           suffix="_validated.html")

        self.assertEqual(asked[asked.index("--batch-size") + 1], "20")
        self.assertEqual(asked[asked.index("--max-context-chars") + 1], "900")
        self.assertEqual(asked[asked.index("--suffix") + 1], "_validated.html")

    def test_unnamed_repair_knobs_keep_his_own_defaults(self):
        asked = self.asked(translator.fix_untranslated)

        for flag in ("--batch-size", "--max-context-chars", "--suffix",
                     "--exceptions", "--fix-prompt-file"):
            self.assertNotIn(flag, asked, flag)


class TestTheLeftoversOverHttp(Base):
    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()
        self.book = self.tmp / "проба.epub"
        self.book.write_bytes(b"PK\x03\x04")

    def test_the_findings_reach_the_page(self):
        home = fake_translator(self.tmp, prints=SCAN)
        got = self.app.post("/api/translator/scan", json={
            "path": str(home), "epub": str(self.book),
            "project": str(self.tmp / "проект")}).get_json()

        self.assertEqual(got["found"], 5)
        self.assertEqual(len(got["rows"]), 2)
        self.assertEqual(got["missing"], ["0119.xhtml", "0120.xhtml"])

    def test_the_mixed_words_question_reaches_the_translator(self):
        """Флаг у него обратный, и потерять эту галку значит молча искать
        не то, о чём попросили.

        Находки мы показываем разобранными, аргументов в них не видно.
        Поэтому поддельный переводчик кладёт их туда, где список глав без
        перевода, — единственное окно, через которое их отсюда видно.
        """
        home = self.tmp / "эхо-скан"
        (home / "gemini_translator").mkdir(parents=True)
        (home / "gemini_translator" / "cli.py").write_text(
            "import json, sys\n"
            "print(json.dumps({'ok': True, "
            "'missing_translations': [x for x in sys.argv[1:]"
            " if x.startswith('--no-')]}))\n", encoding="utf-8")

        def ask(**kw):
            body = {"path": str(home), "epub": str(self.book),
                    "project": str(self.tmp / "проект")}
            body.update(kw)
            return self.app.post("/api/translator/scan",
                                 json=body).get_json()["missing"]

        self.assertEqual(ask(mixed=False), ["--no-mixed-script"])
        self.assertEqual(ask(mixed=True), [])
        # Не спросили вовсе — ищем и смешанные: так у него по умолчанию.
        self.assertEqual(ask(), [])

    def test_a_missing_book_is_refused_at_once(self):
        home = fake_translator(self.tmp, prints=SCAN)
        for what in ("scan", "fix"):
            with self.subTest(what):
                res = self.app.post(f"/api/translator/{what}", json={
                    "path": str(home), "epub": str(self.tmp / "нет.epub"),
                    "project": str(self.tmp / "проект")})
                self.assertEqual(res.status_code, 400)
                self.assertIn("Файла нет", res.get_json()["error"])

    def test_the_repair_is_a_job_and_guards_finished_chapters(self):
        import time

        home = self.tmp / "болтун"
        (home / "gemini_translator").mkdir(parents=True)
        (home / "gemini_translator" / "cli.py").write_text(
            "import json, sys\n"
            "sys.stdout.write(json.dumps("
            "{'ok': True, 'сказали': sys.argv[1:]}))\n", encoding="utf-8")

        job = self.app.post("/api/translator/fix", json={
            "path": str(home), "epub": str(self.book),
            "project": str(self.tmp / "проект"),
            "dry": True}).get_json()["job"]

        until = time.monotonic() + 30
        while time.monotonic() < until:
            got = self.app.get(f"/api/job/{job['id']}").get_json()["job"]
            if not got["running"]:
                break
            time.sleep(0.05)

        said = got["report"]["сказали"]
        self.assertEqual(said[0], "untranslated-fix")
        self.assertIn("--dry-run", said)
