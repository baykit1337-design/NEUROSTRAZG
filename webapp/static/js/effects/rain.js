/* Дождь глифов под карточкой прогресса скачивания.
 *
 * Смысл эффекта не в красоте, а в ответе на давний вопрос: «один поток
 * сейчас работает или больше?». Цифра об этом говорит строкой ниже, но
 * цифру надо прочитать; плотность дождя видна боковым зрением. Один
 * поток — редкие одинокие струи, восемь — сплошная стена.
 *
 * Отсюда все решения ниже:
 *   • струй столько, какова доля живых потоков от полной загрузки;
 *   • прогон встал на паузу — дождь замирает на месте и тускнеет;
 *   • глава не скачалась — одна струя коротко краснеет;
 *   • прогон кончился — дождь гаснет сам, а не пропадает рывком.
 *
 * Холст закрашивает прямоугольник карточки наглухо. Панель у нас
 * полупрозрачная, сквозь неё видно звёздное поле, и два движущихся поля
 * в одних пикселях дерутся между собой. Непрозрачная подложка разводит
 * их, не требуя ни одной правки в звёздах.
 */

//: Ширина столбца в пикселях. Она же — шаг строки: клетка квадратная,
//: иначе хвост рвётся на быстрых струях.
const RAIN_CELL = 15;

//: Столько потоков считаем полной загрузкой: при них дождь идёт стеной.
//: Больше восьми качалка и не просит, а если попросит — доля упрётся в
//: единицу, и стена просто останется стеной.
const RAIN_FULL = 8;

//: Меньше двух струй — это уже не дождь, а две точки на чёрном. Столько
//: же показываем, пока потоков ещё нет: идёт поиск книги или оглавление.
const RAIN_LEAST = 2;

//: Скорость струи: строк в секунду. Разброс нужен обязательно — при
//: одинаковой скорости столбцы выстраиваются в шеренгу и дождь читается
//: как решётка, а не как дождь.
const RAIN_SPEED_MIN = 5;
const RAIN_SPEED_MAX = 15;

//: Длина хвоста в глифах.
const RAIN_TAIL_MIN = 6;
const RAIN_TAIL_MAX = 18;

//: Как часто глиф в хвосте подменяется другим. Без подмены хвост похож
//: на падающую надпись, а не на шум.
const RAIN_SWAP = 110;

//: Насколько гасится кадр. Это и рисует хвост: старые глифы затираются
//: не сразу, а слоями. Заливка полупрозрачная, но холст под ней уже
//: непрозрачен, и прозрачнее он от неё не станет — звёзды не проступят.
const RAIN_FADE = 0.16;

//: Сколько живёт краснота после нескачанной главы, в миллисекундах.
const RAIN_FAIL_LIFE = 1800;

//: Сколько струй краснеет разом, сколько бы глав ни отвалилось за один
//: опрос: краснота — сигнал, а не заливка экрана.
const RAIN_FAIL_MAX = 3;

//: На паузе дождь не пропадает, а тускнеет: работа стоит, но не кончена.
const RAIN_HELD_DIM = 0.35;

//: Голова струи почти белая, хвост — цвета темы, беда — красная.
const RAIN_HEAD = '236, 226, 255';
const RAIN_BODY = '176, 108, 255';
const RAIN_FAIL = '255, 92, 92';

//: Предел яркости. Дождь — подложка под текстом, и спорить с ним за
//: внимание он не должен: цифры прогресса важнее.
const RAIN_HEAD_ALPHA = 0.70;
const RAIN_BODY_ALPHA = 0.30;

//: При скольких струях дождь идёт в полную яркость.
//:
//: Сообщение несёт плотность, а не яркость. Если оставить яркость
//: одинаковой, стена из сорока струй забивает цифры прогресса — это
//: проверено на экране: «скачано 84» приходилось выискивать. Поэтому
//: чем гуще дождь, тем тише каждая струя: корень от отношения даёт
//: суммарную яркость, растущую заметно, но не линейно. Один поток от
//: восьми при этом по-прежнему отличается с одного взгляда.
const RAIN_CALM_STREAMS = 10;

//: Цвет подложки — фон страницы. Держим числами: заливка идёт с
//: прозрачностью, а `var(--bg)` в `rgba()` не подставить.
const RAIN_BASE = '7, 6, 10';

//: Из чего складывается шум. Полуширинная катакана — та самая азбука из
//: «Матрицы»; цифры и латиница разбавляют её, чтобы не выглядело
//: заимствованием один в один.
const RAIN_GLYPHS = 'ｦｱｳｴｵｶｷｹｺｻｼｽｾｿﾀﾂﾃﾅﾆﾇﾈﾊﾋﾎﾏﾐﾑﾒﾓﾔﾕﾗﾘﾜ'
  + '0123456789'
  + 'ABCDEFGHKLMNPRSTUXYZ';

function rainOn(){
  return document.documentElement.classList.contains('fx-rain');
}

/** Системная настройка «уменьшить движение» сильнее галочки.
 *
 * У звёзд при ней остаётся мерцание: там движение — добавка к эффекту.
 * Здесь движение и есть эффект, отнимать у него падение бессмысленно —
 * останется столбик неподвижных букв. Поэтому дождь просто не идёт.
 */
function rainCalm(){
  return window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function rainBetween(from, to){
  return from + Math.random() * (to - from);
}

function rainGlyph(){
  return RAIN_GLYPHS[Math.floor(Math.random() * RAIN_GLYPHS.length)];
}

(function glyphrain(){
  let card = null;
  let canvas = null;
  let ctx = null;

  let streams = [];
  let cols = 0;
  let rows = 0;

  let running = false;
  let lastFrame = 0;
  let frames = 0;

  //: Размер самого холста в последний пересчёт.
  let drawnW = 0;
  let drawnH = 0;
  //: И размер карточки под ним — по нему видно, что она подросла.
  let cardW = 0;
  let cardH = 0;

  //: Что сейчас происходит в прогоне. Пишет сюда качалка через
  //: `rainTune`, дождь только читает.
  const live = {threads: 0, busy: false, held: false, failed: 0};
  let seenFailed = 0;

  function makeStream(col){
    const tail = Math.round(rainBetween(RAIN_TAIL_MIN, RAIN_TAIL_MAX));
    const glyphs = [];
    for(let i = 0; i < tail; i++) glyphs.push(rainGlyph());
    return {
      col,
      // Начинает выше верхнего края, вразнобой: иначе все струи
      // стартуют одной шеренгой.
      y: -rainBetween(0, rows),
      row: -1,
      speed: rainBetween(RAIN_SPEED_MIN, RAIN_SPEED_MAX),
      tail, glyphs,
      swapAt: 0,
      fail: 0,
      leaving: false,
    };
  }

  //: Свободный столбец. Две струи в одном столбце накладываются друг на
  //: друга и выглядят как одна дёрганая.
  function freeCol(){
    const taken = new Set(streams.filter(s => !s.leaving).map(s => s.col));
    const free = [];
    for(let col = 0; col < cols; col++) if(!taken.has(col)) free.push(col);
    if(!free.length) return -1;
    return free[Math.floor(Math.random() * free.length)];
  }

  /* Сколько струй должно идти прямо сейчас.
   *
   * Доля живых потоков от полной загрузки — она же доля занятых
   * столбцов. Потоков ещё нет (идёт поиск книги, собирается
   * оглавление) — показываем самый минимум: работа началась, но
   * качать ещё нечего.
   */
  function want(){
    if(!live.busy || !cols) return 0;
    if(!live.threads) return RAIN_LEAST;
    const share = Math.min(1, live.threads / RAIN_FULL);
    return Math.max(RAIN_LEAST, Math.round(cols * share));
  }

  //: Струи не появляются и не исчезают пачкой: лишние дописывают своё
  //: падение и уходят за нижний край, недостающие приходят сверху.
  function balance(){
    const target = want();
    const staying = streams.filter(s => !s.leaving);

    if(staying.length > target){
      // Уводим самые свежие — те, что ещё наверху: у нижних хвост уже
      // на виду, и обрывать его посреди карточки заметнее.
      const surplus = staying.slice().sort((a, b) => a.y - b.y);
      for(let i = 0; i < staying.length - target; i++) surplus[i].leaving = true;
    }

    for(let i = staying.length; i < target; i++){
      const col = freeCol();
      if(col < 0) break;
      streams.push(makeStream(col));
    }
  }

  /* Нескачанная глава красит струю.
   *
   * Считаем по приросту счётчика ошибок: качалка отдаёт его на каждом
   * опросе, а событий «вот эта глава упала» наружу не выдаёт.
   */
  function markFails(){
    if(live.failed <= seenFailed){
      // Счётчик сбросился — начался новый прогон.
      seenFailed = live.failed;
      return;
    }
    const fresh = Math.min(live.failed - seenFailed, RAIN_FAIL_MAX);
    seenFailed = live.failed;
    const calm = streams.filter(s => !s.fail);
    for(let i = 0; i < fresh && calm.length; i++){
      const pick = Math.floor(Math.random() * calm.length);
      calm[pick].fail = RAIN_FAIL_LIFE;
      calm.splice(pick, 1);
    }
  }

  function advance(now, elapsed){
    for(let i = streams.length - 1; i >= 0; i--){
      const stream = streams[i];
      stream.y += stream.speed * elapsed / 1000;
      if(stream.fail) stream.fail = Math.max(0, stream.fail - elapsed);

      // Голова перешла на новую строку — в хвост въезжает новый глиф.
      const row = Math.floor(stream.y);
      if(row !== stream.row){
        stream.row = row;
        stream.glyphs.unshift(rainGlyph());
        stream.glyphs.length = stream.tail;
      }

      // Подмена случайного глифа в хвосте: без неё хвост читается как
      // падающая надпись, а не как шум.
      if(now >= stream.swapAt){
        stream.swapAt = now + rainBetween(RAIN_SWAP, RAIN_SWAP * 3);
        stream.glyphs[Math.floor(Math.random() * stream.tail)] = rainGlyph();
      }

      // Хвост ушёл за нижний край.
      if(stream.y - stream.tail > rows){
        if(stream.leaving){
          streams.splice(i, 1);
        }else{
          const born = makeStream(stream.col);
          born.y = -rainBetween(0, rows * 0.6);
          streams[i] = born;
        }
      }
    }
  }

  function paint(){
    if(!ctx) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;

    // Гашение кадра — оно же рисование хвоста. Холст под заливкой уже
    // непрозрачен, прозрачнее он не станет: звёзды сквозь него не
    // проступят, сколько бы кадров ни прошло.
    ctx.fillStyle = `rgba(${RAIN_BASE}, ${RAIN_FADE})`;
    ctx.fillRect(0, 0, width, height);

    ctx.font = (RAIN_CELL - 2) + 'px ui-monospace, SFMono-Regular, Menlo, '
      + 'Consolas, monospace';
    ctx.textBaseline = 'top';

    // Чем гуще дождь, тем тише каждая струя: иначе стена забивает цифры,
    // ради которых карточка и существует.
    const dim = Math.min(1, Math.sqrt(RAIN_CALM_STREAMS
                                      / Math.max(1, streams.length)));

    for(const stream of streams){
      const x = stream.col * RAIN_CELL;
      const hurt = stream.fail / RAIN_FAIL_LIFE;
      for(let i = 0; i < stream.tail; i++){
        const row = Math.floor(stream.y) - i;
        if(row < 0 || row > rows) continue;
        // Яркость падает по хвосту квадратом: линейное затухание
        // оставляет хвост равномерно светлым и слишком заметным.
        const near = 1 - i / stream.tail;
        const head = i === 0;
        const alpha = dim
          * (head ? RAIN_HEAD_ALPHA : near * near * RAIN_BODY_ALPHA);
        const color = head
          ? (hurt > 0.5 ? RAIN_FAIL : RAIN_HEAD)
          : (hurt > 0 ? RAIN_FAIL : RAIN_BODY);
        ctx.fillStyle = `rgba(${color}, ${alpha})`;
        ctx.fillText(stream.glyphs[i] || '', x, row * RAIN_CELL);
      }
    }
  }

  function frame(now){
    if(!running) return;
    // Пауза: работа стоит — и дождь стоит. Кадры при этом не считаем
    // вовсе: картинка не меняется, а пауза может тянуться сколько
    // угодно. Холст держит последний кадр, приглушённый стилями, —
    // застывший дождь и есть сообщение о том, что прогон встал.
    if(live.held){
      stop();
      return;
    }
    const elapsed = lastFrame ? Math.min(now - lastFrame, 1000) : 0;
    lastFrame = now;
    frames++;
    // Карточка растёт по ходу прогона: появляются подробности пробы,
    // строка про прокси, сводка. Окно при этом не меняется, и события
    // `resize` не будет — сверяемся сами.
    if(card && (card.clientWidth !== cardW || card.clientHeight !== cardH)){
      resize();
    }
    balance();
    advance(now, elapsed);
    paint();
    requestAnimationFrame(frame);
  }

  function resize(){
    if(!canvas || !card) return;
    // Размер берём у самого холста, а не у карточки: он лежит с отступом
    // на толщину рамки, и «как у карточки» было бы на два пикселя
    // больше — дождь вылезал бы на фиолетовую линию.
    const box = canvas.getBoundingClientRect();
    const width = Math.round(box.width);
    const height = Math.round(box.height);
    if(!width || !height) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    drawnW = width;
    drawnH = height;
    // Под какую карточку посчитано — по ней и сверяемся, когда она
    // растёт по ходу прогона.
    cardW = card.clientWidth;
    cardH = card.clientHeight;
    cols = Math.max(1, Math.ceil(width / RAIN_CELL));
    rows = Math.max(1, Math.ceil(height / RAIN_CELL));

    // Первая заливка — сплошная. Дальше кадр гасится полупрозрачной, и
    // непрозрачность холста держится именно с этого раза.
    ctx.fillStyle = 'rgb(' + RAIN_BASE + ')';
    ctx.fillRect(0, 0, width, height);

    // Струи живут в столбцах: после смены размера столбцы другие, и те,
    // что оказались за краем, надо вернуть на поле.
    for(const stream of streams){
      if(stream.col >= cols) stream.col = Math.floor(Math.random() * cols);
    }
  }

  function build(){
    if(canvas) return canvas;
    card = document.getElementById('progress');
    if(!card) return null;
    canvas = document.createElement('canvas');
    canvas.className = 'glyphrain';
    canvas.setAttribute('aria-hidden', 'true');
    // Прячет холст скрипт, а не стили: правило без `.fx-` работало бы и
    // со снятой галочкой, а такого в файлах эффектов быть не должно.
    canvas.hidden = !rainOn();
    card.prepend(canvas);
    resize();
    return canvas;
  }

  function start(){
    if(running || !rainOn() || rainCalm()) return;
    if(!live.busy) return;
    if(!build()) return;
    // Карточка прогресса до начала работы спрятана и размера не имеет:
    // мерить её можно только сейчас.
    if(!cols || !rows || card.clientHeight !== cardH) resize();
    // Прошлый прогон оставил на холсте свои глифы. Гасятся они за
    // десяток кадров, но эти кадры видны: новый прогон начинается с
    // чужого дождя. Заливаем начисто.
    if(!streams.length && ctx){
      ctx.fillStyle = 'rgb(' + RAIN_BASE + ')';
      ctx.fillRect(0, 0, drawnW, drawnH);
    }
    canvas.hidden = false;
    canvas.style.opacity = live.held ? RAIN_HELD_DIM : 1;
    running = true;
    lastFrame = 0;
    requestAnimationFrame(frame);
  }

  function stop(){
    running = false;
    lastFrame = 0;
  }

  /* Прогон кончился: дождь гаснет сам.
   *
   * Гасим прозрачностью холста, а не остановкой кадров: рывком
   * исчезнувшая подложка читается как сбой отрисовки. Кадры добиваем
   * после того, как гашение доиграло.
   */
  function fade(){
    if(!canvas || canvas.hidden) return;
    canvas.style.opacity = 0;
    setTimeout(() => {
      if(live.busy) return;   // за время гашения начался новый прогон
      stop();
      streams = [];
      if(canvas) canvas.hidden = true;
    }, 950);
  }

  /* Единственная дверь снаружи: качалка на каждом опросе рассказывает,
   * что происходит, а дождь решает, как это показать.
   */
  window.rainTune = (state) => {
    const was = live.busy;
    live.threads = Number(state.threads) || 0;
    live.busy = !!state.busy;
    live.held = !!state.held;
    live.failed = Number(state.failed) || 0;

    if(!live.busy){
      if(was) fade();
      return;
    }
    markFails();
    if(canvas) canvas.style.opacity = live.held ? RAIN_HELD_DIM : 1;
    start();
  };

  /* Слепок состояния наружу.
   *
   * Дождь рисуется на холсте: снаружи не видно ни струй, ни их числа, и
   * проверить «столько ли струй, сколько потоков» нечем — только
   * глазами, а глаз столбцы не пересчитает.
   */
  window.glyphrainState = () => ({
    running, frames, cols, rows,
    threads: live.threads,
    busy: live.busy,
    held: live.held,
    want: want(),
    count: streams.length,
    leaving: streams.filter(s => s.leaving).length,
    hurt: streams.filter(s => s.fail > 0).length,
    opacity: canvas ? Number(canvas.style.opacity || 1) : 0,
    columns: streams.map(s => s.col),
  });

  // Вкладка неактивна — считать кадры некому и незачем.
  document.addEventListener('visibilitychange', () => {
    if(document.hidden) stop();
    else start();
  });

  window.addEventListener('resize', () => {
    if(!canvas) return;
    resize();
  });

  // Галочку могли снять посреди прогона — тогда дождь убирается сразу,
  // без гашения: гашение означает «работа кончилась», а она идёт.
  const watch = new MutationObserver(() => {
    if(rainOn()) start();
    else{
      stop();
      streams = [];
      if(canvas) canvas.hidden = true;
    }
  });
  watch.observe(document.documentElement,
                {attributes: true, attributeFilter: ['class']});
})();
