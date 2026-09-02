/* Связь: точки прокси, искры запросов и кардиограмма трафика.
 *
 * Три эффекта одним файлом: все три живут с одного и того же опроса
 * качалки и одной и той же полоски разметки, которую сами же и заводят.
 * Каждый по-прежнему снимается своей галочкой — снятая убирает и
 * разметку: пустой провод или ряд из нуля точек занимал бы место молча.
 *
 * Дверь наружу одна — `netTune`, — и устроена она так же, как у дождя:
 * качалка на каждом опросе рассказывает, что происходит, а эффекты
 * решают, как это показать. Про задачи и запросы им знать нечего.
 *
 * `fxHas` объявлена в `pointer.js`, который подключается раньше.
 */

//: Больше этого числа точек в ряд не ставим: восьми потоков качалка не
//: просит, а сотня адресов в списке — это список, а не строка состояния.
const NET_DOTS_MAX = 12;

//: Сколько держится погасшая точка после подмены адреса.
const NET_SWAP_MS = 900;

//: Сколько искр пускаем за один опрос, сколько бы глав ни пришло. Искра —
//: указатель жизни, а не счётчик: две сотни разом слились бы в полосу.
const NET_SPARK_MAX = 4;

//: Сколько летит искра. Держать в согласии с `request-pulse.css`.
const NET_SPARK_MS = 900;

//: Как часто спрашиваем трафик и сколько замеров держит график.
const NET_TRAFFIC_MS = 1500;
const NET_TRAFFIC_KEEP = 40;

//: Размер кардиограммы в точках разметки.
const NET_GRAPH_W = 120;
const NET_GRAPH_H = 26;

//: Что качалка рассказала в последний раз.
const netLive = {busy: false, held: false, proxies: 0, switches: 0,
                 done: 0, failed: 0};

/** Полоска под строкой способа. Заводится при первой надобности. */
function netStrip(){
  let strip = document.getElementById('fxNet');
  if(strip) return strip;

  const after = document.getElementById('sMethod');
  if(!after) return null;

  strip = document.createElement('div');
  strip.id = 'fxNet';
  strip.className = 'pnow fxnet';
  strip.style.display = 'flex';
  strip.style.alignItems = 'center';
  strip.style.gap = '10px';
  after.after(strip);
  return strip;
}

function netDrop(selector){
  const node = document.querySelector('#fxNet ' + selector);
  if(node) node.remove();
}

/* --------------------------------------------------- точки прокси */

(function netDots(){
  let seenSwitches = 0;

  function box(){
    const strip = netStrip();
    if(!strip) return null;
    let found = strip.querySelector('.fxnet-dots');
    if(!found){
      found = document.createElement('span');
      found.className = 'fxnet-dots';
      // Первой в полоске: адреса — это про то, чем качаем, а искры — про
      // то, что качается.
      strip.prepend(found);
    }
    return found;
  }

  /** Одна точка гаснет: адрес подменили. */
  function swap(found){
    const dots = found.querySelectorAll('.fxnet-dot');
    if(!dots.length) return;
    const dot = dots[Math.floor(Math.random() * dots.length)];
    dot.classList.add('fxnet-gone');
    setTimeout(() => dot.classList.remove('fxnet-gone'), NET_SWAP_MS);
  }

  window.netDotsTune = () => {
    if(!fxHas('proxy-dots') || !netLive.busy){
      netDrop('.fxnet-dots');
      seenSwitches = netLive.switches;
      return;
    }

    const found = box();
    if(!found) return;

    const want = Math.min(NET_DOTS_MAX, Math.max(1, netLive.proxies || 1));
    while(found.children.length < want){
      const dot = document.createElement('i');
      dot.className = 'fxnet-dot';
      found.append(dot);
    }
    while(found.children.length > want) found.lastChild.remove();

    found.classList.toggle('fxnet-held', netLive.held);
    found.title = netLive.proxies
      ? `Адресов в работе: ${netLive.proxies}`
      : 'Качаем напрямую, без прокси';

    if(netLive.switches > seenSwitches){
      swap(found);
      seenSwitches = netLive.switches;
    }
  };
})();

/* ---------------------------------------------------- искры запросов */

(function netPulse(){
  let seenDone = 0, seenFailed = 0;

  function wire(){
    const strip = netStrip();
    if(!strip) return null;
    let found = strip.querySelector('.fxnet-wire');
    if(!found){
      found = document.createElement('span');
      found.className = 'fxnet-wire';
      strip.append(found);
    }
    return found;
  }

  function spark(found, bad){
    const dot = document.createElement('i');
    dot.className = 'fxnet-spark' + (bad ? ' fxnet-bad' : '');
    found.append(dot);
    setTimeout(() => dot.remove(), NET_SPARK_MS + 60);
  }

  window.netPulseTune = () => {
    if(!fxHas('request-pulse') || !netLive.busy){
      netDrop('.fxnet-wire');
      seenDone = netLive.done;
      seenFailed = netLive.failed;
      return;
    }

    const found = wire();
    if(!found) return;

    // Пауза — обмена нет, и искрам взяться неоткуда. Счётчики при этом
    // запоминаем: иначе после снятия с паузы посыплется всё разом.
    const fresh = Math.max(0, netLive.done - seenDone);
    const lost = Math.max(0, netLive.failed - seenFailed);
    seenDone = netLive.done;
    seenFailed = netLive.failed;
    if(netLive.held) return;

    for(let at = 0; at < Math.min(lost, NET_SPARK_MAX); at += 1){
      spark(found, true);
    }
    for(let at = 0; at < Math.min(fresh, NET_SPARK_MAX); at += 1){
      setTimeout(spark, at * 90, found, false);
    }
  };
})();

/* ------------------------------------------------ кардиограмма трафика */

(function netTraffic(){
  //: Замеры байтов в секунду, самый свежий — последний.
  let speeds = [];
  let last = null, at = null, timer = null;

  function panel(){
    let box = document.getElementById('fxTraffic');
    if(box) return box;

    box = document.createElement('div');
    box.id = 'fxTraffic';

    const canvas = document.createElement('canvas');
    canvas.className = 'fxnet-graph';
    canvas.width = NET_GRAPH_W;
    canvas.height = NET_GRAPH_H;
    canvas.style.width = NET_GRAPH_W + 'px';
    canvas.style.height = NET_GRAPH_H + 'px';

    const said = document.createElement('span');
    said.className = 'fxnet-speed';

    box.append(canvas, said);
    document.body.append(box);
    return box;
  }

  function drop(){
    clearInterval(timer);
    timer = null;
    speeds = [];
    last = at = null;
    const box = document.getElementById('fxTraffic');
    if(box) box.remove();
  }

  /** Байты в человеческом виде. Своя, потому что `weigh` со страницы
   *  считает объём файла, а тут скорость — и подпись другая. */
  function speedText(bytes){
    if(bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' МБ/с';
    if(bytes >= 1024) return Math.round(bytes / 1024) + ' КБ/с';
    return Math.round(bytes) + ' Б/с';
  }

  function draw(){
    const box = document.getElementById('fxTraffic');
    if(!box) return;
    const canvas = box.querySelector('.fxnet-graph');
    const paint = canvas.getContext('2d');
    paint.clearRect(0, 0, NET_GRAPH_W, NET_GRAPH_H);

    box.querySelector('.fxnet-speed').textContent =
      speedText(speeds.length ? speeds[speeds.length - 1] : 0);

    if(speeds.length < 2) return;

    // Высоту меряем по своему же окну: у книги с картинками и у книги из
    // одного текста скорости разнятся на два порядка, и общей меркой
    // одна из них всегда была бы плоской линией.
    const top = Math.max(1, ...speeds);
    const step = NET_GRAPH_W / (NET_TRAFFIC_KEEP - 1);

    paint.beginPath();
    speeds.forEach((speed, index) => {
      const x = index * step;
      const y = NET_GRAPH_H - 1 - (speed / top) * (NET_GRAPH_H - 2);
      index ? paint.lineTo(x, y) : paint.moveTo(x, y);
    });
    paint.strokeStyle = '#c084fc';
    paint.lineWidth = 1.5;
    paint.lineJoin = 'round';
    paint.stroke();
  }

  async function measure(){
    try{
      const got = await call('/api/traffic');
      const now = Date.now();
      const bytes = Number(got.session) || 0;
      if(last !== null && now > at){
        speeds.push(Math.max(0, (bytes - last) / ((now - at) / 1000)));
        while(speeds.length > NET_TRAFFIC_KEEP) speeds.shift();
      }
      last = bytes;
      at = now;
      draw();
    }catch(err){
      // Сервер не ответил — это тоже ответ: связи нет.
      speeds.push(0);
      while(speeds.length > NET_TRAFFIC_KEEP) speeds.shift();
      draw();
    }
  }

  window.netTrafficTune = () => {
    if(!fxHas('traffic-line') || !netLive.busy) return drop();
    if(timer) return;
    panel();
    measure();
    timer = setInterval(measure, NET_TRAFFIC_MS);
  };

  // Вкладка скрыта — спрашивать нечего и некому показывать.
  document.addEventListener('visibilitychange', () => {
    if(document.hidden){
      clearInterval(timer);
      timer = null;
    }else{
      window.netTrafficTune();
    }
  });
})();

/* Единственная дверь снаружи. */
window.netTune = (state) => {
  netLive.busy = !!state.busy;
  netLive.held = !!state.held;
  netLive.proxies = Number(state.proxies) || 0;
  netLive.switches = Number(state.switches) || 0;
  netLive.done = Number(state.done) || 0;
  netLive.failed = Number(state.failed) || 0;

  netDotsTune();
  netPulseTune();
  netTrafficTune();

  // Полоска опустела — убираем и её: пустая строка между способом и
  // кнопками выглядит как забытый отступ.
  const strip = document.getElementById('fxNet');
  if(strip && !strip.children.length) strip.remove();
};

/** Слепок наружу: и точки, и искры живут доли секунды, и проверить их
 *  иначе нечем. */
window.netState = () => ({
  dots: document.querySelectorAll('#fxNet .fxnet-dot').length,
  gone: document.querySelectorAll('#fxNet .fxnet-dot.fxnet-gone').length,
  sparks: document.querySelectorAll('#fxNet .fxnet-spark').length,
  bad: document.querySelectorAll('#fxNet .fxnet-spark.fxnet-bad').length,
  wire: !!document.querySelector('#fxNet .fxnet-wire'),
  graph: !!document.getElementById('fxTraffic'),
});
