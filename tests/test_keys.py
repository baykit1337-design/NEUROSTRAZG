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
                        QuotaSpent, key_id, mask, short)
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


class TestOneKeyStore(unittest.TestCase):
    """Хранилище ключей одно на всё приложение (1.3 ТЗ).

    Разбор глав работал, а «Перевести названия» и «Аннотация» падали с
    «ключей нет»: аннотация заводила клиента вообще без хранилища, и он
    искал ключ в старом одиночном поле настроек, которое список очищает.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parent.parent
                      / "webapp" / "app.py").read_text(encoding="utf-8")

    def test_the_client_is_built_in_exactly_one_place(self):
        """Одна точка сборки — единственный способ ничего не забыть."""
        self.assertEqual(self.source.count("LlmClient("), 1)

    def test_that_place_is_the_factory(self):
        maker = self.source.split("def _llm_client", 1)[1].split("\n@app.", 1)[0]
        self.assertIn("LlmClient(", maker)
        self.assertIn("keystore", maker)

    def test_the_factory_works_without_a_request_body(self):
        """Пересказ и перевод зовут её без полей формы."""
        self.assertIn("def _llm_client(payload: dict | None = None",
                      self.source)
        self.assertIn("payload = payload or {}", self.source)

    def test_every_route_goes_through_it(self):
        for route in ("api_rank_translate", "api_retell_annotation"):
            with self.subTest(route=route):
                body = self.source.split(f"def {route}", 1)[1]
                body = body.split("\n@app.", 1)[0]
                self.assertIn("_llm_client(", body)

    def test_the_store_itself_is_a_single_object(self):
        """Модульный singleton: два хранилища разошлись бы молча."""
        from llm import keys as keys_mod

        self.assertIsInstance(keys_mod.store, keys_mod.KeyStore)
        import webapp.app as web

        self.assertIs(web.keystore, keys_mod.store)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class _Answer:
    """Ответ модели: код и тело, как их видит клиент."""

    def __init__(self, status: int, body: dict | None = None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


class _Http:
    """Клиент, который всегда отдаёт один и тот же ответ."""

    def __init__(self, answer):
        self.answer = answer
        self.asked = 0

    def get(self, url, params=None):
        self.asked += 1
        return self.answer


class TestARejectedKeyIsNotAProxyProblem(KeysBase):
    """Ключ отклонён Google — адреса тут ни при чём.

    Проверка выше подменяла `_once` целиком и потому доказывала только
    половину: что `_request` умеет остановиться на `BadKey`. А сам стык —
    превращается ли настоящий 401 в `BadKey` — не проверялся ничем, и
    там и жила поломка. Транспорт бросал исключение раньше разбора, тело
    ответа выбрасывалось не читая, и отказ ключа шёл как молчание
    прокси: программа обходила все четырнадцать адресов и две минуты
    спустя говорила о них, а не о ключе.
    """

    def setUp(self):
        super().setUp()
        self.said: list[str] = []

    def client(self, key=KEY_A, pool=None):
        return LlmClient(key=key, pool=pool, on_event=self.said.append)

    def ask(self, answer, key=KEY_A):
        return self.client(key)._once(_Http(answer), "https://x/models", None)

    def test_a_401_is_a_bad_key(self):
        with self.assertRaises(BadKey):
            self.ask(_Answer(401))

    def test_a_403_is_a_bad_key_too(self):
        with self.assertRaises(BadKey):
            self.ask(_Answer(403))

    def test_the_answer_says_the_address_will_not_help(self):
        """Иначе человек ищет беду в списке прокси, а она в ключе."""
        with self.assertRaises(BadKey) as caught:
            self.ask(_Answer(401))
        self.assertIn("адреса", str(caught.exception))

    def test_googles_own_words_reach_the_person(self):
        answer = _Answer(403, {"error": {"message": "API key not valid"}})
        with self.assertRaises(BadKey) as caught:
            self.ask(answer)
        self.assertIn("API key not valid", str(caught.exception))

    def test_a_rejected_key_stops_the_tour_of_addresses(self):
        """Тот самый обход четырнадцати адресов на две минуты."""
        client = self.client(pool=_Pool([Proxy(host="10.0.0.1", port=8080),
                                         Proxy(host="10.0.0.2", port=8080)]))
        client._http = lambda url: _Http(_Answer(401))
        with self.assertRaises(BadKey):
            client._request("models")
        went = [line for line in self.said if line.startswith("запрос к модели")]
        self.assertEqual(len(went), 1)

    def test_a_spent_quota_is_told_from_a_dead_address(self):
        with self.assertRaises(QuotaSpent):
            self.ask(_Answer(429))

    def test_a_400_about_the_key_is_a_bad_key(self):
        answer = _Answer(400, {"error": {"message": "API key not valid."}})
        with self.assertRaises(BadKey):
            self.ask(answer)

    def test_a_good_answer_still_comes_through(self):
        body = {"models": [{"name": "models/gemini-x"}]}
        self.assertEqual(self.ask(_Answer(200, body)), body)


class TestTheDownloaderIsNotTouched(unittest.TestCase):
    """Послабление для модели не должно менять качалку."""

    def test_by_default_nothing_is_passed_through(self):
        from mvl.client import Client

        self.assertEqual(Client.pass_statuses, frozenset())

    def test_the_model_client_asks_for_the_body(self):
        from llm.client import MODEL_ANSWERS, _model_client

        client = _model_client(max_attempts=1)
        self.addCleanup(client.close)
        self.assertEqual(client.pass_statuses, MODEL_ANSWERS)


class TestTheAnswerReachesTheParser(unittest.TestCase):
    """Настоящий 401 должен доехать до разбора, а не оборваться в пути.

    Проверки выше подсовывают готовый ответ и потому доказывают только,
    что разбор умеет его читать. Здесь ответ идёт через настоящий
    клиент — тот самый, который раньше бросал исключение, не дав разбору
    ни тела, ни возможности отличить плохой ключ от молчания прокси.
    """

    def serve(self, status: int, body: bytes):
        import json as _json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — имя задано библиотекой
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def answer(self, status: int, body: dict):
        import json as _json

        from llm.client import _model_client

        base = self.serve(status, _json.dumps(body).encode("utf-8"))
        client = _model_client(max_attempts=1)
        self.addCleanup(client.close)
        return LlmClient(key=KEY_A)._once(client, f"{base}/models", None)

    def test_a_real_401_becomes_a_bad_key(self):
        with self.assertRaises(BadKey) as caught:
            self.answer(401, {"error": {"message": "API key not valid"}})
        self.assertIn("API key not valid", str(caught.exception))

    def test_a_real_429_becomes_a_spent_quota(self):
        with self.assertRaises(QuotaSpent):
            self.answer(429, {"error": {"message": "Quota exceeded"}})

    def test_a_real_200_comes_back_whole(self):
        body = {"models": [{"name": "models/gemini-x"}]}
        self.assertEqual(self.answer(200, body), body)

    def test_a_status_nobody_asked_for_still_raises(self):
        """Послабление узкое: 500 как был отказом, так и остался."""
        with self.assertRaises(Exception) as caught:
            self.answer(500, {"error": {"message": "server is sad"}})
        self.assertNotIsInstance(caught.exception, BadKey)


class TestTheModelTakesTheCheckedAddressesFirst(KeysBase):
    """Проверка кнопкой должна значить что-то и для модели.

    Отсеивался только `disabled`, а его ставит одна лишь неудача на
    ходу. Проверка кнопкой помечает иначе — через `alive` и `status`, —
    и запрос к модели шёл по файлу сверху: сначала в адрес, который не
    пустил по паролю, потом в тот, что молчит пятнадцать секунд. Человек
    при этом видел в качалке восемь проверенных рабочих.
    """

    def setUp(self):
        super().setUp()
        self._use = settings.llm.use_proxies
        self.addCleanup(lambda: setattr(settings.llm, "use_proxies", self._use))
        settings.llm.use_proxies = True

    def proxy(self, host, alive=None, status=0):
        found = Proxy(host=host, port=8080)
        found.alive = alive
        found.status = status
        return found

    def route(self, *proxies):
        client = LlmClient(key=KEY_A, pool=_Pool(list(proxies)))
        return [label for _, label in client._proxies()]

    def test_a_checked_address_goes_before_an_unchecked_one(self):
        dead = self.proxy("10.0.0.1", alive=False)
        good = self.proxy("10.0.0.2", alive=True, status=200)
        self.assertEqual(self.route(dead, good)[0], "10.0.0.2:8080")

    def test_the_one_that_failed_the_check_is_not_thrown_away(self):
        """Проверка могла быть давней, а адрес — ожить."""
        dead = self.proxy("10.0.0.1", alive=False)
        good = self.proxy("10.0.0.2", alive=True, status=200)
        self.assertEqual(len(self.route(dead, good)), 2)

    def test_unchecked_addresses_still_work(self):
        """Кнопку не нажимали — пригодных нет ни одного, и это не отказ."""
        self.assertEqual(len(self.route(self.proxy("10.0.0.1"),
                                        self.proxy("10.0.0.2"))), 2)

    def test_an_address_that_failed_on_the_run_is_skipped(self):
        good = self.proxy("10.0.0.2", alive=True, status=200)
        gone = self.proxy("10.0.0.1", alive=True, status=200)
        gone.disabled = True
        self.assertEqual(self.route(gone, good), ["10.0.0.2:8080"])

    def test_the_model_and_the_downloader_agree_on_the_order(self):
        """Два разных порядка однажды разойдутся, и объяснить это будет
        нечем: адреса-то одни и те же."""
        from mvl.proxies import working_proxies

        dead = self.proxy("10.0.0.1", alive=False)
        good = self.proxy("10.0.0.2", alive=True, status=200)
        pool = _Pool([dead, good])
        theirs = [p.label for p in working_proxies(pool)]
        mine = [label for _, label in
                LlmClient(key=KEY_A, pool=pool)._proxies()]
        self.assertEqual(mine, theirs)


class TestTheFailureSaysWhatTheNumberMeans(KeysBase):
    """«Ни через один из 14» человек прочитал как «14 ключей».

    Рядом в журнале стоит имя проверяемого ключа, и без уточнения две
    строки склеиваются в одну мысль: «ключей не хватило». На деле число
    про посредников, а ключ проверяется ровно один — текущий.
    """

    def setUp(self):
        super().setUp()
        self._use = settings.llm.use_proxies
        self.addCleanup(lambda: setattr(settings.llm, "use_proxies", self._use))
        settings.llm.use_proxies = True

    def test_the_number_is_named_as_addresses_not_keys(self):
        client = LlmClient(key=KEY_A,
                           pool=_Pool([Proxy(host="10.0.0.1", port=8080),
                                       Proxy(host="10.0.0.2", port=8080)]))
        client._http = lambda url: None
        client._once = _refuse
        with self.assertRaises(LlmError) as caught:
            client._request("models")
        said = str(caught.exception)
        self.assertIn("посредник", said)
        self.assertNotIn("ключ", said.lower())

    def test_going_straight_names_no_number_at_all(self):
        client = LlmClient(key=KEY_A)
        client._http = lambda url: None
        client._once = _refuse
        with self.assertRaises(LlmError) as caught:
            client._request("models")
        self.assertIn("напрямую", str(caught.exception))


class TestSeveralKeysPastedAtOnce(KeysBase):
    """Поле ключа многострочное, и вставка списком — обычное дело.

    Кнопка «Добавить» это умела, а «Проверить» — нет: она брала весь
    текст поля за один ключ и отправляла пятьдесят строк в поле `key`.
    Google на такое отвечает «ключа нет вовсе», а в подписи к отказу
    оказывалось начало первого ключа и конец последнего. С одним ключом
    всё работало, с несколькими — ничего.
    """

    def test_lines_come_apart(self):
        self.assertEqual(keys_mod.split_keys(f"{KEY_A}\n{KEY_B}"),
                         [KEY_A, KEY_B])

    def test_commas_come_apart_too(self):
        self.assertEqual(keys_mod.split_keys(f"{KEY_A}, {KEY_B}"),
                         [KEY_A, KEY_B])

    def test_the_same_key_twice_is_one_key(self):
        self.assertEqual(keys_mod.split_keys(f"{KEY_A}\n{KEY_A}"), [KEY_A])

    def test_empty_lines_are_not_keys(self):
        self.assertEqual(keys_mod.split_keys(f"\n\n{KEY_A}\n  \n"), [KEY_A])

    def test_the_first_of_many_is_the_one_checked(self):
        self.assertEqual(keys_mod.first_key(f"{KEY_A}\n{KEY_B}"), KEY_A)

    def test_one_key_is_taken_whole(self):
        """Обычный случай ломать нельзя: он и работал."""
        self.assertEqual(keys_mod.first_key(KEY_A), KEY_A)

    def test_nothing_pasted_means_no_key(self):
        self.assertEqual(keys_mod.first_key("   "), "")

    def test_the_check_does_not_glue_the_keys_together(self):
        """То самое склеивание: в `key` уходил весь текст поля."""
        from webapp import app as web

        client = web._llm_client({"key": f"{KEY_A}\n{KEY_B}"})
        self.assertEqual(client.key, KEY_A)
        self.assertNotIn("\n", client.key)

    def test_adding_and_checking_split_the_text_the_same_way(self):
        """Два разбора однажды разойдутся, и объяснить это будет нечем."""
        text = f"{KEY_A},{KEY_B}"
        self.store.add(text)
        stored = [k.key for k in self.store.all()]
        self.assertEqual(stored, keys_mod.split_keys(text))


class TestTheFastestAddressGoesFirst(KeysBase):
    """Время ответа замеряет та же кнопка «Проверить» — им и пользуемся.

    Проверенные адреса шли по порядку в файле, и первым брался не самый
    быстрый, а тот, что вставили раньше других.
    """

    def setUp(self):
        super().setUp()
        self._use = settings.llm.use_proxies
        self.addCleanup(lambda: setattr(settings.llm, "use_proxies", self._use))
        settings.llm.use_proxies = True

    def proxy(self, host, elapsed=None, alive=True, status=200):
        found = Proxy(host=host, port=8080)
        found.alive = alive
        found.status = status
        found.elapsed = elapsed
        return found

    def route(self, *proxies):
        client = LlmClient(key=KEY_A, pool=_Pool(list(proxies)))
        return [label for _, label in client._proxies()]

    def test_the_quick_one_overtakes_the_slow_one(self):
        slow = self.proxy("10.0.0.1", elapsed=9.0)
        quick = self.proxy("10.0.0.2", elapsed=0.4)
        self.assertEqual(self.route(slow, quick)[0], "10.0.0.2:8080")

    def test_an_address_without_a_measure_waits_its_turn(self):
        """Не замерен — не значит быстрый."""
        quick = self.proxy("10.0.0.2", elapsed=0.4)
        unknown = self.proxy("10.0.0.1", elapsed=None)
        self.assertEqual(self.route(unknown, quick)[0], "10.0.0.2:8080")

    def test_the_unchecked_still_come_after_the_checked(self):
        """Скорость важна среди пригодных, а не вместо пригодности."""
        good = self.proxy("10.0.0.2", elapsed=9.0)
        dead = self.proxy("10.0.0.1", alive=False, status=0, elapsed=0.1)
        self.assertEqual(self.route(dead, good)[0], "10.0.0.2:8080")
