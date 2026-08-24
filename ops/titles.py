"""Перевод названий и описаний из рейтинга (5.3, 3.1 ТЗ NEUROSTRAZH).

Список на китайском бесполезен: по нему не понять, о чём книга, а значит
и незачем смотреть рейтинг. Перевод делает модуль из части 2.

Кэш по `book_id`, а не по тексту: идентификатор у книги один и навсегда, а
название и описание на сайте иногда правят — и перевод из-за одной
поправленной запятой запрашивался бы заново.

Описания живут в своём файле: названий полсотни на срез и они короткие, а
описание — абзац, и переводится оно по одному, по кнопке.
"""

from __future__ import annotations

import json
import logging
import threading

from .history import DATA_DIR

log = logging.getLogger(__name__)

TITLES_FILE = DATA_DIR / "titles.json"
ABSTRACTS_FILE = DATA_DIR / "abstracts.json"

#: Сколько названий отдавать модели за раз. Полсотни коротких строк —
#: один дешёвый запрос вместо полусотни дорогих.
BATCH = 25

#: Сколько раз спрашивать одну и ту же пачку, если ответ не разобрался.
#:
#: Модель отвечает по-разному на один и тот же запрос: там, где она один
#: раз обернула JSON в пояснения или оборвалась на середине, со второго
#: захода обычно отвечает как просили. Раньше пачка просто пропадала — и
#: пропадала целиком, двадцать пять названий разом.
TRIES = 2

#: Мельче этого пачку не дробим.
#:
#: Не разобралась пачка и со второго раза — делим пополам: у половины
#: шансов больше, а терять из-за одного упрямого названия остальные
#: двадцать четыре незачем. Дробить до одной строки, однако, нельзя:
#: двадцать пять названий превратились бы в полсотни запросов, а перевод
#: рейтинга — удобство, а не работа программы.
SMALLEST = 5

PROMPT = """Ниже список названий книг на китайском, по одному в строке, с
номерами.

Переведи каждое на русский. Верни СТРОГО JSON: объект, где ключ — номер
строки, значение — перевод. Без пояснений и без текста вокруг.

Названия художественные: переводи по смыслу, а не пословно. Имена
собственные передавай так, как их принято передавать по-русски.

{lines}"""

ABSTRACT_PROMPT = """Ниже описание книги с китайского сайта.

Переведи его на русский. Верни только перевод: ни пояснений, ни исходного
текста, ни кавычек вокруг. Разбиение на абзацы сохрани.

{text}"""

_LOCK = threading.Lock()


def _load(path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("Битый кэш переводов (%s) — начинаем заново", path.name)
        return {}
    return data if isinstance(data, dict) else {}


def _write(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


def known() -> dict:
    """Что уже переведено: book_id → перевод названия."""
    with _LOCK:
        return dict(_load(TITLES_FILE))


def remember(pairs: dict) -> dict:
    with _LOCK:
        data = _load(TITLES_FILE)
        data.update({str(k): str(v) for k, v in pairs.items() if str(v).strip()})
        _write(TITLES_FILE, data)
        return dict(data)


def forget() -> None:
    with _LOCK:
        _write(TITLES_FILE, {})


def abstracts() -> dict:
    """Переводы описаний: book_id → перевод."""
    with _LOCK:
        return dict(_load(ABSTRACTS_FILE))


def abstract_of(book_id) -> str:
    """Перевод описания одной книги. Пусто — ещё не переводили."""
    return abstracts().get(str(book_id), "")


def remember_abstract(book_id, text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    with _LOCK:
        data = _load(ABSTRACTS_FILE)
        data[str(book_id)] = text
        _write(ABSTRACTS_FILE, data)
    return text


def forget_abstracts() -> None:
    with _LOCK:
        _write(ABSTRACTS_FILE, {})


def translate_abstract(book_id, text: str, client, model: str = "",
                       force: bool = False) -> str:
    """Перевод описания книги. Переведённое не перезапрашивает (3.1 ТЗ).

    Описание переводится по одному и по кнопке: их полсотни на срез, а
    читают из них два-три. Гнать все в модель ради «вдруг откроют» — это
    полсотни лишних запросов на каждый снятый рейтинг.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Описания у книги нет — переводить нечего.")

    if not force:
        have = abstract_of(book_id)
        if have:
            return have

    answer = (client.generate(ABSTRACT_PROMPT.format(text=text),
                              json_only=False, model=model) or "").strip()
    if not answer:
        raise ValueError("Модель вернула пустой ответ.")
    return remember_abstract(book_id, answer)


def _said(found, index: int, name: str) -> str:
    """Перевод одной строки из ответа модели.

    Просили ключ — номер строки, но модель обходится с этим вольно:
    пишет `"1."`, кладёт число вместо строки, а то и вовсе берёт ключом
    само китайское название. Всё это — тот же ответ, и отказываться от
    него из-за формы ключа значит выбрасывать готовый перевод.
    """
    for key in (str(index), index, f"{index}.", name):
        try:
            value = found.get(key)
        except TypeError:      # ключ не годится в словарь — не беда
            continue
        if isinstance(value, dict):
            # {"1": {"ru": "…"}} — тоже встречается.
            value = next((v for v in value.values() if isinstance(v, str)), "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _read(answer: str, batch: list) -> dict:
    """Разбор ответа на пачку: номер строки → перевод.

    Пусто — ответ не разобрался вовсе. Список модель возвращает не реже
    объекта, хотя её просили об объекте: тогда читаем по порядку строк.
    """
    from llm.cache import parse_json

    try:
        found = parse_json(answer)
    except ValueError:
        found = None

    if found is None:
        try:
            found = json.loads((answer or "").strip())
        except ValueError:
            return {}
        if isinstance(found, list):
            # Порядок — единственное, что связывает такой ответ со
            # строками. Он годится, только если длина сошлась: короче
            # список — и переводы съедут на чужие книги.
            if len(found) != len(batch):
                return {}
            found = {str(i): v for i, v in enumerate(found, 1)}
        if not isinstance(found, dict):
            return {}

    out = {}
    for index, row in enumerate(batch, 1):
        text = _said(found, index, row.name)
        if text:
            out[index] = text
    return out


def _ask(client, batch: list, model: str) -> dict:
    """Перевод одной пачки: book_id → перевод. Чего нет — то не далось.

    Порядок такой: спросить, при неразборчивом ответе спросить ещё раз,
    и только потом делить пачку пополам. Половина отвечает лучше целого,
    а полученное по дороге не теряется.
    """
    if not batch:
        return {}

    lines = "\n".join(f"{i}. {row.name}" for i, row in enumerate(batch, 1))
    for attempt in range(1, TRIES + 1):
        answer = client.generate(PROMPT.format(lines=lines), model=model)
        found = _read(answer, batch)
        if found:
            got = {batch[index - 1].book_id: text
                   for index, text in found.items()}
            left = [row for row in batch if row.book_id not in got]
            if left:
                # Ответ разобрался, но не на все строки. Остаток — своей
                # пачкой: он меньше, и шансов у него больше.
                log.info("Названия: в ответе не нашлось %s из %s — "
                         "спрашиваем остаток отдельно", len(left), len(batch))
                # Остаток строго меньше пачки: сюда мы попадаем, только
                # если хоть одна строка перевелась.
                got.update(_ask(client, left, model))
            return got
        log.warning("Названия: ответ модели не разобрался "
                    "(попытка %s из %s, в пачке %s)", attempt, TRIES,
                    len(batch))

    if len(batch) <= SMALLEST:
        return {}

    half = len(batch) // 2
    out = _ask(client, batch[:half], model)
    out.update(_ask(client, batch[half:], model))
    return out


def translate(rows, client, model: str = "", force: bool = False) -> dict:
    """Переводит названия строк рейтинга. Переведённые не перезапрашивает."""
    have = known()
    todo = [row for row in rows
            if row.book_id and (force or row.book_id not in have)]

    added = {}
    for start in range(0, len(todo), BATCH):
        added.update(_ask(client, todo[start:start + BATCH], model))

    if added:
        have = remember(added)

    titles = {row.book_id: have.get(row.book_id, "") for row in rows}
    # «Не перевелось» считаем по строкам, а не по пачкам: человеку важно,
    # сколько названий осталось китайскими, а на сколько запросов они были
    # разложены — наше внутреннее дело.
    missing = [row.name for row in todo if not titles.get(row.book_id)]
    return {"titles": titles,
            "translated": len(added), "broken": len(missing),
            "missing": missing[:10],
            "cached": len(rows) - len(added) - len(missing)}
