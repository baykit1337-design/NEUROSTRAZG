/* К-F. Сообщение системы, когда работа кончилась.
 *
 * Мигание заголовка и кольцо в иконке видны только тому, у кого окно
 * браузера на экране. А ночной прогон идёт часами, и человек в это
 * время не в браузере вовсе — он в другой программе или отошёл. До сих
 * пор узнать, что всё кончилось, можно было только вернувшись и
 * посмотрев.
 *
 * Следим за той же разметкой, что и остальные сигналы: законченный блок
 * результата помечен классом `done`. Своих крючков в обработчиках
 * скачивания не заводим — они устарели бы на первой же новой вкладке.
 */

//: Сколько сообщение висит, если система его сама не убирает. Дольше —
//: и это уже не сообщение, а окно, которое надо закрывать.
const FX_NOTE_MS = 12000;

//: Ключ: одинаковые сообщения система складывает в одно, а не вешает
//: стопкой. Ночью работ бывает несколько подряд.
const FX_NOTE_TAG = 'neurostrazh-done';

let fxNoteAsked = false;

/** Умеет ли этот браузер сообщения вообще. */
function fxNoteCan(){
  return typeof Notification !== 'undefined';
}

/** Спросить разрешение — но только с нажатия.
 *
 * Браузеры отказывают в этом вопросе, если он задан сам по себе, без
 * действия человека. Нажатие на кнопку — как раз действие, и работу
 * здесь запускают именно кнопками.
 *
 * Спрашиваем один раз за загрузку страницы: отказ переспрашивать
 * нельзя, а согласие переспрашивать незачем.
 */
function fxNoteAsk(){
  if(fxNoteAsked || !fxNoteCan()) return;
  if(!fxOn('system-note')) return;
  if(Notification.permission !== 'default') return;
  fxNoteAsked = true;
  try{
    // Обещание нам не нужно: следующее сообщение спросит разрешение
    // заново, уже отвеченное.
    const asked = Notification.requestPermission();
    if(asked && asked.catch) asked.catch(() => {});
  }catch(err){
    // Старые браузеры принимают только вид с обработчиком. Не вышло —
    // остаются мигание заголовка и кольцо в иконке.
    console.warn('Сообщения системы недоступны:', err);
  }
}

/** Показать сообщение. Молча ничего не делает, если нельзя. */
function fxNoteShow(text){
  if(!fxOn('system-note') || !fxNoteCan()) return false;
  if(Notification.permission !== 'granted') return false;
  // Вкладка на виду — человек и так всё видит. Сообщение поверх неё
  // сказало бы ему то, что он читает глазами.
  if(!document.hidden) return false;
  try{
    const note = new Notification('NEUROSTRAZH — готово', {
      body: String(text || '').slice(0, 200),
      tag: FX_NOTE_TAG,
    });
    note.onclick = () => { window.focus(); note.close(); };
    setTimeout(() => note.close(), FX_NOTE_MS);
    return true;
  }catch(err){
    // Мобильные браузеры требуют для этого служебного работника и
    // бросаются ошибкой. Не повод ронять страницу.
    console.warn('Сообщение системы не показалось:', err);
    return false;
  }
}

/** Чем кончилось — из самого блока результата.
 *
 * Первая строка блока и есть итог: «Скачано книг: 10 из 13». Собирать
 * её здесь заново значило бы держать вторую копию того же счёта.
 */
function fxNoteText(block){
  const said = (block.innerText || '').trim().split('\n')
    .map(one => one.trim()).filter(Boolean);
  return said.slice(0, 2).join(' · ') || 'Работа закончена';
}

(function fxWatchForDone(){
  if(!fxNoteCan()) return;

  // Разрешение спрашиваем с любого нажатия: работу запускают кнопками,
  // а какой именно — знать здесь не надо.
  document.addEventListener('click', fxNoteAsk, true);

  const observer = new MutationObserver(records => {
    for(const record of records){
      const node = record.target;
      if(!(node instanceof Element)) continue;
      if(!node.classList.contains('result-block')) continue;

      const done = node.classList.contains('done');
      const was = node.dataset.fxNoted === '1';
      node.dataset.fxNoted = done ? '1' : '0';
      if(done && !was) fxNoteShow(fxNoteText(node));
    }
  });
  observer.observe(document.body,
    {subtree: true, attributes: true, attributeFilter: ['class']});
})();
