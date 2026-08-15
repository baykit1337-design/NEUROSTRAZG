/* Оформление: список эффектов и галочки к ним (6.2 ТЗ NEUROSTRAZH).
 *
 * Каждый эффект — отдельный файл стилей, включаемый классом на корне
 * страницы. Отсюда следует главное свойство: любой эффект снимается, не
 * задевая остальные, а при снятых галочках интерфейс работает ровно так
 * же, как до всей этой красоты.
 *
 * Выбор хранится в браузере, а не на сервере: это настройка внешнего вида
 * конкретного экрана, и синхронизировать её не с чем.
 */

const FX_STORE = 'neurostrazh-effects';

/** Реестр. Добавить эффект — строчка здесь и файл в css/effects. */
const EFFECTS = [
  {
    key: 'title-glitch',
    name: 'Глитч названия',
    hint: 'При наведении на «NEUROSTRAZH 2.0» короткий сбой, потом инверсия.',
    on: true,
  },
  {
    key: 'button-press',
    name: 'Отклик кнопок',
    hint: 'Вдавливание, вспышка контура и глитч надписи при нажатии.',
    on: true,
  },
  {
    key: 'progress-life',
    name: 'Живая полоса',
    hint: 'Свечение полосы «дышит», на переднем крае горит искра — видно, '
      + 'что работа идёт, даже когда процент долго не меняется.',
    on: true,
  },
  {
    key: 'done-flash',
    name: 'Вспышка по завершении',
    hint: 'Одна волна свечения по блоку результата, когда операция кончилась.',
    on: true,
  },
  {
    key: 'counter',
    name: 'Счётчики с прокруткой',
    hint: 'Числа в сводках доезжают до нового значения, а не прыгают.',
    on: true,
  },
  {
    key: 'skeleton',
    name: 'Заготовки строк',
    hint: 'Пока список читается, вместо пустоты пульсируют заготовки строк.',
    on: true,
  },
  {
    key: 'subtitle',
    name: 'Блик подзаголовка',
    hint: 'По строке под названием пробегает отблеск, от текста поднимаются '
      + 'искры. Один раз за наведение, а не потоком.',
    on: true,
  },
  {
    key: 'stars',
    name: 'Звёздное поле',
    hint: 'Мелкие статичные точки на фоне, чуть отстают при прокрутке. '
      + 'Без мерцания: мельтешение на фоне отвлекает от текста.',
    on: true,
  },
  {
    key: 'magnetic',
    name: 'Магнитные кнопки',
    hint: 'Крупные кнопки чуть тянутся к курсору и возвращаются с пружиной.',
    on: false,
  },
  {
    key: 'row-sweep',
    name: 'Подсветка строк',
    hint: 'По строке таблицы при наведении проходит блик слева направо.',
    on: true,
  },
  {
    key: 'tab-grow',
    name: 'Рост вкладки',
    hint: 'Содержимое появляется из нажатой кнопки, блоки — каскадом.',
    on: true,
  },
  {
    key: 'static-cards',
    name: 'Отзывчивые сводки',
    hint: 'Карточки, которые нельзя редактировать, тоже отзываются на '
      + 'наведение — иначе они выглядят сломанными.',
    on: true,
  },
];

/** Системная настройка «уменьшить движение» сильнее любых галочек. */
function fxCalm(){
  return window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function fxLoad(){
  let saved = {};
  try{
    saved = JSON.parse(localStorage.getItem(FX_STORE) || '{}') || {};
  }catch(err){
    saved = {};
  }
  const state = {};
  for(const effect of EFFECTS){
    state[effect.key] = effect.key in saved ? !!saved[effect.key] : effect.on;
  }
  return state;
}

function fxSave(state){
  try{
    localStorage.setItem(FX_STORE, JSON.stringify(state));
  }catch(err){
    // Приватный режим — эффекты просто не запомнятся до перезагрузки.
  }
}

function fxApply(state){
  const root = document.documentElement;
  for(const effect of EFFECTS){
    root.classList.toggle('fx-' + effect.key, !!state[effect.key]);
  }
}

let FX_STATE = fxLoad();
fxApply(FX_STATE);

/** Название дублируется в data-text: двойники глитча рисуются из него. */
(function fxTitleText(){
  const title = document.querySelector('.app-title');
  if(title && !title.dataset.text) title.dataset.text = title.textContent.trim();
})();

function fxRender(){
  const box = document.getElementById('fxList');
  if(!box) return;
  box.innerHTML = '';

  for(const effect of EFFECTS){
    const row = document.createElement('label');
    row.className = 'chk';

    const tick = document.createElement('input');
    tick.type = 'checkbox';
    tick.checked = !!FX_STATE[effect.key];
    tick.onchange = () => {
      FX_STATE[effect.key] = tick.checked;
      fxSave(FX_STATE);
      fxApply(FX_STATE);
    };

    row.append(tick, document.createTextNode(' ' + effect.name));
    // Подсказку вешает общая функция интерфейса — своей заводить незачем.
    if(effect.hint && typeof attachTip === 'function') attachTip(row, effect.hint);
    box.append(row);
  }

  const note = document.getElementById('fxNote');
  if(note && fxCalm()){
    note.textContent = 'В системе включено «уменьшить движение» — анимации '
      + 'не запускаются, сколько бы галочек ни стояло.';
  }
}

function fxAll(on){
  for(const effect of EFFECTS) FX_STATE[effect.key] = on;
  fxSave(FX_STATE);
  fxApply(FX_STATE);
  fxRender();
}

document.addEventListener('DOMContentLoaded', () => {
  fxRender();
  const all = document.getElementById('fxAll');
  const none = document.getElementById('fxNone');
  if(all) all.onclick = () => fxAll(true);
  if(none) none.onclick = () => fxAll(false);
});
