"""Ключи, сессии и журнал разбора (часть 7 ТЗ NEUROSTRAZH)."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from llm import keys as keys_mod  # noqa: E402
from llm.client import (BadKey, DIRECT, LlmClient, LlmError, NoKeysLeft,  # noqa: E402
                        key_id, mask, short)
from mvl.proxies import Proxy  # noqa: E402
from ops import joblog, session as session_op  # noqa: E402

KEY_A = "AIzaAAAA1111222233334444aaaabbbbcccc"
KEY_B = "AIzaBBBB5555666677778888ddddeeeeffff"


class KeysBase(unittest.TestCase):
    """Настройки подменяются: настоящий config.json трогать нельзя."""

    def setUp(self):
        self._keys = settings.llm.keys
        self._api = settings.llm.api_key
        self._save = settings.save
        settings.llm.keys = []
        settings.llm.api_key = ""
        settings.save = lambda *a, **k: None

        def restore():
            settings.llm.keys = self._keys
            settings.llm.api_key = self._api
            settings.save = self._save

        self.addCleanup(restore)
        self.store = keys_mod.KeyStore()


class TestMasking(unittest.TestCase):
    """Ключи наружу целиком не уходят никогда."""

    def test_short_hides_the_middle(self):
        self.assertEqual(short(KEY_A), "AIza…cccc")

    def test_short_of_a_tiny_string_hides_everything(self):
        """Раньше показ звал `mask`, и короткий ключ выходил целиком."""
        self.assertEqual(short("abc"), "…")
        self.assertEqual(short(""), "")

    def test_id_is_stable_and_reveals_nothing(self):
        self.assertEqual(key_id(KEY_A), key_id(KEY_A))
        self.assertNotEqual(key_id(KEY_A), key_id(KEY_B))
        self.assertNotIn(KEY_A[:8], key_id(KEY_A))


class TestMaskingWithStore(KeysBase):
    def test_every_stored_key_is_scrubbed_from_text(self):
        """Ключей несколько, и в лог попадёт тот, на котором сорвалось."""
        self.store.add(f"{KEY_A}\n{KEY_B}")
        text = mask(f"сбой по {KEY_B} после {KEY_A}")
        self.assertNotIn(KEY_A, text)
        self.assertNotIn(KEY_B, text)

    def test_key_in_a_url_is_scrubbed(self):
        self.assertNotIn("секрет", mask("https://api/models?key=секрет&x=1"))


class TestKeyList(KeysBase):
    """7.1: список ключей."""

    def test_added_one_by_one(self):
        self.store.add(KEY_A, name="основной")
        self.store.add(KEY_B, name="запасной")
        self.assertEqual([k.name for k in self.store.all()],
                         ["основной", "запасной"])

    def test_added_as_several_lines_at_once(self):
        """Ключи заводят пачкой и копируют из блокнота целиком."""
        self.store.add(f"{KEY_A}\n{KEY_B}")
        self.assertEqual(len(self.store.all()), 2)

    def test_duplicates_are_not_added_twice(self):
        self.store.add(KEY_A)
        self.store.add(KEY_A)
        self.assertEqual(len(self.store.all()), 1)

    def test_removed_by_id_not_by_look(self):
        """У ключей одного провайдера начало совпадает."""
        self.store.add(f"{KEY_A}\n{KEY_B}")
        self.store.remove(key_id(KEY_A))
        self.assertEqual([k.key for k in self.store.all()], [KEY_B])

    def test_old_single_key_setting_is_picked_up(self):
        """Иначе прежний ключ молча пропал бы при обновлении программы."""
        settings.llm.api_key = KEY_A
        self.assertEqual([k.key for k in self.store.all()], [KEY_A])

    def test_key_lives_in_one_place_only(self):
        settings.llm.api_key = KEY_A
        self.store.add(KEY_B)
        self.assertEqual(settings.llm.api_key, "")
        self.assertEqual(len(self.store.all()), 2)

    def test_state_hides_the_keys(self):
        self.store.add(KEY_A)
        state = self.store.state()
        self.assertEqual(state["keys"][0]["key"], short(KEY_A))
        self.assertNotIn(KEY_A, str(state))


class TestRotation(KeysBase):
    """7.1 и 7.2: расход, лимит и переход на следующий ключ."""

    def test_first_active_key_is_taken(self):
        self.store.add(f"{KEY_A}\n{KEY_B}")
        self.assertEqual(self.store.active().key, KEY_A)

    def test_limit_exhausts_the_key_without_waiting_for_the_server(self):
        """Дождаться отказа — значит потерять запрос."""
        self.store.add(KEY_A, limit=2)
        key = self.store.active()
        self.store.spend(key)
        self.store.spend(key)
        self.assertEqual(self.store.all()[0].state, keys_mod.EXHAUSTED)

    def test_next_key_takes_over(self):
        self.store.add(KEY_A, limit=1)
        self.store.add(KEY_B)
        self.store.spend(self.store.active())
        self.assertEqual(self.store.active().key, KEY_B)

    def test_no_keys_left_says_when_they_come_back(self):
        self.store.add(KEY_A, limit=1)
        self.store.spend(self.store.active())
        with self.assertRaises(NoKeysLeft) as caught:
            self.store.active()
        self.assertIn("сброс", str(caught.exception).lower())

    def test_empty_list_asks_for_a_key(self):
        with self.assertRaises(NoKeysLeft) as caught:
            self.store.active()
        self.assertIn("Добавьте", str(caught.exception))

    def test_unlimited_key_never_exhausts_itself(self):
        self.store.add(KEY_A)
        key = self.store.active()
        for _ in range(50):
            self.store.spend(key)
        self.assertEqual(self.store.all()[0].state, keys_mod.ACTIVE)


class TestManualState(KeysBase):
    """7.3: статус переключается вручную."""

    def test_exhausted_can_be_woken_by_hand(self):
        self.store.add(KEY_A, limit=1)
        self.store.spend(self.store.active())
        self.store.update(key_id(KEY_A), state=keys_mod.ACTIVE, used=0,
                          reset_at="", exhausted_at="")
        self.assertEqual(self.store.active().key, KEY_A)

    def test_active_can_be_put_aside(self):
        self.store.add(f"{KEY_A}\n{KEY_B}")
        self.store.update(key_id(KEY_A), state=keys_mod.EXHAUSTED)
        self.assertEqual(self.store.active().key, KEY_B)

    def test_limit_is_editable(self):
        self.store.add(KEY_A)
        self.store.update(key_id(KEY_A), limit=500)
        self.assertEqual(self.store.all()[0].limit, 500)


class TestResetTimer(KeysBase):
    """7.4: таймер сброса квоты."""

    def test_exhausting_sets_a_reset_time(self):
        self.store.add(KEY_A)
        self.store.exhaust(self.store.all()[0])
        key = self.store.all()[0]
        self.assertTrue(key.reset_at)
        self.assertGreater(key.resets_in, 0)

    def test_server_time_wins_over_the_guess(self):
        """У разных ключей сроки разные, а сервер знает точно."""
        self.store.add(KEY_A)
        self.store.exhaust(self.store.all()[0], seconds=90)
        self.assertLessEqual(self.store.all()[0].resets_in, 91)

    def test_key_wakes_up_when_the_time_passes(self):
        self.store.add(KEY_A)
        self.store.exhaust(self.store.all()[0])
        past = (datetime.now() - timedelta(minutes=1)).strftime(keys_mod.STAMP)
        self.store.update(key_id(KEY_A), reset_at=past)

        self.assertEqual(self.store.active().key, KEY_A)
        self.assertEqual(self.store.all()[0].used, 0)

    def test_countdown_is_reported(self):
        self.store.add(KEY_A)
        self.store.exhaust(self.store.all()[0], seconds=3600)
        self.assertIn("resets_in", self.store.state()["keys"][0])


class TestEstimate(unittest.TestCase):
    """7.2: рекомендация лимита на ключ."""

    class Chapter:
        def __init__(self, size):
            self.size = size
            self.text = "x" * size

    def test_work_is_split_between_keys(self):
        from llm.client import estimate

        chapters = [self.Chapter(3500) for _ in range(90)]
        one = estimate(chapters, keys=1).per_key
        three = estimate(chapters, keys=3).per_key
        self.assertLess(three, one)

    def test_recommendation_leaves_room_for_retries(self):
        from llm.client import estimate

        chapters = [self.Chapter(3500) for _ in range(100)]
        self.assertGreater(estimate(chapters, keys=1).per_key, 100)

    def test_average_chapter_is_reported(self):
        from llm.client import estimate

        report = estimate([self.Chapter(3500)] * 10).as_dict()
        self.assertGreater(report["average"], 0)
        self.assertEqual(report["keys"], 1)


class TestSession(unittest.TestCase):
    """7.6: сессия разбора."""

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_start_and_load(self):
        session_op.start(self.root, ["книга"], total=200)
        found = session_op.load(self.root)
        self.assertEqual(found.total, 200)
        self.assertEqual(found.state, session_op.RUNNING)

    def test_progress_is_kept(self):
        session_op.start(self.root, ["книга"], total=200)
        session_op.update(self.root, done=16)
        self.assertEqual(session_op.load(self.root).done, 16)
        self.assertEqual(session_op.load(self.root).left, 184)

    def test_stop_keeps_the_reason(self):
        """«Остановлено» и «кончились ключи» требуют разного."""
        session_op.start(self.root, ["книга"], total=200)
        session_op.stop(self.root, "ключи исчерпаны", done=16)
        found = session_op.load(self.root)
        self.assertEqual(found.state, session_op.STOPPED)
        self.assertIn("ключи", found.reason)

    def test_finished_session_is_not_offered_again(self):
        session_op.start(self.root, ["книга"], total=3)
        session_op.finish(self.root, done=3)
        self.assertTrue(session_op.load(self.root).finished)

    def test_same_folder_continues_the_old_session(self):
        session_op.start(self.root, ["книга"], total=200)
        session_op.update(self.root, done=16)
        again = session_op.start(self.root, ["книга"], total=200)
        self.assertEqual(again.done, 16)

    def test_other_selection_starts_over(self):
        session_op.start(self.root, ["книга"], total=200)
        session_op.update(self.root, done=16)
        again = session_op.start(self.root, ["другая книга"], total=50)
        self.assertEqual(again.done, 0)

    def test_forget_wipes_progress_only(self):
        session_op.start(self.root, ["книга"], total=200)
        (self.root / "analysis" / "facts").mkdir(parents=True, exist_ok=True)
        keep = self.root / "analysis" / "facts" / "0001.json"
        keep.write_text("{}", encoding="utf-8")

        self.assertTrue(session_op.forget(self.root))
        self.assertIsNone(session_op.load(self.root))
        # За кэш уже заплачено — его «Начать заново» не трогает.
        self.assertTrue(keep.is_file())

    def test_missing_session_is_not_an_error(self):
        self.assertIsNone(session_op.load(self.root))
        self.assertFalse(session_op.forget(self.root))

    def test_broken_file_is_not_an_error(self):
        path = self.root / "analysis" / "session.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("не json", encoding="utf-8")
        self.assertIsNone(session_op.load(self.root))


class TestJobLog(unittest.TestCase):
    """7.7: журнал под прогресс-баром."""

    def test_lines_are_kept_in_order(self):
        log = joblog.JobLog()
        log.add("первая")
        log.add("вторая")
        self.assertEqual([l["text"] for l in log.lines()], ["первая", "вторая"])

    def test_time_is_stamped(self):
        log = joblog.JobLog()
        log.add("строка")
        self.assertRegex(log.lines()[0]["at"], r"^\d{2}:\d{2}:\d{2}$")

    def test_only_the_last_lines_are_kept(self):
        """На пятистах главах строк набегают тысячи."""
        log = joblog.JobLog(keep=10)
        for n in range(50):
            log.add(f"строка {n}")
        self.assertEqual(len(log.lines()), 10)
        self.assertEqual(log.total, 50)
        self.assertEqual(log.lines()[-1]["text"], "строка 49")

    def test_tail_can_be_fetched_by_position(self):
        log = joblog.JobLog()
        for n in range(5):
            log.add(f"строка {n}")
        self.assertEqual(len(log.lines(since=3)), 2)

    def test_empty_lines_are_ignored(self):
        log = joblog.JobLog()
        log.add("   ")
        log.add("")
        self.assertEqual(log.lines(), [])

    def test_saved_as_text(self):
        log = joblog.JobLog()
        log.add("глава 215 разобрана")
        self.assertIn("глава 215 разобрана", log.as_text())


class TestRoute(KeysBase):
    """Через что уходит запрос к модели и что об этом сказано (1.1 ТЗ).

    Раньше на вопрос «а точно ли запросы идут через прокси» ответить было
    нечем: в журнале о маршруте не было ни строчки.
    """

    def setUp(self):
        super().setUp()
        self._use = settings.llm.use_proxies
        self.addCleanup(lambda: setattr(settings.llm, "use_proxies", self._use))
        settings.llm.use_proxies = True
        self.said: list[str] = []

    def _client(self, pool=None):
        return LlmClient(key=KEY_A, pool=pool, on_event=self.said.append)

    def test_no_proxies_means_straight_and_it_is_said_so(self):
        route = self._client()._proxies()
        self.assertEqual(route, [(None, DIRECT)])

    def test_proxy_is_named_without_the_password(self):
        proxy = Proxy(host="10.0.0.1", port=8080,
                      username="user", password="s3cret")
        route = self._client(_Pool([proxy]))._proxies()
        self.assertEqual(route, [(proxy.url, "10.0.0.1:8080")])
        self.assertNotIn("s3cret", route[0][1])

    def test_disabled_proxy_is_skipped(self):
        live = Proxy(host="10.0.0.1", port=8080)
        dead = Proxy(host="10.0.0.2", port=8080, disabled=True)
        route = self._client(_Pool([live, dead]))._proxies()
        self.assertEqual([label for _, label in route], ["10.0.0.1:8080"])

    def test_checkbox_off_means_straight_even_with_proxies(self):
        settings.llm.use_proxies = False
        route = self._client(_Pool([Proxy(host="10.0.0.1", port=8080)]))._proxies()
        self.assertEqual(route, [(None, DIRECT)])

    def test_every_attempt_is_written_to_the_log(self):
        client = self._client(_Pool([Proxy(host="10.0.0.1", port=8080),
                                     Proxy(host="10.0.0.2", port=8080)]))
        client._http = lambda url: None
        client._once = _refuse
        with self.assertRaises(LlmError):
            client._request("models")

        route = [line for line in self.said if line.startswith("запрос к модели")]
        self.assertEqual(route, ["запрос к модели через 10.0.0.1:8080",
                                 "запрос к модели через 10.0.0.2:8080"])

    def test_next_address_is_taken_after_a_refusal(self):
        client = self._client(_Pool([Proxy(host="10.0.0.1", port=8080),
                                     Proxy(host="10.0.0.2", port=8080)]))
        client._http = lambda url: None
        client._once = _refuse
        with self.assertRaises(LlmError):
            client._request("models")
        self.assertTrue(any("пробую следующий адрес" in line for line in self.said))

    def test_a_bad_key_does_not_start_a_tour_of_the_addresses(self):
        """Дело в ключе — перебирать адреса бессмысленно и долго."""
        client = self._client(_Pool([Proxy(host="10.0.0.1", port=8080),
                                     Proxy(host="10.0.0.2", port=8080)]))
        client._http = lambda url: None

        def reject(*a, **k):
            raise BadKey("ключ отклонён")

        client._once = reject
        with self.assertRaises(BadKey):
            client._request("models")
        self.assertEqual(
            len([line for line in self.said if line.startswith("запрос к модели")]), 1)

    def test_failure_says_it_in_words_not_in_curl(self):
        client = self._client()
        client._http = lambda url: None
        client._once = _refuse
        with self.assertRaises(LlmError) as caught:
            client._request("models")
        self.assertIn("Не удалось связаться с Gemini", str(caught.exception))


class _Pool:
    """Список прокси в том виде, в каком его видит клиент."""

    def __init__(self, proxies):
        self.proxies = proxies


def _refuse(*args, **kwargs):
    raise OSError("соединение сброшено")


if __name__ == "__main__":
    unittest.main(verbosity=2)
