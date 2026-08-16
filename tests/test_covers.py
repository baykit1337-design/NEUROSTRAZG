"""Обложки книг из рейтинга и их кэш (2.3 ТЗ NEUROSTRAZH).

Адрес обложки на сайте подписан и содержит срок действия. В сохранённом
срезе такая ссылка протухает, а срезы хранятся месяцами — вчерашний
рейтинг остался бы без картинок. Поэтому обложка скачивается один раз и
дальше берётся из своего кэша.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net.sources import rank as rank_net  # noqa: E402
from ops import covers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"

#: Однопиксельная картинка — содержимое неважно, важен сам факт байтов.
PIXEL = b"RIFF\x00\x00\x00\x00WEBPVP8 "


class FakeResponse:
    def __init__(self, content=PIXEL, status_code=200):
        self.content = content
        self.status_code = status_code


class FakeClient:
    """Клиент, который отдаёт то, что ему велели, и считает запросы."""

    def __init__(self, response=None):
        self.response = response if response is not None else FakeResponse()
        self.asked: list[str] = []

    def get(self, url, *args, **kwargs):
        self.asked.append(url)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def close(self):
        pass


class CoversBase(unittest.TestCase):
    """Кэш подменяется: настоящую папку data трогать нельзя."""

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.was = covers.COVER_DIR
        covers.COVER_DIR = Path(self.dir.name) / "covers"
        self.addCleanup(lambda: setattr(covers, "COVER_DIR", self.was))


class TestSafeName(CoversBase):
    """Код книги приходит с чужого сайта — в имя файла он идёт не как есть."""

    def test_a_normal_code_is_fine(self):
        self.assertEqual(covers.safe_id("7276663560335001631"),
                         "7276663560335001631")

    def test_a_path_is_refused(self):
        for bad in ("../../etc/passwd", "a/b", "a\\b", ".", "..", ""):
            with self.subTest(bad=bad):
                self.assertEqual(covers.safe_id(bad), "")

    def test_a_refused_code_has_no_place_to_go(self):
        self.assertIsNone(covers.path_for("../x"))

    def test_the_file_lands_where_the_spec_says(self):
        path = covers.path_for("123")
        self.assertEqual(path.name, "123.webp")
        self.assertEqual(path.parent.name, "covers")


class TestFetching(CoversBase):
    def test_the_picture_is_saved(self):
        client = FakeClient()
        self.assertTrue(covers.fetch(client, "123", "http://site/x.webp"))
        self.assertTrue(covers.have("123"))
        self.assertEqual(covers.path_for("123").read_bytes(), PIXEL)

    def test_it_is_not_downloaded_twice(self):
        """В новом срезе адрес другой, а картинка та же."""
        client = FakeClient()
        covers.fetch(client, "123", "http://site/first.webp")
        covers.fetch(client, "123", "http://site/second-signed.webp")
        self.assertEqual(len(client.asked), 1)

    def test_a_dead_link_is_not_a_crash(self):
        """Ссылки протухают — это ожидаемое, а не исключительное событие."""
        client = FakeClient(FakeResponse(b"", 403))
        self.assertFalse(covers.fetch(client, "123", "http://site/x.webp"))
        self.assertFalse(covers.have("123"))

    def test_a_network_failure_is_not_a_crash(self):
        client = FakeClient(OSError("сеть отвалилась"))
        self.assertFalse(covers.fetch(client, "123", "http://site/x.webp"))

    def test_an_empty_answer_is_not_saved(self):
        client = FakeClient(FakeResponse(b"", 200))
        self.assertFalse(covers.fetch(client, "123", "http://site/x.webp"))
        self.assertFalse(covers.have("123"))

    def test_something_far_too_big_is_not_a_cover(self):
        client = FakeClient(FakeResponse(b"x" * (covers.MAX_BYTES + 1)))
        self.assertFalse(covers.fetch(client, "123", "http://site/x.webp"))

    def test_no_link_means_nothing_to_do(self):
        client = FakeClient()
        self.assertFalse(covers.fetch(client, "123", ""))
        self.assertEqual(client.asked, [])

    def test_a_half_written_file_never_appears(self):
        """Половина картинки на диске чинится только руками."""
        client = FakeClient()
        covers.fetch(client, "123", "http://site/x.webp")
        leftovers = [p for p in covers.COVER_DIR.iterdir()
                     if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_a_broken_cover_can_be_thrown_away(self):
        covers.fetch(FakeClient(), "123", "http://site/x.webp")
        self.assertTrue(covers.forget("123"))
        self.assertFalse(covers.have("123"))

    def test_the_cache_can_be_counted(self):
        covers.fetch(FakeClient(), "123", "http://site/x.webp")
        found = covers.state()
        self.assertEqual(found["count"], 1)
        self.assertEqual(found["bytes"], len(PIXEL))

    def test_counting_an_empty_cache_is_not_a_crash(self):
        self.assertEqual(covers.state()["count"], 0)


class TestCoverInTheRow(unittest.TestCase):
    """Адрес обложки приходит вместе со строкой рейтинга."""

    def test_the_field_is_read_from_the_slice(self):
        row = rank_net.RankRow(book_id="7", cover="http://site/a.webp?x-expires=1")
        self.assertIn("cover", row.as_dict())

    def test_it_survives_saving_and_loading(self):
        row = rank_net.RankRow(book_id="7", cover="http://site/a.webp")
        again = rank_net.RankRow.from_dict(row.as_dict())
        self.assertEqual(again.cover, row.cover)

    def test_an_old_slice_without_covers_still_loads(self):
        again = rank_net.RankRow.from_dict({"book_id": "7", "name": "к"})
        self.assertEqual(again.cover, "")


class TestMimetype(CoversBase):
    """Расширение у файлов одно на все, а формат бывает разный.

    Объявишь webp там, где лежит jpeg, — браузер не покажет ничего, и
    выглядит это как «обложки не работают».
    """

    def written(self, data: bytes):
        covers.COVER_DIR.mkdir(parents=True, exist_ok=True)
        path = covers.path_for("123")
        path.write_bytes(data)
        return path

    def test_png(self):
        self.assertEqual(
            covers.mimetype_of(self.written(b"\x89PNG\r\n\x1a\n" + b"0" * 8)),
            "image/png")

    def test_jpeg(self):
        self.assertEqual(covers.mimetype_of(self.written(b"\xff\xd8\xff" + b"0" * 8)),
                         "image/jpeg")

    def test_gif(self):
        self.assertEqual(covers.mimetype_of(self.written(b"GIF89a" + b"0" * 8)),
                         "image/gif")

    def test_webp(self):
        self.assertEqual(
            covers.mimetype_of(self.written(b"RIFF\x00\x00\x00\x00WEBPVP8 ")),
            "image/webp")

    def test_something_unknown_falls_back_to_the_site_format(self):
        self.assertEqual(covers.mimetype_of(self.written(b"\x00" * 16)),
                         "image/webp")

    def test_a_missing_file_is_not_a_crash(self):
        self.assertEqual(covers.mimetype_of(covers.path_for("999")), "image/webp")


class TestCoverRoute(CoversBase):
    @classmethod
    def setUpClass(cls):
        from webapp.app import app

        app.config["TESTING"] = True
        cls.app = app.test_client()

    def test_a_cached_cover_is_given_out(self):
        covers.fetch(FakeClient(), "123", "http://site/x.webp")
        res = self.app.get("/api/rank/cover/123")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, PIXEL)
        self.assertEqual(res.headers["Content-Type"], "image/webp")

    def test_a_missing_cover_without_a_link_is_404(self):
        res = self.app.get("/api/rank/cover/123")
        self.assertEqual(res.status_code, 404)

    def test_a_bad_code_is_refused(self):
        res = self.app.get("/api/rank/cover/..%2F..%2Fetc%2Fpasswd")
        self.assertIn(res.status_code, (400, 404))

    def test_the_answer_is_cached_by_the_browser(self):
        """Имя файла — код книги, а картинка у книги одна."""
        covers.fetch(FakeClient(), "123", "http://site/x.webp")
        res = self.app.get("/api/rank/cover/123")
        self.assertIn("max-age", res.headers.get("Cache-Control", ""))


class TestCoverUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.tabs = (STATIC / "tabs.js").read_text(encoding="utf-8")

    def test_every_row_gets_a_thumbnail(self):
        self.assertIn("tr.append(rkCover(row))", self.tabs)

    def test_it_goes_through_our_own_cache(self):
        """Ссылка с сайта подписана и живёт недолго."""
        cover = self.tabs.split("function rkCover(row)", 1)[1]
        self.assertIn("/api/rank/cover/", cover)

    def test_loading_is_lazy(self):
        self.assertIn("img.loading = 'lazy'", self.tabs)

    def test_there_is_a_placeholder_while_it_loads(self):
        self.assertIn("#rkTable .cover{", self.page)
        self.assertIn("@keyframes cover-wait", self.page)

    def test_the_placeholder_stops_once_the_picture_is_there(self):
        self.assertIn("box.classList.add('ready')", self.tabs)
        self.assertIn("#rkTable .cover.ready", self.page)

    def test_a_missing_cover_leaves_the_placeholder_not_a_broken_icon(self):
        self.assertIn("box.classList.add('empty')", self.tabs)

    def test_the_size_matches_the_spec(self):
        block = self.page.split("#rkTable .cover{", 1)[1].split("}", 1)[0]
        self.assertIn("height:68px", block)
        self.assertIn("border-radius:5px", block)

    def test_the_chosen_book_card_uses_the_cache_too(self):
        self.assertIn("cover.src = `/api/rank/cover/", self.tabs)

    def test_calm_mode_stops_the_placeholder(self):
        self.assertIn("prefers-reduced-motion: reduce", self.page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
