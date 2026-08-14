"""Пакет тестов.

Журнал операций и корзина живут рядом с программой. Прогон тестов не
должен их трогать: настоящая история пользователя — не свалка для
временных данных. Поэтому здесь, до любого импорта `ops.history`, путь
уводится во временную папку.
"""

import atexit
import os
import shutil
import tempfile

_TEMP = tempfile.mkdtemp(prefix="neurostrazh-tests-")
os.environ.setdefault("NEUROSTRAZH_DATA", _TEMP)
atexit.register(shutil.rmtree, _TEMP, ignore_errors=True)
