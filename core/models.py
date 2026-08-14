"""Внутреннее представление книги — единственное на весь проект.

Любой читатель отдаёт эти объекты, любой писатель принимает их. Ни одна
операция не работает с форматами напрямую: только через `Chapter` и `Book`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chapter:
    """Одна глава: номер, часть, название и абзацы.

    Абзацы хранятся списком, а не одной строкой: склейка и разбиение —
    дело писателя, а не хранилища.
    """

    number: int | None = None
    part: int | None = None
    title: str = ""
    paragraphs: list[str] = field(default_factory=list)
    #: Откуда глава пришла — нужно для отчётов об ошибках.
    source: str = ""

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def size(self) -> int:
        return sum(len(p) for p in self.paragraphs)

    @property
    def label(self) -> str:
        """Номер с частью: «201.2» или просто «201»."""
        if self.number is None:
            return ""
        return f"{self.number}.{self.part}" if self.part else str(self.number)

    def as_dict(self) -> dict:
        return {
            "number": self.number,
            "part": self.part,
            "title": self.title,
            "size": self.size,
            "paragraphs": len(self.paragraphs),
            "source": self.source,
        }


@dataclass
class Book:
    """Книга — просто упорядоченный набор глав плюс метаданные."""

    title: str = ""
    author: str = ""
    chapters: list[Chapter] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.chapters)

    def __iter__(self):
        return iter(self.chapters)

    @property
    def size(self) -> int:
        return sum(chapter.size for chapter in self.chapters)

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "total": len(self.chapters),
            "size": self.size,
        }


@dataclass
class Failure:
    """Что и на каком шаге не получилось. Операции не глотают ошибки."""

    file: str
    step: str
    error: str

    def as_text(self) -> str:
        return f"{self.file} — {self.step}: {self.error}"

    def as_dict(self) -> dict:
        return {"file": self.file, "step": self.step, "error": self.error}


@dataclass
class OpReport:
    """Итог операции — одинаковый для всех вкладок."""

    output: str = ""
    total: int = 0
    written: int = 0
    failed: int = 0
    failures: list[Failure] = field(default_factory=list)
    #: Числа, своеобразные для операции: сколько замен сделано, сколько
    #: строк убрано. Общие поля от них не разрастаются.
    extra: dict = field(default_factory=dict)

    def fail(self, file: str, step: str, error: str) -> None:
        self.failures.append(Failure(file, step, error))
        self.failed += 1

    def as_dict(self) -> dict:
        return {
            "output": self.output,
            "total": self.total,
            "written": self.written,
            "failed": self.failed,
            "failures": [f.as_dict() for f in self.failures],
            "failed_files": [f.as_text() for f in self.failures],
            **self.extra,
        }
