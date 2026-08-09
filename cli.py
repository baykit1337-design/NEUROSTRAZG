#!/usr/bin/env python3
"""CLI: скачивание глав книги с MVLEMPYR.

    python cli.py https://www.mvlempyr.io/novel/insect-tamers-ascension
    python cli.py 6615 --out ~/Books --name "Insect Tamer"
    python cli.py insect-tamers-ascension --from 100 --to 200
    python cli.py --search "insect tamer"
    python cli.py --verify ~/Books/Insect Tamer
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mvl import api
from mvl.client import Client
from mvl.downloader import Cancelled, Downloader, verify
from mvl.paths import prepare_output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Качалка глав с MVLEMPYR", formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("book", nargs="?", help="ссылка на книгу, слаг или числовой код")
    parser.add_argument("--out", "-o", default=".", help="куда класть папку с главами (по умолчанию: текущая)")
    parser.add_argument("--name", "-n", help="имя папки (по умолчанию — название книги)")
    parser.add_argument("--from", dest="first", type=int, default=1, help="с какой главы")
    parser.add_argument("--to", dest="last", type=int, help="по какую главу")
    parser.add_argument("--jobs", "-j", type=int, default=5, help="параллельных запросов, максимум 5")
    parser.add_argument("--search", help="найти книгу в каталоге и выйти")
    parser.add_argument("--verify", help="проверить целостность уже скачанной папки")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


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
            if progress.stage in ("done", "error", "cancelled"):
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
            if progress.stage in ("done", "error", "cancelled"):
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

    client = Client()

    if args.search:
        for novel in api.search_novels(client, args.search):
            print(f"{novel.code:>8}  {novel.total_chapters:>5} гл  {novel.name}")
        return 0

    if not args.book:
        build_parser().print_help()
        return 2

    downloader = Downloader(client=client, concurrency=args.jobs, on_progress=_progress_printer())

    try:
        novel = downloader.find(args.book)
    except (LookupError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    print(f"\n{novel.name} — {novel.total_chapters} глав, код {novel.code}")

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
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
