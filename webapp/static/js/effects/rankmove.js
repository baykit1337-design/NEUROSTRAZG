/* Переезд строк рейтинга (эффект `rank-move`).
 *
 * Рейтинг — это про движение, а движение показывала стрелка сбоку. Её
 * надо прочитать; переезд виден сам: книга, поднявшаяся с четырнадцатого
 * места на третье, проползает вверх мимо остальных.
 *
 * Способ обычный для такой задачи: измерить, где строки были, дать
 * таблице перерисоваться, измерить, где они стали, и на разницу сдвинуть
 * их назад — а потом отпустить. Браузер доедет сам.
 *
 * Ничего в самой вкладке для этого править не пришлось. Строку опознаём
 * не по своей метке, а по той, что уже есть: сразу за каждой строкой в
 * разметке лежит её карточка `.rkcard` с `data-book`.
 *
 * Отдельно про фильтр. Он перерисовывает список на каждую букву, и полёт
 * там был бы дёрганьем, а не переездом. Поэтому при непустом фильтре
 * эффект молчит — а заодно и сам обработчик фильтра держит ссылку на
 * исходный `rkRender`, взятую до подмены, и через обёртку не идёт.
 */

/** Сколько едет строка. Держать в согласии с `css/effects/rank-move.css`. */
const RM_FLIGHT_MS = 560;

/** Сдвиг меньше этого — не переезд, а погрешность вёрстки. */
const RM_LEAST = 2;

function rmOn(){
  return document.documentElement.classList.contains('fx-rank-move');
}

/** Код книги у строки — из карточки, которая идёт сразу за ней. */
function rmBook(tr){
  const box = tr.nextElementSibling;
  return box && box.classList.contains('rkcard') ? (box.dataset.book || '') : '';
}

function rmRows(){
  return document.querySelectorAll('#rkTable .tr');
}

/** Где какая книга стоит прямо сейчас. */
function rmPlaces(){
  const found = new Map();
  for(const tr of rmRows()){
    const book = rmBook(tr);
    if(book) found.set(book, tr.getBoundingClientRect().top);
  }
  return found;
}

/** Идёт ли отбор по названию: тогда список меняется от набора букв. */
function rmFiltering(){
  const box = document.getElementById('rkFilter');
  return !!(box && box.value.trim());
}

function rmReady(){
  const table = document.getElementById('rkTable');
  // `offsetParent` пуст у скрытой вкладки: мерить там нечего, все
  // координаты вышли бы нулями, и строки «переехали» бы через весь экран.
  return rmOn() && table && table.offsetParent !== null && !rmFiltering();
}

function rmRelease(tr){
  tr.classList.remove('fx-moving', 'fx-up', 'fx-down');
  tr.style.transform = '';
}

/** Вернуть строки на прежние места и отпустить. */
function rmFly(before){
  for(const tr of rmRows()){
    const book = rmBook(tr);
    if(!book || !before.has(book)) continue;

    const shift = before.get(book) - tr.getBoundingClientRect().top;
    if(Math.abs(shift) < RM_LEAST) continue;

    rmRelease(tr);
    tr.style.transform = 'translateY(' + shift.toFixed(1) + 'px)';
    // Чтение размера заставляет браузер применить сдвиг до того, как мы
    // его снимем. Без этой строки перехода не будет вовсе: браузер
    // объединит обе правки и покажет только последнюю.
    void tr.offsetHeight;

    // Сдвиг вниз означает, что строка была ниже, а стала выше: книга
    // поднялась в рейтинге.
    tr.classList.add('fx-moving', shift > 0 ? 'fx-up' : 'fx-down');
    tr.style.transform = '';
    setTimeout(rmRelease, RM_FLIGHT_MS + 60, tr);
  }
}

(function rmWatch(){
  if(typeof rkRender !== 'function') return;
  const was = rkRender;

  rkRender = function(){
    if(!rmReady()) return was.apply(this, arguments);

    const before = rmPlaces();
    const out = was.apply(this, arguments);
    // Пусто до перерисовки — значит, список показывается впервые.
    // Появление — не переезд, и ехать тут неоткуда.
    if(before.size) rmFly(before);
    return out;
  };
})();
