"""Обрыв связи ставит прогон на паузу, а не заканчивает книгу.

Раньше выдернутый кабель выглядел для качалки ровно как «сайт лёг»: тот
же отказ, тот же текст от curl. И поступала она с ним так же — писала
причину и останавливалась. Человек возвращался через минуту к целому
интернету и остановленному на трёхсотой главе прогону.

Отличить одно от другого по тексту ошибки нельзя. Поэтому спрашиваем не
текст, а связь: `core.online` стучится в публичные адреса напрямую. Не
ответил никто — беда наша, и её надо переждать. Ответил хоть кто-то —
беда не наша, и дальше всё как было.

Здесь проверяется и то, и другое: что обрыв пережидается, и что при
живой сети ничего не изменилось.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import online as online_mod  # noqa: E402
from mvl import api  # noqa: E402
from mvl import client as client_mod  # noqa: E402
from mvl import downloader as downloader_mod  # noqa: E402
from mvl.client import NetworkError  # noqa: E402
from mvl.downloader import Downloader  # noqa: E402


class Source:
    """Источник, у которого главы отваливаются заданное число раз.

    `flaky` — номера глав, которые не придут с первого раза. Со второго
    приходят: так ведёт себя книга, когда виновата была не она.
    """

    key = "fake"
    name = "Подставной"
    needs_proxy = False
    cancel = None
    timeouts: dict = {}

    def __init__(self, total=9, flaky=(), fails=1):
        self.total = total
        self.flaky = set(flaky)
        self.fails = fails
        #: Сколько раз каждую главу спрашивали.
        self.tries: dict[int, int] = {}

    def toc(self, client, novel, first=1, last=None, on_progress=None):
        rows = [api.Chapter(number=n, post_id=str(n))
                for n in range(first, (last or self.total) + 1)]
        return api.Toc(chapters=rows, missing=[])

    def chapter(self, client, chapter):
        self.tries[chapter.number] = self.tries.get(chapter.number, 0) + 1
        if (chapter.number in self.flaky
                and self.tries[chapter.number] <= self.fails):
            raise NetworkError("Connection was reset")
        return f"Глава {chapter.number}", "Текст главы."


class Base(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, downloader_mod, "BATCH_PAUSE_RANGE",
                        downloader_mod.BATCH_PAUSE_RANGE)
        downloader_mod.BATCH_PAUSE_RANGE = (0, 0)
        # Ждать по-настоящему тут нечего: проверяется решение, а не темп.
        self.addCleanup(setattr, downloader_mod, "OFFLINE_WAITS",
                        downloader_mod.OFFLINE_WAITS)
        downloader_mod.OFFLINE_WAITS = (0, 0, 0)
        # Вежливая пауза между главами берётся у клиента в момент вызова.
        self.addCleanup(setattr, client_mod, "SITE_PAUSE_RANGE",
                        client_mod.SITE_PAUSE_RANGE)
        client_mod.SITE_PAUSE_RANGE = (0, 0)

        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def network(self, answers):
        """Подменяет вопрос «есть ли связь» списком ответов.

        `answers` — что отвечать по порядку; когда список кончится, дальше
        отвечаем последним. `True` значит «связи нет».
        """
        self.asked = []
        answers = list(answers)

        def offline(extra=()):
            said = answers[len(self.asked)] if len(self.asked) < len(answers) \
                else answers[-1]
            self.asked.append(said)
            return said

        self.addCleanup(setattr, online_mod, "offline", online_mod.offline)
        online_mod.offline = offline

    def run_with(self, source, threads=1):
        loader = Downloader(source=source, threads=threads, probe=False)
        novel = api.Novel(code=1, name="Книга", slug="k",
                          total_chapters=source.total)
        return loader, loader.run(novel, self.folder)


class TestABreakIsWaitedOut(Base):
    """Связь пропала и вернулась — книга должна доехать до конца."""

    def test_the_chapter_is_taken_again_after_the_break(self):
        source = Source(total=5, flaky=(3,))
        self.network([True, False])
        _, report = self.run_with(source)
        self.assertEqual(report.downloaded, 5)
        self.assertEqual(report.failed_chapters, [])

    def test_the_same_chapter_is_the_one_retried(self):
        """Не следующая: пропущенная глава — это дыра в книге."""
        source = Source(total=5, flaky=(3,))
        self.network([True, False])
        self.run_with(source)
        self.assertEqual(source.tries[3], 2)

    def test_the_screen_says_we_are_waiting(self):
        """Молча стоящий прогон человек считает зависшим и убивает."""
        said = []
        source = Source(total=5, flaky=(3,))
        self.network([True, False])
        loader = Downloader(source=source, threads=1, probe=False,
                            on_progress=lambda p: said.append(
                                (p.stage, p.message or "")))
        loader.run(api.Novel(code=1, name="Книга", slug="k",
                             total_chapters=5), self.folder)
        waiting = [text for stage, text in said if stage == "offline"]
        self.assertTrue(waiting)
        self.assertTrue(waiting[0].strip())

    def test_a_break_that_never_ends_still_stops_the_run(self):
        """Ждать вечно — то же зависание, только с объяснением."""
        source = Source(total=5, flaky=(3,), fails=99)
        self.network([True])
        _, report = self.run_with(source)
        self.assertEqual(report.downloaded, 2)


class TestALiveNetworkChangesNothing(Base):
    """Сайт лёг — это по-прежнему остановка, а не получасовое ожидание."""

    def test_the_run_stops_as_before(self):
        source = Source(total=5, flaky=(3,), fails=99)
        self.network([False])
        _, report = self.run_with(source)
        self.assertEqual(report.downloaded, 2)

    def test_the_broken_chapter_is_not_asked_twice(self):
        """Повтор при живой сети — это лишний запрос на мёртвый сайт."""
        source = Source(total=5, flaky=(3,), fails=99)
        self.network([False])
        self.run_with(source)
        self.assertEqual(source.tries[3], 1)

    def test_a_clean_run_never_asks_about_the_network(self):
        """Проверка связи — это соединения наружу. Даром их не тратим."""
        source = Source(total=5)
        self.network([False])
        _, report = self.run_with(source)
        self.assertEqual(report.downloaded, 5)
        self.assertEqual(self.asked, [])


class TestTheWholeBatchComesBack(Base):
    """В несколько потоков обрыв уносит всю пачку разом."""

    def test_the_batch_is_downloaded_after_the_break(self):
        source = Source(total=9, flaky=(1, 2, 3))
        self.network([True, False])
        _, report = self.run_with(source, threads=3)
        self.assertEqual(report.downloaded, 9)

    def test_the_chapters_do_not_stay_in_the_failed_list(self):
        """Они скачаны. Оставить их в «не скачано» — соврать в отчёте."""
        source = Source(total=9, flaky=(1, 2, 3))
        self.network([True, False])
        _, report = self.run_with(source, threads=3)
        self.assertEqual(report.failed_chapters, [])

    def test_the_threads_are_not_dropped_for_a_break(self):
        """Сбавлять обороты незачем: сайт тут ни при чём."""
        source = Source(total=9, flaky=(1, 2, 3))
        self.network([True, False])
        loader, _ = self.run_with(source, threads=3)
        self.assertEqual(loader.threads, 3)

    def test_a_live_network_still_drops_the_threads(self):
        source = Source(total=9, flaky=(1, 2, 3), fails=99)
        self.network([False])
        loader, _ = self.run_with(source, threads=3)
        self.assertEqual(loader.threads, 1)


class TestTheSessionIsMadeAnewAfterStanding(Base):
    """«Поставил паузу, выдернул интернет, вернул, нажал продолжить».

    Прежнее соединение к этому моменту мертво, и первая же глава после
    паузы отваливалась по сети — при полностью живом интернете. Пауза
    затем и нужна, чтобы чинить связь; значит после неё сессию надо
    заводить заново.
    """

    def loader(self):
        return Downloader(source=Source(), threads=1, probe=False)

    def test_a_run_that_never_stood_makes_nothing_anew(self):
        self.assertFalse(self.loader()._take_stood())

    def test_standing_on_a_pause_is_remembered(self):
        loader = self.loader()
        loader.paused.set()
        threading.Timer(0.05, loader.paused.clear).start()
        loader._hold()
        self.assertTrue(loader._take_stood())

    def test_it_is_remembered_only_once(self):
        """Иначе сессия заводилась бы заново на каждой главе до конца."""
        loader = self.loader()
        loader._stood = True
        loader._take_stood()
        self.assertFalse(loader._take_stood())

    def test_waiting_out_a_break_counts_as_standing(self):
        loader = self.loader()
        self.network([True, False])
        self.assertTrue(loader._wait_for_network("оборвалось"))
        self.assertTrue(loader._take_stood())


class TestHowManyBreaksWeSitThrough(Base):
    """Мигающая связь не должна крутить книгу по кругу без конца."""

    def test_the_rescues_are_counted(self):
        loader = Downloader(source=Source(), threads=1, probe=False)
        self.network([True, False])
        loader._wait_for_network("оборвалось")
        self.assertEqual(loader._offline_rescues, 1)

    def test_after_the_limit_a_break_is_an_ordinary_trouble(self):
        loader = Downloader(source=Source(), threads=1, probe=False)
        loader._offline_rescues = downloader_mod.MAX_OFFLINE_RESCUES
        self.network([True, False])
        self.assertFalse(loader._wait_for_network("оборвалось"))
        # И связь даже не спрашивали: ответ уже известен.
        self.assertEqual(self.asked, [])


class TestAskingWhetherThereIsANetwork(unittest.TestCase):
    """Сам вопрос: `core.online`."""

    def setUp(self):
        self.tried = []
        self.addCleanup(setattr, online_mod, "reachable", online_mod.reachable)

    def answer(self, alive):
        def reachable(host, port, timeout=online_mod.TIMEOUT):
            self.tried.append((host, port))
            return (host, port) in alive
        online_mod.reachable = reachable

    def test_one_answering_address_is_enough(self):
        self.answer({online_mod.PROBES[-1]})
        self.assertTrue(online_mod.online())

    def test_silence_from_everyone_means_no_network(self):
        """Именно от всех: один закрытый у провайдера адрес — не приговор
        интернету, а повод спросить следующего."""
        self.answer(set())
        self.assertTrue(online_mod.offline())
        self.assertEqual(len(self.tried), len(online_mod.PROBES))

    def test_our_own_proxy_is_asked_first(self):
        """Он и есть наша связь с миром: молчит он — остальное неважно."""
        self.answer({("10.0.0.1", 8080)})
        self.assertTrue(online_mod.online([("10.0.0.1", 8080)]))
        self.assertEqual(self.tried, [("10.0.0.1", 8080)])

    def test_the_addresses_asked_are_not_names(self):
        """Имена может не отдавать сам DNS — это третья беда со своим
        лечением, и путать её с «интернета нет» нельзя."""
        for host, _ in online_mod.PROBES:
            self.assertRegex(host, r"^\d+\.\d+\.\d+\.\d+$")

    def test_a_dead_address_is_not_reachable(self):
        """Настоящий сокет, без подмен: адрес из зарезервированных под
        документацию, туда не дозвониться ниоткуда."""
        self.assertFalse(online_mod.reachable("192.0.2.1", 443, timeout=0.2))


if __name__ == "__main__":
    unittest.main()
