#!/usr/bin/env python3
"""Проба на одну главу: пускает ли витрина обычный HTTP-запрос.

Ровно один запрос, без параллельности. Ничего не сохраняет — только
докладывает, что пришло.

    python probe.py                 # глава 6615-200, контрольная
    python probe.py 6615-1
    python probe.py https://www.mvlempyr.io/chapter/6615-200

Исход A — пришёл HTML с div#chapter: путь рабочий, можно качать.
Исход B — заглушка Cloudflare: обходить не пытаемся, переходим к WebToEpub
          (см. README, раздел «Запасной план»).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_CHAPTER = "6615-200"
SITE = "https://www.mvlempyr.io"
# Referer — страница книги, как если бы пользователь пришёл по ссылке оттуда.
DEFAULT_REFERER = f"{SITE}/novel/insect-tamers-ascension"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": DEFAULT_REFERER,
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def build_url(argument: str) -> str:
    if argument.startswith("http"):
        return argument
    if re.fullmatch(r"\d+-\d+", argument):
        return f"{SITE}/chapter/{argument}"
    raise SystemExit(f"Не понимаю аргумент: {argument!r}. Нужен '6615-200' или полный URL.")


def main() -> int:
    url = build_url(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CHAPTER)

    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        print("Нужен curl_cffi: pip install curl_cffi")
        print("Обычный requests не подойдёт — Cloudflare отсекает по TLS-отпечатку.")
        return 2

    print(f"GET {url}")
    print("клиент: curl_cffi, impersonate=chrome, Session\n")

    # Session, а не одиночный запрос: Cloudflare выдаёт куку доступа, и в
    # реальном прогоне её нужно переиспользовать между главами.
    with curl_requests.Session(impersonate="chrome") as session:
        try:
            response = session.get(url, headers=HEADERS, timeout=30)
        except Exception as exc:
            print(f"Запрос не прошёл: {type(exc).__name__}: {exc}")
            return 2

    body = response.text
    print(f"статус:        {response.status_code}")
    print(f"размер ответа: {len(body.encode('utf-8')) / 1024:.1f} КБ")

    from mvl.api import looks_like_cloudflare

    if looks_like_cloudflare(body):
        print("\nИСХОД B: пришла заглушка Cloudflare.")
        print("Обходить её не пытаемся. Запасной план — WebToEpub, см. README.")
        print("Список ссылок для расширения: python cli.py 6615 --links links.txt")
        return 1

    if response.status_code != 200:
        print(f"\nНеожиданный статус {response.status_code} — это не исход A.")
        print(f"Первые 300 символов:\n{body[:300]}")
        return 1

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body, "lxml")
    block = soup.find(id="chapter")
    print(f"div#chapter:   {'найден' if block else 'НЕ найден'}")

    if block is None:
        print("\nСтраница пришла, но разметка другая — селекторы надо пересмотреть.")
        print(f"Первые 300 символов:\n{body[:300]}")
        return 1

    from mvl.api import parse_chapter_page

    title, text = parse_chapter_page(body)
    paragraphs = text.split("\n\n")
    print(f"абзацев:       {len(paragraphs)}")
    print(f"заголовок:     {title or '(пусто)'}")
    print(f"\nпервые 300 символов текста:\n{text[:300]}")

    print("\nИСХОД A: страница отдаётся, текст разбирается.")
    print("Можно качать: один поток, пауза 2-4 с, одна сессия на прогон.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
