"""Жанры, теги, статус и язык — по-русски.

Каталог отдаёт их по-английски, и карточка книги была английской целиком:
«Ongoing · Chinese», «Accelerated Growth», «Overpowered Protagonist».
Читает эту карточку русскоязычный человек, и половину слов там надо
переводить в уме.

Словарь, а не модель, и это не экономия. Список слов у каталога закрытый
и повторяется из книги в книгу: те же три десятка жанров и та же пара
сотен тегов. Гонять их через платную модель на каждой книге значило бы
платить за один и тот же перевод сто раз — и получать его каждый раз
чуть другим, а теги должны совпадать буквально: по ним ищут.

Незнакомое слово остаётся как есть. Это честнее выдумки: увидев чужое
слово, человек поймёт, что его не перевели, а увидев неверный перевод —
не поймёт ничего.

Перевод здесь не хранится: он ничего не стоит и считается заново при
каждом показе. Место под хранение (`genres_ru` и прочие) отведено тому
переводу, который делает модель, — он стоит денег, и затирать его нельзя.
"""

from __future__ import annotations

import re

#: Жанры каталога. Список закрытый, это весь он.
GENRES = {
    "action": "боевик",
    "adult": "для взрослых",
    "adventure": "приключения",
    "comedy": "комедия",
    "drama": "драма",
    "ecchi": "этти",
    "eastern fantasy": "восточное фэнтези",
    "fantasy": "фэнтези",
    "gender bender": "смена пола",
    "harem": "гарем",
    "historical": "историческое",
    "horror": "ужасы",
    "isekai": "исекай",
    "josei": "дзёсэй",
    "litrpg": "литрпг",
    "magical realism": "магический реализм",
    "martial arts": "боевые искусства",
    "mature": "для взрослых, 18+",
    "mecha": "меха",
    "military": "военное",
    "mystery": "детектив",
    "psychological": "психологическое",
    "romance": "романтика",
    "school life": "школа",
    "sci fi": "фантастика",
    "science fiction": "фантастика",
    "seinen": "сэйнэн",
    "shoujo": "сёдзё",
    "shoujo ai": "сёдзё-ай",
    "shounen": "сёнэн",
    "shounen ai": "сёнэн-ай",
    "slice of life": "повседневность",
    "smut": "эротика",
    "sports": "спорт",
    "supernatural": "сверхъестественное",
    "tragedy": "трагедия",
    "urban": "городское",
    "video games": "игры",
    "wuxia": "уся",
    "xianxia": "сянься",
    "xuanhuan": "сюаньхуань",
    "yaoi": "яой",
    "yuri": "юри",
}

#: Теги сайта. Их сотни; здесь те, что встречаются постоянно. Незнакомый
#: тег остаётся английским — и это видно, а значит поправимо.
TAGS = {
    "abusive characters": "жестокие персонажи",
    "accelerated growth": "ускоренный рост",
    "adapted to anime": "есть аниме",
    "adapted to drama": "есть дорама",
    "adapted to manhua": "есть маньхуа",
    "adapted to manga": "есть манга",
    "advanced technology": "высокие технологии",
    "alchemy": "алхимия",
    "aliens": "инопланетяне",
    "alternate world": "иной мир",
    "amnesia": "амнезия",
    "ancient times": "древние времена",
    "androids": "андроиды",
    "angels": "ангелы",
    "animal characteristics": "звериные черты",
    "animal rearing": "разведение животных",
    "antihero protagonist": "герой-антигерой",
    "apocalypse": "апокалипсис",
    "appearance changes": "смена внешности",
    "arranged marriage": "брак по договорённости",
    "artifact crafting": "создание артефактов",
    "artifacts": "артефакты",
    "assassins": "убийцы",
    "beast companions": "звери-спутники",
    "beastkin": "звериный народ",
    "beautiful female lead": "красивая героиня",
    "betrayal": "предательство",
    "black belly": "себе на уме",
    "blacksmith": "кузнец",
    "bloodlines": "родословные",
    "body tempering": "закалка тела",
    "books": "книги",
    "brotherhood": "братство",
    "business management": "управление делом",
    "calm protagonist": "хладнокровный герой",
    "cannibalism": "каннибализм",
    "card games": "карточные игры",
    "carefree protagonist": "беззаботный герой",
    "caring protagonist": "заботливый герой",
    "cautious protagonist": "осторожный герой",
    "character growth": "рост героя",
    "cheats": "читы",
    "childcare": "воспитание детей",
    "clan building": "создание клана",
    "clever protagonist": "смекалистый герой",
    "cold protagonist": "холодный герой",
    "confident protagonist": "уверенный герой",
    "cooking": "кулинария",
    "corruption": "порча",
    "crafting": "ремесло",
    "cruel characters": "жестокие персонажи",
    "cultivation": "культивация",
    "curses": "проклятия",
    "dark": "мрачное",
    "death": "смерть",
    "demon lord": "повелитель демонов",
    "demons": "демоны",
    "determined protagonist": "упорный герой",
    "devoted love interests": "преданная любовь",
    "dragons": "драконы",
    "dungeons": "подземелья",
    "dwarfs": "гномы",
    "early romance": "ранняя романтика",
    "elves": "эльфы",
    "empires": "империи",
    "enemies become lovers": "враги становятся возлюбленными",
    "evil protagonist": "злой герой",
    "evolution": "эволюция",
    "eye powers": "силы глаз",
    "family": "семья",
    "famous protagonist": "известный герой",
    "fast cultivation": "быстрая культивация",
    "fast learner": "быстро учится",
    "female protagonist": "героиня-женщина",
    "firearms": "огнестрельное оружие",
    "first time intercourse": "первый раз",
    "game elements": "игровые элементы",
    "game ranking system": "рейтинг как в игре",
    "gate to another world": "врата в иной мир",
    "genius protagonist": "гениальный герой",
    "ghosts": "призраки",
    "goblins": "гоблины",
    "gods": "боги",
    "guilds": "гильдии",
    "hard working protagonist": "трудолюбивый герой",
    "healers": "целители",
    "heavenly tribulation": "небесная кара",
    "hiding true abilities": "скрывает силу",
    "hiding true identity": "скрывает личность",
    "human nonhuman relationship": "любовь человека и нечеловека",
    "immortals": "бессмертные",
    "inheritance": "наследие",
    "intelligent protagonist": "умный герой",
    "interdimensional travel": "путешествия между мирами",
    "kingdom building": "строительство королевства",
    "level system": "система уровней",
    "loyal subordinates": "верные соратники",
    "magic": "магия",
    "magic beasts": "магические звери",
    "magic formations": "магические печати",
    "male protagonist": "герой-мужчина",
    "management": "управление",
    "mature protagonist": "взрослый герой",
    "medical knowledge": "медицина",
    "mercenaries": "наёмники",
    "military": "армия",
    "modern day": "наше время",
    "modern knowledge": "знания из нашего мира",
    "monsters": "монстры",
    "multiple identities": "несколько личностей",
    "multiple realms": "множество миров",
    "mutated creatures": "мутанты",
    "mysterious family background": "загадочное происхождение",
    "mysterious past": "загадочное прошлое",
    "necromancer": "некромант",
    "nobles": "знать",
    "orcs": "орки",
    "organized crime": "организованная преступность",
    "overpowered protagonist": "непобедимый герой",
    "parallel worlds": "параллельные миры",
    "past plays a big role": "прошлое многое решает",
    "pets": "питомцы",
    "pill concocting": "изготовление пилюль",
    "poisons": "яды",
    "politics": "политика",
    "poor protagonist": "бедный герой",
    "possession": "одержимость",
    "power struggle": "борьба за власть",
    "previous life talent": "таланты прошлой жизни",
    "protagonist strong from the start": "герой силён с начала",
    "race change": "смена расы",
    "reincarnated in another world": "перерождение в ином мире",
    "reincarnation": "перерождение",
    "revenge": "месть",
    "romantic subplot": "любовная линия",
    "royalty": "королевская кровь",
    "ruthless protagonist": "безжалостный герой",
    "schemes and conspiracies": "интриги и заговоры",
    "sect development": "развитие секты",
    "secret identity": "тайная личность",
    "secretive protagonist": "скрытный герой",
    "servants": "слуги",
    "shameless protagonist": "бесстыжий герой",
    "skill assimilation": "поглощение навыков",
    "skill books": "книги навыков",
    "slaves": "рабы",
    "slow growth at start": "медленный старт",
    "smart couple": "умная пара",
    "soul power": "сила души",
    "spatial manipulation": "управление пространством",
    "spirits": "духи",
    "strategist": "стратег",
    "strength based social hierarchy": "иерархия по силе",
    "strong love interests": "сильные возлюбленные",
    "strong to stronger": "сильный становится сильнее",
    "sword and magic": "меч и магия",
    "sword wielder": "мечник",
    "system administrator": "системный администратор",
    "time manipulation": "управление временем",
    "time skip": "скачок во времени",
    "time travel": "путешествие во времени",
    "tragic past": "трагическое прошлое",
    "transmigration": "переселение души",
    "transported to another world": "попал в иной мир",
    "unique cultivation technique": "особая техника культивации",
    "unique weapons": "необычное оружие",
    "vampires": "вампиры",
    "war": "война",
    "weak to strong": "из слабого в сильного",
    "wealthy characters": "богатые персонажи",
    "werebeasts": "оборотни",
    "wizards": "волшебники",
    "world hopping": "прыжки по мирам",
    "world travel": "странствия по миру",
    "younger sisters": "младшие сёстры",
}

#: Выходит книга или закончена.
STATUS = {
    "ongoing": "выходит",
    "completed": "закончена",
    "complete": "закончена",
    "finished": "закончена",
    "hiatus": "заморожена",
    "on hiatus": "заморожена",
    "dropped": "брошена",
    "cancelled": "отменена",
    "canceled": "отменена",
}

#: Язык оригинала.
LANGUAGE = {
    "chinese": "китайский",
    "korean": "корейский",
    "japanese": "японский",
    "english": "английский",
    "filipino": "филиппинский",
    "indonesian": "индонезийский",
    "malay": "малайский",
    "thai": "тайский",
    "vietnamese": "вьетнамский",
    "russian": "русский",
}

#: Всё, что не буква и не цифра, при сверке считается пробелом: каталог
#: пишет то «Sci-fi», то «Sci Fi», то «sci_fi» — это одно слово.
_GAP = re.compile(r"[^0-9a-zа-яё]+")


def _plain(text) -> str:
    """Слово в том виде, в каком его ищут в словаре."""
    return _GAP.sub(" ", str(text or "").strip().lower()).strip()


def word(text, book: dict | None = None) -> str:
    """Перевод одного слова. Пусто — такого слова в словаре нет.

    `book` — какой словарь спрашивать; по умолчанию сразу все, потому что
    жанр и тег у каталога иногда совпадают («Military» бывает и тем, и
    другим), а перевод у них один.
    """
    plain = _plain(text)
    if not plain:
        return ""
    if book is not None:
        # Свой словарь первым, но не единственным: каталог называет одно
        # и то же слово то жанром, то тегом («Military» бывает и тем, и
        # другим), и отказываться от готового перевода из-за того, что он
        # лежит в соседнем списке, незачем.
        found = book.get(plain)
        if found:
            return found
    for known in (GENRES, TAGS, STATUS, LANGUAGE):
        found = known.get(plain)
        if found:
            return found
    return ""


def words(items, book: dict | None = None) -> list:
    """Список слов по-русски. Незнакомое остаётся как есть.

    Смешанный список честнее двух крайностей: переводить наугад нельзя, а
    прятать перевод всех остальных из-за одного незнакомого — терять то,
    что уже сделано.
    """
    said = []
    for one in items or []:
        text = str(one).strip()
        if not text:
            continue
        said.append(word(text, book) or text)
    return said


def status(text) -> str:
    """«Ongoing» → «выходит». Незнакомое — как есть."""
    return word(text, STATUS) or str(text or "")


def language(text) -> str:
    """«Chinese» → «китайский». Незнакомое — как есть."""
    return word(text, LANGUAGE) or str(text or "")


def genres(items) -> list:
    return words(items, GENRES)


def tags(items) -> list:
    return words(items, TAGS)
