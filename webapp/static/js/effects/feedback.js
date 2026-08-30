/* 6.7 Обратная связь: счётчики, вспышка завершения, скелетоны.
 *
 * Всё здесь навешивается поверх готового интерфейса и ничего в нём не
 * переписывает: снятая галочка возвращает прежнее поведение целиком.
 * Поэтому счётчики и вспышка следят за уже существующими узлами, а не
 * встраиваются в каждую вкладку по отдельности.
 */

/** Сколько крутить число. Дольше — и цифра отстаёт от происходящего. */
const FX_COUNT_MS = 500;

function fxOn(key){
  return document.documentElement.classList.contains('fx-' + key);
}

/* ------------------------------------------------ счётчики с прокруткой */

/** Прокручивает число до нового значения.
 *
 *  Числа со значением, а не любые: «скачано 1578» прокручивать осмысленно,
 *  проценты и номер главы — нет, они и так меняются каждую секунду.
 */
function fxRoll(node, to){
  const from = Number(node.dataset.fxValue || 0);
  node.dataset.fxValue = String(to);

  // Табло сильнее прокрутки: они работают с одними и теми же числами, и
  // вместе цифра сперва доезжала бы, а потом ещё и переворачивалась.
  if(fxOn('flip-count') && from !== to){
    fxFlip(node, to);
    return;
  }

  if(!fxOn('counter') || from === to || Math.abs(to - from) < 2){
    node.textContent = String(to);
    return;
  }

  if(node._fxTimer) cancelAnimationFrame(node._fxTimer);
  const started = performance.now();
  // Промежуточные значения пишет сам эффект, и наблюдатель увидит их как
  // новые. Без этого флага он погнался бы за собственным хвостом.
  node._fxRolling = true;

  function step(now){
    const part = Math.min(1, (now - started) / FX_COUNT_MS);
    // Замедление к концу: так последняя цифра успевает прочитаться.
    const eased = 1 - Math.pow(1 - part, 3);
    node.textContent = String(Math.round(from + (to - from) * eased));
    if(part < 1){
      node._fxTimer = requestAnimationFrame(step);
    }else{
      node._fxRolling = false;
    }
  }
  node._fxTimer = requestAnimationFrame(step);
}

/** Переворачивает число, как створку на вокзальном табло.
 *
 *  Текст подменяется между половинками переворота: в первой створка
 *  уходит ребром, во второй возвращается уже с новым числом. Подмени мы
 *  раньше — смена была бы видна, позже — створка вернулась бы пустой.
 */
function fxFlip(node, to){
  if(node._fxFlipTimer) clearTimeout(node._fxFlipTimer);
  node._fxRolling = true;

  node.classList.remove('fx-flip-in');
  node.classList.add('fx-flip-out');
  node._fxFlipTimer = setTimeout(() => {
    node.textContent = String(to);
    node.classList.remove('fx-flip-out');
    node.classList.add('fx-flip-in');
    node._fxFlipTimer = setTimeout(() => {
      node.classList.remove('fx-flip-in');
      node._fxRolling = false;
    }, 180);
  }, 130);
}

/* ------------------------------------------------ искра у ключей */

/** Ключ исчерпан — короткая вспышка у счётчика.
 *
 *  Счётчик меняется молча, а момент важный: на нём кончается бесплатная
 *  квота. Следим за тем же числом, что и показываем, — за счётчиком
 *  исчерпанных: он растёт, значит ключ только что сгорел.
 */
function fxWatchKeys(){
  const observer = new MutationObserver(() => {
    if(!fxOn('key-spark')) return;
    for(const node of document.querySelectorAll('.fmkeys b.spent')){
      const shown = node.textContent.trim();
      if(!/^\d+$/.test(shown)) continue;
      const now = Number(shown);
      const was = Number(node.dataset.fxSpent);
      node.dataset.fxSpent = String(now);
      // Только рост: список ключей перечитывают и после сброса квоты,
      // и вспыхивать на возврате в строй незачем.
      if(!Number.isFinite(was) || now <= was) continue;

      node.classList.remove('fx-spark');
      void node.offsetWidth;
      node.classList.add('fx-spark');
      setTimeout(() => node.classList.remove('fx-spark'), 600);
    }
  });
  observer.observe(document.body, {subtree: true, childList: true,
                                   characterData: true});
}

/** Следит за числами в блоках статистики и прокручивает их. */
function fxWatchNumbers(){
  const observer = new MutationObserver(records => {
    for(const record of records){
      const node = record.target.nodeType === 1
        ? record.target : record.target.parentElement;
      if(!node || node.tagName !== 'B' || !node.closest('.stats')) continue;
      if(node._fxRolling) continue;

      const shown = node.textContent.trim();
      // Прокручиваем только целые числа: «18 мин 42 с» крутить нельзя.
      if(!/^\d+$/.test(shown)) continue;
      const to = Number(shown);
      if(String(node.dataset.fxValue) === String(to)) continue;
      fxRoll(node, to);
    }
  });

  observer.observe(document.body,
    {subtree: true, childList: true, characterData: true});
}

/* -------------------------------------------- вспышка по завершении */

/** Один раз на переход «работает → готово». */
function fxWatchDone(){
  const observer = new MutationObserver(records => {
    if(!fxOn('done-flash')) return;
    for(const record of records){
      const node = record.target;
      if(!(node instanceof Element) || !node.classList.contains('result-block')) continue;
      const done = node.classList.contains('done');
      const was = node.dataset.fxDone === '1';
      node.dataset.fxDone = done ? '1' : '0';
      if(!done || was) continue;

      node.classList.remove('fx-flash');
      // Перезапуск анимации: без чтения размера браузер не заметит, что
      // класс снимали и вернули в том же кадре.
      void node.offsetWidth;
      node.classList.add('fx-flash');
      setTimeout(() => node.classList.remove('fx-flash'), 700);
    }
  });

  observer.observe(document.body,
    {subtree: true, attributes: true, attributeFilter: ['class']});
}

/* ------------------------------------------------------- скелетоны */

/** Рисует заготовки строк в таблице, пока она грузится. */
function fxSkeleton(id, rows){
  const box = document.getElementById(id);
  if(!box || !fxOn('skeleton')) return;
  box.innerHTML = '';
  for(let i = 0; i < (rows || 6); i++){
    const line = document.createElement('div');
    line.className = 'skel';
    box.append(line);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  fxWatchNumbers();
  fxWatchDone();
  fxWatchKeys();
});
