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
