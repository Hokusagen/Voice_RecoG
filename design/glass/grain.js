/* «Зерно» — вариант 3 второго круга (NEXT.md): капсула спокойна, жизнь в зерне.
 *
 * Капсула с подписью — рабочий стол Дарви: её силуэт не меняется, поэтому текст
 * всегда лежит на спокойном стекле. Сам Дарви — стеклянное зерно у левого торца,
 * слитое с капсулой нормированным smin. В «Слушаю» зерно дышит голосом, в
 * обработке рвёт перешеек и перебирает формы M3, в «Готово» стол стягивается в
 * него, и дальше Дарви откликается телом. Материал — стекло Линзы без изменений:
 * defaultGlass(), толщина по размеру^0.3, лепесток света и дисперсия кромки как в lens.js.
 */
(function () {
  'use strict';

  const H = 56;              // высота капсулы
  const PAD = 24;            // поле от торца до текста: на 24 px кромка уже не ломает фон
  const ICON = 26;           // значок 16 + зазор 10 в раскладке подписи основы
  const R_LISTEN = 18;       // зерно ~36 px в «Слушаю»
  const R_THINK = 20;        // в обработке чуть крупнее: лепесткам M3 нужно место
  const R_DONE = 28;         // слитая форма «Готово» — круг высоты капсулы
  // Зерно касается торца капсулы, и перешеек даёт сам smin: при k 5.25 его
  // полувысота ~11 px против 18 у зерна и 28 у стола. Так зерно читается отдельным
  // телом, а не наплывом на торце (при нахлёсте форма становилась «яйцом»).
  const OFF_LISTEN = -R_LISTEN;
  const PAD_L = 20;          // от торца стола до текста в «Слушаю» и обработке
  const GAP_THINK = 18;      // зазор после разрыва: больше 2k даже в движении (k до 7.35)
  // Голос: вздох фразы плюс живое дыхание внутри неё. Вздох скромнее, дыхание глубже:
  // при вздохе 4.6 и дыхании ±1.3 зерно во фразе «надувалось и стояло». Теперь край
  // ходит на ±3 px внутри фразы, а зерно у кота всё так же не больше 48 px (при 52 оно
  // вставало в рост стола и переставало читаться зерном).
  const SWELL = 4.0;         // вздох фразы, px радиуса: 36 → ~43 px, дыхание ±1.8 сверху
  const WORD = 0.5;          // ударное слово внутри фразы, ± px радиуса
  const K_REST = 5.25;       // smin в покое (калибровка Apple для 56 px)
  const K_MERGE = 8;         // на слиянии «Готово»; потолок 10 не трогаем
  const MARGIN = 14;         // текст видим, пока до торца не меньше 14 px
  const SWEEP = 0.9;         // обход света на входе в работу, с (как у Линзы)
  const LIGHT0 = -Math.PI / 4; // свет в покое: сверху справа (экранные оси, y вниз)
  // Галочка «Готово» на светлом фоне: #4FDCA6 на белом даёт 1.7:1. Контраст добираем
  // цветом значка, а не пятном под ним: это тот же зелёный тон, только глубже. Тот же
  // тон, что у «Линзы·Света» и «Ртути», — на общем просмотре три галочки должны быть одной.
  const CHECK_DARK = '#07472F';
  // Галочка — всё содержимое «Готово». Проступает с 0.12 с, пока зерно и стол ещё
  // сливаются: к 0.3 с она уже видна целиком, как у двух других вариантов, а не
  // ждёт конца слияния (раньше — 0.27–0.43 с, на кадре 0.3 с её почти не было).
  const CHECK_AT = 0.12;
  // ×1.4 — ~40% диаметра круга 56 px, как у «Линзы·Света» и системных галочек Apple:
  // значок 16 px занимал меньше трети диаметра, и когда кромка гасла, круг читался пустым.
  const CHECK_SCALE = 1.4;

  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const clamp01 = (x) => clamp(x, 0, 1);
  const smooth = (a, b, x) => { const u = clamp01((x - a) / (b - a)); return u * u * (3 - 2 * u); };
  // Горб 0→1→0 на [a, b] как sin²: гладкий на концах, пружине нечего сглаживать.
  const bump = (x, a, b) => (x <= a || x >= b ? 0 : Math.sin((Math.PI * (x - a)) / (b - a)) ** 2);
  // Парабола прыжка: скорость наибольшая в отрыве и в приземлении, поэтому
  // пружина сама даёт отскок там, где у тела есть импульс (WWDC18/803).
  const hop = (x, a, b) => { const u = (x - a) / (b - a); return u <= 0 || u >= 1 ? 0 : 4 * u * (1 - u); };
  // Обход света трогается и останавливается мягко — читается как поворот предмета.
  const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

  const SHAPE = `
uniform vec4 uCap;     // капсула: центр xy, ширина, высота
uniform vec4 uGrain;   // зерно: центр xy, радиус, присутствие в smin
uniform vec4 uForm;    // xy — сплющивание зерна (площадь сохраняется), z — k smin, w — радиус линзы в долях R
uniform vec4 uA; uniform vec2 uAe; uniform vec4 uB; uniform vec2 uBe;
uniform vec3 uMorph;   // прогресс A→B, поворот, доля морфа
uniform vec4 uSun;     // форма Sunny для радости
uniform vec2 uSunP;    // доля Sunny, поворот

float sdCap(vec2 p) { return sdPill(p, uCap.xy, max(uCap.z, uCap.w), uCap.w); }
// r(θ)/R зерна: круг плюс доля морфа обработки и доля Sunny. Смешиваем отклонения
// от круга, а не сами формы: из круга в морф и обратно без скачка на смене пары.
float grainR(float th) {
  float r = 1.0;
  if (uMorph.z > 0.001) {
    float a = th - uMorph.y;
    r += (mix(m3r(a, uA, uAe), m3r(a, uB, uBe), uMorph.x) - 1.0) * uMorph.z;
  }
  if (uSunP.x > 0.001) r += (m3r(th - uSunP.y, uSun, vec2(1.0, 0.0)) - 1.0) * uSunP.x;
  return r;
}
// То же, что sdMorph из kit.js, но с долями форм и сплющиванием: лепестки гаснут
// к центру как (ρ/R)², оценка делится на |∇f| — бортик одной ширины на лепестке и во впадине.
float sdGrain(vec2 p) {
  vec2 q = (p - uGrain.xy) / uForm.xy;
  float s = min(uForm.x, uForm.y);
  float R = uGrain.z;
  float rho = length(q);
  // Далеко от зерна лепестки не нужны: там считается только тень. Порог дальше
  // зоны влияния smin (5.33k), иначе на торце капсулы был бы шов.
  if ((uMorph.z < 0.001 && uSunP.x < 0.001) || rho > R * 1.5 + 60.0) return (rho - R) * s;
  float th = atan(q.y, q.x);
  const float e = 0.01;
  float ra = grainR(th);
  float rb = grainR(th + e);
  float fade = min(rho / R, 1.0);
  fade *= fade;
  float r = R * (1.0 + (ra - 1.0) * fade);
  float dr = R * (rb - ra) / e * fade;
  return (rho - r) / sqrt(1.0 + dr * dr / max(rho * rho, 1.0)) * s;
}
// Порядок цепочки фиксированный: капсула, потом зерно. Лопнувшее или утонувшее
// зерно выпадает из smin через k·присутствие, иначе раздувало бы капсулу изнутри.
float shape(vec2 p) {
  float dc = sdCap(p);
  if (uGrain.z < 0.05) return dc;
  return smin(dc, sdGrain(p), uForm.z * uGrain.w);
}
// Линза — от описанного круга зерна: морф и Sunny ломают свет как круг, а
// лепестки видны кромкой и бликом (kit.js, LG_LENS_SHAPE).
#define LG_LENS_SHAPE
float lensShape(vec2 p) {
  float dc = sdCap(p);
  if (uGrain.z < 0.05) return dc;
  float dg = (length((p - uGrain.xy) / uForm.xy) - uGrain.z * uForm.w) * min(uForm.x, uForm.y);
  return smin(dc, dg, uForm.z * uGrain.w);
}
`;

  const MAIN = `
uniform float uMat;
uniform vec4 uBox;     // рамка формы с запасом на тень: за ней только фон
uniform vec4 uThick;   // бортик и A капсулы, бортик и A зерна
uniform vec4 uVoice;   // x — голос (свет ободка зерна), y — свет изнутри, z — точка «Слушаю», w — акцент
uniform vec2 uLabelC;  // центр подписи: по фону под ней выбирается тон ореола точки
uniform vec3 uLight;   // xy — направление на свет, z — сила обхода света (0..1)

void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  // Основная площадь холста — одна выборка фона: сначала рамка, потом расстояние.
  // Запас 85–90 px: тень там уже меньше 1/255, и на белом нет ступеньки по рамке.
  if (uMat <= 0.001 || p.x < uBox.x || p.x > uBox.z || p.y < uBox.y || p.y > uBox.w) { outColor = vec4(bg, 1.0); return; }
  float d0 = shape(p);
  if (d0 > 85.0) { outColor = vec4(bg, 1.0); return; }
  float mc = clamp(uMat, 0.0, 1.0);
  bool hasGrain = uGrain.z > 0.05;
  float dg = hasGrain ? sdGrain(p) : 1e4;
  // Чья кромка ближе: у зерна своя толщина по его размеру (размер^0.3), у капсулы своя.
  float own = hasGrain ? clamp(0.5 + (sdCap(p) - dg) / 10.0, 0.0, 1.0) : 0.0;
  Glass g = defaultGlass();
  g.bevel = mix(uThick.x, uThick.z, own);
  g.amplitude = mix(uThick.y, uThick.w, own);
  g.light = uLight.xy;
  g.materialize = uMat;
  // Дисперсия как у Линзы — только в кромке. В вогнутом перешейке нормали сходятся,
  // и цветные копии фона там искрят: каймы оставляем выпуклой кромке (лапласиан ≥ 0).
  if (d0 < 1.0 && -d0 < g.bevel + 1.0) {
    const float e = 2.0;
    float lap = (shape(p + vec2(e, 0.0)) + shape(p - vec2(e, 0.0)) + shape(p + vec2(0.0, e)) + shape(p - vec2(0.0, e)) - 4.0 * d0) / (e * e);
    g.dispersion = 0.035 * smoothstep(-0.03, 0.0, lap);
  }
  vec4 glass = liquidGlass(p, g, bg);
  vec3 col = glass.rgb;
  if (glass.a > 0.0) {
    vec2 n;
    float inside = max(-shapeDist(p, n), 0.0);
    // Лепесток света у кромки — как в Линзе (покой 0.2, в обходе ярче и шире). Голос
    // светит только ободком зерна: дуга ярче и длиннее во фразе и дышит вместе с ним,
    // а текст на капсуле стоит на ровном стекле.
    float vo = uVoice.x * own;
    float fl = uVoice.w * own;
    float spec = 0.2 + 0.3 * uLight.z + 0.6 * vo + 0.4 * fl;
    float wide = 1.8 + 0.9 * uLight.z + 0.9 * vo + 0.5 * fl;
    if (inside < wide + 0.5) {
      float c = dot(n, g.light);
      float e = mix(6.0, 2.2, clamp(vo + 0.6 * fl, 0.0, 1.0));
      float lobe = pow(max(c, 0.0), e) + 0.5 * pow(max(-c, 0.0), e);
      float k = lobe * spec * glass.a * mc;
      // На тёмном свет — осветление, на светлом осветлять нечего: там свет читается
      // тонкой тёмной линией по самому краю, как ребро стекла на бумаге (приём Линзы).
      float bright = smoothstep(0.5, 0.85, luma(col));
      float band = 1.0 - smoothstep(0.3, wide, inside);
      col += (1.0 - col) * band * k * (1.0 - 0.6 * bright);
      float edge = 1.0 - smoothstep(0.35, 1.25, inside);
      col *= 1.0 - 0.42 * bright * edge * k;
    }
    col = statusRim(col, p, inside, glass.a);
    // Свет из глубины зерна — «из-под пальца», источник голоса. Держится внутри
    // зерна: к подписи на капсуле не доходит.
    if (hasGrain && uVoice.y > 0.002) col = touchGlow(col, p, uGrain.xy, uGrain.z * 0.8, uVoice.y * (1.0 - smoothstep(-3.0, 1.0, dg)), glass.a);
    // Точка «Слушаю» — в центре зерна, где линза 1:1. Рисуем сами: зерно тянется к
    // голосу и несёт её с собой, а подпись основы должна стоять на месте.
    if (uVoice.z > 0.01) {
      float dd = length(p - uGrain.xy);
      if (dd < 12.0) {
        float mean = luma(sceneAt(uLabelC, 5.0) + sceneAt(uLabelC + vec2(-60.0, 0.0), 5.0) + sceneAt(uLabelC + vec2(60.0, 0.0), 5.0)) / 3.0;
        // Ореол как у значка основы: тон противоположный тону текста.
        float halo = exp(-pow(max(dd - 3.2, 0.0), 2.0) / 6.0) * 0.42 * uVoice.z * glass.a;
        col = mean > 0.45 ? col + (1.0 - col) * halo : col * (1.0 - halo);
        float a = clamp(3.7 - dd + 0.5, 0.0, 1.0) * uVoice.z * glass.a;
        col = mix(col, vec3(1.0, 0.373, 0.427), a);
      }
    }
    // Своего ореола под галочкой «Готово» нет, как у «Линзы·Света»: пятно ложилось
    // молочным кругом в центр стекла, где оно должно быть 1:1. Контраст даёт цвет и
    // размер значка (тёмно-зелёная ×1.4 на светлом, светлая на тёмном) плюс общий
    // ореол значка основы.
  }
  outColor = vec4(col, 1.0);
}
`;

  const SUNNY = LG.shapeVec('Sunny')[0];
  const SUNNY_MAX = LG.shapes.Sunny.max;

  LG.register({
    id: 'grain',
    round: 2,

    setup(ctx) {
      const S = ctx.Spring;
      this.prog = ctx.program(ctx.glsl.header + ctx.glsl.common + ctx.glsl.morph + SHAPE + ctx.glsl.glass
        + ctx.glsl.status + ctx.glsl.touch + MAIN);
      // Материализация: как у Линзы, но чуть быстрее — вся за ~300 мс.
      this.mat = new S(0, 0.36, 0.85);
      this.capX = new S(0, 0.42, 0.86);
      this.capW = new S(160, 0.42, 0.86);
      this.capH = new S(H, 0.3, 1.0);
      // Зерно ходит пружиной M3 default spatial: ζ 0.8, жёсткость 380 → 0.322 с.
      this.gx = new S(0, 0.322, 0.8);
      this.gR = new S(R_LISTEN, 0.35, 0.8);
      this.ck = new S(1, 0.2, 1.0);        // присутствие капсулы в smin: в «Готово» она тонет в зерне
      this.voice = new S(0, 0.42, 0.86);   // голос фразами: кот плавно, «живее» — с лёгким перелётом
      this.wordS = new S(0.5, 0.35, 1.0);  // ударное слово внутри фразы, 0..1
      this.lean = new S(0, 0.3, 0.9);      // «тянется к голосу» — наружу, от стола
      this.kick = new S(0, 0.34, 0.6);     // глоток на ударном месте фразы
      this.flare = new S(0, 0.4, 1.0);     // вспышка ободка на том же акценте
      this.morphAmt = new S(0, 0.3, 1.0);
      this.sun = new S(0, 0.2, 0.8);
      this.jy = new S(0, 0.25, 0.85);      // подскок и оседание реакции, px
      this.sq = new S(0, 0.16, 0.7);       // сплющивание: + шире и ниже, − уже и выше
      // «Мотает головой» в ошибке: период ~0.22 с (4.5 Гц — качок, а не дрожь), слабое
      // демпфирование — до лопания успевают два-три видимых качка.
      this.shake = new S(0, 0.22, 0.18);
      // Лопание: множитель радиуса. Критическая пружина — зерно схлопывается за ~0.1 с,
      // видно как лопание, а не как исчезновение в один кадр.
      this.pop = new S(1, 0.14, 1.0);
      this.dot = new S(0, 0.15, 1.0);
      this.phi = 0;          // фаза дыхания зерна во фразе
      this.tm = null;        // темперамент, сглаженный: переключатель на лету не даёт скачка
      this.sweepAt = -10;
      this.labEl = ctx.root ? ctx.root.querySelector('.lg-label') : null;
      // Цикл мягких форм: на зерне 40 px глубокий клевер читался крестом «плюс»,
      // а круга в цикле нет — пока идёт работа, зерно всё время «думает».
      this.morph = new LG.Morph(['Cookie4', 'Cookie9', 'Pentagon', 'Oval', 'Cookie6']);
      this.status = new LG.StatusFlash();
      this.stage = 'hidden';
      this.final = null;
      this.L = null;
      this.xCL0 = null;
      this.m = 0;
      this.loud = 0.8;
      this.word = 0.8;
      this.textAt = null;
      this.swap = false;
      this.morphing = false;
      this.popped = false;
      this.landAt = null;
    },

    // Цели раскладки стадии. Левый торец капсулы с «Слушаю» до «Причёсываю» стоит на
    // месте: текст начинается в одной точке, а движется только зерно.
    layout(ctx, s, stage) {
      const W2 = ctx.W / 2;
      const textW = Math.max(0, s.contentW - ICON);
      if (stage === 'listening' || stage === 'transcribing' || stage === 'polishing') {
        const capW = textW + PAD_L + PAD;
        const listening = stage === 'listening';
        const P = listening ? R_LISTEN - OFF_LISTEN : GAP_THINK + 2 * R_THINK;
        if (this.xCL0 == null) this.xCL0 = W2 - (P + capW) / 2 + P;
        const xCL = this.xCL0;
        return {
          capX: xCL + capW / 2, capW, capH: H,
          gx: listening ? xCL + OFF_LISTEN : xCL - GAP_THINK - R_THINK,
          gR: listening ? R_LISTEN : R_THINK,
        };
      }
      // «Готово»: всё сходится в круг по центру; стол сжимается в ноль внутри зерна.
      if (stage === 'done') return { capX: W2, capW: 0, capH: H, gx: W2, gR: R_DONE };
      // «Ошибка»: капсула одна, по центру; зерно к этому моменту лопнет.
      if (stage === 'error') {
        const capW = s.contentW + 2 * PAD;
        return { capX: W2, capW, capH: H, gx: W2 - capW / 2 + OFF_LISTEN, gR: R_LISTEN };
      }
      return null;
    },

    enter(ctx, s) {
      const from = this.stage;
      const st = s.stage;
      this.stage = st;
      if (st === 'hidden') return;
      const fromHidden = (from === 'hidden' && this.mat.value < 0.05) || this.mat.value < 0.02;
      // Новая диктовка — новая раскладка: стол встаёт по центру под свою подпись.
      if (fromHidden || st === 'listening') this.xCL0 = null;
      const L = this.layout(ctx, s, st);
      if (fromHidden) {
        // Из невидимого форма сразу встаёт на место: появление — рост линзы, а не растяжение.
        this.capX.snap(L.capX); this.capW.snap(st === 'done' ? 0 : L.capW); this.capH.snap(st === 'done' ? 0 : L.capH);
        this.gx.snap(L.gx); this.gR.snap(L.gR);
        this.ck.snap(st === 'done' ? 0 : 1);
        for (const sp of [this.voice, this.lean, this.kick, this.flare, this.morphAmt, this.sun, this.jy, this.sq, this.shake]) sp.snap(0);
        this.wordS.snap(0.5);
        this.pop.snap(1);
        this.dot.snap(0);
        this.morph.reset();
        this.morphing = false;
        this.loud = 0.8;
        this.word = 0.8;
        this.phi = 0;
        this.textAt = null;
      }
      if (st === 'listening') {
        this.pop.snap(1);
        this.popped = false;
      }
      // Начало работы — событие: свет один раз обходит силуэт, как в Линзе. Стол при
      // этом раздвигается сразу, но только вправо, от зерна: левый торец стоит, и
      // перешеек рвётся первым (пружина зерна быстрее). Ждать разрыва ради стола нельзя —
      // основа уже сменила подпись, и стол стоял бы пустым ~0.3 с.
      if (st === 'transcribing') this.sweepAt = s.time;
      if (st === 'done') this.landAt = null;
      if (st === 'error') {
        // Стол встаёт по центру холста под «Не расслышал», пока подпись ещё не проступила:
        // раньше левый торец стоял, стол рос вправо, и капсула с ошибкой оставалась на
        // ~35 px правее центра, где у двух других вариантов она по центру. Переезд
        // укладывается в ~0.25 с и кончается до проявления подписи, поэтому читаемый
        // текст не едет. Зерно едет на левом торце: его цель — от торца итогового стола,
        // и пружина зерна быстрее пружины стола, так что зазор в пути только растёт и
        // стол не наезжает на зерно (иначе они слились бы вместо разрыва).
        this.errAnchor = L.capX - L.capW / 2;
        this.errR = fromHidden ? L.gR : this.gR.target;
        // Зерно отходит от торца хотя бы на зазор обработки: из «Слушаю» оно касалось стола.
        this.errGx = Math.min(fromHidden ? L.gx : this.gx.target, this.errAnchor - this.errR - GAP_THINK);
        this.popped = false;
        this.pop.snap(1);
        // Лопается после качков: к 0.3 с успевают «туда — обратно» и третий, слабый;
        // у «живее» чуть раньше. Подпись лопания не ждёт — она уже на столе.
        this.popT = this.T(0.32, 0.3);
        // Вздрагивает (быстрый отскок от стола), затем мотает головой — смущённо, без
        // тревоги. Качки стартуют, когда отскок почти прошёл, иначе они тонут в нём.
        this.shook = false;
      }
      this.L = L;
      // Подпись: гасим, только если новая не влезает в нынешнюю форму; иначе она
      // проступает поверх, без провала в пустую капсулу.
      const geo = this.labelGeo(ctx, s, st, 1);
      if (fromHidden || !geo.fits || this.textAt == null) {
        this.textAt = null;
        this.swap = false;
      } else {
        this.textAt = s.time;
        this.swap = true;
      }
    },

    // Значение по темпераменту от сглаженного s.temper: даже величины, которые идут в
    // форму напрямую, а не через пружину, не прыгают при переключении на лету.
    T(cat, lively) { return cat + (lively - cat) * (this.tm == null ? 0 : this.tm); },

    // Где стоит подпись и влезает ли она в нынешнюю форму (с запасом MARGIN до торцов).
    labelGeo(ctx, s, st, sc) {
      const W2 = ctx.W / 2;
      const capX = W2 + (this.capX.value - W2) * sc;
      const capW = Math.max(this.capW.value, this.capH.value) * sc;
      const xCL = capX - capW / 2;
      const xCR = capX + capW / 2;
      const cw = s.contentW;
      if (st === 'done') {
        const gx = W2 + (this.gx.value - W2) * sc;
        const gR = this.gR.value * sc;
        const span = Math.max(xCR, gx + gR) - Math.min(xCL, gx - gR);
        // Слияние кончилось — стол почти утонул в зерне, центр зерна спокоен: по этому
        // признаку стол выходит из smin и начинается реакция. Галочка его не ждёт (CHECK_AT).
        const fits = span < 2 * R_DONE + 28 && Math.abs(this.gx.value - W2) < 12;
        return { cx: gx, fits, hideIcon: false, margin: fits ? 20 : 0 };
      }
      if (st === 'error') {
        const margin = (capW - cw) / 2;
        // Текст проступает на последних пикселях роста стола, а не посреди растяжения,
        // и когда стол почти доехал до центра (40 px/с — остаток переезда ~2 px): пока
        // подпись едва видна, она ещё может сдвинуться, а прочитанная уже стоит.
        const settled = Math.abs(this.capW.velocity) < 250 && Math.abs(this.capX.velocity) < 40;
        return { cx: capX, fits: margin >= MARGIN && settled, hideIcon: false, margin };
      }
      // Слушаю и обработка: значок скрыт (свою точку рисует шейдер), текст привязан
      // к левому торцу — начинается в PAD_L от него.
      const cx = xCL + PAD_L - ICON + cw / 2;
      const margin = Math.min(PAD_L, xCR - (cx + cw / 2));
      return { cx, fits: margin >= MARGIN, hideIcon: true, margin };
    },

    frame(ctx, s) {
      const dt = s.dt;
      const W2 = ctx.W / 2;
      const cy0 = ctx.H / 2;
      // Темперамент сглаживаем за ~0.3 с: переключатель на странице меняет его рывком.
      const tmT = s.temper || 0;
      this.tm = this.tm == null ? tmT : this.tm + (tmT - this.tm) * (1 - Math.exp(-dt / 0.3));
      const T = (a, b) => this.T(a, b);
      if (s.stage !== this.stage) this.enter(ctx, s);
      this.status.step(s);
      const st = s.stage;
      const t = s.t;
      const listening = st === 'listening';
      const thinking = st === 'transcribing' || st === 'polishing';
      if (st === 'done' || st === 'error') this.final = st;
      else if (st !== 'hidden') this.final = null;
      const afterDone = st === 'done' || (st === 'hidden' && this.final === 'done');

      // ---- материализация: на уходе быстрее и без перелёта (как у Линзы)
      if (s.shown) { this.mat.response = 0.36; this.mat.damping = 0.85; }
      else { this.mat.response = 0.32; this.mat.damping = 1.0; }
      const m = this.mat.set(s.shown ? 1 : 0).step(dt);
      const mc = clamp01(m);

      // ---- голос. Вентиль фразы: speech (атака 120, спад 500 мс) и уровень выше
      // пола. Внутри фразы уровень стоит у 0.6–0.95 и на слогах не проваливается ниже
      // порога, поэтому зерно вздыхает фразами, а не слогами; громкая фраза — глубже.
      const gate = listening ? s.speech * smooth(0.15, 0.55, s.level) : 0;
      if (listening && s.speech > 0.5) {
        this.loud += (s.level - this.loud) * (1 - Math.exp(-dt / 0.6));
        this.word += (s.level - this.word) * (1 - Math.exp(-dt / 0.2));
      }
      const loudN = clamp01((this.loud - 0.62) / 0.3);
      // Слово меряем относительно своей фразы: по абсолютному порогу ровный голос давал
      // постоянную величину, и зерно внутри фразы каменело надутым. Огибающая 0.2 с и
      // пружина 0.35 с срезают всё выше ~1 Гц — слоги 4–6 Гц до формы не доходят.
      const wordN = clamp01(0.5 + (this.word - this.loud) / 0.06);
      this.voice.response = T(0.42, 0.3);
      this.voice.damping = T(0.86, 0.62);
      const v = Math.max(0, this.voice.set(gate * (0.8 + 0.2 * loudN)).step(dt));
      const wn = this.wordS.set(listening ? wordN : 0.5).step(dt);
      // Живая система: во фразе зерно дышит 0.65–1.1 Гц, громче — чаще; голос задаёт
      // её глубину и темп, а не рисует форму. Вторая, несоразмерная частота и слово
      // сбивают ровный такт — это дыхание, а не метроном. В паузе v → 0, и зерно
      // замирает вместе с ним. Фраза начинается со вдоха: фаза с нуля.
      // Размах ±1.8–2.1 px радиуса: с полусдвигом центра наружный край ходит на ±2.7–3.1 px —
      // в пределах «дыхание ≤ 3–4 px» (RESEARCH.md), и длинная фраза не каменеет.
      for (const e of s.events) if (listening && e.type === 'phrase' && v < 0.2) this.phi = 0;
      this.phi += dt * 2 * Math.PI * (0.65 + 0.45 * loudN) * T(1, 1.15);
      const osc = 0.8 * Math.sin(this.phi) + 0.2 * Math.sin(1.618 * this.phi + 1.3);
      const breath = v * (T(1.8, 2.1) * osc + WORD * (2 * wn - 1));
      // Ударное место фразы (не чаще раза в 0.7 с) — редкий акцент: глоток и вспышка ободка.
      // Глоток 1.6–2.4 px — чтобы он выходил из хода дыхания, а не тонул в нём (было ~0.9).
      // Пик пружины 0.34 с при ζ 0.62 — это v0·0.027 с, у ζ 0.5 — v0·0.03 с: отсюда скорости.
      if (listening) {
        for (const e of s.events) {
          if (e.type !== 'peak') continue;
          const k = 0.6 + 0.4 * (e.strength || 0);
          this.kick.velocity += T(75, 100) * k;
          this.flare.velocity += T(24, 34) * k;
        }
      }
      this.kick.damping = T(0.62, 0.5);
      const kick = this.kick.set(0).step(dt);
      const flare = clamp01(this.flare.set(0).step(dt));
      // Амплитуда наклона своя у темперамента — через пружину: переключатель не даёт скачка.
      const lean = this.lean.set(-T(2.5, 4.5) * v).step(dt);

      if (!this.L) {
        ctx.draw(this.prog, { uMat: 0 });
        return { labelOpacity: 0, hideLabel: true };
      }

      // ---- цели раскладки
      if (listening || thinking) this.L = this.layout(ctx, s, st) || this.L;
      const L = this.L;
      // На уходе форма замирает как есть: гаснет линза, а не геометрия.
      if (st !== 'hidden') {
        // Ошибка: стол по центру холста (layout), переезд — до проявления подписи.
        this.capX.set(L.capX);
        this.capW.set(L.capW);
        // В «Готово» стол теряет высоту, только когда уже спрятался в зерне.
        this.capH.set(st === 'done' ? (this.capW.value < 64 ? 0 : H) : L.capH);
      }

      // Пружины зерна по стадии и темпераменту.
      if (st === 'done') {
        // Слияние ~0.3 с: при 0.2 с мостик между зерном и столом глаз не успевал заметить.
        this.gx.response = T(0.52, 0.44); this.gx.damping = T(0.86, 0.72);
        this.gR.response = T(0.46, 0.38); this.gR.damping = T(0.86, 0.66);
        this.capW.response = 0.5; this.capW.damping = 0.9;
        this.capX.response = 0.5; this.capX.damping = 0.9;
      } else if (st === 'error') {
        this.gx.response = 0.2; this.gx.damping = 0.85;
        this.gR.response = 0.35; this.gR.damping = 0.8;
        // Центр стола — критическая пружина 0.3 с: без перелёта, к 0.25 с остаток
        // переезда ~1 px, и подпись встаёт уже на место, а не догоняет стол.
        this.capW.response = 0.32; this.capW.damping = 0.9;
        this.capX.response = 0.3; this.capX.damping = 1.0;
      } else if (st !== 'hidden') {
        this.gx.response = 0.322; this.gx.damping = T(0.8, 0.64);
        this.gR.response = 0.35; this.gR.damping = T(0.8, 0.66);
        this.capW.response = 0.42; this.capW.damping = 0.86;
        this.capX.response = 0.42; this.capX.damping = 0.86;
      }
      if (st === 'error') {
        // Отрыв: зерно отскакивает от стола, мотает головой и лопается; стол тем
        // временем встаёт по центру под подпись и дальше стоит.
        this.gx.set(this.errGx - T(8, 12));
        this.gR.set(this.errR);
        if (!this.popped && t >= this.popT) { this.popped = true; this.pop.set(0); }
      } else if (st !== 'hidden') {
        this.gx.set(L.gx);
        this.gR.set(L.gR);
      }

      this.capX.step(dt); this.capW.step(dt); this.capH.step(dt);
      this.gx.step(dt); this.gR.step(dt);
      // Кот мотает головой на 4 px, «живее» — на 6 и слабее гасит (ζ 0.18 против 0.1).
      // Период 0.22 с (4.5 Гц): качок, а не дрожь.
      if (st === 'error' && !this.shook && t >= 0.07) { this.shake.velocity -= T(110, 140); this.shook = true; }
      this.shake.response = 0.22;
      this.shake.damping = T(0.18, 0.1);
      const shake = this.shake.set(0).step(dt);
      const pop = Math.max(0, this.pop.step(dt));

      // ---- морф обработки: только когда зерно уже отошло — форма и есть статус.
      // Порог 2k + 6: морф начинается после разрыва, а не вместе с ним.
      const gapNow = (this.capX.value - Math.max(this.capW.value, this.capH.value) / 2) - (this.gx.value + this.gR.value);
      if (thinking) {
        if (!this.morphing && gapNow > 2 * K_REST + 6) this.morphing = true;
        if (this.morphing) {
          this.morph.p.damping = T(0.7, 0.58);
          this.morph.step(dt, T(1, 1.2) * (st === 'polishing' ? 1.1 : 1));
        }
        this.morphAmt.response = 0.3;
      } else {
        this.morphing = false;
        this.morphAmt.response = st === 'error' ? 0.16 : 0.22;
      }
      const mA = clamp01(this.morphAmt.set(this.morphing ? 1 : 0).step(dt));
      if (!this.morphing && mA < 0.005) this.morph.reset();

      // ---- «Готово»: слияние и реакция Дарви
      let jyT = 0, sqT = 0, sunT = 0, sunRot = 0;
      const geoDone = st === 'done' ? this.labelGeo(ctx, s, st, 1) : null;
      if (st === 'done') {
        this.ck.set(geoDone.fits ? 0 : 1);
        // Радость ждёт, пока схлынет зелёная полоса итога (к 0.7 с её яркость ~0.3 от пика):
        // вершина прыжка с солнышком посреди яркой зелёной кромки и с галочкой внутри
        // читалась значком «проверено», а не радостью тела. Сначала итог, потом отклик.
        const land0 = s.emotion === 'joy' ? 0.5 : 0.18;
        if (this.landAt == null && geoDone.fits) this.landAt = Math.max(t, land0);
        const tr = this.landAt == null ? -1 : t - this.landAt;
        if (s.emotion === 'joy') {
          // Радость: присел, подпрыгнул и на миг стал солнышком, приземлился.
          // У «живее» после приземления — маленький отскок в четверть высоты (отскок ≤ 0.3).
          const J = T(5, 10);
          jyT = -J * (hop(tr, 0.04, 0.4) + T(0, 0.24) * hop(tr, 0.42, 0.6));
          sqT = T(0.035, 0.06) * bump(tr, -0.06, 0.1) - T(0.025, 0.045) * bump(tr, 0.08, 0.32) + T(0.02, 0.05) * bump(tr, 0.38, 0.6);
          // Солнышко — лёгкий намёк на вершине прыжка, и лучи в прыжке чуть поворачиваются:
          // полная доля с галочкой внутри читалась значком «проверено», а не радостью.
          // К посадке форма уже круглая (пружина sun отстаёт на ~0.05 с).
          sunT = T(0.4, 0.6) * bump(tr, 0.02, 0.36);
          sunRot = 0.5 * (Math.PI / 8) * hop(tr, 0.04, 0.4);
          this.jy.response = 0.2; this.jy.damping = T(0.9, 0.62);
        } else if (s.emotion === 'sad') {
          // Грусть: коротко вздыхает — чуть вытягивается вверх, — потом медленно оседает и
          // прижимается вниз, дольше затихает. У кота грусть отличается от кивка и глубиной,
          // и темпом: кивок ~2.6 px и обратно к 0.7 с, грусть 4.5 px и медленная пружина без
          // возврата — боковым зрением «чуть осело» у обеих читалось одинаково.
          // Цель выдоха у кота выше, чем у «живее»: его медленная пружина берёт от короткого
          // горба лишь треть, и вышло бы −0.2 px — невидимо; так выдох ~0.6 px у обоих.
          jyT = T(4.5, 6) * smooth(0.05, 0.6, tr) - T(1.5, 1.2) * bump(tr, -0.05, 0.22);
          sqT = T(0.06, 0.075) * smooth(0.1, 0.65, tr) - T(0.02, 0.03) * bump(tr, -0.05, 0.22);
          this.jy.response = T(0.55, 0.42); this.jy.damping = 1.0;
        } else {
          // Без эмоции — самое частое «Готово»: удовлетворённый кивок. Оседает и чуть
          // сплющивается, как голова в кивке: сдвиг на 1.5 px глаз не ловил.
          jyT = T(3.0, 4.0) * bump(tr, 0.0, 0.36);
          sqT = T(0.025, 0.035) * bump(tr, 0.0, 0.3);
          this.jy.response = 0.25; this.jy.damping = 0.85;
        }
      } else if (st === 'hidden' && this.final === 'done' && s.emotion === 'sad') {
        // Грусть держится и на уходе: гаснет, чуть опускаясь.
        jyT = T(4.5, 6) + 2;
        sqT = T(0.06, 0.075);
      } else if (st !== 'hidden') {
        this.ck.set(1);
      }
      if (st === 'error' && t > this.popT - 0.12 && !this.popped) sqT = 0.06;   // вдох перед лопанием
      const jy = this.jy.set(jyT).step(dt);
      const sqv = clamp(this.sq.set(sqT).step(dt), -0.2, 0.25);
      const sA = clamp01(this.sun.set(sunT).step(dt));
      const ck = clamp01(this.ck.step(dt));
      this.dot.set(listening ? 1 : 0).step(dt);

      // ---- k smin: в движении больше (k(t) = 5.25·(1 + 0.4·m)), на слиянии «Готово» — 8.
      const mT = clamp(Math.max(Math.abs(this.gx.velocity) / 120, Math.abs(this.capW.velocity) / 250,
        Math.abs(this.capX.velocity) / 200, Math.abs(this.gR.velocity) / 40), 0, 1);
      this.m += (mT - this.m) * (mT > this.m ? 1 - Math.exp(-dt / 0.05) : 1 - Math.exp(-dt / 0.18));
      let k = K_REST * (1 + 0.4 * this.m);
      if (st === 'done' && ck > 0.02) k = Math.max(k, K_MERGE * smooth(0, 0.12, t));
      k = Math.min(k, K_MERGE);

      // ---- геометрия кадра: лёгкий масштаб 0.96→1 вместе с материализацией
      const sc = 0.96 + 0.04 * m;
      const X = (x) => W2 + (x - W2) * sc;
      const capXv = X(this.capX.value);
      const capHv = Math.max(0, this.capH.value) * sc;
      const capWv = Math.max(0, this.capW.value) * sc;
      const cyCap = cy0 + (afterDone ? jy : 0);
      const swellPop = st === 'error' && !this.popped ? 1 + 0.08 * smooth(this.popT - 0.12, this.popT, t) : 1;
      // Голосовая добавка к радиусу с мягким коленом выше 5.5 px: у кота фраза под него
      // почти не заходит, а у «живее» совпадение вершины дыхания с глотком раздувало
      // зерно до 54 px — в рост стола. Колено гладкое (tanh), форма не упирается в потолок.
      const ex = SWELL * v + breath + kick;
      const exS = ex > 5.5 ? 5.5 + 2.5 * Math.tanh((ex - 5.5) / 2.5) : ex;
      let gR = (Math.max(0, this.gR.value) + exS) * pop * swellPop * sc;
      if (st === 'error' && this.popped && pop < 0.04) gR = 0;
      // Зерно растёт наружу, от стола: перешеек почти не меняется, а выступ за торец
      // растёт на вздох, дыхание и наклон — это видно боковым зрением на любом фоне.
      // Дыхание сдвигает центр наполовину: у стола перешеек лишь слегка «пьёт», снаружи
      // край ходит в полтора раза шире.
      const gxD = X(this.gx.value - 0.6 * SWELL * v - 0.5 * breath + lean + shake);
      const gyD = cy0 + jy;
      const sx = 1 + sqv;
      const sy = 1 / (1 + sqv);
      const maxM = Math.max(LG.shapes[this.morph.from].max, LG.shapes[this.morph.to].max);
      const lensK = 1 + (maxM - 1) * mA + (SUNNY_MAX - 1) * sA;

      // ---- оптика: толщина по размеру^0.3 (капсула — как у Линзы, от 250 px ширины;
      // зерно — от паспортных 13/41 на 56 px). Кромка сужается с материализацией, A идёт
      // как m² (на уходе m³) — у торцов не висят оторванные перевёрнутые глифы.
      const fade = s.shown ? mc : mc * mc;
      const rim = 0.35 + 0.65 * mc;
      // Толщину зерна считаем от его размера стадии, без вздоха: голос меняет размер,
      // но не толщину стекла — толщину от голоса заказчик отверг в первом круге.
      const capThick = Math.pow(Math.max(capWv / 250, 1), 0.3);
      const gThick = Math.pow(Math.max(2 * Math.max(0, this.gR.value) * sc, 8) / H, 0.3);

      // ---- подпись
      const geo = this.labelGeo(ctx, s, st, sc);
      const done = st === 'done';
      // Галочка «Готово» идёт по часам стадии, а не по концу слияния: к 0.3 с она видна.
      const ready = done ? t >= CHECK_AT : geo.fits;
      if (s.shown && ready && mc > 0.7 && this.textAt == null) this.textAt = s.time;
      let opacity = 0;
      let blur = 0;
      if (s.shown && this.textAt != null) {
        const kk = s.time - this.textAt;
        // Появление целиком укладывается в ~300 мс: текст проступает, пока линза дорастает.
        const gateM = smooth(0.7, 0.92, mc);
        if (this.swap) {
          opacity = (0.4 + 0.6 * smooth(0, 0.18, kk)) * gateM;
          blur = 1.5 * (1 - smooth(0, 0.2, kk));
        } else if (done) {
          // Галочка проявляется из короткого размытия 4 → 0 px за 0.12 с, как у «Линзы·Света»:
          // так читается «проступила», а не «включилась».
          opacity = smooth(0, 0.18, kk) * gateM;
          blur = 4 * (1 - smooth(0, 0.12, kk));
        } else {
          opacity = smooth(0, 0.18, kk) * gateM;
          blur = 3 * (1 - smooth(0, 0.24, kk));
        }
        // Страховка: форма стала тесна подписи — подпись гаснет раньше, чем вылезет.
        if (!done) opacity *= smooth(MARGIN - 4, MARGIN, geo.margin);
      }
      let cx = geo.cx;
      let cy = cy0;
      if (done) {
        // Галочка — в центре формы: середина охвата зерна и стола, пока стол не утонул,
        // потом центр зерна (в реакциях галочка идёт за телом). Ехать с зерном через
        // перешеек она не должна, а приколотая к центру холста она стояла на 5–9 px
        // правее центра уже собравшегося круга, пока тот доезжал (0.25–0.35 с).
        const capHalf = Math.max(capWv, capHv) / 2;
        cx = (Math.min(capXv - capHalf, gxD - gR * sx) + Math.max(capXv + capHalf, gxD + gR * sx)) / 2;
        cy = gyD;
      }
      // Тон подписи выбирает основа по фону; цвет галочки идёт за ним: тёмно-зелёная на
      // светлом фоне, зелёная итога на тёмном.
      const tone = this.labEl ? this.labEl.dataset.tone : '';
      const lightBg = tone === 'dark';

      // ---- обход света на входе в работу: один поворот на 360°, лепесток ярче в пути
      const sw = clamp01((s.time - this.sweepAt) / SWEEP);
      const ang = LIGHT0 + 2 * Math.PI * easeInOut(sw);
      const passing = sw < 1 && s.shown ? Math.sin(Math.PI * sw) : 0;

      // Рамка формы с запасом на тень (30 px размытия, 8 px вниз).
      const gExt = gR * 1.3 * Math.max(sx, sy) + 2;
      const box = [
        Math.min(capXv - Math.max(capWv, capHv) / 2, gR > 0.05 ? gxD - gExt : 1e4) - 90,
        Math.min(cyCap - capHv / 2, gR > 0.05 ? gyD - gExt : 1e4) - 90,
        Math.max(capXv + Math.max(capWv, capHv) / 2, gR > 0.05 ? gxD + gExt : -1e4) + 90,
        Math.max(cyCap + capHv / 2, gR > 0.05 ? gyD + gExt : -1e4) + 98,
      ];

      const mu = this.morph.uniforms;
      ctx.draw(this.prog, {
        uCap: [capXv, cyCap, capWv, capHv],
        uGrain: [gxD, gyD, gR, Math.min(ck, clamp01(pop * 4))],
        uForm: [sx, sy, k, lensK],
        uA: mu.A, uAe: mu.Ae, uB: mu.B, uBe: mu.Be,
        uMorph: [mu.t, mu.rot, mA],
        uSun: SUNNY, uSunP: [sA, Math.PI / 8 + sunRot],
        uMat: m, uBox: box,
        uThick: [13 * capThick * rim, 41 * capThick * fade, 13 * gThick * rim, 41 * gThick * fade],
        // Свет ободка дышит вместе с зерном: дыхание ±2 px — это ±0.16 силы.
        uVoice: [clamp01(v + 0.08 * breath), 0.3 * v, clamp01(this.dot.value) * smooth(0.5, 0.95, mc), flare],
        uLabelC: [geo.cx, cy0],
        uLight: [Math.cos(ang), Math.sin(ang), passing],
        uStatus: this.status.uniform,
      });

      // Зазор по нарисованной форме: край зерна против торца стола (перешеек при ≤ 2k).
      const gap = (capXv - Math.max(capWv, capHv) / 2) - (gxD + gR * sx);
      return {
        cx, cy,
        labelOpacity: opacity,
        labelBlur: blur,
        // Масштаб основа ставит вокруг центра подписи, то есть вокруг cx/cy.
        labelScale: done ? CHECK_SCALE : 1,
        hideIcon: geo.hideIcon,
        iconColor: done && lightBg ? CHECK_DARK : undefined,
        trace: {
          dx: cx - W2,                             // центр подписи/галочки от центра холста
          gx: gxD - W2,                            // центр зерна от центра холста
          r: gR,                                   // радиус зерна: голос
          v,                                       // сила голоса после вентиля фразы
          b: breath,                               // дыхание зерна во фразе, px
          gap,                                     // зазор зерно — стол: перешеек
          w: capWv,                                // ширина стола
          jy,                                      // подскок/оседание реакции
          shape: Math.max(mA, sA),                 // доля морфа или Sunny
        },
      };
    },
  });
})();
