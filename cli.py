#!/usr/bin/env python3
"""NEUROSTRAZH из командной строки: скачивание глав книги.

Примеры ниже — для источника MVLEMPYR, с которого всё начиналось.

    python cli.py https://www.mvlempyr.io/novel/insect-tamers-ascension
    python cli.py 6615 --out ~/Books --name "Insect Tamer"
    python cli.py insect-tamers-ascension --from 100 --to 200
    python cli.py --search "insect tamer"
    python cli.py --verify ~/Books/Insect Tamer
    python cli.py 6615 --links links.txt   # запасной план: список для WebToEpub
    python cli.py --check-proxies          # проверить список прокси
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mvl import api
from mvl.client import SITE, Client
from mvl.downloader import Cancelled, Downloader, verify
from mvl.paths import prepare_output_dir
from mvl.proxies import PROXY_FILE, Proxy, ProxyPool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NEUROSTRAZH — качалка глав",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # Версия берётся из того же места, что и в шапке интерфейса: две
    # записи однажды разойдутся, и «какая у меня версия» станет
    # вопросом без ответа.
    from mvl import __version__

    parser.add_argument("--version", action="version",
                        version=f"NEUROSTRAZH {__version__}")
    parser.add_argument("book", nargs="?", help="ссылка на книгу, слаг или числовой код")
    parser.add_argument("--out", "-o", default=".", help="куда класть папку с главами (по умолчанию: текущая)")
    parser.add_argument("--name", "-n", help="имя папки (по умолчанию — название книги)")
    parser.add_argument("--from", dest="first", type=int, default=1, help="с какой главы")
    parser.add_argument("--to", dest="last", type=int, help="по какую главу")
    parser.add_argument(
        "--links",
        metavar="ФАЙЛ",
        help="не качать, а выгрузить список ссылок на главы (для WebToEpub)",
    )
    parser.add_argument("--search", help="найти книгу в каталоге и выйти")
    parser.add_argument("--verify", help="проверить целостность уже скачанной папки")
    parser.add_argument(
        "--proxies",
        metavar="ФАЙЛ",
        default=PROXY_FILE,
        help=f"список прокси, ip:port:user:pass построчно (по умолчанию: {PROXY_FILE})",
    )
    parser.add_argument(
        "--proxy",
        metavar="IP:PORT:USER:PASS",
        help="один прокси вручную, вместо файла",
    )
    parser.add_argument(
        "--no-proxy", action="store_true", help="идти напрямую, без прокси"
    )
    parser.add_argument(
        "--check-proxies", action="store_true", help="проверить список прокси и выйти"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


def build_pool(args) -> ProxyPool | None:
    """Готовит пул прокси: один вручную, файл или ничего."""
    if args.no_proxy:
        return None

    if args.proxy:
        proxy = Proxy.parse(args.proxy)
        if proxy is None:
            raise ValueError(f"Не разобрал прокси: {args.proxy}")
        return ProxyPool([proxy], source="--proxy")

    path = Path(args.proxies).expanduser()
    if not path.exists():
        # Файла нет и вручную ничего не задали — работаем напрямую.
        return None
    return ProxyPool.from_file(path)


def prepare_pool(pool: ProxyPool) -> bool:
    """Проверяет список и печатает таблицу. False — пригодных нет."""
    print(f"Проверяем {len(pool)} прокси на {SITE}…")
    pool.check_all(
        on_progress=lambda done, total: print(f"\r  {done}/{total}", end="", flush=True)
    )
    print("\r" + " " * 24 + "\r", end="", flush=True)
    print(pool.table())
    print()

    if pool.usable_count == 0:
        print(
            "Ни один прокси не пропускает до сайта.\n"
            "Напрямую не идём — этот путь заблокирован.\n"
            "Обновите proxies.txt и попробуйте снова.",
            file=sys.stderr,
        )
        return False

    print(f"Пригодных: {pool.usable_count} из {len(pool)}. Работаем через {pool.current().label}\n")
    return True


TERMINAL_STAGES = ("done", "error", "cancelled", "blocked")


def _progress_printer():
    """Прогресс-бар tqdm, если он есть; иначе простой вывод в строку."""
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None

    state = {"bar": None, "stage": None}

    def render(progress):
        if tqdm is None:
            sys.stdout.write(f"\r[{progress.stage}] {progress.done}/{progress.total} {progress.message[:60]:<60}")
            sys.stdout.flush()
            if progress.stage in TERMINAL_STAGES:
                sys.stdout.write("\n")
            return

        if progress.stage != state["stage"]:
            if state["bar"] is not None:
                state["bar"].close()
                state["bar"] = None
            state["stage"] = progress.stage
            if progress.stage in ("toc", "download") and progress.total:
                state["bar"] = tqdm(total=progress.total, unit="гл", desc=progress.stage)
            else:
                print(progress.message)

        bar = state["bar"]
        if bar is not None:
            bar.total = progress.total or bar.total
            bar.n = progress.done
            bar.set_postfix_str(f"ошибок {progress.failed}")
            bar.refresh()
            if progress.stage in TERMINAL_STAGES:
                bar.close()
                state["bar"] = None

    return render


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.verify:
        report = verify(Path(args.verify).expanduser())
        print(f"Книга: {report['novel'].get('name', '?')}")
        print(f"Файлов на диске: {report['on_disk']} из {report['total_chapters']}")
        if report["missing"]:
            print(f"Не хватает глав: {report['missing_compact']}")
        if report["lost_files"]:
            print(f"Записаны в кэше, но файлов нет: {report['lost_files']}")
        if report["failed"]:
            print(f"С ошибками: {sorted(report['failed'])}")
        return 0

    try:
        pool = build_pool(args)
    except (OSError, ValueError) as exc:
        print(f"Список прокси: {exc}", file=sys.stderr)
        return 1

    if args.check_proxies:
        if pool is None:
            print("Список прокси не задан. Укажите --proxies или --proxy.", file=sys.stderr)
            return 1
        return 0 if prepare_pool(pool) else 1

    client = Client()

    if args.search:
        for novel in api.search_novels(client, args.search):
            print(f"{novel.code:>8}  {novel.total_chapters:>5} гл  {novel.name}")
        return 0

    if not args.book:
        build_parser().print_help()
        return 2

    downloader = Downloader(client=client, pool=pool, on_progress=_progress_printer())

    try:
        novel = downloader.find(args.book)
    except (LookupError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    print(f"\n{novel.name} — {novel.total_chapters} глав, код {novel.code}")

    if args.links:
        toc = api.fetch_toc(client, novel, first=args.first, last=args.last)
        links = api.chapter_links(novel, toc.chapters)
        Path(args.links).expanduser().write_text("\n".join(links) + "\n", encoding="utf-8")
        client.close()
        print(f"Ссылок выгружено: {len(links)} → {args.links}")
        if toc.missing:
            print(f"Нет в оглавлении: {len(toc.missing)} глав")
        return 0

    # Скачивание идёт через прокси: домен витрины режется провайдером.
    if pool is not None and not prepare_pool(pool):
        client.close()
        return 1

    output_dir = prepare_output_dir(args.out, args.name or novel.name)
    print(f"Папка: {output_dir}\n")

    try:
        report = downloader.run(novel, output_dir, first=args.first, last=args.last)
    except Cancelled:
        print("\nОстановлено. Запустите снова — продолжит с места остановки.")
        return 130
    except KeyboardInterrupt:
        print("\nПрервано. Запустите снова — продолжит с места остановки.")
        return 130
    finally:
        client.close()

    print(f"\nСкачано: {report.downloaded}")
    print(f"Пропущено (уже были): {report.skipped}")
    print(f"Ошибок: {report.failed}")
    if report.failed_chapters:
        print(f"Не удалось: {report.failed_chapters} (подробности в errors.log)")
    if report.missing_in_toc:
        print(f"Нет в оглавлении: {report.missing_in_toc}")
    if report.proxy_switches:
        print(f"Переключений прокси: {report.proxy_switches}, последний — {report.proxy}")

    if report.stopped_reason:
        print(f"\nПрогон остановлен: {report.stopped_reason}")
        print("Запустите ту же команду снова — продолжит с места остановки.")
        return 2
    if report.blocked_at is not None:
        print(
            f"\nСайт закрыл доступ на главе {report.blocked_at} — прогон остановлен.\n"
            f"Подождите и запустите ту же команду снова — продолжит с этого места.\n"
            f"Если блок повторяется — запасной план: python cli.py {novel.code} --links links.txt"
        )
        return 2
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
