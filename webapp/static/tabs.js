/* Вкладки «Переименовать», «Разбить», «Объединить» и «Проверка текста».
 *
 * Общие помощники ($, call, showError, TERMINAL) объявлены в index.html и
 * доступны здесь: этот файл подключается следом.
 */

/* ------------------------------------------------- системный проводник */

/** Кнопки «Обзор…» — открывают настоящее окно Windows. */
async function pickPath(button){
  const input = $(button.dataset.target);
  const kind = button.dataset.kind === 'file' ? 'file' : 'folder';
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Окно…';
  try{
    const data = await call('/api/pick/' + kind, {initial: input.value.trim()});
    if(data.path){
      input.value = data.path;
      input.dispatchEvent(new Event('input'));
      // И `change` следом: выбор в системном окне — такое же решение
      // человека, как набранный руками путь, и запомниться должен так же.
      // Обработчиков `change` на этих полях больше нет ни одного, так
      // что второе событие никого не будит зря.
      input.dispatchEvent(new Event('change'));
    }
  }catch(err){
    // Проводника нет — встроенный обозреватель остаётся запасным вариантом.
    showError(err.message + '. Путь можно вписать вручную.');
  }finally{
    button.disabled = false;
    button.textContent = label;
  }
}

document.querySelectorAll('.browse').forEach(b => { b.onclick = () => pickPath(b); });

// Без графической оболочки кнопки бесполезны — убираем их.
call('/api/pick/available').then(data => {
  if(!data.available){
    document.querySelectorAll('.browse').forEach(b => b.remove());
  }
}).catch(() => {});

// На вкладке «Качалка» проводник отдаёт путь через скрытое поле, а
// дальше подхватывает её собственный обозреватель.
$('baseHidden').addEventListener('input', e => browse(e.target.value));


/* ------------------------------------------------- всплывающие подсказки */

/* Подсказки рисует общий слой на уровне body (index.html, 1.4 ТЗ).
 *
 * Раньше подсказка была вложена в сам значок и разворачивалась внутрь
 * карточки — граница карточки её обрезала, и текст у пометки «проверьте»
 * прочитать было нельзя. Заодно исчезли три копии одного и того же кода
 * и привязка «только к тому, что было на странице при загрузке»: слой
 * ловит наведение на лету, поэтому подсказки работают и у строк, которые
 * дорисованы позже.
 */

/** Ставит подсказку на произвольный элемент (для галочек, что строит JS). */
function attachTip(element, text){
  if(!text) return;
  const icon = document.createElement('i');
  icon.className = 'hint-icon';
  icon.textContent = '?';
  // Текст живёт в атрибуте — дальше его найдёт общий слой.
  icon.dataset.tip = text;
  element.append(icon);
}

/* ----------------------------------------------- свои выпадающие списки */

/** Нативный select был белым и нечитаемым — рисуем свой. */
function makeDropdown(node, onChange){
  const options = JSON.parse(node.dataset.options || '[]');
  let value = options.length ? options[0][0] : '';

  const toggle = document.createElement('button');
  toggle.className = 'ghost dropdown-toggle';
  const menu = document.createElement('div');
  menu.className = 'dropdown-menu';
  menu.hidden = true;

  function label(){
    const found = options.find(o => o[0] === value);
    const text = found ? found[1] : '';
    const name = document.createElement('span');
    name.className = 'dd-label';
    name.textContent = text;
    // Длинное название («Новинки авторов-новичков») в кнопку не влезало:
    // текст переносился на вторую строку и вылезал за её рамку. Обрезаем
    // многоточием, а целиком показываем подсказкой.
    name.title = text;
    const caret = document.createElement('span');
    caret.className = 'dd-caret';
    caret.textContent = '▾';
    toggle.replaceChildren(name, caret);
  }

  for(const [key, text] of options){
    const item = document.createElement('div');
    item.className = 'dropdown-item';
    item.textContent = text;
    item.onclick = () => {
      value = key;
      menu.hidden = true;
      menu.querySelectorAll('.dropdown-item').forEach(i => i.classList.remove('selected'));
      item.classList.add('selected');
      label();
      if(onChange) onChange(value);
    };
    if(key === value) item.classList.add('selected');
    menu.append(item);
  }

  toggle.onclick = e => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  document.addEventListener('click', () => { menu.hidden = true; });

  label();
  node.append(toggle, menu);

  /** Выбрать пункт из кода: список моделей приходит с сервера, и
      подобранную по умолчанию надо отметить уже после отрисовки.

      Обработчик изменения по умолчанию НЕ зовётся: часть вызовов идёт
      как раз изнутри него, и получилось бы бесконечное кольцо. Кому
      нужно поведение как при нажатии — просит `notify` явно. */
  function set(key, options_ = {}){
    if(!options.some(o => o[0] === key)) return false;
    value = key;
    menu.querySelectorAll('.dropdown-item').forEach((item, index) => {
      item.classList.toggle('selected', options[index][0] === key);
    });
    label();
    if(options_.notify && onChange) onChange(value);
    return true;
  }

  /** Подпись выбранного пункта — то, что человек видит в списке.
   *
   * Наружу нужна там, где о выборе сообщают уже потом: в итоге
   * скачивания «источник: Fanqie (через посредника)» понятно, а
   * «источник: fanqie-mirror» — это ключ, и читать его человеку незачем.
   */
  function chosenLabel(){
    const found = options.find(o => o[0] === value);
    return found ? found[1] : value;
  }

  return {get value(){ return value; },
          get label(){ return chosenLabel(); }, set};
}

/* -------------------------------------- одна кнопка «Выбрать…» на всё */

//: Что выбрано на каждой вкладке: список путей.
const CHOSEN = {};

/** Рисует список выбранного с возможностью снять. */
function renderChosen(listId){
  const box = $(listId);
  const paths = CHOSEN[listId] || [];
  box.innerHTML = '';
  for(const path of paths){
    const row = document.createElement('div');
    row.className = 'item';
    const name = document.createElement('span');
    name.textContent = path.split(/[/\\]/).pop() || path;
    name.title = path;
    const drop = document.createElement('button');
    drop.textContent = '×';
    drop.title = 'Убрать из списка';
    drop.onclick = () => {
      CHOSEN[listId] = (CHOSEN[listId] || []).filter(p => p !== path);
      renderChosen(listId);
      if(box.dataset.onchange) window[box.dataset.onchange]();
    };
    row.append(name, drop);
    box.append(row);
  }
  syncPickPath(listId);
  updateListBar(listId);
}

/** Поле пути рядом с кнопкой «Выбрать…».
 *
 * Выбор файлов устроен одинаково во всех вкладках, а выглядел
 * по-разному: где-то поле с адресом и кнопка справа, где-то — голая
 * кнопка во всю строку. Поле здесь общее: показывает выбранное и
 * принимает путь, вписанный руками, — без него окно выбора, которое не
 * открылось, не обойти ничем.
 *
 * Поле есть не у каждого списка, и это не ошибка: у «Проверки» свой вид.
 */
function pickPathField(listId){
  return document.querySelector(`.pickpath[data-list="${listId}"]`);
}

function syncPickPath(listId){
  const field = pickPathField(listId);
  if(!field || field === document.activeElement) return;  // не мешаем набирать

  const paths = CHOSEN[listId] || [];
  // Один путь показываем целиком: он и есть ответ на вопрос «что выбрано».
  // Несколько — счётчиком, иначе строка превращается в кашу.
  field.value = paths.length === 1 ? paths[0]
    : (paths.length ? `выбрано ${paths.length} `
        + plural(paths.length, 'путь', 'пути', 'путей') : '');
  field.title = paths.join('\n');
}

document.querySelectorAll('.pickpath').forEach(field => {
  const listId = field.dataset.list;
  const apply = () => {
    const typed = field.value.trim();
    // Счётчик обратно в путь не превращаем: это наш текст, а не адрес.
    if(/^выбрано \d+ /.test(typed)) return;
    CHOSEN[listId] = typed ? [typed] : [];
    renderChosen(listId);
    const handler = $(listId).dataset.onchange;
    if(handler && window[handler]) window[handler]();
  };
  field.addEventListener('change', apply);
  field.addEventListener('keydown', e => { if(e.key === 'Enter') apply(); });
});

/** Счётчик и кнопка «Очистить список» у списка выбранных путей.
 *
 * Панель есть не у всех списков (у «Проверки» свой вид), поэтому её
 * отсутствие — не ошибка.
 */
function updateListBar(listId, files){
  const prefix = listId.replace(/List$/, '');
  const bar = document.getElementById(prefix + 'ListBar');
  if(!bar) return;

  const paths = (CHOSEN[listId] || []).length;
  bar.hidden = paths === 0;
  const label = document.getElementById(prefix + 'Count');
  if(!label) return;

  // Пока папку не прочитали, известно только число путей. После чтения
  // берём настоящее число файлов: выбрана одна папка, а в ней их тысяча.
  const count = files == null ? paths : files;
  label.textContent = `выбрано: ${count} ${plural(count, 'файл', 'файла', 'файлов')}`
    + (files != null && paths > 1 ? ` в ${paths} ${plural(paths, 'пути', 'путях', 'путях')}` : '');
}

document.querySelectorAll('.clearlist').forEach(button => {
  button.onclick = () => {
    // Выбрал по ошибке папку с тысячами файлов — снимается разом.
    const listId = button.dataset.list;
    // Снять выбор и оставить работу идти нельзя: она продолжит тратить
    // ключи на файлы, которые человек только что убрал с экрана.
    const tab = button.closest('section');
    if(tab) cancelTab(tab.id.replace('tab-', ''));
    CHOSEN[listId] = [];
    renderChosen(listId);
    const handler = $(listId).dataset.onchange;
    if(handler && window[handler]) window[handler]();
  };
});

/** Открыть системное окно и добавить выбранное к списку.
 *
 * Кнопки две, и каждая ведёт ровно в одно окно: «Файлы…» — в выбор
 * файлов, где берут и один, и сотню разом, «Папку…» — в выбор папки.
 *
 * Раньше кнопка была одна и показывала два окна подряд: сперва выбор
 * файлов, а если человек ничего не выбрал — выбор папки. Tk не умеет
 * окна, принимающего и то и другое, и обойти это внутри окна было нечем:
 * отказ и пустой выбор он отдаёт одинаково, отличить их со стороны
 * нельзя. Выходило, что «Отмена» открывает окно заново.
 *
 * Две кнопки снимают вопрос совсем: окно открывается одно, и «Отмена» в
 * нём значит отмену.
 */
async function pickAny(button, kind){
  const listId = button.dataset.list;
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Окно…';
  try{
    const data = await call('/api/pick/' + kind, {});
    if(data.paths?.length){
      // Добавляем к уже выбранному, дубликаты отсеиваем.
      const current = new Set(CHOSEN[listId] || []);
      data.paths.forEach(p => current.add(p));
      CHOSEN[listId] = [...current];
      renderChosen(listId);
      // Читается сразу после выбора — отдельной кнопки нет.
      const handler = $(listId).dataset.onchange;
      if(handler && window[handler]) window[handler]();
    }
  }catch(err){
    showError(err.message + ' Путь можно вписать в поле рядом.');
  }finally{
    button.disabled = false;
    button.textContent = label;
  }
}

document.querySelectorAll('.pickany').forEach(button => {
  button.onclick = () => pickAny(button, 'files');
});

document.querySelectorAll('.pickfolder').forEach(button => {
  button.onclick = () => pickAny(button, 'folder');
});


/** Склонение: «1 файл», «2 файла», «5 файлов». */
function plural(count, one, few, many){
  const tail = count % 10, hundred = count % 100;
  if(hundred >= 11 && hundred <= 14) return many;
  if(tail === 1) return one;
  if(tail >= 2 && tail <= 4) return few;
  return many;
}

/** Размер по-человечески: «412 МБ», а не «432013312».
 *
 * Тот же счёт, что и на сервере: килобайты и байты целыми, мегабайты и
 * гигабайты — с десятой долей. Иначе «0 МБ» стояло бы у всего, что
 * меньше половины мегабайта.
 */
function weigh(size){
  let step = Number(size) || 0;
  for(const name of ['Б', 'КБ', 'МБ', 'ГБ']){
    if(step < 1024 || name === 'ГБ'){
      return (name === 'Б' || name === 'КБ')
        ? `${Math.round(step)} ${name}`
        : `${step.toFixed(1)} ${name}`;
    }
    step /= 1024;
  }
  return `${size} Б`;
}

/** Расширения выбранного, по убыванию частоты: «.txt», «.txt и .docx». */
/** Разбор выбора по форматам: «.docx — 200, .txt — 100, .fb2 — 12».
 *
 * В одной папке форматы спокойно лежат вперемешку, и до запуска надо
 * видеть, что именно набралось: молча отсеянный десяток файлов иначе
 * обнаружится только по недостающим главам в готовой книге.
 */
function formatBreakdown(files){
  const seen = new Map();
  for(const path of files || []){
    const match = /\.[^./\\]+$/.exec(path);
    if(match) seen.set(match[0].toLowerCase(),
                       (seen.get(match[0].toLowerCase()) || 0) + 1);
  }
  return [...seen.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([suffix, count]) => `${suffix} — ${count}`)
    .join(', ');
}

function extensions(files){
  const seen = new Map();
  for(const path of files || []){
    const match = /\.[^./\\]+$/.exec(path);
    const suffix = match ? match[0].toLowerCase() : '';
    if(suffix) seen.set(suffix, (seen.get(suffix) || 0) + 1);
  }
  const list = [...seen.entries()].sort((a, b) => b[1] - a[1]).map(e => e[0]);
  if(!list.length) return '';
  return list.length <= 2 ? list.join(' и ') : `${list[0]} и ещё ${list.length - 1}`;
}

/**
 * Строка-схема «что на входе → что делаем → что на выходе».
 *
 * Собирается из фактического выбора, а не из задуманного: если выбрана
 * не та папка, это видно до запуска, а не после.
 */
function drawSchema(id, input, action, output){
  const box = $(id);
  if(!input.count){ box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = '';

  const left = document.createElement('span');
  left.innerHTML = `<b>${input.count}</b> ${plural(input.count, 'файл', 'файла', 'файлов')}`
    + (input.formats ? ` ${input.formats}` : '');

  const act = document.createElement('span');
  act.className = 'act';
  act.textContent = action;

  const right = document.createElement('span');
  right.innerHTML = `<b>${output.count}</b> ${plural(output.count, 'файл', 'файла', 'файлов')}`
    + ` ${output.format}`;

  const a1 = document.createElement('span'); a1.className = 'arrow'; a1.textContent = '→';
  const a2 = document.createElement('span'); a2.className = 'arrow'; a2.textContent = '→';
  box.append(left, a1, act, a2, right);
}

/* ------------------------------------------------------ общий прогресс */

/** Рисует полосу и возвращает true, пока операция идёт. */
function drawProgress(p, fillId, statusId, pctId){
  const busy = !TERMINAL.includes(p.stage);
  const pct = p.total ? Math.min(100, Math.round(p.done / p.total * 100)) : 0;
  const fill = $(fillId);
  // Полосе ожидания ширину не ставим: она у неё своя, бегущая, и наши
  // «0%» её бы просто погасили. Такая полоса стоит там, где процентов
  // взять неоткуда, — например под переводом книги.
  if(!fill.parentElement.classList.contains('waiting')) fill.style.width = pct + '%';
  // Блик бежит только пока идёт работа.
  fill.classList.toggle('active', busy);
  if(statusId) $(statusId).innerHTML = (busy ? '<span class="spin"></span>' : '') + (p.message || '');
  if(pctId) $(pctId).textContent = p.total ? pct + '%' : '';
  return busy;
}

/** Общий блок результата: кружок, пульсирующий текст, полоса (раздел 2). */
function drawResult(p, fillId, statusId, pctId){
  const busy = drawProgress(p, fillId, null, pctId);
  const box = $(statusId);
  if(box){
    box.textContent = p.message || '';
    // Состояние ставится на родителя — кружок и текст в такт.
    markResult(statusId, busy, p.stage);
  }
  // Секундомер и прогноз — рядом со счётчиками той же операции (2.1).
  // `LAST_JOB` выставляется прямо перед отрисовкой, поэтому здесь это
  // всегда та задача, чей прогресс сейчас и рисуется.
  drawTimers(statusId, LAST_JOB);
  return busy;
}

/** Сколько заняла операция, словами: «18 мин 42 с». */
function tookText(seconds){
  seconds = Math.round(seconds);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if(h) return `${h} ч ${m} мин`;
  if(m) return `${m} мин ${s} с`;
  return `${s} с`;
}


/* ---------- какая задача чьей вкладке принадлежит (7.8) ----------
 *
 * Раньше «Очистить список» просто снимал выбор, а задача продолжала идти:
 * таймер шёл, запросы к модели уходили, ключи тратились. Поэтому теперь у
 * каждой длительной работы есть хозяин — вкладка, — и всё, что задачу
 * отменяет, обращается сюда.
 */

const TAB_JOBS = {};

/** Задача началась и принадлежит этой вкладке. */
function ownJob(tab, jobId){
  TAB_JOBS[tab] = jobId;
}

/** Задача кончилась сама. */
function dropJob(tab){
  delete TAB_JOBS[tab];
}

/** Отменяет работу вкладки. Возвращает true, если было что отменять.
 *
 *  Качалка сюда намеренно не записывается: скачивание идёт часами, у него
 *  своя кнопка «Остановить» и своя докачка, и обрывать его переходом на
 *  соседнюю вкладку значило бы наказывать за любопытство. Правило про
 *  отмену появилось из-за ключей модели — их и бережём.
 */
function cancelTab(tab){
  const jobId = TAB_JOBS[tab];
  if(!jobId) return false;
  dropJob(tab);
  stopJob(jobId);
  return true;
}

/** Задача, которую сейчас рисуют.
 *
 *  Нужна `drawResult`: та получает от вкладок только прогресс, а таймерам
 *  нужны секундомер и признак завершения, которые лежат на самой задаче.
 *  Передавать job во все десять вызовов значило бы править каждый.
 */
let LAST_JOB = null;

/** Опрашивает задачу до конца. onDone получает готовый job. */
/* --------------------------------------- оповещение об окончании
 *
 * Скачивание на пятьсот глав идёт полчаса, и всё это время приходилось
 * смотреть в окно: уйдёшь — не узнаешь, что готово.
 *
 * Первым делом — заголовок вкладки браузера. Он виден всегда, ничего не
 * спрашивает и работает везде. Настоящее уведомление системы просим
 * только если человек его разрешил, и просим разрешения не при загрузке
 * страницы, а когда оно впервые понадобится: окно с вопросом на пустом
 * месте раздражает сильнее, чем польза от него.
 */

//: Каким заголовок был до того, как мы его тронули.
const TITLE_WAS = document.title;
let titleTimer = null;

function titleSay(text){
  clearInterval(titleTimer);
  if(!text){
    document.title = TITLE_WAS;
    return;
  }
  // Помигаем, пока на вкладку не посмотрят: неподвижная строка в ряду
  // из десяти вкладок теряется.
  let on = false;
  document.title = text;
  titleTimer = setInterval(() => {
    on = !on;
    document.title = on ? TITLE_WAS : text;
  }, 1200);
}

document.addEventListener('visibilitychange', () => {
  if(!document.hidden) titleSay('');
});

/** Говорит, что работа кончилась, — если на неё сейчас не смотрят. */
function jobDone(job){
  if(!document.hidden) return;
  const beda = job.error || (job.progress || {}).stage === 'error';
  const text = beda ? '✕ Не вышло — NEUROSTRAZH'
                    : '✓ Готово — NEUROSTRAZH';
  titleSay(text);
  try{
    if(!('Notification' in window)) return;
    if(Notification.permission === 'granted'){
      new Notification(text, {body: (job.progress || {}).message || ''});
    }else if(Notification.permission === 'default'){
      Notification.requestPermission();
    }
  }catch(err){
    // Уведомления запрещены настройками — заголовок уже сказал своё.
  }
}

function pollJob(jobId, draw, onDone){
  const timer = setInterval(async () => {
    try{
      const {job} = await call('/api/job/' + jobId);
      LAST_JOB = job;
      if(!draw(job)){
        clearInterval(timer);
        onDone(job);
        jobDone(job);
      }
    }catch(err){
      clearInterval(timer);
      showError(err.message);
    }
  }, 500);
  return timer;
}

function stopJob(jobId){
  return call('/api/job/' + jobId + '/cancel', {}).catch(err => showError(err.message));
}

/* ========================== Переименовать ========================== */

let rnChapters = [], rnRows = [], rnJob = null, rnTimer = null;
//: Ввод пути руками не должен дёргать сервер на каждой букве.
let rnScanTimer = null;
const rnSplits = {};      // путь к файлу -> на сколько частей
const rnChosen = new Set();  // отмеченные главы

function rnFormat(){
  return {
    number: $('rnNum').checked,
    part: $('rnPart').checked,
    title: $('rnTitle').checked,
    prefix: $('rnPrefix').value,
    separator: rnSepMenu ? rnSepMenu.value : ': ',
    // Как писать часть: «22.2» или «22. Часть 2». Обе записи
    // равноправны — выбор нужен, чтобы продолжение книги не сбивало
    // вид уже собранных глав.
    part_style: rnPartMenu ? rnPartMenu.value : 'dot',
  };
}

function rnPayload(){
  return {
    folder_in: $('rnIn').value.trim(),
    pattern: $('rnPattern').value.trim(),
    format: rnFormat(),
    splits: rnSplits,
    renumber: $('rnRenumber').checked,
    renumber_from: $('rnStart').value,
    // Без этого сервер брал умолчание `True`, и название главы
    // дописывалось в файл всегда — выключить его было нечем.
    headings: $('rnHeadings').checked,
    // Отмеченные строки. Понятия «служебный файл», который выпадает сам,
    // больше нет: что не нужно, человек снимает галочкой.
    chosen: [...rnChosen],
  };
}

/** Те же замены, что и на сервере (mvl/rename.py, FORBIDDEN_MAP). */
const FORBIDDEN = {':': ' -', '/': '-', '\\': '-', '|': '-',
                   '*': '', '?': '', '"': "'", '<': '(', '>': ')'};

function safeFilename(name){
  let out = name;
  for(const [bad, good] of Object.entries(FORBIDDEN)) out = out.split(bad).join(good);
  return out.replace(/\s+/g, ' ').replace(/^[\s.]+|[\s.]+$/g, '');
}

/** Живой пример имени на первой главе из папки. */
function rnUpdateExample(){
  const first = rnChapters.find(c => rnChosen.has(c.path)) || rnChapters[0];
  const fmt = rnFormat();
  if(!first){ $('rnExample').textContent = '—'; return; }

  // Часть показываем только если эта глава действительно разрезана: у целой
  // главы части нет, и включённая галочка ничего не добавляет.
  const part = rnSplits[first.path] > 1 ? 1 : first.part;

  let head = '';
  if(fmt.number && first.number !== null){
    head = fmt.prefix ? `${fmt.prefix} ${first.number}` : String(first.number);
    // Обе записи, как и на сервере: пример обязан совпадать с тем, что
    // получится на диске, иначе он вводит в заблуждение.
    if(fmt.part && part){
      head += fmt.part_style === 'word' ? `. Часть ${part}` : '.' + part;
    }
  }
  let name = head;
  if(fmt.title && first.title) name = head ? head + fmt.separator + first.title : first.title;

  // Пример показывает настоящее итоговое имя, а не то, которое Windows
  // всё равно не примет — иначе он расходился бы с предпросмотром.
  $('rnExample').textContent = safeFilename(name) || '—';

  const bad = /[:\\/*?"<>|]/.test(fmt.separator);
  $('rnForbidden').hidden = !bad;
  if(bad){
    $('rnForbidden').textContent =
      'Windows не разрешает такие символы в именах файлов, поэтому двоеточие ' +
      'заменяется на « -». В примере и предпросмотре видно итоговое имя.';
  }
}

async function rnScan(){
  showError('');
  try{
    const data = await call('/api/rename/scan', {
      folder_in: $('rnIn').value.trim(),
      pattern: $('rnPattern').value.trim(),
    });
    rnChapters = data.chapters;
    rnChosen.clear();
    Object.keys(rnSplits).forEach(k => delete rnSplits[k]);

    // По умолчанию отмечены все: ни один файл не исключается сам.
    rnChapters.forEach(c => rnChosen.add(c.path));

    $('rnScanned').textContent =
      `Файлов: ${data.total}` + (data.suspect ? `, проверьте: ${data.suspect}` : '');
    $('rnServiceNote').textContent = data.suspect
      ? `Разбор ${data.suspect} имён вызывает сомнения — они помечены значком. `
        + 'Файлы переименуются наравне с остальными; снимите галочку, если лишние.'
      : 'Все имена разобраны.';
    ['rnPatternCard','rnFormat','rnListCard','rnPlace'].forEach(id => { $(id).hidden = false; });
    // Формат на выходе — как у исходника, один раз на выбранную папку.
    // Имя папки само не подставляется: по умолчанию файлы ложатся прямо
    // в выбранную, и подставленное имя означало бы обратное.
    const paths = (rnChapters || []).map(c => c.path).join('|');
    if(paths !== rnState.forPaths){
      rnState.forPaths = paths;
      guessFormat(rnChapters.map(c => c.path), 'rnFormats', rnState,
                  () => {});
    }

    // Список рисуется без пересборки предпросмотра: собирать его дважды
    // подряд значит послать два запроса и отдать экран тому, который
    // вернётся последним (4.4 ТЗ).
    rnRenderList(false);
    rnUpdateExample();
    await rnBuildPreview();
    hdOffer('rnIn');
  }catch(err){
    showError(err.message);
    $('rnPatternCard').hidden = false;
  }
}

/** Рисует список глав. `build` — пересобрать ли заодно предпросмотр.
 *
 *  При чтении папки предпросмотр собирается отдельно и один раз: он
 *  нужен всегда, независимо от того, трогал ли кто-нибудь галочки.
 */
function rnRenderList(build = true){
  const list = $('rnList');
  list.innerHTML = '';
  for(const chapter of rnChapters){
    const row = document.createElement('div');
    row.className = 'tr' + (chapter.suspect ? ' suspect' : '');

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = rnChosen.has(chapter.path);
    box.onchange = () => {
      box.checked ? rnChosen.add(chapter.path) : rnChosen.delete(chapter.path);
      rnUpdateChosen();
    };

    const name = document.createElement('span');
    name.className = 'grow';
    name.textContent = chapter.name;

    const size = document.createElement('span');
    size.className = 'num';
    // Объём известен не всегда: тяжёлые форматы (.docx, .rtf) при показе
    // списка не читаются — разбор .docx стоит 46 мс на файл, и на
    // пятистах это полминуты перед пустым экраном. Текст возьмут при
    // записи, а здесь честно ставим прочерк.
    size.textContent = chapter.size == null
      ? '—' : chapter.size.toLocaleString('ru') + ' симв.';

    row.append(box, name);
    if(chapter.suspect){
      // Помечаем, но не отбираем: решает человек.
      const tag = document.createElement('span');
      tag.className = 'tag warn';
      tag.textContent = '⚠ проверьте';
      // Подсказка на самой пометке, а не на значке «?» внутри неё: значок
      // тут лишний, а целиться мышью в него — отдельное упражнение.
      if(chapter.suspect_reason) tag.dataset.tip = chapter.suspect_reason;
      row.append(tag);
    }
    if(chapter.number != null){
      const num = document.createElement('span');
      num.className = 'tag';
      num.textContent = chapter.assigned ? `№${chapter.number} по порядку`
                                         : `№${chapter.number}`;
      row.append(num);
    }
    if(rnSplits[chapter.path] > 1){
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = '÷' + rnSplits[chapter.path];
      row.append(tag);
    }
    row.append(size);
    list.append(row);
  }
  if(build) rnUpdateChosen();
}

/** Подпись под списком (1.5 ТЗ).
 *
 * Считаем по предпросмотру, а не по галочкам: в работу уходят именно его
 * строки. «Отмечено 206 из 206» при пустом предпросмотре — обещание,
 * которого кнопка не выполнит, и человек ищет причину не там.
 *
 * `rows` — сколько строк в предпросмотре; `null`, пока он не построен.
 */
function rnUpdateChosen(rows){
  const total = rnChapters.length;
  const shown = rows === null || rows === undefined
    ? '…' : rows;
  let text = `— в предпросмотре ${shown} из ${total}`;
  // Расхождение показываем только когда оно есть: обычно числа равны.
  if(rows !== null && rows !== undefined && rows !== rnChosen.size){
    text += `, отмечено ${rnChosen.size}`;
  }
  $('rnSelected').textContent = text;
  if(rows === null || rows === undefined) rnBuildPreview();
}

/** Почему предпросмотр пуст. Общее «сначала отметьте» ничего не чинит. */
function rnWhyEmpty(){
  if(!rnChapters.length){
    return 'В папке не нашлось ни одного файла с текстом.';
  }
  if(!rnChosen.size){
    return 'Сняты все галочки: отметьте главы в списке выше.';
  }
  return 'Главы отмечены, но предпросмотр пуст — разбор имён не дал ни '
    + 'одной главы. Задайте своё выражение в поле «Свой шаблон имени».';
}

//: Номер последней запрошенной сборки предпросмотра. Ответы приходят не
//: в том порядке, в каком уходили запросы, и отставший затирал бы свежий.
let rnBuildNo = 0;

async function rnBuildPreview(){
  const mine = ++rnBuildNo;
  try{
    const data = await call('/api/rename/plan', rnPayload());
    // Пока ходили на сервер, галочки могли поменять ещё раз — тогда этот
    // ответ уже про прошлое состояние, и показывать его нельзя.
    if(mine !== rnBuildNo) return;
    rnRows = data.rows;
    const table = $('rnPreview');
    table.innerHTML = '';

    data.rows.forEach((row, index) => {
      const line = document.createElement('div');
      line.className = 'tr' + (row.service ? ' service' : '');

      const old = document.createElement('span');
      old.className = 'grow';
      old.textContent = row.old_name;
      old.title = row.old_name;

      const arrow = document.createElement('span');
      arrow.className = 'arrow';
      arrow.textContent = '→';

      // Строку предпросмотра можно поправить руками.
      const input = document.createElement('input');
      input.className = 'rowname';
      input.value = row.new_name;
      input.oninput = () => { rnRows[index].new_name = input.value; };

      line.append(old, arrow, input);
      table.append(line);
    });

    $('rnPreviewCard').hidden = false;
    // Кнопка завязана на предпросмотр: в работу уходят его строки.
    $('rnApply').disabled = !data.rows.length;
    $('rnApplyHint').textContent = data.rows.length
      ? `Будет создано файлов: ${data.rows.length}. Оригиналы не изменятся.`
      : rnWhyEmpty();
    rnUpdateChosen(data.rows.length);
  }catch(err){
    if(mine !== rnBuildNo) return;
    // Предпросмотр не построился — причина нужна здесь же, у кнопки:
    // иначе она просто не нажимается и непонятно почему.
    showError(err.message, $('rnApply'));
    $('rnApply').disabled = true;
    $('rnApplyHint').textContent =
      'Предпросмотр не построился: ' + err.message;
    rnUpdateChosen(0);
  }
}

function rnApplySplit(parts){
  if(!rnChosen.size){
    showError('Отметьте главы, которые нужно поделить');
    return;
  }
  for(const path of rnChosen){
    if(parts > 1) rnSplits[path] = parts;
    else delete rnSplits[path];
  }
  // Части без своего номера получают одно имя на всех, и запись встанет
  // на совпадении имён. Галочка снята по умолчанию нарочно, но делят
  // главы — значит, номер части нужен.
  if(parts > 1) $('rnPart').checked = true;
  rnRenderList();
  rnUpdateExample();
  rnBuildPreview();
}

/** Окно «на сколько частей» — единственный вопрос, как в ТЗ. */
function rnAskParts(){
  if(!rnChosen.size){
    showError('Отметьте главы, которые нужно поделить');
    return;
  }
  $('rnDialog').hidden = false;
}

async function rnApply(){
  showError('');
  $('rnApply').disabled = true;
  try{
    const started = await askThenCall('/api/rename/apply', {
      ...rnPayload(),
      base: $('rnBase').value.trim(),
      folder_out: $('rnOut').value.trim(),
      out_format: rnState.format.replace('.', ''),
      names: rnRows.map(r => r.new_name),
    });
    // Пусто — человек отказался сохранять в занятую папку.
    if(!started) return;
    const job = started.job;
    rnJob = job.id;
    ownJob('rename', job.id);
    $('rnProgress').hidden = false;
    $('rnStop').hidden = false;
    $('rnSummary').textContent = 'Папка: ' + job.output_dir;

    rnTimer = pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('rnWritten').textContent = p.written || p.done || 0;
        $('rnFailed').textContent = p.failed || 0;
        return drawResult(p, 'rnFill', 'rnStatus', 'rnPct');
      },
      job => {
        $('rnStop').hidden = true;
        if(job.report){
          let text = `Папка: ${job.report.output_dir}`;
          if(job.report.failed_files?.length){
            text += '\nНе записаны:\n' + job.report.failed_files.join('\n');
          }
          $('rnSummary').style.whiteSpace = 'pre-line';
          $('rnSummary').textContent = text;
        }
        if(job.error) showError(job.error, $('rnSummary'));
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('rnApply').disabled = false;
  }
}

// Папка читается сразу после выбора — отдельной кнопки нет.
$('rnIn').addEventListener('input', () => {
  clearTimeout(rnScanTimer);
  rnScanTimer = setTimeout(() => { if($('rnIn').value.trim()) rnScan(); }, 400);
});
$('rnAll').onclick = () => {
  rnChapters.forEach(c => rnChosen.add(c.path));
  rnRenderList();
};
$('rnNone').onclick = () => { rnChosen.clear(); rnRenderList(); };
$('rnHalve').onclick = () => rnApplySplit(2);
$('rnSplit').onclick = rnAskParts;
$('rnRenumber').onchange = () => {
  $('rnStart').disabled = !$('rnRenumber').checked;
  rnBuildPreview();
};
['rnNum','rnPart','rnTitle'].forEach(id => {
  $(id).onchange = () => { rnUpdateExample(); rnBuildPreview(); };
});
['rnPrefix','rnStart'].forEach(id => {
  $(id).addEventListener('input', () => { rnUpdateExample(); rnBuildPreview(); });
});
const rnSepMenu = makeDropdown($('rnSep'), () => { rnUpdateExample(); rnBuildPreview(); });
const rnPartMenu = makeDropdown($('rnPartStyle'),
                                () => { rnUpdateExample(); rnBuildPreview(); });
$('rnPattern').addEventListener('keydown', e => { if(e.key === 'Enter') rnScan(); });
//: Формат на выходе у «Переименовать». Хранится так же, как у остальных
//: вкладок, чтобы кнопки строились общей функцией.
//: `forPaths` — для какой папки формат уже подобран по исходнику.
const rnState = {format: '.txt', forPaths: ''};
const rnPartsMenu = makeDropdown($('rnParts'));
$('rnPartsOk').onclick = () => {
  $('rnDialog').hidden = true;
  rnApplySplit(parseInt(rnPartsMenu.value, 10));
};
$('rnPartsCancel').onclick = () => { $('rnDialog').hidden = true; };
$('rnApply').onclick = rnApply;
$('rnStop').onclick = () => stopJob(rnJob);

/* ===================== «Разбить» и «Объединить» =====================
 *
 * Две зеркальные операции: один файл в множество и множество в один.
 * Раньше их было три вкладки («Разбить», «В Word», «В TXT»), и каждая
 * знала свой формат. Формат теперь параметр, а не отдельная вкладка,
 * поэтому настройки собираются одним кодом с разной приставкой в id.
 */

//: Списки форматов приходят с сервера: иначе новый формат пришлось бы
//: добавлять и в ядре, и здесь.
let FORMATS = {readable: [], writable: ['.txt']};

/** Кнопки выбора формата на выходе. */
function buildFormats(rowId, state, onChange){
  const row = $(rowId);
  row.innerHTML = '';
  for(const suffix of FORMATS.writable){
    const btn = document.createElement('button');
    btn.className = 'pick' + (suffix === state.format ? ' on' : '');
    btn.textContent = suffix;
    btn.onclick = () => {
      state.format = suffix;
      row.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === btn));
      onChange();
    };
    row.append(btn);
  }
}

/** Оформление .docx — общее для обеих вкладок, отличается приставкой id. */
function styleOf(p, menus){
  const chosen = menus.font ? menus.font.value : 'Times New Roman';
  return {
    font: chosen === '__other__'
      ? ($(p + 'FontOther').value.trim() || 'Times New Roman') : chosen,
    size: $(p + 'Size').value,
    line_spacing: $(p + 'Spacing').value,
    first_line_indent_cm: $(p + 'Indent').value,
    page_break_between_chapters: $(p + 'Break').checked,
  };
}

function prepOf(p, menus){
  return {
    strip_title: $(p + 'StripTitle').checked,
    italic_system: $(p + 'ItalicSystem').checked,
    align: menus.align ? menus.align.value : 'left',
    scene_style: menus.scene ? menus.scene.value : 'stars',
    first_line_indent_cm: $(p + 'Indent').value,
  };
}

/** Показывает список ошибок по файлам: молчаливых отказов быть не должно. */
function showFailures(tableId, failures){
  const table = $(tableId);
  table.innerHTML = '';
  if(!failures || !failures.length){ table.hidden = true; return; }
  for(const failure of failures){
    const row = document.createElement('div');
    row.className = 'tr';
    const file = document.createElement('span');
    file.className = 'grow';
    file.textContent = failure.file;
    file.title = failure.file;
    const step = document.createElement('span');
    step.className = 'tag';
    step.textContent = failure.step;
    const text = document.createElement('span');
    text.className = 'grow';
    text.textContent = failure.error;
    text.title = failure.error;
    row.append(file, step, text);
    table.append(row);
  }
  table.hidden = false;
}

/* ------------------------------------------------ сворачивание карточек
 *
 * Всё, что не основная работа вкладки, лежит сложенным: настройки
 * оформления, обработка текста, объём глав, предпросмотр. Обычно там
 * ничего не трогают, а глаз они забирают наравне с главным.
 *
 * Карточке достаточно `data-fold`, а её заголовку — класса `foldhead`:
 * свёрнутая от развёрнутой отличается ровно одним классом, и ни один
 * `id` при этом никуда не переезжает.
 */

document.addEventListener('click', event => {
  const head = event.target.closest('.foldhead');
  if(!head) return;
  const card = head.closest('[data-fold]');
  if(card) card.classList.toggle('folded');
});

/** Развернуть карточку и подвести к ней взгляд. */
function unfold(id){
  const card = $(id);
  if(!card) return;
  card.classList.remove('folded');
  card.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

/** Оформление и обработка нужны не всякому формату — прячем лишнее. */
function toggleOptions(p, format){
  $(p + 'Style').hidden = format !== '.docx';
  $(p + 'Prep').hidden = false;
}

/* ------------------------------------------------------------ Разбить */

const spState = {format: '.txt', job: null, menus: {}, scan: null,
                 //: главам поимённо — на сколько частей резать
                 pieces: {}, chosen: new Set(),
                 //: последняя глава, по галочке которой нажимали, — от неё
                 //: считается промежуток при отметке с Shift
                 lastPicked: null,
                 //: для каких путей формат уже подобран по исходнику
                 forPaths: ''};

function spUpdateFinal(){
  const base = $('spBase').value.trim(), name = $('spFolder').value.trim();
  // Имя папки — по желанию. Нет его — главы лягут прямо в выбранную.
  $('spFinal').textContent = base
    ? `Главы лягут в: ${base}${name ? '/' + name : ''}  (${spState.format})` : '';
  toggleOptions('sp', spState.format);
  spDrawSchema();
  // Расширение в предпросмотре — то же, что выбрано кнопкой. Раньше
  // предпросмотр перерисовывался только при чтении с диска, и после
  // смены формата обещал .txt, а на диск ложился .docx.
  spDrawPreview();
}

/** Формат на выходе — как у исходника.
 *
 * Разбивают вордовский файл, чтобы получить вордовские главы; ставить
 * это руками каждый раз — работа на пустом месте. Подбирается один раз
 * на выбранный файл: дальше человек волен выбрать любой другой формат,
 * и своё нажатие важнее нашей догадки.
 *
 * Одна на все вкладки: вопрос «какой формат у исходника» везде один и
 * тот же, и три ответа на него однажды разошлись бы.
 */
function guessFormat(files, rowId, state, onChange){
  const first = (files || [])[0] || '';
  const match = /\.[^./\\]+$/.exec(first);
  const suffix = match ? match[0].toLowerCase() : '';
  if(!suffix || !(FORMATS.writable || []).includes(suffix)) return;
  state.format = suffix;
  buildFormats(rowId, state, onChange);
  onChange();
}

function spGuessFormat(files){
  guessFormat(files, 'spFormats', spState, spUpdateFinal);
}

/** «1 файл .epub → разбить → 5 файлов .docx». */
function spDrawSchema(){
  const data = spState.scan;
  if(!data){ $('spSchema').hidden = true; return; }
  // Число файлов на выходе считает сервер: он же их и пишет. Своё
  // умножение здесь однажды разошлось бы с настоящим делением.
  drawSchema('spSchema',
    {count: data.file_count, formats: extensions(data.files)},
    'разбить',
    {count: data.total, format: spState.format});
}

/** Формат имени файла — тот же набор, что во вкладке «Переименовать». */
function spNameFormat(){
  return {
    number: $('spNum').checked,
    part: $('spPartNum').checked,
    title: $('spTitleOn').checked,
    prefix: $('spPrefix').value,
    separator: spState.menus.sep ? spState.menus.sep.value : ': ',
    part_style: spState.menus.partStyle ? spState.menus.partStyle.value : 'dot',
  };
}

/** Чем делить книгу и с какого номера нумеровать главы.
 *
 *  Оба поля едут во все три запроса вкладки: чтение, проверку объёма и
 *  запись. Разойдись они — предпросмотр показывал бы одну книгу, а на диск
 *  легла бы другая.
 */
function spCut(){
  const way = spState.menus.way ? spState.menus.way.value : '';
  const start = $('spFrom').value.trim();
  return {
    way,
    // Шаблон нужен только делению по заголовку: при делении по разметке
    // он не при чём, и посланный вместе с ней сбивал бы с толку.
    pattern: way ? '' : $('spPattern').value.trim(),
    start,
  };
}

//: Чем поделили — словами, для строки под списком файлов.
const SP_WAY_NAMES = {boxes: 'по рамкам', blank: 'по пустому абзацу'};

/** Читается сразу после выбора — отдельной кнопки «Прочитать» нет. */
async function spScan(){
  const targets = CHOSEN.spList || [];
  if(!targets.length){
    spState.scan = null;
    spState.pieces = {};
    spState.chosen.clear();
    spState.lastPicked = null;
    ['spOpts', 'spPlace', 'spStyle', 'spPrep', 'spPatternCard', 'spSchema',
     'spChaptersCard', 'spPreviewCard'].forEach(id => { $(id).hidden = true; });
    $('spScanned').textContent = 'Файлы читаются сразу после выбора.';
    return;
  }
  showError('');
  // Читаем книгу заново — набор глав может быть другим, и деление,
  // заданное прежним главам по номерам, уехало бы не на те.
  spState.pieces = {};
  spState.chosen.clear();
  // Книга другая — отсчёт промежутка начинается заново: номера тех же
  // глав указывали бы на чужой текст.
  spState.lastPicked = null;
  $('spScanned').innerHTML = '<span class="spin"></span>Читаем…';
  try{
    const data = await call('/api/split/scan', {
      targets,
      ...spCut(),
      pieces: spState.pieces,
      name_format: spNameFormat(),
      seq: $('spSeq').checked,
    });
    spState.scan = data;
    // Выбран другой файл — формат подбирается заново по нему. Тот же
    // файл перечитывают с шаблоном заголовка, и сбрасывать выбранное
    // руками на этом шаге было бы отменой чужого решения.
    const paths = targets.join('|');
    if(paths !== spState.forPaths){
      spState.forPaths = paths;
      spGuessFormat(data.files);
    }
    // Выбрали файл — значит, нужны все главы из него, а не часть.
    for(const chapter of data.chapters || []) spState.chosen.add(chapter.index);
    updateListBar('spList', data.file_count);
    $('spScanned').textContent =
      `Файлов: ${data.file_count}, глав: ${data.found}` +
      (data.total !== data.found ? `, файлов на выходе: ${data.total}` : '') +
      // При «сам определит» человек иначе не узнает, что сработало.
      (SP_WAY_NAMES[data.way] ? ` (поделено ${SP_WAY_NAMES[data.way]})` : '') + '.';
    if(data.unreadable?.length) showError('Не прочитаны: ' + data.unreadable.join('; '));
    $('spOpts').hidden = false;
    $('spPlace').hidden = false;
    // Карточку способа показываем в двух случаях. Способ выбран — он там
    // живёт, и спрятать её значило бы отнять возможность передумать.
    // Из одного файла вышла одна глава — разбиение ничего не разбило, и
    // спросить, чем делить, надо прямо сейчас: молча отдать один файл на
    // выходе значит сделать вид, что операция удалась. Своего вопроса
    // сервер тут не задаёт — книгу с числом в имени («ОРИГ 80-200») он
    // принимает за готовую главу и отвечает без возражений.
    const nothingHappened = data.file_count === 1 && data.found < 2;
    $('spPatternCard').hidden = !(spCut().way || nothingHappened);
    if(nothingHappened && !spCut().way) spSayNothingSplit();
    spDrawChapters();
    spDrawPreview();
    // Имя папки само не подставляется: по умолчанию главы ложатся прямо
    // в выбранную папку, и подставленное имя означало бы обратное.
    spUpdateFinal();
    // Находка есть — предлагаем очистку сами, не дожидаясь кнопки.
    hdOffer('spList');
  }catch(err){
    $('spScanned').textContent = '';
    $('spOpts').hidden = true;
    $('spPlace').hidden = true;
    $('spChaptersCard').hidden = true;
    $('spPreviewCard').hidden = true;
    // Заголовков не нашлось — наугад не режем, просим шаблон. Не нашлось
    // границ по разметке — просим выбрать другой способ; та же карточка.
    if(err.needPattern || err.needWay){
      $('spPatternCard').hidden = false;
      if(err.needPattern && !$('spPattern').value) $('spPattern').value = err.pattern || '';
    }
    showError(err.message);
  }
}
window.spScan = spScan;

//: Галочки глав по номеру главы. Нужны отметке промежутком.
let spBoxes = {};

/** Отмечает или снимает все главы от одной до другой, включая обе.
 *
 *  Первая глава, двести первая с Shift — и двести галочек встают разом.
 *  Направление неважно: вверх и вниз работает одинаково, как в проводнике.
 *
 *  Состояние берём от той главы, по которой нажали: сняли галочку с
 *  двухсотой — снимается весь промежуток. Иначе Shift умел бы только
 *  отмечать, и снять двести галочек было бы по-прежнему нечем.
 */
function spPickRange(from, to, want){
  const first = Math.min(from, to);
  const last = Math.max(from, to);
  for(let index = first; index <= last; index++){
    want ? spState.chosen.add(index) : spState.chosen.delete(index);
    if(spBoxes[index]) spBoxes[index].checked = want;
  }
}

/** Найденные главы: что отмечено и на сколько частей режется. */
function spDrawChapters(){
  const data = spState.scan;
  const table = $('spChapters');
  table.innerHTML = '';
  if(!data || !data.chapters?.length){
    $('spChaptersCard').hidden = true;
    return;
  }

  // Галочки помним поимённо: отметка с Shift меняет разом целый
  // промежуток, а перерисовывать ради этого тысячу строк — заметная
  // задержка на каждое нажатие.
  spBoxes = {};

  for(const chapter of data.chapters){
    const row = document.createElement('div');
    row.className = 'tr';

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = spState.chosen.has(chapter.index);
    spBoxes[chapter.index] = box;
    // Слушаем нажатие, а не изменение: в `change` не приходит Shift —
    // это не событие мыши. Пробел на клавиатуре тоже даёт `click`, так
    // что с клавиатуры галочка работает по-прежнему.
    box.onclick = event => {
      const want = box.checked;
      if(event.shiftKey && spState.lastPicked !== null){
        spPickRange(spState.lastPicked, chapter.index, want);
      }else{
        want ? spState.chosen.add(chapter.index)
             : spState.chosen.delete(chapter.index);
      }
      spState.lastPicked = chapter.index;
      spShowPicked();
    };

    const name = document.createElement('span');
    name.className = 'grow';
    name.textContent = chapter.title || `Глава ${chapter.index}`;
    name.title = name.textContent;

    const size = document.createElement('span');
    size.className = 'num';
    size.textContent = chapter.size.toLocaleString('ru') + ' симв.';

    // Сколько частей — из своего же состояния, а не из ответа: ответ
    // приходит только при чтении с диска, а галочку жмут чаще.
    const count = spState.pieces[String(chapter.index)] || 1;
    row.append(box, name);
    if(count > 1){
      const tag = document.createElement('span');
      tag.className = 'tag warn';
      tag.textContent = `на ${count} ${plural(count, 'часть', 'части', 'частей')}`;
      row.append(tag);
    }
    row.append(size);
    table.append(row);
  }
  $('spChaptersCard').hidden = false;
  spShowPicked();
}

/** Пересобрать имена, не перечитывая книгу с диска. */
async function spRefresh(){
  const data = spState.scan;
  if(!data?.chapters?.length) return;
  try{
    const fresh = await call('/api/split/names', {
      chapters: data.chapters.map(c => ({index: c.index, number: c.number,
                                         title: c.title})),
      pieces: spState.pieces,
      name_format: spNameFormat(),
      seq: $('spSeq').checked,
    });
    data.names = fresh.names || [];
    data.total = data.names.length;
    spDrawChapters();
    spDrawPreview();
    spDrawSchema();
    $('spScanned').textContent =
      `Файлов: ${data.file_count}, глав: ${data.found}` +
      (data.total !== data.found ? `, файлов на выходе: ${data.total}` : '') + '.';
  }catch(err){
    showError(err.message);
  }
}

//: Приставку набирают по букве — дёргать сервер на каждой не нужно.
let spNameTimer = null;
function spRefreshSoon(){
  clearTimeout(spNameTimer);
  spNameTimer = setTimeout(spRefresh, 250);
}

function spShowPicked(){
  const picked = spState.chosen.size;
  $('spPicked').textContent = picked ? `отмечено: ${picked}` : '';
}

/** Что ляжет на диск. Имена приходят с сервера — он же их и пишет. */
function spDrawPreview(){
  const data = spState.scan;
  const table = $('spPreview');
  table.innerHTML = '';
  if(!data || !data.names?.length){
    $('spPreviewCard').hidden = true;
    return;
  }

  for(const name of data.names){
    const row = document.createElement('div');
    row.className = 'tr';
    const text = document.createElement('span');
    text.className = 'grow';
    text.textContent = name + spState.format;
    text.title = text.textContent;
    row.append(text);
    table.append(row);
  }
  $('spPreviewNote').textContent =
    `файлов: ${data.total}` + (data.total !== data.found
      ? ` из ${data.found} ${plural(data.found, 'главы', 'глав', 'глав')}` : '');
  $('spPreviewCard').hidden = false;
}

/** Задаёт отмеченным главам число частей и перечитывает предпросмотр. */
function spApplyParts(count){
  if(!spState.chosen.size){
    showError('Отметьте главы, которые нужно поделить');
    return;
  }
  for(const index of spState.chosen){
    if(count > 1) spState.pieces[String(index)] = count;
    else delete spState.pieces[String(index)];
  }
  // Части без своего номера получают одно имя на всех, и запись
  // расходится с предпросмотром приписками «(2)». Галочка снята по
  // умолчанию нарочно, но делят главы — значит, номер части нужен.
  if(count > 1) $('spPartNum').checked = true;
  spRefresh();
}

function spAskParts(){
  if(!spState.chosen.size){
    showError('Отметьте главы, которые нужно поделить');
    return;
  }
  $('spDialog').hidden = false;
}

function spPickAll(on){
  spState.chosen.clear();
  if(on) for(const chapter of spState.scan?.chapters || []) spState.chosen.add(chapter.index);
  spDrawChapters();
}

/** Спрашивает разрешение, если сервер попросил, и повторяет запрос.
 *
 * Проверку делает сервер, а не страница: «в папке уже что-то лежит» —
 * вопрос о диске, и обойти его, нажав кнопку на вкладке, которую я забыл
 * поправить, быть не должно.
 */
async function askThenCall(url, body){
  try{
    return await call(url, body);
  }catch(err){
    if(!err.needConfirm) throw err;
    if(!confirm(err.message)) return null;
    return await call(url, {...body, confirm: true});
  }
}

async function spStart(){
  showError('');
  $('spStart').disabled = true;
  $('spErrors').hidden = true;
  try{
    const started = await askThenCall('/api/split/start', {
      targets: CHOSEN.spList || [],
      base: $('spBase').value.trim(),
      folder: $('spFolder').value.trim(),
      format: spState.format,
      ...spCut(),
      pieces: spState.pieces,
      name_format: spNameFormat(),
      seq: $('spSeq').checked,
      headings: $('spHeadings').checked,
      encoding: spState.menus.encoding ? spState.menus.encoding.value : 'utf-8',
      style: styleOf('sp', spState.menus),
      prep: prepOf('sp', spState.menus),
    });
    // Пусто — человек отказался сохранять в занятую папку.
    if(!started) return;
    const job = started.job;
    spState.job = job.id;
    ownJob('split', job.id);
    $('spProgress').hidden = false;
    $('spStop').hidden = false;
    $('spSummary').textContent = 'Папка: ' + job.output_dir;

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('spWritten').textContent = p.written || p.done || 0;
        $('spFailed').textContent = p.failed || 0;
        return drawResult(p, 'spFill', 'spStatus', 'spPct');
      },
      job => {
        $('spStop').hidden = true;
        if(job.error){ showError(job.error, $('spSummary')); return; }
        $('spSummary').textContent = 'Папка: ' + (job.report?.output || job.output_dir);
        showFailures('spErrors', job.report?.failures);
      });
  }catch(err){
    showError(err.message);
    if(err.needPattern) $('spPatternCard').hidden = false;
  }finally{
    $('spStart').disabled = false;
  }
}

/* --------------------------------------------------------- Объединить */

const mgState = {format: '.txt', job: null, menus: {}, scan: null,
                 //: для каких путей формат уже подобран по исходнику
                 forPaths: ''};

function mgUpdateFinal(){
  const base = $('mgBase').value.trim(), name = $('mgName').value.trim();
  $('mgFinal').textContent = base && name
    ? `Файл: ${base}/${name}${mgState.format}` : '';
  toggleOptions('mg', mgState.format);
  mgDrawSchema();
}

/** «5 файлов .txt → объединить → 1 файл .epub». */
function mgDrawSchema(){
  const data = mgState.scan;
  if(!data){ $('mgSchema').hidden = true; return; }
  drawSchema('mgSchema',
    {count: data.file_count, formats: extensions(data.files)},
    'объединить',
    {count: 1, format: mgState.format});
}

async function mgScan(){
  const targets = CHOSEN.mgList || [];
  if(!targets.length){
    mgState.scan = null;
    ['mgOpts', 'mgPlace', 'mgStyle', 'mgPrep', 'mgSchema']
      .forEach(id => { $(id).hidden = true; });
    $('mgScanned').textContent = 'Файлы читаются сразу после выбора.';
    return;
  }
  showError('');
  $('mgScanned').innerHTML = '<span class="spin"></span>Читаем…';
  try{
    const data = await call('/api/merge/scan', {
      targets,
      order: mgState.menus.order ? mgState.menus.order.value : 'number',
    });
    mgState.scan = data;
    // Формат на выходе — как у исходника, один раз на выбранное. Тот же
    // порядок, что в «Разбить»: своё нажатие важнее нашей догадки.
    const paths = targets.join('|');
    if(paths !== mgState.forPaths){
      mgState.forPaths = paths;
      guessFormat(data.files, 'mgFormats', mgState, mgUpdateFinal);
    }
    updateListBar('mgList', data.file_count);
    // 4.2: разбор по форматам. Порядок глав от формата не зависит —
    // главы сортируются по номеру, чем бы ни был файл.
    const kinds = formatBreakdown(data.files);
    $('mgScanned').textContent =
      `Выбрано ${data.file_count} ${plural(data.file_count, 'файл', 'файла', 'файлов')}`
      + (kinds ? `: ${kinds}` : '')
      + `. Глав: ${data.total}. `
      + (data.titles.length ? 'Первые: ' + data.titles.join(' · ') : '');
    if(data.unreadable?.length){
      showError('Не прочитаны: ' + data.unreadable.join('; '), $('mgScanned'));
    }
    // Пропущенное по формату — предупреждение, а не отказ: рядом с
    // главами часто лежит что-то постороннее, и это в порядке вещей.
    $('mgSkipped').hidden = !data.skipped?.length;
    if(data.skipped?.length){
      const shown = data.skipped.slice(0, 8).join(', ');
      $('mgSkipped').textContent =
        `Пропущено по формату: ${data.skipped.length} `
        + `(${shown}${data.skipped.length > 8 ? ' и другие' : ''}).`;
    }
    $('mgOpts').hidden = false;
    $('mgPlace').hidden = false;
    if(!$('mgName').value) $('mgName').value = 'Книга';
    mgUpdateFinal();
    hdOffer('mgList');
  }catch(err){
    showError(err.message);
    $('mgOpts').hidden = true;
    $('mgPlace').hidden = true;
    $('mgScanned').textContent = '';
  }
}
window.mgScan = mgScan;

async function mgStart(){
  showError('');
  $('mgStart').disabled = true;
  $('mgErrors').hidden = true;
  try{
    const {job} = await call('/api/merge/start', {
      targets: CHOSEN.mgList || [],
      base: $('mgBase').value.trim(),
      name: $('mgName').value.trim(),
      format: mgState.format,
      order: mgState.menus.order ? mgState.menus.order.value : 'number',
      encoding: mgState.menus.encoding ? mgState.menus.encoding.value : 'utf-8',
      separator: mgState.menus.separator ? mgState.menus.separator.value : 'blank',
      custom_separator: $('mgCustom').value,
      headings: $('mgHeadings').checked,
      style: styleOf('mg', mgState.menus),
      prep: prepOf('mg', mgState.menus),
    });
    mgState.job = job.id;
    ownJob('merge', job.id);
    $('mgProgress').hidden = false;
    $('mgStop').hidden = false;
    $('mgSummary').textContent = 'Файл: ' + job.output_dir;

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('mgWritten').textContent = p.written || p.done || 0;
        $('mgFailed').textContent = p.failed || 0;
        return drawResult(p, 'mgFill', 'mgStatus', 'mgPct');
      },
      job => {
        $('mgStop').hidden = true;
        if(job.error){ showError(job.error, $('mgSummary')); return; }
        $('mgSummary').textContent = 'Файл: ' + (job.report?.output || job.output_dir);
        showFailures('mgErrors', job.report?.failures);
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('mgStart').disabled = false;
  }
}

/* -------------------------------------------------------- Конвертация */

/* Третья из семьи. «Разбить» делает из одного много, «Объединить» — из
 * многого одно, здесь число не меняется вовсе: меняется формат. Раньше
 * ради этого запускали «Объединить» по разу на главу.
 */

const cvState = {format: '.docx', job: null, menus: {}, scan: null};

function cvUpdateFinal(){
  const base = $('cvBase').value.trim();
  const name = $('cvFolder').value.trim() || 'Конвертация';
  $('cvFinal').textContent = base
    ? `Файлы лягут в: ${base}/${name}  (${cvState.format})` : '';
  toggleOptions('cv', cvState.format);
  cvDrawSchema();
}

/** «5 файлов .txt → перегнать → 5 файлов .docx»: число одно и то же. */
function cvDrawSchema(){
  const data = cvState.scan;
  if(!data){ $('cvSchema').hidden = true; return; }
  drawSchema('cvSchema',
    {count: data.file_count, formats: extensions(data.files)},
    'перегнать',
    {count: data.file_count, format: cvState.format});
}

/** Пересчёт после выбора. Содержимое не читается — только имена файлов. */
async function cvScan(){
  const targets = CHOSEN.cvList || [];
  if(!targets.length){
    cvState.scan = null;
    ['cvOpts', 'cvPlace', 'cvStyle', 'cvPrep', 'cvSchema', 'cvSkipped']
      .forEach(id => { $(id).hidden = true; });
    $('cvScanned').textContent = 'Каждый файл превращается в свой: главы '
      + 'внутри не режутся и не склеиваются.';
    return;
  }
  showError('');
  try{
    const data = await call('/api/convert/scan', {targets});
    cvState.scan = data;
    updateListBar('cvList', data.file_count);
    const kinds = formatBreakdown(data.files);
    $('cvScanned').textContent =
      `Выбрано ${data.file_count} `
      + `${plural(data.file_count, 'файл', 'файла', 'файлов')}`
      + (kinds ? `: ${kinds}` : '')
      + `. Столько же и получится.`;
    $('cvSkipped').hidden = !data.skipped?.length;
    if(data.skipped?.length){
      const shown = data.skipped.slice(0, 8).join(', ');
      $('cvSkipped').textContent =
        `Пропущено по формату: ${data.skipped.length} `
        + `(${shown}${data.skipped.length > 8 ? ' и другие' : ''}).`;
    }
    $('cvOpts').hidden = false;
    $('cvPlace').hidden = false;
    cvUpdateFinal();
  }catch(err){
    showError(err.message, $('cvScanned'));
    $('cvOpts').hidden = true;
    $('cvPlace').hidden = true;
  }
}
window.cvScan = cvScan;

async function cvStart(){
  showError('');
  $('cvStart').disabled = true;
  $('cvErrors').hidden = true;
  try{
    const {job} = await call('/api/convert/start', {
      targets: CHOSEN.cvList || [],
      base: $('cvBase').value.trim(),
      folder: $('cvFolder').value.trim(),
      format: cvState.format,
      encoding: cvState.menus.encoding ? cvState.menus.encoding.value : 'utf-8',
      headings: $('cvHeadings').checked,
      style: styleOf('cv', cvState.menus),
      prep: prepOf('cv', cvState.menus),
    });
    cvState.job = job.id;
    ownJob('convert', job.id);
    $('cvProgress').hidden = false;
    $('cvStop').hidden = false;
    $('cvSummary').textContent = 'Папка: ' + job.output_dir;

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('cvWritten').textContent = p.written || p.done || 0;
        $('cvFailed').textContent = p.failed || 0;
        return drawResult(p, 'cvFill', 'cvStatus', 'cvPct');
      },
      job => {
        $('cvStop').hidden = true;
        if(job.error){ showError(job.error, $('cvSummary')); return; }
        $('cvSummary').textContent =
          'Папка: ' + (job.report?.output || job.output_dir);
        // Перегон в тот же формат не ошибка — но человек мог выбрать
        // формат по ошибке, и молчать об этом не стоит.
        // `extra` в отчёте раскладывается по верхнему уровню, отдельного
        // ключа `extra` в ответе нет.
        const same = job.report?.same_format;
        if(same){
          $('cvSummary').textContent += ` · ${same} `
            + `${plural(same, 'файл', 'файла', 'файлов')} уже были в `
            + `${cvState.format}`;
        }
        showFailures('cvErrors', job.report?.failures);
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('cvStart').disabled = false;
  }
}

/* ==================== Форматировать ====================
 *
 * Книга уезжает на сайт одним .md, где главы размечены строками
 * `# [Название :|: Порядок :|: Платность :|: Том]`. Работы две: собрать
 * такой файл из папки глав и переписать заголовки в уже готовом, когда
 * переводчик оставил их английскими.
 *
 * Во второй работе правится только название. Номер главы модели не
 * отдаётся вовсе — его подставляем сами: полторы тысячи заголовков, и
 * поправь она номер хоть в одном, книга на сайте съедет.
 */
const fmState = {menus: {}, files: null, book: null, job: null};

function fmStylePayload(){
  return {
    prefix: $('fmPrefix').value.trim(),
    separator: fmState.menus.sep ? fmState.menus.sep.value : ' — ',
    paid: fmState.menus.paid ? fmState.menus.paid.value : '',
    volume: $('fmVolume').value.trim(),
    first: Number($('fmFirst').value) || 0,
    parts: Number($('fmParts').value) || 1,
  };
}

/** Что делать с названием, собирая книгу из файлов: оставить или убрать.
 *
 *  Перевода здесь нет нарочно: он живёт во второй карточке, вместе с
 *  ключами, моделью и кэшем.
 */
function fmCollectNames(){
  return fmState.menus.collectNames ? fmState.menus.collectNames.value : 'keep';
}

/** Что делать с названием: перевести, оставить, убрать. */
function fmNamesWay(){
  return fmState.menus.names ? fmState.menus.names.value : 'translate';
}

/** Выбор модели нужен только переводу — остальным способам к ней не
 *  ходить вовсе, ни ключей, ни сети. Показывать его всегда значило бы
 *  требовать ключ там, где он ни при чём. */
function fmShowWay(){
  const way = fmNamesWay();
  $('fmModelRow').hidden = way !== 'translate';
  $('fmRetitle').textContent = way === 'translate'
    ? 'Перевести заголовки' : 'Переписать заголовки';
}

/** Показать, как будет выглядеть заголовок.
 *
 *  Правила ровно те же, что у `make_head` на сервере: пустое поле с
 *  конца не пишем вовсе, а пропуск в середине оставляем — том без
 *  платности перед ним съехал бы на чужое поле. Платность «как в форме»
 *  — это пробел, и отдельным полем она не нужна: сайт и без неё возьмёт
 *  значение из формы.
 */
function fmShowSample(){
  const s = fmStylePayload();
  const mark = s.parts > 1 ? '1171.1' : '1171';
  const order = s.first ? String(s.first) : '';
  const paid = (s.paid || '').trim();

  let rest = [];
  if(s.volume.trim()) rest = [order, paid || ' ', s.volume];
  else if(paid) rest = [order, paid];
  else if(order) rest = [order];

  const tail = rest.map(x => ` :|: ${x}`).join('');
  // Название показываем только если оно и будет: иначе образец обещает
  // одно, а в книгу ложится другое.
  const named = fmCollectNames() === 'keep' ? `${s.separator}Название` : '';
  $('fmSample').textContent =
    `Заголовок выйдет такой:  # [${s.prefix} ${mark}${named}${tail}]`;
}

async function fmScan(){
  const targets = CHOSEN.fmList || [];
  $('fmPreview').hidden = true;
  if(!targets.length){
    fmState.files = null;
    $('fmScanned').textContent = 'Файлы читаются сразу после выбора.';
    $('fmSkipped').hidden = true;
    return;
  }
  showError('');
  try{
    const data = await call('/api/format/files',
                            {targets, ...fmStylePayload()});
    fmState.files = data;
    updateListBar('fmList', data.files);
    $('fmScanned').textContent =
      `Глав найдено: ${data.total} в ${data.files} `
      + `${plural(data.files, 'файле', 'файлах', 'файлах')}.`;
    $('fmSkipped').hidden = !data.skipped?.length;
    if(data.skipped?.length){
      const shown = data.skipped.slice(0, 8).join(', ');
      $('fmSkipped').textContent =
        `Пропущено по формату: ${data.skipped.length} (${shown}`
        + `${data.skipped.length > 8 ? ' и другие' : ''}).`;
    }
    fmShowLines('fmPreview', data.sample);
  }catch(err){
    showError(err.message, $('fmScanned'));
  }
}
window.fmScan = fmScan;

/** Что не так с нумерацией книги.
 *
 *  Загрузчик сортирует главы по полю «Порядок», а человек читает номер в
 *  названии — расходятся они молча, и заметить это можно только до
 *  отправки на сайт.
 */
function fmShowLook(look){
  const stats = $('fmLook');
  const rows = $('fmLookRows');
  stats.replaceChildren();
  rows.replaceChildren();
  stats.hidden = rows.hidden = !look;
  if(!look) return;

  const range = look.first !== null && look.last !== null
    ? `${look.first}–${look.last}` : '—';
  const counts = [
    ['глав', look.total],
    ['с номером', look.numbered],
    ['номера', range],
  ];
  for(const [name, value] of counts){
    const cell = document.createElement('span');
    const bold = document.createElement('b');
    bold.textContent = String(value);
    cell.append(document.createTextNode(name + ' '), bold);
    stats.append(cell);
  }

  const verdict = document.createElement('span');
  verdict.className = look.ok ? 'fm-good' : 'fm-bad';
  verdict.textContent = look.ok
    ? 'с нумерацией всё в порядке'
    : 'с нумерацией непорядок';
  stats.append(verdict);

  // Каждая находка своей строкой: чинить их всё равно по одной, а
  // «непорядок» без подробностей не говорит, что именно чинить.
  const found = [
    ['Пропущены номера', look.gaps, look.gaps_count,
     'этих глав в книге нет — похоже, потерялись по дороге'],
    // Книгу, поделённую надвое, отдают загрузчику парами: «Глава 295»
    // дважды подряд. Пропавшая глава дыры в номерах тогда не оставляет —
    // номер остаётся, просто глав под ним становится меньше.
    [`Глав под номером меньше ${look.per_number}`, look.thin, look.thin_count,
     'у остальных номеров глав больше — похоже, эти потерялись. Какой '
     + 'именно части не хватает, скажет «Каких глав нет в папке» во '
     + 'вкладке «Проверка»: там видно имена файлов'],
    // Повтор самой главы, а не её номера: номер у двух глав совпадает и
    // по делу — у главы бывает две-три части, — а вот дословно совпавший
    // текст значит ровно одно: глава попала в книгу дважды.
    ['Глава повторяется дословно', look.doubles, look.doubles_count,
     'один и тот же текст под этими номерами — на сайт уедет дважды'],
    ['Номер идёт назад', look.backwards, look.backwards_count,
     'порядок глав собьётся'],
    ['Повтор в поле «Порядок»', look.order_doubles, look.order_doubles_count,
     'сайт сортирует именно по нему'],
    ['Без номера в названии', look.nameless, look.nameless_count,
     'сайт назначит порядок сам'],
  ];
  for(const [name, items, count, why] of found){
    if(!count) continue;
    const row = document.createElement('div');
    row.className = 'tr';

    const head = document.createElement('span');
    head.style.flex = '0 0 210px';
    head.textContent = `${name}: ${count}`;
    const body = document.createElement('code');
    body.style.flex = '1';
    body.textContent = (items || []).join(', ')
      + (count > (items || []).length ? ' и другие' : '');
    body.title = why;
    row.append(head, body);
    rows.append(row);
  }
  rows.hidden = !rows.children.length;
}

/** Готовые строки заголовков — как есть, без разбора на поля. */
function fmShowLines(boxId, lines){
  const box = $(boxId);
  box.innerHTML = '';
  box.hidden = !(lines || []).length;
  for(const line of lines || []){
    const row = document.createElement('div');
    row.className = 'tr';
    const cell = document.createElement('code');
    cell.textContent = line;
    cell.style.fontSize = '12px';
    cell.style.wordBreak = 'break-all';
    row.append(cell);
    box.append(row);
  }
}

async function fmBookScan(){
  const targets = CHOSEN.fmBookList || [];
  $('fmBookPreview').hidden = true;
  if(!targets.length){
    fmState.book = null;
    $('fmBookNote').textContent = '';
    fmShowLook(null);
    return;
  }
  showError('');
  try{
    const data = await call('/api/format/book', {targets});
    fmState.book = data;
    $('fmBookNote').textContent =
      `Глав в книге: ${data.total}. `
      + (data.untranslated
        ? `Заголовков не по-русски: ${data.untranslated}.`
        : 'Все заголовки уже на русском — переводить нечего.');
    fmShowLook(data.look);
    fmShowLines('fmBookPreview', data.sample);
    if(!$('fmOutName').value.trim()){
      $('fmOutName').value = 'книга-ru';
    }
  }catch(err){
    showError(err.message, $('fmBookNote'));
    fmState.book = null;
    // Прежний отчёт относится к прежнему файлу: оставить его значило бы
    // показывать разбор книги, которую не прочитали.
    fmShowLook(null);
  }
}
window.fmBookScan = fmBookScan;

/** Сколько ключей живо и сколько исчерпано — рядом с прогрессом.
 *
 *  Одним числом их не покажешь: «десять ключей» ничего не говорит, если
 *  девять из них уже отдали свою квоту.
 */
function fmShowKeys(keys){
  const box = $('fmKeys');
  if(!keys || !keys.total){ box.hidden = true; return; }
  box.hidden = false;
  box.replaceChildren();

  const live = document.createElement('b');
  live.className = 'live';
  live.textContent = String(keys.active || 0);
  const spent = document.createElement('b');
  spent.className = 'spent';
  spent.textContent = String(keys.exhausted || 0);

  box.append(document.createTextNode('ключи '), live,
             document.createTextNode(' / '), spent);
  box.title = `Ключей в работе: ${keys.active || 0}, `
    + `исчерпано: ${keys.exhausted || 0}, всего: ${keys.total}`;
}

/** Прогресс — под ту карточку, в которой нажали кнопку.
 *
 * Карточка прогресса одна на всю вкладку, и стояла она последней, ниже
 * «Мусора в главах» и «Объёма глав». Работ на вкладке две, и запуск
 * любой из них уводил ответ за край экрана: нажал наверху — ищи внизу.
 *
 * Переносим саму карточку, а не заводим вторую: у прогресса свои
 * счётчики, кнопка «Остановить» и журнал, и держать этому второй
 * экземпляр значило бы однажды чинить их в двух местах.
 */
function fmPlaceProgress(button){
  const card = button && button.closest('.card');
  const box = $('fmProgress');
  if(card && card.nextElementSibling !== box) card.after(box);
}

/** Общее для обеих работ: показать прогресс и дождаться конца.
 *
 * `near` — кнопка, которой работу запустили: прогресс встаёт под её
 * карточкой.
 */
function fmWatch(job, done, withLog, near){
  fmState.job = job.id;
  ownJob('format', job.id);
  fmPlaceProgress(near);
  $('fmProgress').hidden = false;
  $('fmStop').hidden = false;
  $('fmErrors').hidden = true;
  $('fmKeys').hidden = true;
  $('fmSummary').textContent = 'Файл: ' + job.output_dir;
  // Строку состояния перерисовываем сразу по новой задаче: до первого
  // опроса на экране висело «Готово» от прошлой работы, и запуск
  // выглядел так, будто уже всё закончилось.
  drawResult(job.progress || {}, 'fmFill', 'fmStatus', 'fmPct');

  // Журнал заводим только там, где он есть: у сборки книги запросов к
  // модели нет вовсе, и пустая раскрывашка обещала бы то, чего нет.
  $('fmLogBox').hidden = true;
  const watcher = withLog
    ? logWatch(job.id, {box: 'fmLog', wrap: 'fmLogBox', save: 'fmLogSave'})
    : null;

  pollJob(job.id,
    job => {
      const p = job.progress || {};
      $('fmWritten').textContent = p.written || p.done || 0;
      $('fmFailed').textContent = p.failed || 0;
      fmShowKeys(p.keys);
      return drawResult(p, 'fmFill', 'fmStatus', 'fmPct');
    },
    job => {
      $('fmStop').hidden = true;
      if(watcher) watcher.stop();
      fmShowKeys(job.report?.keys || job.progress?.keys);
      if(job.error){ showError(job.error, $('fmSummary')); return; }
      $('fmSummary').textContent =
        'Файл: ' + (job.report?.output || job.output_dir);
      if(done) done(job);
      showFailures('fmErrors', job.report?.failures);
    });
}

async function fmCollect(){
  showError('');
  $('fmCollect').disabled = true;
  try{
    const {job} = await call('/api/format/collect', {
      targets: CHOSEN.fmList || [],
      base: $('fmBase').value.trim(),
      name: $('fmName').value.trim(),
      ...fmStylePayload(),
      // В `fmStylePayload` этому не место: он едет и в запросы второй
      // карточки, а там под именем `names` лежит свой, другой выбор —
      // к нему добавлен перевод. Положи мы наш туда, он поехал бы и
      // туда, молча затерев тот.
      names: fmCollectNames(),
    });
    fmWatch(job, job => {
      const total = job.report?.written || 0;
      $('fmSummary').textContent +=
        ` · глав в книге: ${total}`;
    }, false, $('fmCollect'));
  }catch(err){ showError(err.message, $('fmCollect')); }
  finally{ $('fmCollect').disabled = false; }
}

/** «До и после» — каким станет каждый заголовок.
 *
 * К модели не ходит ни разу: «оставить» и «убрать» считаются точно, а
 * для перевода показывается то, что уже есть в словаре имён и в кэше.
 * Остальное честно помечено «переведётся» — и сразу видно, за сколько
 * строк придётся платить.
 */
async function fmBefore(){
  showError('');
  const button = $('fmBefore');
  button.disabled = true;
  $('fmBeforeNote').innerHTML = '<span class="spin"></span>Считаем…';
  try{
    const got = await call('/api/format/retitle/preview', {
      targets: CHOSEN.fmBookList || [],
      names: fmNamesWay(),
      renumber: Number($('fmRenumber').value) || 0,
      tidy: $('fmTidy').checked,
      mark_parts: $('fmPartMarks').checked,
      ...fmStylePayload(),
    });

    const table = $('fmBeforeRows');
    table.innerHTML = '';
    for(const row of got.rows || []){
      const line = document.createElement('div');
      line.className = 'tr';
      const was = document.createElement('span');
      was.className = 'grow';
      was.textContent = row.before;
      was.title = row.before;
      const now = document.createElement('span');
      now.className = 'grow';
      now.textContent = row.after;
      now.title = row.after;
      line.append(was, now);
      if(row.later){
        const tag = document.createElement('span');
        tag.className = 'tag warn';
        tag.textContent = 'переведётся';
        line.append(tag);
      }
      table.append(line);
    }
    if(got.more){
      const rest = document.createElement('div');
      rest.className = 'tr';
      const text = document.createElement('span');
      text.className = 'grow';
      text.textContent = `…и ещё ${got.more}`;
      rest.append(text);
      table.append(rest);
    }
    table.hidden = !(got.rows || []).length;

    $('fmBeforeNote').textContent = got.waiting
      ? `Глав: ${got.total}. Готово без запроса: ${got.ready}, `
        + `переведётся: ${got.waiting}.`
      : `Глав: ${got.total}. Всё считается без запроса к модели.`;
  }catch(err){
    showError(err.message, $('fmBefore'));
    $('fmBeforeNote').textContent = '';
  }finally{
    button.disabled = false;
  }
}

async function fmRetitle(){
  showError('');
  $('fmRetitle').disabled = true;
  try{
    const {job} = await call('/api/format/retitle', {
      targets: CHOSEN.fmBookList || [],
      base: $('fmOutBase').value.trim(),
      name: $('fmOutName').value.trim(),
      names: fmNamesWay(),
      renumber: Number($('fmRenumber').value) || 0,
      tidy: $('fmTidy').checked,
      mark_parts: $('fmPartMarks').checked,
      model: fmState.menus.model ? fmState.menus.model.value : '',
      force: $('fmForce').checked,
      ...fmStylePayload(),
    });
    fmWatch(job, job => {
      // журнал нужен именно здесь: только перевод ходит к модели
      const r = job.report || {};
      $('fmSummary').textContent +=
        ` · переведено ${r.translated || 0}, из кэша ${r.cached || 0}`
        + (r.broken ? `, осталось как было ${r.broken}` : '');
    }, true, $('fmRetitle'));
  }catch(err){ showError(err.message, $('fmRetitle')); }
  finally{ $('fmRetitle').disabled = false; }
}

/* ------------------------------------------------------------ привязка */

for(const [p, state, update, scan] of [
  ['sp', spState, spUpdateFinal, spScan],
  ['mg', mgState, mgUpdateFinal, mgScan],
  ['cv', cvState, cvUpdateFinal, cvScan],
]){
  state.menus.font = makeDropdown($(p + 'Font'), value => {
    // «Другой…» открывает поле для ручного ввода.
    $(p + 'FontOther').hidden = value !== '__other__';
  });
  state.menus.align = makeDropdown($(p + 'Align'));
  state.menus.scene = makeDropdown($(p + 'Scene'));
  state.menus.encoding = makeDropdown($(p + 'Encoding'));
  $(p + 'List').dataset.onchange = p + 'Scan';
  $(p + 'Stop').onclick = () => stopJob(state.job);
  $(p + 'Start').onclick = {sp: spStart, mg: mgStart, cv: cvStart}[p];
  $(p + 'Base').addEventListener('input', update);
}

/* ------------------------------------------------------- объём глав
 *
 * Один и тот же вопрос на трёх вкладках: какая глава выделяется, малая
 * или большая. Считает его сервер (`ops/stats`), а рисуется он здесь
 * одним кодом на все три — иначе объём главы в одной вкладке однажды
 * разошёлся бы с ним же в соседней.
 */

async function volumeLook(prefix, url, body){
  showError('');
  const button = $(prefix + 'VolLook');
  button.disabled = true;
  $(prefix + 'VolNote').innerHTML = '<span class="spin"></span>Считаем…';
  try{
    volumeShow(prefix, await call(url, body));
  }catch(err){
    showError(err.message);
    $(prefix + 'VolNote').textContent = '';
  }finally{
    button.disabled = false;
  }
}

function volumeShow(prefix, data){
  const table = $(prefix + 'VolTable');
  table.innerHTML = '';
  const out = data.standout || {};

  if(!data.chapters){
    $(prefix + 'VolNote').textContent = 'Глав не нашлось.';
    table.hidden = true;
    return;
  }
  if(!out.enough){
    // Порог живёт на сервере, и причина молчания приходит оттуда же.
    $(prefix + 'VolNote').textContent =
      `Глав: ${data.chapters}. Их слишком мало, чтобы говорить, какая ` +
      'выделяется: в короткой книге любая отличается от любой вдвое.';
    table.hidden = true;
    return;
  }

  $(prefix + 'VolNote').textContent =
    `Глав: ${data.chapters}, обычная около ${out.middle.toLocaleString('ru')} ` +
    `знаков. Короче обычного: ${out.small}, длиннее: ${out.big}.` +
    (out.total ? '' : ' Все главы ровные.');

  for(const row of out.chapters || []){
    const line = document.createElement('div');
    line.className = 'tr';

    const name = document.createElement('span');
    name.className = 'grow';
    name.textContent = row.title || row.label;
    name.title = row.source || name.textContent;

    const tag = document.createElement('span');
    tag.className = 'tag warn';
    tag.textContent = row.mark_name;

    const size = document.createElement('span');
    size.className = 'num';
    // «В 4 раза» отвечает на «насколько», а голые знаки — нет.
    size.textContent = `${row.characters.toLocaleString('ru')} симв. · ×${row.times}`;

    line.append(name, tag, size);
    table.append(line);
  }
  if(out.more){
    const line = document.createElement('div');
    line.className = 'tr';
    const rest = document.createElement('span');
    rest.className = 'grow';
    rest.textContent = `…и ещё ${out.more}`;
    line.append(rest);
    table.append(line);
  }
  table.hidden = !(out.chapters || []).length;
}

// На этой вкладке книга ещё не разбита: главы у неё внутри файла, а не
// по файлам. Общая проверка объёма насчитала бы «глав: 1».
$('spVolLook').onclick = () =>
  volumeLook('sp', '/api/split/volume', {targets: CHOSEN.spList || [],
                                         ...spCut()});
$('rnVolLook').onclick = () =>
  volumeLook('rn', '/api/stats', {targets: [$('rnIn').value.trim()]});
$('fmVolLook').onclick = () =>
  volumeLook('fm', '/api/format/volume', {targets: CHOSEN.fmBookList || []});

$('spFolder').addEventListener('input', spUpdateFinal);
$('spRescan').onclick = () => spScan();
$('spPattern').addEventListener('keydown', e => { if(e.key === 'Enter') spScan(); });

// Способ деления и начало нумерации меняют сам набор глав, а не только их
// имена, — поэтому книгу перечитываем, а не пересобираем предпросмотр.
// Номер слушаем по `change`, а не по `input`: иначе книга читалась бы на
// каждую набранную цифру.
spState.menus.way = makeDropdown($('spWay'), () => { spShowWay(); spScan(); });
$('spFrom').addEventListener('change', () => spScan());

/** Говорит, что делить нечем, прямо в карточке выбора способа.
 *
 *  Пишем в примечание, а не в общую полосу ошибок: это не поломка, а
 *  вопрос — и ответ на него в этой же карточке.
 */
function spSayNothingSplit(){
  const note = $('spWayNote');
  note.hidden = false;
  note.textContent = 'Книга прочиталась одной главой — делить её нечем. '
    + 'Заголовков вида «Глава 12» в ней нет. Если книгу собирали '
    + 'копированием со страницы сайта в Word, выберите деление по разметке.';
}

/** Показывает то, что нужно выбранному способу деления. */
function spShowWay(){
  const way = spState.menus.way ? spState.menus.way.value : '';
  $('spWayHead').hidden = !!way;
  const note = $('spWayNote');
  note.hidden = !way;
  note.textContent = SP_WAY_HINTS[way] || '';
}

//: Что означает способ — словами, под выбором.
const SP_WAY_HINTS = {
  auto: 'Сначала пробуем рамки, потом пустой абзац. Чем поделили — напишем '
      + 'в строке под списком файлов.',
  boxes: 'Рамка вокруг главы: так Word переносит блок с рамкой со страницы '
       + 'сайта. Работает только с .docx.',
  blank: 'Каждый пустой абзац начинает новую главу. Работает только с .docx.',
};

spShowWay();

// Формат имени: любая правка перечитывает предпросмотр. Имена считает
// сервер, поэтому «показать» и «записать» здесь одно и то же действие.
spState.menus.sep = makeDropdown($('spSep'), () => spRefresh());
spState.menus.partStyle = makeDropdown($('spPartStyle'), () => spRefresh());
const spPartsMenu = makeDropdown($('spPartsPick'));
for(const id of ['spNum', 'spPartNum', 'spTitleOn', 'spSeq']){
  $(id).addEventListener('change', () => spRefresh());
}
$('spPrefix').addEventListener('input', spRefreshSoon);

// «Разделить» — не отдельное действие, а разворот того, чем делят.
// Записывает всё равно «Разбить»: два способа сохранить одно и то же
// сбивали бы с толку сильнее, чем спрятанные кнопки.
$('spDivide').onclick = () => unfold('spChaptersCard');

$('spAll').onclick = () => spPickAll(true);
$('spNone').onclick = () => spPickAll(false);
$('spHalve').onclick = () => spApplyParts(2);
$('spMany').onclick = spAskParts;
$('spWhole').onclick = () => spApplyParts(1);
$('spPartsOk').onclick = () => {
  $('spDialog').hidden = true;
  spApplyParts(parseInt(spPartsMenu.value, 10));
};
$('spPartsCancel').onclick = () => { $('spDialog').hidden = true; };

$('mgName').addEventListener('input', mgUpdateFinal);
mgState.menus.order = makeDropdown($('mgOrder'), () => mgScan());
mgState.menus.separator = makeDropdown($('mgSeparator'), value => {
  // «Свой вариант» открывает поле для ручного ввода.
  $('mgCustom').hidden = value !== 'custom';
});

$('cvFolder').addEventListener('input', cvUpdateFinal);

// Списки форматов строятся по ответу сервера, а не по своему перечню.
function buildAllFormats(){
  buildFormats('spFormats', spState, spUpdateFinal);
  buildFormats('mgFormats', mgState, mgUpdateFinal);
  buildFormats('cvFormats', cvState, cvUpdateFinal);
  buildFormats('rnFormats', rnState, () => {});
  writeFormatCaptions();
}

/** Подписи «какие файлы принимаются» (4.1 ТЗ).
 *
 * Перечень расширений, записанный в разметке руками, устаревает молча:
 * форматов стало восемь, а подпись обещала четыре. Берём его из того же
 * списка, по которому работает и сам разбор.
 */
function writeFormatCaptions(){
  for(const node of document.querySelectorAll('[data-formats]')){
    const list = FORMATS[node.dataset.formats] || [];
    node.textContent = list.length ? ' — ' + list.join(', ') : '';
  }
}

call('/api/formats').then(data => {
  FORMATS = data;
  buildAllFormats();
}).catch(buildAllFormats);

spUpdateFinal();
mgUpdateFinal();



/* ===================== Очистка мусорной шапки =====================
 *
 * Один блок на три вкладки: «Разбить», «Объединить», «Переименовать».
 * Жёстких правил нет — сервер считает повторы и присылает находки, а
 * решает человек галочками.
 */

let hdSource = null, hdFindings = [], hdChosen = new Set(), hdJob = null;

//: Находки внутри файла и отмеченные из них. Ключ — «вид·текст»: одна и
//: та же строка бывает и повтором, и соседом заголовка.
let hdInside = [], hdInsideChosen = new Set(), hdPeekLines = [];

/** Ключ правила: вид и текст. Текста у сдвоенного заголовка нет. */
function hdKey(rule){
  return `${rule.kind} :: ${rule.text || ''}`;
}

/** Пути, с которыми работает вызвавшая вкладка. */
function hdTargets(){
  if(!hdSource) return [];
  // «Переименовать» держит путь в поле, остальные — в списке выбранного.
  const field = document.getElementById(hdSource);
  if(field && field.tagName === 'INPUT'){
    const value = field.value.trim();
    return value ? [value] : [];
  }
  return CHOSEN[hdSource] || [];
}

function hdRender(){
  const list = $('hdList');
  list.innerHTML = '';
  for(const finding of hdFindings){
    const row = document.createElement('div');
    row.className = 'tr';

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = hdChosen.has(finding.text);
    box.onchange = () => {
      box.checked ? hdChosen.add(finding.text) : hdChosen.delete(finding.text);
      hdUpdate();
    };

    const text = document.createElement('span');
    text.className = 'grow';
    // У дубля названия своей строки нет: она у каждого файла своя.
    text.textContent = finding.kind === 'title'
      ? 'название главы, продублированное в тексте' : finding.text;
    text.title = text.textContent;

    // Клик по фрагменту открывает файл, где он встречается: посмотреть,
    // о чём речь, надо до удаления, а не после.
    const files = finding.files || [];
    if(files.length){
      text.style.cursor = 'pointer';
      text.title = `Открыть ${files[0]}`
        + (files.length > 1 ? `\nВстречается в ${finding.count} файлах` : '');
      text.onclick = () => call('/api/open', {path: files[0]})
        .catch(err => showError(err.message));
    }

    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = `${finding.count} из ${finding.total}`;
    tag.title = files.length > 1
      ? `Встречается в ${finding.count} файлах` : '';

    row.append(box, text, tag);
    list.append(row);
    // 4.3: под находкой — сам фрагмент. У дубля названия своей строки
    // нет, и раньше на его месте не показывалось ничего.
    list.append(hdExample(finding));
  }
  hdUpdate();
}

/** Кладёт текст в буфер обмена. Возвращает, получилось ли.
 *
 * http://127.0.0.1 браузер защищённым не считает, а программа живёт
 * именно там — поэтому запасной путь через скрытое поле обязателен.
 */
async function copyText(text){
  try{
    if(navigator.clipboard && window.isSecureContext){
      await navigator.clipboard.writeText(text);
      return true;
    }
    const field = document.createElement('textarea');
    field.value = text;
    field.style.position = 'fixed';
    field.style.opacity = '0';
    document.body.append(field);
    field.select();
    const done = document.execCommand('copy');
    field.remove();
    return done;
  }catch(err){
    return false;
  }
}

/** Копирует фрагмент, отвечая надписью на самой кнопке. */
async function hdCopy(text, button){
  const said = button.textContent;
  button.textContent = await copyText(text) ? 'скопировано' : 'не вышло';
  setTimeout(() => { button.textContent = said; }, 1500);
}

/** 3.5: находки внутри файла. У них своя подпись — не «в файлах», а
 *  «встречается N раз»: файл-то один. */
//: Насколько часто строка должна встречаться, чтобы отметиться сама.
//: Шапка стоит у каждой главы — значит, у почти каждого заголовка. Всё,
//: что реже, находкой остаётся, но галку человек ставит сам.
const HD_SURE_SHARE = 0.7;

/** Похожа ли находка на шапку настолько, чтобы отметить её самому.
 *
 * Название книги над каждой главой встречается тысячу раз при тысяче
 * глав — это шапка. Реплика «Yeah.» встречается двадцать раз при тысяче
 * глав — это текст, и трогать его нельзя.
 */
function hdSure(rule){
  if(rule.kind === 'manual' || rule.kind === 'pattern') return true;
  const total = Number(rule.total) || 0;
  const count = Number(rule.count) || 0;
  return total > 0 && count / total >= HD_SURE_SHARE;
}

/** Отметить или снять разом весь список находок внутри файла. */
function hdInsideAll(on){
  hdInsideChosen = on ? new Set(hdInside.map(hdKey)) : new Set();
  hdRenderInside();
  hdCount();
}

function hdRenderInside(){
  const list = $('hdInside');
  list.innerHTML = '';

  for(const rule of hdInside){
    const row = document.createElement('div');
    row.className = 'tr';

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = hdInsideChosen.has(hdKey(rule));
    box.onchange = () => {
      box.checked ? hdInsideChosen.add(hdKey(rule))
                  : hdInsideChosen.delete(hdKey(rule));
      hdUpdate();
    };

    const text = document.createElement('span');
    text.className = 'grow';
    text.textContent = rule.text;
    text.title = rule.at?.length
      ? 'Строки: ' + rule.at.slice(0, 10).join(', ') : rule.text;

    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = rule.label;

    row.append(box, text, tag);
    list.append(row);

    // 4.3: под находкой — сам фрагмент, а не только название правила.
    // По «Сдвоенный заголовок» не видно, что программа собирается
    // выкинуть, а решать это человеку.
    list.append(hdExample(rule));
  }
  $('hdInsideBox').hidden = hdInside.length === 0;
  hdUpdate();
}

/** Фрагмент под находкой: строки как они лежат в файле (4.3 ТЗ).
 *
 * У правил с тысячей совпадений показывается один пример и счётчик:
 * тысяча одинаковых троек на экране бесполезна. Клик по строке
 * открывает файл, рядом кнопка «скопировать».
 */
function hdExample(rule){
  const box = document.createElement('div');
  box.className = 'tr example';

  const lines = document.createElement('div');
  lines.className = 'grow';

  for(const line of rule.example || []){
    const one = document.createElement('div');
    one.className = 'line' + (line.removed ? ' removed' : '');
    one.textContent = line.text;
    one.title = line.removed ? 'Эта строка удалится' : 'Эта строка останется';
    lines.append(one);
  }
  if(!lines.children.length){
    const said = document.createElement('div');
    said.className = 'line';
    said.textContent = rule.text;
    lines.append(said);
  }
  box.append(lines);

  const file = (rule.files || [])[0];
  if(file){
    const open = document.createElement('button');
    open.className = 'ghost';
    open.style.padding = '4px 10px';
    open.textContent = 'открыть файл';
    open.title = file;
    open.onclick = e => {
      e.stopPropagation();
      call('/api/open', {path: file}).catch(err => showError(err.message, open));
    };
    box.append(open);
    // Клик по самому фрагменту делает то же: целиться в кнопку не надо.
    lines.style.cursor = 'pointer';
    lines.onclick = () => call('/api/open', {path: file})
      .catch(err => showError(err.message, box));
  }

  const copy = document.createElement('button');
  copy.className = 'ghost';
  copy.style.padding = '4px 10px';
  copy.textContent = 'скопировать';
  copy.title = 'Чтобы найти место поиском внутри документа';
  copy.onclick = e => {
    e.stopPropagation();
    // Копируем сам фрагмент: искать в документе по названию правила
    // невозможно, а по строке из файла — ровно то, что нужно.
    hdCopy((rule.example || []).map(l => l.text).join('\n') || rule.text, copy);
  };
  box.append(copy);
  return box;
}

/** 3.4: полностью ручной разбор — первые строки файла с галочками. */
function hdRenderPeek(){
  const list = $('hdPeek');
  list.innerHTML = '';
  for(const line of hdPeekLines){
    if(!line.text.trim()) continue;
    const row = document.createElement('div');
    row.className = 'tr';

    const box = document.createElement('input');
    box.type = 'checkbox';
    const rule = {kind: 'repeat', text: line.text,
                  label: 'отмечено вручную', at: [line.number]};
    box.checked = hdInsideChosen.has(hdKey(rule));
    box.onchange = () => {
      if(box.checked){
        hdInsideChosen.add(hdKey(rule));
        // Отмеченная руками строка становится обычным правилом: иначе её
        // некуда положить, и на «Удалить» она не поедет.
        if(!hdInside.some(r => hdKey(r) === hdKey(rule))) hdInside.push(rule);
      }else{
        hdInsideChosen.delete(hdKey(rule));
      }
      // Список выше — единственная правда о том, что будет удалено.
      hdRenderInside();
    };

    const number = document.createElement('span');
    number.className = 'tag';
    number.textContent = line.number;

    const text = document.createElement('span');
    text.className = 'grow';
    text.textContent = line.text;
    text.title = line.text;

    row.append(box, number, text);
    list.append(row);
  }
  $('hdPeekBox').hidden = list.children.length === 0;
}

function hdUpdate(){
  const total = hdChosen.size + hdInsideChosen.size;
  $('hdClean').disabled = total === 0;
  $('hdClean').textContent = total
    ? `Удалить отмеченное (${total})` : 'Удалить отмеченное';
  // Куда сохранить — показываем, как только есть что удалять.
  $('hdPlace').hidden = !(hdFindings.length || hdInside.length);
}

/** Отмеченные правила внутри файла — в том виде, в каком их ждёт сервер. */
function hdRules(){
  return hdInside.filter(rule => hdInsideChosen.has(hdKey(rule)))
    .map(rule => ({kind: rule.kind, text: rule.text, value: rule.value || ''}));
}

/** Переносит блок в раздел вкладки, которая его вызвала.
 *
 *  Раньше он лежал над всеми разделами сразу и потому висел на каждой
 *  вкладке, даже там, где ничего не выбрано.
 */
function hdPlaceCard(source){
  const field = document.getElementById(source);
  const section = field && field.closest('section');
  const card = $('hdCard');
  if(section && card.parentNode !== section) section.append(card);
}

async function hdScan(source, quiet){
  hdSource = source;
  hdPlaceCard(source);
  const targets = hdTargets();
  if(!targets.length){
    if(!quiet) showError('Сначала выберите файлы или папку');
    return 0;
  }

  if(!quiet){
    $('hdCard').hidden = false;
    $('hdIntro').innerHTML = '<span class="spin"></span>Читаем файлы…';
    $('hdList').innerHTML = '';
    $('hdInside').innerHTML = '';
    $('hdPlace').hidden = true;
  }
  try{
    const data = await call('/api/headers/scan', {
      targets,
      repeat: Number($('hdRepeat').value) || 0,
      offset: Number($('hdOffset').value) || 0,
      pattern: $('hdPattern').value.trim(),
    });
    hdFindings = data.findings || [];
    hdChosen = new Set(hdFindings.map(f => f.text));
    hdInside = data.inside || [];
    // Отмечаем не всё подряд, а только то, что похоже на шапку наверняка.
    // Реплика вроде «Yeah.» повторяется в книге двадцать раз — правило её
    // находит, но шапкой она не является, а снимать пятьсот галок руками
    // невозможно.
    hdInsideChosen = new Set(hdInside.filter(hdSure).map(hdKey));
    hdPeekLines = data.peek || [];

    $('hdCard').hidden = false;
    const found = hdFindings.length + hdInside.length;

    if(!found){
      // 3.4: «ничего не найдено» — не ответ. Показываем начало файла:
      // по нему сразу видно, каким правилом надо воспользоваться.
      $('hdIntro').textContent =
        `Файлов: ${data.file_count}. Правила ничего не нашли — посмотрите `
        + 'начало файла ниже и отметьте лишние строки сами.';
      $('hdRulesBox').open = true;
      hdRenderInside();
      hdRenderPeek();
      return 0;
    }

    $('hdIntro').textContent = hdFindings.length
      ? `Файлов: ${data.file_count}. Строки ниже повторяются почти в каждом — `
        + 'это шапка, а не содержание. Снимите галочку, если строка нужна.'
      : `Файлов: ${data.file_count}. Между файлами повторов нет, а внутри — есть.`;
    $('hdInsideIntro').textContent =
      'Книга может лежать одним файлом на тысячу глав: тогда шапка ищется '
      + 'внутри него самого. Число справа — сколько раз строка встретилась.';
    if(!$('hdFolder').value) $('hdFolder').value = 'Без шапок';
    hdRender();
    hdRenderInside();
    hdRenderPeek();
    return found;
  }catch(err){
    if(!quiet) showError(err.message, $('hdCard'));
    return 0;
  }
}
window.hdScan = hdScan;

/** Предлагается сама при чтении папки, если находка есть. */
async function hdOffer(source){
  const found = await hdScan(source, true);
  if(!found) return;
  // Карточка остаётся свёрнутой, и к ней не подводят взгляд. Раньше делали
  // ровно наоборот — разворачивали и прокручивали страницу вниз, — и это
  // перебивало работу: человек выбрал файл, чтобы его разбить, а его
  // уносило к находке, которую он не спрашивал. Сворачивать её обратно и
  // возвращаться наверх приходилось руками, каждый раз.
  //
  // Находка — это сообщение, а не задача. Уведомления довольно: понадобится
  // — человек спустится и раскроет карточку сам.
  toast(`В начале файлов нашлась шапка: находок ${found}. `
        + 'Блок «Мусорная шапка» — ниже, раскройте, если нужно.');
}
window.hdOffer = hdOffer;

async function hdClean(){
  showError('');
  $('hdClean').disabled = true;
  try{
    const {job} = await call('/api/headers/clean', {
      targets: hdTargets(),
      base: $('hdBase').value.trim(),
      folder: $('hdFolder').value.trim(),
      texts: [...hdChosen],
      rules: hdRules(),
    });
    hdJob = job.id;
    $('hdProgress').hidden = false;
    $('hdSummary').textContent = 'Папка: ' + job.output_dir;

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('hdWritten').textContent = p.written || p.done || 0;
        $('hdFailed').textContent = p.failed || 0;
        return drawResult(p, 'hdFill', 'hdStatus', 'hdPct');
      },
      job => {
        if(job.error){ showError(job.error, $('hdSummary')); return; }
        $('hdSummary').textContent = 'Папка: ' + (job.report?.output || job.output_dir);
      });
  }catch(err){
    showError(err.message);
  }finally{
    hdUpdate();
  }
}

document.querySelectorAll('.hdOpen').forEach(button => {
  button.onclick = () => hdScan(button.dataset.source, false);
});
$('hdClean').onclick = hdClean;
$('hdInsideAll').onclick = () => hdInsideAll(true);
$('hdInsideNone').onclick = () => hdInsideAll(false);
$('hdClose').onclick = () => { $('hdCard').hidden = true; };
// 3.4: правило меняют и сразу смотрят, что найдётся — без предпросмотра
// подбирать выражение вслепую невозможно.
$('hdRescan').onclick = () => hdScan(hdSource, false);
for(const id of ['hdRepeat', 'hdOffset', 'hdPattern']){
  $(id).addEventListener('keydown', e => {
    if(e.key === 'Enter') hdScan(hdSource, false);
  });
}


/* ===================== Настройки модели (часть 2) =====================
 *
 * Пользователь вводит только ключ: список моделей и выбор по умолчанию
 * программа получает сама. Недействительный ключ виден сразу, при вводе,
 * а не при первом разборе главы.
 */

let llmMenu = null, llmModels = [];

/* Поле ввода ключей — многострочное: их вставляют пачкой из блокнота, и
   прятать точками то, что человек прямо сейчас вставляет, бессмысленно.
   В списке ниже и в логах ключ показывается только сокращённым. */

function llmFillModels(models, suggested){
  llmModels = models;
  const options = models.map(m => [
    m.short,
    m.short + (m.flash ? '  · дешёвая' : '') +
      (m.input_limit ? `  · до ${Math.round(m.input_limit / 1000)}k токенов` : ''),
  ]);
  const box = $('llmModel');
  box.dataset.options = JSON.stringify(options);
  box.innerHTML = '';
  llmMenu = makeDropdown(box);
  if(suggested) llmMenu.set(suggested);

  // Тот же список — на вкладке «Форматировать»: модель там та же самая,
  // а второй список однажды разошёлся бы с первым.
  const spare = $('fmModel');
  if(spare){
    spare.dataset.options = JSON.stringify(options);
    spare.innerHTML = '';
    fmState.menus.model = makeDropdown(spare);
    if(suggested) fmState.menus.model.set(suggested, {notify: false});
  }

  $('llmModelNote').textContent = suggested
    ? `Подобрана сама: ${suggested}. Для разбора глав этого достаточно, `
      + 'а на пятистах главах разница в цене существенная.'
    : '';
}

/** Журнал одиночного запроса — в тот же блок, что и журнал разбора.
 *
 * Проверка ключа не задача и прогресс-бара не имеет, но вопросы к ней те
 * же: каким ключом проверяли, через какой адрес ушёл запрос, что ответил
 * сервер. Ответы на них сервер присылает строками вместе с ответом.
 */
function llmLog(lines){
  if(!lines || !lines.length) return;
  const box = $('llmLogBox');
  box.hidden = false;
  box.open = true;
  // Журнал одной проверки, а не накопительный: строки прошлой попытки
  // рядом с новыми только сбивают.
  $('llmLog').innerHTML = '';
  logDraw($('llmLog'), lines);
}

async function llmCheck(){
  showError('');
  $('llmCheck').disabled = true;
  const note = $('llmKeyNote');
  const original = note.textContent;
  note.innerHTML = '<span class="spin"></span>Спрашиваем список моделей…';
  try{
    const data = await call('/api/llm/check', {key: $('llmKey').value.trim()});
    llmLog(data.log);
    note.textContent = `Ключ рабочий: ${data.checked || data.key}. `
      + `Моделей доступно: ${data.models.length}.`;
    $('llmSetup').hidden = false;
    llmFillModels(data.models, data.suggested);
  }catch(err){
    note.textContent = original;
    llmLog(err.log);
    $('llmSetup').hidden = true;
    showError(err.message, $('llmCheck'));
  }finally{
    $('llmCheck').disabled = false;
  }
}

async function llmSave(){
  showError('');
  $('llmSave').disabled = true;
  try{
    const data = await call('/api/llm/save', {
      key: $('llmKey').value.trim(),
      model: llmMenu ? llmMenu.value : '',
      use_proxies: $('llmProxy').checked,
    });
    $('llmSaved').textContent =
      `Сохранено. Ключей: ${data.total}, модель ${data.model}.`;
    $('llmKey').value = '';
    llmRenderKeys(data);
  }catch(err){
    showError(err.message, $('llmSave'));
  }finally{
    $('llmSave').disabled = false;
  }
}

/* ------------------------------------------- список ключей (7.1–7.4) */

/** Сколько ждать до сброса, словами. */
function llmWait(seconds){
  if(seconds === null || seconds === undefined) return '';
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
  if(h) return `${h} ч ${m} мин`;
  return m ? `${m} мин` : 'меньше минуты';
}

function llmRenderKeys(data){
  const box = $('llmKeys');
  box.innerHTML = '';
  const keys = (data && data.keys) || [];
  if(!keys.length){
    box.innerHTML = '<div class="tr"><span class="grow hint">'
      + 'Ключей пока нет. Добавьте хотя бы один.</span></div>';
    return;
  }

  for(const key of keys){
    const row = document.createElement('div');
    row.className = 'tr ' + key.state;

    const name = document.createElement('input');
    name.type = 'text';
    name.className = 'rowname';
    name.value = key.name || '';
    // Заполнителем — сокращённый ключ: имя может быть и пустым, и
    // подставлять его в само поле нельзя, оно сохранится как имя.
    name.placeholder = key.label || 'название';
    name.title = 'Метка, чтобы различать ключи';
    name.onchange = () => llmUpdate(key.id, {name: name.value.trim()});
    row.append(name);

    const shown = document.createElement('span');
    shown.className = 'num';
    shown.textContent = key.key;
    shown.title = 'Ключ целиком не показывается никогда';
    row.append(shown);

    const used = document.createElement('span');
    used.className = 'grow';
    used.textContent = key.limit
      ? `использовано ${key.used} из ${key.limit}`
      : `использовано ${key.used}`;
    row.append(used);

    const limit = document.createElement('input');
    limit.type = 'number';
    limit.min = '0';
    limit.className = 'rowname';
    limit.style.flex = '0 0 90px';
    limit.value = key.limit || '';
    limit.placeholder = 'лимит';
    limit.title = 'Сколько запросов разрешено. Пусто — без ограничения';
    limit.onchange = () => llmUpdate(key.id, {limit: Number(limit.value) || 0});
    row.append(limit);

    const state = document.createElement('span');
    state.className = 'state';
    state.textContent = key.state === 'active' ? 'активен' : 'исчерпан';
    if(key.state !== 'active' && key.resets_in !== null){
      state.textContent += ` · через ${llmWait(key.resets_in)}`;
      state.title = 'Столько до сброса квоты';
    }
    row.append(state);

    const flip = document.createElement('button');
    flip.className = 'ghost';
    flip.style.padding = '4px 10px';
    flip.textContent = key.state === 'active' ? 'отложить' : 'вернуть';
    flip.title = key.state === 'active'
      ? 'Пометить исчерпанным, чтобы не трогать'
      : 'Снять пометку и попробовать снова';
    flip.onclick = () => llmUpdate(key.id,
      {state: key.state === 'active' ? 'exhausted' : 'active'});
    row.append(flip);

    const drop = document.createElement('button');
    drop.className = 'ghost';
    drop.style.padding = '4px 10px';
    drop.textContent = '✕';
    drop.title = 'Убрать ключ';
    drop.onclick = () => llmRemove(key.id);
    row.append(drop);

    box.append(row);
  }
}

async function llmKeysState(){
  try{
    llmRenderKeys(await call('/api/llm/state'));
  }catch(err){ /* список ключей не повод показывать ошибку на весь экран */ }
}

async function llmAdd(){
  showError('');
  const text = $('llmKey').value.trim();
  if(!text){ showError('Введите ключ', $('llmAdd')); return; }
  try{
    const data = await call('/api/llm/keys/add', {
      key: text,
      name: $('llmName').value.trim(),
      limit: Number($('llmLimit').value) || 0,
    });
    $('llmKey').value = '';
    $('llmName').value = '';
    llmRenderKeys(data);
  }catch(err){ showError(err.message, $('llmAdd')); }
}

async function llmUpdate(id, fields){
  try{
    llmRenderKeys(await call('/api/llm/keys/update', {id, ...fields}));
  }catch(err){ showError(err.message, $('llmKeys')); }
}

async function llmRemove(id){
  try{
    llmRenderKeys(await call('/api/llm/keys/remove', {id}));
  }catch(err){ showError(err.message, $('llmKeys')); }
}

/** 7.2: «Оценить расход» — объём работы и сколько класть на ключ. */
async function llmEstimate(){
  showError('');
  const targets = CHOSEN.anList || [];
  if(!targets.length){
    showError('Сначала выберите файлы на этой вкладке', $('llmEstimate'));
    return;
  }
  $('llmEstimate').disabled = true;
  try{
    const data = await call('/api/llm/estimate', {targets, root: anRoot});
    $('llmEstimateNote').textContent =
      `Глав ${data.chapters}, к отправке ${data.to_send}`
      + (data.cached ? `, в кэше ${data.cached}` : '')
      + `. Средняя глава ${ru(data.average)} токенов, всего ~${ru(data.tokens)}.`
      + ` На ключ рекомендуется ${data.per_key} запросов`
      + (data.keys > 1 ? ` (ключей ${data.keys})` : '')
      + '. Значение подставлено в поля лимита — его можно изменить.';
    // Подставляем, но не навязываем: у платных планов потолок другой.
    for(const row of document.querySelectorAll('#llmKeys .tr')){
      const limit = row.querySelectorAll('input')[1];
      if(limit && !Number(limit.value)) limit.value = data.per_key;
    }
  }catch(err){ showError(err.message, $('llmEstimate')); }
  finally{ $('llmEstimate').disabled = false; }
}

/* ------------------------------------------ сколько ключей ещё живы
 *
 * Проверка одного ключа отвечает на вопрос «какая модель», и на полусотне
 * вставленных ключей она бесполезна: отказал первый — и всё, а сколько из
 * остальных рабочих, неизвестно. Ключи кончаются по одному за день, и
 * вопрос тут ровно один — сколько зелёных.
 *
 * Подписи состояний приходят с сервера вместе с отчётом: список закрытый
 * и живёт в `KEY_STATES`.
 */

let llmAllJob = null;

async function llmCheckAll(){
  showError('');
  $('llmCheckAll').disabled = true;
  $('llmAllBox').hidden = false;
  $('llmAllRows').hidden = true;
  try{
    const {job} = await call('/api/llm/keys/checkall', {});
    llmAllJob = job.id;
    $('llmAllStop').hidden = false;
    drawResult(job.progress || {}, 'llmAllFill', 'llmAllStatus');

    pollJob(job.id,
      job => drawResult(job.progress || {}, 'llmAllFill', 'llmAllStatus'),
      job => {
        llmAllJob = null;
        $('llmAllStop').hidden = true;
        $('llmCheckAll').disabled = false;
        if(job.error){ showError(job.error, $('llmAllBox')); return; }
        llmDrawAll(job.report || {});
        // Счётчик живых в шапке считает сервер по хранилищу — после
        // проверки он там другой.
        llmKeysState();
      });
  }catch(err){
    showError(err.message, $('llmCheckAll'));
    $('llmCheckAll').disabled = false;
  }
}

function llmDrawAll(report){
  const table = $('llmAllRows');
  table.innerHTML = '';
  for(const row of report.rows || []){
    const line = document.createElement('div');
    line.className = 'tr';

    const name = document.createElement('span');
    name.className = 'grow';
    name.textContent = row.label;

    const tag = document.createElement('span');
    // Живой — обычной меткой, всё остальное — предупреждением: разница
    // между «работает» и «не работает» должна ловиться взглядом.
    tag.className = row.state === 'live' ? 'tag' : 'tag warn';
    tag.textContent = row.state_name;

    const why = document.createElement('span');
    why.className = 'num';
    why.textContent = row.why ? row.why.slice(0, 70) : '';
    why.title = row.why || '';

    line.append(name, tag, why);
    table.append(line);
  }
  table.hidden = !(report.rows || []).length;
}

$('llmCheckAll').onclick = llmCheckAll;
$('llmAllStop').onclick = () => stopJob(llmAllJob);
$('llmCheck').onclick = llmCheck;
$('llmSave').onclick = llmSave;
$('llmAdd').onclick = llmAdd;
// Запасной путь для вставки: ярлык зависит от раскладки, кнопка — нет.
$('llmPaste').onclick = () => {
  const field = $('llmKey');
  field.focus();
  pasteInto(field);
};
$('llmEstimate').onclick = llmEstimate;
llmKeysState();

// Что уже настроено — показываем при запуске. Сами ключи не показываются
// нигде и никогда: список ниже рисует только сокращения.
call('/api/llm/state').then(data => {
  $('llmProxy').checked = data.use_proxies;
  if(!data.configured) return;
  $('llmKeyNote').textContent =
    `Ключей сохранено: ${data.total}, из них активны ${data.active}`
    + (data.model ? `. Модель: ${data.model}.` : '.')
    + ' Новые добавляются полем выше.';
}).catch(() => {});


/* ======================= Анализ: три этапа =======================
 *
 * Этап 1 — разбор глав моделью, этап 2 — реестр, этап 3 — сверка. Реестр
 * между этапами лежит на диске рядом с книгой, поэтому вкладку можно
 * закрыть и вернуться.
 */

let anRoot = '', anJob = null, anKindMenu = null, anGlossMenu = null;
let anEntities = [], anFindings = [], anKinds = [];

/** Папка книги: рядом с ней ляжет analysis/. */
function anPayload(extra){
  return {targets: CHOSEN.anList || [], root: anRoot, ...(extra || {})};
}

async function anScan(){
  const targets = CHOSEN.anList || [];
  // Смена папки — тоже отмена: разбор пошёл бы по старому выбору, а
  // человек уже смотрит на новый.
  cancelTab('analyze');
  if(!targets.length){
    ['anStage1','anStage2','anStage3','anGlossary','glCard','anRetell']
      .forEach(id => { $(id).hidden = true; });
    $('anScanned').textContent = 'Файлы читаются сразу после выбора.';
    return;
  }
  showError('');
  $('anScanned').innerHTML = '<span class="spin"></span>Читаем…';
  try{
    const data = await call('/api/analyze/scan', anPayload());
    anRoot = data.root;
    updateListBar('anList', data.file_count);
    $('anScanned').textContent =
      `Файлов: ${data.file_count}, глав: ${data.total}. Папка разбора: ${data.root}/analysis`;

    const e = data.estimate;
    $('anEstimate').textContent =
      `К отправке ${e.to_send} из ${e.chapters} глав` +
      (e.cached ? `, ${e.cached} уже в кэше` : '') +
      `. Объём: ${e.characters.toLocaleString('ru')} символов, ` +
      `примерно ${e.tokens.toLocaleString('ru')} токенов.`;

    $('anStage1').hidden = false;
    await anLoadRegistry();
  }catch(err){
    showError(err.message);
    $('anScanned').textContent = '';
  }
}
window.anScan = anScan;

/* --------------------- сессия, журнал и результат (7.5–7.7) ---------- */

/** Отрисовка строк журнала. Общая на все журналы: их на экране уже три —
 *  под разбором глав, под переводом заголовков и под проверкой ключа. */
function logDraw(box, lines){
  const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
  for(const line of lines){
    const row = document.createElement('div');
    row.className = 'ln ' + (line.kind || 'info');
    const at = document.createElement('span');
    at.className = 'at';
    at.textContent = line.at;
    row.append(at, document.createTextNode(line.text));
    box.append(row);
  }
  // Автопрокрутка только если человек и так смотрит на конец: иначе
  // нельзя было бы прочитать то, что уехало выше.
  if(stick) box.scrollTop = box.scrollHeight;
}

/** Наблюдение за журналом задачи: дозапрашивает хвост и рисует.
 *
 *  Общее, как и рисовалка: журналов под прогрессом уже два — разбор глав
 *  и перевод заголовков, — и свой опрос у каждого разошёлся бы с чужим,
 *  а чинить пришлось бы оба. Счётчик прочитанного держим в замыкании: у
 *  двух журналов на экране он свой.
 */
function logWatch(jobId, where){
  const box = $(where.box);
  let seen = 0;

  async function tick(){
    try{
      const data = await call(`/api/job/${jobId}/log?since=${seen}`);
      if(data.lines?.length){
        logDraw(box, data.lines);
        seen = data.total;
      }
    }catch(err){ /* журнал не повод ронять экран */ }
  }

  box.innerHTML = '';
  if(where.wrap) $(where.wrap).hidden = false;
  if(where.save){
    $(where.save).onclick = () => {
      window.location = `/api/job/${jobId}/log.txt`;
    };
  }
  const timer = setInterval(tick, 900);

  return {
    stop(){
      clearInterval(timer);
      // Последний кусок: между опросами могло набежать.
      tick();
    },
  };
}

let anLogger = null;

function anLogStart(jobId){
  anLogger = logWatch(jobId, {box: 'anLog', wrap: 'anLogBox',
                              save: 'anLogSave'});
}

function anLogStop(){
  if(anLogger) anLogger.stop();
  anLogger = null;
}

/** 7.5: блок результата. Он показывается в любом исходе. */
function anShowResult(result, title){
  if(!result) { $('anResult').hidden = true; return; }
  $('anResult').hidden = false;
  $('anResultTitle').textContent = title;
  markResult('anResultTitle', false,
             result.can_continue ? 'cancelled' : 'done');

  const rows = [
    ['Обработано', `${result.done} из ${result.total} глав`],
    ['Ошибок', String(result.failed)],
    ['Ключи', `${result.keys_exhausted} из ${result.keys_total} исчерпаны`],
  ];
  if(result.resets_in !== null && result.resets_in !== undefined){
    rows.push(['Следующий сброс', 'через ' + llmWait(result.resets_in)]);
  }
  rows.push(['Папка', result.output]);

  const box = $('anResultRows');
  box.innerHTML = '';
  for(const [name, value] of rows){
    const span = document.createElement('span');
    span.innerHTML = `${name}: <b>${value}</b>`;
    box.append(span);
  }
  // «Продолжить» имеет смысл, только когда есть чем продолжать.
  $('anContinue').disabled = !result.can_continue;
}

/** 7.6: если по этой папке осталась незавершённая работа — предложить. */
async function anCheckSession(){
  try{
    const data = await call('/api/analyze/sessions', anPayload());
    const found = (data.sessions || [])[0];
    if(!found){ $('anSession').hidden = true; return false; }

    $('anSession').hidden = false;
    const box = $('anSessionRows');
    box.innerHTML = '';
    for(const [name, value] of [
      ['Папка', found.root],
      ['Обработано', `${found.done} из ${found.total}`],
      ['Начата', found.when],
      ['Остановлена', found.reason || '—'],
    ]){
      const span = document.createElement('span');
      span.innerHTML = `${name}: <b>${value}</b>`;
      box.append(span);
    }
    return true;
  }catch(err){ return false; }
}

async function anStart(options){
  showError('');
  options = options || {};

  // Незавершённую работу не переписываем молча: спрашиваем, продолжить
  // или начать заново. Заново — это ещё раз заплатить за те же главы.
  if(!options.confirmed && await anCheckSession()) return;

  $('anSession').hidden = true;
  $('anResult').hidden = true;
  $('anStart').disabled = true;
  try{
    const {job} = await call('/api/analyze/start',
      anPayload({force: $('anForce').checked, restart: !!options.restart}));
    anJob = job.id;
    ownJob('analyze', job.id);
    $('anProgress').hidden = false;
    $('anStop').hidden = false;
    $('anSummary').textContent = 'Папка: ' + job.output_dir;
    anLogStart(job.id);

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('anWritten').textContent = p.written || p.done || 0;
        $('anFailed').textContent = p.failed || 0;
        return drawResult(p, 'anFill', 'anStatus', 'anPct');
      },
      async job => {
        $('anStop').hidden = true;
        dropJob('analyze');
        anLogStop(job.id);
        const r = job.report || {};

        if(job.error){
          showError(job.error);
          anShowResult(r.result, 'Работа прервана ошибкой');
        }else if(job.progress?.stage === 'cancelled'){
          anShowResult(r.result, job.progress.message || 'Работа остановлена');
        }else{
          anShowResult(r.result, 'Готово');
          let text = `Папка: ${r.output || job.output_dir}`;
          if(r.failed_files?.length){
            text += '\n' + r.failed_files.slice(0, 20).join('\n');
          }
          $('anSummary').style.whiteSpace = 'pre-line';
          $('anSummary').textContent = text;
        }
        await anLoadRegistry();
        await llmKeysState();
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('anStart').disabled = false;
  }
}

$('anResume').onclick = () => anStart({confirmed: true});
$('anFresh').onclick = () => {
  if(!confirm('Начать заново? Отметка о ходе работы стирается.\n\n'
              + 'Разобранные главы останутся в кэше — за них уже заплачено.')) return;
  anStart({confirmed: true, restart: true});
};
$('anSkip').onclick = () => { $('anSession').hidden = true; };
$('anContinue').onclick = () => anStart({confirmed: true});
$('anRestart').onclick = () => $('anFresh').onclick();
$('anAddKeys').onclick = () => {
  $('anResult').hidden = true;
  $('llmKey').focus();
  $('llmKey').scrollIntoView({behavior: 'smooth', block: 'center'});
};

/* ------------------------------------------------------------- реестр */

async function anLoadRegistry(){
  try{
    const data = await call('/api/registry/state', anPayload());
    anRoot = data.root;
    anEntities = data.entities || [];

    const s = data.stats;
    $('anStats').textContent = s.entities
      ? `Сущностей ${s.entities}, связей ${s.links}, событий ${s.events}, `
        + `глав разобрано ${s.chapters}. Подтверждено вручную: ${s.confirmed}.`
      : 'Реестр пуст — сначала разберите главы.';

    ['anStage2','anGlossary','glCard','anStage3','anRetell'].forEach(id => {
      $(id).hidden = s.entities === 0;
    });
    anRenderEntities();
    anRenderDupes(data.duplicates || []);
  }catch(err){
    showError(err.message);
  }
}

function anRenderEntities(){
  const kind = anKindMenu ? anKindMenu.value : 'персонаж';
  const list = kind === '__all__' ? anEntities
                                  : anEntities.filter(e => e.type === kind);
  const table = $('anEntities');
  table.innerHTML = '';

  if(!list.length){
    table.innerHTML = '<div class="tr"><span class="grow">Записей этого типа нет.</span></div>';
    return;
  }

  for(const entity of list.slice(0, 300)){
    const row = document.createElement('div');
    row.className = 'tr';

    const name = document.createElement('input');
    name.type = 'text';
    name.className = 'grow';
    name.value = entity.name;
    name.title = 'Правка делает запись подтверждённой — модель её больше не перепишет';
    name.onchange = () => anEdit(entity.id, {name: name.value});

    const aliases = document.createElement('span');
    aliases.className = 'grow';
    aliases.textContent = entity.aliases.join(', ');
    aliases.title = 'Варианты имени';

    const tag = document.createElement('span');
    tag.className = 'tag' + (entity.confirmed ? '' : ' warn');
    tag.textContent = entity.confirmed ? 'подтверждено' : 'от модели';

    const where = document.createElement('span');
    where.className = 'num';
    where.textContent = entity.first_chapter != null ? `с гл. ${entity.first_chapter}` : '';

    row.append(name, aliases, tag, where);
    table.append(row);
  }
}

function anRenderDupes(pairs){
  $('anDupes').hidden = pairs.length === 0;
  const table = $('anDupeList');
  table.innerHTML = '';
  for(const pair of pairs){
    const row = document.createElement('div');
    row.className = 'tr';
    const text = document.createElement('span');
    text.className = 'grow';
    text.textContent = `${pair.keep_name} ← ${pair.drop_name}`;
    const button = document.createElement('button');
    button.className = 'ghost';
    button.style.cssText = 'padding:4px 10px;font-size:12px';
    button.textContent = 'Объединить';
    button.onclick = async () => {
      button.disabled = true;
      try{
        await call('/api/registry/merge',
                   anPayload({keep: pair.keep, drop: pair.drop}));
        await anLoadRegistry();
      }catch(err){ showError(err.message); button.disabled = false; }
    };
    row.append(text, button);
    table.append(row);
  }
}

async function anEdit(id, changes){
  try{
    await call('/api/registry/edit', anPayload({id, ...changes}));
    await anLoadRegistry();
  }catch(err){ showError(err.message); }
}

/* --------------------------------------------------------- глоссарий */

async function anGlossImport(){
  const text = $('anGlossText').value;
  if(!text.trim()){ showError('Вставьте глоссарий в поле'); return; }
  try{
    const data = await call('/api/glossary/import', anPayload({text}));
    $('anGlossNote').textContent =
      `Разобрано строк: ${data.total}, новых записей: ${data.added}.`;
    await anLoadRegistry();
  }catch(err){ showError(err.message); }
}

async function anGlossExport(){
  try{
    const data = await call('/api/glossary/export',
      anPayload({format: anGlossMenu ? anGlossMenu.value : 'txt'}));
    $('anGlossText').value = data.text;
    $('anGlossNote').textContent =
      `Выгружено в формате ${data.format}. Скопируйте и отдайте переводчику.`;
  }catch(err){ showError(err.message); }
}

/* ------------------------------------------ глоссарий имён (пункт 11)
 *
 * Реестр уже сводит написания одного имени в варианты — иначе считал бы
 * одного человека двумя. Здесь накопленное превращается в словарь
 * замен, тот самый, что применяет «Замена по словарю»: своей замены
 * заводить не пришлось, а у неё есть предпросмотр и откат.
 *
 * Правит человек, а не программа. Главное написание выбирается
 * нажатием, ненужную строку можно снять: угадать, «Юй Шэн» правильнее
 * или «Юй Шен», по одному реестру нельзя.
 */
let glGroups = [];

async function glBuild(){
  showError('');
  $('glBuild').disabled = true;
  try{
    const data = await call('/api/names/glossary', anPayload());
    glGroups = (data.groups || []).map(g => ({...g, on: true}));
    glPath = data.path || '';
    glShow();
  }catch(err){ showError(err.message, $('glBuild')); }
  finally{ $('glBuild').disabled = false; }
}

let glPath = '';

function glShow(){
  const box = $('glList');
  box.innerHTML = '';
  $('glSave').hidden = !glGroups.length;

  // Считаем по самим строкам, а не по сводке с сервера: сводка стареет
  // в тот миг, когда человек снял галку или сменил главное написание.
  const on = glGroups.filter(g => g.on);
  const variants = on.reduce((sum, g) => sum + g.variants.length, 0);

  $('glNote').textContent = !glGroups.length
    ? 'Разнобоя в написаниях не нашлось — в реестре каждое имя записано '
      + 'одинаково. Это хорошо: менять нечего.'
    : `Имён с разнобоем: ${glGroups.length}. `
      + `Написаний под замену: ${variants}. `
      + (glPath ? `Правила лягут в ${glPath}.` : '');

  for(const group of glGroups) box.append(glRow(group));
}

function glRow(group){
  const row = document.createElement('div');
  row.className = 'gl' + (group.on ? '' : ' off');

  const use = document.createElement('input');
  use.type = 'checkbox';
  use.checked = group.on;
  use.title = 'Включить это имя в словарь';
  use.onchange = () => { group.on = use.checked; glShow(); };
  row.append(use);

  const side = document.createElement('div');
  side.className = 'gl-side';

  const line = document.createElement('div');
  line.className = 'gl-names';
  for(const name of [group.canonical, ...group.variants]){
    const chip = document.createElement('button');
    chip.className = 'glname' + (name === group.canonical ? ' on' : '');
    chip.textContent = name;
    chip.title = name === group.canonical
      ? 'К этому написанию приводим'
      : 'Сделать главным это написание';
    chip.onclick = () => {
      if(name === group.canonical) return;
      // Меняем местами: прежнее главное становится вариантом, иначе
      // оно бы просто пропало из словаря.
      group.variants = [group.canonical,
                        ...group.variants.filter(v => v !== name)];
      group.canonical = name;
      glShow();
    };
    line.append(chip);
  }
  side.append(line);

  const was = document.createElement('div');
  was.className = 'gl-was';
  was.textContent = `${group.variants.join(', ')} → ${group.canonical}`
    + (group.kind ? ` · ${group.kind}` : '')
    + (group.confirmed ? ' · подтверждено' : '');
  side.append(was);
  row.append(side);
  return row;
}

async function glSave(){
  showError('');
  const chosen = glGroups.filter(g => g.on);
  if(!chosen.length){
    showError('Ни одного имени не отмечено', $('glSave'));
    return;
  }
  $('glSave').disabled = true;
  try{
    const data = await call('/api/names/save', anPayload({groups: chosen}));
    $('glNote').textContent = data.added
      ? `Дописано правил: ${data.added}. Всего в словаре: ${data.rules}. `
        + `Файл: ${data.path}. Применить их — на вкладке «Инструменты», `
        + 'замена по словарю: там есть предпросмотр.'
      : `Новых правил не появилось — все уже были в словаре (${data.rules}).`;
  }catch(err){ showError(err.message, $('glSave')); }
  finally{ $('glSave').disabled = false; }
}

/* ---------------------------------------------------- противоречия */

async function anLoadKinds(){
  try{
    const data = await call('/api/analyze/kinds');
    anKinds = data.kinds || [];
    const box = $('anKinds');
    box.innerHTML = '';
    for(const kind of anKinds){
      const label = document.createElement('label');
      label.className = 'chk';
      const box2 = document.createElement('input');
      box2.type = 'checkbox';
      box2.checked = true;
      box2.dataset.kind = kind.key;
      label.append(box2, document.createTextNode(' ' + kind.name));
      box.append(label);
    }
  }catch(err){ /* вкладка ещё может быть не нужна */ }
}

function anChosenKinds(){
  return [...document.querySelectorAll('#anKinds input:checked')]
    .map(i => i.dataset.kind);
}

async function anCheck(){
  showError('');
  const kinds = anChosenKinds();
  if(!kinds.length){ showError('Отметьте хотя бы одну проверку'); return; }

  $('anCheck').disabled = true;
  $('anCheckNote').innerHTML = '<span class="spin"></span>Сверяем факты с реестром…';
  try{
    const data = await call('/api/analyze/check', anPayload({kinds}));
    anFindings = data.findings || [];
    $('anCheckNote').textContent =
      `Проверено глав: ${data.chapters}. Находок: ${data.total}.`;
    $('anExportRow').hidden = false;
    anRenderFindings();
  }catch(err){
    showError(err.message);
    $('anCheckNote').textContent = '';
  }finally{
    $('anCheck').disabled = false;
  }
}

function anRenderFindings(){
  const table = $('anFindings');
  table.innerHTML = '';
  if(!anFindings.length){
    table.innerHTML = '<div class="tr"><span class="grow">Противоречий не нашлось.</span></div>';
    return;
  }

  anFindings.forEach((finding, index) => {
    const row = document.createElement('div');
    row.className = 'tr';

    const where = document.createElement('span');
    where.className = 'num';
    where.textContent = finding.chapter != null ? `гл. ${finding.chapter}` : '—';

    const kind = document.createElement('span');
    kind.className = 'tag warn';
    kind.textContent = finding.kind_name;

    const text = document.createElement('span');
    text.className = 'grow';
    text.textContent = finding.message;
    text.title = finding.quote || finding.message;

    // Три действия из ТЗ: ошибка, верно, пропустить.
    const actions = document.createElement('span');
    actions.className = 'actions';
    for(const [label, mark] of [['Это ошибка', 'error'],
                                ['Это верно', 'right'],
                                ['Пропустить', 'skip']]){
      const button = document.createElement('button');
      button.className = 'ghost';
      button.style.cssText = 'padding:3px 10px;font-size:11px';
      button.textContent = label;
      button.onclick = () => anDecide(index, mark, row);
      actions.append(button);
    }

    row.append(where, kind, text, actions);
    table.append(row);
  });
}

async function anDecide(index, mark, row){
  const finding = anFindings[index];
  finding.decision = mark;
  row.style.opacity = mark === 'skip' ? '.45' : '1';

  if(mark === 'right' && finding.entity){
    // «Это верно» — реестр ошибался, запись подтверждаем как есть.
    await anEdit(finding.entity, {});
  }
  const kept = anFindings.filter(f => f.decision === 'error').length;
  $('anCheckNote').textContent =
    `Находок: ${anFindings.length}. Помечено ошибками: ${kept}.`;
}

async function anCards(){
  try{
    const data = await call('/api/analyze/cards', anPayload({type: 'персонаж'}));
    $('anGlossText').value = data.text || 'Персонажей в реестре нет.';
    $('anGlossNote').textContent =
      `Карточек: ${data.cards.length}. Текст в поле глоссария — скопируйте.`;
  }catch(err){ showError(err.message); }
}

/** Отчёт по находкам, помеченным ошибками. */
function anSaveReport(){
  const errors = anFindings.filter(f => f.decision === 'error');
  const rows = (errors.length ? errors : anFindings).map(f =>
    `Глава ${f.chapter ?? '—'} · ${f.kind_name}\n${f.message}` +
    (f.quote ? `\nЦитата: ${f.quote}` : '') + '\n');
  $('anGlossText').value = rows.join('\n');
  $('anGlossNote').textContent =
    `Отчёт на ${rows.length} находок — в поле выше, скопируйте.`;
}

$('anList').dataset.onchange = 'anScan';

/* ------------------------------------------------ мусор в главах
 *
 * Подписи находок и разбор строк живут в `ops/junk`: страница только
 * показывает и отмечает. Своя копия правила «что считать лишним» здесь
 * однажды разошлась бы с той, по которой чистят, и человек убрал бы не
 * то, что видел.
 */

let fmJunkFinds = [];
const fmJunkPicked = new Set();

async function fmJunkLook(){
  showError('');
  const targets = CHOSEN.fmBookList || [];
  if(!targets.length){ showError('Сначала выберите готовый .md'); return; }

  $('fmJunkLook').disabled = true;
  $('fmJunkNote').innerHTML = '<span class="spin"></span>Смотрим…';
  try{
    const data = await call('/api/format/junk', {targets});
    fmJunkFinds = data.finds || [];
    fmJunkPicked.clear();
    // Отмечаем сразу то, что мешает загрузчику: остальное — на выбор.
    for(const find of fmJunkFinds) if(find.spoils) fmJunkPicked.add(find.key);
    $('fmJunkNote').textContent = data.summary || '';
    fmJunkDraw();
  }catch(err){
    showError(err.message);
    $('fmJunkNote').textContent = '';
  }finally{
    $('fmJunkLook').disabled = false;
  }
}

function fmJunkDraw(){
  const table = $('fmJunkTable');
  table.innerHTML = '';
  if(!fmJunkFinds.length){
    table.hidden = true;
    $('fmJunkWhere').hidden = true;
    return;
  }

  for(const find of fmJunkFinds){
    const row = document.createElement('div');
    row.className = 'tr';

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = fmJunkPicked.has(find.key);
    box.onchange = () => {
      box.checked ? fmJunkPicked.add(find.key) : fmJunkPicked.delete(find.key);
    };

    const name = document.createElement('span');
    name.className = 'grow' + (find.spoils ? ' cu-hole' : '');
    name.textContent = find.kind_name + (find.text ? ` — ${find.text}` : '');
    name.title = find.sample || name.textContent;

    const count = document.createElement('span');
    count.className = 'num';
    count.textContent = find.count;

    row.append(box, name, count);
    table.append(row);

    // Строки находки: без них непонятно, что именно уйдёт из книги.
    //
    // Раньше показывалась одна — первая попавшаяся. Находка «не
    // переведено» собирает под собой все английские строки книги разом,
    // и по одной из них не понять ни что там осталось, ни стоит ли это
    // убирать: человек видел «[B]» и не видел ещё сорока строк, которые
    // уйдут вместе с ней.
    const spots = find.spots?.length ? find.spots
                : (find.sample ? [{text: find.sample, where: ''}] : []);
    for(const spot of spots){
      const line = document.createElement('div');
      line.className = 'hint';
      line.style.margin = '2px 10px 4px';
      line.textContent = spot.where ? `${spot.where} — ${spot.text}` : spot.text;
      table.append(line);
    }
    // Сколько осталось за списком. Молчать об этом нельзя: человек решил
    // бы, что видит все находки, и снял бы больше, чем думал.
    if(find.count > spots.length){
      const rest = document.createElement('div');
      rest.className = 'hint';
      rest.style.margin = '0 10px 8px';
      rest.textContent = `…и ещё ${find.count - spots.length}`;
      table.append(rest);
    }
  }
  table.hidden = false;
  $('fmJunkWhere').hidden = false;
}

async function fmJunkClean(){
  showError('');
  const targets = CHOSEN.fmBookList || [];
  if(!targets.length){ showError('Сначала выберите готовый .md'); return; }
  if(!fmJunkPicked.size){ showError('Отметьте, что убрать'); return; }

  $('fmJunkClean').disabled = true;
  try{
    const data = await call('/api/format/junk/clean', {
      targets,
      keys: [...fmJunkPicked],
      base: $('fmJunkBase').value.trim(),
      name: $('fmJunkName').value.trim(),
    });
    $('fmJunkResult').textContent =
      `Готово. Снято строк: ${data.removed}, глав: ${data.chapters}.\n${data.output}`;
  }catch(err){
    showError(err.message, $('fmJunkResult'));
  }finally{
    $('fmJunkClean').disabled = false;
  }
}

/* ---------------------------------------- привязка «Форматировать» */

$('fmList').dataset.onchange = 'fmScan';
$('fmBookList').dataset.onchange = 'fmBookScan';
$('fmCollect').onclick = fmCollect;
$('fmRetitle').onclick = fmRetitle;
$('fmBefore').onclick = fmBefore;
$('fmJunkLook').onclick = fmJunkLook;
$('fmJunkClean').onclick = fmJunkClean;
$('fmStop').onclick = () => cancelTab('format');

// Пересчитываем образец на каждое изменение: он и есть ответ на вопрос
// «что получится», а получить его после сборки книги поздно.
for(const id of ['fmPrefix', 'fmVolume', 'fmFirst', 'fmParts']){
  $(id).addEventListener('input', () => { fmShowSample(); fmScan(); });
}

async function fmLoadOptions(){
  try{
    const data = await call('/api/format/options');
    $('fmPrefix').value = data.prefix || 'Глава';
    $('fmSep').dataset.options = JSON.stringify(
      (data.separators || []).map(s => [s.key, s.name]));
    $('fmPaid').dataset.options = JSON.stringify(
      (data.payment || []).map(p => [p.key, p.name]));
    $('fmNames').dataset.options = JSON.stringify(
      (data.names || []).map(n => [n.key, n.name]));
    fmState.menus.names = makeDropdown($('fmNames'), fmShowWay);
    fmShowWay();
    fmState.menus.sep = makeDropdown($('fmSep'), () => {
      fmShowSample();
      fmScan();
    });
    // Название в заголовке: образец перерисовывается, файлы перечитывать
    // незачем — от этого выбора зависит только заголовок.
    fmState.menus.collectNames = makeDropdown($('fmCollectNames'), fmShowSample);
    fmState.menus.paid = makeDropdown($('fmPaid'), () => {
      fmShowSample();
      fmScan();
    });
    if(data.default_separator){
      fmState.menus.sep.set(data.default_separator, {notify: false});
    }
    fmShowSample();
  }catch(err){ /* вкладка ещё может быть не нужна */ }
}
document.addEventListener('DOMContentLoaded', fmLoadOptions);
$('anStart').onclick = () => anStart();
$('anStop').onclick = () => stopJob(anJob);
$('anRebuild').onclick = async () => {
  try{
    await call('/api/registry/rebuild', anPayload());
    await anLoadRegistry();
  }catch(err){ showError(err.message); }
};
$('anGlossImport').onclick = anGlossImport;
$('anGlossExport').onclick = anGlossExport;
$('glBuild').onclick = glBuild;
$('glSave').onclick = glSave;
$('anCheck').onclick = anCheck;
$('anCards').onclick = anCards;
$('anSaveReport').onclick = anSaveReport;

anKindMenu = makeDropdown($('anKind'), () => anRenderEntities());
anGlossMenu = makeDropdown($('anGlossFmt'));
anLoadKinds();

/* -------------------------------- пересказ и выгрузка (3.5) */

let rtWhatMenu = null, rtFormatMenu = null;

async function rtChapters(){
  showError('');
  $('rtChapters').disabled = true;
  $('rtNote').innerHTML = '<span class="spin"></span>Собираем…';
  try{
    const data = await call('/api/retell/chapters', anPayload());
    $('rtText').hidden = false;
    $('rtText').value = data.text || 'Событий в реестре нет.';
    $('rtNote').textContent = data.total
      ? `Пересказ по ${data.total} главам. Запросов к модели не было.`
      : 'Событий в реестре нет — сначала разберите главы.';
  }catch(err){
    showError(err.message);
    $('rtNote').textContent = '';
  }finally{
    $('rtChapters').disabled = false;
  }
}

async function rtAnnotation(){
  showError('');
  $('rtAnnotation').disabled = true;
  $('rtNote').innerHTML = '<span class="spin"></span>Спрашиваем модель…';
  try{
    const data = await call('/api/retell/annotation',
      anPayload({model: llmMenu ? llmMenu.value : ''}));
    $('rtText').hidden = false;
    $('rtText').value = data.text;
    // Про объём говорим, но текст не режем: обрезанная на полуслове
    // аннотация хуже длинной.
    $('rtNote').textContent =
      `Аннотация на ${data.length} символов по ${data.chapters} главам.`
      + (data.within ? '' : ' Это вне рамок 1000–1500 — можно перезапросить.');
  }catch(err){
    showError(err.message);
    $('rtNote').textContent = '';
  }finally{
    $('rtAnnotation').disabled = false;
  }
}

async function rtExport(){
  showError('');
  const what = rtWhatMenu ? rtWhatMenu.value : 'cards';
  try{
    const data = await call('/api/export', anPayload({
      what,
      format: rtFormatMenu ? rtFormatMenu.value : '.md',
      type: anKindMenu ? anKindMenu.value : 'персонаж',
      glossary_format: anGlossMenu ? anGlossMenu.value : 'txt',
      text: $('rtText').value,
    }));
    $('rtSaved').textContent = `Записано: ${data.saved} (${data.length} символов).`;
  }catch(err){ showError(err.message); }
}

$('rtChapters').onclick = rtChapters;
$('rtAnnotation').onclick = rtAnnotation;
$('rtExport').onclick = rtExport;
rtWhatMenu = makeDropdown($('rtWhat'));
rtFormatMenu = makeDropdown($('rtFormat'));



/* ===================== Инструменты редактора =====================
 *
 * Замена по всей книге, словарь автозамен и сверка оригинала с
 * переводом. Общее у всех трёх: ничего не пишется поверх оригиналов, а
 * перед записью показывается, что именно изменится.
 */

let rpMatches = [], rpSkip = new Set(), rpJob = null, cmpKinds = [];

function rpRules(){
  const find = $('rpFind').value;
  if(!find) return [];
  return [{find, replace: $('rpReplace').value,
           regex: $('rpRegex').checked, case: $('rpCase').checked}];
}

function rpTargets(){ return CHOSEN.rpList || []; }

/** Совпадение знает только имя файла — путь достраиваем по выбранному. */
function rpFullPath(name){
  const targets = rpTargets();
  const folder = targets.find(t => !/\.[^./\\]+$/.test(t));
  if(folder) return folder.replace(/[/\\]$/, '') + '/' + name;
  return targets.find(t => t.endsWith(name)) || name;
}

/** Ключ снятого совпадения.
 *
 * Через JSON, а не склейкой через разделитель: в имени файла бывает и
 * пробел, и точка, и дефис — любой выбранный символ рано или поздно
 * встретится внутри имени и развалит ключ. На «Глава 1.txt» так и вышло.
 */
function rpKey(match){
  return JSON.stringify([match.file, match.paragraph, match.rule, match.index]);
}

/** Снятые галочки — четвёрками «файл, абзац, правило, номер совпадения».
 *  Номер обязателен: без него снятая галочка отменяла бы замену во всём
 *  абзаце, а не в одном месте. */
function rpSkipList(){
  return [...rpSkip].map(key => {
    const [file, paragraph, rule, index] = JSON.parse(key);
    return [rpFullPath(file), paragraph, rule, index];
  });
}

async function rpPreview(){
  showError('');
  if(!rpTargets().length){ showError('Сначала выберите файлы или папку'); return; }
  if(!$('rpFind').value){ showError('Введите, что искать'); return; }

  $('rpPreview').disabled = true;
  $('rpNote').innerHTML = '<span class="spin"></span>Ищем…';
  try{
    const data = await call('/api/replace/preview',
      {targets: rpTargets(), rules: rpRules()});
    rpMatches = data.matches || [];
    rpSkip.clear();

    $('rpNote').textContent =
      `Совпадений: ${data.total} в ${data.touched} файлах из ${data.files}.`
      + (data.shown < data.total ? ` Показаны первые ${data.shown}.` : '');
    $('rpPlace').hidden = data.total === 0;
    if(!$('rpFolder').value) $('rpFolder').value = 'Правлено';
    rpRenderMatches();
  }catch(err){
    showError(err.message);
    $('rpNote').textContent = '';
    $('rpPlace').hidden = true;
  }finally{
    $('rpPreview').disabled = false;
  }
}

function rpRenderMatches(){
  const table = $('rpMatches');
  table.innerHTML = '';
  if(!rpMatches.length){
    table.innerHTML = '<div class="tr"><span class="grow">Совпадений нет.</span></div>';
    return;
  }

  for(const match of rpMatches.slice(0, 400)){
    const key = rpKey(match);
    const row = document.createElement('div');
    row.className = 'tr';

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = true;
    box.title = 'Снимите, чтобы это совпадение не заменялось';
    box.onchange = () => {
      if(box.checked) rpSkip.delete(key); else rpSkip.add(key);
      row.style.opacity = box.checked ? '1' : '.45';
      $('rpNote').textContent =
        `Совпадений: ${rpMatches.length}. Снято: ${rpSkip.size}.`;
    };

    const where = document.createElement('span');
    where.className = 'num';
    where.textContent = `${match.chapter} · абз. ${match.paragraph}`;

    const before = document.createElement('span');
    before.className = 'grow';
    before.textContent = match.before;
    before.title = match.before;

    const after = document.createElement('span');
    after.className = 'tag';
    after.textContent = '→ ' + match.after;

    row.append(box, where, before, after);
    table.append(row);
  }
}

async function rpStart(rules, note){
  showError('');
  $('rpStart').disabled = true;
  try{
    const {job} = await call('/api/replace/start', {
      targets: rpTargets(),
      rules: rules || rpRules(),
      skip: rules ? [] : rpSkipList(),
      base: $('rpBase').value.trim(),
      folder: $('rpFolder').value.trim(),
    });
    rpJob = job.id;
    $('rpProgress').hidden = false;
    $('rpSummary').textContent = 'Папка: ' + job.output_dir;

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('rpWritten').textContent = p.written || p.done || 0;
        $('rpFailed').textContent = p.failed || 0;
        return drawResult(p, 'rpFill', 'rpStatus', 'rpPct');
      },
      job => {
        if(job.error){ showError(job.error, $('rpSummary')); return; }
        const r = job.report || {};
        $('rpSummary').textContent =
          `Папка: ${r.output || job.output_dir}` +
          (r.replaced != null ? ` · замен: ${r.replaced}` : '');
        if(note) $(note).textContent = `Готово, замен: ${r.replaced ?? 0}.`;
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('rpStart').disabled = false;
  }
}

/* ---------------------------- речь в кавычках — через тире (инструменты) */

/** Список «до и после» строится сам, как только выбраны файлы.
 *
 *  Кнопки «посмотреть, что изменится» здесь нет намеренно: настраивать
 *  нечего, и лишнее нажатие ничего не решает — только откладывает ответ
 *  на единственный вопрос, который в это время и возникает.
 */
async function spchScan(){
  const targets = rpTargets();
  const table = $('spchTable');
  if(!targets.length){
    $('spchNote').textContent = '';
    table.hidden = true;
    $('spchPlace').hidden = true;
    return;
  }

  $('spchNote').innerHTML = '<span class="spin"></span>Смотрим…';
  try{
    const data = await call('/api/speech/preview', {targets});
    $('spchNote').textContent = data.summary || '';
    spchDraw(data);
  }catch(err){
    showError(err.message, $('spchNote'));
    $('spchNote').textContent = '';
    table.hidden = true;
    $('spchPlace').hidden = true;
  }
}

/** Строку показываем целиком: решают по тексту реплики, а не по длине. */
function spchDraw(data){
  const table = $('spchTable');
  table.innerHTML = '';
  const rows = data.samples || [];
  if(!rows.length){
    table.hidden = true;
    // Прятать «куда сохранить», когда менять нечего: кнопка, которой
    // нечего делать, обещает работу, которой не будет.
    $('spchPlace').hidden = true;
    return;
  }

  for(const row of rows){
    const line = document.createElement('div');
    line.className = 'tr';
    const was = document.createElement('span');
    was.className = 'grow';
    was.textContent = row.before;
    was.title = [row.file, row.chapter].filter(Boolean).join(' · ') || row.before;
    const now = document.createElement('span');
    now.className = 'grow';
    now.textContent = row.after;
    now.title = was.title;
    line.append(was, now);
    table.append(line);
  }
  // Сколько осталось за списком. Молчать нельзя: человек решил бы, что
  // видит все правки, и не ждал бы остальных.
  if(data.more){
    const rest = document.createElement('div');
    rest.className = 'tr';
    const text = document.createElement('span');
    text.className = 'grow';
    text.textContent = `…и ещё ${data.more}`;
    rest.append(text);
    table.append(rest);
  }
  table.hidden = false;
  $('spchPlace').hidden = false;
}

async function spchStart(){
  showError('');
  const targets = rpTargets();
  if(!targets.length){ showError('Сначала выберите файлы или папку'); return; }

  $('spchStart').disabled = true;
  try{
    const {job} = await call('/api/speech/start', {
      targets,
      base: $('spchBase').value.trim(),
      folder: $('spchFolder').value.trim(),
      format: spchState.format ? spchState.format.value : '',
    });
    $('spchProgress').hidden = false;
    $('spchSummary').textContent = 'Папка: ' + job.output_dir;

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('spchWritten').textContent = p.written || p.done || 0;
        $('spchFailed').textContent = p.failed || 0;
        return drawResult(p, 'spchFill', 'spchStatus', 'spchPct');
      },
      job => {
        if(job.error){ showError(job.error, $('spchSummary')); return; }
        const r = job.report || {};
        $('spchSummary').textContent =
          `Папка: ${r.output || job.output_dir}` +
          (r.changed != null ? ` · реплик переписано: ${r.changed}` : '');
      });
  }catch(err){
    showError(err.message, $('spchSummary'));
  }finally{
    $('spchStart').disabled = false;
  }
}

const spchState = {};

/* --------------------------------------------------- словарь автозамен */

/** Папка книги: словарь ведётся отдельно для каждой. */
function dcRoot(){
  const targets = rpTargets();
  if(!targets.length) return '';
  const folder = targets.find(t => !/\.[^./\\]+$/.test(t));
  return folder || targets[0].replace(/[/\\][^/\\]*$/, '');
}

async function dcCall(path, extra){
  return call(path, {targets: rpTargets(), root: dcRoot(), ...(extra || {})});
}

async function dcLoad(){
  try{
    const data = await dcCall('/api/dictionary/load');
    $('dcText').value = data.text || '';
    $('dcNote').textContent = data.text
      ? `Загружено правил: ${data.rules}. Файл: ${data.path}`
      : `Словаря пока нет. Он будет создан здесь: ${data.path}`;
  }catch(err){ showError(err.message); }
}

async function dcSave(){
  try{
    const data = await dcCall('/api/dictionary/save', {text: $('dcText').value});
    $('dcNote').textContent = `Сохранено правил: ${data.rules}. Файл: ${data.path}`;
  }catch(err){ showError(err.message); }
}

async function dcSummary(){
  showError('');
  if(!rpTargets().length){ showError('Сначала выберите файлы или папку'); return; }
  $('dcNote').innerHTML = '<span class="spin"></span>Считаем…';
  try{
    const data = await dcCall('/api/dictionary/summary',
                              {dictionary: $('dcText').value});
    $('dcNote').textContent =
      `Всего замен: ${data.total} в ${data.touched} файлах из ${data.files}.`;

    const table = $('dcRules');
    table.innerHTML = '';
    for(const rule of data.rules){
      const row = document.createElement('div');
      row.className = 'tr';
      const text = document.createElement('span');
      text.className = 'grow';
      text.textContent = `${rule.find} → ${rule.replace}`;
      const tag = document.createElement('span');
      tag.className = 'tag' + (rule.count ? '' : ' warn');
      tag.textContent = rule.count ? String(rule.count) : 'ни разу';
      row.append(text, tag);
      table.append(row);
    }
  }catch(err){
    showError(err.message);
    $('dcNote').textContent = '';
  }
}

async function dcApply(){
  const text = $('dcText').value.trim();
  if(!text){ showError('Словарь пуст'); return; }
  if(!$('rpBase').value.trim()){
    showError('Укажите, куда сохранить — поле выше, в блоке замены');
    return;
  }
  $('rpPlace').hidden = false;
  // Правила берём из словаря, а не из полей поиска.
  const data = await dcCall('/api/dictionary/summary', {dictionary: text});
  await rpStart(data.rules.map(r => ({find: r.find, replace: r.replace,
                                      regex: r.regex})), 'dcNote');
}

/* ------------------------------------------ сверка оригинала и перевода */

async function cmpLoadKinds(){
  try{
    const data = await call('/api/compare/kinds');
    cmpKinds = data.kinds || [];
    const box = $('cmpKinds');
    box.innerHTML = '';
    for(const kind of cmpKinds){
      const label = document.createElement('label');
      label.className = 'chk';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = true;
      input.dataset.kind = kind.key;
      label.append(input, document.createTextNode(' ' + kind.name));
      box.append(label);
    }
  }catch(err){ /* вкладка может быть ещё не нужна */ }
}

async function cmpStart(){
  showError('');
  const left = $('cmpLeft').value.trim(), right = $('cmpRight').value.trim();
  if(!left || !right){ showError('Укажите обе папки'); return; }

  $('cmpStart').disabled = true;
  $('cmpNote').innerHTML = '<span class="spin"></span>Сверяем…';
  try{
    const kinds = [...document.querySelectorAll('#cmpKinds input:checked')]
      .map(i => i.dataset.kind);
    const data = await call('/api/compare/start',
      {original: [left], translated: [right], kinds});

    $('cmpNote').textContent =
      `Глав в оригинале ${data.original}, в переводе ${data.translated}, `
      + `сопоставлено ${data.matched}. Находок: ${data.total}.`;

    const table = $('cmpFindings');
    table.innerHTML = '';
    if(!data.findings.length){
      table.innerHTML = '<div class="tr"><span class="grow">Расхождений нет.</span></div>';
      return;
    }
    for(const finding of data.findings.slice(0, 400)){
      const row = document.createElement('div');
      row.className = 'tr';
      const where = document.createElement('span');
      where.className = 'num';
      where.textContent = finding.chapter;
      const kind = document.createElement('span');
      kind.className = 'tag warn';
      kind.textContent = finding.kind_name;
      const text = document.createElement('span');
      text.className = 'grow';
      text.textContent = finding.message;
      text.title = finding.source || finding.message;
      row.append(where, kind, text);
      table.append(row);
    }
  }catch(err){
    showError(err.message);
    $('cmpNote').textContent = '';
  }finally{
    $('cmpStart').disabled = false;
  }
}

$('rpPreview').onclick = rpPreview;
$('rpStart').onclick = () => rpStart();
$('spchStart').onclick = spchStart;
spchState.format = makeDropdown($('spchFormat'));
// Список «до и после» строится сам: выбор файлов — единственное,
// что этой работе нужно знать.
$('rpList').dataset.onchange = 'spchScan';
$('dcLoad').onclick = dcLoad;
$('dcSave').onclick = dcSave;
$('dcSummary').onclick = dcSummary;
$('dcApply').onclick = dcApply;
$('cmpStart').onclick = cmpStart;
cmpLoadKinds();


/* ----------------------------------------- два слива одной книги
 *
 * Подписи находок и вывод «какую папку брать» считает сервер: разница
 * между «есть только слева» и «слева обрезано» одна на всю программу, и
 * второй её экземпляр здесь однажды разошёлся бы с первым.
 */

async function sdStart(){
  showError('');
  const left = $('sdLeft').value.trim(), right = $('sdRight').value.trim();
  if(!left || !right){ showError('Укажите обе папки'); return; }

  $('sdStart').disabled = true;
  $('sdNote').innerHTML = '<span class="spin"></span>Сравниваем…';
  try{
    const data = await call('/api/sides/start', {left: [left], right: [right]});

    const here = data.left_name || 'первая', there = data.right_name || 'вторая';
    $('sdNote').textContent =
      `Глав: ${here} — ${data.left_total}, ${there} — ${data.right_total}, `
      + `общих ${data.matched}. Расхождений: ${data.total}.`;
    $('sdAdvice').textContent = data.advice || '';

    const chips = $('sdSummary');
    chips.innerHTML = '';
    for(const row of data.summary || []){
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.textContent = `${row.kind_name}: ${row.count}`;
      chips.append(chip);
    }

    const table = $('sdFindings');
    table.innerHTML = '';
    for(const finding of data.findings || []){
      const row = document.createElement('div');
      row.className = 'tr';
      const where = document.createElement('span');
      where.className = 'num';
      where.textContent = finding.chapter;
      const kind = document.createElement('span');
      kind.className = 'tag warn';
      kind.textContent = finding.kind_name;
      const size = document.createElement('span');
      size.className = 'grow';
      // Числа рядом с находкой: без них «короче» нечем поверить.
      size.textContent = `${finding.left} ↔ ${finding.right} знаков`;
      row.append(where, kind, size);
      table.append(row);
    }
    for(const bad of data.unreadable || []){
      const row = document.createElement('div');
      row.className = 'tr';
      const text = document.createElement('span');
      text.className = 'grow';
      text.textContent = bad;
      row.append(text);
      table.append(row);
    }
  }catch(err){
    showError(err.message);
    $('sdNote').textContent = '';
  }finally{
    $('sdStart').disabled = false;
  }
}

$('sdStart').onclick = sdStart;


/* ============= Сравнение версий, журнал и корзина =============
 *
 * Обе вещи — страховка. Автоматическая очистка иногда портит текст, и без
 * сравнения это обнаруживается поздно и случайно; без корзины
 * восстанавливать нечего вовсе.
 */

async function dfStart(){
  showError('');
  const before = $('dfBefore').value.trim(), after = $('dfAfter').value.trim();
  if(!before || !after){ showError('Укажите обе стороны сравнения'); return; }

  $('dfStart').disabled = true;
  $('dfNote').innerHTML = '<span class="spin"></span>Сравниваем…';
  try{
    const data = await call('/api/diff', {before, after});
    $('dfNote').textContent =
      `Глав сопоставлено ${data.total}, изменено ${data.changed}. `
      + `Добавлено строк ${data.added}, убрано ${data.removed}.`
      + (data.only_left.length ? ` Только слева: ${data.only_left.join(', ')}.` : '')
      + (data.only_right.length ? ` Только справа: ${data.only_right.join(', ')}.` : '');
    dfRender(data.chapters || []);
  }catch(err){
    showError(err.message);
    $('dfNote').textContent = '';
    $('dfResult').innerHTML = '';
  }finally{
    $('dfStart').disabled = false;
  }
}

function dfRender(chapters){
  const box = $('dfResult');
  box.innerHTML = '';
  if(!chapters.length){
    box.innerHTML = '<p class="hint">Различий нет.</p>';
    return;
  }

  for(const chapter of chapters.slice(0, 40)){
    const block = document.createElement('div');
    block.className = 'diff';
    block.style.marginBottom = '12px';

    const head = document.createElement('div');
    head.className = 'diff-head';
    head.textContent =
      `Глава ${chapter.chapter} · добавлено ${chapter.added}, убрано ${chapter.removed}`;
    block.append(head);

    for(const line of chapter.lines){
      const row = document.createElement('div');
      row.className = 'ln ' + line.kind;
      row.textContent = line.text;
      block.append(row);
    }
    box.append(block);
  }
}

/* ------------------------------------------------- журнал и корзина */

async function hsLoad(){
  showError('');
  // Пока журнал и корзина читаются, таблица не должна выглядеть пустой.
  if(typeof fxSkeleton === 'function') fxSkeleton('hsRecords', 5);
  try{
    const data = await call('/api/history/state');
    hsRender(data);
  }catch(err){ showError(err.message); }
}

function hsRender(data){
  // Вес корзины виден рядом со счётом копий: десять копий одной правки —
  // это ничто, а десять копий книги на пятьсот глав — гигабайты, о
  // которых иначе узнаёшь от диска.
  $('hsNote').textContent =
    `Записей: ${data.records.length}. Копий в корзине: ${data.backups.length} `
    + `(хранится последних ${data.keep}), вес ${weigh(data.bytes)} `
    + `из ${weigh(data.cap)}. Папка данных: ${data.dir}, `
    + `${weigh(data.data_bytes)}`;

  const table = $('hsRecords');
  table.innerHTML = '';
  if(!data.records.length){
    table.innerHTML = '<div class="tr"><span class="grow">Журнал пуст.</span></div>';
    return;
  }

  for(const record of data.records.slice(0, 100)){
    const row = document.createElement('div');
    row.className = 'tr';

    const when = document.createElement('span');
    when.className = 'num';
    when.textContent = record.when;

    const what = document.createElement('span');
    what.className = 'tag';
    what.textContent = record.operation;

    const where = document.createElement('span');
    where.className = 'grow';
    where.textContent = record.output || record.source;
    where.title = `Источник: ${record.source}\nРезультат: ${record.output}`;

    const counts = document.createElement('span');
    counts.className = 'num';
    counts.textContent = `${record.files} файл.`
      + (record.failed ? ` · ошибок ${record.failed}` : '');

    row.append(when, what, where, counts);

    if(record.restorable){
      const button = document.createElement('button');
      button.className = 'ghost';
      button.style.cssText = 'padding:3px 10px;font-size:11px';
      button.textContent = 'Восстановить';
      button.title = `Вернуть файлы из копии ${record.backup}`;
      button.onclick = () => hsRestore(record, button);
      row.append(button);
    }
    table.append(row);
  }
}

async function hsRestore(record, button){
  // Текущее состояние тоже уйдёт в корзину — на сервере, до записи.
  button.disabled = true;
  button.textContent = 'Возвращаем…';
  try{
    const data = await call('/api/history/restore',
      {backup: record.backup, target: record.output});
    hsRender(data);
    toast(`Восстановлено файлов: ${data.restored}.`);
  }catch(err){
    showError(err.message);
    button.disabled = false;
    button.textContent = 'Восстановить';
  }
}

$('dfStart').onclick = dfStart;
$('hsLoad').onclick = hsLoad;

/* ------------------------------------------- вернуть как было
 *
 * Копия перед перезаписью делалась всегда, а достать её можно было
 * только так: четвёртая вкладка, «Показать», найти строку, нажать
 * «Восстановить». Страховка, о которой узнаёшь, только специально полезши
 * за ней, спасает не тогда, когда нужна.
 *
 * Теперь то же самое — одной кнопкой и по Ctrl+Z с любой вкладки. Само
 * возвращение обратимо: перед ним текущее состояние тоже уходит в
 * корзину.
 */

//: Что откатится. Пусто — откатывать нечего, и кнопки не видно.
let undoWhat = null;

function undoShow(state){
  undoWhat = (state || {}).undo || null;
  // Сколько шагов назад ещё осталось. Одна кнопка без счётчика читается
  // как единственная попытка, и после первого возврата человек не знает,
  // можно ли нажать ещё.
  const left = ((state || {}).undo_left) || 0;
  $('hsUndo').hidden = !undoWhat;
  $('hsUndoNote').textContent = undoWhat
    ? `Ctrl+Z вернёт папку «${undoWhat.output}» к тому, что было `
      + `до операции «${undoWhat.operation}» от ${undoWhat.when}.`
      + (left > 1
         ? ` Дальше назад — ещё ${left - 1} `
           + `${plural(left - 1, 'шаг', 'шага', 'шагов')}.`
         : '')
    : '';
}

async function undoLook(){
  try{
    undoShow(await call('/api/history/state'));
  }catch(err){
    // Нет журнала — просто нечего предлагать.
    undoShow(null);
  }
}

async function undoDo(){
  if(!undoWhat){
    showError('Возвращать нечего: копии последней операции нет');
    return;
  }
  if(!confirm(`Вернуть папку «${undoWhat.output}» к тому, что было до `
              + `операции «${undoWhat.operation}» от ${undoWhat.when}?\n\n`
              + 'Нынешнее содержимое тоже уйдёт в корзину — этот шаг '
              + 'обратим.')) return;
  try{
    const got = await call('/api/history/undo', {});
    toast(`Возвращено файлов: ${got.restored}.`);
    undoShow(got);
  }catch(err){
    showError(err.message, $('hsUndo'));
  }
}

$('hsUndo').onclick = undoDo;

/* --------------------------------------------- горячие клавиши
 *
 * На всю программу их было две: Escape и Ctrl+V. Добавляем ровно то, что
 * делают чаще всего, — выбрать файл и запустить.
 *
 * Кнопку ищем на самой вкладке, а не по таблице «вкладка → кнопка»:
 * такая таблица устаревает молча, стоит переименовать один `id`. Главное
 * действие вкладки — её единственная `primary`, выбор файла — кнопка
 * выбора; так оно и размечено везде.
 *
 * Клавиши узнаём по `code`, а не по букве: на кириллице Ctrl+O — это
 * Ctrl+Щ, и по `key` он бы не поймался.
 */

function tabNow(){
  return [...document.querySelectorAll('section[id^="tab-"]')]
    .find(one => !one.hidden) || null;
}

function typing(){
  const spot = document.activeElement;
  return !!spot && (spot.tagName === 'INPUT' || spot.tagName === 'TEXTAREA'
                    || spot.isContentEditable);
}

/** Видно ли элемент по-настоящему.
 *
 * Проверять свой `hidden` мало: кнопка бывает открытой, а спрятан её
 * родитель. Так и вышло — на «Разбить» первой в разметке идёт `primary`
 * из закрытого окна «Разделить», и Ctrl+Enter нажимал бы её вместо
 * «Разбить». `offsetParent` пуст у всего, что не на экране.
 */
function onScreen(node){
  return !!node && !node.hidden && node.offsetParent !== null;
}

/** Нажимает кнопку вкладки, если она есть, видна и доступна. */
function tabPress(selector){
  const where = tabNow();
  if(!where) return false;
  const button = [...where.querySelectorAll(selector)]
    .find(one => onScreen(one) && !one.disabled);
  if(!button) return false;
  button.click();
  return true;
}

document.addEventListener('keydown', event => {
  if(!(event.ctrlKey || event.metaKey) || event.shiftKey || event.altKey) return;

  // Ctrl+Z — вернуть как было. Не поверх набора текста: там своя отмена,
  // и отнимать её у полей ввода нельзя.
  if(event.code === 'KeyZ'){
    if(typing()) return;
    event.preventDefault();
    undoDo();
    return;
  }

  // Ctrl+O — выбрать файл или папку на этой вкладке.
  if(event.code === 'KeyO'){
    if(tabPress('.pickany, .browse')) event.preventDefault();
    return;
  }

  // Ctrl+Enter — запустить. Работает и из поля ввода: там это привычный
  // способ отправить набранное, а не отмена чего-либо.
  if(event.code === 'Enter' || event.code === 'NumpadEnter'){
    if(tabPress('button.primary:not([hidden])')) event.preventDefault();
  }
});

undoLook();

/* ------------------------------------------- обновление программы
 *
 * Проверка и загрузка разделены нарочно: трафик у человека может быть на
 * счету, и решать, тратить ли его на файлы, должен он — увидев сперва,
 * сколько их и насколько они изменились.
 *
 * Вес в байтах до загрузки не обещаем: сравнение отдаёт число строк, а не
 * байт, и выдавать одно за другое нельзя.
 */

let upPlan = null;

function upDrawFiles(plan){
  const table = $('upFiles');
  table.innerHTML = '';
  for(const one of plan.changes || []){
    const row = document.createElement('div');
    row.className = 'tr';
    const name = document.createElement('span');
    name.className = 'grow';
    name.textContent = one.path;
    name.title = one.path;
    const tag = document.createElement('span');
    tag.className = 'tag' + (one.gone ? ' warn' : '');
    tag.textContent = one.gone ? 'удалён'
      : one.status === 'added' ? 'новый' : 'изменён';
    const size = document.createElement('span');
    size.className = 'num';
    // Вес честнее строк, но знает его только сверка по содержимому.
    size.textContent = one.gone ? '—'
      : one.size ? weigh(one.size) : `${one.lines} стр.`;
    row.append(name, tag, size);
    table.append(row);
  }
  table.hidden = !(plan.changes || []).length;
}

/** Одна кнопка: посмотреть, спросить и забрать.
 *
 *  Двух кнопок быть не должно. «Проверить», а потом «Обновить» — это
 *  работа программы, переложенная на человека: он и так нажал
 *  «обновить», значит хочет обновиться. Трафик бережёт не вторая
 *  кнопка, а вопрос с весом перед загрузкой — его и задаём.
 */
async function upGo(){
  showError('');
  const button = $('upGo');
  button.disabled = true;
  $('upErrors').hidden = true;
  $('upNews').hidden = true;
  $('upNote').innerHTML = '<span class="spin"></span>Смотрим, что изменилось…';

  let plan;
  try{
    plan = await call('/api/update/look');
  }catch(err){
    showError(err.message, $('upNote'));
    $('upNote').textContent = '';
    button.disabled = false;
    return;
  }

  upPlan = plan;
  $('upWhere').textContent = `Источник: ${plan.where}`;
  upDrawFiles(plan);

  if(plan.trouble || plan.fresh || !plan.files){
    $('upNote').textContent = plan.trouble
      || (plan.fresh ? 'Стоит последняя версия.'
                     : 'Обновлять нечего: расхождений с репозиторием нет.');
    button.disabled = false;
    return;
  }

  // Вес известен точно только при сверке по содержимому; сравнение
  // коммитов его не сообщает, и выдавать строки за байты нельзя.
  const weight = plan.size ? weigh(plan.size)
                           : `${plan.lines} строк(и) правок`;
  const also = plan.needs_install
    ? '\n\nИзменился список зависимостей — после обновления понадобится: '
      + 'pip install -r requirements.txt'
    : '';
  $('upNote').textContent = `Изменилось файлов: ${plan.files}, ${weight}.`;
  if(!confirm(`Скачать ${plan.files} файл(ов), ${weight}?\n\n`
              + 'Прежние уйдут в корзину, вернуть их можно кнопкой.' + also)){
    $('upNote').textContent += ' Не качаем.';
    button.disabled = false;
    return;
  }

  try{
    const {job} = await call('/api/update/apply', {});
    $('upProgress').hidden = false;
    pollJob(job.id,
      job => drawResult(job.progress || {}, 'upFill', 'upStatus', 'upPct'),
      job => {
        button.disabled = false;
        if(job.error){ showError(job.error, $('upNote')); return; }
        $('upFiles').hidden = true;
        showFailures('upErrors', (job.report?.failures || []).map(
          one => ({file: one, step: 'обновление', error: ''})));
        const done = job.report || {};
        if(done.rolled_back){
          // Прежние файлы уже вернулись на место — сказать это прямо
          // важнее, чем показать список новшеств, которых не будет.
          $('upNote').textContent =
            'Обновление отменено: с новыми файлами программа не '
            + `запускается (${done.rolled_back}). Прежняя версия на месте.`;
          return;
        }
        upNews(done.news || []);
        $('upBack').hidden = !done.backup;
        $('upNote').textContent =
          `Обновлено, ${weigh(done.bytes || 0)}. Изменения вступят в силу `
          + 'после перезапуска программы.'
          + (done.needs_install
             ? ' Изменился список зависимостей — выполните: '
               + 'pip install -r requirements.txt'
             : '');
      });
  }catch(err){
    showError(err.message, $('upNote'));
    button.disabled = false;
  }
}

/** Что нового: заголовки, появившиеся в истории изменений. */
function upNews(rows){
  const list = $('upNewsList');
  list.innerHTML = '';
  for(const one of rows){
    const item = document.createElement('li');
    item.textContent = one;
    list.append(item);
  }
  $('upNews').hidden = !rows.length;
}

async function upBack(){
  showError('');
  if(!confirm('Вернуть файлы программы к тому, что стояло до обновления?\n\n'
              + 'Книги, настройки и журнал не тронутся.')) return;
  const button = $('upBack');
  button.disabled = true;
  try{
    const got = await call('/api/update/undo', {});
    $('upNote').textContent = got.message;
    $('upNews').hidden = true;
    button.hidden = true;
  }catch(err){
    showError(err.message, $('upNote'));
  }finally{
    button.disabled = false;
  }
}

$('upGo').onclick = upGo;
$('upBack').onclick = upBack;

/* ------------------------------------------- отчёт о проблеме
 *
 * Журнал теперь пишется в файл, но найти его в папке данных и вырезать
 * оттуда нужное — работа, которую человек делать не станет. Кнопка
 * собирает готовый текст: версия, система, последние строки журнала и
 * то, что человек сам написал про поломку.
 *
 * Свой набор имён (`dg`), а не `rp`: тот занят вкладкой «Замена», и
 * повторный `id` на странице отваливается молча.
 */

async function dgMake(){
  showError('');
  const button = $('dgMake');
  button.disabled = true;
  $('dgNote').innerHTML = '<span class="spin"></span>Собираем…';
  try{
    const got = await call('/api/report', {what: $('dgWhat').value.trim()});
    $('dgText').value = got.text || '';
    $('dgText').hidden = false;
    $('dgCopy').hidden = false;
    $('dgOpen').hidden = !got.kept;
    $('dgOpen').dataset.path = got.file || '';
    $('dgNote').textContent = got.kept
      ? 'Готово. Ключи и пароли вырезаны — можно отправлять.'
      : 'Журнала ещё нет: он заводится при запуске программы. '
        + 'Отчёт собран без него.';
  }catch(err){
    showError(err.message);
    $('dgNote').textContent = '';
  }finally{
    button.disabled = false;
  }
}

$('dgMake').onclick = dgMake;
$('dgCopy').onclick = async () => {
  try{
    await navigator.clipboard.writeText($('dgText').value);
    $('dgNote').textContent = 'Скопировано.';
  }catch(err){
    // Буфер бывает закрыт настройками браузера — выделяем, чтобы
    // человек нажал Ctrl+C сам, а не остался ни с чем.
    $('dgText').select();
    $('dgNote').textContent = 'Буфер недоступен — текст выделен, нажмите Ctrl+C.';
  }
};
$('dgOpen').onclick = async () => {
  try{
    await call('/api/open', {path: $('dgOpen').dataset.path});
  }catch(err){ showError(err.message); }
};


/* ------------------------------------------- переводчик EPUB (связь)
 *
 * Переводчик — отдельная программа, стоящая рядом. Мы храним только путь
 * к ней и зовём её команды. Своего глоссария, промптов и ключей у нас
 * нет: всё это остаётся у неё, в папке проекта и в её домашней папке.
 *
 * Здесь пока только проверка связи. Пока она не ответит, строить перевод
 * бессмысленно — окажется, что говорить не с кем.
 */

function tlShow(data){
  data = data || {};
  const path = data.path || '';
  if(path && !$('tlPath').value) $('tlPath').value = path;

  const rows = data.providers || [];
  const table = $('tlList');
  table.innerHTML = '';
  for(const one of rows){
    const row = document.createElement('div');
    row.className = 'tr';
    const name = document.createElement('span');
    name.className = 'grow';
    name.textContent = one.name || one.id;
    const keys = document.createElement('span');
    keys.className = 'num';
    keys.textContent = `${one.keys} ${plural(one.keys, 'ключ', 'ключа', 'ключей')}`;
    const models = document.createElement('span');
    models.className = 'num';
    models.textContent = one.models
      ? `${one.models} ${plural(one.models, 'модель', 'модели', 'моделей')}`
      : '—';
    row.append(name, keys, models);
    table.append(row);
  }
  table.hidden = !rows.length;
}

async function tlLoad(){
  try{
    tlShow(await call('/api/translator/state'));
  }catch(err){
    // Настройка — удобство. Не прочиталась — остальное работает.
    $('tlNote').textContent = '';
  }
}

async function tlSave(){
  const path = $('tlPath').value.trim();
  try{
    const got = await call('/api/translator/path', {path});
    tlShow(got);
    $('tlNote').textContent = path
      ? 'Папка запомнена. Нажмите «Проверить связь».'
      : 'Путь очищен.';
    return true;
  }catch(err){
    showError(err.message, $('tlNote'));
    $('tlNote').textContent = '';
    return false;
  }
}

async function tlCheck(){
  showError('');
  const button = $('tlCheck');
  button.disabled = true;
  // Путь сперва запоминаем: проверять одно, а хранить другое — верный
  // способ получить «работало вчера».
  if(!(await tlSave())){ button.disabled = false; return; }

  $('tlNote').innerHTML = '<span class=\"spin\"></span>Спрашиваем переводчик…';
  try{
    const got = await call('/api/translator/check', {path: $('tlPath').value.trim()});
    tlShow(got);
    const bits = [`Связь есть. Ключей: ${got.keys}`];
    if(got.provider) bits.push(`сервис: ${got.provider}`);
    if(got.model) bits.push(`модель: ${got.model}`);
    if(got.projects) bits.push(`проектов в истории: ${got.projects}`);
    $('tlNote').textContent = bits.join(', ') + '.';
  }catch(err){
    showError(err.message, $('tlNote'));
    $('tlNote').textContent = '';
  }finally{
    button.disabled = false;
  }
}

$('tlCheck').onclick = tlCheck;
$('tlPath').onchange = tlSave;
tlLoad();

/* ------------------------------------- что именно будет переведено
 *
 * План — это «до и после» для перевода, и нужен он ровно затем же:
 * увидеть работу до того, как за неё заплатят. Цена тут — квота ключей,
 * и промахнуться дороже всего.
 *
 * В сеть план не ходит и квоту не тратит, поэтому и ответ приходит
 * сразу, без задачи и полосы прогресса.
 */

const tlScopeMenu = makeDropdown($('tlScope'));

/** Строка плана: подпись слева, число или текст справа. */
function tlRow(name, value, hint){
  const row = document.createElement('div');
  row.className = 'tr';

  const left = document.createElement('span');
  left.className = 'grow';
  left.textContent = name;
  if(hint) left.title = hint;

  const right = document.createElement('span');
  right.className = 'num';
  right.textContent = value;

  row.append(left, right);
  return row;
}

function tlPlanShow(got){
  const table = $('tlPlanRows');
  table.innerHTML = '';

  for(const [name, value, hint] of [
    ['Глав возьмётся', ru(got.chapters), ''],
    ['Задач к модели', ru(got.tasks),
     'Глава может делиться на несколько запросов — по ним и считается квота'],
    ['Знаков в исходнике', ru(got.chars), ''],
    ['Сервис', got.provider || '—', ''],
    ['Модель', got.model || '—', ''],
    // Квота — единственное, из-за чего план вообще смотрят: по ней и
    // видно, хватит ли ключей на всю книгу разом.
    ['Запросов в минуту', got.rpm ? ru(got.rpm) : '—', ''],
    ['Запросов в сутки', got.rpd ? ru(got.rpd) : '—',
     'На один ключ. Задач больше — работа встанет на квоте'],
  ]){
    if(value !== '—' || name === 'Сервис' || name === 'Модель'){
      table.append(tlRow(name, value, hint));
    }
  }

  if(got.sample?.length){
    const where = document.createElement('div');
    where.className = 'hint';
    where.style.margin = '6px 10px 8px';
    where.textContent = got.sample.join(' · ')
      + (got.more ? ` … и ещё ${got.more}` : '');
    table.append(where);
  }
  table.hidden = false;
}

async function tlPlanLook(){
  showError('');
  const button = $('tlPlan');
  button.disabled = true;
  $('tlPlanRows').hidden = true;
  $('tlPlanNote').innerHTML = '<span class="spin"></span>Считаем план…';
  try{
    const got = await call('/api/translator/plan', {
      path: $('tlPath').value.trim(),
      epub: $('tlEpub').value.trim(),
      project: $('tlProject').value.trim(),
      scope: tlScopeMenu ? tlScopeMenu.value : 'pending',
    });
    tlPlanShow(got);
    $('tlPlanNote').textContent = got.chapters
      ? `Возьмётся глав: ${ru(got.chapters)}. Ключей и сети это пока не стоило.`
      : 'Брать нечего: под этот отбор не попала ни одна глава.';
  }catch(err){
    showError(err.message, $('tlPlanNote'));
    $('tlPlanNote').textContent = '';
  }finally{
    button.disabled = false;
  }
}

$('tlPlan').onclick = tlPlanLook;

/* ------------------------------------------------ сама работа
 *
 * Четыре команды переводчика в том порядке, в каком их и делают:
 * глоссарий, перевод, сверка, сборка. Каждая идёт часами, поэтому
 * обычной задачей — с журналом и остановкой.
 *
 * Полосы по главам тут нет и не будет обманной: сколько глав впереди,
 * переводчик по ходу не сообщает. Вместо процента — его собственный
 * журнал: видно, что он делает прямо сейчас.
 */

let tlJob = null;

/** Что отправляем на любую из четырёх команд. */
function tlWork(){
  return {
    path: $('tlPath').value.trim(),
    epub: $('tlEpub').value.trim(),
    project: $('tlProject').value.trim(),
    scope: tlScopeMenu ? tlScopeMenu.value : 'pending',
    workers: Number($('tlWorkers').value) || 0,
    rpm: Number($('tlRpm').value) || 0,
    // Пустое поле — «как настроено у переводчика»: своим значением
    // затирать его настройку молча нельзя.
    temperature: $('tlTemp').value.trim() || null,
  };
}

/** Полоса: `null` — бежит, `true` — полная, `false` — пустая.
 *
 *  Бегущая полоса честна, пока работа идёт, но после «Готово» она врала
 *  бы: движение читается как «ещё делается».
 */
function tlBar(done){
  const fill = $('tlFill');
  fill.parentElement.classList.toggle('waiting', done === null);
  fill.style.width = done === null ? '' : (done ? '100%' : '0');
}

function tlLog(rows){
  const box = $('tlLog');
  if(!box) return;
  box.textContent = (rows || []).join('\n');
  $('tlLogBox').hidden = !(rows || []).length;
  box.scrollTop = box.scrollHeight;
}

async function tlRun(what, extra){
  showError('');
  const buttons = ['tlGlossary', 'tlTranslate', 'tlConsistency', 'tlBuild'];
  buttons.forEach(id => { $(id).disabled = true; });
  $('tlBox').hidden = false;
  $('tlStop').hidden = false;
  $('tlDone').textContent = '';
  tlBar(null);
  tlLog([]);

  try{
    const {job} = await call('/api/translator/' + what,
                             {...tlWork(), ...(extra || {})});
    tlJob = job.id;
    // Вкладке эта задача намеренно не отдаётся — как и скачивание, см.
    // `cancelTab`. Перевод идёт часами и стоит квоты ключей, а «Очистить
    // список» на этой же вкладке снимает совсем другой список: обрывать
    // им ночную работу нельзя. Останавливает её только своя кнопка.
    drawResult(job.progress || {}, 'tlFill', 'tlStatus');

    pollJob(job.id,
      job => {
        tlLog(job.progress?.lines);
        return drawResult(job.progress || {}, 'tlFill', 'tlStatus');
      },
      job => {
        $('tlStop').hidden = true;
        buttons.forEach(id => { $(id).disabled = false; });
        tlBar(!job.error);
        if(job.error){ showError(job.error, $('tlDone')); return; }
        const said = job.report || {};
        $('tlDone').textContent = tlResult(said);
      });
  }catch(err){
    showError(err.message, $('tlDone'));
    $('tlStop').hidden = true;
    buttons.forEach(id => { $(id).disabled = false; });
  }
}

/** Итог словами. Читаем бережно: формат чужой и может поменяться. */
function tlResult(said){
  const bits = [];
  for(const [key, name] of [['translated', 'переведено глав'],
                            ['failed', 'не вышло'],
                            ['terms', 'терминов в глоссарий'],
                            ['issues', 'расхождений'],
                            ['output', 'файл']]){
    if(said[key] !== undefined && said[key] !== null && said[key] !== ''){
      bits.push(`${name}: ${said[key]}`);
    }
  }
  return bits.length ? 'Готово. ' + bits.join(', ') + '.' : 'Готово.';
}

$('tlGlossary').onclick = () => tlRun('glossary');
$('tlTranslate').onclick = () => tlRun('translate');
$('tlConsistency').onclick = () => tlRun('consistency');
$('tlBuild').onclick = () => tlRun('build', {output: $('tlOut').value.trim()});
$('tlStop').onclick = () => stopJob(tlJob);

/* ------------------------------------------------- счётчик трафика
 *
 * При платном пакете это первое, что хочется видеть. Считает сервер — в
 * одном месте, через которое проходят и главы, и рейтинги, и перевод.
 */

async function trLoad(){
  try{
    const got = await call('/api/traffic');
    $('trSession').textContent = weigh(got.session);
    $('trMonth').textContent = weigh(got.month);
    $('trMonthName').textContent = got.month_name || 'месяц';
    // Без файла месячный итог живёт только в памяти — врать не надо.
    $('trMonth').title = got.kept
      ? 'Считается с первого числа этого месяца.'
      : 'Месячный итог не сохраняется: программа запущена без папки данных.';
  }catch(err){
    $('trSession').textContent = $('trMonth').textContent = '—';
  }
}

$('trAgain').onclick = trLoad;
// Обновляем при заходе на вкладку: цифра, показанная час назад, врёт.
document.querySelector('.tabs button[data-tab="tools"]')
  ?.addEventListener('click', trLoad);
trLoad();

/* ============== Статистика книги, шапка и подпись ============== */

/** Число с разделителями разрядов: «1 578» читается, «1578» — хуже. */
function ru(value){
  return Number(value || 0).toLocaleString('ru');
}

async function stStart(){
  showError('');
  const targets = rpTargets();
  if(!targets.length){ showError('Сначала выберите файлы или папку'); return; }

  $('stStart').disabled = true;
  $('stNote').innerHTML = '<span class="spin"></span>Считаем…';
  try{
    const data = await call('/api/stats', {targets});
    if(!data.chapters){
      $('stNote').textContent = 'Глав не нашлось.';
      return;
    }

    $('stNote').textContent = `Время чтения: примерно ${data.reading_time}.`;
    const numbers = $('stNumbers');
    numbers.hidden = false;
    numbers.innerHTML = '';
    for(const [name, value] of [
      ['глав', ru(data.chapters)],
      ['символов', ru(data.characters)],
      ['слов', ru(data.words)],
      ['абзацев', ru(data.paragraphs)],
      ['среднее на главу', ru(data.average)],
      ['медиана', ru(data.median)],
    ]){
      const span = document.createElement('span');
      span.innerHTML = `${name} <b>${value}</b>`;
      numbers.append(span);
    }

    $('stEdges').textContent =
      `Самая короткая: ${data.shortest.label || data.shortest.title} `
      + `(${ru(data.shortest.characters)} симв.). `
      + `Самая длинная: ${data.longest.label || data.longest.title} `
      + `(${ru(data.longest.characters)} симв.).`;

    stChart(data.buckets || []);
  }catch(err){
    showError(err.message);
    $('stNote').textContent = '';
  }finally{
    $('stStart').disabled = false;
  }
}

/** Столбики распределения объёма: видно, какие главы стоит поделить. */
function stChart(buckets){
  const box = $('stChart');
  box.innerHTML = '';
  if(!buckets.length){ box.hidden = true; return; }

  box.hidden = false;
  const chart = document.createElement('div');
  chart.className = 'chart';
  const peak = Math.max(...buckets.map(b => b.characters)) || 1;

  for(const bucket of buckets){
    const bar = document.createElement('i');
    bar.style.height = Math.max(3, Math.round(bucket.characters / peak * 100)) + '%';
    bar.title = bucket.from === bucket.to
      ? `Глава ${bucket.from}: ${ru(bucket.characters)} симв.`
      : `Главы ${bucket.from}–${bucket.to}: в среднем ${ru(bucket.characters)} симв.`;
    chart.append(bar);
  }
  box.append(chart);
}

/* ------------------------------------------------ шапка и подпись */

function sgTemplate(){
  return {head: $('sgHead').value, foot: $('sgFoot').value,
          skip_edges: $('sgEdges').checked};
}

async function sgPreview(){
  showError('');
  const targets = rpTargets();
  if(!targets.length){ showError('Сначала выберите файлы или папку'); return; }

  try{
    const data = await call('/api/signature/preview',
      {targets, template: sgTemplate()});
    $('sgNote').textContent =
      `Пример на главе «${data.chapter}», всего глав ${data.total}.`;

    const box = $('sgSample');
    box.hidden = false;
    box.innerHTML = '';
    const head = new Set(data.head), foot = new Set(data.foot);
    for(const line of data.paragraphs){
      const row = document.createElement('div');
      // Дописанное выделяем — видно, что именно добавится.
      row.className = 'ln ' + (head.has(line) || foot.has(line) ? 'added' : 'same');
      row.textContent = line;
      box.append(row);
    }
  }catch(err){
    showError(err.message);
    $('sgSample').hidden = true;
  }
}

async function sgStart(){
  showError('');
  // Свои поля, а не из блока замены: тот скрыт, пока не сделан
  // предпросмотр, и отсылать к невидимому полю нельзя.
  if(!$('sgBase').value.trim()){ showError('Укажите, куда сохранить копию'); return; }
  if(!rpTargets().length){ showError('Сначала выберите файлы или папку'); return; }

  $('sgStart').disabled = true;
  try{
    const {job} = await call('/api/signature/start', {
      targets: rpTargets(),
      template: sgTemplate(),
      base: $('sgBase').value.trim(),
      folder: ($('sgFolder').value.trim() || 'С подписью'),
    });
    $('sgProgress').hidden = false;
    $('sgNote').textContent = 'Пишем в: ' + job.output_dir;

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('sgWritten').textContent = p.written || p.done || 0;
        return drawResult(p, 'sgFill', 'sgStatus', 'sgPct');
      },
      job => {
        if(job.error){ showError(job.error, $('sgProgress')); return; }
        const r = job.report || {};
        $('sgNote').textContent =
          `Готово. Записано ${r.written} из ${r.total}. Папка: ${r.output}`;
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('sgStart').disabled = false;
  }
}

/* =============== Читалка и очередь задач (4.4 и 4.6) ===============
 *
 * Читалка показывает главу в том оформлении, в каком она уйдёт в файл, —
 * иначе смотреть в ней было бы бессмысленно. Очередь склеивает операции
 * в цепочку: папка результата одного шага становится входом следующего.
 */

let rdPage = null, rdList = [], rdMenu = null;

function rdKinds(){
  // Список проверок берём тот же, что отмечен на вкладке «Проверка»:
  // подсвечивать в читалке то, что человек проверять не просил, незачем.
  return $('rdMarks').checked ? (ckSelected ? ckSelected() : null) : [];
}

async function rdOpen(index){
  showError('');
  const targets = rpTargets();
  if(!targets.length){ showError('Сначала выберите файлы или папку'); return; }

  $('rdOpen').disabled = true;
  try{
    if(!rdList.length || index === undefined){
      const data = await call('/api/reader/list', {targets});
      rdList = data.chapters || [];
      if(!rdList.length){ showError('Глав не нашлось'); return; }
      rdFillPick();
    }
    const page = await call('/api/reader/open',
      {targets, index: index || 0, kinds: rdKinds()});
    rdShow(page);
    $('rdBox').hidden = false;
  }catch(err){
    showError(err.message);
  }finally{
    $('rdOpen').disabled = false;
  }
}

function rdFillPick(){
  // Список глав приходит с сервера, поэтому меню пересобирается целиком —
  // тем же способом, что и список моделей.
  const box = $('rdPick');
  box.dataset.options = JSON.stringify(rdList.map(chapter => [
    String(chapter.index),
    chapter.title || chapter.label || `Глава ${chapter.index + 1}`,
  ]));
  box.innerHTML = '';
  rdMenu = makeDropdown(box, value => rdOpen(Number(value)));
}

function rdShow(page){
  rdPage = page;
  if(rdMenu) rdMenu.set(String(page.index));
  $('rdPrev').disabled = !page.has_prev;
  $('rdNext').disabled = !page.has_next;
  $('rdNote').textContent =
    `Глава ${page.index + 1} из ${page.total}. Абзацев ${page.paragraphs.length}.`
    + (page.findings.length ? ` Находок проверки: ${page.findings.length}.` : '');

  // Абзац с находкой подсвечивается целиком: точное место всё равно видно
  // по тексту, а подсветка внутри абзаца ломалась бы на подготовке.
  const marked = new Set(page.findings.map(f => (f.context || '').trim()));
  const box = $('rdText');
  box.innerHTML = '';
  for(const paragraph of page.paragraphs){
    const row = document.createElement('p');
    if(marked.has(paragraph.trim())) row.className = 'mark';
    row.textContent = paragraph;
    box.append(row);
  }
  rdEditMode(false);
}

function rdEditMode(on){
  $('rdText').hidden = on;
  $('rdEdit').hidden = !on;
  $('rdEditBtn').hidden = on;
  $('rdSave').hidden = !on;
  $('rdCancel').hidden = !on;
  if(on) $('rdEdit').value = rdPage ? rdPage.text : '';
}

async function rdSave(){
  showError('');
  if(!rdPage) return;
  if(!confirm('Правка запишется поверх файла ' + rdPage.source
              + '\n\nКопия уйдёт в корзину. Продолжить?')) return;

  $('rdSave').disabled = true;
  try{
    const data = await call('/api/reader/save',
      {source: rdPage.source, text: $('rdEdit').value});
    // Сначала перечитываем главу, потом пишем итог: иначе перечитывание
    // затирает сообщение и человек не видит, сохранилось ли что-нибудь.
    await rdOpen(rdPage.index);
    $('rdNote').textContent =
      `Сохранено: ${data.saved}. Абзацев ${data.paragraphs}.`
      + (data.backup ? ' Копия в корзине.' : '');
  }catch(err){
    showError(err.message);
  }finally{
    $('rdSave').disabled = false;
  }
}

$('rdOpen').onclick = () => { rdList = []; rdOpen(0); };
$('rdPrev').onclick = () => rdPage && rdPage.has_prev && rdOpen(rdPage.index - 1);
$('rdNext').onclick = () => rdPage && rdPage.has_next && rdOpen(rdPage.index + 1);
$('rdEditBtn').onclick = () => rdEditMode(true);
$('rdCancel').onclick = () => rdEditMode(false);
$('rdSave').onclick = rdSave;

/* ------------------------------------------------------ орфография */

let orfJob = null, orfFindings = [];

async function orfStart(){
  showError('');
  const targets = rpTargets();
  if(!targets.length){ showError('Сначала выберите файлы или папку'); return; }

  $('orfStart').disabled = true;
  $('orfNote').innerHTML = '<span class="spin"></span>Читаем словарь…';
  if(typeof fxSkeleton === 'function') fxSkeleton('orfFindings', 6);
  try{
    const {job} = await call('/api/spelling/start',
      {targets, use_registry: $('orfReg').checked});
    orfJob = job.id;
    ownJob('tools', job.id);
    $('orfProgress').hidden = false;
    $('orfStop').hidden = false;

    pollJob(job.id,
      job => drawResult(job.progress || {}, 'orfFill', 'orfStatus', null),
      job => {
        $('orfStop').hidden = true;
        dropJob('tools');
        orfJob = null;
        if(job.error){ showError(job.error, $('orfNote')); $('orfNote').textContent = ''; return; }
        orfRender(job.report || {});
      });
  }catch(err){
    // Пакет не поставлен — это не поломка, а недостающий словарь.
    showError(err.message);
    $('orfNote').textContent = '';
    $('orfProgress').hidden = true;
  }finally{
    $('orfStart').disabled = false;
  }
}

function orfRender(report){
  orfFindings = report.findings || [];
  $('orfNote').textContent =
    `Незнакомых слов ${report.total} на ${ru(report.words)} слов текста`
    + `, глав ${report.chapters}. В словаре книги и реестре: ${report.known}.`
    + (report.total > report.shown ? ` Показаны первые ${report.shown}.` : '');

  const box = $('orfFindings');
  box.innerHTML = '';
  if(!orfFindings.length){
    box.innerHTML = '<div class="tr"><span class="grow hint">'
      + 'Незнакомых слов не нашлось.</span></div>';
    return;
  }

  for(const finding of orfFindings){
    const row = document.createElement('div');
    row.className = 'tr';

    const word = document.createElement('b');
    word.textContent = finding.word;
    row.append(word);

    const count = document.createElement('span');
    count.className = 'num';
    count.textContent = `×${finding.count}`;
    row.append(count);

    const quote = document.createElement('span');
    quote.className = 'grow';
    quote.title = finding.quote;
    quote.textContent = finding.quote;
    row.append(quote);

    if(finding.suggestions.length){
      const hint = document.createElement('span');
      hint.className = 'tag';
      hint.textContent = finding.suggestions.join(', ');
      row.append(hint);
    }

    const known = document.createElement('button');
    known.className = 'ghost';
    known.textContent = 'это имя';
    known.title = 'Внести в словарь книги — больше не спрашивать';
    known.style.padding = '4px 10px';
    known.onclick = () => orfKnown(finding, row);
    row.append(known);

    const open = document.createElement('button');
    open.className = 'ghost';
    open.textContent = 'открыть';
    open.style.padding = '4px 10px';
    open.onclick = () => call('/api/open', {path: finding.path})
      .catch(err => showError(err.message));
    row.append(open);

    box.append(row);
  }
}

async function orfKnown(finding, row){
  try{
    const data = await call('/api/spelling/known',
      {targets: rpTargets(), words: [finding.word]});
    // Строка убирается сразу: вернуть её можно повторной проверкой, а
    // держать на экране слово, которое уже признано именем, незачем.
    row.remove();
    $('orfNote').textContent =
      `«${finding.word}» внесено в словарь книги. Всего своих слов: ${data.count}.`;
  }catch(err){ showError(err.message); }
}

$('orfStart').onclick = orfStart;
$('orfStop').onclick = () => orfJob && stopJob(orfJob);

/* ---------------------------------------------------- очередь задач */

let qSteps = [], qKinds = [], qJob = null, qKindMenu = null, qSavedMenu = null;

async function qLoadState(){
  try{
    const data = await call('/api/queue/state');
    qKinds = data.kinds || [];

    const kind = $('qKind');
    kind.dataset.options = JSON.stringify(qKinds.map(i => [i.key, i.name]));
    kind.innerHTML = '';
    qKindMenu = makeDropdown(kind);

    const saved = $('qSaved');
    saved.dataset.options = JSON.stringify(
      [['', '— сохранённые очереди —']].concat(
        (data.queues || []).map(q => [q.name, `${q.name} (шагов ${q.total})`])));
    saved.innerHTML = '';
    qSavedMenu = makeDropdown(saved);
    return data;
  }catch(err){ showError(err.message); return {queues: []}; }
}

function qKindName(key){
  const found = qKinds.find(k => k.key === key);
  return found ? found.name : key;
}

/** Какие поля нужны шагу. Спрашиваем только их: лишние поля мешают. */
function qNeedsOutput(kind){
  // Проверки ничего не пишут — папка результата им не нужна.
  return !['check', 'spelling', 'stats'].includes(kind);
}

function qRender(){
  const box = $('qSteps');
  box.innerHTML = '';
  if(!qSteps.length){
    box.innerHTML = '<div class="tr"><span class="grow hint">'
      + 'Шагов пока нет. Добавьте первый — он возьмёт на вход то, '
      + 'что указано выше.</span></div>';
    return;
  }

  qSteps.forEach((step, index) => {
    const row = document.createElement('div');
    row.className = 'tr ' + (step.state || 'waiting');

    const dot = document.createElement('span');
    dot.className = 'dot';
    row.append(dot);

    const name = document.createElement('span');
    name.className = 'num';
    name.textContent = `${index + 1}.`;
    row.append(name);

    const title = document.createElement('span');
    title.className = 'grow';
    title.textContent = step.title || qKindName(step.kind);
    row.append(title);

    if(qNeedsOutput(step.kind)){
      const base = document.createElement('input');
      base.type = 'text';
      base.className = 'rowname';
      base.placeholder = 'куда сохранить';
      base.value = step.params.base || '';
      base.oninput = () => { step.params.base = base.value.trim(); };
      base.style.flex = '1';
      row.append(base);

      const folder = document.createElement('input');
      folder.type = 'text';
      folder.className = 'rowname';
      folder.placeholder = 'имя папки';
      folder.value = step.params.folder || '';
      folder.oninput = () => { step.params.folder = folder.value.trim(); };
      row.append(folder);
    }

    const up = document.createElement('button');
    up.className = 'ghost';
    up.textContent = '↑';
    up.title = 'Выше';
    up.style.padding = '4px 9px';
    up.onclick = () => qMove(index, -1);
    row.append(up);

    const drop = document.createElement('button');
    drop.className = 'ghost';
    drop.textContent = '✕';
    drop.title = 'Убрать шаг';
    drop.style.padding = '4px 9px';
    drop.onclick = () => { qSteps.splice(index, 1); qRender(); };
    row.append(drop);

    if(step.message){
      const said = document.createElement('span');
      said.className = 'said';
      said.textContent = step.message;
      row.append(said);
    }
    box.append(row);
  });
}

function qMove(index, shift){
  const to = index + shift;
  if(to < 0 || to >= qSteps.length) return;
  [qSteps[index], qSteps[to]] = [qSteps[to], qSteps[index]];
  qRender();
}

function qAdd(){
  const kind = qKindMenu ? qKindMenu.value : '';
  if(!kind) return;
  qSteps.push({kind, params: {}, title: qKindName(kind), state: 'waiting',
               message: ''});
  qRender();
}

function qPayload(){
  return {name: $('qName').value.trim(), steps: qSteps};
}

async function qSave(){
  showError('');
  if(!$('qName').value.trim()){ showError('Дайте очереди имя'); return; }
  if(!qSteps.length){ showError('В очереди нет ни одного шага'); return; }
  try{
    await call('/api/queue/save', {queue: qPayload()});
    await qLoadState();
    if(qSavedMenu) qSavedMenu.set($('qName').value.trim());
    $('qNote').textContent = 'Очередь сохранена — её можно запускать снова.';
  }catch(err){ showError(err.message); }
}

async function qLoad(){
  const name = qSavedMenu ? qSavedMenu.value : '';
  if(!name) return;
  const data = await qLoadState();
  const queue = (data.queues || []).find(q => q.name === name);
  if(!queue) return;
  $('qName').value = queue.name;
  qSteps = queue.steps.map(s => ({...s, params: {...s.params}}));
  qRender();
}

async function qDrop(){
  const name = qSavedMenu ? qSavedMenu.value : '';
  if(!name) return;
  try{
    await call('/api/queue/remove', {name});
    await qLoadState();
    $('qNote').textContent = `Очередь «${name}» удалена.`;
  }catch(err){ showError(err.message); }
}

async function qRun(){
  showError('');
  if(!qSteps.length){ showError('В очереди нет ни одного шага'); return; }

  $('qRun').disabled = true;
  try{
    const {job} = await call('/api/queue/start', {
      queue: qPayload(),
      start_from: $('qStart').value.trim(),
    });
    qJob = job.id;
    ownJob('tools', job.id);
    $('qProgress').hidden = false;
    $('qStop').hidden = false;

    pollJob(job.id,
      job => {
        const progress = job.progress || {};
        if(progress.queue){ qSteps = progress.queue.steps; qRender(); }
        return drawResult(progress, 'qFill', 'qStatus', null);
      },
      job => {
        $('qStop').hidden = true;
        dropJob('tools');
        qJob = null;
        if(job.error){ showError(job.error, $('qStop')); return; }
        const report = job.report || {};
        if(report.steps){ qSteps = report.steps; qRender(); }
        $('qNote').textContent = job.progress.message || '';
      });
  }catch(err){
    showError(err.message);
    $('qStop').hidden = true;
  }finally{
    $('qRun').disabled = false;
  }
}

$('qAdd').onclick = qAdd;
$('qSave').onclick = qSave;
$('qLoad').onclick = qLoad;
$('qDrop').onclick = qDrop;
$('qRun').onclick = qRun;
$('qStop').onclick = () => qJob && stopJob(qJob);
qRender();
qLoadState();


$('stStart').onclick = stStart;
$('sgPreview').onclick = sgPreview;
$('sgStart').onclick = sgStart;

/* ========================== Проверка текста ========================== */

let ckJob = null, ckFindings = [], ckFilter = null, ckCleanJob = null;
//: Замеренная высота строки таблицы и защита от зацикливания перерисовки.
let ckRowHeight = 0, drawPasses = 0;

/** Строит галочки проверок по группам и кнопки пресетов. */
async function ckBuildChecks(){
  let data;
  try{
    data = await call('/api/check/rules');
  }catch(err){
    showError(err.message);
    return;
  }

  const box = $('ckKinds');
  box.innerHTML = '';
  for(const group of data.groups){
    const wrap = document.createElement('div');
    wrap.className = 'check-group';

    const head = document.createElement('div');
    head.className = 'check-group-head';
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = group.title;

    const all = document.createElement('button');
    all.className = 'ghost';
    all.textContent = 'Отметить все';
    const none = document.createElement('button');
    none.className = 'ghost';
    none.textContent = 'Снять все';

    head.append(name, all, none);
    wrap.append(head);

    const checks = document.createElement('div');
    checks.className = 'checks';
    for(const rule of group.rules){
      const label = document.createElement('label');
      label.className = 'chk';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = rule.key;
      input.checked = true;
      label.append(input, document.createTextNode(' ' + rule.name));
      // Подсказка при наведении: что ищется и почему это важно.
      attachTip(label, rule.tip);
      checks.append(label);
    }
    all.onclick = () => checks.querySelectorAll('input').forEach(i => { i.checked = true; });
    none.onclick = () => checks.querySelectorAll('input').forEach(i => { i.checked = false; });

    wrap.append(checks);
    box.append(wrap);
  }

  const presets = $('ckPresets');
  presets.innerHTML = '';
  for(const preset of data.presets){
    const chip = document.createElement('button');
    chip.className = 'chip';
    chip.textContent = preset.name;
    chip.onclick = () => {
      const wanted = new Set(preset.kinds);
      box.querySelectorAll('input').forEach(i => { i.checked = wanted.has(i.value); });
      presets.querySelectorAll('.chip').forEach(c => c.classList.remove('on'));
      chip.classList.add('on');
    };
    presets.append(chip);
  }

  // Пункты очистки — оттуда же, чтобы список не расходился с сервером.
  const clean = $('ckCleanKinds');
  clean.innerHTML = '';
  for(const kind of data.clean_kinds){
    const label = document.createElement('label');
    label.className = 'chk';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = kind.key;
    input.checked = true;
    label.append(input, document.createTextNode(' ' + kind.name));
    clean.append(label);
  }
}

ckBuildChecks();

function ckSelected(){
  return [...$('ckKinds').querySelectorAll('input:checked')].map(i => i.value);
}

function ckCleanSelected(){
  return [...$('ckCleanKinds').querySelectorAll('input:checked')].map(i => i.value);
}

async function ckStart(){
  showError('');
  const targets = CHOSEN.ckList || [];
  if(!targets.length){ showError('Сначала выберите файлы или папку'); return; }
  const kinds = ckSelected();
  if(!kinds.length){ showError('Отметьте хотя бы одну проверку'); return; }

  $('ckStart').disabled = true;
  ckFilter = null;
  $('ckSearch').value = '';
  try{
    const {job} = await call('/api/check/start', {targets, kinds});
    ckJob = job.id;
    ownJob('check', job.id);
    $('ckProgress').hidden = false;
    $('ckStop').hidden = false;
    $('ckSave').hidden = true;

    pollJob(job.id,
      job => drawResult(job.progress || {}, 'ckFill', 'ckStatus'),
      job => {
        $('ckStop').hidden = true;
        if(job.error){ showError(job.error, $('ckStop')); return; }
        if(job.report){
          $('ckSave').hidden = false;
          ckRender(job.report);
        }
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('ckStart').disabled = false;
  }
}

function ckRender(report){
  ckFindings = report.findings;

  const summary = $('ckSummary');
  summary.innerHTML = '';
  for(const row of report.summary){
    const chip = document.createElement('button');
    chip.className = 'chip';
    chip.innerHTML = `${row.kind_name} <b>${row.count}</b>`;
    chip.onclick = () => {
      // Повторный клик снимает фильтр.
      ckFilter = ckFilter === row.kind ? null : row.kind;
      summary.querySelectorAll('.chip').forEach(c => c.classList.remove('on'));
      if(ckFilter) chip.classList.add('on');
      ckRenderTable();
    };
    summary.append(chip);
  }
  $('ckSummaryCard').hidden = !report.summary.length;

  const words = $('ckWords');
  words.innerHTML = '';
  for(const row of report.latin_words){
    const line = document.createElement('div');
    line.className = 'tr';
    const word = document.createElement('span');
    word.className = 'grow';
    word.textContent = row.word;
    const count = document.createElement('span');
    count.className = 'num';
    count.textContent = '×' + row.count;
    line.append(word, count);
    words.append(line);
  }
  $('ckWordsCard').hidden = !report.latin_words.length;

  // Сначала показываем карточку, потом рисуем: у скрытого блока высота
  // равна нулю, и замер строки не срабатывает.
  $('ckResults').hidden = false;
  $('ckCleanCard').hidden = false;
  ckRenderTable();
}

/** Все находки доступны в самом окне — без обрезки, список виртуальный. */
function ckRenderTable(){
  const needle = $('ckSearch').value.trim().toLowerCase();
  let rows = ckFilter ? ckFindings.filter(f => f.kind === ckFilter) : ckFindings;
  if(needle){
    rows = rows.filter(f =>
      (f.context || f.fragment).toLowerCase().includes(needle) ||
      f.file.toLowerCase().includes(needle));
  }
  $('ckCount').textContent = `— ${rows.length}` +
    (rows.length !== ckFindings.length ? ` из ${ckFindings.length}` : '');

  const table = $('ckTable');
  table.innerHTML = '';
  table.onscroll = null;

  // Виртуальный список: в DOM держим только видимую часть, поэтому даже
  // 30 тысяч находок открываются без обрезки и без подвисаний.
  // Высоту строки не зашиваем — при другом шрифте или масштабе она другая,
  // и строки начинают наезжать друг на друга. Меряем по факту.
  let ROW = ckRowHeight || 31;
  const spacer = document.createElement('div');
  spacer.style.height = rows.length * ROW + 'px';
  spacer.style.position = 'relative';
  spacer.style.minWidth = 'min-content';
  table.append(spacer);

  // Развёрнутых строк немного, поэтому их добавочную высоту держим
  // отдельно и учитываем в раскладке — иначе они наезжают на соседей.
  const opened = new Set();
  const extra = new Map();

  function offsetOf(index){
    let shift = 0;
    for(const [i, value] of extra){
      if(i < index) shift += value;
    }
    return index * ROW + shift;
  }

  function totalHeight(){
    let sum = rows.length * ROW;
    for(const value of extra.values()) sum += value;
    return sum;
  }

  function draw(){
    spacer.style.height = totalHeight() + 'px';
    const top = table.scrollTop;
    const height = table.clientHeight || 400;

    // Границы окна ищем по фактическим смещениям: строки разной высоты.
    let first = 0;
    while(first < rows.length && offsetOf(first + 1) < top) first++;
    let last = first;
    while(last < rows.length && offsetOf(last) < top + height) last++;
    first = Math.max(0, first - 3);
    last = Math.min(rows.length, last + 3);

    spacer.innerHTML = '';
    const drawn = [];
    for(let i = first; i < last; i++){
      const node = buildRow(rows[i], i);
      node.style.top = offsetOf(i) + 'px';
      spacer.append(node);
      drawn.push([i, node]);
    }

    let changed = false;

    // Сначала уточняем высоту обычной строки — от неё считается вся раскладка.
    const plain = drawn.find(([i]) => !opened.has(i));
    if(plain){
      const measured = plain[1].offsetHeight;
      if(measured > 0 && Math.abs(measured - ROW) > 1){
        ROW = measured;
        ckRowHeight = measured;
        changed = true;
      }
    }

    // Затем добавочную высоту развёрнутых.
    for(const [i, node] of drawn){
      if(!opened.has(i)) continue;
      const value = Math.max(0, node.offsetHeight - ROW);
      if(Math.abs((extra.get(i) || 0) - value) > 1){
        extra.set(i, value);
        changed = true;
      }
    }
    if(changed && drawPasses < 4){
      drawPasses++;
      draw();
    }else{
      drawPasses = 0;
    }
  }

  function buildRow(finding, index){
    const line = document.createElement('div');
    line.className = 'tr' + (opened.has(index) ? ' open' : '');
    line.style.position = 'absolute';
    line.style.left = '0';
    line.style.right = '0';
    if(opened.has(index)) line.style.flexWrap = 'wrap';

    const file = document.createElement('span');
    file.className = 'fname';
    file.textContent = finding.file;
    file.title = finding.file;   // полное имя в подсказке

    const lineNo = document.createElement('span');
    lineNo.className = 'num';
    lineNo.textContent = 'стр. ' + finding.line;

    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = finding.kind_name;

    const text = document.createElement('span');
    text.className = 'ftext';
    text.textContent = finding.fragment;
    text.title = finding.context || finding.fragment;  // полный текст в подсказке

    line.append(file, lineNo, tag, text);

    if(opened.has(index)){
      // Одиночный клик разворачивает строку и показывает абзац целиком.
      const full = document.createElement('div');
      full.className = 'full';
      full.textContent = finding.context || finding.fragment;

      const row = document.createElement('div');
      row.className = 'row';

      const copy = document.createElement('button');
      copy.className = 'ghost';
      copy.textContent = 'Скопировать фрагмент';
      copy.onclick = async e => {
        e.stopPropagation();
        const value = finding.context || finding.fragment;
        try{
          await navigator.clipboard.writeText(value);
          copy.textContent = 'Скопировано';
        }catch(err){
          // Буфер может быть закрыт политикой браузера — выделим текст сам.
          const range = document.createRange();
          range.selectNodeContents(full);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          copy.textContent = 'Выделено, нажмите Ctrl+C';
        }
        setTimeout(() => { copy.textContent = 'Скопировать фрагмент'; }, 2500);
      };

      const open = document.createElement('button');
      open.className = 'ghost';
      open.textContent = 'Открыть файл';
      open.onclick = e => { e.stopPropagation(); openFinding(finding); };

      row.append(copy, open);
      full.append(row);
      line.append(full);
      // Развёрнутая строка выше обычной — сдвигаем последующие.
      line.style.zIndex = '2';
      line.style.background = '#12101a';
    }

    line.onclick = () => {
      if(opened.has(index)){
        opened.delete(index);
        extra.delete(index);
      }else{
        opened.add(index);
      }
      draw();
    };
    // Двойной клик открывает файл в программе по умолчанию.
    line.ondblclick = e => { e.stopPropagation(); openFinding(finding); };

    return line;
  }

  table.onscroll = draw;
  draw();
}

/** Открывает файл находки в Word, редакторе — чем система умеет. */
async function openFinding(finding){
  if(!finding.path){ showError('Путь к файлу неизвестен'); return; }
  try{
    await call('/api/open', {path: finding.path});
  }catch(err){
    showError(err.message);
  }
}

/* ------------------------------------------------------------ очистка */

async function ckCleanPreview(){
  showError('');
  const targets = CHOSEN.ckList || [];
  if(!targets.length){ showError('Сначала выберите файлы или папку'); return; }

  $('ckCleanPreview').disabled = true;
  try{
    const data = await call('/api/clean/preview', {targets, kinds: ckCleanSelected()});
    const table = $('ckCleanCounts');
    table.innerHTML = '';
    for(const row of data.counts){
      const line = document.createElement('div');
      line.className = 'tr';
      const name = document.createElement('span');
      name.className = 'grow';
      name.textContent = row.kind_name;
      const count = document.createElement('span');
      count.className = 'num';
      count.textContent = row.count;
      line.append(name, count);
      table.append(line);
    }
    table.hidden = false;
    $('ckCleanResult').textContent = `Будет исправлено мест: ${data.total}. ` +
      'Оригиналы не изменятся.';
  }catch(err){
    showError(err.message);
  }finally{
    $('ckCleanPreview').disabled = false;
  }
}

async function ckClean(){
  showError('');
  const targets = CHOSEN.ckList || [];
  if(!targets.length){ showError('Сначала выберите файлы или папку'); return; }

  $('ckClean').disabled = true;
  try{
    const {job} = await call('/api/clean/start', {
      targets,
      kinds: ckCleanSelected(),
      base: $('ckBase').value.trim(),
      folder: $('ckOut').value.trim(),
    });
    ckCleanJob = job.id;
    ownJob('check', job.id);
    $('ckCleanResultBox').hidden = false;

    pollJob(job.id,
      job => drawResult(job.progress || {}, 'ckCleanFill', 'ckCleanStatus'),
      job => {
        if(job.error){ showError(job.error, $('ckCleanResultBox')); return; }
        const report = job.report || {};
        // Отчёт: что и сколько исправлено.
        const parts = (report.counts || []).map(r => `${r.kind_name}: ${r.count}`);
        $('ckCleanResult').textContent =
          `Папка: ${report.output_dir}\n` +
          `Файлов: ${report.written}, исправлено мест: ${report.total}\n` +
          parts.join('\n');
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('ckClean').disabled = false;
  }
}

$('ckStart').onclick = ckStart;
$('ckStop').onclick = () => stopJob(ckCleanJob || ckJob);
$('ckSave').onclick = () => { window.location = '/api/check/' + ckJob + '/report'; };
$('ckSearch').addEventListener('input', ckRenderTable);
$('ckCleanPreview').onclick = ckCleanPreview;
$('ckClean').onclick = ckClean;

/* ------------------------------------------- осмотр: всё ли на месте
 *
 * Отдельно от «Проверить» намеренно: там разбор текста по двум десяткам
 * правил, здесь — один вопрос, можно ли книгу выкладывать. Подписи
 * находок приходят с сервера вместе с отчётом: список родов закрытый и
 * живёт в `ops/checkup`, и держать его вторым экземпляром здесь значило
 * бы однажды разойтись — находка есть, а называть её нечем.
 */

let cuJob = null;

async function cuStart(targets){
  showError('');
  targets = targets || CHOSEN.ckList || [];
  if(!targets.length){ showError('Сначала выберите папку книги'); return; }

  $('cuStart').disabled = true;
  try{
    const {job} = await call('/api/checkup/start', {targets});
    cuJob = job.id;
    ownJob('check', job.id);
    $('cuBox').hidden = false;
    $('cuStop').hidden = false;
    $('cuFound').hidden = true;
    // Сразу рисуем свой прогресс: иначе в блоке до первого опроса висит
    // «Готово» от прошлого осмотра.
    drawResult(job.progress || {}, 'cuFill', 'cuStatus');

    pollJob(job.id,
      job => drawResult(job.progress || {}, 'cuFill', 'cuStatus'),
      job => {
        $('cuStop').hidden = true;
        if(job.error){ showError(job.error, $('cuCard')); return; }
        cuShow(job.report || {});
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('cuStart').disabled = false;
  }
}

/** Находки осмотра — списком. Общая на оба осмотра: подписи и порядок
 *  приходят с сервера, и рисовать их двумя способами не за чем. */
function cuShow(report, boxId){
  const box = $(boxId || 'cuFound');
  box.innerHTML = '';
  const troubles = report.troubles || [];
  if(!troubles.length){ box.hidden = true; return; }

  for(const trouble of troubles){
    const row = document.createElement('div');
    row.className = 'tr';

    const name = document.createElement('span');
    name.className = 'grow' + (trouble.hole ? ' cu-hole' : '');
    name.textContent = trouble.kind_name
      + (trouble.detail ? ' — ' + trouble.detail : '');
    name.title = name.textContent;

    const count = document.createElement('span');
    count.className = 'num';
    count.textContent = trouble.count;
    row.append(name, count);
    box.append(row);

    const where = document.createElement('div');
    // Класс общий, «приглушённый»: карточка подсвечивает свой текст
    // целиком, и своя копия того же цвета из подсветки бы выпала.
    where.className = 'hint';
    where.style.margin = '2px 10px 8px';
    where.textContent = (trouble.where || []).join(' · ')
      + (trouble.more ? ` … и ещё ${trouble.more}` : '');
    box.append(where);
  }
  box.hidden = false;
}

$('cuStart').onclick = () => cuStart();
$('cuStop').onclick = () => stopJob(cuJob);

/* --------------------------------------- каких глав нет: по одним именам
 *
 * Проверка нумерации в готовой книге говорит «под номером 303 глав
 * меньше, чем у соседей», и дальше человек остаётся один на один с
 * папкой в несколько сотен файлов. Здесь тот же вопрос задаётся самой
 * папке, и ответ выходит точный: «нет 303.1».
 *
 * Задачей не делаем: файлы не читаются вовсе, ответ приходит сразу.
 */

async function mnStart(){
  showError('');
  const targets = CHOSEN.ckList || [];
  if(!targets.length){ showError('Сначала выберите папку с главами'); return; }

  $('mnStart').disabled = true;
  try{
    const {report} = await call('/api/checkup/names', {targets});
    $('mnBox').hidden = false;
    $('mnStatus').textContent = report.summary;
    cuShow(report, 'mnFound');
  }catch(err){
    showError(err.message, $('mnCard'));
  }finally{
    $('mnStart').disabled = false;
  }
}

$('mnStart').onclick = () => mnStart();

// Раздел 3: свои стрелки у всех числовых полей приложения.
addSpinners();

/* ================= Таймеры операций (2.1 и 2.2) =================
 *
 * Полоса внизу оказалась неудачной: при прокрутке содержимое уезжало под
 * неё, а в покое она сообщала бесполезное «8 прокси» на каждой вкладке.
 * Теперь время стоит там, где на него и смотрят, — рядом с прогресс-баром
 * и счётчиками той операции, к которой оно относится.
 *
 * Секундомер считает сервер: перезагрузка вкладки не должна его сбивать.
 * Прогноз — здесь, по последним замерам: средняя с начала врёт в начале
 * работы и устаревает после смены прокси.
 */

//: Сколько замеров держать для прогноза.
const ETA_SAMPLES = 20;

//: История «сколько сделано и когда» по каждой задаче.
const ETA_HISTORY = {};

function clockText(seconds){
  seconds = Math.max(0, Math.round(seconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = n => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

/** Прогноз по скорости последних элементов. Пусто — данных ещё мало. */
function etaText(jobId, done, total){
  const list = ETA_HISTORY[jobId] || (ETA_HISTORY[jobId] = []);
  const now = Date.now();
  if(!list.length || list[list.length - 1].done !== done){
    list.push({at: now, done});
    if(list.length > ETA_SAMPLES) list.shift();
  }
  if(list.length < 3 || !total || done >= total) return '';

  const first = list[0];
  const seconds = (now - first.at) / 1000;
  const made = done - first.done;
  // Пока не сделано ни одного шага, прогнозировать нечего: прочерк
  // честнее выдуманного числа.
  if(seconds <= 0 || made <= 0) return '';
  return clockText((total - done) / (made / seconds));
}

/** Строка «3 потока · 3 прокси» — только если многопоточность включилась.
 *
 *  В один поток строки нет вовсе: сообщать «1 поток» незачем, а показывать
 *  число прокси там, где сеть не используется, — тем более.
 */
function modeText(progress){
  const threads = Number(progress.threads || 0);
  if(threads < 2) return '';
  const proxies = Number(progress.proxies || 0);
  return `${threads} ${plural(threads, 'поток', 'потока', 'потоков')}`
    + (proxies ? ` · ${proxies} ${plural(proxies, 'прокси', 'прокси', 'прокси')}` : '');
}

/** Рисует таймеры блока результата. Ищет `<prefix>Timers` рядом. */
function drawTimers(statusId, job){
  const box = $(String(statusId).replace(/Status$/, '') + 'Timers');
  if(!box || !job) return;

  const progress = job.progress || {};
  const done = job.running === false || TERMINAL.includes(progress.stage);
  const parts = [];

  if(done){
    // По завершении оба таймера заменяются итогом — оставшееся время
    // после конца работы смысла не имеет.
    if(job.elapsed >= 1) parts.push(`заняло <b>${tookText(job.elapsed)}</b>`);
  }else{
    parts.push(`прошло <b>${clockText(job.elapsed || 0)}</b>`);
    const left = etaText(job.id, Number(progress.done || 0), Number(progress.total || 0));
    parts.push(`осталось <b>${left || '—'}</b>`);
  }

  const mode = modeText(progress);
  if(mode) parts.push(`<span class="mode">${mode}</span>`);
  box.innerHTML = parts.join(' · ');
}

/* ================= Источники и рейтинг Фанкью (часть 5) =================
 *
 * Источник — отдельный модуль на сервере, здесь только выбор. Меню
 * строится по ответу `/api/sources`, а не по зашитому списку: иначе новый
 * источник пришлось бы вписывать в двух местах.
 *
 * Живёт в этом файле, а не в разметке: `makeDropdown` объявлена здесь, и
 * вызывать её раньше было бы полаганием на то, что ответ сервера придёт
 * позже загрузки скрипта.
 */

/* Версии на странице нет и быть не должно.
 *
 * Её показывали дважды: сначала в подзаголовке, потом в подвале. Оба
 * раза она никому не понадобилась и оба раза мешала. Кому нужен номер —
 * тот спросит `python cli.py --version` или `GET /api/about`; в
 * интерфейсе ей места нет.
 */

async function loadSources(){
  try{
    const data = await call('/api/sources');
    const box = $('srcPick');
    if(!box) return;
    box.dataset.options = JSON.stringify(
      (data.sources || []).map(s => [s.key, s.name]));
    box.innerHTML = '';
    const show = key => {
      const found = (data.sources || []).find(s => s.key === key);
      if(!found) return;
      // И заполнитель в поле, и пояснение под ним меняются вместе с
      // источником: у Фанкью в ссылке не слаг, а числовой код.
      $('q').placeholder = found.placeholder || '';
      $('srcHint').textContent = found.hint || '';
    };
    srcMenu = makeDropdown(box, show);
    const first = (data.sources || [])[0];
    if(first) show(first.key);
  }catch(err){ /* источники не список вкладок — молча оставляем как есть */ }
}
loadSources();

/* ------------------------------------------------ рейтинг (5.2) */

let rkRows = [], rkTitles = {}, rkPicked = null;
let rkAudMenu = null, rkKindMenu = null, rkCatMenu = null, rkCats = {};
let rkSiteMenu = null, rkBoardMenu = null, rkChannelMenu = null, rkSites = [];

/** Выбранный сайт целиком, а не только его ключ. */
function rkSite(){
  const key = rkSiteMenu ? rkSiteMenu.value : '';
  return rkSites.find(s => s.key === key) || rkSites[0] || {key: '', boards: []};
}

function rkWhere(){
  const site = rkSite();
  return {
    site: site.key,
    // Доска есть только у сайтов без деления на аудиторию и жанр. Слать
    // её всегда безвредно: у Фанкью сервер её просто не читает.
    board: rkBoardMenu ? rkBoardMenu.value : '',
    // Раздел есть только там, где доска перемножается на жанр. У
    // остальных сервер его не читает — слать безвредно.
    channel: (rkChannelMenu && (rkSite().channels || []).length)
      ? rkChannelMenu.value : '',
    audience: rkAudMenu ? rkAudMenu.value : '1',
    kind: rkKindMenu ? rkKindMenu.value : '2',
    category: rkCatMenu ? rkCatMenu.value : '',
  };
}

/** Что за сайт выбран — то и показываем.
 *
 * У Фанкью рейтинг делится на аудиторию, вид и жанр; у MVLEMPYR ничего
 * этого нет, там три доски по сроку. Оставлять на экране выпадашки,
 * которые ни на что не влияют, — врать человеку.
 */
function rkApplySite(){
  const site = rkSite();
  const fanqie = !site.key;

  $('rkFanqieWhere').hidden = !fanqie;
  $('rkCategory').hidden = !fanqie;
  $('rkBoard').hidden = fanqie || !(site.boards || []).length;
  $('rkChannel').hidden = !(site.channels || []).length;

  if(!fanqie && (site.boards || []).length){
    const box = $('rkBoard');
    const want = JSON.stringify(site.boards.map(b => [b.key, b.name]));
    if(box.dataset.options !== want){
      box.dataset.options = want;
      box.innerHTML = '';
      rkBoardMenu = makeDropdown(box, () => rkState());
    }
  }

  // Раздел — второй список, и он не замена доске, а дополнение: у
  // Цидяня «билеты за месяц» и «городское» выбираются независимо.
  if((site.channels || []).length){
    const box = $('rkChannel');
    const want = JSON.stringify(site.channels.map(c => [c.key, c.name]));
    if(box.dataset.options !== want){
      box.dataset.options = want;
      box.innerHTML = '';
      rkChannelMenu = makeDropdown(box, () => rkState());
    }
  }

  // Пояснение приходит вместе с сайтом, а не выбирается здесь по «это
  // Фанкью или не Фанкью». Развилка на два случая уже соврала однажды:
  // под Webnovel показывалось «своей страницы рейтинга у сайта нет» — при
  // том, что у него она как раз есть, а никакого среднего балла нет.
  // Третий сайт повторил бы ту же ошибку.
  $('rkAbout').textContent = (site.about || '')
    + ' Движение по местам считается своей историей: срезы складываются к '
    + 'себе, и по расписанию ничего не запрашивается — срез снимается кнопкой.';
}

function rkMove(value){
  if(value === null || value === undefined) return {text: '—', cls: 'flat'};
  if(value > 0) return {text: '▲ ' + value, cls: 'up'};
  if(value < 0) return {text: '▼ ' + Math.abs(value), cls: 'down'};
  return {text: '=', cls: 'flat'};
}

/* --------------------------------------------------- порядок среза
 *
 * Список порядков и то, какое поле строки за каждый отвечает, приходит
 * с сервера (`ops/rank.ORDERS`): второго перечня здесь быть не должно.
 * Само сравнение чисел — рядом с фильтром, который тоже считается на
 * странице: и то и другое лишь показывает уже полученный срез.
 */

let rkOrders = [];       // что пришло с сервера
let rkOrderMenu = null;
let rkOrderBy = 'place';
let rkOrderDesc = true;

function rkOrderField(){
  return (rkOrders.find(o => o.key === rkOrderBy) || {}).field || '';
}

/** Скольким строкам известно поле выбранного порядка. */
function rkOrderKnown(rows){
  const field = rkOrderField();
  if(!field) return rows.length;
  return rows.filter(row => Number(row[field])).length;
}

function rkSort(rows){
  if(rkOrderBy === 'place' || !rkOrders.length){
    // Сверху первое место или сверху последнее. Строки без места всегда
    // внизу: «последними» их звать не за что — мы их просто не знаем.
    const sign = rkOrderDesc ? 1 : -1;
    return [...rows].sort((a, b) =>
      (a.place ? 0 : 1) - (b.place ? 0 : 1)
      || sign * ((a.place || 0) - (b.place || 0)));
  }
  if(rkOrderBy === 'new'){
    // Новинки наверх, внутри — по месту: новая книга на пятом месте
    // интереснее новой книги на сороковом. Признак `is_new` считает
    // сервер по своей истории срезов — на сайте этого нет вовсе.
    return [...rows].sort((a, b) =>
      (a.is_new ? 0 : 1) - (b.is_new ? 0 : 1) || (a.place || 1e6) - (b.place || 1e6));
  }

  const field = rkOrderField();
  const sign = rkOrderDesc ? -1 : 1;
  return [...rows].sort((a, b) => {
    const one = Number(a[field]) || null, two = Number(b[field]) || null;
    // Строки без числа всегда вниз, в обе стороны: «сначала те, у кого
    // мало глав» не должно означать «сначала те, про кого не знаем».
    if(one === null || two === null){
      return (one === null ? 1 : 0) - (two === null ? 1 : 0);
    }
    return sign * (one - two) || (a.place || 1e6) - (b.place || 1e6);
  });
}

/** Подпись на переключателе направления — своя у места и у чисел.
 *
 *  Положение переключателя у них общее: «сверху то, что выше в
 *  рейтинге» — первое место или большее число. Разные подписи на одну
 *  кнопку нужны затем, чтобы «↓ больше сверху» не стояло над списком,
 *  где сортируют по месту.
 */
function rkShowDir(){
  const button = $('rkOrderDir');
  // У «новинок» направления нет: они либо наверху, либо это уже не они.
  button.hidden = rkOrderBy === 'new';
  button.textContent = rkOrderBy === 'place'
    ? (rkOrderDesc ? '↓ с первого места' : '↑ с последнего места')
    : (rkOrderDesc ? '↓ больше сверху' : '↑ меньше сверху');
}

function rkOrderNote(rows){
  const field = rkOrderField();
  if(!field) return '';
  const have = rkOrderKnown(rows);
  if(have === rows.length) return '';
  return have
    ? `Это число известно у ${have} книг из ${rows.length} — остальные внизу.`
    : 'Этого числа нет ни у одной книги этого рейтинга — порядок не изменился.';
}

function rkRender(){
  const box = $('rkTable');
  box.innerHTML = '';
  const filter = $('rkFilter').value.trim().toLowerCase();
  const shown = rkSort(rkRows.filter(row => !filter
    || (row.name || '').toLowerCase().includes(filter)
    || (rkTitles[row.book_id] || '').toLowerCase().includes(filter)
    || (row.author || '').toLowerCase().includes(filter)));

  const said = rkOrderNote(shown);
  $('rkOrderNote').textContent = said;
  $('rkOrderNote').hidden = !said;
  rkShowDir();

  if(!shown.length){
    box.innerHTML = '<div class="tr"><span class="grow hint">'
      + (rkRows.length ? 'Ничего не подошло под фильтр.'
                       : 'Срезов пока нет — нажмите «Обновить срез».')
      + '</span></div>';
    return;
  }

  for(const row of shown){
    const tr = document.createElement('div');
    tr.className = 'tr';

    const place = document.createElement('span');
    place.className = 'place';
    place.textContent = row.place;
    tr.append(place);

    tr.append(rkCover(row));

    const name = document.createElement('span');
    name.className = 'grow';
    // Название могло не расшифроваться — тогда честно говорим об этом, а
    // не показываем строку из служебных квадратиков.
    name.textContent = row.secret ? `книга ${row.book_id}` : row.name;
    name.title = [row.author && 'автор: ' + row.author,
                  row.words && `${ru(row.words)} знаков`,
                  row.chapters && `${ru(row.chapters)} глав`,
                  row.status,
                  // У Фанкью это название последней главы, у MVLEMPYR —
                  // язык оригинала: подписи разные, а поле одно.
                  row.last_chapter && (row.site ? row.last_chapter
                                                : 'последняя: ' + row.last_chapter)]
                 .filter(Boolean).join(' · ');
    if(row.secret) name.style.opacity = '.7';
    tr.append(name);

    // Числа читающих у второго сайта нет вовсе, зато есть балл. Показывать
    // вместо него ноль значило бы сказать «книгу никто не читает».
    const count = document.createElement('span');
    count.className = 'num';
    if(row.readers){
      count.textContent = ru(row.readers);
      count.title = 'читающих';
    }else if(row.score){
      // Звёздочка означает оценку. На досках Webnovel в этом же поле
      // лежат голоса, покупки и добавления в библиотеку — там она врала
      // бы. Что за число, знает тот, кто его достал: подпись приходит
      // вместе со строкой.
      count.textContent = row.metric ? ru(row.score) : '★ ' + row.score;
      count.title = row.metric || 'средний балл';
    }else{
      count.textContent = '—';
      count.title = 'сайт не показывает ни числа читающих, ни балла';
    }
    tr.append(count);

    // Движение: за сутки и за неделю считаем по своей истории, а `diff` —
    // то, что посчитал сам сайт.
    for(const [value, label] of [[row.day, 'за сутки'], [row.week, 'за неделю'],
                                 [row.diff, 'по данным сайта']]){
      const move = rkMove(value);
      const span = document.createElement('span');
      span.className = 'num ' + move.cls;
      span.textContent = move.text;
      span.title = label;
      tr.append(span);
    }

    if(row.is_new){
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = 'новая';
      tr.append(tag);
    }else if(row.holding > 1){
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = `${row.holding} дн.`;
      tag.title = 'дней подряд в топе';
      tr.append(tag);
    }

    const get = document.createElement('button');
    get.className = 'ghost';
    get.textContent = 'скачать';
    get.style.padding = '4px 10px';
    get.onclick = e => { e.stopPropagation(); rkPick(row); };
    tr.append(get);

    tr.append(rkCopyMenu(row));

    // 2.4: клик по строке раскрывает её. Кнопки внутри строки свои клики
    // не пускают наверх, иначе «скачать» ещё и раскрывала бы карточку.
    tr.style.cursor = 'pointer';
    tr.onclick = () => rkToggle(row, tr);

    if(rkTitles[row.book_id]){
      const ru_ = document.createElement('span');
      ru_.className = 'ru';
      ru_.textContent = rkTitles[row.book_id];
      tr.append(ru_);
    }
    box.append(tr);
    // Строго после строки: карточка раскрывается под ней, а не над.
    box.append(rkDetailsBox(row));
  }
}

//: Адрес книги на сайте. Собирается из кода — другого способа нет.
const RK_LINK = 'https://fanqienovel.com/page/';

/** Ссылка на книгу из строки рейтинга.
 *
 * Складывать её из кода можно было, пока сайт был один. У MVLEMPYR
 * адрес книги строится из слага, а не из кода, и вычислить его здесь
 * уже нечем — сервер кладёт готовую ссылку в саму строку.
 */
function rkLink(row){
  return row.link || (RK_LINK + row.book_id);
}

/** Куда идти за подробностями книги из строки рейтинга.
 *
 * Сайт передаётся тот же, что у строки: у каждого рейтинга свой
 * читатель подробностей. Слаг — потому что у MVLEMPYR книга ищется в
 * каталоге по нему точно, а по коду только приблизительным поиском;
 * взять его больше неоткуда — он спрятан в готовой ссылке на книгу.
 */
function rkBookUrl(row){
  const at = `/api/rank/book/${encodeURIComponent(row.book_id)}`;
  if(!row.site) return at;
  const parts = [`site=${encodeURIComponent(row.site)}`];
  const path = (row.link || '').split('/').filter(Boolean);
  const slug = path.pop();
  // Раздел сайта — то, что стоит перед слагом. У Webnovel комикс живёт
  // в `/comic/`, а роман в `/book/`; собранный наугад адрес отвечал
  // «HTTP 404», хотя обложка той же книги грузилась прекрасно: она
  // лежит отдельно и по коду.
  const section = path.pop();
  if(slug && slug !== row.book_id) parts.push(`slug=${encodeURIComponent(slug)}`);
  if(section) parts.push(`section=${encodeURIComponent(section)}`);
  return `${at}?${parts.join('&')}`;
}

/** Миниатюра обложки в строке рейтинга (2.3 ТЗ).
 *
 * Картинка идёт через свой кэш, а не по ссылке с сайта: та подписана и
 * с сроком действия, а срезы хранятся месяцами — во вчерашнем рейтинге
 * такие ссылки уже мертвы.
 *
 * Загрузка ленивая (`loading="lazy"`): в срезе полсотни строк, и тянуть
 * все обложки разом незачем. Пока картинка не пришла, на её месте
 * пульсирует заготовка, а не пустота.
 */
/** Имя обложки в кэше: сайт и код книги.
 *
 * Строка среза помнит свой сайт сама (`row.site`), а не берёт его из
 * выпадашки: во вчерашнем срезе Фанкью строки должны остаться
 * фанкьюшными, даже если сейчас на экране другой рейтинг.
 */
function rkCoverKey(row){
  return row.site ? `${row.site}-${row.book_id}` : String(row.book_id);
}

function rkCover(row){
  const box = document.createElement('span');
  box.className = 'cover';

  if(!row.book_id) return box;

  const img = document.createElement('img');
  img.loading = 'lazy';
  img.decoding = 'async';
  img.alt = '';
  // Ключ кэша с приставкой сайта. Коды у сайтов свои и независимые: у
  // MVLEMPYR это четыре цифры, у Фанкью девятнадцать, но совпасть они
  // однажды могут — и тогда в одном рейтинге показалась бы обложка из
  // другого. Разбираться в такой путанице было бы нечем.
  img.src = `/api/rank/cover/${encodeURIComponent(rkCoverKey(row))}`
    + (row.cover ? `?url=${encodeURIComponent(row.cover)}` : '');
  img.onload = () => box.classList.add('ready');
  // Обложки может не быть вовсе — тогда остаётся заготовка, и это лучше
  // значка «картинка не загрузилась».
  img.onerror = () => { img.remove(); box.classList.add('empty'); };

  box.append(img);
  return box;
}

/** Кнопка «скопировать» с меню из двух пунктов (2.2 ТЗ).
 *
 * Забрать ссылку руками из рейтинга было нельзя вовсе, а нужна она
 * постоянно: то поделиться, то открыть в браузере, то проверить книгу.
 */
function rkCopyMenu(row){
  const button = document.createElement('button');
  button.className = 'ghost';
  button.textContent = 'скопировать';
  button.style.padding = '4px 10px';

  const put = async (text, said) => {
    toast(await copyText(text) ? said : 'Скопировать не вышло');
  };

  button.onclick = e => {
    e.stopPropagation();
    openMenu(button, [
      ['ссылку', () => put(rkLink(row), 'Ссылка скопирована')],
      ['id', () => put(String(row.book_id), 'Код книги скопирован')],
    ]);
  };
  return button;
}

function rkShow(data){
  rkRows = data.rows || [];
  if(data.titles) rkTitles = data.titles;
  $('rkDetails').hidden = true;

  const parts = [];
  if(rkRows.length){
    parts.push(`Срез за ${data.day}, строк ${rkRows.length}`);
    if(data.stats_date) parts.push(`статистика сайта до ${data.stats_date}`);
    parts.push(`дней в истории ${data.days}`);
    if(data.decoded === false) parts.push('названия расшифровать не удалось');
    if(data.same_version) parts.push('рейтинг с прошлого раза не обновился');
  }
  $('rkNote').textContent = parts.join(' · ') + (parts.length ? '.' : '')
    + (data.note ? ' ' + data.note : '');
  rkFont(data.font);
  rkRender();
}

/** Подробности разбора шрифта (2.5 ТЗ).
 *
 * «Названия расшифровать не удалось» не говорит, что чинить: не скачался
 * файл, не разобрался, обезличены имена глифов или не хватает пакетов
 * для сравнения по начертанию — беды разные.
 */
function rkFont(found){
  const box = $('rkFont');
  if(!found || !Object.keys(found).length){ box.hidden = true; return; }
  // Всё расшифровалось — подробности не нужны, только помеха.
  if(found.ok && !found.unmapped){ box.hidden = true; return; }

  box.hidden = false;
  box.open = !found.ok;
  const list = $('rkFontRows');
  list.innerHTML = '';

  const rows = [
    ['шрифт со страницы', found.family || 'не найден'],
    ['файл скачан', found.downloaded
      ? `да, ${ru(found.size)} байт` : 'нет'],
    ['отпечаток файла', found.digest || '—'],
    ['глифов в шрифте', found.glyphs ? ru(found.glyphs) : '—'],
    ['из них служебных', found.private ? ru(found.private) : '—'],
    ['сопоставлено', found.mapped ? ru(found.mapped) : '0'],
    ['без пары', found.unmapped ? ru(found.unmapped) : '0'],
    ['способ', found.method || '—'],
  ];
  // Порог имеет смысл только у сравнения по начертанию.
  if(found.threshold) rows.push(['порог сравнения', found.threshold]);
  if(found.error) rows.push(['где встало', found.error]);

  for(const [name, value] of rows){
    const row = document.createElement('div');
    row.className = 'tr';
    const label = document.createElement('span');
    label.className = 'grow';
    label.textContent = name;
    const said = document.createElement('span');
    said.className = 'num';
    said.textContent = String(value);
    row.append(label, said);
    list.append(row);
  }
}

/** Подробности поломки: по ним видно, что именно сломалось. */
function rkDiagnose(details){
  const box = $('rkDetails');
  box.innerHTML = '';
  if(!details){ box.hidden = true; return; }
  box.hidden = false;
  for(const [name, value] of Object.entries(details)){
    const row = document.createElement('div');
    row.className = 'tr';
    const label = document.createElement('span');
    label.className = 'grow';
    label.textContent = {
      page_size: 'размер страницы', state_found: 'объект с данными найден',
      book_list: 'книг в объекте', json_error: 'разбор JSON',
      font: 'шрифт скачан', url: 'адрес', http: 'ответ сайта',
      font_details: 'подробности шрифта',
    }[name] || name;
    const said = document.createElement('span');
    said.className = 'num';
    if(name === 'font_details'){
      // Подробности шрифта — отдельный блок, а не строка со словарём.
      rkFont(value);
      continue;
    }
    said.textContent = typeof value === 'boolean' ? (value ? 'да' : 'нет')
                                                  : String(value);
    row.append(label, said);
    box.append(row);
  }
}

async function rkState(){
  try{
    const where = rkWhere();
    const query = new URLSearchParams(where).toString();
    rkShow(await call('/api/rank/state?' + query));
  }catch(err){ showError(err.message); }
}

async function rkLoadCategories(fetchFromSite){
  // Разделы с сайта — такой же поход в сеть, как и сам срез. Из памяти
  // они приходят мгновенно, и полоса там была бы миганием на ровном
  // месте, поэтому показываем её только когда идём наружу.
  if(fetchFromSite) rkWaiting(true);
  try{
    const data = await call('/api/rank/categories'
                            + (fetchFromSite ? '?fetch=1' : ''));
    rkCats = data.categories || {};
    rkSites = data.sites || [];
    rkOrders = data.orders || [];

    if(!rkOrderMenu && rkOrders.length){
      const box = $('rkOrder');
      box.dataset.options = JSON.stringify(rkOrders.map(o => [o.key, o.name]));
      box.innerHTML = '';
      rkOrderMenu = makeDropdown(box, value => { rkOrderBy = value; rkRender(); });
    }

    if(!rkSiteMenu && rkSites.length){
      const box = $('rkSite');
      box.dataset.options = JSON.stringify(rkSites.map(s => [s.key, s.name]));
      box.innerHTML = '';
      rkSiteMenu = makeDropdown(box, () => { rkApplySite(); rkState(); });
    }

    if(!rkAudMenu){
      const aud = $('rkAudience');
      aud.dataset.options = JSON.stringify(data.audiences.map(a => [a.key, a.name]));
      aud.innerHTML = '';
      rkAudMenu = makeDropdown(aud, () => { rkFillCategories(); rkState(); });

      const kind = $('rkKind');
      kind.dataset.options = JSON.stringify(data.kinds.map(k => [k.key, k.name]));
      kind.innerHTML = '';
      rkKindMenu = makeDropdown(kind, () => rkState());
    }
    rkFillCategories();
    rkApplySite();
  }catch(err){
    showError(err.message);
  }finally{
    if(fetchFromSite) rkWaiting(false);
  }
}

function rkFillCategories(){
  const side = rkAudMenu ? rkAudMenu.value : '1';
  const list = rkCats[side] || [];
  const box = $('rkCategory');
  box.dataset.options = JSON.stringify(list.map(c => [
    c.id, c.name + (c.translated ? '' : ' (без перевода)')]));
  box.innerHTML = '';
  rkCatMenu = makeDropdown(box, () => rkState());
}

/** Полоса ожидания на время запроса к сайту.
 *
 * Процентов у неё нет и быть не может: рейтинг приходит одной страницей
 * за один запрос — считать нечего, а рисовать выдуманное число хуже, чем
 * не рисовать никакого. Отвечает она на другой вопрос, тот, который в
 * это время и возникает: работает оно или подвисло.
 */
function rkWaiting(on){
  $('rkBar').hidden = !on;
}

async function rkRefresh(){
  showError('');
  $('rkRefresh').disabled = true;
  rkWaiting(true);
  $('rkNote').innerHTML = '<span class="spin"></span>Запрашиваем рейтинг…';
  try{
    const data = await call('/api/rank/refresh', rkWhere());
    rkShow(data);
  }catch(err){
    showError(err.message);
    $('rkNote').textContent = '';
    rkDiagnose(err.details);
  }finally{
    rkWaiting(false);
    $('rkRefresh').disabled = false;
  }
}

/** Переводы описаний, полученные скопом.
 *
 *  Раскрытая карточка спрашивает свой перевод у сервера, но после общего
 *  перевода он уже здесь: ходить за ним второй раз незачем.
 */
let rkAbouts = {};

//: Идущий прогон за описаниями. Пока он есть, кнопка — «Остановить».
let rkAboutsJob = null;

/** Забрать недостающие описания — задачей, с прогрессом и остановкой.
 *
 *  Перевод описаний работал только по тем книгам, чью карточку уже
 *  забирали с сайта. Кнопка называлась «Перевести всё» и молча
 *  пропускала половину среза. Ходить за полусотней страниц внутри
 *  перевода нельзя: это минута с виду зависшей кнопкой.
 */
async function rkFetchAbouts(){
  const {job} = await call('/api/rank/abouts/start', rkWhere());
  rkAboutsJob = job.id;
  $('rkTranslate').textContent = 'Остановить';
  $('rkTranslate').disabled = false;

  return new Promise(done => {
    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('rkNote').textContent = p.message || '';
        return !TERMINAL.includes(p.stage);
      },
      job => {
        rkAboutsJob = null;
        done({...(job.report || {}), stopped: !!job.cancelled});
      });
  });
}

async function rkTranslate(){
  // Кнопка на время прогона становится «Остановить»: другой ей быть
  // негде, а бросать задачу нечем.
  if(rkAboutsJob){ stopJob(rkAboutsJob); return; }

  showError('');
  $('rkTranslate').disabled = true;
  const was = $('rkTranslate').textContent;
  $('rkTranslate').textContent = 'Читаем описания…';
  try{
    const got = await rkFetchAbouts();
    if(got.stopped){
      // Остановили — значит, остановили всё: тратить ключи на перевод
      // после «Остановить» человек не просил.
      $('rkNote').textContent = 'Остановлено. Что успели забрать — осталось.';
      return;
    }
    $('rkTranslate').textContent = 'Переводим…';
    $('rkTranslate').disabled = true;
    if(got.missed) showError(`Не забралось описаний: ${got.missed}. `
      + 'Остальные переведены.');
    // Одной кнопкой — и названия, и описания. Описания идут пачками по
    // шесть: полсотни укладываются в девять запросов, а не в полсотни.
    const data = await call('/api/rank/translate',
      {...rkWhere(), model: llmMenu ? llmMenu.value : '', abstracts: true});
    rkTitles = data.titles || {};
    rkAbouts = {...rkAbouts, ...((data.abouts || {}).abstracts || {})};

    // «Не разобрано ответов» человеку ничего не говорило: ответы — наше
    // внутреннее дело, а видит он китайские названия. Считаем и называем
    // именно их.
    const left = (data.missing || []).join(', ');
    let note = `Названия: переведено ${data.translated}, из кэша ${data.cached}.`
      + (data.broken
        ? ` Осталось китайскими: ${data.broken}`
          + (left ? ` — ${left}${data.broken > (data.missing || []).length
            ? ' и другие' : ''}.` : '.')
          + ' Нажмите ещё раз.'
        : '');

    // Счётчики раздельные: названия и описания стоят разного числа
    // запросов, и одно число на двоих прятало бы цену.
    const about = data.abouts;
    if(about){
      note += ` Описания: переведено ${about.translated}, `
        + `из кэша ${about.cached}.`
        + (about.absent
          ? ` Без описания на сайте: ${about.absent}.`
          : '')
        // «Не забирали» — это наше, и человеку надо сказать, что делать.
        // Раньше такие книги считались как «без описания», и кнопка
        // молча пропускала половину среза.
        + (about.unknown
          ? ` Ещё у ${about.unknown} описание не забирали с сайта —`
            + ' раскройте строку, и оно переведётся.'
          : '')
        + (about.broken ? ` Не далось: ${about.broken}.` : '');
    }
    $('rkNote').textContent = note;
    rkRender();
  }catch(err){ showError(err.message); }
  finally{
    $('rkTranslate').disabled = false;
    $('rkTranslate').textContent = was;
  }
}

/* Раскрытие строки рейтинга (2.4 ТЗ).
 *
 * В срезе нет ни описания, ни жанра, а без них непонятно, стоит ли книгу
 * вообще брать. Данные тянутся лениво — по первому раскрытию — и лежат в
 * своём кэше: ходить на сайт при каждом клике незачем.
 *
 * Раскрыта всегда одна строка: две развёрнутые карточки не помещаются на
 * экран, и сравнивать их всё равно не выходит.
 */
let rkOpenId = null;

/** Пустой блок под подробности. Наполняется при первом раскрытии. */
function rkDetailsBox(row){
  const box = document.createElement('div');
  box.className = 'rkcard';
  box.dataset.book = row.book_id;
  box.hidden = true;
  return box;
}

function rkBoxOf(bookId){
  return document.querySelector(`#rkTable .rkcard[data-book="${bookId}"]`);
}

/**
 * Что о книге известно из самой строки рейтинга.
 *
 * У большинства сайтов это место, название и число — карточку из такого
 * не соберёшь. Цидянь же печатает в строке всю книгу: автора, жанр,
 * статус, описание, последнюю главу и время. Тогда страница книги нужна
 * только ради объёма и числа глав, а если она не открылась — карточке
 * всё равно есть что показать.
 */
function rkFromRow(row){
  return {
    name: row.name || '',
    abstract: (row.about || '').trim(),
    author: row.author || '',
    category: row.category || '',
    status: row.status || '',
    last_chapter: row.last_chapter || '',
    updated: row.updated || '',
    cover: row.cover || '',
    link: row.link || '',
    tags: [],
  };
}

/** Со страницы книги данные полнее, но пустое поле не должно затирать
 *  непустое: страница может промолчать там, где рейтинг сказал. */
function rkMerge(known, fresh){
  const out = {...known};
  for(const [key, value] of Object.entries(fresh || {})){
    const empty = value === null || value === undefined || value === ''
      || (Array.isArray(value) && !value.length);
    if(!empty || !(key in out)) out[key] = value;
  }
  return out;
}

async function rkToggle(row, tr){
  const box = rkBoxOf(row.book_id);
  if(!box) return;

  // Уже открытую закрываем: одновременно раскрыта одна строка.
  if(rkOpenId && rkOpenId !== row.book_id){
    const other = rkBoxOf(rkOpenId);
    if(other) rkShut(other);
  }

  if(rkOpenId === row.book_id){ rkShut(box); rkOpenId = null; return; }
  rkOpenId = row.book_id;

  if(!box.dataset.filled){
    box.innerHTML = '<div class="hint" style="padding:10px 12px">'
      + '<span class="spin"></span>Читаем страницу книги…</div>';
    rkOpen(box);
    try{
      // Подробности спрашиваем у того сайта, с которого строка. Сначала
      // запрос уходил всегда фанкьюшный, и на строке MVLEMPYR человек
      // получал «HTTP 404 fanqienovel.com/page/13571». Потом такой
      // запрос перестали слать вовсе — и раскрытая строка стала копией
      // самой строки: то же название, те же числа, те же кнопки.
      // Раскрывают, чтобы узнать больше, а не чтобы прочесть то же
      // крупнее.
      const data = rkMerge(rkFromRow(row), await call(rkBookUrl(row)));
      box.innerHTML = '';
      box.append(rkCardBody(row, data));
      box.dataset.filled = '1';
    }catch(err){
      box.innerHTML = '';
      // Часть сайтов кладёт описание прямо в строку рейтинга — так
      // делает Цидянь. Тогда закрытая страница книги не повод показать
      // одну ошибку: карточку есть из чего собрать, а про неудачу
      // достаточно сказать строкой ниже.
      const known = rkFromRow(row);
      if(known.abstract){
        box.append(rkCardBody(row, known));
        box.dataset.filled = '1';
      }
      const said = document.createElement('div');
      said.className = known.abstract ? 'hint' : 'err local';
      said.hidden = false;
      said.style.padding = '0 12px 10px';
      said.textContent = known.abstract
        ? 'Страница книги не открылась, показано то, что было в рейтинге: '
          + err.message
        : 'Подробности не пришли: ' + err.message;
      box.append(said);
    }
    rkOpen(box);
    return;
  }
  rkOpen(box);
}

/** Плавно по высоте: резкий скачок сбивает место, на которое смотрели. */
function rkOpen(box){
  box.hidden = false;
  box.style.maxHeight = box.scrollHeight + 'px';
  box.classList.add('open');
}

function rkShut(box){
  box.style.maxHeight = '0px';
  box.classList.remove('open');
  // Прятать только после доигранного перехода, иначе он не виден.
  setTimeout(() => { if(!box.classList.contains('open')) box.hidden = true; }, 300);
}

//: Какой язык описания выбран у книги. Держим здесь, а не в самой
//: карточке: список пересобирается на каждый фильтр и на каждый срез, и
//: выбор «читаю по-русски» иначе слетал бы (3.1 ТЗ).
const rkLang = {};

//: Что показать вместо описания, когда его нет. Отдельно про шрифт:
//: описание тоже подменяется им, и пустое место выглядит как поломка.
const RK_NO_ABOUT = 'Описания на странице книги нет.';
const RK_SECRET_ABOUT = 'Описание зашифровано шрифтом — расшифровать не вышло.';

/** Описание книги с переключателем «оригинал / перевод» (3.1 ТЗ).
 *
 * Перевод заказывается по кнопке и по одной книге: описаний полсотни на
 * срез, а читают из них два-три. Переведённое сервер помнит по коду
 * книги, поэтому второй раз кнопка не понадобится.
 */
function rkAbout(row, data){
  const wrap = document.createElement('div');
  const own = (data.abstract || '').trim();
  // Перевод мог приехать общей кнопкой — тогда он уже здесь.
  let done = (data.abstract_ru || '').trim()
             || (rkAbouts[row.book_id] || '').trim();

  const text = document.createElement('p');
  text.className = 'hint';
  text.style.whiteSpace = 'pre-line';

  const bar = document.createElement('div');
  bar.className = 'row';
  bar.style.gap = '6px';
  bar.style.marginTop = '6px';

  const orig = document.createElement('button');
  orig.className = 'ghost';
  orig.textContent = '原';
  orig.title = 'описание как на сайте';
  const ru_ = document.createElement('button');
  ru_.className = 'ghost';
  ru_.textContent = 'RU';
  ru_.title = 'перевод описания';
  const ask = document.createElement('button');
  ask.className = 'ghost';
  ask.textContent = 'перевести';

  for(const button of [orig, ru_, ask]) button.style.padding = '2px 10px';

  function show(){
    const on = rkLang[row.book_id] === 'ru' && !!done;
    text.textContent = on ? done
      : (own || (data.secret ? RK_SECRET_ABOUT : RK_NO_ABOUT));
    orig.classList.toggle('on', !on);
    ru_.classList.toggle('on', on);
    ru_.hidden = !done;
    // Пока перевода нет, вместо второй кнопки стоит та, что его закажет.
    ask.hidden = !!done;
  }

  orig.onclick = e => { e.stopPropagation(); rkLang[row.book_id] = 'zh'; show(); };
  ru_.onclick = e => { e.stopPropagation(); rkLang[row.book_id] = 'ru'; show(); };
  ask.onclick = async e => {
    e.stopPropagation();
    ask.disabled = true;
    ask.textContent = 'Переводим…';
    try{
      const got = await call('/api/rank/abstract',
                             {book_id: row.book_id, text: own});
      done = (got.abstract || '').trim();
      // Перевод заказывали — его и показываем, без второго нажатия.
      rkLang[row.book_id] = 'ru';
      show();
    }catch(err){
      toast(err.message);
    }finally{
      ask.disabled = false;
      ask.textContent = 'перевести';
    }
  };

  wrap.append(text);
  // Переводить нечего — и переключать нечего.
  if(own) wrap.append(bar);
  bar.append(orig, ru_, ask);
  show();
  return wrap;
}

/** Содержимое раскрытой карточки. */
function rkCardBody(row, data){
  const wrap = document.createElement('div');
  wrap.className = 'rkcard-body';

  const cover = document.createElement('img');
  cover.className = 'rkcard-cover';
  cover.alt = '';
  cover.loading = 'lazy';
  // Тот же ключ кэша, что и у миниатюры в строке: без приставки сайта
  // раскрытая карточка ходила бы за обложкой по чужому имени и в
  // половине случаев не находила её вовсе.
  cover.src = `/api/rank/cover/${encodeURIComponent(rkCoverKey(row))}`
    + ((data.cover || row.cover) ? `?url=${encodeURIComponent(data.cover || row.cover)}` : '');
  cover.onerror = () => { cover.hidden = true; };

  const side = document.createElement('div');
  side.className = 'rkcard-side';

  const title = document.createElement('div');
  title.className = 'book-name';
  // Оригинал и перевод рядом (3.1 ТЗ). Название берём со страницы книги:
  // там оно полное, в срезе бывает урезанным.
  title.textContent = rkBothTitles({
    book_id: row.book_id,
    name: data.name || row.name,
    secret: data.secret === undefined ? row.secret : data.secret,
  });
  side.append(title);

  side.append(rkAbout(row, data));

  const tags = document.createElement('div');
  tags.className = 'rkcard-tags';
  for(const tag of [data.category, ...(data.tags || [])].filter(Boolean)){
    const chip = document.createElement('span');
    chip.className = 'tag';
    chip.textContent = tag;
    tags.append(chip);
  }
  if(tags.children.length) side.append(tags);

  const stats = document.createElement('div');
  stats.className = 'stats';
  // Числа у сайтов разные, и показывать чужие прочерками — врать в
  // обе стороны: у MVLEMPYR нет ни читающих, ни знаков, зато есть балл,
  // а у Фанкью наоборот. Поэтому строка складывается из того, что у
  // книги действительно есть.
  const chapters = data.chapters || row.chapters;
  const words = data.words || row.words;
  const score = data.score === undefined ? row.score : data.score;
  const rows = [
    chapters && ['глав', ru(chapters)],
    words && ['знаков', ru(words)],
    ['статус', data.status || row.status || '—'],
    row.readers && ['читающих', ru(row.readers)],
    // Подпись числа — та же, что в строке. «Балл» подходит только там,
    // где это действительно оценка: у Цидяня это купленные билеты, у
    // Webnovel голоса или покупки, и называть их баллом — врать про
    // число, которое человек прочитает как оценку.
    score && [row.metric || 'балл',
              row.metric ? ru(score) : String(score)],
  ].filter(Boolean);
  for(const [name, value] of rows){
    const span = document.createElement('span');
    span.innerHTML = `${name} <b>${value}</b>`;
    stats.append(span);
  }
  side.append(stats);

  // `last_chapter` из строки берём только у Фанкью. У MVLEMPYR это же
  // поле занято языком оригинала — общая строка рейтинга одна на все
  // сайты, — и подпись «последняя глава: английский» получалась чушью.
  const tail = data.last_chapter || (!row.site && row.last_chapter);
  const when = [
    data.updated && `обновлено ${rkWhen(data.updated)}`,
    data.first_published && `первая публикация ${rkWhen(data.first_published)}`,
    tail && `последняя глава: ${tail}`,
    data.language && `язык оригинала: ${data.language}`,
    (data.author || row.author) && `автор: ${data.author || row.author}`,
  ].filter(Boolean);
  if(when.length){
    const line = document.createElement('p');
    line.className = 'hint';
    line.textContent = when.join(' · ');
    side.append(line);
  }

  // Кнопка здесь одна, и это не экономия места.
  //
  // Раньше карточка повторяла «Скачать» и «Скопировать», которые уже
  // стоят в самой строке — в строке, до которой отсюда один сантиметр
  // вверх. Два одинаковых действия рядом не помогают, а заставляют
  // выбирать между ними: человек читает обе кнопки и гадает, чем они
  // отличаются. Не отличаются ничем.
  //
  // «Открыть на сайте» осталась потому, что в строке её нет.
  const buttons = document.createElement('div');
  buttons.className = 'row';
  buttons.style.marginTop = '12px';

  const open = document.createElement('button');
  open.className = 'ghost';
  open.textContent = 'Открыть на сайте';
  open.onclick = e => {
    e.stopPropagation();
    window.open(data.link || rkLink(row), '_blank', 'noopener');
  };

  buttons.append(open);
  side.append(buttons);

  wrap.append(cover, side);
  return wrap;
}

/** Дата с сайта: приходит то числом секунд, то строкой. */
function rkWhen(value){
  const number = Number(value);
  if(number > 0){
    // Секунды и миллисекунды сайт смешивает — различаем по порядку.
    const when = new Date(number > 1e12 ? number : number * 1000);
    if(!isNaN(when)) return when.toLocaleDateString('ru');
  }
  // WordPress отдаёт дату строкой вида 2026-08-20T11:04:00. Числом она
  // не становится, и в карточке так и висела целиком, с секундами.
  if(typeof value === 'string' && /^\d{4}-\d\d-\d\d/.test(value)){
    const when = new Date(value);
    if(!isNaN(when)) return when.toLocaleDateString('ru');
  }
  return String(value);
}

/** Книга выбрана — уходим на качалку и настраиваем её под эту книгу (2.1).
 *
 * Раньше здесь был свой маленький загрузчик со своими полями. Он умел
 * меньше качалки, а диапазон глав оставался от прошлого запуска — отсюда
 * и бралось «Конечная глава меньше начальной» на только что выбранной
 * книге. Теперь всё идёт одним путём: рейтинг лишь заполняет качалку.
 */
async function rkPick(row){
  // С сайта может не быть качалки вовсе. У Цидяня за первыми главами
  // начинается подписка, и делать вид, что книга сейчас скачается, —
  // враньё: человек уйдёт на вкладку качалки, нажмёт «Найти» и получит
  // невнятную ошибку. Честнее сказать сразу и дать в руки то, что
  // действительно поможет, — название для поиска на сайте-сливе.
  const from = rkSites.find(s => s.key === (row.site || ''));
  if(row.site && from && !from.source){
    const said = await copyText(row.name || String(row.book_id));
    toast(`Скачивать с ${from.name} программа не умеет: там подписка. `
      + (said ? 'Название скопировано — ищите книгу на сайте-сливе.'
              : 'Ищите книгу на сайте-сливе по названию.'));
    return;
  }

  rkPicked = row;
  goTab('download');

  // Источник — Фанкью через посредника. Обычный способ на этих книгах
  // упирается в закрытые главы: у книги на тысячу двести открыто десять,
  // и прогон вырождается в сплошные пропуски. Посредник отдаёт их все —
  // ценой того, что и книга, и запрос идут через чужой сервер открытым
  // текстом. Способ виден в поле «Источник» и меняется одним щелчком.
  // С `notify`: вместе с источником меняются заполнитель поля и пояснение
  // под ним — у Фанкью в ссылке не слаг, а числовой код.
  //
  // Всё сказанное — про Фанкью. У строки из другого рейтинга и источник
  // другой, и берётся он не отсюда, а из ответа сервера: там же, где
  // объявлен сам рейтинг. Иначе третий сайт пришлось бы вписывать сюда
  // руками, а список сайтов — снова в двух местах.
  if(typeof srcMenu !== 'undefined' && srcMenu){
    const known = rkSites.find(s => s.key === (row.site || ''));
    const source = row.site ? (known && known.source) : 'fanqie-mirror';
    if(source) srcMenu.set(source, {notify: true});
  }
  $('q').value = row.book_id;

  // Диапазон чистим сразу, до поиска: пустые поля означают «вся книга»,
  // а числа от прошлого запуска — то самое «конечная глава меньше
  // начальной» на только что выбранной книге.
  $('first').value = '';
  $('last').value = '';
  if(typeof rangeNote === 'function') rangeNote('');

  // Имя папки от прошлой книги здесь тем более лишнее: главы легли бы в
  // чужую папку. Своё имя подставит поиск — его считает сервер, у него
  // есть перевод названия (3.2 ТЗ).
  $('folder').value = '';

  rkShowCard(row);
  rkCardFlash();

  try{
    // Без подстановки диапазона: поля уже очищены и значат то же самое.
    await find(false);
  }catch(err){ /* показать карточку важнее, чем найти книгу с первого раза */ }
}

/** Русское название книги из рейтинга, если оно уже переведено. */
function rkTitleOf(bookId){
  return (rkTitles[String(bookId)] || '').trim();
}

/** Название книги «оригинал / перевод» (3.1, 3.2 ТЗ).
 *
 * Одного перевода мало: по нему книгу не найти ни на сайте, ни в поиске.
 * Одного оригинала мало тем более: непонятно, о чём книга. Поэтому видно
 * оба, а если чего-то нет — то, что есть.
 */
function rkBothTitles(row){
  const own = row.secret ? '' : (row.name || '').trim();
  const ru_ = rkTitleOf(row.book_id);
  if(own && ru_ && own !== ru_) return `${own} / ${ru_}`;
  return own || ru_ || `книга ${row.book_id}`;
}

/** Карточка «что именно выбрано»: то, что о книге знает рейтинг. */
function rkShowCard(row){
  // Карточка одна на оба пути — та же, что показывает найденную книгу.
  // Двух одинаковых обложек одна под другой быть не должно: книга одна,
  // и откуда её взяли, читателю безразлично. Сюда кладём то, что знает
  // срез; ответит сайт — `find` перепишет теми же полями.
  const card = $('book');
  card.hidden = false;
  $('bookName').textContent = rkBothTitles(row);
  $('bookMeta').textContent = [
    `код ${row.book_id}`,
    row.author && 'автор: ' + row.author,
    row.readers && `${ru(row.readers)} читающих`,
    row.words && `${ru(row.words)} знаков`,
    row.status,
    row.place && `место ${row.place} в срезе`,
  ].filter(Boolean).join('  ·  ');
  // Перевод названия у среза уже может быть — тогда переводить нечего.
  $('bookTranslate').hidden = !!rkTitleOf(row.book_id);

  // Через свой кэш, как и миниатюра в строке: ссылка с сайта подписана и
  // живёт недолго, а карточка может провисеть на экране весь вечер.
  const cover = $('bookCover');
  cover.hidden = !row.book_id;
  if(row.book_id){
    cover.src = `/api/rank/cover/${encodeURIComponent(row.book_id)}`
      + (row.cover ? `?url=${encodeURIComponent(row.cover)}` : '');
    cover.onerror = () => { cover.hidden = true; };
  }
}

/** Доскроллить и подсветить: иначе непонятно, куда книга уехала. */
function rkCardFlash(){
  const card = $('book');
  card.scrollIntoView({behavior: 'smooth', block: 'center'});
  card.classList.remove('flash');
  // Перезапуск анимации: без чтения раскладки браузер снятие и возврат
  // класса в одном кадре не заметит.
  void card.offsetWidth;
  card.classList.add('flash');
}

$('rkRefresh').onclick = rkRefresh;
$('rkTranslate').onclick = rkTranslate;
$('rkFilter').addEventListener('input', rkRender);

$('rkOrderDir').onclick = () => {
  rkOrderDesc = !rkOrderDesc;
  rkRender();
};

rkLoadCategories().then(rkState);


/* ------------------------------------------------- общая доска «Везде»
 *
 * Склейка книг по сайтам считается на сервере: сравнение названий и
 * правило «одинаковое название при разных авторах — не одна книга»
 * живут в `ops/everywhere`, и второй их экземпляр здесь однажды
 * разошёлся бы с первым.
 */

let evRows = [];

async function evLoad(){
  showError('');
  $('evStart').disabled = true;
  $('evNote').innerHTML = '<span class="spin"></span>Сводим срезы…';
  try{
    const data = await call('/api/rank/everywhere');
    evRows = data.rows || [];

    // Пустая доска без причины читается как поломка. Причину знает
    // сервер: он же считает, скольким книгам не хватает перевода.
    $('evNote').textContent = (data.total
      ? `Книг: ${data.total}, из них на нескольких сайтах: ${data.shared}.`
        + (data.more ? ` Показаны первые ${data.total - data.more}.` : '')
      : 'Срезов ещё нет. Снимите хотя бы один рейтинг кнопкой «Обновить срез».')
      + (data.advice ? ' ' + data.advice : '');

    // Из чего собрана доска: срез месячной давности — не «читают
    // сейчас», и не сказать об этом значило бы соврать датой.
    const taken = $('evTaken');
    taken.innerHTML = '';
    for(const row of data.taken || []){
      const line = document.createElement('div');
      line.className = 'tr';
      const name = document.createElement('span');
      name.className = 'grow';
      name.textContent = [row.site_name, row.board_name, row.category_name]
        .filter(Boolean).join(' · ');
      const when = document.createElement('span');
      when.className = 'num';
      when.textContent = `${row.day} · ${row.rows}`;
      line.append(name, when);
      taken.append(line);
    }
    taken.hidden = !(data.taken || []).length;

    evRender();
  }catch(err){
    showError(err.message);
    $('evNote').textContent = '';
  }finally{
    $('evStart').disabled = false;
  }
}

function evRender(){
  const only = $('evOnlyShared').checked;
  const table = $('evTable');
  table.innerHTML = '';

  const rows = evRows.filter(row => !only || row.sites > 1);
  if(!rows.length){
    const line = document.createElement('div');
    line.className = 'tr';
    const text = document.createElement('span');
    text.className = 'grow';
    text.textContent = only
      ? 'Ни одной книги не узнали больше чем в одном рейтинге.'
      : 'Пусто.';
    line.append(text);
    table.append(line);
    return;
  }

  for(const row of rows){
    const line = document.createElement('div');
    line.className = 'tr';

    const place = document.createElement('span');
    place.className = 'num';
    place.textContent = row.best || '—';

    const name = document.createElement('span');
    name.className = 'grow';
    name.textContent = row.name + (row.author ? ` — ${row.author}` : '');
    name.title = name.textContent;

    line.append(place, name);
    for(const seat of row.seats){
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = `${seat.site_name} #${seat.place || '—'}`;
      tag.title = [seat.board, seat.day].filter(Boolean).join(' · ');
      line.append(tag);
    }
    table.append(line);
  }
}

$('evStart').onclick = evLoad;
$('evOnlyShared').addEventListener('change', evRender);


/* ============ Память полей и последние папки ============
 *
 * Программа не помнила между запусками ничего, кроме галочек эффектов:
 * папку назначения приходилось набирать заново каждый раз, и на каждой
 * вкладке отдельно. При работе «в два клика» это самая дорогая потеря
 * времени из всех.
 *
 * Запоминаем не всё подряд, а только помеченное `data-keep`. Правило
 * нарочно от обратного: попади сюда поле ключа или ссылка на книгу, они
 * молча осели бы в хранилище браузера. Помечено — значит, кто-то решил,
 * что это можно хранить.
 *
 * Хранилище браузера бывает закрыто настройками, и тогда всё это просто
 * не работает — но не мешает: каждый поход в него обёрнут.
 */

const KEEP_STORE = 'nz-fields';
const FOLDER_STORE = 'nz-folders';

//: Сколько последних папок подсказывать. Больше — уже не подсказка, а
//: список, в котором надо искать.
const FOLDERS_KEPT = 8;

function keepRead(name){
  try{
    return JSON.parse(localStorage.getItem(name) || 'null') || null;
  }catch(err){
    return null;
  }
}

function keepWrite(name, value){
  try{
    localStorage.setItem(name, JSON.stringify(value));
  }catch(err){
    // Приватное окно или запрет на хранение: молча живём без памяти.
  }
}

/** Последние папки назначения — в общий список подсказок. */
function foldersDraw(){
  const box = $('nzFolders');
  if(!box) return;
  box.innerHTML = '';
  for(const path of keepRead(FOLDER_STORE) || []){
    const item = document.createElement('option');
    item.value = path;
    box.append(item);
  }
}

/** Запоминает папку как недавнюю. Повтор поднимается наверх, а не
 *  ложится вторым: список из одной папки в трёх экземплярах бесполезен. */
function folderUsed(path){
  const clean = String(path || '').trim();
  if(!clean) return;
  const kept = (keepRead(FOLDER_STORE) || []).filter(one => one !== clean);
  kept.unshift(clean);
  keepWrite(FOLDER_STORE, kept.slice(0, FOLDERS_KEPT));
  foldersDraw();
}

function keepFields(){
  return [...document.querySelectorAll('[data-keep]')];
}

function keepSave(){
  const kept = {};
  for(const field of keepFields()){
    const value = field.type === 'checkbox' ? field.checked : field.value;
    if(value !== '' && value !== false) kept[field.id] = value;
  }
  keepWrite(KEEP_STORE, kept);
}

/** Возвращает поля на место при запуске.
 *
 * Событие `input` шлём нарочно: на нём висят подписи «главы лягут в…» и
 * схемы «файл → разбить → файлы». Молча подставленное значение оставило
 * бы их пустыми, и человек решил бы, что поле не заполнено.
 */
function keepLoad(){
  const kept = keepRead(KEEP_STORE) || {};
  for(const field of keepFields()){
    const value = kept[field.id];
    if(value === undefined) continue;
    if(field.type === 'checkbox') field.checked = !!value;
    else field.value = value;
    field.dispatchEvent(new Event('input'));
  }
  foldersDraw();
}

for(const field of keepFields()){
  // Набранное запоминаем сразу, а в список недавних папок кладём только
  // по `change` — то есть когда путь дописан, а не на каждой букве.
  field.addEventListener('input', keepSave);
  field.addEventListener('change', () => {
    keepSave();
    folderUsed(field.value);
  });
}

keepLoad();


/* ============ Словарь имён собственных ============
 *
 * Заголовки идут к модели пачками по двадцать пять, каждая пачка — свой
 * запрос, и модель не помнит, как назвала героя в прошлой: отсюда «Ли
 * Сяо» в одной главе и «Ли Сяон» в соседней.
 *
 * Разбирает присланное сервер — тем же кодом, что принимает глоссарий от
 * переводчика. Своего понимания формата здесь нет намеренно: два
 * понимания одного файла однажды разъедутся.
 */

function gnShow(data){
  $('gnText').value = data.text || '';
  $('gnNote').textContent = data.total
    ? `В словаре имён: ${data.total}.`
    : 'Словарь пуст — имена переводятся как выйдет.';
}

async function gnLoad(){
  try{
    gnShow(await call('/api/titles/spellings'));
  }catch(err){ showError(err.message, $('gnNote')); }
}

async function gnSave(){
  showError('');
  $('gnSave').disabled = true;
  try{
    // `replace` нарочно: поле показывает словарь целиком, и человек
    // правит его как текст. Дописывать к нему же значило бы, что
    // удалённая строка возвращается сама.
    const got = await call('/api/titles/spellings',
                           {text: $('gnText').value, replace: true});
    gnShow(got);
    toast(`Словарь сохранён: имён ${got.total}.`);
  }catch(err){
    showError(err.message, $('gnNote'));
  }finally{
    $('gnSave').disabled = false;
  }
}

async function gnClear(){
  if(!confirm('Очистить словарь имён? Имена снова будут переводиться '
              + 'как выйдет.')) return;
  try{
    gnShow(await call('/api/titles/spellings', {clear: true}));
  }catch(err){ showError(err.message, $('gnNote')); }
}

$('gnSave').onclick = gnSave;
$('gnLoad').onclick = gnLoad;
$('gnClear').onclick = gnClear;
gnLoad();
