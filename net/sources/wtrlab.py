"""WTR-LAB: книга приходит уже переведённой на английский.

Это тот же размен, что у RanobeLIB и Dreamy, — чужой перевод вместо
своего.

**Переводов у сайта три**, и над текстом стоит переключатель: «Web»,
«Web+» и «AI». Берём обычный «Web»: он лежит готовым у каждой главы и
достаётся сразу. «AI» — машина, которая переводит по запросу: главы там
открываются поштучно, часть за самоцветы, и книга оттуда идёт часами.
WebToEpub просит именно «ai» — ему нужен перевод получше; нам нужен тот,
который есть у всех глав.

Как называется выбранный перевод, сайт пишет в адрес страницы
(`?service=web`) и в её начинку (`active_service`), а в запросе за
главой то же слово уходит полем `translate`. Поэтому выбор здесь не
настройка программы, а часть ссылки: человек копирует адрес с той
страницы, где читает, и выбор уже сделан там, где его видно.

**Откуда что берётся.** Страница книги собрана на Next.js: вся её начинка
лежит в теге `<script id="__NEXT_DATA__">` одним куском JSON — название,
автор, обложка, число глав. Разбирать вёрстку незачем, да и нечего:
оглавление в неё вообще не попадает, список глав рисуется уже в браузере.
Он приходит отдельным запросом, `GET /api/chapters/{код}`, и это
единственный способ увидеть книгу целиком.

**Текст главы приходит не страницей.** За ним ходят POST-запросом на
`/api/reader/get`, и в ответе не разметка, а список абзацев. Имена в них
заменены метками вида `※7⛬`, а сами имена лежат рядом, в словаре главы.
Не подставить их значит положить в книгу текст, где вместо каждого имени
стоит закорючка с номером, — и заметить это можно только прочитав.

**Пауза между главами зависит от перевода.** У «Web» текст уже лежит, и
торопить нечего — хватает общей паузы витрины. У «AI» сервер переводит
главу в момент запроса и на частые запросы отвечает пустой главой или
проверкой «вы не робот»; со стороны это выглядит как рваная книга, хотя
сайт просто просит не частить. Там ставится двенадцать секунд — та
величина, на которой это работает у WebToEpub, — и книга на восемьсот
глав идёт часами. Ставится она в `_remember`, при разборе адреса: до
него неизвестно, какой перевод спрашивают, а разница между ними — те
самые часы.

**Чего здесь нет.** У сайта есть ещё два словаря: личный, из настроек
пользователя, и общий на книгу. Оба нужны только чтобы **перебить** имена,
уже подставленные в главу, и оба требуют входа под своей учётной записью.
Мы не входим никуда, поэтому берём то, что сайт кладёт в саму главу.

Откуда правила разбора: расширение `dteviot/WebToEpub` (GPL-3.0). Взяты
адреса запросов, вид тела и имена полей ответа — то, что снаружи не
угадать. См. README.

**Живьём не проверено.** Сайт закрыт для среды, в которой писался модуль
(прокси отвечает 403). Разбор проверен на настоящей странице книги,
сохранённой человеком, и на ответах, собранных по описанию полей.
Устроен он так, чтобы молчаливой полукниги не вышло: не нашлось начинки
страницы, списка глав или текста — модуль говорит «источник изменился» и
прикладывает ответ, а не отдаёт пустоту.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import parse_qs, urlparse

from .base import Chapter, Novel, Source, SourceBroken, Toc

log = logging.getLogger(__name__)

#: Витрина. Она же `Referer` для запросов глав.
SITE = "https://wtr-lab.com"

#: Адрес книги: `/en/novel/8093/the-wizard-is-chasing-the-truth`.
#: Ловится и из адреса главы — у неё те же три куска и `chapter-N` в
#: конце. Человек приносит то, что у него открыто, а открыта у него чаще
#: глава.
BOOK_PATH = re.compile(
    r"/(?P<lang>[a-z]{2})/novel/(?P<code>\d+)/(?P<slug>[^/?#]+)",
    re.IGNORECASE)

#: Начинка страницы у Next.js.
NEXT_DATA = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE)

#: Метка имени внутри абзаца. Номер — место в словаре главы, а не сам
#: перевод. Закрывающих знака два: сайт ставит то один, то другой.
TERM_MARKS = ("※{n}⛬", "※{n}〓")

#: Абзац, который на деле картинка. Книге они не нужны — в текст их не
#: положить, — но пропускать молча тоже нельзя было бы, если бы в них
#: лежал текст. В них не лежит: рядом идёт отдельный список адресов.
IMAGE_MARK = "[image]"

#: Каким переводом берём главу. У сайта их три — «Web», «Web+» и «AI», —
#: и над текстом стоит переключатель. Id службы виден в адресе страницы
#: (`?service=web`) и в её начинке (`active_service`), а в запросе за
#: главой то же значение уходит полем `translate`.
#:
#: Берём обычный «Web»: он лежит готовым у каждой главы и достаётся
#: сразу. «AI» — та самая машина, которая переводит по запросу: главы
#: там открываются поштучно, часть за самоцветы, и книга оттуда идёт
#: часами. WebToEpub просит именно «ai», и это его право — ему нужен
#: перевод получше; нам нужен тот, который есть у всех глав.
WEB, AI = "web", "ai"

#: Сколько ждать между главами.
#:
#: У «Web» перевод уже лежит, и торопить нечего: хватает общей паузы
#: витрины. У «AI» сервер переводит главу в момент запроса и на частые
#: запросы отвечает пустой главой — там нужен десяток секунд.
PAUSE_AI = 12.0


class ChapterNotTranslated(SourceBroken):
    """Этой главы у выбранного перевода нет.

    Отдельно от «источник изменился»: чинить нечего и повторять нечего —
    перевода просто нет. У «AI» он появляется тогда, когда его закажет
    кто-то из читателей сайта. Качалка отмечает такую главу пропуском и
    идёт дальше, а не роняет книгу целиком.
    """


def _text(value) -> str:
    return str(value).strip() if value is not None else ""


class WtrlabSource(Source):
    """Книга с WTR-LAB по ссылке, уже по-английски."""

    key = "wtrlab"
    name = "WTR-LAB (перевод на английский)"
    placeholder = "https://wtr-lab.com/en/novel/8093/the-wizard-is-chasing-the-truth"
    hint = ("Книга приходит уже переведённой на английский — переводить "
            "её после скачивания не нужно, но и перевод не свой. "
            "Вставьте адрес книги целиком. Берём обычный перевод «Web» — "
            "он лежит готовым у каждой главы. Нужен другой — скопируйте "
            "адрес с той страницы, где он у вас выбран: сайт пишет выбор "
            "прямо в адрес (?service=…). У «AI» главы открываются "
            "поштучно, и книга оттуда идёт часами.")
    needs_proxy = False
    #: Пауза не постоянная: её ставит выбранный перевод. Поле остаётся у
    #: самого источника, потому что качалка спрашивает именно его.
    pause = 0.0

    # ----------------------------------------------------------- книга

    @staticmethod
    def _parts(address: str) -> tuple[str, str, str]:
        """Язык, код книги и слаг из адреса. Пусто — адрес не тот."""
        try:
            path = urlparse((address or "").strip()).path or ""
        except ValueError:
            return "", "", ""
        found = BOOK_PATH.search(path)
        if not found:
            return "", "", ""
        return (found.group("lang").lower(), found.group("code"),
                found.group("slug"))

    @staticmethod
    def _service(address: str) -> str:
        """Какой перевод берём. По умолчанию «Web».

        Спрашиваем сам адрес: сайт пишет выбор в него (`?service=ai`), и
        человек копирует ссылку с той страницы, где читает. Это дешевле
        любой настройки в программе — выбор уже сделан там, где его
        видно, а нам остаётся его не потерять.
        """
        try:
            asked = parse_qs(urlparse((address or "").strip()).query)
        except ValueError:
            return WEB
        found = (asked.get("service") or [""])[0].strip().lower()
        return found or WEB

    def _remember(self, address: str) -> str:
        """Перевод из адреса — и пауза под него.

        Пауза выставляется здесь, а не при создании источника: до
        разбора адреса неизвестно, какой перевод спрашивают, а разница
        между ними — часы на восьмистах главах.
        """
        service = self._service(address)
        self.pause = PAUSE_AI if service == AI else 0.0
        return service

    def _demand_parts(self, query: str) -> tuple[str, str, str]:
        lang, code, slug = self._parts(query)
        if not code:
            raise SourceBroken(
                "Этот источник принимает полный адрес книги на "
                f"{SITE}. Пример: {self.placeholder}")
        return lang, code, slug

    def _book_url(self, lang: str, code: str, slug: str,
                  service: str = WEB) -> str:
        """Адрес книги. Выбранный перевод остаётся в нём.

        Иначе он терялся бы между «найти» и «скачать»: главу качает
        отдельный вызов, которому книга уже не видна, — а видна ему
        только ссылка.
        """
        where = f"{SITE}/{lang}/novel/{code}/{slug}"
        return where if service == WEB else f"{where}?service={service}"

    @staticmethod
    def _begin(page: str) -> dict:
        """Начинка страницы книги — та, что Next.js кладёт в скрипт."""
        found = NEXT_DATA.search(page or "")
        if not found:
            raise SourceBroken(
                "Источник изменился: на странице книги нет её начинки "
                "(__NEXT_DATA__). Разбирать вёрстку нечего — оглавление "
                "в неё не попадает вовсе.", page=page or "")
        try:
            begin = json.loads(found.group(1))
        except ValueError as exc:
            raise SourceBroken(
                f"Источник изменился: начинку страницы книги не разобрать "
                f"({exc}).", page=page or "") from exc
        if not isinstance(begin, dict):
            raise SourceBroken(
                "Источник изменился: начинка страницы книги пришла не "
                "тем, чем была.", page=page or "")
        return begin

    @staticmethod
    def _serie(begin: dict) -> dict:
        """Сама книга внутри начинки страницы."""
        where = begin
        for step in ("props", "pageProps", "serie", "serie_data"):
            where = where.get(step) if isinstance(where, dict) else None
            if where is None:
                return {}
        return where if isinstance(where, dict) else {}

    def find(self, client, query: str) -> Novel:
        lang, code, slug = self._demand_parts(query)
        service = self._remember(query)
        book = self._book_url(lang, code, slug, service)
        serie = self._serie(self._begin(client.get_text(book)))
        about = serie.get("data") if isinstance(serie.get("data"), dict) else {}

        # Число глав берём из начинки, но за настоящим списком всё равно
        # идём отдельно: здесь оно справочное и на день-другой отстаёт.
        counted = serie.get("chapter_count") or serie.get("raw_chapter_count")

        return Novel(
            code=int(code),
            name=_text(about.get("title")) or f"book-{code}",
            #: Адрес книги целиком: по нему строятся все остальные, и
            #: терять его нельзя — язык и слаг из кода не выводятся.
            slug=book,
            total_chapters=int(counted or 0),
            author=_text(about.get("author")) or _text(serie.get("author")),
            status="",
            language=lang or "en",
            cover=_text(about.get("image")),
        )

    # ------------------------------------------------------- оглавление

    def toc(self, client, novel: Novel, first: int = 1, last: int | None = None,
            on_progress=None) -> Toc:
        book = novel.slug or ""
        lang, code, slug = self._parts(book)
        if not code:
            raise SourceBroken(
                "У книги не сохранён адрес сайта — найдите её заново.")
        service = self._remember(book)

        where = f"{SITE}/api/chapters/{code}"
        try:
            answer = client.get(where).json()
        except Exception as exc:  # noqa: BLE001 — беда одна, причин много
            raise SourceBroken(
                f"Список глав не пришёл ({where}): {exc}. У этого сайта он "
                "приходит отдельным запросом, и без него скачивать "
                "нечего.") from exc

        rows = answer.get("chapters") if isinstance(answer, dict) else None
        if not isinstance(rows, list) or not rows:
            raise SourceBroken(
                f"Источник изменился: в ответе со списком глав ({where}) "
                "самого списка нет. Скачивание невозможно, пока модуль не "
                "поправят.")

        chapters = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            order = item.get("order")
            try:
                number = int(order)
            except (TypeError, ValueError):
                continue
            link = f"{SITE}/{lang}/novel/{code}/{slug}/chapter-{number}"
            if service != WEB:
                # Выбранный перевод едет в ссылке: главу качает отдельный
                # вызов, которому книга уже не видна — видна только она.
                link = f"{link}?service={service}"
            chapters.append(Chapter(number=number, post_id=number,
                                    ch_name=_text(item.get("title")),
                                    link=link))
        if not chapters:
            raise SourceBroken(
                f"Источник изменился: в списке глав ({where}) не нашлось "
                "ни одного номера. Скачивание невозможно, пока модуль не "
                "поправят.")

        chapters.sort(key=lambda one: one.number)
        upto = last or chapters[-1].number
        wanted = [one for one in chapters if first <= one.number <= upto]
        if on_progress:
            on_progress(len(wanted), len(wanted))

        have = {one.number for one in wanted}
        missing = [n for n in range(first, upto + 1) if n not in have]
        return Toc(chapters=wanted, missing=missing)

    # ------------------------------------------------------------ глава

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        address = chapter.link or ""
        lang, code, _ = self._parts(address)
        if not code:
            raise SourceBroken(f"У главы {chapter.number} нет адреса.")

        service = self._remember(address)
        body = json.dumps({
            # Тем же словом сайт называет перевод и в адресе страницы
            # (`?service=web`), и здесь. «web» — тот, что лежит готовым.
            "translate": service,
            "language": lang or "en",
            "raw_id": code,
            "chapter_no": str(chapter.number),
            "retry": False,
            "force_retry": False,
        })
        where = f"{SITE}/api/reader/get"
        try:
            answer = client.post(
                where, data=body,
                headers={"Content-Type": "application/json;charset=UTF-8",
                         "Referer": address}).json()
        except Exception as exc:  # noqa: BLE001 — беда одна, причин много
            raise SourceBroken(
                f"Глава {chapter.number} не пришла ({where}): {exc}.") from exc

        if not isinstance(answer, dict):
            raise SourceBroken(
                f"Источник изменился: ответ на главу {chapter.number} "
                "пришёл не тем, чем был.")

        self._check(answer, chapter)

        inner = self._inner(answer)
        rows = inner.get("body")
        if not isinstance(rows, list) or not rows:
            # Пустая глава — не поломка разбора, но и в книгу класть
            # нечего. У «AI» так отвечает сервер, когда его торопят.
            raise ChapterNotTranslated(
                f"Глава {chapter.number} пришла пустой (перевод "
                f"«{service}»). Попробуйте позже, а если повторяется — "
                "откройте её в браузере и посмотрите, есть ли она там.")

        said = self._terms(inner)
        patch = inner.get("patch") if isinstance(inner.get("patch"), list) else []
        lines = []
        for one in rows:
            if not isinstance(one, str) or one == IMAGE_MARK:
                continue
            words = self._fill(one, said, patch)
            if words.strip():
                lines.append(words.strip())

        if not lines:
            raise SourceBroken(
                f"Источник изменился: в главе {chapter.number} не нашлось "
                "ни одного абзаца.")

        head = answer.get("chapter")
        title = _text(head.get("title")) if isinstance(head, dict) else ""
        return (title or chapter.title), "\n\n".join(lines)

    @staticmethod
    def _check(answer: dict, chapter: Chapter) -> None:
        """Отказы, которые сайт называет своими словами."""
        if _text(answer.get("code")) == "CHAPTER_LOCKED":
            raise ChapterNotTranslated(
                f"Глава {chapter.number} у этого перевода закрыта. Так "
                "бывает у «AI»: главы там открываются поштучно, часть за "
                "самоцветы. Обычный «Web» лежит открытым у всех глав — "
                "вставьте адрес книги без «?service=».")
        if answer.get("requireTurnstile"):
            raise SourceBroken(
                f"Сайт просит проверку «вы не робот» на главе "
                f"{chapter.number}. Пройти её отсюда нечем: откройте книгу "
                "в браузере, а потом продолжите скачивание.")

    @staticmethod
    def _inner(answer: dict) -> dict:
        """Внутренность ответа: `data.data`, где и лежит сама глава."""
        where = answer.get("data")
        where = where.get("data") if isinstance(where, dict) else None
        return where if isinstance(where, dict) else {}

    @staticmethod
    def _terms(inner: dict) -> list[str]:
        """Имена по местам словаря главы.

        Каждая запись — список, где первым идёт перевод. Пустая запись
        оставляется пустой строкой: подставить вместо метки нечего, и
        метка останется на виду. Это лучше, чем тихо съесть имя.
        """
        glossary = inner.get("glossary_data")
        rows = glossary.get("terms") if isinstance(glossary, dict) else None
        if not isinstance(rows, list):
            return []
        out = []
        for one in rows:
            if isinstance(one, list) and one and isinstance(one[0], str):
                out.append(one[0])
            else:
                out.append("")
        return out

    @staticmethod
    def _fill(text: str, said: list[str], patch: list) -> str:
        """Метки — на имена, а `zh`-куски — на их перевод.

        Порядок важен: сперва словарь главы, потом заплатки. Заплатка
        ищет в тексте иероглифы, которые машина не перевела вовсе, и
        подставленное имя ей не мешает.
        """
        for number, word in enumerate(said):
            if not word:
                continue
            for mark in TERM_MARKS:
                text = text.replace(mark.format(n=number), word)
        for one in patch:
            if not isinstance(one, dict):
                continue
            was, now = _text(one.get("zh")), _text(one.get("en"))
            if was and now:
                text = text.replace(was, " " + now)
        return text


__all__ = ["ChapterNotTranslated", "SITE", "WtrlabSource"]
