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

// Появление с задержкой 400 мс, чтобы не мельтешили.
const TOOLTIP_DELAY = 400;

document.querySelectorAll('.hint-icon').forEach(icon => {
  const tip = document.createElement('span');
  tip.className = 'tooltip';
  tip.textContent = icon.dataset.tip || '';
  icon.append(tip);

  let timer = null;
  icon.addEventListener('mouseenter', () => {
    timer = setTimeout(() => tip.classList.add('visible'), TOOLTIP_DELAY);
  });
  icon.addEventListener('mouseleave', () => {
    clearTimeout(timer);
    tip.classList.remove('visible');
  });
});

// Раздел 12: подсказка вешается прямо на элемент, значок вопроса не нужен.
document.querySelectorAll('.tipped').forEach(node => {
  const tip = document.createElement('span');
  tip.className = 'tooltip';
  tip.textContent = node.dataset.tip || '';
  node.append(tip);

  let timer = null;
  node.addEventListener('mouseenter', () => {
    timer = setTimeout(() => tip.classList.add('visible'), TOOLTIP_DELAY);
  });
  node.addEventListener('mouseleave', () => {
    clearTimeout(timer);
    tip.classList.remove('visible');
  });
});

/** Ставит подсказку на произвольный элемент (для галочек, что строит JS). */
function attachTip(element, text){
  if(!text) return;
  const icon = document.createElement('i');
  icon.className = 'hint-icon';
  icon.textContent = '?';
  const tip = document.createElement('span');
  tip.className = 'tooltip';
  tip.textContent = text;
  icon.append(tip);

  let timer = null;
  icon.addEventListener('mouseenter', () => {
    timer = setTimeout(() => tip.classList.add('visible'), TOOLTIP_DELAY);
  });
  icon.addEventListener('mouseleave', () => {
    clearTimeout(timer);
    tip.classList.remove('visible');
  });
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
      подобранную по умолчанию надо отметить уже после отрисовки. */
  function set(key){
    if(!options.some(o => o[0] === key)) return false;
    value = key;
    menu.querySelectorAll('.dropdown-item').forEach((item, index) => {
      item.classList.toggle('selected', options[index][0] === key);
    });
    label();
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
  return busy;
}

/** Опрашивает задачу до конца. onDone получает готовый job. */
function pollJob(jobId, draw, onDone){
  const timer = setInterval(async () => {
    try{
      const {job} = await call('/api/job/' + jobId);
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

let rnChapters = [], rnRows = [], rnFmtOut = 'txt', rnJob = null, rnTimer = null;
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

    rnRenderList();
    rnUpdateExample();
    await rnBuildPreview();
    hdOffer('rnIn');
  }catch(err){
    showError(err.message);
    $('rnPatternCard').hidden = false;
  }
}

function rnRenderList(){
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
      if(chapter.suspect_reason) attachTip(tag, chapter.suspect_reason);
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
  rnUpdateChosen();
}

function rnUpdateChosen(){
  $('rnSelected').textContent =
    `— отмечено ${rnChosen.size} из ${rnChapters.length}`;
  rnBuildPreview();
}

async function rnBuildPreview(){
  try{
    const data = await call('/api/rename/plan', rnPayload());
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
    $('rnApply').disabled = !data.rows.length;
    $('rnApplyHint').textContent = data.rows.length
      ? `Будет создано файлов: ${data.rows.length}. Оригиналы не изменятся.`
      : 'Нечего переименовывать.';
  }catch(err){
    showError(err.message);
    $('rnApply').disabled = true;
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
      out_format: rnFmtOut,
      names: rnRows.map(r => r.new_name),
    });
    rnJob = job.id;
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
        if(job.error) showError(job.error);
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
// Кнопки формата на выходе. Переключаем в пределах своей строки: тот же
// класс носят кнопки режима в качалке, и общий обработчик их затирал.
document.querySelectorAll('.pick2[data-fmt]').forEach(btn => {
  btn.onclick = () => {
    btn.parentNode.querySelectorAll('.pick2[data-fmt]')
       .forEach(b => b.classList.toggle('on', b === btn));
    rnFmtOut = btn.dataset.fmt;
  };
});
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
        if(job.error){ showError(job.error); return; }
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
    $('mgScanned').textContent =
      `Файлов: ${data.file_count}, глав: ${data.total}. ` +
      (data.titles.length ? 'Первые: ' + data.titles.join(' · ') : '');
    if(data.unreadable?.length) showError('Не прочитаны: ' + data.unreadable.join('; '));
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
        if(job.error){ showError(job.error); return; }
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
call('/api/formats').then(data => {
  FORMATS = data;
  buildFormats('spFormats', spState, spUpdateFinal);
  buildFormats('mgFormats', mgState, mgUpdateFinal);
}).catch(() => {
  buildFormats('spFormats', spState, spUpdateFinal);
  buildFormats('mgFormats', mgState, mgUpdateFinal);
});

spUpdateFinal();
mgUpdateFinal();



/* ===================== Очистка мусорной шапки =====================
 *
 * Один блок на три вкладки: «Разбить», «Объединить», «Переименовать».
 * Жёстких правил нет — сервер считает повторы и присылает находки, а
 * решает человек галочками.
 */

let hdSource = null, hdFindings = [], hdChosen = new Set(), hdJob = null;

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

    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = `${finding.count} из ${finding.total}`;

    row.append(box, text, tag);
    list.append(row);
  }
  hdUpdate();
}

function hdUpdate(){
  $('hdClean').disabled = hdChosen.size === 0;
  $('hdClean').textContent = hdChosen.size
    ? `Удалить отмеченное (${hdChosen.size})` : 'Удалить отмеченное';
}

async function hdScan(source, quiet){
  hdSource = source;
  const targets = hdTargets();
  if(!targets.length){
    if(!quiet) showError('Сначала выберите файлы или папку');
    return 0;
  }

  if(!quiet){
    $('hdCard').hidden = false;
    $('hdIntro').innerHTML = '<span class="spin"></span>Читаем начала файлов…';
    $('hdList').innerHTML = '';
    $('hdPlace').hidden = true;
  }
  try{
    const data = await call('/api/headers/scan', {targets});
    hdFindings = data.findings || [];
    hdChosen = new Set(hdFindings.map(f => f.text));

    if(!hdFindings.length){
      if(!quiet){
        $('hdCard').hidden = false;
        $('hdIntro').textContent =
          `Файлов: ${data.file_count}. Повторяющихся строк в начале не нашлось.`;
        $('hdPlace').hidden = true;
      }
      return 0;
    }

    $('hdCard').hidden = false;
    $('hdIntro').textContent =
      `Файлов: ${data.file_count}. Строки ниже повторяются почти в каждом — `
      + 'это шапка, а не содержание. Снимите галочку, если строка нужна.';
    $('hdPlace').hidden = false;
    if(!$('hdFolder').value) $('hdFolder').value = 'Без шапок';
    hdRender();
    return hdFindings.length;
  }catch(err){
    if(!quiet) showError(err.message);
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
        if(job.error){ showError(job.error); return; }
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


/* ===================== Настройки модели (часть 2) =====================
 *
 * Пользователь вводит только ключ: список моделей и выбор по умолчанию
 * программа получает сама. Недействительный ключ виден сразу, при вводе,
 * а не при первом разборе главы.
 */

let llmMenu = null, llmModels = [];

/** Ключ в поле показывается точками, пока не нажали «Показать». */
$('llmShow').onclick = () => {
  const field = $('llmKey');
  const hidden = field.type === 'password';
  field.type = hidden ? 'text' : 'password';
  $('llmShow').textContent = hidden ? 'Скрыть' : 'Показать';
};

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

async function llmCheck(){
  showError('');
  $('llmCheck').disabled = true;
  const note = $('llmKeyNote');
  const original = note.textContent;
  note.innerHTML = '<span class="spin"></span>Спрашиваем список моделей…';
  try{
    const data = await call('/api/llm/check', {key: $('llmKey').value.trim()});
    note.textContent = `Ключ рабочий: ${data.key}. Моделей доступно: ${data.models.length}.`;
    $('llmSetup').hidden = false;
    llmFillModels(data.models, data.suggested);
  }catch(err){
    note.textContent = original;
    $('llmSetup').hidden = true;
    showError(err.message);
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
      `Сохранено: ключ ${data.key}, модель ${data.model}.`;
    $('llmKey').value = '';
    $('llmKey').placeholder = data.key;
  }catch(err){
    showError(err.message);
  }finally{
    $('llmSave').disabled = false;
  }
}

$('llmCheck').onclick = llmCheck;
$('llmSave').onclick = llmSave;

// Что уже настроено — показываем при запуске. Ключ только маскированный.
call('/api/llm/state').then(data => {
  if(!data.configured) return;
  $('llmKey').placeholder = data.key;
  $('llmProxy').checked = data.use_proxies;
  $('llmKeyNote').textContent =
    `Ключ уже сохранён: ${data.key}` + (data.model ? `, модель ${data.model}.` : '.')
    + ' Введите новый, чтобы заменить.';
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
  if(!targets.length){
    ['anStage1','anStage2','anStage3','anGlossary'].forEach(id => { $(id).hidden = true; });
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

async function anStart(){
  showError('');
  $('anStart').disabled = true;
  try{
    const {job} = await call('/api/analyze/start',
      anPayload({force: $('anForce').checked}));
    anJob = job.id;
    $('anProgress').hidden = false;
    $('anStop').hidden = false;
    $('anSummary').textContent = 'Папка: ' + job.output_dir;

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('anWritten').textContent = p.written || p.done || 0;
        $('anFailed').textContent = p.failed || 0;
        return drawResult(p, 'anFill', 'anStatus', 'anPct');
      },
      async job => {
        $('anStop').hidden = true;
        if(job.error){ showError(job.error); return; }
        const r = job.report || {};
        let text = `Папка: ${r.output || job.output_dir}`;
        if(r.failed_files?.length){
          text += '\n' + r.failed_files.slice(0, 20).join('\n');
        }
        $('anSummary').style.whiteSpace = 'pre-line';
        $('anSummary').textContent = text;
        await anLoadRegistry();
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('anStart').disabled = false;
  }
}

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

    ['anStage2','anGlossary','anStage3'].forEach(id => {
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
$('anStart').onclick = anStart;
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
    $('ckProgress').hidden = false;
    $('ckStop').hidden = false;
    $('ckSave').hidden = true;

    pollJob(job.id,
      job => drawResult(job.progress || {}, 'ckFill', 'ckStatus'),
      job => {
        $('ckStop').hidden = true;
        if(job.error){ showError(job.error); return; }
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
    $('ckCleanResultBox').hidden = false;

    pollJob(job.id,
      job => drawResult(job.progress || {}, 'ckCleanFill', 'ckCleanStatus'),
      job => {
        if(job.error){ showError(job.error); return; }
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
