/* Обложки рейтинга: наклон под курсором и перелёт в раскрытую карточку.
 *
 * Два эффекта в одном файле, потому что оба — про одну и ту же обложку и
 * обоим нужна её геометрия. Галочки у них при этом свои: `cover-lift` и
 * `card-open` включаются и снимаются порознь.
 *
 * Ничего в самой вкладке не правится: наклон навешивается одним
 * обработчиком на всю таблицу, перелёт — обёрткой поверх раскрытия
 * строки. Снятая галочка возвращает прежнее поведение целиком.
 */

/** Сколько летит двойник обложки. */
const COV_FLIGHT_MS = 430;

/** Дольше этого после нажатия — уже не взлетаем.
 *
 * Карточка наполняется страницей книги, а её ещё надо получить. Обычно
 * это доли секунды, но сайт бывает и медленным, и закрытым. Обложка,
 * взлетевшая через пять секунд после нажатия, читается не как
 * продолжение нажатия, а как сбой: связь с действием потеряна.
 */
const COV_TOO_LATE_MS = 1200;

function covOn(key){
  return document.documentElement.classList.contains('fx-' + key);
}

function covCalm(){
  return window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/* ------------------------------------------- наклон под курсором (6) */

(function covTilt(){
  //: Обложка, которая сейчас отклонена. Держим её, чтобы вернуть на
  //: место, когда курсор ушёл на соседнюю: `mouseleave` на таблице
  //: срабатывает только на её краю, а внутри строки переходов много.
  let held = null;

  function drop(){
    if(!held) return;
    held.classList.remove('fx-tilt');
    held.style.removeProperty('--fx-tx');
    held.style.removeProperty('--fx-ty');
    held = null;
  }

  function follow(event){
    if(!covOn('cover-lift') || covCalm()) return drop();

    const cover = event.target.closest
      ? event.target.closest('#rkTable .cover.ready') : null;
    if(!cover) return drop();
    if(held && held !== cover) drop();

    const box = cover.getBoundingClientRect();
    if(!box.width || !box.height) return;

    // Доли от -1 до 1, отсчитанные от середины обложки: угол считает уже
    // таблица стилей, здесь только положение курсора.
    const x = (event.clientX - box.left) / box.width * 2 - 1;
    const y = (event.clientY - box.top) / box.height * 2 - 1;
    cover.style.setProperty('--fx-tx', x.toFixed(3));
    cover.style.setProperty('--fx-ty', y.toFixed(3));
    cover.classList.add('fx-tilt');
    held = cover;
  }

  document.addEventListener('DOMContentLoaded', () => {
    const table = document.getElementById('rkTable');
    if(!table) return;
    table.addEventListener('mousemove', follow);
    table.addEventListener('mouseleave', drop);
    // Список перерисовывается целиком, и отклонённая обложка исчезает
    // вместе со строкой. Забытая ссылка на неё держала бы узел в памяти.
    table.addEventListener('scroll', drop);
  });
})();

/* --------------------------------- перелёт обложки в карточку (7) */

/** Двойник обложки, летящий из строки в карточку.
 *
 * Летит именно двойник: подвинь мы настоящую миниатюру, строка осталась
 * бы дырявой, если карточка почему-либо не откроется. Двойник живёт
 * четыре десятых секунды и убирается сам — в том числе если анимация
 * оборвётся вместе со страницей.
 */
function covFlight(from, to){
  const start = from.getBoundingClientRect();
  const end = to.getBoundingClientRect();
  if(!start.width || !start.height || !end.width || !end.height) return;

  const ghost = document.createElement('img');
  ghost.className = 'fx-flight';
  ghost.alt = '';
  ghost.src = from.currentSrc || from.src;
  ghost.style.left = end.left + 'px';
  ghost.style.top = end.top + 'px';
  ghost.style.width = end.width + 'px';
  ghost.style.height = end.height + 'px';
  document.body.append(ghost);

  const shiftX = start.left - end.left;
  const shiftY = start.top - end.top;
  const scaleX = start.width / end.width;
  const scaleY = start.height / end.height;

  // Пока летит двойник, настоящая обложка карточки спрятана: иначе одна
  // и та же картинка видна дважды, и перелёт читается как размножение.
  const shown = to.style.visibility;
  to.style.visibility = 'hidden';

  const done = () => { ghost.remove(); to.style.visibility = shown; };
  let run = null;
  try{
    run = ghost.animate([
      {transform: 'translate(' + shiftX + 'px,' + shiftY + 'px) scale('
        + scaleX + ',' + scaleY + ')', opacity: .9},
      {transform: 'none', opacity: 1},
    ], {duration: COV_FLIGHT_MS, easing: 'cubic-bezier(.22,.61,.36,1)'});
  }catch(err){
    // Старый браузер без Web Animations — просто без перелёта.
    return done();
  }
  run.onfinish = done;
  run.oncancel = done;
  setTimeout(done, COV_FLIGHT_MS + 400);
}

(function covOpen(){
  if(typeof rkToggle !== 'function') return;
  const was = rkToggle;

  rkToggle = async function(row, tr){
    if(!covOn('card-open') || covCalm() || !row || !tr){
      return was.apply(this, arguments);
    }

    const box = typeof rkBoxOf === 'function' ? rkBoxOf(row.book_id) : null;
    // Была ли строка закрыта до нажатия: закрытие — не перелёт.
    const shut = !box || box.hidden;
    const pressed = Date.now();
    const out = await was.apply(this, arguments);

    const card = typeof rkBoxOf === 'function' ? rkBoxOf(row.book_id) : null;
    if(!shut || !card || card.hidden) return out;
    if(Date.now() - pressed > COV_TOO_LATE_MS) return out;

    const small = tr.querySelector('.cover img');
    const big = card.querySelector('img.rkcard-cover');
    if(small && big && !big.hidden) covFlight(small, big);
    return out;
  };
})();
