/* Встряска блока с ошибкой (эффект `error-shake`).
 *
 * Сообщение появлялось молча и на своём месте — под карточкой, где на
 * него можно и не посмотреть. Хуже всего это на втором нажатии той же
 * кнопки: текст тот же, блок тот же, и понять, что запрос вообще был,
 * нечем.
 *
 * Поэтому встряска запускается не появлением блока, а самим вызовом
 * `showError`. Появление можно было бы поймать и стилями, но повтор —
 * нет, а повтор здесь и есть главный случай.
 */

/** Сколько длится встряска. Держать в согласии с `error-shake.css`. */
const SHK_MS = 420;

function shkOn(){
  return document.documentElement.classList.contains('fx-error-shake');
}

function shkHit(box){
  // Снять и навесить заново, прочитав между этим размер: без чтения
  // браузер объединит обе правки, класс останется на месте, и повторная
  // ошибка пройдёт беззвучно — ровно тот случай, ради которого всё это.
  box.classList.remove('fx-shake');
  void box.offsetHeight;
  box.classList.add('fx-shake');
  setTimeout(() => box.classList.remove('fx-shake'), SHK_MS + 120);
}

(function shkWatch(){
  if(typeof showError !== 'function') return;
  const was = showError;

  showError = function(message){
    const out = was.apply(this, arguments);
    if(!message || !shkOn()) return out;

    // Показанным остаётся ровно один блок: `showError` гасит прежний
    // перед тем, как зажечь новый. Но искать его по имени незачем —
    // берём тот, что виден.
    for(const box of document.querySelectorAll('.err')){
      if(!box.hidden && (box.textContent || '').trim()) shkHit(box);
    }
    return out;
  };
})();
