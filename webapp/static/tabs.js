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
  return {get value(){ return value; }};
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
}

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
document.querySelectorAll('.pick2').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.pick2').forEach(b => b.classList.toggle('on', b === btn));
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

const spState = {format: '.txt', job: null, menus: {}};

function spUpdateFinal(){
  const base = $('spBase').value.trim(), name = $('spFolder').value.trim();
  $('spFinal').textContent = base && name
    ? `Главы лягут в: ${base}/${name}  (${spState.format})` : '';
  toggleOptions('sp', spState.format);
}

/** Читается сразу после выбора — отдельной кнопки «Прочитать» нет. */
async function spScan(){
  const targets = CHOSEN.spList || [];
  if(!targets.length){
    ['spOpts', 'spPlace', 'spStyle', 'spPrep', 'spPatternCard']
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

const mgState = {format: '.txt', job: null, menus: {}};

function mgUpdateFinal(){
  const base = $('mgBase').value.trim(), name = $('mgName').value.trim();
  $('mgFinal').textContent = base && name
    ? `Файл: ${base}/${name}${mgState.format}` : '';
  toggleOptions('mg', mgState.format);
}

async function mgScan(){
  const targets = CHOSEN.mgList || [];
  if(!targets.length){
    ['mgOpts', 'mgPlace', 'mgStyle', 'mgPrep'].forEach(id => { $(id).hidden = true; });
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
