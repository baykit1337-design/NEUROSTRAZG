#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Разбивает книгу из одного файла на отдельные .txt по главам.

Поддерживает:
  .epub  — берёт главы как отдельные файлы внутри архива (точные границы)
  .txt   — режет по заголовкам глав регулярным выражением

Использование:
    python split_book.py книга.epub
    python split_book.py книга.txt
    python split_book.py книга.txt --out "D:\\Переводы\\Книга"
    python split_book.py книга.txt --pattern "^\\s*Глава\\s+\\d+"
"""

import argparse
import html
import logging
import os
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- HTML -> текст

class TextExtractor(HTMLParser):
    """Вытаскивает текст, сохраняя разбивку на абзацы."""

    BLOCK = {'p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote'}
    SKIP = {'script', 'style', 'head'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0
        self._heading = None
        self._in_heading = False
        self._heading_buf = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag in ('h1', 'h2', 'h3') and self._heading is None:
            self._in_heading = True
        if tag == 'br':
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag in ('h1', 'h2', 'h3') and self._in_heading:
            self._in_heading = False
            self._heading = ''.join(self._heading_buf).strip() or None
        if tag in self.BLOCK:
            self.parts.append('\n')

    def handle_data(self, data):
        if self._skip_depth:
            return
        self.parts.append(data)
        if self._in_heading:
            self._heading_buf.append(data)

    def result(self):
        raw = ''.join(self.parts)
        raw = raw.replace('\u00a0', ' ')
        # схлопываем пробелы внутри строк, но сохраняем пустые строки как границы абзацев
        lines = [re.sub(r'[ \t]+', ' ', ln).strip() for ln in raw.split('\n')]
        lines = [ln for ln in lines if ln]
        return '\n\n'.join(lines), self._heading


def html_to_text(data: bytes):
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('utf-8', errors='replace')
    p = TextExtractor()
    p.feed(text)
    return p.result()


# ---------------------------------------------------------------- имена файлов

BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def safe_name(s: str, limit: int = 110) -> str:
    s = BAD_CHARS.sub('', s)
    s = re.sub(r'\s+', ' ', s).strip(' .')
    return s[:limit] or 'chapter'


# ---------------------------------------------------------------- EPUB

#: Сколько знаков в странице без заголовка ещё считаем служебными
#: (обложка, титул, выходные данные), а не главой.
SERVICE_PAGE = 200


def _toc_titles(z, names, base, manifest, nav_ids, ncx_ids):
    """Названия глав из оглавления епаба: путь к файлу → название.

    Зачем. Название главы лежит в епабе в двух местах, и в разных книгах
    заполнено то одно, то другое. Внутри самой главы — заголовком `<h1>`;
    его мы и брали. Но целые книги приходят вообще без заголовков внутри:
    там есть только оглавление, а в файлах — голый текст.

    Раньше на такой книге название бралось из имени файла. Имена в епабе
    служебные — `0122.xhtml`, — и книга на четыреста сорок шесть глав
    выходила из программы как «Глава 122», «Глава 123», «Глава 124»: не
    названия и не номера, а порядковые номера файлов внутри архива.

    Разбираем оба вида оглавления. EPUB3 держит его отдельной страницей
    со ссылками, EPUB2 — файлом `.ncx`. Книга бывает и с тем и с другим,
    поэтому берём всё, что нашлось, а первое найденное название за
    файлом и остаётся.
    """
    found: dict[str, str] = {}

    def put(href: str, title: str):
        title = re.sub(r'\s+', ' ', (title or '')).strip()
        if not href or not title:
            return
        # Ссылка ведёт в место внутри файла: «глава.xhtml#top». Нам нужен
        # сам файл — глава лежит в нём целиком.
        href = unquote(href.split('#')[0])
        if not href:
            return
        full = os.path.normpath(os.path.join(base, href)).replace('\\', '/')
        found.setdefault(full, title)

    for idref in list(nav_ids) + list(ncx_ids):
        href = manifest.get(idref)
        if not href:
            continue
        full = os.path.normpath(os.path.join(base, href)).replace('\\', '/')
        if full not in names:
            continue
        # Папка самого оглавления, а не книги: ссылки в нём относительны
        # его собственного места.
        here = os.path.dirname(full)
        try:
            raw = z.read(full)
        except (KeyError, OSError):
            continue

        if idref in ncx_ids:
            # EPUB2: navPoint → navLabel/text и content@src.
            try:
                tree = ET.fromstring(raw)
            except ET.ParseError:
                continue
            for point in tree.iter():
                if not point.tag.endswith('navPoint'):
                    continue
                label = src = ''
                for el in point.iter():
                    if el.tag.endswith('text') and not label:
                        label = ''.join(el.itertext())
                    if el.tag.endswith('content') and el.get('src') and not src:
                        src = el.get('src')
                if src:
                    put(os.path.relpath(
                        os.path.normpath(os.path.join(here, unquote(src.split('#')[0]))),
                        base or '.').replace('\\', '/'), label)
        else:
            # EPUB3: страница со ссылками. Разбираем как HTML, а не как
            # XML: страница оглавления бывает и не строгим XML.
            links = LinkExtractor()
            try:
                links.feed(raw.decode('utf-8', errors='replace'))
            except Exception as exc:  # noqa: BLE001 — кривое оглавление не повод бросать книгу
                log.warning("Оглавление %s не разобралось: %s", full, exc)
            for href, label in links.links:
                put(os.path.relpath(
                    os.path.normpath(os.path.join(here, unquote(href.split('#')[0]))),
                    base or '.').replace('\\', '/'), label)

    return found


class LinkExtractor(HTMLParser):
    """Ссылки со страницы оглавления: адрес и подпись."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        href = dict(attrs).get('href')
        if href:
            self._href = href
            self._text = []

    def handle_endtag(self, tag):
        if tag == 'a' and self._href is not None:
            self.links.append((self._href, ''.join(self._text)))
            self._href = None
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)


def epub_chapters(path: Path):
    """Возвращает список (заголовок, текст) в порядке чтения книги."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()

        # 1. находим OPF через container.xml
        opf_path = None
        if 'META-INF/container.xml' in names:
            root = ET.fromstring(z.read('META-INF/container.xml'))
            for rf in root.iter():
                if rf.tag.endswith('rootfile') and rf.get('full-path'):
                    opf_path = rf.get('full-path')
                    break
        if not opf_path:
            opf_path = next((n for n in names if n.lower().endswith('.opf')), None)
        if not opf_path:
            raise SystemExit('не найден OPF внутри epub — файл повреждён?')

        base = os.path.dirname(opf_path)
        opf = ET.fromstring(z.read(opf_path))

        # 2. manifest: id -> href
        manifest = {}
        # Оглавление помечено в манифесте само — угадывать его по объёму
        # не нужно, а вот короткую настоящую главу так недолго и потерять.
        nav_ids = set()
        #: Оглавление старого образца, отдельным файлом `.ncx`.
        ncx_ids = set()
        for el in opf.iter():
            if el.tag.endswith('item') and el.get('id') and el.get('href'):
                manifest[el.get('id')] = el.get('href')
                if 'nav' in (el.get('properties') or '').split():
                    nav_ids.add(el.get('id'))
                if el.get('media-type') == 'application/x-dtbncx+xml':
                    ncx_ids.add(el.get('id'))

        # 3. spine: порядок чтения
        order = [el.get('idref') for el in opf.iter()
                 if el.tag.endswith('itemref') and el.get('idref')]
        # У корешка бывает своя ссылка на `.ncx` — там, где в манифесте
        # тип не проставлен.
        for el in opf.iter():
            if el.tag.endswith('spine') and el.get('toc'):
                ncx_ids.add(el.get('toc'))

        toc = _toc_titles(z, names, base, manifest, nav_ids, ncx_ids)

        chapters = []
        for idref in order:
            href = manifest.get(idref)
            if not href or idref in nav_ids:
                continue
            full = os.path.normpath(os.path.join(base, href)).replace('\\', '/')
            if full not in names:
                continue
            if not full.lower().endswith(('.xhtml', '.html', '.htm')):
                continue

            text, heading = html_to_text(z.read(full))
            # Служебная страница — та, у которой нет заголовка и почти нет
            # текста. Порог по одной длине терял настоящие главы: у
            # авторского послесловия или интерлюдии двухсот знаков нет.
            if not heading and len(text) < SERVICE_PAGE:
                continue
            if not text.strip():
                continue

            # Оглавление — вторым, а не первым. Заголовок внутри главы
            # пишет тот же, кто писал саму главу, и он точнее; оглавление
            # же бывает и на уровне томов — тогда его название досталось
            # бы одной главе из полусотни.
            #
            # А вот имя файла названием не является вовсе: в епабе оно
            # служебное («0122.xhtml»), и до оглавления доходить до него
            # было нельзя.
            title = heading or toc.get(full) or Path(full).stem
            chapters.append((title, text))

        return chapters


# ---------------------------------------------------------------- TXT

DEFAULT_PATTERN = r'^[ \t]*(?:Chapter|Глава|CHAPTER|ГЛАВА)[ \t]+\d+.*$'


def txt_chapters(path: Path, pattern: str):
    raw = path.read_text(encoding='utf-8', errors='replace')
    rx = re.compile(pattern, re.MULTILINE)

    marks = list(rx.finditer(raw))
    if not marks:
        raise SystemExit(
            'заголовки глав не найдены.\n'
            f'Использовался шаблон: {pattern}\n'
            'Посмотрите, как выглядит начало главы в файле, и задайте свой '
            'через --pattern'
        )

    chapters = []
    for i, m in enumerate(marks):
        start = m.start()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(raw)
        block = raw[start:end].strip()
        title = m.group(0).strip()
        body = block[len(m.group(0)):].strip()
        chapters.append((title, body))
    return chapters


# ---------------------------------------------------------------- запись

def write_chapters(chapters, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    width = max(4, len(str(len(chapters))))
    written = 0
    for i, (title, text) in enumerate(chapters, 1):
        name = f'{str(i).zfill(width)} - {safe_name(title)}.txt'
        (out_dir / name).write_text(f'{title}\n\n{text}\n', encoding='utf-8')
        written += 1
    return written


def main():
    ap = argparse.ArgumentParser(description='Разбивает книгу на отдельные .txt по главам')
    ap.add_argument('book', help='путь к .epub или .txt')
    ap.add_argument('--out', help='папка для результата (по умолчанию — рядом с книгой)')
    ap.add_argument('--pattern', default=DEFAULT_PATTERN,
                    help='регулярка заголовка главы (только для .txt)')
    args = ap.parse_args()

    src = Path(args.book).expanduser()
    if not src.exists():
        raise SystemExit(f'файл не найден: {src}')

    out_dir = Path(args.out).expanduser() if args.out else src.parent / safe_name(src.stem)

    ext = src.suffix.lower()
    if ext == '.epub':
        chapters = epub_chapters(src)
    elif ext in ('.txt', '.text'):
        chapters = txt_chapters(src, args.pattern)
    else:
        raise SystemExit(f'не умею работать с {ext}, нужен .epub или .txt')

    if not chapters:
        raise SystemExit('глав не найдено')

    n = write_chapters(chapters, out_dir)
    print(f'Готово: {n} глав')
    print(f'Папка:  {out_dir}')
    print('\nПервые файлы:')
    for f in sorted(out_dir.glob('*.txt'))[:5]:
        print('  ', f.name)


if __name__ == '__main__':
    main()
