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
import os
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET


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
        for el in opf.iter():
            if el.tag.endswith('item') and el.get('id') and el.get('href'):
                manifest[el.get('id')] = el.get('href')

        # 3. spine: порядок чтения
        order = [el.get('idref') for el in opf.iter()
                 if el.tag.endswith('itemref') and el.get('idref')]

        chapters = []
        for idref in order:
            href = manifest.get(idref)
            if not href:
                continue
            full = os.path.normpath(os.path.join(base, href)).replace('\\', '/')
            if full not in names:
                continue
            if not full.lower().endswith(('.xhtml', '.html', '.htm')):
                continue

            text, heading = html_to_text(z.read(full))
            if len(text) < 200:      # обложка, оглавление, служебные страницы
                continue

            title = heading or Path(full).stem
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
