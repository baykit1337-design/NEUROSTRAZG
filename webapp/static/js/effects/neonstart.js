/* Неон включается при запуске (эффект `neon-start`).
 *
 * Вуаль во весь экран, у которой рывками падает прозрачность: раз —
 * разраз — и горит. Сама анимация в `css/effects/neon-start.css`, здесь
 * только слой и его уборка.
 *
 * Слой убирается после анимации, а не остаётся навсегда прозрачным:
 * лишний элемент во весь экран поверх страницы — это лишний повод
 * однажды поймать им нажатие. `pointer-events:none` от этого бережёт, но
 * убрать надёжнее, чем понадеяться.
 *
 * Играет один раз за запуск программы. Переключение вкладок и любая
 * перерисовка вывеску не зажигают заново: она уже горит.
 */

/** Сколько длится разгорание. Держать в согласии с `neon-start.css`. */
const NEON_MS = 1000;

/** Запас поверх анимации: `animationend` не придёт, если человек
 *  попросил у системы поменьше движения — тогда слой снимет таймер. */
const NEON_SLACK = 400;

function neonStart(){
  const root = document.documentElement;
  if(!root.classList.contains('fx-neon-start')) return;

  const veil = document.createElement('div');
  veil.className = 'fx-neon-veil';
  // В конец `body`: слой должен лежать поверх всего, а не спорить за
  // порядок с карточками, у которых свой z-index.
  document.body.append(veil);

  let gone = false;
  const drop = () => {
    if(gone) return;
    gone = true;
    veil.remove();
  };
  veil.addEventListener('animationend', drop);
  setTimeout(drop, NEON_MS + NEON_SLACK);
}

// Ждём разметку: слой кладётся в `body`, а скрипты подключены до его
// конца не везде.
if(document.readyState === 'loading'){
  document.addEventListener('DOMContentLoaded', neonStart);
}else{
  neonStart();
}
