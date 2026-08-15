/* 3.2 Звёздное поле: расстановка точек и параллакс при прокрутке.
 *
 * Точки ставятся один раз при загрузке и больше не меняются: звёзды,
 * которые перескакивают с места на место при каждой прокрутке, выглядят
 * поломкой, а не небом.
 *
 * Смещение считается в `requestAnimationFrame`, а не в обработчике
 * прокрутки: событий приходит куда больше, чем кадров, и пересчитывать на
 * каждое — впустую греть процессор.
 */

//: Сколько точек. Меньше сотни — пусто, больше двух — рябит.
const STARS_MIN = 120;
const STARS_MAX = 180;

//: Насколько медленнее содержимого движется слой. На тысяче пикселей
//: прокрутки это два-пять десятков — заметно, но не бросается в глаза.
const STARS_PARALLAX = 0.035;

//: Каждая десятая точка — с фиолетовым оттенком.
const STARS_VIOLET = 10;

function starsOn(){
  return document.documentElement.classList.contains('fx-stars');
}

(function starfield(){
  let layer = null;

  /** Расставляет точки. Зовётся один раз за загрузку страницы. */
  function build(){
    if(layer) return layer;
    layer = document.createElement('div');
    layer.className = 'starfield';

    const count = STARS_MIN + Math.floor(Math.random() * (STARS_MAX - STARS_MIN));
    for(let n = 0; n < count; n++){
      const star = document.createElement('i');
      const size = Math.random() < 0.65 ? 1 : 2;
      star.style.width = star.style.height = size + 'px';
      star.style.left = (Math.random() * 100).toFixed(3) + '%';
      // Поле выше экрана: при прокрутке снизу не должно появляться пустоты.
      star.style.top = (Math.random() * 130).toFixed(3) + '%';
      // Разная прозрачность важнее разного размера: одинаково яркие точки
      // читаются как сетка, а не как небо.
      star.style.opacity = (0.15 + Math.random() * 0.35).toFixed(2);
      if(n % STARS_VIOLET === 0) star.className = 'violet';
      layer.append(star);
    }
    document.body.append(layer);
    return layer;
  }

  let waiting = false;

  function paint(){
    waiting = false;
    if(!layer) return;
    const shift = -(window.scrollY || 0) * STARS_PARALLAX;
    layer.style.transform = `translate3d(0, ${shift.toFixed(1)}px, 0)`;
  }

  function onScroll(){
    if(!starsOn() || waiting) return;
    waiting = true;
    requestAnimationFrame(paint);
  }

  function start(){
    if(!starsOn()) return;
    build();
    paint();
  }

  document.addEventListener('DOMContentLoaded', start);
  document.addEventListener('scroll', onScroll, {passive: true});

  // Галочку могли поставить уже после загрузки — тогда поле строится тогда.
  const watch = new MutationObserver(() => {
    if(starsOn()) start();
  });
  watch.observe(document.documentElement,
                {attributes: true, attributeFilter: ['class']});
})();
