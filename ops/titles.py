"""Перевод названий и описаний из рейтинга (5.3, 3.1 ТЗ NEUROSTRAZH).

Список на китайском бесполезен: по нему не понять, о чём книга, а значит
и незачем смотреть рейтинг. Перевод делает модуль из части 2.

Кэш по `book_id`, а не по тексту: идентификатор у книги один и навсегда, а
название и описание на сайте иногда правят — и перевод из-за одной
поправленной запятой запрашивался бы заново.

Описания живут в своём файле: названий полсотни на срез и они короткие, а
описание — абзац.

Раньше описания переводились строго по одному, по кнопке: полсотни
отдельных запросов на срез — слишком дорого ради «вдруг откроют».
Возражение было про запрос на описание, а не про перевод как таковой:
пачкой по шесть те же полсотни укладываются в девять запросов, и кнопка
«перевести всё» перестала быть разорительной. Перевод по одному никуда
не делся — он остался для раскрытой строки.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass

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

#: Сколько описаний отдавать модели за раз.
#:
#: Описание — абзац, а не строка: двадцать пять абзацев в одном запросе
#: модель обрывает на середине. Шесть проходят целиком, и полсотни
#: описаний укладываются в девять запросов вместо полусотни.
ABOUT_BATCH = 6

ABOUTS_PROMPT = """Ниже описания книг с китайских сайтов, каждое под своим
номером и отделено строкой ---.

Переведи каждое на русский. Верни СТРОГО JSON: объект, где ключ — номер
описания, значение — перевод целиком. Без пояснений и без текста вокруг.

Переводи по смыслу, а не пословно. Имена собственные передавай так, как
их принято передавать по-русски.

{lines}"""


@dataclass(frozen=True)
class Kind:
    """Что переводим.

    У названий и описаний разное всё, кроме главного: их одинаково
    спрашивают пачкой, одинаково разбирают ответ и одинаково дробят
    пачку, когда ответ не разобрался. Держать эту механику двумя копиями
    значило бы чинить её дважды — а чинилась она уже трижды.
    """

    prompt: str
    size: int
    word: str
    #: Чем разделять строки в запросе. Названия — по строке на каждое,
    #: описания — абзацами, и без разделителя они слипаются в одно.
    joiner: str = "\n"


HEADINGS_PROMPT = """Ниже названия глав книги, по одному в строке, с
номерами.

Переведи каждое на русский. Верни СТРОГО JSON: объект, где ключ — номер
строки, значение — перевод. Без пояснений и без текста вокруг.

Это названия глав художественной книги: переводи по смыслу, коротко, как
принято называть главы. Слово «глава» и номер главы в перевод НЕ
добавляй — они подставляются отдельно.
{hint}
{lines}"""

TITLES = Kind(prompt=PROMPT, size=BATCH, word="Названия")
ABOUTS = Kind(prompt=ABOUTS_PROMPT, size=ABOUT_BATCH, word="Описания",
              joiner="\n---\n")
HEADINGS = Kind(prompt=HEADINGS_PROMPT, size=BATCH, word="Заголовки")

#: Переводы названий глав. Отдельно от рейтинга: там ключ — код книги на
#: сайте, а здесь само название, потому что никакого кода у главы нет.
HEADINGS_FILE = DATA_DIR / "headings.json"

#: Словарь имён собственных: как писать по-русски. Заголовки идут пачками
#: по двадцать пять, каждая пачка — свой запрос, и модель не помнит, как
#: назвала героя в прошлой. Отсюда «Ли Сяо» в одной главе и «Ли Сяон» в
#: соседней. Словарь даётся модели вместе с пачкой.
NAMES_FILE = DATA_DIR / "names.json"

#: Сколько пар давать модели за раз. Словарь бывает на сотни имён, а в
#: пачке двадцать пять коротких заголовков: отправлять весь список к
#: каждой — платить за него сотню раз. Берём только те, что в этой пачке
#: и встречаются, а этот предел — страховка от книги, где в заголовках
#: одни имена.
NAMES_IN_PROMPT = 40


@dataclass(frozen=True)
class Line:
    """Одна строка запроса: чья она и что переводим."""

    book_id: str
    text: str


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
    for index, line in enumerate(batch, 1):
        text = _said(found, index, line.text)
        if text:
            out[index] = text
    return out


def _ask(client, batch: list, model: str, kind: Kind = TITLES) -> dict:
    """Перевод одной пачки: book_id → перевод. Чего нет — то не далось.

    Порядок такой: спросить, при неразборчивом ответе спросить ещё раз,
    и только потом делить пачку пополам. Половина отвечает лучше целого,
    а полученное по дороге не теряется.
    """
    if not batch:
        return {}

    lines = kind.joiner.join(f"{i}. {line.text}"
                             for i, line in enumerate(batch, 1))
    # Словарь имён — только у заголовков и только по тем именам, что в
    # этой пачке встречаются. Остальным видам он не нужен: у прочих
    # запросов в шаблоне и места для него нет, а лишний довод `format`
    # молча пропускает.
    hint = hint_for([line.text for line in batch]) if kind is HEADINGS else ""
    for attempt in range(1, TRIES + 1):
        answer = client.generate(kind.prompt.format(lines=lines, hint=hint),
                                 model=model)
        found = _read(answer, batch)
        if found:
            got = {batch[index - 1].book_id: text
                   for index, text in found.items()}
            left = [line for line in batch if line.book_id not in got]
            if left:
                # Ответ разобрался, но не на все строки. Остаток — своей
                # пачкой: он меньше, и шансов у него больше.
                log.info("%s: в ответе не нашлось %s из %s — "
                         "спрашиваем остаток отдельно", kind.word, len(left),
                         len(batch))
                # Остаток строго меньше пачки: сюда мы попадаем, только
                # если хоть одна строка перевелась.
                got.update(_ask(client, left, model, kind))
            return got
        log.warning("%s: ответ модели не разобрался "
                    "(попытка %s из %s, в пачке %s)", kind.word, attempt,
                    TRIES, len(batch))

    if len(batch) <= SMALLEST:
        return {}

    half = len(batch) // 2
    out = _ask(client, batch[:half], model, kind)
    out.update(_ask(client, batch[half:], model, kind))
    return out


def _run(lines: list, client, model: str, kind: Kind) -> dict:
    """Прогнать готовые строки пачками. Общее для названий и описаний."""
    added = {}
    for start in range(0, len(lines), kind.size):
        added.update(_ask(client, lines[start:start + kind.size], model, kind))
    return added


def translate(rows, client, model: str = "", force: bool = False) -> dict:
    """Переводит названия строк рейтинга. Переведённые не перезапрашивает."""
    have = known()
    todo = [Line(row.book_id, row.name) for row in rows
            if row.book_id and (force or row.book_id not in have)]

    added = _run(todo, client, model, TITLES)
    if added:
        have = remember(added)

    titles = {row.book_id: have.get(row.book_id, "") for row in rows}
    # «Не перевелось» считаем по строкам, а не по пачкам: человеку важно,
    # сколько названий осталось китайскими, а на сколько запросов они были
    # разложены — наше внутреннее дело.
    missing = [line.text for line in todo if not titles.get(line.book_id)]
    return {"titles": titles,
            "translated": len(added), "broken": len(missing),
            "missing": missing[:10],
            "cached": len(rows) - len(added) - len(missing)}


def headings() -> dict:
    """Что уже переведено: название главы → перевод."""
    with _LOCK:
        return dict(_load(HEADINGS_FILE))


def remember_headings(pairs: dict) -> dict:
    with _LOCK:
        data = _load(HEADINGS_FILE)
        data.update({str(k): str(v).strip() for k, v in pairs.items()
                     if str(v).strip()})
        _write(HEADINGS_FILE, data)
        return dict(data)


def forget_headings() -> None:
    with _LOCK:
        _write(HEADINGS_FILE, {})


# ------------------------------------------- словарь имён собственных


def spellings() -> dict:
    """Как писать имена: оригинал → русское написание.

    Не `names`: так зовётся список заголовков в самом переводе, и одно
    имя на две разные вещи однажды выстрелит.
    """
    with _LOCK:
        return dict(_load(NAMES_FILE))


def remember_spellings(pairs) -> dict:
    """Дописывает пары в словарь.

    Принимает и готовый словарь, и список пар — глоссарий от переводчика
    приходит парами, а разбирает их `ops/glossary`, который умеет и
    `=`, и стрелку, и CSV, и JSON.
    """
    rows = pairs.items() if isinstance(pairs, dict) else (pairs or ())
    with _LOCK:
        data = _load(NAMES_FILE)
        for key, value in rows:
            key, value = str(key or "").strip(), str(value or "").strip()
            if key and value:
                data[key] = value
        _write(NAMES_FILE, data)
        return dict(data)


def forget_spellings() -> None:
    with _LOCK:
        _write(NAMES_FILE, {})


def hint_for(texts, table: dict | None = None) -> str:
    """Кусок запроса со словарём — только по тем именам, что здесь есть.

    Словарь бывает на сотни имён, а в пачке двадцать пять коротких
    заголовков. Отправлять весь список к каждой пачке — платить за него
    сотню раз, а квота у ключей суточная.

    Имя ищется в тексте как есть, без учёта регистра: заголовки приходят
    и «LI XIAO», и «Li Xiao».
    """
    table = spellings() if table is None else table
    if not table:
        return ""

    where = "\n".join(str(one or "") for one in texts).lower()
    found = [(key, value) for key, value in table.items()
             if str(key).lower() in where]
    if not found:
        return ""

    found.sort(key=lambda pair: len(pair[0]), reverse=True)
    rows = "\n".join(f"{key} = {value}"
                     for key, value in found[:NAMES_IN_PROMPT])
    return ("\nИмена собственные пиши строго так — это уже принятые в этой\n"
            "книге написания, менять их нельзя:\n" + rows + "\n")


def translate_headings(names, client, model: str = "",
                       force: bool = False, on_step=None) -> dict:
    """Переводит названия глав пачками. Кэш — по самому названию.

    Кэш здесь важнее, чем в рейтинге: глав бывает полторы тысячи, и
    оборвись работа на середине — без него второй заход начинался бы с
    нуля и стоил бы столько же, сколько первый.

    Ключ — само название, а не номер главы: у главы номер свой, а имя
    может повторяться, и переводить «Trade» дважды незачем.
    """
    names = [str(x or "").strip() for x in (names or [])]
    have = headings()

    # Заголовок, целиком совпавший со словарной статьёй, не спрашиваем
    # вовсе: написание уже принято человеком, и переспрашивать модель —
    # платить за ответ, который мы и так знаем, да ещё рискуя получить
    # другой. Квота у ключей суточная, и это не мелочь.
    table = spellings()
    straight = {name: table[name] for name in names if name in table}

    todo, seen = [], set()
    for name in names:
        if not name or name in seen or name in straight:
            continue
        if force or name not in have:
            seen.add(name)
            todo.append(Line(name, name))

    added = {}
    for start in range(0, len(todo), HEADINGS.size):
        added.update(_ask(client, todo[start:start + HEADINGS.size], model,
                          HEADINGS))
        if on_step:
            on_step(min(start + HEADINGS.size, len(todo)), len(todo))
    if added:
        have = remember_headings(added)

    # Словарное написание важнее и кэша, и свежего ответа модели: его
    # выбрал человек, и переубеждать его нам нечем.
    ready = {name: straight.get(name) or have.get(name, "")
             for name in names if name}
    missing = [line.text for line in todo if not ready.get(line.book_id)]
    return {"names": ready,
            "translated": len(added), "broken": len(missing),
            "missing": missing[:10],
            # Взятое из словаря — не перевод и не кэш: за него не платили
            # вовсе, и складывать его с кэшем значило бы прятать, сколько
            # словарь сберёг.
            "from_glossary": len(straight),
            "cached": len(set(names)) - len(added) - len(missing)
                      - len(straight)}


def translate_all_abstracts(texts: dict, client, model: str = "",
                            force: bool = False) -> dict:
    """Переводит описания пачками: `book_id` → описание на языке сайта.

    Берёт готовые тексты, а не строки рейтинга: описание у Цидяня лежит
    прямо в строке доски, у остальных сайтов — в кэше раскрытой карточки,
    и знать про оба места этому модулю незачем.
    """
    have = abstracts()
    todo = [Line(str(book_id), str(text).strip())
            for book_id, text in (texts or {}).items()
            if str(book_id) and str(text).strip()
            and (force or str(book_id) not in have)]

    added = _run(todo, client, model, ABOUTS)
    if added:
        with _LOCK:
            data = _load(ABSTRACTS_FILE)
            data.update({str(k): str(v).strip() for k, v in added.items()
                         if str(v).strip()})
            _write(ABSTRACTS_FILE, data)
            have = dict(data)

    ready = {book_id: have.get(str(book_id), "") for book_id in (texts or {})}
    missing = [line.book_id for line in todo if not ready.get(line.book_id)]
    return {"abstracts": ready,
            "translated": len(added), "broken": len(missing),
            "missing": missing[:10],
            "cached": len(texts or {}) - len(added) - len(missing)}
