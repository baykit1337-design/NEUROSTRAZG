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
});
