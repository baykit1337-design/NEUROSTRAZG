"""Осмотр скачанной папки: всё ли на месте (пункт 5).

Проверяется не «функция вернула словарь», а то, ради чего она написана:
пропущенная глава названа, целая книга не обвиняется зря, а выброс не
превращает список пропусков в шестьсот номеров.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import checkup  # noqa: E402
from ops.base import Cancelled, Progress  # noqa: E402


def body(number: int = 0) -> str:
    """Текст главы. У каждой свой: одинаковые главы — уже находка."""
    return f"Глава {number}. Здесь про своё место, своих людей и свой день. " * 6


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def book(self, numbers=range(1, 21), **odd):
        """Папка с главами. `odd` — имя файла в свой текст."""
        folder = self.tmp / "книга"
        folder.mkdir(parents=True, exist_ok=True)
        for number in numbers:
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n{body(number)}", encoding="utf-8")
        for name, text in odd.items():
            (folder / f"{name}.txt").write_text(text, encoding="utf-8")
        return folder

    def kinds(self, look):
        return {trouble.kind: trouble for trouble in look.troubles}


class TestWholeBook(Base):
    def test_a_book_with_nothing_wrong_says_so(self):
        """Проверка, которая ругается всегда, не проверка."""
        look = checkup.look(self.book())
        self.assertTrue(look.clean, look.summary())
        self.assertEqual(look.chapters, 20)
        self.assertEqual((look.first, look.last), (1, 20))
        self.assertIn("всё на месте", look.summary())

    def test_the_summary_counts_chapters(self):
        look = checkup.look(self.book())
        self.assertIn("Глав: 20", look.summary())
        self.assertIn("1–20", look.summary())


class TestNumbering(Base):
    def test_a_missing_chapter_is_named(self):
        folder = self.book()
        (folder / "Глава 7.txt").unlink()
        look = checkup.look(folder)

        trouble = self.kinds(look)["missing"]
        self.assertEqual(trouble.size, 1)
        self.assertIn("7", trouble.where)
        self.assertTrue(trouble.hole)

    def test_a_run_of_missing_chapters_is_one_line(self):
        """«205, 206, 207, 208» глазами не читается, «205–208» читается."""
        folder = self.book()
        for number in (5, 6, 7, 8):
            (folder / f"Глава {number}.txt").unlink()
        trouble = self.kinds(checkup.look(folder))["missing"]

        self.assertEqual(trouble.where, ["5–8"])
        # Свёрнутая строка одна, а глав потеряно четыре — и счётчик
        # должен говорить про главы, а не про строки.
        self.assertEqual(trouble.size, 4)

    def test_a_stray_number_does_not_invent_hundreds_of_gaps(self):
        """Одна глава 9001 среди двадцати — это выброс, а не дыра в
        восемь тысяч девятьсот глав."""
        folder = self.book()
        (folder / "Глава 9001.txt").write_text(
            f"Глава 9001\n\n{body(9001)}", encoding="utf-8")
        look = checkup.look(folder)

        self.assertNotIn("missing", self.kinds(look))
        self.assertEqual(self.kinds(look)["stray"].where, ["9001"])
        self.assertEqual((look.first, look.last), (1, 20))

    def test_two_files_with_one_number_name_both(self):
        folder = self.book()
        (folder / "Глава 12 копия.txt").write_text(
            f"Глава 12\n\n{body(120)}", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["doubles"]

        self.assertEqual(trouble.size, 1)
        self.assertIn("Глава 12 копия.txt", trouble.where[0])
        self.assertIn("Глава 12.txt", trouble.where[0])

    def test_a_hole_in_the_parts_is_found(self):
        folder = self.book()
        for part in (1, 3):
            (folder / f"Глава 21.{part}.txt").write_text(
                f"Глава 21.{part}\n\n{body(210 + part)}", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["parts"]

        self.assertEqual(trouble.where, ["21.2"])

    def test_a_chapter_without_a_number_is_only_worth_a_look(self):
        """Послесловие — не дыра в книге, и красным его звать нечего."""
        folder = self.book(послесловие=f"Послесловие\n\n{body(99)}")
        trouble = self.kinds(checkup.look(folder))["nameless"]

        self.assertFalse(trouble.hole)
        self.assertEqual(trouble.where, ["послесловие.txt"])


class TestBodies(Base):
    def test_an_empty_chapter_is_a_hole(self):
        folder = self.book()
        (folder / "Глава 9.txt").write_text("Глава 9\n\n", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["empty"]

        self.assertTrue(trouble.hole)
        self.assertEqual(trouble.where, ["Глава 9.txt"])

    def test_a_chapter_cut_mid_word_is_found(self):
        folder = self.book()
        (folder / "Глава 9.txt").write_text(
            "Глава 9\n\nОн шагнул вперёд и увидел, что дверь откр",
            encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["cut"]

        self.assertEqual(trouble.where, ["Глава 9.txt"])

    def test_a_finished_chapter_is_not_called_cut(self):
        """Точка, многоточие, закрытая кавычка — глава дописана."""
        folder = self.book(numbers=range(1, 6))
        for number, tail in ((1, "."), (2, "…"), (3, "»"), (4, "!"), (5, "?")):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n{body(number).strip()[:-1]}{tail}", encoding="utf-8")
        self.assertNotIn("cut", self.kinds(checkup.look(folder)))

    def test_a_chapter_far_shorter_than_the_rest_is_suspicious(self):
        folder = self.book()
        (folder / "Глава 9.txt").write_text(
            "Глава 9\n\nОн ушёл.", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["short"]

        self.assertIn("Глава 9.txt", trouble.where[0])
        # Подписи мало: «короткая» без «короткая по сравнению с чем»
        # ничего не говорит.
        self.assertIn("знаков", trouble.detail)

    def test_a_short_book_is_not_measured_against_its_own_median(self):
        """В книге из трёх глав любая может быть вчетверо короче другой
        просто так, и обвинять её не в чем."""
        folder = self.book(numbers=range(1, 4))
        (folder / "Глава 2.txt").write_text(
            "Глава 2\n\nОн ушёл.", encoding="utf-8")
        self.assertNotIn("short", self.kinds(checkup.look(folder)))


class TestRepeats(Base):
    def test_the_same_text_under_two_numbers_is_found(self):
        """Качалка кладёт одну и ту же страницу под двумя номерами, когда
        сайт отдаёт заглушку вместо главы. По номерам это незаметно."""
        folder = self.book()
        same = "Совершенно одинаковый текст двух разных глав. " * 8
        for number in (4, 15):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n{same}", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["same"]

        # Считаются главы, а не пары: сотня одинаковых заглушек даёт пять
        # тысяч пар, и такое число только пугает.
        self.assertEqual(trouble.size, 2)
        self.assertIn("4", trouble.where[0])
        self.assertIn("15", trouble.where[0])

    def test_repeats_are_counted_in_chapters_not_in_pairs(self):
        """Сайт отдал одну заглушку вместо пяти глав — это пять глав, а
        не десять пар."""
        folder = self.book()
        stub = "Страница временно недоступна, попробуйте позже. " * 8
        for number in (3, 6, 9, 12, 18):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n{stub}", encoding="utf-8")
        self.assertEqual(self.kinds(checkup.look(folder))["same"].size, 5)

    def test_different_chapters_are_not_called_repeats(self):
        folder = self.tmp / "разные"
        folder.mkdir()
        for number in range(1, 11):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n" + f"Совсем разный текст главы {number}. "
                + "Здесь про другое место, других людей и другой день. " * 4,
                encoding="utf-8")
        self.assertNotIn("same", self.kinds(checkup.look(folder)))


class TestOrderAndLimits(Base):
    def test_holes_come_before_things_to_look_at(self):
        """С дыр начинают. Если они внизу списка, их не увидят."""
        folder = self.book(послесловие=f"Послесловие\n\n{body(99)}")
        (folder / "Глава 7.txt").unlink()
        look = checkup.look(folder)

        holes = [t.hole for t in look.troubles]
        self.assertEqual(holes, sorted(holes, reverse=True))
        self.assertGreaterEqual(look.holes, 1)

    def test_the_summary_names_holes_and_counts_the_rest(self):
        folder = self.book(послесловие=f"Послесловие\n\n{body(99)}")
        (folder / "Глава 7.txt").unlink()
        summary = checkup.look(folder).summary()

        self.assertIn("пропущенные главы: 1", summary.lower())
        self.assertIn("присмотреться", summary)

    def test_a_long_list_is_cut_but_the_count_is_not(self):
        """Полторы тысячи имён в отчёте — это отчёт, который не читают."""
        folder = self.book(numbers=range(1, 200))
        for number in range(1, 200, 2):
            (folder / f"Глава {number}.txt").write_text(
                f"Глава {number}\n\n", encoding="utf-8")
        trouble = self.kinds(checkup.look(folder))["empty"]

        self.assertEqual(len(trouble.as_dict()["where"]), checkup.SHOW)
        self.assertEqual(trouble.as_dict()["count"], 100)
        self.assertEqual(trouble.as_dict()["more"], 100 - checkup.SHOW)

    def test_every_kind_has_a_name_for_the_page(self):
        """Страница берёт подписи отсюда: род без имени показать нечем."""
        folder = self.book(послесловие=f"Послесловие\n\n{body(99)}")
        (folder / "Глава 7.txt").unlink()
        (folder / "Глава 9.txt").write_text("Глава 9\n\n", encoding="utf-8")

        for trouble in checkup.look(folder).troubles:
            with self.subTest(trouble.kind):
                self.assertIn(trouble.kind, checkup.KINDS)
                self.assertTrue(trouble.as_dict()["kind_name"])


class Names(Base):
    """Папка, в которой важны только имена файлов."""

    def folder(self, names, where: str = "OEBPS") -> Path:
        folder = self.tmp / where
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            # Пустые: проверка по именам файлы не открывает вовсе, и
            # содержимое здесь ни при чём.
            (folder / name).write_text("", encoding="utf-8")
        return folder

    def slice(self, first=294, last=382, missing_first=(), missing_second=(),
              gone=(), title="Reaping_a_Rich_Harvest", suffix=".xhtml",
              extra: str = ""):
        """Слив в OEBPS: у главы две части, вторая помечена цифрой в хвосте.

        `missing_first` — номера, у которых нет первой части, `missing_second`
        — второй, `gone` — которых нет вовсе.
        """
        names, seq = [], 1
        for number in range(first, last + 1):
            if number in gone:
                continue
            if number not in missing_first:
                names.append(f"{seq:04d}_Chapter_{number}_{title}{extra}{suffix}")
                seq += 1
            if number not in missing_second:
                names.append(f"{seq:04d}_Chapter_{number}_{title}_2{extra}{suffix}")
                seq += 1
        return names


class TestTheFolderNamesTheMissingPart(Names):
    """Ради этого проверка и написана.

    Готовая книга говорит «под номером 303 глав меньше, чем у соседей», и
    дальше человек остаётся один на один с папкой в несколько сотен
    файлов. Здесь ответ точный: нет 303.1.
    """

    def test_the_missing_half_is_named_by_its_part(self):
        look = checkup.look_names(self.folder(self.slice(
            missing_first=(303, 330), missing_second=(294, 341))))
        found = self.kinds(look)["parts"]

        self.assertEqual(found.where, ["294.2", "303.1", "330.1", "341.2"])
        self.assertEqual(found.count, 4)

    def test_a_number_gone_whole_is_a_missing_chapter_not_a_part(self):
        """Пропала глава целиком — это другая беда и другое слово."""
        look = checkup.look_names(self.folder(self.slice(gone=(300,))))
        found = self.kinds(look)

        self.assertEqual(found["missing"].where, ["300"])
        self.assertNotIn("parts", found)

    def test_a_folder_with_everything_in_place_is_not_accused(self):
        """Проверка, которая ругается всегда, не проверка."""
        look = checkup.look_names(self.folder(self.slice()))

        self.assertTrue(look.clean, look.summary())
        self.assertEqual((look.first, look.last), (294, 382))

    def test_the_same_part_twice_is_a_double(self):
        names = self.slice()
        names.append("9999_Chapter_300_Reaping_a_Rich_Harvest_2.xhtml")
        found = self.kinds(checkup.look_names(self.folder(names)))

        self.assertEqual(found["doubles"].where, ["300.2"])

    def test_the_names_are_enough_to_answer(self):
        """Файлы не читаются вовсе — иначе на тысяче глав пришлось бы ждать."""
        folder = self.folder(self.slice(missing_first=(303,)))
        for path in folder.iterdir():
            self.assertEqual(path.read_text(encoding="utf-8"), "")
        self.assertEqual(
            self.kinds(checkup.look_names(folder))["parts"].where, ["303.1"])


class TestTheTranslatorsSignature(Names):
    """Переводчик дописывает подпись к каждому имени, и номер части
    перестаёт быть последним."""

    def test_a_common_tail_is_taken_off_before_the_parts_are_read(self):
        look = checkup.look_names(self.folder(self.slice(
            missing_first=(303,), suffix=".html", extra="_translated_gemini")))

        self.assertEqual(self.kinds(look)["parts"].where, ["303.1"])

    def test_the_tail_that_was_taken_off_is_shown(self):
        """Разбор мог ошибиться — тогда это видно сразу."""
        look = checkup.look_names(self.folder(self.slice(
            suffix=".html", extra="_translated_gemini")))

        self.assertEqual(self.kinds(look)["tail"].where, ["_translated_gemini"])

    def test_a_tail_ending_in_a_digit_is_not_taken_off(self):
        """У папки, где вторая часть есть у каждой главы, общим хвостом
        окажется сам «_2» — и снять его значило бы стереть пометку части
        со всех файлов разом."""
        self.assertEqual(
            checkup.common_tail([f"Глава_{n}_2" for n in range(1, 20)]), "")

    def test_a_tail_that_is_not_a_whole_word_is_not_taken_off(self):
        """«ранslated_gemini» хвостом не является: резать имя посередине
        значит выдумывать."""
        self.assertEqual(checkup.common_tail(["Глава1рост", "Глава2рост"]), "")

    def test_a_lone_file_keeps_its_whole_name(self):
        """Общего хвоста у одного имени нет: он и есть всё имя."""
        self.assertEqual(checkup.common_tail(["Глава_1_перевод"]), "")


class TestTheRowNeedsEvidence(Names):
    """Хвостовая цифра — часть не всегда: «Level 2» выглядит так же.
    Доказательство берётся у всей папки сразу."""

    def test_two_files_are_not_a_row(self):
        """В папке из двух файлов «у каждого номера по две части» значит
        только то, что файлов всего два."""
        self.assertEqual(checkup.usual_row({1: [1, 2], 2: [1, 2]}), ())

    def test_a_row_the_minority_lives_by_is_no_row(self):
        """Разнобой рядом не считается: самый частый ряд здесь всё равно
        встречается реже, чем не встречается, — и объявлять его нормой
        значило бы обвинить в пропаже две трети папки."""
        rows = {number: [1, 2] for number in range(1, 11)}
        rows.update({number: [1] for number in range(11, 19)})
        rows.update({number: [1, 2, 3] for number in range(19, 27)})

        self.assertEqual(checkup.usual_row(rows), ())

    def test_titles_ending_in_a_digit_do_not_invent_parts(self):
        """У каждой главы свой файл, а название кончается числом. Ряда тут
        нет, и обвинять папку в пропаже частей не в чем."""
        names = [f"{n:04d}_Chapter_{n}_Level_{n % 7 + 2}.xhtml"
                 for n in range(1, 60)]
        look = checkup.look_names(self.folder(names))

        self.assertNotIn("parts", self.kinds(look))
        self.assertTrue(look.clean, look.summary())

    def test_two_unmarked_files_under_one_number_name_no_part(self):
        """Обе части без пометки неразличимы: сказать, какой не хватает,
        нечего, — и выдумывать ответ нельзя."""
        self.assertEqual(checkup.usual_row(
            {number: [1, 1] for number in range(1, 30)}), ())


class TestWhenTheRowIsUnknown(Names):
    """Ряда нет — назвать пропавшую часть нечем. Но сказать, где файлов
    меньше, чем у соседей, всё равно надо: пропажу в такой папке иначе не
    видно вовсе, номер-то на месте."""

    def two_each(self, thin=()):
        names = []
        for number in range(1, 40):
            names.append(f"Глава {number}.xhtml")
            if number not in thin:
                names.append(f"Глава {number} (продолжение).xhtml")
        return names

    def test_a_number_with_fewer_files_is_found(self):
        found = self.kinds(checkup.look_names(self.folder(self.two_each(thin=(7, 20)))))

        self.assertEqual(found["thin"].where, ["7", "20"])
        self.assertIn("2", found["thin"].detail)

    def test_a_folder_where_every_number_has_the_same_is_not_accused(self):
        look = checkup.look_names(self.folder(self.two_each()))

        self.assertTrue(look.clean, look.summary())


class TestThePageGetsTheAnswer(Names):
    """Отчёт должен доехать до страницы целиком: подписи находок она берёт
    с сервера и второго их экземпляра у себя не держит."""

    def setUp(self):
        super().setUp()
        from webapp.app import app

        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_the_missing_parts_reach_the_page(self):
        folder = self.folder(self.slice(missing_first=(303,)))
        res = self.client.post("/api/checkup/names",
                               json={"targets": [str(folder)]})
        self.assertEqual(res.status_code, 200)

        report = res.get_json()["report"]
        found = {row["kind"]: row for row in report["troubles"]}
        self.assertEqual(found["parts"]["where"], ["303.1"])
        self.assertTrue(found["parts"]["kind_name"])
        self.assertIn("пропущенные части: 1", report["summary"])

    def test_nothing_chosen_is_answered_not_crashed(self):
        res = self.client.post("/api/checkup/names", json={"targets": []})
        self.assertEqual(res.status_code, 400)
        self.assertTrue(res.get_json()["error"])


class TestStopping(Base):
    def test_stopping_the_look_stops_it(self):
        """Осмотр читает всю книгу. Не прерывался бы — кнопка «Остановить»
        врала бы."""
        progress = Progress()
        progress.cancel.set()
        with self.assertRaises(Cancelled):
            checkup.look(self.book(), progress)


if __name__ == "__main__":
    unittest.main()
