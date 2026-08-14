"""Смысловой анализ: сбор фактов и сведение их в реестр.

Существующие проверки ловят механику — разметку, кодировку, повторы. Они
не находят ошибку в грамматически правильном предложении: чтобы заметить,
что персонаж призвал чужого питомца, надо знать, чей он.

Модуль не знает, какая модель отвечает и по какому адресу: клиент ему
передают снаружи. Поэтому его можно проверить без сети и без ключа.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from core.models import OpReport
from core.registry import Entity, Event, Link, Registry, slug
from llm import prompts
from llm.cache import Entry, FactsCache, fingerprint, parse_json

from .base import Progress, collect_files, read_all

log = logging.getLogger(__name__)


@dataclass
class FactsReport:
    """Итог сбора фактов."""

    total: int = 0
    parsed: int = 0
    cached: int = 0
    failed: int = 0
    failures: list = field(default_factory=list)
    output: str = ""

    def fail(self, chapter, reason: str) -> None:
        self.failures.append({"chapter": chapter, "reason": reason})
        self.failed += 1

    def as_dict(self) -> dict:
        return {
            "total": self.total, "parsed": self.parsed, "cached": self.cached,
            "failed": self.failed, "failures": self.failures,
            "output": self.output,
            # Общий блок результата на всех вкладках ждёт эти два поля.
            "written": self.parsed + self.cached,
            "failed_files": [f"глава {f['chapter']}: {f['reason']}"
                             for f in self.failures],
        }


def scan(targets, root: Path | None = None) -> dict:
    """Что предстоит разобрать и сколько уже готово."""
    from llm.client import estimate

    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report)

    base = Path(root) if root else _root_of(files)
    cache = FactsCache(base)
    ready = sum(
        1 for chapter in chapters
        if cache.fresh(chapter.number, chapter.text, chapter.source) is not None
    )

    return {
        "file_count": len(files),
        "total": len(chapters),
        "cached": ready,
        "root": str(base),
        "estimate": estimate(chapters, ready).as_dict(),
        "unreadable": [failure.as_text() for failure in report.failures],
    }


def _root_of(files) -> Path:
    """Папка книги: рядом с ней ляжет analysis/."""
    if not files:
        return Path.cwd()
    first = Path(files[0])
    return first.parent if first.is_file() else first


def collect(
    targets,
    client,
    root: Path | None = None,
    model: str = "",
    concurrency: int | None = None,
    retries: int | None = None,
    progress: Progress | None = None,
    force: bool = False,
) -> FactsReport:
    """Разбирает главы моделью и складывает факты в кэш.

    Ответ, который не разобрался, повторяется до `retries` раз; после этого
    глава помечается необработанной, но прогон продолжается — одна глава не
    должна ронять пятьсот.
    """
    progress = progress or Progress()
    concurrency = concurrency or settings.llm.concurrency
    retries = settings.llm.max_retries if retries is None else retries

    read = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, read, progress)
    if not chapters:
        detail = read.failures[0].as_text() if read.failures else ""
        raise ValueError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    base = Path(root) if root else _root_of(files)
    cache = FactsCache(base)
    report = FactsReport(total=len(chapters), output=str(base / "analysis"))

    # Что уже разобрано — заново не шлём: разбор стоит денег.
    pending = []
    for chapter in chapters:
        if not force and cache.fresh(chapter.number, chapter.text, chapter.source):
            report.cached += 1
        else:
            pending.append(chapter)

    done = report.cached
    lock = threading.Lock()
    total = len(chapters)
    progress.step(done, total, f"В кэше {done} из {total}")

    def one(chapter):
        nonlocal done
        progress.check()
        prompt = prompts.facts(chapter.number, chapter.title, chapter.text)
        error = ""

        for attempt in range(retries + 1):
            progress.check()
            try:
                answer = client.generate(prompt, json_only=True, model=model)
                facts = parse_json(answer)
                cache.put(Entry(
                    number=chapter.number,
                    title=chapter.title,
                    source=chapter.source,
                    fingerprint=fingerprint(chapter.text),
                    model=model or settings.llm.model,
                    facts=facts,
                ))
                with lock:
                    report.parsed += 1
                    done += 1
                    progress.step(done, total,
                                  f"Глава {chapter.label or '?'} разобрана")
                return
            except Exception as exc:  # noqa: BLE001 — причину показываем целиком
                error = f"{type(exc).__name__}: {exc}"
                log.warning("Глава %s, попытка %s: %s",
                            chapter.label, attempt + 1, error)

        with lock:
            report.fail(chapter.label or chapter.title, error)
            done += 1
            progress.step(done, total, f"Глава {chapter.label or '?'} не разобрана")

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = [pool.submit(one, chapter) for chapter in pending]
            for future in as_completed(futures):
                # Отмена прилетает сюда исключением — пробрасываем наверх.
                future.result()

    return report


# ------------------------------------------------------------------- реестр


def build_registry(root: Path, keep: Registry | None = None) -> Registry:
    """Сводит факты из кэша в общий реестр.

    Подтверждённые записи сохраняются: человек уже сказал, как правильно,
    и пересборка не должна затирать его правку.
    """
    cache = FactsCache(Path(root))
    registry = Registry()

    if keep is not None:
        # Переносим то, что подтверждено вручную или пришло из глоссария.
        for entity in keep.entities.values():
            if entity.confirmed:
                registry.entities[entity.id] = entity
        registry.links = [link for link in keep.links if link.confirmed]

    for entry in cache.entries():
        number = entry.number
        facts = entry.facts or {}
        if number is None:
            number = facts.get("chapter")

        for item in facts.get("entities") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            registry.add_entity(Entity(
                name=name,
                type=str(item.get("type") or "термин"),
                status=str(item.get("status") or "жив"),
                first_chapter=number,
                attributes={str(k): v for k, v in (item.get("attributes") or {}).items()},
            ))

        for item in facts.get("links") or []:
            source = registry.find(str(item.get("from") or ""))
            target = registry.find(str(item.get("to") or ""))
            kind = str(item.get("type") or "").strip()
            if source is None or target is None or not kind:
                continue
            registry.add_link(Link(source=source.id, target=target.id,
                                   type=kind, since_chapter=number))

        for item in facts.get("events") or []:
            actor = registry.find(str(item.get("actor") or ""))
            obj = registry.find(str(item.get("object") or ""))
            registry.add_event(Event(
                chapter=number,
                type=str(item.get("type") or ""),
                actor=actor.id if actor else slug(str(item.get("actor") or "")),
                object=obj.id if obj else slug(str(item.get("object") or "")),
                quote=str(item.get("quote") or ""),
            ))

        if number is not None and number not in registry.chapters:
            registry.chapters.append(number)

    return registry


def load_registry(root: Path) -> Registry:
    return Registry.load(FactsCache(Path(root)).registry_path)


def save_registry(root: Path, registry: Registry) -> Path:
    path = FactsCache(Path(root)).registry_path
    registry.save(path)
    return path


def rebuild(root: Path) -> Registry:
    """Пересобирает реестр из кэша, сохраняя подтверждённое."""
    registry = build_registry(root, keep=load_registry(root))
    save_registry(root, registry)
    return registry
