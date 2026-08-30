/* Что видно, когда окно свёрнуто: иконка вкладки и её заголовок.
 *
 * Оба эффекта отвечают на один вопрос — «оно там ещё работает?» — из
 * положения, в котором интерфейса не видно вовсе. Перевод книги идёт
 * часами, скачивание — тоже, и всё это время человек занят другим окном.
 * До сих пор единственным способом узнать ответ было переключиться.
 *
 * Оба следят за той же разметкой, что и остальные эффекты: полоса в
 * работе помечена классом `active`, законченный блок результата — `done`.
 * Своих крючков в тридцати обработчиках не заводим — они бы устарели на
 * первой же новой вкладке.
 */

/* --------------------------------------------- прогресс в иконке вкладки */

//: Размер иконки. Больше незачем: в полосе вкладок она рисуется в 16.
const FX_ICON = 32;

//: Чаще перерисовывать иконку смысла нет — глаз не различит, а замена
//: `href` заставляет браузер разбирать картинку заново.
const FX_ICON_MS = 400;

let fxIconLink = null;
let fxIconWas = null;
let fxIconShown = -1;
let fxIconAt = 0;

/** Ссылка на иконку страницы. Заводим один раз и запоминаем исходную. */
function fxIcon(){
  if(fxIconLink) return fxIconLink;
  fxIconLink = document.querySelector('link[rel="icon"]');
  if(!fxIconLink){
    fxIconLink = document.createElement('link');
    fxIconLink.rel = 'icon';
    document.head.append(fxIconLink);
  }
  if(fxIconWas === null) fxIconWas = fxIconLink.getAttribute('href') || '';
  return fxIconLink;
}

/** Сколько процентов показывает самая полная работающая полоса.
 *
 *  Работ может идти несколько; иконка одна, и показывает она ту, что
 *  ближе к концу: именно её окончания и ждут.
 */
function fxBusyPercent(){
  let best = -1;
  for(const fill of document.querySelectorAll('.bar > i.active')){
    const bar = fill.parentElement;
    // Полоса ожидания процентов не знает — она бежит без них.
    if(bar && bar.classList.contains('waiting')){
      best = Math.max(best, 0);
      continue;
    }
    const width = parseFloat(fill.style.width || '0');
    if(!Number.isNaN(width)) best = Math.max(best, width);
  }
  return best;
}

/** Рисует кольцо заполнения поверх точки. */
function fxDrawIcon(percent){
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = FX_ICON;
  const pen = canvas.getContext('2d');
  if(!pen) return '';

  const middle = FX_ICON / 2;
  const radius = middle - 3;

  pen.lineWidth = 5;
  pen.strokeStyle = '#2a2035';
  pen.beginPath();
  pen.arc(middle, middle, radius, 0, Math.PI * 2);
  pen.stroke();

  const part = Math.max(0, Math.min(100, percent)) / 100;
  if(part > 0){
    pen.strokeStyle = '#b06cff';
    pen.lineCap = 'round';
    pen.beginPath();
    // От двенадцати часов по часовой стрелке — как читают круговую шкалу.
    pen.arc(middle, middle, radius, -Math.PI / 2,
            -Math.PI / 2 + Math.PI * 2 * part);
    pen.stroke();
  }

  pen.fillStyle = '#e9d5ff';
  pen.beginPath();
  pen.arc(middle, middle, 3.5, 0, Math.PI * 2);
  pen.fill();

  return canvas.toDataURL('image/png');
}

function fxIconTick(){
  const on = fxOn('favicon-progress');
  const percent = on ? fxBusyPercent() : -1;

  if(percent < 0){
    // Работа кончилась или галочку сняли — возвращаем родную иконку.
    if(fxIconShown >= 0 && fxIconWas !== null){
      fxIcon().setAttribute('href', fxIconWas);
      fxIconShown = -1;
    }
    return;
  }

  const now = Date.now();
  const step = Math.round(percent);
  if(step === fxIconShown && now - fxIconAt < 4000) return;
  if(now - fxIconAt < FX_ICON_MS) return;

  const drawn = fxDrawIcon(step);
  if(!drawn) return;
  fxIcon().setAttribute('href', drawn);
  fxIconShown = step;
  fxIconAt = now;
}

/* ------------------------------------ мигание заголовка по завершении */

//: Сколько раз мигнуть. Дольше — и это уже не сообщение, а требование
//: внимания: человек мог уйти надолго и вернуться через час.
const FX_BLINK_TIMES = 12;
const FX_BLINK_MS = 900;

let fxTitleWas = null;
let fxBlinkTimer = null;
let fxBlinkLeft = 0;

function fxBlinkStop(){
  if(fxBlinkTimer) clearInterval(fxBlinkTimer);
  fxBlinkTimer = null;
  fxBlinkLeft = 0;
  if(fxTitleWas !== null){
    document.title = fxTitleWas;
    fxTitleWas = null;
  }
}

/** Начинает мигать заголовком. Только когда вкладка не на виду. */
function fxBlinkStart(){
  if(!fxOn('title-blink') || !document.hidden) return;
  if(fxBlinkTimer) { fxBlinkLeft = FX_BLINK_TIMES; return; }

  fxTitleWas = document.title;
  fxBlinkLeft = FX_BLINK_TIMES;
  let shown = false;
  fxBlinkTimer = setInterval(() => {
    shown = !shown;
    document.title = shown ? '✓ Готово — NEUROSTRAZH' : fxTitleWas;
    if(--fxBlinkLeft <= 0) fxBlinkStop();
  }, FX_BLINK_MS);
}

/** Заглянули на вкладку — сообщение своё дело сделало. */
document.addEventListener('visibilitychange', () => {
  if(!document.hidden) fxBlinkStop();
});

/* ------------------------------------------------------------ слежение */

(function fxWatchTabSignals(){
  // Полосу опрашиваем по времени, а не по событиям: ширину меняет
  // `style`, и наблюдатель за атрибутами дёргался бы на каждый процент.
  setInterval(fxIconTick, FX_ICON_MS);

  const observer = new MutationObserver(records => {
    for(const record of records){
      const node = record.target;
      if(!(node instanceof Element)) continue;
      if(!node.classList.contains('result-block')) continue;

      const done = node.classList.contains('done');
      const was = node.dataset.fxBlinked === '1';
      node.dataset.fxBlinked = done ? '1' : '0';
      if(done && !was) fxBlinkStart();
    }
  });
  observer.observe(document.body,
    {subtree: true, attributes: true, attributeFilter: ['class']});
})();
