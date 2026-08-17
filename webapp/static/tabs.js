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
    toggle.innerHTML = `<span>${found ? found[1] : ''}</span><span>▾</span>`;
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

  return {get value(){ return value; }, set};
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
  updateListBar(listId);
}

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

document.querySelectorAll('.pickany').forEach(button => {
  button.onclick = async () => {
    const listId = button.dataset.list;
    const label = button.textContent;
    button.disabled = true;
    button.textContent = 'Окно…';
    try{
      const data = await call('/api/pick/any', {});
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
      showError(err.message + ' Путь можно вписать вручную ниже.');
    }finally{
      button.disabled = false;
      button.textContent = label;
    }
  };
});


/** Склонение: «1 файл», «2 файла», «5 файлов». */
function plural(count, one, few, many){
  const tail = count % 10, hundred = count % 100;
  if(hundred >= 11 && hundred <= 14) return many;
  if(tail === 1) return one;
  if(tail >= 2 && tail <= 4) return few;
  return many;
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
  fill.style.width = pct + '%';
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
function pollJob(jobId, draw, onDone){
  const timer = setInterval(async () => {
    try{
      const {job} = await call('/api/job/' + jobId);
      LAST_JOB = job;
      if(!draw(job)){
        clearInterval(timer);
        onDone(job);
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
    if(fmt.part && part) head += '.' + part;
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
    if(!$('rnOut').value) $('rnOut').value = 'Готово';

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
    size.textContent = chapter.size.toLocaleString('ru') + ' симв.';

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
    const {job} = await call('/api/rename/apply', {
      ...rnPayload(),
      base: $('rnBase').value.trim(),
      folder_out: $('rnOut').value.trim(),
      out_format: rnState.format.replace('.', ''),
      names: rnRows.map(r => r.new_name),
    });
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
$('rnPattern').addEventListener('keydown', e => { if(e.key === 'Enter') rnScan(); });
//: Формат на выходе у «Переименовать». Хранится так же, как у остальных
//: вкладок, чтобы кнопки строились общей функцией.
const rnState = {format: '.txt'};
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

/** Оформление и обработка нужны не всякому формату — прячем лишнее. */
function toggleOptions(p, format){
  $(p + 'Style').hidden = format !== '.docx';
  $(p + 'Prep').hidden = false;
}

/* ------------------------------------------------------------ Разбить */

const spState = {format: '.txt', job: null, menus: {}, scan: null};

function spUpdateFinal(){
  const base = $('spBase').value.trim(), name = $('spFolder').value.trim();
  $('spFinal').textContent = base && name
    ? `Главы лягут в: ${base}/${name}  (${spState.format})` : '';
  toggleOptions('sp', spState.format);
  spDrawSchema();
}

/** «1 файл .epub → разбить → 5 файлов .docx». */
function spDrawSchema(){
  const data = spState.scan;
  if(!data){ $('spSchema').hidden = true; return; }
  const parts = Math.max(1, Number($('spParts').value) || 1);
  drawSchema('spSchema',
    {count: data.file_count, formats: extensions(data.files)},
    'разбить',
    {count: data.total * parts, format: spState.format});
}

/** Читается сразу после выбора — отдельной кнопки «Прочитать» нет. */
async function spScan(){
  const targets = CHOSEN.spList || [];
  if(!targets.length){
    spState.scan = null;
    ['spOpts', 'spPlace', 'spStyle', 'spPrep', 'spPatternCard', 'spSchema']
      .forEach(id => { $(id).hidden = true; });
    $('spScanned').textContent = 'Файлы читаются сразу после выбора.';
    return;
  }
  showError('');
  $('spScanned').innerHTML = '<span class="spin"></span>Читаем…';
  try{
    const data = await call('/api/split/scan', {
      targets,
      pattern: $('spPattern').value.trim(),
      parts: Number($('spParts').value) || 1,
    });
    spState.scan = data;
    updateListBar('spList', data.file_count);
    $('spScanned').textContent =
      `Файлов: ${data.file_count}, глав: ${data.total}. ` +
      (data.titles.length ? 'Первые: ' + data.titles.join(' · ') : '');
    if(data.unreadable?.length) showError('Не прочитаны: ' + data.unreadable.join('; '));
    $('spOpts').hidden = false;
    $('spPlace').hidden = false;
    $('spPatternCard').hidden = true;
    if(!$('spFolder').value && targets.length === 1){
      const name = targets[0].split(/[/\\]/).pop() || '';
      $('spFolder').value = name.replace(/\.[^.]+$/, '');
    }
    spUpdateFinal();
    // Находка есть — предлагаем очистку сами, не дожидаясь кнопки.
    hdOffer('spList');
  }catch(err){
    $('spScanned').textContent = '';
    $('spOpts').hidden = true;
    $('spPlace').hidden = true;
    // Заголовков не нашлось — наугад не режем, просим шаблон.
    if(err.needPattern){
      $('spPatternCard').hidden = false;
      if(!$('spPattern').value) $('spPattern').value = err.pattern || '';
    }
    showError(err.message);
  }
}
window.spScan = spScan;

async function spStart(){
  showError('');
  $('spStart').disabled = true;
  $('spErrors').hidden = true;
  try{
    const {job} = await call('/api/split/start', {
      targets: CHOSEN.spList || [],
      base: $('spBase').value.trim(),
      folder: $('spFolder').value.trim(),
      format: spState.format,
      pattern: $('spPattern').value.trim(),
      parts: Number($('spParts').value) || 1,
      headings: $('spHeadings').checked,
      encoding: spState.menus.encoding ? spState.menus.encoding.value : 'utf-8',
      style: styleOf('sp', spState.menus),
      prep: prepOf('sp', spState.menus),
    });
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

const mgState = {format: '.txt', job: null, menus: {}, scan: null};

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

/* ------------------------------------------------------------ привязка */

for(const [p, state, update, scan] of [
  ['sp', spState, spUpdateFinal, spScan],
  ['mg', mgState, mgUpdateFinal, mgScan],
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
  $(p + 'Start').onclick = p === 'sp' ? spStart : mgStart;
  $(p + 'Base').addEventListener('input', update);
}

$('spFolder').addEventListener('input', spUpdateFinal);
$('spParts').addEventListener('input', spUpdateFinal);
$('spRescan').onclick = () => spScan();
$('spPattern').addEventListener('keydown', e => { if(e.key === 'Enter') spScan(); });

$('mgName').addEventListener('input', mgUpdateFinal);
mgState.menus.order = makeDropdown($('mgOrder'), () => mgScan());
mgState.menus.separator = makeDropdown($('mgSeparator'), value => {
  // «Свой вариант» открывает поле для ручного ввода.
  $('mgCustom').hidden = value !== 'custom';
});

// Списки форматов строятся по ответу сервера, а не по своему перечню.
function buildAllFormats(){
  buildFormats('spFormats', spState, spUpdateFinal);
  buildFormats('mgFormats', mgState, mgUpdateFinal);
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

    if(finding.kind !== 'title' && finding.text){
      const copy = document.createElement('button');
      copy.className = 'ghost';
      copy.style.padding = '4px 10px';
      copy.textContent = 'скопировать';
      copy.title = 'Чтобы найти место поиском внутри документа';
      copy.onclick = () => hdCopy(finding.text, copy);
      row.append(copy);
    }
    list.append(row);
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

    // Копировать имеет смысл только настоящую строку: «Сдвоенный
    // заголовок главы» — это название правила, а не текст из файла.
    if(rule.kind === 'repeat' || rule.kind === 'neighbour'){
      const copy = document.createElement('button');
      copy.className = 'ghost';
      copy.style.padding = '4px 10px';
      copy.textContent = 'скопировать';
      copy.title = 'Чтобы найти место поиском внутри документа';
      copy.onclick = () => hdCopy(rule.text, copy);
      row.append(copy);
    }
    list.append(row);
  }
  $('hdInsideBox').hidden = hdInside.length === 0;
  hdUpdate();
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
    hdInsideChosen = new Set(hdInside.map(hdKey));
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
  if(found) toast(`В начале файлов нашлась шапка: находок ${found}. `
                  + 'Блок «Мусорная шапка» открыт выше.');
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
    ['anStage1','anStage2','anStage3','anGlossary','anRetell']
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

//: Сколько строк журнала уже показано — дозапрашиваем только хвост.
let anLogSeen = 0, anLogTimer = null;

function anLogDraw(lines){
  logDraw($('anLog'), lines);
}

/** Отрисовка строк журнала. Общая: журналов на экране два — под
 *  прогресс-баром разбора и под кнопкой проверки ключа. */
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

async function anLogTick(jobId){
  try{
    const data = await call(`/api/job/${jobId}/log?since=${anLogSeen}`);
    if(data.lines?.length){
      anLogDraw(data.lines);
      anLogSeen = data.total;
    }
  }catch(err){ /* журнал не повод ронять экран */ }
}

function anLogStart(jobId){
  anLogSeen = 0;
  $('anLog').innerHTML = '';
  $('anLogBox').hidden = false;
  clearInterval(anLogTimer);
  anLogTimer = setInterval(() => anLogTick(jobId), 900);
  $('anLogSave').onclick = () => {
    window.location = `/api/job/${jobId}/log.txt`;
  };
}

function anLogStop(jobId){
  clearInterval(anLogTimer);
  anLogTimer = null;
  // Последний кусок: между опросами могло набежать.
  if(jobId) anLogTick(jobId);
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

    ['anStage2','anGlossary','anStage3','anRetell'].forEach(id => {
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
$('dcLoad').onclick = dcLoad;
$('dcSave').onclick = dcSave;
$('dcSummary').onclick = dcSummary;
$('dcApply').onclick = dcApply;
$('cmpStart').onclick = cmpStart;
cmpLoadKinds();


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
  $('hsNote').textContent =
    `Записей: ${data.records.length}. Копий в корзине: ${data.backups.length} `
    + `(хранится последних ${data.keep}). Папка: ${data.dir}`;

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

function rkWhere(){
  return {
    audience: rkAudMenu ? rkAudMenu.value : '1',
    kind: rkKindMenu ? rkKindMenu.value : '2',
    category: rkCatMenu ? rkCatMenu.value : '',
  };
}

function rkMove(value){
  if(value === null || value === undefined) return {text: '—', cls: 'flat'};
  if(value > 0) return {text: '▲ ' + value, cls: 'up'};
  if(value < 0) return {text: '▼ ' + Math.abs(value), cls: 'down'};
  return {text: '=', cls: 'flat'};
}

function rkRender(){
  const box = $('rkTable');
  box.innerHTML = '';
  const filter = $('rkFilter').value.trim().toLowerCase();
  const shown = rkRows.filter(row => !filter
    || (row.name || '').toLowerCase().includes(filter)
    || (rkTitles[row.book_id] || '').toLowerCase().includes(filter)
    || (row.author || '').toLowerCase().includes(filter));

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
                  row.status, row.last_chapter && 'последняя: ' + row.last_chapter]
                 .filter(Boolean).join(' · ');
    if(row.secret) name.style.opacity = '.7';
    tr.append(name);

    const readers = document.createElement('span');
    readers.className = 'num';
    readers.textContent = ru(row.readers);
    readers.title = 'читающих';
    tr.append(readers);

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
function rkCover(row){
  const box = document.createElement('span');
  box.className = 'cover';

  if(!row.book_id) return box;

  const img = document.createElement('img');
  img.loading = 'lazy';
  img.decoding = 'async';
  img.alt = '';
  img.src = `/api/rank/cover/${encodeURIComponent(row.book_id)}`
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
      ['ссылку', () => put(RK_LINK + row.book_id, 'Ссылка скопирована')],
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
  try{
    const data = await call('/api/rank/categories'
                            + (fetchFromSite ? '?fetch=1' : ''));
    rkCats = data.categories || {};

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
  }catch(err){ showError(err.message); }
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

async function rkRefresh(){
  showError('');
  $('rkRefresh').disabled = true;
  $('rkNote').innerHTML = '<span class="spin"></span>Запрашиваем рейтинг…';
  try{
    const data = await call('/api/rank/refresh', rkWhere());
    rkShow(data);
  }catch(err){
    showError(err.message);
    $('rkNote').textContent = '';
    rkDiagnose(err.details);
  }finally{
    $('rkRefresh').disabled = false;
  }
}

async function rkTranslate(){
  showError('');
  $('rkTranslate').disabled = true;
  try{
    const data = await call('/api/rank/translate',
      {...rkWhere(), model: llmMenu ? llmMenu.value : ''});
    rkTitles = data.titles || {};
    $('rkNote').textContent =
      `Переведено ${data.translated}, из кэша ${data.cached}.`
      + (data.broken ? ` Не разобрано ответов: ${data.broken}.` : '');
    rkRender();
  }catch(err){ showError(err.message); }
  finally{ $('rkTranslate').disabled = false; }
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
      const data = await call(`/api/rank/book/${encodeURIComponent(row.book_id)}`);
      box.innerHTML = '';
      box.append(rkCardBody(row, data));
      box.dataset.filled = '1';
    }catch(err){
      box.innerHTML = '';
      const said = document.createElement('div');
      said.className = 'err local';
      said.hidden = false;
      said.textContent = 'Подробности не пришли: ' + err.message;
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

/** Содержимое раскрытой карточки. */
function rkCardBody(row, data){
  const wrap = document.createElement('div');
  wrap.className = 'rkcard-body';

  const cover = document.createElement('img');
  cover.className = 'rkcard-cover';
  cover.alt = '';
  cover.loading = 'lazy';
  cover.src = `/api/rank/cover/${encodeURIComponent(row.book_id)}`
    + ((data.cover || row.cover) ? `?url=${encodeURIComponent(data.cover || row.cover)}` : '');
  cover.onerror = () => { cover.hidden = true; };

  const side = document.createElement('div');
  side.className = 'rkcard-side';

  const title = document.createElement('div');
  title.className = 'book-name';
  title.textContent = data.secret ? `книга ${row.book_id}`
                                  : (data.name || row.name);
  side.append(title);

  // Описание тоже подменяется шрифтом: пустое место на его месте
  // выглядит как поломка, поэтому говорим прямо.
  const about = document.createElement('p');
  about.className = 'hint';
  about.style.whiteSpace = 'pre-line';
  about.textContent = data.abstract
    || (data.secret ? 'Описание зашифровано шрифтом — расшифровать не вышло.'
                    : 'Описания на странице книги нет.');
  side.append(about);

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
  const rows = [
    ['глав', data.chapters ? ru(data.chapters) : '—'],
    ['знаков', (data.words || row.words) ? ru(data.words || row.words) : '—'],
    ['статус', data.status || row.status || '—'],
    ['читающих', row.readers ? ru(row.readers) : '—'],
  ];
  for(const [name, value] of rows){
    const span = document.createElement('span');
    span.innerHTML = `${name} <b>${value}</b>`;
    stats.append(span);
  }
  side.append(stats);

  const when = [
    data.updated && `обновлено ${rkWhen(data.updated)}`,
    data.first_published && `первая публикация ${rkWhen(data.first_published)}`,
    (data.last_chapter || row.last_chapter)
      && `последняя глава: ${data.last_chapter || row.last_chapter}`,
    data.author && `автор: ${data.author}`,
  ].filter(Boolean);
  if(when.length){
    const line = document.createElement('p');
    line.className = 'hint';
    line.textContent = when.join(' · ');
    side.append(line);
  }

  const buttons = document.createElement('div');
  buttons.className = 'row';
  buttons.style.marginTop = '12px';

  const get = document.createElement('button');
  get.className = 'primary';
  get.style.flex = '1';
  get.textContent = 'Скачать';
  get.onclick = e => { e.stopPropagation(); rkPick(row); };

  const open = document.createElement('button');
  open.className = 'ghost';
  open.textContent = 'Открыть на сайте';
  open.onclick = e => {
    e.stopPropagation();
    window.open(data.link || (RK_LINK + row.book_id), '_blank', 'noopener');
  };

  const copy = document.createElement('button');
  copy.className = 'ghost';
  copy.textContent = 'Скопировать';
  copy.onclick = e => {
    e.stopPropagation();
    openMenu(copy, [
      ['ссылку', async () => toast(
        await copyText(RK_LINK + row.book_id) ? 'Ссылка скопирована'
                                              : 'Скопировать не вышло')],
      ['id', async () => toast(
        await copyText(String(row.book_id)) ? 'Код книги скопирован'
                                            : 'Скопировать не вышло')],
    ]);
  };

  buttons.append(get, open, copy);
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
  rkPicked = row;
  goTab('download');

  // Источник — Fanqie: рейтинг больше ниоткуда не берётся.
  // С `notify`: вместе с источником меняются заполнитель поля и пояснение
  // под ним — у Фанкью в ссылке не слаг, а числовой код.
  if(typeof srcMenu !== 'undefined' && srcMenu) srcMenu.set('fanqie', {notify: true});
  $('q').value = row.book_id;

  // Диапазон чистим сразу, до поиска: пустые поля означают «вся книга»,
  // а числа от прошлого запуска — то самое «конечная глава меньше
  // начальной» на только что выбранной книге.
  $('first').value = '';
  $('last').value = '';
  if(typeof rangeNote === 'function') rangeNote('');

  rkShowCard(row);
  rkCardFlash();

  try{
    // Без подстановки диапазона: поля уже очищены и значат то же самое.
    await find(false);
  }catch(err){ /* показать карточку важнее, чем найти книгу с первого раза */ }
}

/** Карточка «что именно выбрано»: то, что о книге знает рейтинг. */
function rkShowCard(row){
  const card = $('rkCard');
  card.hidden = false;
  $('rkCardName').textContent = row.secret
    ? `книга ${row.book_id}` : (rkTitles[row.book_id] || row.name);
  $('rkCardMeta').textContent = [
    `код ${row.book_id}`,
    row.author && 'автор: ' + row.author,
    row.readers && `${ru(row.readers)} читающих`,
    row.words && `${ru(row.words)} знаков`,
    row.status,
    row.place && `место ${row.place} в срезе`,
  ].filter(Boolean).join('  ·  ');

  // Через свой кэш, как и миниатюра в строке: ссылка с сайта подписана и
  // живёт недолго, а карточка может провисеть на экране весь вечер.
  const cover = $('rkCardCover');
  cover.hidden = !row.book_id;
  if(row.book_id){
    cover.src = `/api/rank/cover/${encodeURIComponent(row.book_id)}`
      + (row.cover ? `?url=${encodeURIComponent(row.cover)}` : '');
    cover.onerror = () => { cover.hidden = true; };
  }
}

/** Доскроллить и подсветить: иначе непонятно, куда книга уехала. */
function rkCardFlash(){
  const card = $('rkCard');
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
rkLoadCategories().then(rkState);
