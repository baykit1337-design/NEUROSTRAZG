/* 1.3 Искры над подзаголовком.
 *
 * Стилями это не сделать: точек десяток, у каждой своё место и свой
 * разброс, а перечислять их в CSS пришлось бы поимённо.
 *
 * Рождаются один раз за наведение, а не потоком: непрерывный фонтанчик
 * над строкой мельтешит и тянет взгляд на себя. Повторный запуск — только
 * после того, как курсор ушёл и вернулся.
 */

//: Сколько искр за одно наведение.
const SPARK_MIN = 8;
const SPARK_MAX = 12;

//: На сколько поднимаются и сколько живут.
const SPARK_RISE = [12, 20];
const SPARK_LIFE = [700, 900];

//: Разброс по горизонтали — небольшой, иначе искры разлетаются веером.
const SPARK_DRIFT = 6;

const SPARK_COLORS = ['#c084fc', '#d8b4fe', '#e9d5ff'];

function sparksOn(){
  return document.documentElement.classList.contains('fx-subtitle');
}

function between(low, high){
  return low + Math.random() * (high - low);
}

(function subtitleSparks(){
  const line = document.querySelector('.sub');
  if(!line) return;

  //: Пока курсор не ушёл, второй раз не запускаем.
  let inside = false;

  function burst(){
    const box = line.getBoundingClientRect();
    const count = Math.round(between(SPARK_MIN, SPARK_MAX));

    for(let n = 0; n < count; n++){
      const spark = document.createElement('i');
      spark.className = 'spark';
      // Вдоль строки, в случайном месте — и сразу над буквами.
      spark.style.left = (box.left + Math.random() * box.width).toFixed(1) + 'px';
      spark.style.top = (box.top + box.height * 0.6).toFixed(1) + 'px';
      spark.style.background =
        SPARK_COLORS[Math.floor(Math.random() * SPARK_COLORS.length)];
      spark.style.setProperty('--dy', `-${between(...SPARK_RISE).toFixed(1)}px`);
      spark.style.setProperty('--dx',
        `${between(-SPARK_DRIFT, SPARK_DRIFT).toFixed(1)}px`);

      const life = between(...SPARK_LIFE);
      spark.style.setProperty('--life', `${life.toFixed(0)}ms`);
      document.body.append(spark);
      // Убираем по окончании: иначе за вечер в теле страницы накопятся
      // тысячи невидимых точек.
      setTimeout(() => spark.remove(), life + 50);
    }
  }

  line.addEventListener('mouseenter', () => {
    if(inside || !sparksOn()) return;
    inside = true;
    burst();
  });
  line.addEventListener('mouseleave', () => { inside = false; });
})();
