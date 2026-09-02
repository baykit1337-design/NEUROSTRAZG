/* Рейтинг: место, обложка первого, тасовка доски и полёт обложки.
 *
 * Четыре эффекта одним файлом: все четыре живут с одного и того же
 * события — перерисовки списка, — и разносить по файлам пришлось бы саму
 * обёртку, а не эффекты. Каждый по-прежнему снимается своей галочкой:
 * скрипт только расставляет метки, а показывать их или нет, решают
 * стили.
 *
 * Обёртка та же, что у «Переезда строк»: подменяем `rkRender`. Вкладку
 * при этом править не пришлось ни в одном месте.
 *
 * Подключаться этот файл обязан ПОСЛЕ `rankmove.js`. Тот меряет, где
 * строки стояли и где стали; запустись наша сдача до его замера, он
 * померил бы строки посреди их появления и разослал бы всех в разные
 * стороны.
 */

//: Дальше этого места подсветка номера уже неотличима от нуля.
const RL_TOP = 20;

//: Сдача: сколько едет строка и через сколько после неё трогается
//: следующая. Длительность держать в согласии с `board-shuffle.css`.
const RL_DEAL_MS = 340;
const RL_DEAL_STEP = 26;

//: Дальше этой строки задержку не наращиваем: в списке их бывает под
//: сотню, и последняя появлялась бы через две с половиной секунды.
const RL_DEAL_LAST = 12;

//: Сколько летит обложка. Держать в согласии с `cover-flight.css`.
const RL_FLY_MS = 520;

//: Сколько кадров ждём, что «Качалка» откроется. Полёт туда, куда не
//: перешли, был бы враньём: у книги с сайта по подписке качалки нет
//: вовсе, и кнопка там только копирует название.
const RL_FLY_FRAMES = 30;

//: Во что съёживается обложка на подлёте к вкладке.
const RL_FLY_SIZE = 16;

//: Насколько близко к краю экрана позволено сесть.
//:
//: Строка вкладок не липкая: в длинном рейтинге её на экране может не
//: быть вовсе, и обложка улетала бы за верхний край — в никуда. Прижимаем
//: посадку к экрану: пусть летит вверх и садится у самого края, зато
//: полёт виден весь.
const RL_FLY_EDGE = 8;

function rlOn(key){
  return document.documentElement.classList.contains('fx-' + key);
}

function rlRows(){
  return document.querySelectorAll('#rkTable .tr');
}

/** Код книги у строки — из карточки, которая идёт сразу за ней. */
function rlBook(tr){
  const box = tr.nextElementSibling;
  return box && box.classList.contains('rkcard') ? (box.dataset.book || '') : '';
}

function rlBooks(){
  const seen = new Set();
  for(const tr of rlRows()){
    const book = rlBook(tr);
    if(book) seen.add(book);
  }
  return seen;
}

/** Жар номера и метка первого места.
 *
 * Первое место — не первая строка: список сортируют и по числу
 * читающих, и по движению за сутки.
 */
function rlMark(){
  for(const tr of rlRows()){
    const place = tr.querySelector('.place');
    if(!place) continue;

    const number = parseInt(place.textContent, 10);
    const heat = Number.isFinite(number)
      ? Math.max(0, (RL_TOP - number + 1) / RL_TOP) : 0;
    place.style.setProperty('--fx-place-heat', heat.toFixed(2));
    tr.classList.toggle('fx-top', number === 1);
  }
}

/** Сдать список заново. */
function rlDeal(){
  let at = 0;
  for(const tr of rlRows()){
    const wait = Math.min(at, RL_DEAL_LAST) * RL_DEAL_STEP;
    tr.classList.remove('fx-dealt');
    // Без чтения размера браузер не заметит, что класс сняли и вернули в
    // том же кадре, и анимация не перезапустится.
    void tr.offsetWidth;
    tr.style.animationDelay = wait + 'ms';
    tr.classList.add('fx-dealt');

    setTimeout(one => {
      one.classList.remove('fx-dealt');
      one.style.animationDelay = '';
    }, RL_DEAL_MS + wait + 80, tr);
    at += 1;
  }
}

/** Сменилась ли доска: в списке не осталось ни одной прежней книги.
 *
 * Новый срез той же доски так не выглядит — там книги те же, и их
 * перемещение показывает «Переезд строк рейтинга».
 */
function rlFresh(before, now){
  if(!before.size || !now.size) return false;
  for(const book of now){
    if(before.has(book)) return false;
  }
  return true;
}

(function rlWatch(){
  if(typeof rkRender !== 'function') return;
  const was = rkRender;

  rkRender = function(){
    const before = rlBooks();
    const out = was.apply(this, arguments);

    rlMark();
    if(rlOn('board-shuffle') && rlFresh(before, rlBooks())) rlDeal();
    return out;
  };
})();

/* ------------------------------------------- полёт обложки в качалку */

(function rlCoverFlight(){
  /** Место посадки, прижатое к экрану. */
  function onScreen(at, size){
    return Math.max(RL_FLY_EDGE,
                    Math.min(at, size - RL_FLY_SIZE - RL_FLY_EDGE));
  }

  /** Копия обложки летит от строки к вкладке и тает. */
  function fly(from, src){
    const target = document.querySelector('.tabs button[data-tab="download"]');
    if(!target) return;
    const to = target.getBoundingClientRect();

    const ghost = document.createElement('img');
    ghost.className = 'fx-flying';
    ghost.alt = '';
    ghost.src = src;
    ghost.style.left = from.left + 'px';
    ghost.style.top = from.top + 'px';
    ghost.style.width = from.width + 'px';
    ghost.style.height = from.height + 'px';
    document.body.append(ghost);

    // Чтение размера заставляет браузер применить начальное положение до
    // того, как мы поставим конечное. Без этой строки перехода не будет
    // вовсе: браузер объединит обе правки и покажет только последнюю.
    void ghost.offsetWidth;

    ghost.style.left = onScreen(to.left + to.width / 2 - RL_FLY_SIZE / 2,
                                window.innerWidth) + 'px';
    ghost.style.top = onScreen(to.top + to.height / 2 - RL_FLY_SIZE / 2,
                               window.innerHeight) + 'px';
    ghost.style.width = RL_FLY_SIZE + 'px';
    ghost.style.height = RL_FLY_SIZE + 'px';
    ghost.style.opacity = '0';

    setTimeout(() => ghost.remove(), RL_FLY_MS + 80);
  }

  /** Дождаться, что «Качалка» открылась, и только тогда отпускать. */
  function whenOpened(then){
    let frames = 0;
    (function look(){
      const button = document.querySelector('.tabs button[data-tab="download"]');
      if(button && button.classList.contains('on')) return then();
      if(frames < RL_FLY_FRAMES){
        frames += 1;
        requestAnimationFrame(look);
      }
    })();
  }

  // Перехват, а не всплытие. Кнопки внутри строки гасят свой клик —
  // иначе «скачать» ещё и раскрывала бы карточку книги, — и до страницы
  // он не доходит вовсе. Перехват идёт сверху вниз, до самой кнопки, и
  // погасить его она уже не может.
  document.addEventListener('click', event => {
    if(!rlOn('cover-flight')) return;

    const button = event.target.closest && event.target.closest('#rkTable .tr button');
    if(!button) return;

    // Какую кнопку нажали, не разбираем: соседняя открывает меню
    // копирования и никуда не переходит, а полёт запускает не нажатие, а
    // открывшаяся вкладка. Подписи кнопок при этом остаются подписями, а
    // не опознавательными знаками.
    const tr = button.closest('.tr');
    const img = tr && tr.querySelector('.cover img');
    if(!img || !img.getAttribute('src')) return;

    // Место и картинку берём сейчас: пока «Качалка» откроется, рейтинг
    // уже спрячется, и мерить будет нечего.
    const from = img.getBoundingClientRect();
    const src = img.src;
    if(!from.width || !from.height) return;

    whenOpened(() => fly(from, src));
  }, true);
})();
