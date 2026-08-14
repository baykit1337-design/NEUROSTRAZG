"""Настройки NEUROSTRAZH — все в одном месте.

Никаких захардкоженных таймаутов, путей и ключей в коде. Значения можно
переопределить в `config.json` рядом с проектом; этот файл в `.gitignore`,
потому что в нём лежат ключи.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"


@dataclass
class Network:
    """Таймауты и вежливость к сайту."""

    #: Страница главы весит ~220 КБ, за 30 секунд не успевает.
    read_timeout: int = 120
    connect_timeout: int = 15
    max_timeout: int = 300
    max_attempts: int = 3
    #: Витрина: пауза между главами при одном потоке.
    pause_range: tuple[float, float] = (2.0, 4.0)
    #: Пауза между пачками при многопоточном скачивании.
    batch_pause_range: tuple[float, float] = (1.0, 2.0)


@dataclass
class Threads:
    """Многопоточность. Выше max сайт заваливать не нужно."""

    default: int = 3
    max: int = 6
    #: Сколько глав качает пробный прогон и в сколько потоков.
    probe_chapters: int = 5
    probe_threads: int = 3
    #: Проба идёт без повторов: способ, которому нужны три попытки на
    #: главу, не рабочий, а повторы вдобавок портят замер времени.
    probe_attempts: int = 1
    #: Во сколько раз пачка должна обгонять последовательное скачивание.
    #: 1.7 отбраковывал рабочие способы: сеть шумит, и разброс времени
    #: между главами сам по себе съедает часть выигрыша.
    probe_speedup: float = 1.3


@dataclass
class Proxies:
    file: str = "proxies.txt"
    check_timeout: int = 60
    geo_timeout: int = 15
    check_concurrency: int = 5


@dataclass
class Output:
    """Значения по умолчанию для вывода."""

    format: str = ".txt"
    encoding: str = "utf-8"
    font: str = "Times New Roman"
    size: int = 12
    line_spacing: float = 1.5
    first_line_indent_cm: float = 0.0
    align: str = "left"
    page_break_between_chapters: bool = True


@dataclass
class Llm:
    """Смысловой анализ. Ключ здесь не хранится в репозитории."""

    api_key: str = ""
    model: str = "gemini-2.0-flash"
    concurrency: int = 3
    max_retries: int = 2
    #: Пауза между запросами, чтобы не упереться в лимиты ключа.
    rate_limit_pause: float = 0.0


@dataclass
class Config:
    network: Network = field(default_factory=Network)
    threads: Threads = field(default_factory=Threads)
    proxies: Proxies = field(default_factory=Proxies)
    output: Output = field(default_factory=Output)
    llm: Llm = field(default_factory=Llm)
    #: Метод многопоточности, сработавший в прошлый раз, — пробуем первым.
    last_download_method: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Читает config.json, если он есть. Иначе значения по умолчанию."""
        path = path or CONFIG_FILE
        config = cls()
        if not path.is_file():
            return config

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Битый config.json не должен мешать работе.
            return config

        for section, values in data.items():
            if section == "last_download_method":
                config.last_download_method = str(values or "")
                continue
            target = getattr(config, section, None)
            if target is None or not isinstance(values, dict):
                continue
            for key, value in values.items():
                if hasattr(target, key):
                    setattr(target, key, value)
        return config

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_FILE
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @property
    def llm_key(self) -> str:
        """Ключ из настроек либо из переменной окружения."""
        return self.llm.api_key or os.environ.get("GEMINI_API_KEY", "")


#: Общий экземпляр — его импортируют модули.
settings = Config.load()
