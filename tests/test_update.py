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


if __name__ == "__main__":
    unittest.main(verbosity=2)
