/* Подсветка найденного в фильтре рейтинга (эффект `find-hit`).
 *
 * Набрал слово — восемьдесят строк схлопнулись до пяти, но по какому
 * месту они совпали, приходилось искать глазами. На китайских названиях
 * особенно: взгляду там не за что зацепиться.
 *
 * Подсветка ставится **после** того, как таблицу перерисовала сама
 * вкладка, и живёт до следующей перерисовки. Своей она не устраивает:
 * список каждый раз собирается заново, накопиться разметке негде.
 *
 * Тонкость с обработчиком. Отбор по названию вкладка вешает на поле
 * сама, и ссылку на `rkRender` берёт до всякой подмены — через обёртку
 * такой вызов не идёт. Поэтому слушаем поле и своим обработчиком: он
 * добавлен позже, а значит и сработает позже, когда строки уже на месте.
 */

function hitOn(){
  return document.documentElement.classList.contains('fx-find-hit');
}

/** Что ищут прямо сейчас. */
function hitWanted(){
  const box = document.getElementById('rkFilter');
  return box ? box.value.trim().toLowerCase() : '';
}

/** Куда смотреть в строке: название и его перевод. */
function hitParts(tr){
  return tr.querySelectorAll(':scope > .grow, :scope > .ru');
}

/** Обвести совпадения внутри одного узла.
 *
 * Разметка собирается узлами, а не строкой: название приходит с чужого
 * сайта, и склеивать из него HTML нельзя — китайская книга с угловой
 * скобкой в заголовке превратилась бы в чужой тег.
 */
function hitMark(node, wanted){
  const text = node.textContent || '';
  const where = text.toLowerCase();
  if(!wanted || where.indexOf(wanted) < 0) return;

  const out = document.createDocumentFragment();
  let at = 0;
  for(;;){
    const found = where.indexOf(wanted, at);
    if(found < 0) break;
    if(found > at) out.append(text.slice(at, found));
    const hit = document.createElement('mark');
    hit.className = 'fx-hit';
    hit.textContent = text.slice(found, found + wanted.length);
    out.append(hit);
    at = found + wanted.length;
  }
  if(at < text.length) out.append(text.slice(at));
  node.replaceChildren(out);
}

function hitPaint(){
  const table = document.getElementById('rkTable');
  if(!table) return;
  if(!hitOn()) return hitClear();

  const wanted = hitWanted();
  if(!wanted) return hitClear();

  for(const tr of table.querySelectorAll('.tr')){
    for(const part of hitParts(tr)) hitMark(part, wanted);
  }
}

/** Снять подсветку, не трогая текста.
 *
 * Нужно ради снятой галочки: список сам по себе не перерисуется, а
 * оставленные метки выглядели бы как «эффект не выключается».
 */
function hitClear(){
  for(const hit of document.querySelectorAll('#rkTable mark.fx-hit')){
    hit.replaceWith(hit.textContent || '');
  }
  for(const part of document.querySelectorAll('#rkTable .tr > .grow,'
      + ' #rkTable .tr > .ru')){
    // Соседние текстовые узлы после снятия метки склеиваем: иначе
    // следующая подсветка увидит обрывки вместо целого названия.
    part.normalize();
  }
}

(function hitWatch(){
  document.addEventListener('DOMContentLoaded', () => {
    const box = document.getElementById('rkFilter');
    if(box) box.addEventListener('input', hitPaint);

    // Срез могли обновить с непустым отбором — тогда строки новые, а
    // искомое прежнее.
    if(typeof rkRender === 'function'){
      const was = rkRender;
      rkRender = function(){
        const out = was.apply(this, arguments);
        hitPaint();
        return out;
      };
    }
  });
})();
