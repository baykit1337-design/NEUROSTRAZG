"""Второй способ качать Фанкью — через стороннего посредника.

Веб-версия отдаёт закрытые главы только тем, кто вошёл, а таких глав у
книги обычно подавляющее большинство: у книги на тысячу двести глав
открыто десять. Посредник отдаёт их все — но это чужая машина по голому
адресу, поэтому способ выбирается руками и по умолчанию не включён.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from mvl.api import Chapter  # noqa: E402
from net import sources  # noqa: E402
from net.sources.base import SourceBroken  # noqa: E402
from net.sources.fanqie import ChapterEncrypted, PaidChapter  # noqa: E402
from net.sources.fanqiemirror import FanqieMirrorSource  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class FakeClient:
    def __init__(self, answer=""):
        self.answer = answer
        self.asked = []

    def get_text(self, url, params=None, headers=None):
        self.asked.append(url)
        return self.answer


def reply(content="", code=200, message=""):
    body = {"code": code, "data": {"content": content}}
    if message:
        body["message"] = message
    return json.dumps(body, ensure_ascii=False)


class MirrorBase(unittest.TestCase):
    def setUp(self):
        self.source = FanqieMirrorSource()

    def chapter(self):
        return Chapter(number=4, post_id="7496032198177325593",
                       ch_name="Глава 4")


class TestChoiceIsDeliberate(unittest.TestCase):
    """Способ выбирается руками: он меняет книгу на чужой сервер."""

    def test_the_mirror_is_offered_as_its_own_source(self):
        keys = [s.key for s in sources.all_sources()]
        self.assertIn("fanqie-mirror", keys)

    def test_it_is_not_the_default(self):
        self.assertNotEqual(sources.get("").key, "fanqie-mirror")

    def test_the_plain_site_stays_available(self):
        """Прежний способ никуда не делся — он без посредника."""
        self.assertEqual(sources.get("fanqie").key, "fanqie")

    def test_the_hint_says_what_the_price_is(self):
        """Человек должен узнать про чужой сервер до нажатия, а не после."""
        hint = sources.get("fanqie-mirror").hint
        self.assertIn("сторонний", hint)
        self.assertIn("шифрования", hint)

    def test_the_address_lives_in_the_settings(self):
        """Адрес по голому IP умрёт — заменить его должно быть можно."""
        self.assertTrue(settings.mirror.url)
        self.assertIn("mirror", sources.get("fanqie-mirror").hint)


class TestChapterFromTheMirror(MirrorBase):
    def test_the_text_comes_back(self):
        client = FakeClient(reply("<p>Первый абзац.</p><p>Второй абзац.</p>"))
        title, text = self.source.chapter(client, self.chapter())

        self.assertEqual(title, "Глава 4")
        self.assertIn("Первый абзац.", text)
        self.assertIn("Второй абзац.", text)

    def test_the_chapter_id_goes_into_the_address(self):
        client = FakeClient(reply("<p>Текст.</p>"))
        self.source.chapter(client, self.chapter())
        self.assertIn("item_id=7496032198177325593", client.asked[0])

    def test_voice_blocks_are_thrown_away(self):
        """Вставки озвучки — служебные, в книге им не место."""
        client = FakeClient(reply(
            '<div class="novel-fm-asr">озвучка</div><p>Текст главы.</p>'))
        _, text = self.source.chapter(client, self.chapter())

        self.assertNotIn("озвучка", text)
        self.assertIn("Текст главы.", text)

    def test_voice_marks_inside_a_paragraph_are_thrown_away_too(self):
        client = FakeClient(reply("<p>Текст.{!-- PGC_VOICE:1234 --}</p>"))
        _, text = self.source.chapter(client, self.chapter())

        self.assertNotIn("PGC_VOICE", text)
        self.assertIn("Текст.", text)

    def test_a_chapter_without_an_id_is_refused(self):
        with self.assertRaises(SourceBroken):
            self.source.chapter(FakeClient(), Chapter(number=1))


class TestMirrorRefusals(MirrorBase):
    """Отказ посредника не должен выглядеть как поломка нашего разбора."""

    def test_its_own_code_is_repeated_back(self):
        client = FakeClient(reply(code=500, message="ничего не найдено"))
        with self.assertRaises(SourceBroken) as caught:
            self.source.chapter(client, self.chapter())

        said = str(caught.exception)
        self.assertIn("500", said)
        self.assertIn("ничего не найдено", said)
        self.assertIn(settings.mirror.url, said, "адрес должен быть в отказе")

    def test_an_empty_chapter_counts_as_closed(self):
        with self.assertRaises(PaidChapter):
            self.source.chapter(FakeClient(reply("")), self.chapter())

    def test_a_paid_stub_counts_as_closed(self):
        with self.assertRaises(PaidChapter):
            self.source.chapter(FakeClient(reply("<p>需要付费</p>")),
                                self.chapter())

    def test_markup_without_any_text_is_a_breakage(self):
        with self.assertRaises(SourceBroken):
            self.source.chapter(FakeClient(reply("<p>   </p>")),
                                self.chapter())

    def test_not_json_at_all(self):
        with self.assertRaises(SourceBroken):
            self.source.chapter(FakeClient("<html>вход</html>"),
                                self.chapter())

    def test_encrypted_text_is_still_refused(self):
        """Посредник отдаёт готовый текст, но проверку не отменяем.

        Начнёт однажды отдавать зашифрованное — узнаем сразу, а не через
        сотню глав нечитаемых файлов.
        """
        secret = "".join(chr(0xE000 + n % 80) for n in range(200))
        with self.assertRaises(ChapterEncrypted):
            self.source.chapter(FakeClient(reply(f"<p>Начало.{secret}</p>")),
                                self.chapter())

    def test_an_empty_address_says_so_plainly(self):
        saved = settings.mirror.url
        settings.mirror.url = ""
        self.addCleanup(setattr, settings.mirror, "url", saved)

        with self.assertRaises(SourceBroken) as caught:
            self.source.chapter(FakeClient(reply("<p>Текст.</p>")),
                                self.chapter())
        self.assertIn("mirror", str(caught.exception))


class TestBookStillComesFromTheSite(MirrorBase):
    """Посредник отвечает только за текст главы.

    Поиск и оглавление берутся с самого сайта: там они и точнее, и без
    посторонних. Значит, весь разбор страницы наследуется как есть.
    """

    def test_the_code_is_read_the_same_way(self):
        self.assertEqual(
            self.source.code_of("https://fanqienovel.com/page/7143038691944959011"),
            "7143038691944959011")

    def test_it_still_needs_a_proxy(self):
        """Страница книги китайская — без прокси её не видно."""
        self.assertTrue(self.source.needs_proxy)


class TestLicenceIsHonoured(unittest.TestCase):
    """Адрес посредника взят из проекта под AGPL-3.0.

    Лицензия требовательная: она распространяется на всю программу, а не
    на один файл. Раз мы этим пользуемся — текст лицензии лежит рядом, и
    в README сказано, откуда что взято.
    """

    def test_the_licence_text_is_in_the_repository(self):
        licence = ROOT / "LICENSE"
        self.assertTrue(licence.is_file(), "нет файла LICENSE")
        self.assertIn("AFFERO", licence.read_text(encoding="utf-8")[:400].upper())

    def test_the_readme_names_the_source_of_the_address(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("ying-ck/fanqienovel-downloader", readme)
        self.assertIn("AGPL", readme)


if __name__ == "__main__":
    unittest.main()


class TestAnUnusableChapterDoesNotKillTheRun(unittest.TestCase):
    """Платная и нерасшифрованная глава пропускаются, а не роняют книгу.

    Последовательный путь ловил только сетевые ошибки. `PaidChapter` и
    `ChapterEncrypted` — обычные исключения, они пролетали мимо всех
    перехватов и убивали задачу целиком: «скачано 0, пропущено 0,
    ошибок 0» и стек в логе. Многопоточный путь такое умел давно —
    расходились две ветки одного и того же.
    """

    def test_both_kinds_count_as_skippable(self):
        from mvl.downloader import _is_paid

        self.assertTrue(_is_paid(PaidChapter("платная")))
        self.assertTrue(_is_paid(ChapterEncrypted("нерасшифрована")))

    def test_a_network_error_is_not_skippable(self):
        """Сетевую осечку повтор лечит — её пропускать нельзя."""
        from mvl.downloader import _is_paid

        self.assertFalse(_is_paid(OSError("сеть отвалилась")))

    def test_the_sequential_path_handles_them_too(self):
        source = (ROOT / "mvl" / "downloader.py").read_text(encoding="utf-8")
        loop = source.split("for index, chapter in enumerate(pending)", 1)[1]
        loop = loop.split("def _finish", 1)[0]

        self.assertIn("if not _is_paid(exc):", loop)
        self.assertIn("paid += 1", loop)

    def test_skipped_chapters_reach_the_report(self):
        """Иначе в итоге стоит «пропущено 0» при пропущенных главах."""
        source = (ROOT / "mvl" / "downloader.py").read_text(encoding="utf-8")
        self.assertIn("skipped + paid", source)


class TestProxyOrderPrefersCheckedOnes(unittest.TestCase):
    """Замер утыкался в мёртвый адрес, хотя рядом было восемь рабочих.

    `disabled` ставится только на ходу, а проверка кнопкой помечает
    иначе — через `alive` и `status`. Список «не disabled» поэтому
    включал и провалившие проверку, и первым по порядку в файле шёл
    мёртвый.
    """

    class FakePool:
        """Пул из пар «пригоден, отключён» в порядке файла."""

        class Address:
            def __init__(self, url, usable=False, disabled=False):
                self.url, self.usable, self.disabled = url, usable, disabled

        def __init__(self, *rows):
            self.proxies = [self.Address(*row) for row in rows]

    def order(self, pool):
        from webapp.app import _working_proxies

        return [p.url for p in _working_proxies(pool)]

    def test_a_checked_address_beats_the_first_one_in_the_file(self):
        """Ровно тот случай из отчёта: мёртвый первый, рабочие следом."""
        pool = self.FakePool(("мёртвый", False), ("рабочий", True))
        self.assertEqual(self.order(pool)[0], "рабочий")

    def test_unchecked_ones_are_not_thrown_away(self):
        """До нажатия кнопки пригодных нет вовсе — без адреса хуже."""
        pool = self.FakePool(("первый", False), ("второй", False))
        self.assertEqual(self.order(pool), ["первый", "второй"])

    def test_disabled_ones_are_left_out(self):
        """Отключённый на ходу — единственный, кто действительно мёртв."""
        pool = self.FakePool(("выбывший", True, True), ("живой", True))
        self.assertEqual(self.order(pool), ["живой"])

    def test_an_address_without_the_checked_flag_counts_as_unchecked(self):
        """Пул приходит снаружи; не всякий объект носит признак проверки."""
        class Bare:
            url, disabled = "без признака", False

        class Pool:
            proxies = [Bare()]

        self.assertEqual(self.order(Pool()), ["без признака"])

    def test_no_pool_at_all_is_not_a_crash(self):
        self.assertEqual(self.order(None), [])

    def test_the_threads_check_uses_that_order(self):
        app = (ROOT / "webapp" / "app.py").read_text(encoding="utf-8")
        self.assertIn("live = _working_proxies(pool)", app)
