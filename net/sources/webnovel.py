"""Источник Webnovel.

Ни вёрстку, ни шрифты разбирать не нужно: обе нужные страницы кладут всё
в объект на самой странице. Книга — в `g_data.book`, глава — в
`g_data.chapInfo`, и текст главы лежит там абзац к абзацу, готовым.
Разметка вокруг может меняться сколько угодно.

Есть одна ловушка, из-за которой наивный разбор ломается сразу же: то,
что выглядит как JSON, им не является. Сайт экранирует обратной косой
чертой пробелы и амперсанды — `"Marvel:\\ I\\ Steal\\ Powers"`, — а таких
escape-последовательностей в JSON нет, и любой разборщик на этом
останавливается. Поэтому перед разбором лишние косые убираются.

Чего этот источник не умеет и не будет:
  • платные главы. У книги часть глав закрыта, и открываются они деньгами
    на счёте читателя. Обходить это программа не станет — закрытая глава
    честно отмечается пропуском;
  • главы, зашифрованные шрифтом. Сайт иногда отдаёт текст вперемешку с
    собственным начертанием, и без него это не буквы, а мусор. Такую
    главу лучше пропустить с внятной причиной, чем записать нечитаемой.

Живой проверки в песочнице не было: `www.webnovel.com` из неё недоступен
— шлюз отвечает 403 на любой хост вне разрешённого списка. Разбор написан
по исходникам страницы книги и страницы главы и покрыт тестами на них же;
первый живой запуск — на машине человека.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .base import Chapter, Novel, Source, SourceBroken, Toc

log = logging.getLogger(__name__)

SITE = "https://www.webnovel.com"

#: Код книги — длинное число. Оно же встречается в адресе главы, поэтому
#: сначала пробуем разобрать адрес, и только потом принимаем голое число.
BOOK_ID = re.compile(r"\b(\d{8,25})\b")

#: `/book/{slug}_{bookId}` либо `/book/{bookId}`.
BOOK_IN_URL = re.compile(r"/book/(?:[^/]*?_)?(\d{8,25})")

#: Ссылка на главу в оглавлении: последнее число адреса — код главы.
CHAPTER_LINK = re.compile(r'href="(/book/[^"]*?(\d{10,25}))"')

#: Объект со страницы. Ищем не регулярным выражением по всему телу, а по
#: началу — дальше скобки считаются вручную: внутри объекта есть и
#: вложенные скобки, и строки со скобками, и регулярное выражение на
#: этом всегда обрезает не там.
BOOK_MARK = "g_data.book="
CHAPTER_MARK = "chapInfo="

#: Косые перед символами, которых нет в списке допустимых для JSON.
#: Оставляем `"` `\` `/` `b` `f` `n` `r` `t` `u` — всё остальное снимаем.
BAD_ESCAPE = re.compile(r'\\([^"\\/bfnrtu])')


def _unescape(text: str) -> str:
    """Убирает косые, которых в JSON быть не должно.

    Сайт экранирует ими пробелы, амперсанды и апострофы. Разборщик JSON
    на первой же такой останавливается, и без этой чистки со страницы не
    прочитать вообще ничего.
    """
    return BAD_ESCAPE.sub(r"\1", text)


def _object_after(page: str, mark: str) -> dict:
    """Объект, идущий сразу за меткой.

    Скобки считаются вручную, с оглядкой на строки: внутри объекта есть и
    вложенные скобки, и строки, в которых скобки — просто символы.
    """
    start = page.find(mark)
    if start < 0:
        raise SourceBroken(
            f"На странице нет объекта «{mark}» — сайт сменил разметку")
    start = page.find("{", start)
    if start < 0:
        raise SourceBroken(f"За «{mark}» не нашлось объекта")

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(page)):
        char = page[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                raw = page[start:i + 1]
                try:
                    return json.loads(_unescape(raw))
                except ValueError as exc:
                    raise SourceBroken(
                        f"Объект «{mark}» не разбирается: {exc}") from exc
    raise SourceBroken(f"Объект «{mark}» оборван — страница пришла не целиком")


def _text_of(html: str) -> str:
    """Абзац главы: из размеченного куска — просто текст."""
    if not html:
        return ""
    return BeautifulSoup(_unescape(html), "lxml").get_text(" ", strip=True)


class ChapterLocked(SourceBroken):
    """Глава закрыта и открывается деньгами.

    Отдельно от «разметка сменилась»: чинить тут нечего, и повторять
    тоже незачем. Качалка отмечает такую главу пропуском и идёт дальше.
    """


class ChapterScrambled(SourceBroken):
    """Текст главы отдан вместе со своим шрифтом.

    Без этого шрифта это не буквы, а служебные значки. Записать такую
    главу значило бы положить в книгу мусор под видом текста.
    """


class WebnovelSource(Source):
    """Книга с webnovel.com."""

    key = "webnovel"
    name = "Webnovel"
    placeholder = "https://www.webnovel.com/book/36543528000922105"
    hint = ("Вставьте адрес книги или её числовой код. Платные главы "
            "останутся пропущенными: программа их не обходит.")
    #: Сайт мировой и провайдером не режется. Прокси при этом никто не
    #: запрещает — они просто не обязательны.
    needs_proxy = False

    # ----------------------------------------------------------- книга

    def book_id(self, query: str) -> str:
        """Код книги из адреса, кода или ссылки на главу."""
        text = (query or "").strip()
        if not text:
            return ""
        if text.isdigit():
            return text

        found = BOOK_IN_URL.search(text)
        if found:
            return found.group(1)
        # Адрес незнакомой формы, но с длинным числом внутри: берём его
        # первым — в адресе главы книга идёт раньше главы.
        if "webnovel.com" in urlparse(text).netloc:
            any_number = BOOK_ID.search(text)
            if any_number:
                return any_number.group(1)
        return ""

    def find(self, client, query: str) -> Novel:
        code = self.book_id(query)
        if not code:
            raise SourceBroken(
                "Это не похоже на книгу с Webnovel. Нужен адрес вида "
                "https://www.webnovel.com/book/36543528000922105 "
                "или сам числовой код.")

        page = client.get_text(f"{SITE}/book/{code}")
        info = (_object_after(page, BOOK_MARK) or {}).get("bookInfo") or {}
        if not info:
            raise SourceBroken(
                "На странице книги нет её описания — сайт сменил разметку")

        total = int(info.get("totalChapterNum")
                    or info.get("chapterNum") or 0)
        return Novel(
            # Код длинный, но всё равно число: тип общий на все источники.
            code=int(code),
            name=str(info.get("bookName") or "").strip() or f"Книга {code}",
            # Слаг у сайта в адресе необязателен: короткая форма
            # `/book/{код}` работает и её же отдаёт сам сайт в
            # `rel="canonical"`. Держим код — он не меняется никогда.
            slug=code,
            total_chapters=total,
            author=str(info.get("authorName") or "").strip(),
            status=self._status(info),
            language=str(info.get("languageName") or "").strip().lower(),
            cover=self._cover(code, info),
        )

    @staticmethod
    def _status(info: dict) -> str:
        """Пишется книга или закончена.

        Сайт держит это числом: полсотни — «завершена», всё, что меньше,
        — «продолжается». Отдельного словесного поля у него нет.
        """
        try:
            action = int(info.get("actionStatus") or 0)
        except (TypeError, ValueError):
            return ""
        return "закончена" if action >= 50 else "пишется"

    @staticmethod
    def _cover(code: str, info: dict) -> str:
        stamp = info.get("coverUpdateTime") or ""
        address = f"https://book-pic.webnovel.com/bookcover/{code}"
        return f"{address}?imageMogr2/thumbnail/600x&imageId={stamp}" if stamp \
            else address

    # ------------------------------------------------------- оглавление

    def toc(self, client, novel: Novel, first: int = 1, last: int | None = None,
            on_progress=None) -> Toc:
        code = str(novel.slug or novel.code)
        page = client.get_text(f"{SITE}/book/{code}/catalog")
        rows = self._catalog(page, code)
        if not rows:
            raise SourceBroken(
                f"Оглавление книги {code} не разобралось: страница "
                f"{SITE}/book/{code}/catalog не отдала ни одной главы. "
                "Скорее всего, сайт переделал её на подгрузку скриптом — "
                "тогда разбор надо чинить, а не повторять запрос.")

        edge = last or len(rows)
        chapters = []
        for number, (chapter_id, name) in enumerate(rows, 1):
            if number < first or number > edge:
                continue
            chapters.append(Chapter(
                number=number,
                post_id=chapter_id,
                ch_name=name,
                link=f"{SITE}/book/{code}/{chapter_id}",
            ))
            if on_progress:
                on_progress(len(chapters), min(edge, len(rows)) - first + 1)

        return Toc(chapters=chapters, missing=[])

    @staticmethod
    def _catalog(page: str, code: str) -> list:
        """Пары «код главы, название» в порядке чтения.

        Собираем по ссылкам страницы оглавления. Разбирать вместо этого
        какой-нибудь объект с данными было бы надёжнее — так сделаны и
        книга, и глава, — но объекта оглавления мне видеть не приходилось,
        а сочинять его форму по догадке значит написать разбор, который
        никогда не проверялся и тихо ничего не найдёт. Ссылки на главы
        сайт проставляет ради поисковиков, и они переживают переделку
        вида.
        """
        rows = []
        seen = set()
        soup = BeautifulSoup(page, "lxml")
        for link in soup.find_all("a", href=True):
            found = CHAPTER_LINK.search(f'href="{link["href"]}"')
            if not found:
                continue
            chapter_id = found.group(2)
            # Ссылка на саму книгу тоже кончается длинным числом — это её
            # код, а не глава.
            if chapter_id == code or chapter_id in seen:
                continue
            seen.add(chapter_id)
            rows.append((chapter_id, link.get_text(" ", strip=True)))
        return rows

    # ------------------------------------------------------------ глава

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        page = client.get_text(chapter.link)
        info = (_object_after(page, CHAPTER_MARK) or {}).get("chapterInfo") or {}
        if not info:
            raise SourceBroken(
                f"В главе {chapter.number} нет текста — сайт сменил разметку")

        if info.get("css"):
            raise ChapterScrambled(
                f"Глава {chapter.number} отдана вместе со своим шрифтом: "
                "без него это не буквы. Пропускаем — записывать мусор хуже, "
                "чем не записать ничего.")

        parts = [_text_of(item.get("content") or "")
                 for item in info.get("contents") or []]
        text = "\n\n".join(part for part in parts if part)

        if not text:
            if not int(info.get("isAuth") or 0):
                raise ChapterLocked(
                    f"Глава {chapter.number} платная: открывается монетами "
                    "на счёте читателя. Программа этого не обходит.")
            raise SourceBroken(
                f"Глава {chapter.number} пришла пустой — сайт сменил разметку")

        name = str(info.get("chapterName") or "").strip() or chapter.title
        return name, text


__all__ = ["ChapterLocked", "ChapterScrambled", "SITE", "WebnovelSource"]
