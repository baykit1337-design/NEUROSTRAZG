/* То, что в эффектах нельзя сделать одними стилями: притяжение кнопок к
 * курсору и точка, из которой вырастает вкладка.
 *
 * Прожектор и свой курсор отсюда убраны вместе с самими эффектами: они не
 * прижились, а мёртвый код хуже отсутствующего — он выглядит рабочим.
 */

/** Насколько кнопка тянется к курсору. Больше четырёх пикселей — и
 *  промахиваешься мимо кнопки, которая уехала. */
const FX_MAGNET = 4;

/** По вертикали меньше: кнопки верхней панели стоят вплотную к краю
 *  строки, и на четырёх пикселях им уже не хватало места. */
const FX_MAGNET_Y = 3;

/** Магнитятся только крупные кнопки действий. */
const FX_MAGNET_MIN = 90;

function fxHas(key){
  return document.documentElement.classList.contains('fx-' + key);
}

/* ------------------------------------------- магнитные кнопки (6.4) */

(function fxMagnetic(){
  let held = null;

  function release(button){
    button.style.transform = '';
    button.style.transition = '';
  }

  document.addEventListener('mousemove', event => {
    if(!fxHas('magnetic')) return;

    const button = event.target.closest && event.target.closest('button');
    if(held && held !== button) { release(held); held = null; }
    if(!button || button.disabled) return;

    const box = button.getBoundingClientRect();
    // Строки списков не магнитим: там кнопки мелкие и стоят вплотную.
    if(box.width < FX_MAGNET_MIN) return;

    const dx = (event.clientX - (box.left + box.width / 2)) / (box.width / 2);
    const dy = (event.clientY - (box.top + box.height / 2)) / (box.height / 2);
    held = button;
    button.style.transition = 'transform .12s ease-out';
    button.style.transform =
      `translate(${(dx * FX_MAGNET).toFixed(2)}px, ${(dy * FX_MAGNET_Y).toFixed(2)}px)`;
  });

  // Возврат с пружиной — на уход курсора и на любое снятие эффекта.
  document.addEventListener('mouseout', event => {
    const button = event.target.closest && event.target.closest('button');
    if(!button) return;
    button.style.transition = 'transform .34s cubic-bezier(.34,1.56,.64,1)';
    button.style.transform = '';
    if(held === button) held = null;
  });
})();

/* ------------------------------- точка роста при смене вкладки (6.8) */

(function fxTabOrigin(){
  //: Дольше самой длинной части каскада — иначе последние карточки
  //: обрывались бы на середине появления.
  const CASCADE_MS = 600;

  // Всплытие, а не перехват: раздел выбирается обработчиком самой кнопки,
  // и до него открытым числится ещё старый.
  document.addEventListener('click', event => {
    const button = event.target.closest && event.target.closest('.tabs button');
    if(!button || !fxHas('tab-grow')) return;

    const box = button.getBoundingClientRect();
    const shown = document.querySelector('section:not([hidden])');
    if(!shown) return;

    // Начало трансформации — центр нажатой кнопки в координатах раздела.
    const area = shown.getBoundingClientRect();
    const origin = box.left + box.width / 2 - area.left;
    shown.style.setProperty('--fx-origin', origin.toFixed(1) + 'px');

    shown.classList.remove('fx-enter');
    // Без чтения размера браузер не заметит, что класс снимали и вернули
    // в том же кадре, и анимация не перезапустится.
    void shown.offsetWidth;
    shown.classList.add('fx-enter');

    // Класс снимается после показа: иначе он висел бы на разделе всё
    // время, пока тот открыт, и мешал следующему запуску.
    setTimeout(() => shown.classList.remove('fx-enter'), CASCADE_MS);
  });
})();
