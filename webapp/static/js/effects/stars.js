/* Живое звёздное поле (часть 5 ТЗ NEUROSTRAZH).
 *
 * Точки раньше стояли намертво и двигались только при прокрутке. Небо от
 * этого выглядело нарисованным: настоящее слегка дышит само по себе.
 *
 * Всё поле — один `canvas`. Полторы сотни отдельных элементов, каждый со
 * своей анимацией, браузер пересчитывает на каждом кадре и тратит на это
 * больше, чем на всю остальную страницу; на холсте это один проход.
 *
 * Движения нарочно медленные. Точка уходит в полную невидимость и оттуда
 * же разгорается, у каждой свой цикл и своя фаза: пока одни гаснут,
 * другие светят. Ускорять это нельзя — быстрое мерцание превращает фон в
 * гирлянду и отвлекает от текста, ради которого программа и написана.
 */

//: Сколько точек. Меньше сотни — пусто, больше двух сотен — рябит.
const STARS_MIN = 120;
const STARS_MAX = 180;

//: Три группы по глубине: доля, границы яркости, размер.
//:
//: Нижняя граница — ноль: точка уходит в полную невидимость и оттуда же
//: разгорается. С ненулевым `dim` она тускнела, но оставалась на месте
//: светлым пятном, и «затухание» читалось как перепад яркости, а не как
//: исчезновение.
const STARS_DEPTHS = [
  {share: 0.60, dim: 0.00, bright: 0.25, size: 1.0, glow: false},
  {share: 0.30, dim: 0.00, bright: 0.50, size: 1.5, glow: false},
  {share: 0.10, dim: 0.00, bright: 0.85, size: 2.0, glow: true},
];

//: Мерцание: длительность полного цикла у каждой точки своя. Медленно и
//: вразнобой — пока одни гаснут, другие разгораются. Короткий цикл
//: превращает поле в гирлянду, а это уже не фон, а мигалка.
const STARS_BLINK_MIN = 4000;
const STARS_BLINK_MAX = 12000;

//: Переезд: раз в столько-то одна точка гаснет и появляется в новом месте.
const STARS_MOVE_MIN = 6000;
const STARS_MOVE_MAX = 10000;

//: Сколько длится угасание и сколько — появление.
const STARS_FADE_MIN = 2000;
const STARS_FADE_MAX = 3000;

//: Сколько точек могут переезжать одновременно.
const STARS_MOVING_MAX = 3;

//: Новое место не ближе этого к соседям, иначе точки сбиваются в кучки.
const STARS_APART = 40;

//: Дрейф всего поля: пикселей в минуту и как часто менять направление.
//: Полтора пикселя в минуту — это пиксель за сорок секунд, то есть поле
//: стояло на месте: за весь прогон книги оно уезжало на семь пикселей.
//: Восемь — сорок пикселей за пять минут: движение видно, но никуда не
//: спешит. Мерцание и затухание тут ни при чём, они отдельно.
const STARS_DRIFT = 8;
const STARS_TURN_MIN = 120000;
const STARS_TURN_MAX = 300000;

//: Параллакс при прокрутке. У ближних точек он в разы сильнее.
const STARS_PARALLAX = 0.02;
const STARS_PARALLAX_DEPTH = 3;

//: Каждая десятая точка — с фиолетовым оттенком: чистый белый на фоне
//: темы выглядит инородным.
const STARS_VIOLET = 10;
const STARS_WHITE = '255, 255, 255';
const STARS_LILAC = '201, 167, 255';

//: Насколько выше и ниже экрана простирается поле: при прокрутке снизу
//: не должно появляться пустоты.
const STARS_MARGIN = 0.3;

function starsOn(){
  return document.documentElement.classList.contains('fx-stars');
}

//: Свой дрейф у каждой точки: пикселей в минуту. Опыт включают, чтобы
//: посмотреть на движение, поэтому оно должно быть видно: девять
//: пикселей в минуту — это пиксель за семь секунд, то есть ничего.
//: Здесь три пикселя в секунду: точки заметно расходятся, но никуда не
//: летят.
const STARS_WANDER = 180;

/** Включён ли опыт «звёзды расходятся врозь» (своя галочка эффектов). */
function starsWander(){
  return document.documentElement.classList.contains('fx-star-wander');
}

function starsCalm(){
  return window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function starsBetween(from, to){
  return from + Math.random() * (to - from);
}

(function starfield(){
  let canvas = null, ctx = null, stars = [], running = false;
  let width = 0, height = 0, ratio = 1;
  //: Дрейф: куда и с какой скоростью ползёт всё поле.
  let driftX = 0, driftY = 0, driftAngle = Math.random() * Math.PI * 2;
  let turnAt = 0, movedAt = 0, lastFrame = 0;
  //: Сколько кадров отрисовано. Нужен только для слепка состояния: по
  //: нему видно, идёт цикл или встал после первого кадра.
  let frames = 0;

  /* Системное «уменьшить движение». Читаем один раз и следим за сменой:
   * `matchMedia` шестьдесят раз в секунду — лишняя работа на ровном месте.
   *
   * Раньше при этой настройке поле рисовало один кадр и замирало совсем —
   * та самая статичная картинка (4.1 ТЗ). Настройка, однако, про
   * перемещение, а не про яркость: укачивает движение, а не медленный
   * перелив. Поэтому в тихом режиме гаснут дрейф, переезды и параллакс —
   * всё, что двигает точки, — а мерцание остаётся: небо живёт, но ничто
   * по экрану не ездит. */
  let calm = starsCalm();
  if(window.matchMedia){
    const watchCalm = window.matchMedia('(prefers-reduced-motion: reduce)');
    const noted = () => { calm = watchCalm.matches; };
    if(watchCalm.addEventListener) watchCalm.addEventListener('change', noted);
    else if(watchCalm.addListener) watchCalm.addListener(noted);
  }

  function depthOf(){
    const roll = Math.random();
    let sum = 0;
    for(let index = 0; index < STARS_DEPTHS.length; index++){
      sum += STARS_DEPTHS[index].share;
      if(roll <= sum) return index;
    }
    return 0;
  }

  /** Место подальше от соседей — иначе точки собираются в кучки. */
  function freeSpot(){
    for(let tries = 0; tries < 12; tries++){
      const x = Math.random() * width;
      const y = Math.random() * height;
      let near = false;
      for(const star of stars){
        if(Math.hypot(star.x - x, star.y - y) < STARS_APART){ near = true; break; }
      }
      if(!near) return {x, y};
    }
    // Не нашлось за дюжину попыток — ставим как есть: пустое место на
    // небе хуже, чем пара точек поближе друг к другу, чем хотелось бы.
    return {x: Math.random() * width, y: Math.random() * height};
  }

  function makeStar(index){
    const depth = depthOf();
    const rule = STARS_DEPTHS[depth];
    const spot = freeSpot();
    return {
      x: spot.x, y: spot.y,
      depth,
      size: rule.size,
      glow: rule.glow,
      dim: rule.dim, bright: rule.bright,
      colour: index % STARS_VIOLET === 0 ? STARS_LILAC : STARS_WHITE,
      // Своя длительность и своя фаза: иначе точки мигают хором, а это
      // читается как поломка, а не как небо.
      cycle: starsBetween(STARS_BLINK_MIN, STARS_BLINK_MAX),
      phase: Math.random() * Math.PI * 2,
      // Переезд: 0 — стоит на месте, иначе доля прожитого перехода.
      leaving: 0, arriving: 0, fade: 0,
      // Свой дрейф: куда и с какой скоростью ползёт именно эта точка.
      // Считается всегда, применяется только при включённой галочке —
      // так опыт не переписывает поле, а добавляется к нему.
      wanderAngle: Math.random() * Math.PI * 2,
      wanderRate: starsBetween(STARS_WANDER * 0.4, STARS_WANDER),
      wx: 0, wy: 0,
    };
  }

  function build(){
    stars = [];
    const count = STARS_MIN + Math.floor(Math.random() * (STARS_MAX - STARS_MIN));
    for(let n = 0; n < count; n++) stars.push(makeStar(n));
  }

  function resize(){
    if(!canvas) return;
    ratio = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight * (1 + STARS_MARGIN * 2);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  /** Яркость точки прямо сейчас: мерцание плюс переезд. */
  function shineOf(star, now){
    const wave = (Math.sin(now / star.cycle * Math.PI * 2 + star.phase) + 1) / 2;
    let shine = star.dim + (star.bright - star.dim) * wave;
    if(star.leaving){
      shine *= Math.max(0, 1 - (now - star.leaving) / star.fade);
    }else if(star.arriving){
      shine *= Math.min(1, (now - star.arriving) / star.fade);
    }
    return shine;
  }

  /** Одна случайная точка гаснет и появляется в новом месте. */
  function relocate(now){
    const busy = stars.filter(s => s.leaving || s.arriving).length;
    if(busy >= STARS_MOVING_MAX) return;
    const still = stars.filter(s => !s.leaving && !s.arriving);
    if(!still.length) return;
    const star = still[Math.floor(Math.random() * still.length)];
    star.leaving = now;
    star.fade = starsBetween(STARS_FADE_MIN, STARS_FADE_MAX);
  }

  function advance(now, elapsed){
    // В тихом режиме точки стоят: двигать их эта настройка и запрещает.
    // Мерцание ей не подчиняется — оно живёт в `shineOf`.
    if(calm) return;

    // Разворот направления дрейфа — плавный и редкий.
    if(now >= turnAt){
      driftAngle = Math.random() * Math.PI * 2;
      turnAt = now + starsBetween(STARS_TURN_MIN, STARS_TURN_MAX);
    }
    // Пиксели в минуту переводим в пиксели за прошедшие миллисекунды.
    // При включённом опыте общий снос выключается: иначе поле и едет
    // целиком, и перемешивается — два движения сразу читаются как рябь.
    const own = starsWander();
    const step = own ? 0 : STARS_DRIFT * (elapsed / 60000);
    driftX += Math.cos(driftAngle) * step;
    driftY += Math.sin(driftAngle) * step;

    if(own){
      const minutes = elapsed / 60000;
      for(const star of stars){
        star.wx += Math.cos(star.wanderAngle) * star.wanderRate * minutes;
        star.wy += Math.sin(star.wanderAngle) * star.wanderRate * minutes;
      }
    }

    if(now >= movedAt){
      relocate(now);
      movedAt = now + starsBetween(STARS_MOVE_MIN, STARS_MOVE_MAX);
    }

    for(const star of stars){
      if(star.leaving && now - star.leaving >= star.fade){
        // Погасла — переставляем и зажигаем на новом месте.
        const spot = freeSpot();
        star.x = spot.x;
        star.y = spot.y;
        star.leaving = 0;
        star.arriving = now;
        star.fade = starsBetween(STARS_FADE_MIN, STARS_FADE_MAX);
      }else if(star.arriving && now - star.arriving >= star.fade){
        star.arriving = 0;
      }
    }
  }

  function paint(now){
    ctx.clearRect(0, 0, width, height);
    // Параллакс — тоже перемещение: в тихом режиме поле стоит на месте.
    const scroll = calm ? 0 : (window.scrollY || 0);

    for(const star of stars){
      // Ближние смещаются сильнее дальних — от этого поле кажется глубже.
      const depth = 1 + star.depth * (STARS_PARALLAX_DEPTH - 1) / 2;
      const y = star.y + driftY + star.wy - scroll * STARS_PARALLAX * depth;
      const x = star.x + driftX + star.wx;

      // Ушедшее за край возвращаем с другой стороны: дрейф бесконечен.
      const atX = ((x % width) + width) % width;
      const atY = ((y % height) + height) % height;

      const shine = shineOf(star, now);
      if(shine <= 0.01) continue;

      ctx.beginPath();
      ctx.arc(atX, atY, star.size / 2, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${star.colour}, ${shine.toFixed(3)})`;
      if(star.glow){
        ctx.shadowBlur = 4;
        ctx.shadowColor = `rgba(${star.colour}, ${(shine * 0.6).toFixed(3)})`;
      }else{
        ctx.shadowBlur = 0;
      }
      ctx.fill();
    }
    ctx.shadowBlur = 0;
  }

  function frame(now){
    if(!running) return;
    const elapsed = lastFrame ? Math.min(now - lastFrame, 1000) : 0;
    lastFrame = now;
    frames++;
    advance(now, elapsed);
    paint(now);
    requestAnimationFrame(frame);
  }

  function build_canvas(){
    if(canvas) return canvas;
    canvas = document.createElement('canvas');
    canvas.className = 'starfield';
    canvas.setAttribute('aria-hidden', 'true');
    // Прячет холст скрипт, а не стили: правило без `.fx-` работало бы и
    // со снятой галочкой, а такого в файлах эффектов быть не должно.
    canvas.hidden = !starsOn();
    ctx = canvas.getContext('2d');
    document.body.append(canvas);
    resize();
    build();
    return canvas;
  }

  function start(){
    if(!starsOn() || running) return;
    build_canvas();
    canvas.hidden = false;
    if(!turnAt) turnAt = performance.now() + starsBetween(STARS_TURN_MIN, STARS_TURN_MAX);
    if(!movedAt) movedAt = performance.now() + starsBetween(STARS_MOVE_MIN, STARS_MOVE_MAX);

    running = true;
    lastFrame = 0;
    requestAnimationFrame(frame);
  }

  function stop(){
    running = false;
    lastFrame = 0;
  }

  /* Слепок состояния поля наружу (4.1 ТЗ).
   *
   * Поле рисуется на холсте: снаружи не видно ни точек, ни их яркости, и
   * проверить «идёт ли цикл вообще» нечем — только глазами, а глаз на
   * такой амплитуде не судья: движение здесь считается пикселями в
   * минуту, и работающее поле от застывшего на глаз не отличить.
   *
   * Слепок читают только снаружи; сам эффект им не пользуется, и менять
   * через него нечего — это копия, а не сами точки.
   */
  window.starfieldState = () => ({
    running,
    calm,
    count: stars.length,
    frames,
    driftX, driftY, driftAngle,
    moving: stars.filter(s => s.leaving || s.arriving).length,
    stars: stars.map(star => ({
      depth: star.depth, size: star.size, cycle: star.cycle,
      phase: star.phase, x: star.x, y: star.y,
      // Собственный дрейф точки: без него снаружи не отличить включённый
      // опыт «расходятся врозь» от выключенного.
      wx: star.wx, wy: star.wy,
      shine: shineOf(star, performance.now()),
    })),
  });

  document.addEventListener('DOMContentLoaded', start);

  // Вкладка неактивна — считать кадры некому и незачем.
  document.addEventListener('visibilitychange', () => {
    if(document.hidden) stop();
    else start();
  });

  window.addEventListener('resize', () => {
    if(!canvas) return;
    resize();
    // Точки живут в пикселях: после смены размера их надо расставить
    // заново, иначе половина окажется за краем.
    build();
    if(!running) paint(performance.now());
  });

  // Галочку могли поставить уже после загрузки — тогда поле строится тогда.
  const watch = new MutationObserver(() => {
    if(starsOn()) start();
    else{
      stop();
      if(canvas) canvas.hidden = true;
    }
  });
  watch.observe(document.documentElement,
                {attributes: true, attributeFilter: ['class']});
})();
