"""Оркестрация скачивания: пачки, кэш, докачка, отчёт."""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import api
from .client import MAX_CONCURRENCY, Client, HttpError, polite_pause
from .paths import chapter_filename, write_chapter

log = logging.getLogger(__name__)

STATE_FILE = "state.json"
ERROR_LOG = "errors.log"
STATE_VERSION = 1


@dataclass
class Progress:
    stage: str = "idle"  # idle | search | toc | probe | download | done | error
    message: str = ""
    done: int = 0
    total: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    novel: dict = field(default_factory=dict)
    output_dir: str = ""
    mode: str = ""
    requested: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    failed_chapters: list[int] = field(default_factory=list)
    missing_in_toc: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


class State:
    """state.json в папке книги: что уже скачано, что упало."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {
            "version": STATE_VERSION,
            "novel": {},
            "mode": "",
            "downloaded": {},
            "failed": {},
            "missing_in_toc": [],
            "updated_at": None,
        }
        self._lock = threading.Lock()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Битый %s (%s) — начинаем с чистого состояния", self.path.name, exc)
            return
        if isinstance(loaded, dict) and loaded.get("version") == STATE_VERSION:
            self.data.update(loaded)

    def save(self) -> None:
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tmp = self.path.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self.path)
        except OSError as exc:
            log.warning("Не удалось сохранить состояние: %s", exc)

    def is_done(self, number: int, output_dir: Path) -> bool:
        """Глава считается готовой, только если файл действительно на месте."""
        name = self.data["downloaded"].get(str(number))
        return bool(name) and (output_dir / name).exists()

    def mark_done(self, number: int, filename: str) -> None:
        with self._lock:
            self.data["downloaded"][str(number)] = filename
            self.data["failed"].pop(str(number), None)

    def mark_failed(self, number: int, reason: str) -> None:
        with self._lock:
            self.data["failed"][str(number)] = reason


class Downloader:
    """Скачивает главы книги в отдельные .txt.

    Прерывание в любой момент безопасно: прогресс лежит в state.json, при
    следующем запуске готовые главы пропускаются.
    """

    def __init__(
        self,
        client: Client | None = None,
        concurrency: int = MAX_CONCURRENCY,
        on_progress=None,
        cancel_event: threading.Event | None = None,
    ):
        self.client = client or Client()
        self.concurrency = max(1, min(concurrency, MAX_CONCURRENCY))
        self.on_progress = on_progress
        self.cancel = cancel_event or threading.Event()
        self.progress = Progress()

    # ------------------------------------------------------------- служебное

    def _emit(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self.progress, key, value)
        if self.on_progress:
            self.on_progress(self.progress)

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    def _log_error(self, output_dir: Path, number: int, reason: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with (output_dir / ERROR_LOG).open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp}\tглава {number}\t{reason}\n")
        except OSError as exc:
            log.warning("Не удалось записать в %s: %s", ERROR_LOG, exc)

    # ----------------------------------------------------------------- поиск

    def find(self, query: str) -> api.Novel:
        self._emit(stage="search", message=f"Ищем книгу: {query}")
        novel = api.find_novel(self.client, query)
        self._emit(message=f"Найдено: {novel.name} ({novel.total_chapters} глав)")
        return novel

    # ------------------------------------------------------------- основное

    def run(
        self,
        novel: api.Novel,
        output_dir: Path,
        first: int = 1,
        last: int | None = None,
    ) -> Report:
        state = State(output_dir / STATE_FILE)
        state.data["novel"] = novel.to_dict()

        last = last or novel.total_chapters
        self._emit(stage="toc", message="Собираем оглавление…", done=0, total=last - first + 1)

        toc = api.fetch_toc(
            self.client,
            novel,
            first=first,
            last=last,
            on_progress=lambda d, t: self._emit(done=d, total=t),
        )
        self._check_cancel()

        state.data["missing_in_toc"] = toc.missing
        if toc.missing:
            self._log_error(
                output_dir, 0, f"нет в оглавлении: {_compact_ranges(toc.missing)}"
            )

        # Уже готовые главы не перекачиваем.
        pending = [ch for ch in toc.chapters if not state.is_done(ch.number, output_dir)]
        skipped = len(toc.chapters) - len(pending)

        self._emit(
            stage="probe",
            message="Проверяем, отдаёт ли REST текст глав…",
            done=0,
            total=len(pending),
            skipped=skipped,
        )

        mode = state.data.get("mode") or ""
        if not mode or not pending:
            probe_target = pending[0] if pending else (toc.chapters[0] if toc.chapters else None)
            mode = api.probe_content_mode(self.client, probe_target) if probe_target else api.MODE_HTML
            state.data["mode"] = mode
        state.save()

        mode_label = "JSON (без парсинга HTML)" if mode == api.MODE_REST else "HTML-страницы"
        self._emit(
            stage="download",
            message=f"Качаем {len(pending)} глав, источник текста: {mode_label}",
        )

        downloaded = 0
        failed: list[int] = []

        try:
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                batches = list(api.batched(pending, self.concurrency))
                for index, batch in enumerate(batches):
                    self._check_cancel()
                    results = list(
                        pool.map(
                            lambda ch: self._one(ch, novel, output_dir, mode, state), batch
                        )
                    )
                    for chapter, ok in zip(batch, results):
                        if ok:
                            downloaded += 1
                        else:
                            failed.append(chapter.number)

                    self._emit(
                        done=downloaded + len(failed),
                        downloaded=downloaded,
                        failed=len(failed),
                        message=f"Глава {batch[-1].number} из {last}",
                    )
                    state.save()

                    if index < len(batches) - 1:
                        polite_pause()  # пауза между пачками
        except Cancelled:
            state.save()
            self._emit(stage="cancelled", message="Остановлено. Прогресс сохранён — можно продолжить.")
            raise
        finally:
            state.save()

        report = Report(
            novel=novel.to_dict(),
            output_dir=str(output_dir),
            mode=mode,
            requested=len(toc.chapters) + len(toc.missing),
            downloaded=downloaded,
            skipped=skipped,
            failed=len(failed),
            failed_chapters=sorted(failed),
            missing_in_toc=toc.missing,
        )
        self._emit(
            stage="done",
            message=(
                f"Готово. Скачано {downloaded}, пропущено (уже было) {skipped}, "
                f"ошибок {len(failed)}."
            ),
            downloaded=downloaded,
            skipped=skipped,
            failed=len(failed),
        )
        return report

    def _one(
        self,
        chapter: api.Chapter,
        novel: api.Novel,
        output_dir: Path,
        mode: str,
        state: State,
    ) -> bool:
        """Скачивает и сохраняет одну главу. True — успех."""
        if self.cancel.is_set():
            return False
        try:
            title, text = api.fetch_chapter(self.client, chapter, mode)
            if not text.strip():
                raise ValueError("пустой текст главы")

            filename = chapter_filename(chapter.number, title or chapter.title)
            write_chapter(output_dir / filename, novel.name, title or chapter.title, chapter.number, text)
            state.mark_done(chapter.number, filename)
            return True
        except (HttpError, ValueError, OSError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            log.warning("Глава %s не скачана: %s", chapter.number, reason)
            state.mark_failed(chapter.number, reason)
            self._log_error(output_dir, chapter.number, reason)
            return False


class Cancelled(Exception):
    """Пользователь остановил скачивание."""


def _compact_ranges(numbers: list[int]) -> str:
    """[1,2,3,7] → '1-3, 7'."""
    if not numbers:
        return ""
    numbers = sorted(numbers)
    parts, start, prev = [], numbers[0], numbers[0]
    for n in numbers[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(parts)


def verify(output_dir: Path) -> dict:
    """Сверяет state.json с реально лежащими файлами."""
    state = State(output_dir / STATE_FILE)
    recorded = state.data.get("downloaded", {})
    present, lost = [], []
    for number, filename in recorded.items():
        (present if (output_dir / filename).exists() else lost).append(int(number))

    total = int((state.data.get("novel") or {}).get("total_chapters") or 0)
    have = set(present)
    missing = [n for n in range(1, total + 1) if n not in have] if total else []

    return {
        "novel": state.data.get("novel", {}),
        "total_chapters": total,
        "on_disk": len(present),
        "lost_files": sorted(lost),
        "missing": missing,
        "missing_compact": _compact_ranges(missing),
        "failed": {int(k): v for k, v in state.data.get("failed", {}).items()},
    }
