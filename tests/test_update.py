"""Обновление программы: забираем только изменившиеся файлы.

Трафик у человека на счету, поэтому проверяется в первую очередь не то,
что файлы скачиваются, а то, что лишнего не качается и лишнее не
перезаписывается: настройки с ключом, список прокси с паролями и всё
нажитое принадлежат человеку, а не репозиторию.

GitHub здесь поддельный — настоящий из этой среды недоступен, да и
проверять надо наш разбор, а не чужой сервер.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import update  # noqa: E402

OLD = "a" * 40
NEW = "b" * 40


class FakeAnswer:
    def __init__(self, body=None, raw=b""):
        self._body = body
        self.content = raw

    def json(self):
        return self._body


class FakeHub:
    """Отвечает как GitHub и считает, о чём его спросили."""

    def __init__(self, head=NEW, files=None, blobs=None):
        self.head = head
        self.files = files if files is not None else []
        self.blobs = blobs or {}
        self.asked: list[str] = []

    def get(self, url, params=None, headers=None):
        self.asked.append(url)
        if "/git/ref/heads/" in url:
            return FakeAnswer({"object": {"sha": self.head}})
        if "/compare/" in url:
            return FakeAnswer({"files": self.files})
        name = url.rsplit("/", 1)[-1]
        for path, body in self.blobs.items():
            if url.endswith(path):
                return FakeAnswer(raw=body)
        return FakeAnswer(raw=f"тело {name}".encode("utf-8"))

    def close(self):
        pass


def change(path, status="modified", lines=3):
    return {"filename": path, "status": status, "changes": lines}


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

        # Свой корень и своя память о версии: прогон не должен ни
        # переписывать саму программу, ни трогать настоящие данные.
        self._was = (update.ROOT, update.REVISION_FILE)
        update.ROOT = self.tmp / "программа"
        update.ROOT.mkdir()
        update.REVISION_FILE = self.tmp / "revision.json"
        self.addCleanup(self._restore)

    def _restore(self):
        update.ROOT, update.REVISION_FILE = self._was


class TestWhatItRefusesToTouch(unittest.TestCase):
    """Настройки с ключом, пароли и нажитое — не наше дело."""

    def test_settings_and_proxies_are_never_touched(self):
        self.assertFalse(update.mine("config.json"))
        self.assertFalse(update.mine("proxies.txt"))

    def test_what_the_person_made_is_never_touched(self):
        for path in ("data/history.json", "data/logs/neurostrazh.log",
                     "outputs/книга/Глава 1.txt", ".git/config"):
            with self.subTest(path):
                self.assertFalse(update.mine(path))

    def test_a_path_that_climbs_out_is_refused(self):
        """`../` в имени — это запись мимо папки программы."""
        self.assertFalse(update.mine("../секрет"))
        self.assertFalse(update.mine("ops/../../секрет"))

    def test_the_program_itself_is_ours(self):
        self.assertTrue(update.mine("ops/split.py"))
        self.assertTrue(update.mine("webapp/static/tabs.js"))


class TestTheCheckIsCheap(Base):
    def test_the_first_run_just_remembers_where_we_are(self):
        """Качать весь репозиторий ради сверки — ровно тот трафик,
        который мы и бережём."""
        hub = FakeHub()
        seen = update.look(hub)

        self.assertTrue(seen.fresh)
        self.assertEqual(update.current(), NEW)
        # Сравнения не было: спрашивали только адрес ветки.
        self.assertFalse([one for one in hub.asked if "/compare/" in one])

    def test_nothing_new_costs_one_question(self):
        update.remember(NEW)
        hub = FakeHub(head=NEW)
        seen = update.look(hub)

        self.assertTrue(seen.fresh)
        self.assertEqual(len(hub.asked), 1)

    def test_something_new_lists_the_files(self):
        update.remember(OLD)
        hub = FakeHub(files=[change("ops/split.py"), change("README.md")])
        seen = update.look(hub)

        self.assertFalse(seen.fresh)
        self.assertEqual([one.path for one in seen.changes],
                         ["ops/split.py", "README.md"])

    def test_it_says_lines_not_bytes(self):
        """Веса файла сравнение не отдаёт вовсе, и выдавать одно за
        другое нельзя: человек считает по этому числу трафик."""
        update.remember(OLD)
        hub = FakeHub(files=[change("ops/split.py", lines=12)])
        said = update.look(hub).as_dict()

        self.assertEqual(said["lines"], 12)
        self.assertNotIn("bytes", said)

    def test_settings_are_dropped_from_the_list(self):
        """Даже если в самом репозитории они менялись."""
        update.remember(OLD)
        hub = FakeHub(files=[change("config.json"), change("ops/split.py")])
        seen = update.look(hub)
        self.assertEqual([one.path for one in seen.changes], ["ops/split.py"])

    def test_a_whole_new_copy_is_refused_out_loud(self):
        """Молча перекачать всё по дорогому трафику — худшее решение."""
        update.remember(OLD)
        hub = FakeHub(files=[change(f"файл{n}.py")
                             for n in range(update.TOO_MANY + 1)])
        seen = update.look(hub)

        self.assertTrue(seen.trouble)
        self.assertIn("целиком", seen.trouble)

    def test_a_vanished_commit_is_explained_not_hidden(self):
        """После переписанной истории нашего коммита в репозитории нет."""
        update.remember(OLD)
        hub = FakeHub(files=None)
        hub.files = None
        seen = update.look(hub)
        self.assertIn("больше нет", seen.trouble)


class TestTheDownload(Base):
    def plan(self, *rows):
        update.remember(OLD)
        return update.look(FakeHub(files=list(rows)))

    def test_a_file_lands_where_it_belongs(self):
        hub = FakeHub(files=[change("ops/split.py")],
                      blobs={"ops/split.py": b"# svezhy"})
        done = update.apply(hub, self.plan(change("ops/split.py")))

        self.assertEqual(done.written, 1)
        self.assertEqual((update.ROOT / "ops" / "split.py").read_bytes(),
                         b"# svezhy")

    def test_a_removed_file_goes_away(self):
        (update.ROOT / "старое.py").write_text("было", encoding="utf-8")
        hub = FakeHub(files=[change("старое.py", status="removed")])
        done = update.apply(hub, self.plan(change("старое.py", status="removed")))

        self.assertEqual(done.removed, 1)
        self.assertFalse((update.ROOT / "старое.py").exists())

    def test_a_broken_download_leaves_the_old_file_alone(self):
        """Оборвалась связь — старый файл должен остаться целым, иначе
        программа перестанет запускаться."""
        target = update.ROOT / "ops" / "split.py"
        target.parent.mkdir(parents=True)
        target.write_text("старое, но рабочее", encoding="utf-8")

        class Broken(FakeHub):
            def get(inner, url, params=None, headers=None):
                if "raw" in url:
                    raise OSError("связь оборвалась")
                return super().get(url, params, headers)

        done = update.apply(Broken(files=[change("ops/split.py")]),
                            self.plan(change("ops/split.py")))

        self.assertTrue(done.failures)
        self.assertEqual(target.read_text(encoding="utf-8"), "старое, но рабочее")
        self.assertEqual(list(target.parent.glob("*.new")), [])

    def test_the_file_appears_whole_or_not_at_all(self):
        """Половина нового файла поверх старого — сломанная программа.

        Поэтому тело сперва целиком ложится рядом и только потом
        переезжает на место. Проверяем сам этот порядок: в тот миг,
        когда происходит переезд, на месте ещё старое, а рядом уже
        целиком новое.
        """
        target = update.ROOT / "ops" / "split.py"
        target.parent.mkdir(parents=True)
        target.write_text("старое", encoding="utf-8")

        seen = {}
        real = update.os.replace

        def watch(spare, where):
            seen["рядом"] = Path(spare).read_bytes()
            seen["на месте"] = Path(where).read_bytes()
            return real(spare, where)

        update.os.replace = watch
        self.addCleanup(setattr, update.os, "replace", real)

        update.apply(FakeHub(files=[change("ops/split.py")],
                             blobs={"ops/split.py": "новое целиком".encode("utf-8")}),
                     self.plan(change("ops/split.py")))

        self.assertEqual(seen["рядом"], "новое целиком".encode("utf-8"))
        self.assertEqual(seen["на месте"], "старое".encode("utf-8"))

    def test_a_failure_does_not_move_the_mark(self):
        """Запомни мы версию при половине легших файлов — следующая
        проверка сказала бы «всё свежее», а половина осталась старой."""
        class Broken(FakeHub):
            def get(inner, url, params=None, headers=None):
                if "raw" in url:
                    raise OSError("связь оборвалась")
                return super().get(url, params, headers)

        update.apply(Broken(files=[change("ops/split.py")]),
                     self.plan(change("ops/split.py")))
        self.assertEqual(update.current(), OLD)

    def test_a_clean_run_moves_the_mark(self):
        update.apply(FakeHub(files=[change("ops/split.py")]),
                     self.plan(change("ops/split.py")))
        self.assertEqual(update.current(), NEW)


class TestOverHttp(Base):
    def setUp(self):
        super().setUp()
        from webapp import app as web

        web.app.config["TESTING"] = True
        self.app = web.app.test_client()
        self.web = web

    def test_there_is_nothing_to_update_is_a_plain_answer(self):
        """Не поломка, а «всё уже стоит»."""
        update.remember(NEW)
        held = self.web.Client
        self.web.Client = lambda *a, **k: FakeHub(head=NEW)
        self.addCleanup(setattr, self.web, "Client", held)

        res = self.app.post("/api/update/apply")
        self.assertEqual(res.status_code, 400)
        self.assertIn("последняя версия", res.get_json()["error"])

    def test_the_check_says_where_it_looks(self):
        """Репозиторий, из которого качают, и тот, в котором пишут, —
        не обязательно один и тот же."""
        held = self.web.Client
        self.web.Client = lambda *a, **k: FakeHub()
        self.addCleanup(setattr, self.web, "Client", held)

        got = self.app.get("/api/update/look").get_json()
        self.assertIn("@", got["where"])


class TestTheCopyCanBePutBack(Base):
    """Копия перед обновлением должна помнить, откуда каждый файл.

    Плоская копия по именам теряла бы `ops/base.py` под `core/base.py` — и
    вернуть её на место было бы нечем.
    """

    def setUp(self):
        super().setUp()
        from ops import history
        self.history = history
        self._bak = (history.DATA_DIR, history.HISTORY_FILE, history.BACKUP_DIR)
        history.DATA_DIR = self.tmp / "data"
        history.HISTORY_FILE = history.DATA_DIR / "history.json"
        history.BACKUP_DIR = history.DATA_DIR / "backup"
        self.addCleanup(self._back)

        for name in ("ops/base.py", "core/base.py"):
            path = update.ROOT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"старый {name}", encoding="utf-8")

    def _back(self):
        (self.history.DATA_DIR, self.history.HISTORY_FILE,
         self.history.BACKUP_DIR) = self._bak

    def plan(self):
        hub = FakeHub(files=[change("ops/base.py"), change("core/base.py")],
                      blobs={"ops/base.py": b"new ops",
                             "core/base.py": b"new core"})
        update.remember(OLD)
        return hub, update.look(hub)

    def test_two_files_with_one_name_both_survive_in_the_copy(self):
        hub, plan = self.plan()
        done = update.apply(hub, plan)
        kept = Path(done.backup)
        self.assertEqual((kept / "ops" / "base.py").read_text(encoding="utf-8"),
                         "старый ops/base.py")
        self.assertEqual((kept / "core" / "base.py").read_text(encoding="utf-8"),
                         "старый core/base.py")

    def test_going_back_puts_every_file_where_it_was(self):
        hub, plan = self.plan()
        done = update.apply(hub, plan)
        self.assertEqual(
            (update.ROOT / "ops" / "base.py").read_bytes(), b"new ops")

        self.assertEqual(update.undo(done.backup), 2)
        self.assertEqual(
            (update.ROOT / "ops" / "base.py").read_text(encoding="utf-8"),
            "старый ops/base.py")
        self.assertEqual(
            (update.ROOT / "core" / "base.py").read_text(encoding="utf-8"),
            "старый core/base.py")

    def test_the_copy_is_findable_afterwards(self):
        hub, plan = self.plan()
        update.apply(hub, plan)
        self.assertTrue(update.last_backup())


class TestAnUpdateThatDoesNotStart(Base):
    """Обновление, после которого программа не запускается, хуже
    отсутствия обновления."""

    def setUp(self):
        super().setUp()
        from ops import history
        self.history = history
        self._bak = (history.DATA_DIR, history.HISTORY_FILE, history.BACKUP_DIR)
        history.DATA_DIR = self.tmp / "data"
        history.HISTORY_FILE = history.DATA_DIR / "history.json"
        history.BACKUP_DIR = history.DATA_DIR / "backup"
        self.addCleanup(self._back)

        path = update.ROOT / "ops" / "split.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("рабочий", encoding="utf-8")

    def _back(self):
        (self.history.DATA_DIR, self.history.HISTORY_FILE,
         self.history.BACKUP_DIR) = self._bak

    def broken(self):
        """Пробный запуск, который говорит, что программа сломана."""
        held = update.works
        update.works = lambda: "ImportError: нет такого модуля"
        self.addCleanup(setattr, update, "works", held)

    def test_the_old_files_come_back(self):
        self.broken()
        hub = FakeHub(files=[change("ops/split.py")],
                      blobs={"ops/split.py": b"broken"})
        update.remember(OLD)
        done = update.apply(hub, update.look(hub))

        self.assertTrue(done.rolled_back)
        self.assertEqual(
            (update.ROOT / "ops" / "split.py").read_text(encoding="utf-8"),
            "рабочий")

    def test_the_version_is_not_remembered_after_a_rollback(self):
        """Иначе следующая проверка сказала бы «стоит последняя»."""
        self.broken()
        hub = FakeHub(files=[change("ops/split.py")])
        update.remember(OLD)
        update.apply(hub, update.look(hub))
        self.assertEqual(update.current(), OLD)

    def test_a_working_update_stays(self):
        hub = FakeHub(files=[change("ops/split.py")],
                      blobs={"ops/split.py": "хороший".encode("utf-8")})
        update.remember(OLD)
        done = update.apply(hub, update.look(hub))
        self.assertFalse(done.rolled_back)
        self.assertEqual(
            (update.ROOT / "ops" / "split.py").read_text(encoding="utf-8"),
            "хороший")

    def test_the_check_is_skipped_where_there_is_no_program(self):
        """Свой пустой корень — проверять нечего, но и мешать нельзя."""
        self.assertEqual(update.works(), "")


class TestWhatIsNew(Base):
    """«Обновлено 12 файлов» не говорит ничего, а весь CHANGELOG — это
    полторы тысячи строк."""

    def test_only_the_new_headings_are_taken(self):
        was = "# История\n\n### Первое\n текст\n"
        now = "# История\n\n### Второе\n текст\n### Первое\n текст\n"
        self.assertEqual(update.news_of(was, now), ["Второе"])

    def test_nothing_new_is_an_empty_list(self):
        same = "### Одно\n"
        self.assertEqual(update.news_of(same, same), [])

    def test_the_update_reports_what_appeared(self):
        (update.ROOT / update.CHANGELOG).write_text("### Старое\n",
                                                    encoding="utf-8")
        hub = FakeHub(files=[change(update.CHANGELOG)],
                      blobs={update.CHANGELOG:
                             "### Новое\n### Старое\n".encode("utf-8")})
        update.remember(OLD)
        done = update.apply(hub, update.look(hub), check=False)
        self.assertEqual(done.news, ["Новое"])


class TestNewDependencies(Base):
    """Обновление приносит файлы, но не библиотеки."""

    def test_a_changed_requirements_is_noticed(self):
        hub = FakeHub(files=[change("requirements.txt"), change("ops/split.py")])
        update.remember(OLD)
        self.assertTrue(update.look(hub).needs_install)

    def test_an_ordinary_update_says_nothing_about_it(self):
        hub = FakeHub(files=[change("ops/split.py")])
        update.remember(OLD)
        self.assertFalse(update.look(hub).needs_install)

    def test_it_reaches_the_result(self):
        hub = FakeHub(files=[change("requirements.txt")])
        update.remember(OLD)
        done = update.apply(hub, update.look(hub), check=False)
        self.assertTrue(done.as_dict()["needs_install"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
