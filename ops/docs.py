"""Выгрузка готового текста в файл — карточки, пересказ, аннотация.

Отдельно от `core/writers`, потому что это не главы книги: у карточек нет
номера, части и названия, и притворяться главой ради записи им незачем.
Форматы те же два, что просит ТЗ: `.md` как есть и `.docx` через общее
оформление.

Заголовки размечены решёткой — так текст читается и без всякой обработки,
а при записи в `.docx` из них получаются настоящие заголовки.
"""

from __future__ import annotations

from pathlib import Path

FORMATS = (".md", ".docx", ".txt")


class ExportError(Exception):
    """Записать не удалось."""


def _docx(text: str, path: Path, style=None) -> None:
    from mvl.word import DocxUnavailable, Style, new_document

    try:
        document = new_document(style or Style())
    except DocxUnavailable as exc:
        raise ExportError(str(exc)) from exc

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            document.add_heading(stripped.lstrip("#").strip(), level=min(level, 4))
        else:
            document.add_paragraph(stripped)

    try:
        document.save(str(path))
    except OSError as exc:
        raise ExportError(f"Не удалось записать {path}: {exc}") from exc


def save(text: str, path, style=None) -> str:
    """Пишет текст в файл. Расширение решает, каким он будет."""
    path = Path(str(path)).expanduser()
    if path.suffix.lower() not in FORMATS:
        raise ExportError(
            f"Не умею писать {path.suffix or 'файл без расширения'} — "
            f"нужен один из {', '.join(FORMATS)}")
    if not (text or "").strip():
        raise ExportError("Нечего выгружать: текст пуст")

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".docx":
        _docx(text, path, style)
    else:
        try:
            path.write_text(text.rstrip() + "\n", encoding="utf-8")
        except OSError as exc:
            raise ExportError(f"Не удалось записать {path}: {exc}") from exc
    return str(path)
