/* Отклик полей и кнопок: разгон колеса и дрожь недоступной кнопки.
 *
 * Оба эффекта живут одним слушателем на всю страницу, а не обходом
 * элементов при загрузке: половина полей и кнопок появляется позже —
 * стрелки к числовым полям дорисовывает `addSpinners`, строки рейтинга
 * и находки строятся по ответу сервера. Обход при загрузке до них не
 * дошёл бы, а второй обход пришлось бы звать из каждого места, где
 * что-то дорисовано.
 *
 * `fxHas` объявлена в `pointer.js`, который подключается раньше.
 */

/* ------------------------------------ разгон числового поля колесом */

(function fxSpinWheel(){
  //: Насколько шаг больше обычного на самом разгоне. «Глав в томе»
  //: доходит от нуля до двухсот пятидесяти за пару секунд вместо
  //: двухсот пятидесяти щелчков.
  const TOP_STEP = 25;

  //: За сколько миллисекунд разгон сходит на нет. Меньше — и он не
  //: успевает набраться на обычной прокрутке колеса; больше — и поле
  //: остаётся разогнанным, когда к нему вернулись через полминуты.
  const COOL_MS = 700;

  //: Сколько щелчков подряд нужно, чтобы дойти до предела. Первый
  //: щелчок всегда двигает на один шаг: точную правку на единицу
  //: разгон отбирать не должен.
  const TO_TOP = 14;

  let heat = 0, seen = 0, wrap = null, calm = null;

  function cool(){
    clearTimeout(calm);
    calm = setTimeout(() => {
      heat = 0;
      if(wrap){
        wrap.classList.remove('fx-spinning');
        wrap.style.removeProperty('--fx-spin-heat');
        wrap = null;
      }
    }, COOL_MS);
  }

  document.addEventListener('wheel', event => {
    if(!fxHas('spin-wheel')) return;

    const box = event.target.closest && event.target.closest('.spin-wrap');
    const input = box && box.querySelector('input[type=number]');
    if(!input || input.disabled || input.readOnly) return;

    // Только в поле, куда уже щёлкнули. Иначе колесо переставало
    // прокручивать страницу каждый раз, когда курсор случайно проезжал
    // над числом, — а поля эти стоят посреди карточек.
    if(document.activeElement !== input) return;

    event.preventDefault();

    if(box !== wrap){
      if(wrap) wrap.classList.remove('fx-spinning');
      wrap = box;
      seen = 0;
    }
    seen += 1;
    heat = Math.min(1, seen / TO_TOP);

    wrap.classList.add('fx-spinning');
    wrap.style.setProperty('--fx-spin-heat', heat.toFixed(2));

    const steps = Math.max(1, Math.round(1 + (TOP_STEP - 1) * heat * heat));
    for(let at = 0; at < steps; at += 1){
      if(event.deltaY < 0) input.stepUp(); else input.stepDown();
    }
    // Одно событие на весь разгон, а не по одному на шаг: на каждое
    // из них пересчитывается предпросмотр, и двадцать пять пересчётов
    // за один щелчок колеса вешают вкладку.
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));

    cool();
  }, {passive: false});
})();

/* ------------------------------------------ дрожь недоступной кнопки */

(function fxLockShake(){
  //: Чуть дольше самой дрожи — иначе класс снимается на её середине.
  const SHAKE_MS = 420;

  /** Выключенная кнопка под этой точкой.
   *
   * Ищем по месту, а не по цели события: событий от выключенной кнопки
   * браузер не рассылает вовсе, и целью оказывается то, что лежит под
   * ней. Смотрим только открытый раздел — на скрытых вкладках кнопок
   * втрое больше, и все они выключены.
   */
  function lockedAt(x, y){
    const shown = document.querySelector('section:not([hidden])') || document;
    for(const button of shown.querySelectorAll('button:disabled')){
      const box = button.getBoundingClientRect();
      if(x >= box.left && x <= box.right && y >= box.top && y <= box.bottom){
        return button;
      }
    }
    return null;
  }

  document.addEventListener('pointerdown', event => {
    if(!fxHas('lock-shake')) return;

    const button = lockedAt(event.clientX, event.clientY);
    if(!button || button.classList.contains('fx-locked')) return;

    button.classList.add('fx-locked');
    setTimeout(() => button.classList.remove('fx-locked'), SHAKE_MS);
  });
})();

/* ------------------------------ сторона, с которой въезжает вкладка */

(function fxTabSlide(){
  //: Чуть дольше самого уезда.
  const SLIDE_MS = 400;

  //: Номер вкладки, открытой сейчас. Направление видно только по нему:
  //: в момент, когда обработчик доходит до нас, открытой уже числится
  //: новая, и сравнивать не с чем.
  let at = -1;

  function tabs(){
    return [...document.querySelectorAll('.tabs button')];
  }

  document.addEventListener('DOMContentLoaded', () => {
    at = tabs().findIndex(button => button.classList.contains('on'));
  });

  document.addEventListener('click', event => {
    const button = event.target.closest && event.target.closest('.tabs button');
    if(!button) return;

    const now = tabs().indexOf(button);
    const back = at >= 0 && now >= 0 && now < at;
    // Номер запоминаем всегда, даже при снятой галочке: включат её
    // посреди работы — направление должно быть известно сразу.
    at = now;

    if(!fxHas('tab-slide')) return;
    const shown = document.querySelector('section:not([hidden])');
    if(!shown) return;

    shown.classList.remove('fx-slide-from-left', 'fx-slide-from-right');
    // Без чтения размера браузер не заметит, что класс сняли и вернули в
    // том же кадре, и анимация не перезапустится.
    void shown.offsetWidth;
    shown.classList.add(back ? 'fx-slide-from-left' : 'fx-slide-from-right');

    setTimeout(() => shown.classList.remove(
      'fx-slide-from-left', 'fx-slide-from-right'), SLIDE_MS);
  });
})();
