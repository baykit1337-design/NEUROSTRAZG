/* Вкладки «Переименовать», «В Word» и «Проверка текста».
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

// На вкладках «Качалка» и «Разбить» проводник отдаёт путь через скрытое
// поле, а дальше подхватывает их собственный обозреватель.
$('baseHidden').addEventListener('input', e => browse(e.target.value));
$('spBaseHidden').addEventListener('input', e => browseSplitOut(e.target.value));
$('bookHidden').addEventListener('input', e => {
  const path = e.target.value;
  if(path) pickBook({path, name: path.split(/[/\\]/).pop()});
});


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
const rnSplits = {};      // путь к файлу -> на сколько частей
const rnChosen = new Set();  // отмеченные главы

function rnFormat(){
  return {
    number: $('rnNum').checked,
    part: $('rnPart').checked,
    title: $('rnTitle').checked,
    prefix: $('rnPrefix').value,
    separator: $('rnSep').value,
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
    skip_service: $('rnSkipService').checked,
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
  const first = rnChapters.find(c => !c.service);
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
  const button = $('rnScan');
  button.disabled = true;
  try{
    const data = await call('/api/rename/scan', {
      folder_in: $('rnIn').value.trim(),
      pattern: $('rnPattern').value.trim(),
    });
    rnChapters = data.chapters;
    rnChosen.clear();
    Object.keys(rnSplits).forEach(k => delete rnSplits[k]);

    $('rnScanned').textContent =
      `Файлов: ${data.total}` + (data.service ? `, служебных: ${data.service}` : '');
    $('rnServiceNote').textContent = data.service
      ? `Служебных файлов: ${data.service}. Снимите галочку, чтобы переименовать их вручную.`
      : 'Служебных файлов не найдено.';
    ['rnPatternCard','rnFormat','rnListCard','rnPlace'].forEach(id => { $(id).hidden = false; });
    if(!$('rnOut').value) $('rnOut').value = 'Готово';

    rnRenderList();
    rnUpdateExample();
    await rnBuildPreview();
  }catch(err){
    showError(err.message);
    $('rnPatternCard').hidden = false;
  }finally{
    button.disabled = false;
  }
}

function rnRenderList(){
  const list = $('rnList');
  list.innerHTML = '';
  for(const chapter of rnChapters){
    const row = document.createElement('div');
    row.className = 'tr' + (chapter.service ? ' service' : '');

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = rnChosen.has(chapter.path);
    box.disabled = chapter.service;
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
    if(chapter.service){
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = 'служебный';
      row.append(tag);
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
  $('rnSelected').textContent = rnChosen.size ? `— отмечено ${rnChosen.size}` : '';
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
        return drawProgress(p, 'rnFill', 'rnStatus', 'rnPct');
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

$('rnScan').onclick = rnScan;
$('rnAll').onclick = () => {
  rnChapters.filter(c => !c.service).forEach(c => rnChosen.add(c.path));
  rnRenderList();
};
$('rnNone').onclick = () => { rnChosen.clear(); rnRenderList(); };
$('rnHalve').onclick = () => rnApplySplit(2);
$('rnSplit').onclick = rnAskParts;
$('rnRenumber').onchange = () => {
  $('rnStart').disabled = !$('rnRenumber').checked;
  rnBuildPreview();
};
['rnNum','rnPart','rnTitle','rnSkipService'].forEach(id => {
  $(id).onchange = () => { rnUpdateExample(); rnBuildPreview(); };
});
['rnPrefix','rnStart'].forEach(id => {
  $(id).addEventListener('input', () => { rnUpdateExample(); rnBuildPreview(); });
});
$('rnSep').onchange = () => { rnUpdateExample(); rnBuildPreview(); };
$('rnPattern').addEventListener('keydown', e => { if(e.key === 'Enter') rnScan(); });
document.querySelectorAll('.pick2').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.pick2').forEach(b => b.classList.toggle('on', b === btn));
    rnFmtOut = btn.dataset.fmt;
  };
});
$('rnPartsOk').onclick = () => {
  $('rnDialog').hidden = true;
  rnApplySplit(parseInt($('rnParts').value, 10));
};
$('rnPartsCancel').onclick = () => { $('rnDialog').hidden = true; };
$('rnApply').onclick = rnApply;
$('rnStop').onclick = () => stopJob(rnJob);

/* ============================== В Word ============================== */

let wdMode = 'single', wdJob = null, wdAlign = null, wdScene = null;

//: Пояснение под каждым режимом — что получится на выходе.
const WD_MODE_NOTES = {
  single: 'Все главы из выбранного лягут в один файл .docx.',
  per_chapter: 'Каждая глава станет отдельным файлом .docx в новой папке.',
};

function wdStyle(){
  return {
    font: $('wdFont').value.trim() || 'Times New Roman',
    size: $('wdSize').value,
    line_spacing: $('wdSpacing').value,
    first_line_indent_cm: $('wdIndent').value,
    page_break_between_chapters: $('wdBreak').checked,
  };
}

function wdPrep(){
  return {
    strip_title: $('wdStripTitle').checked,
    italic_system: $('wdItalicSystem').checked,
    align: wdAlign ? wdAlign.value : 'left',
    scene_style: wdScene ? wdScene.value : 'stars',
    first_line_indent_cm: $('wdIndent').value,
  };
}

function wdUpdateFinal(){
  const base = $('wdBase').value.trim(), name = $('wdName').value.trim();
  $('wdFinal').textContent = base && name
    ? (wdMode === 'single' ? `Документ: ${base}/${name}.docx` : `Папка: ${base}/${name}`)
    : '';
  $('wdModeNote').textContent = WD_MODE_NOTES[wdMode] || '';
}

/** Читается сразу после выбора — отдельной кнопки «Прочитать» больше нет. */
async function wdScan(){
  const targets = CHOSEN.wdList || [];
  if(!targets.length){
    $('wdOpts').hidden = true;
    $('wdScanned').textContent = 'Файлы читаются сразу после выбора.';
    return;
  }
  showError('');
  $('wdScanned').innerHTML = '<span class="spin"></span>Читаем…';
  try{
    const data = await call('/api/word/scan', {targets});
    $('wdScanned').textContent =
      `Файлов: ${data.file_count}, глав: ${data.total}. ` +
      (data.titles.length ? 'Первые: ' + data.titles.join(' · ') : '');
    if(data.unreadable?.length){
      showError('Не прочитаны: ' + data.unreadable.join('; '));
    }
    $('wdOpts').hidden = false;
    if(!$('wdName').value) $('wdName').value = 'Книга';
    wdUpdateFinal();
  }catch(err){
    showError(err.message);
    $('wdOpts').hidden = true;
    $('wdScanned').textContent = '';
  }
}
window.wdScan = wdScan;

async function wdStart(){
  showError('');
  $('wdStart').disabled = true;
  $('wdErrors').hidden = true;
  try{
    const {job} = await call('/api/word/start', {
      targets: CHOSEN.wdList || [],
      base: $('wdBase').value.trim(),
      name: $('wdName').value.trim(),
      mode: wdMode,
      style: wdStyle(),
      prep: wdPrep(),
    });
    wdJob = job.id;
    $('wdProgress').hidden = false;
    $('wdStop').hidden = false;
    $('wdSummary').textContent = 'Результат: ' + job.output_dir;

    pollJob(job.id,
      job => {
        const p = job.progress || {};
        $('wdWritten').textContent = p.written || p.done || 0;
        $('wdFailed').textContent = p.failed || 0;
        return drawProgress(p, 'wdFill', 'wdStatus', 'wdPct');
      },
      job => {
        $('wdStop').hidden = true;
        if(job.error) showError(job.error);
        // Молчаливых отказов быть не должно: показываем каждую осечку.
        const failures = job.report?.failures || [];
        if(failures.length){
          const table = $('wdErrors');
          table.innerHTML = '';
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
      });
  }catch(err){
    showError(err.message);
  }finally{
    $('wdStart').disabled = false;
  }
}

document.querySelectorAll('.pick3').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.pick3').forEach(b => b.classList.toggle('on', b === btn));
    wdMode = btn.dataset.mode;
    wdUpdateFinal();
  };
});
$('wdList').dataset.onchange = 'wdScan';
$('wdStart').onclick = wdStart;
$('wdStop').onclick = () => stopJob(wdJob);
['wdBase','wdName'].forEach(id => $(id).addEventListener('input', wdUpdateFinal));
wdAlign = makeDropdown($('wdAlign'));
wdScene = makeDropdown($('wdScene'));
wdUpdateFinal();

/* ========================== Проверка текста ========================== */

//: Тип проверки → подпись и всплывающая подсказка.
const CHECK_KINDS = [
  ['cjk', 'Иероглифы и азиатские алфавиты',
   'Куски текста, оставшиеся непереведёнными: китайские, корейские, японские символы.'],
  ['markdown', 'Остатки markdown',
   'Служебные символы разметки (**, ##, ---), которые модель оставила в тексте.'],
  ['latin', 'Латиница в русском тексте',
   'Английские слова, которые могли остаться без перевода. Часто это имена — смотреть глазами.'],
  ['model', 'Следы модели-переводчика',
   'Фразы вроде «Вот перевод» или «Translator\u2019s note», случайно попавшие в текст.'],
  ['broken', 'Битая кодировка и HTML',
   'Испорченные символы и неубранные теги вроде &nbsp; или <br>.'],
  ['loop', 'Зацикливание модели',
   'Один и тот же абзац повторён три раза подряд и больше. Так бывает, когда модель «залипает».'],
  ['size', 'Подозрительный объём',
   'Глава заметно короче или длиннее остальных. Возможно, перевод оборвался.'],
  ['pairs', 'Непарные кавычки и скобки',
   'Открывающая есть, закрывающей нет.'],
];

//: Что умеет чистить кнопка «Очистить».
const CLEAN_KINDS = [
  ['markdown', 'Остатки markdown'],
  ['html', 'HTML-теги и entity'],
  ['nbsp', 'Неразрывные пробелы'],
  ['broken', 'Битые символы'],
  ['model', 'Следы модели-переводчика'],
  ['dupes', 'Повторяющиеся абзацы'],
  ['blanks', 'Лишние пустые строки'],
];

let ckJob = null, ckFindings = [], ckFilter = null, ckCleanJob = null;

(function ckBuildChecks(){
  const box = $('ckKinds');
  for(const [key, label, tip] of CHECK_KINDS){
    const wrap = document.createElement('label');
    wrap.className = 'chk';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = key;
    input.checked = true;
    wrap.append(input, document.createTextNode(' ' + label));
    attachTip(wrap, tip);
    box.append(wrap);
  }

  const clean = $('ckCleanKinds');
  for(const [key, label] of CLEAN_KINDS){
    const wrap = document.createElement('label');
    wrap.className = 'chk';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = key;
    input.checked = true;
    wrap.append(input, document.createTextNode(' ' + label));
    clean.append(wrap);
  }
})();

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
      job => drawProgress(job.progress || {}, 'ckFill', 'ckStatus'),
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

  ckRenderTable();
  $('ckResults').hidden = false;
  $('ckCleanCard').hidden = false;
}

/** Все находки доступны в самом окне: список рисуется по мере прокрутки. */
function ckRenderTable(){
  const needle = $('ckSearch').value.trim().toLowerCase();
  let rows = ckFilter ? ckFindings.filter(f => f.kind === ckFilter) : ckFindings;
  if(needle){
    rows = rows.filter(f =>
      f.fragment.toLowerCase().includes(needle) || f.file.toLowerCase().includes(needle));
  }
  $('ckCount').textContent = `— ${rows.length}` +
    (rows.length !== ckFindings.length ? ` из ${ckFindings.length}` : '');

  const table = $('ckTable');
  table.innerHTML = '';
  table.onscroll = null;

  // Виртуальный список: в DOM держим только видимую часть, поэтому даже
  // 30 тысяч находок открываются без обрезки и без подвисаний.
  const ROW = 31;
  const spacer = document.createElement('div');
  spacer.style.height = rows.length * ROW + 'px';
  spacer.style.position = 'relative';
  table.append(spacer);

  function draw(){
    const top = table.scrollTop;
    const height = table.clientHeight || 400;
    const first = Math.max(0, Math.floor(top / ROW) - 5);
    const last = Math.min(rows.length, Math.ceil((top + height) / ROW) + 5);

    spacer.innerHTML = '';
    for(let i = first; i < last; i++){
      const finding = rows[i];
      const line = document.createElement('div');
      line.className = 'tr';
      line.style.position = 'absolute';
      line.style.top = i * ROW + 'px';
      line.style.left = '0';
      line.style.right = '0';

      const file = document.createElement('span');
      file.className = 'grow';
      file.textContent = finding.file;
      file.title = finding.file;

      const lineNo = document.createElement('span');
      lineNo.className = 'num';
      lineNo.textContent = 'стр. ' + finding.line;

      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = finding.kind_name;

      const fragment = document.createElement('span');
      fragment.className = 'grow';
      fragment.textContent = finding.fragment;
      fragment.title = finding.fragment;

      line.append(file, lineNo, tag, fragment);
      spacer.append(line);
    }
  }

  table.onscroll = draw;
  draw();
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
    $('ckProgress').hidden = false;
    $('ckStop').hidden = false;

    pollJob(job.id,
      job => drawProgress(job.progress || {}, 'ckFill', 'ckStatus'),
      job => {
        $('ckStop').hidden = true;
        if(job.error){ showError(job.error); return; }
        const report = job.report || {};
        // Отчёт: что и сколько исправлено.
        const parts = (report.counts || []).map(r => `${r.kind_name}: ${r.count}`);
        $('ckCleanResult').style.whiteSpace = 'pre-line';
        $('ckCleanResult').textContent =
          `Готово. Папка: ${report.output_dir}\n` +
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
