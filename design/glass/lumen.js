/* «Линза·Свет» — второй круг, вариант 1: тихий эталон.
 *
 * Материал — стекло «Линзы» без изменений. Капсула почти не меняет форму: голос
 * показан светом, который рождается под значком микрофона и растекается по кромке,
 * как по световоду; ожидание — прозрачный «думающий» диск с формами Material 3;
 * итог — цвет в кромке (kit.js) и короткая интонация Дарви. Дарви здесь — сама
 * капсула: весь его язык — подскок, оседание и кивок одного и того же тела.
 *
 * Свет один, а носителей у него три, потому что белый свет виден не везде: на
 * тёмном — белая полоса у кромки и свечение изнутри, на белом — тёмное ребро,
 * освещённое со стороны микрофона, и ореол точки её же цветом. Все три идут от
 * одного уровня фраз, поэтому в паузе гаснут вместе.
 */
(function () {
  'use strict';

  const BASE_H = 56;          // паспортная высота: стекло 13/41 px
  const DISC = 52;            // «думающий» диск
  const DONE_D = 56;          // диск «Готово» — чуть крупнее думающего: выдох после работы
  const LIGHT0 = -Math.PI / 4; // покой: свет сверху справа (экранные оси, y вниз)
  // Пока гаснет подпись «Слушаю», капсула стоит: иначе буквы на последних кадрах
  // вылезли бы за сжимающуюся кромку. 0.12 с — чуть меньше перехода CSS основы.
  const CONTRACT_DELAY = 0.12;
  const SEQ = ['Cookie4', 'Cookie9', 'Clover4Leaf', 'Oval', 'Circle'];

  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const smooth = (a, b, x) => { const t = clamp01((x - a) / (b - a)); return t * t * (3 - 2 * t); };

  const SHAPE = `
uniform vec2 uCenter;
uniform vec2 uSize;       // полная ширина и высота силуэта, px
uniform float uFlower;    // сила лепестков M3: 0 — гладкая капсула или круг
uniform vec4 uA; uniform vec2 uAe; uniform vec4 uB; uniform vec2 uBe;
uniform vec2 uMorph;      // прогресс A→B и поворот
uniform float uLensExt;   // на сколько px линза шире силуэта: описанный круг морфа

// Радиус торца — половина МЕНЬШЕЙ стороны: у sdPill он всегда h/2, и вытянутый
// подскоком диск (h > w) ломался бы. Так капсула, круг и сплюснутый круг — одно тело.
float sdBody(vec2 p, vec2 c, vec2 size) {
  vec2 hs = max(size * 0.5, vec2(0.5));
  return sdRoundBox(p - c, hs, min(hs.x, hs.y));
}
float shape(vec2 p) {
  float d = sdBody(p, uCenter, uSize);
  if (abs(uFlower) < 0.001) return d;
  float R = 0.5 * min(uSize.x, uSize.y);
  return mix(d, sdMorph(p, uCenter, R, uA, uAe, uB, uBe, uMorph.x, uMorph.y), uFlower);
}
// Линза — от гладкого описанного круга: фон ломается как у круглой капли, а
// лепестки видны только силуэтом, бликом и тёмной кромкой — по ним бегут искры.
#define LG_LENS_SHAPE
float lensShape(vec2 p) { return sdBody(p, uCenter, uSize + 2.0 * uLensExt); }
`;

  const MAIN = `
uniform float uMat;
uniform float uBevel;
uniform float uAmp;
uniform vec2 uLight;
uniform float uSpec;      // сила лепестка света у кромки со стороны источника (покой 0.2)
uniform float uLobe;      // показатель лепестка: меньше — длиннее освещённая дуга
uniform vec4 uVoice;      // xy — источник голоса (значок), z — сила света, w — длина засветки на тёмном, px
uniform vec2 uReach;      // x — длина тёмного ребра на светлом, px; y — ширина полосы света, px
uniform vec2 uGlow;       // свечение изнутри: сила и радиус, px
uniform vec4 uDot;        // ореол точки-значка: xy — центр, z — сила, w — радиус, px
uniform vec3 uDotColor;   // цвет точки «Слушаю»

void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  // Дальше ~100 px от линзы тень меньше 1/255: фон как есть, без морфа и нормалей —
  // основная площадь холста почти бесплатна. Линза — дешёвая капсула, силуэт внутри неё.
  float dl = lensShape(p);
  if (uMat <= 0.001 || dl > 100.0) { outColor = vec4(bg, 1.0); return; }
  float mc = clamp(uMat, 0.0, 1.0);
  Glass g = defaultGlass();
  g.bevel = uBevel;
  g.amplitude = uAmp;
  g.light = uLight;
  g.materialize = uMat;
  // Как у «Линзы»: лёгкое расхождение каналов только в бортике — в центре смещения
  // нет, и тройная выборка там была бы пустой тратой.
  g.dispersion = (-dl < uBevel + 1.0) ? 0.035 : 0.0;
  vec4 glass = liquidGlass(p, g, bg);
  vec3 col = glass.rgb;
  if (glass.a <= 0.0) { outColor = vec4(col, 1.0); return; }

  vec2 n;
  float inside = max(-shapeDist(p, n), 0.0);
  float wide = uReach.y;
  if (inside < max(wide, 1.25 + 2.2 * uVoice.z) + 0.5) {
    // Лепесток света «Линзы»: узкая дуга у кромки вокруг направления на источник
    // и вдвое слабее напротив. На лепестках морфа именно он даёт искры.
    float c = dot(n, uLight);
    float lobe = pow(max(c, 0.0), uLobe) + 0.5 * pow(max(-c, 0.0), uLobe);
    float k = lobe * uSpec;
    float bright = smoothstep(0.5, 0.85, luma(col));
    // Свет голоса: источник под значком микрофона, стекло ведёт его по кромке, как
    // световод. Громче — ярче и дальше от значка. Медленный шум по длине — свет
    // живой, но почти стоит на месте: никакой бегущей по кромке кометы.
    // На тёмном белая полоса короткая (гаусс): длинная превращала капсулу в стекло
    // в белой обводке. На светлом тёмное ребро видно слабее, и ему нужна длина — во
    // фразе оно доходит до середины капсулы, а не остаётся пятном у торца, — но со
    // спадом острее гаусса (показатель 1.5): темнее всего у значка, к середине
    // вполсилы, в правой трети почти нет. Ровное по всей кромке ребро читалось
    // рамкой фокуса, а не светом от микрофона.
    float dd = max(length(p - uVoice.xy) - 0.5 * uSize.y, 0.0);
    float rl = mix(uVoice.w, uReach.x, bright);
    float reach = exp(-pow(dd / max(rl, 1.0), mix(2.0, 1.5, bright)));
    reach *= 0.8 + 0.2 * vnoise(vec2(dd * 0.035 - uTime * 0.2, step(uCenter.y, p.y) * 5.0));
    float kv = uVoice.z * reach;
    k = min(k + kv, 1.0) * glass.a * mc;
    // На тёмном свет — осветление преломлённого фона. На светлом осветлять нечего,
    // и свет читается контрастом: тонкая тёмная линия ребра со стороны света, как
    // край стекла на белой бумаге. Для голоса она шире и темнее — ради документа.
    float band = 1.0 - smoothstep(0.3, wide, inside);
    col += (1.0 - col) * band * k * (1.0 - 0.6 * bright);
    float edge = 1.0 - smoothstep(0.35, 1.25 + 2.2 * kv, inside);
    col *= 1.0 - (0.42 + 0.45 * kv) * bright * edge * k;
  }
  // Ореол точки-значка её же цветом: белый свет на белом не виден, а цветной —
  // виден. Это свет того же источника, что и полоса у кромки, поэтому цвет один —
  // цвет точки. На светлом — подмес цвета в стекло, на тёмном — вдвое слабее
  // цветной свет: там голос уже несут белый свет и свечение.
  vec2 dp = p - uDot.xy;
  // Дальше трёх радиусов гаусс меньше 1e-4: там ореола нет, считать нечего.
  if (uDot.z > 0.003 && dot(dp, dp) < 9.0 * uDot.w * uDot.w) {
    vec2 dq = dp / max(uDot.w, 1.0);
    float hk = exp(-dot(dq, dq)) * uDot.z * glass.a * mc;
    float lb = smoothstep(0.45, 0.8, luma(col));
    vec3 tinted = mix(col, uDotColor, hk);
    vec3 lit = col + (1.0 - col) * uDotColor * (0.5 * hk);
    col = mix(lit, tinted, lb);
  }
  // Свечение «из-под пальца», где палец — сама точка: середину она закрывает, и
  // свет встаёт кольцом вокруг неё. Без окна белое облако поднимало стекло у точки
  // почти до её яркости, и на тёмном она растворялась в нём, отличаясь только
  // оттенком. Окно — радиус точки (3.7 px) плюс ~1.5 px, дальше свечение
  // набирается к 14 px, ещё до первой буквы (18 px). Не глухое: треть света
  // остаётся и в окне, иначе тёмное кольцо у точки внутри белого читалось зрачком.
  // Окно — только на тёмном стекле: там подъём фона съедает контраст точки. На
  // обоях точка темнее стекла, и светлое поле вокруг, наоборот, её выделяет.
  float dimGlass = 1.0 - smoothstep(0.35, 0.55, luma(col));
  float hole = mix(1.0, mix(0.3, 1.0, smoothstep(5.0, 14.0, length(p - uVoice.xy))), dimGlass);
  col = touchGlow(col, p, uVoice.xy, uGlow.y, uGlow.x, glass.a * mc * hole);
  col = statusRim(col, p, inside, glass.a);
  outColor = vec4(col, 1.0);
}
`;

  LG.register({
    id: 'lumen',
    round: 2,

    setup(ctx) {
      this.prog = ctx.program(ctx.glsl.header + ctx.glsl.common + ctx.glsl.morph + SHAPE
        + ctx.glsl.glass + ctx.glsl.status + ctx.glsl.touch + MAIN);
      const S = ctx.Spring;
      // Материализация как у «Линзы»: мягкий подход с лёгким перелётом.
      this.mat = new S(0, 0.4, 0.8);
      this.w = new S(160, 0.5, 0.85);
      this.h = new S(BASE_H, 0.5, 0.85);
      this.flower = new S(0, 0.5, 0.85);
      // Голос фразами: апериодическая пружина поверх уровня (отклик — по темпераменту).
      this.voice = new S(0, 0.36, 1.0);
      this.accent = new S(0, 0.5, 0.9);
      this.dy = new S(0, 0.3, 1.0);
      this.dx = new S(0, 0.3, 0.4);
      this.spec = new S(0.2, 0.35, 1.0);
      this.label = new S(0, 0.2, 1.0);
      this.tp = new S(0, 0.5, 1.0);
      // Галочка: 0 — зелёный основы, 1 — тёмно-зелёный для светлого фона.
      this.ink = new S(0, 0.25, 1.0);
      // Тон подписи (светлый/тёмный текст) выбирает основа по фону под плашкой и
      // пишет в data-tone; в s его нет, поэтому читаем решение основы прямо с подписи.
      this.labelEl = ctx.root ? ctx.root.querySelector('.lg-label') : null;
      this.dotColor = [1, 0.373, 0.427];
      this.status = new LG.StatusFlash();
      this.morph = new LG.Morph(SEQ);
      this.stage = 'hidden';
      this.from = 'hidden';
      this.lvSlow = 0;
      this.first = true;
      this.shakePending = false;
    },

    frame(ctx, s) {
      const dt = s.dt;
      if (this.first) { this.tp.snap(s.temper || 0); this.first = false; }
      // Темперамент тоже на пружине: переключатель на странице не дёргает форму.
      const tp = this.tp.set(s.temper || 0).step(dt);
      const T = (cat, lively) => cat + (lively - cat) * tp;

      if (s.stage !== this.stage) {
        this.from = this.stage;
        this.stage = s.stage;
        if (s.shown && this.from === 'hidden' && this.mat.value < 0.05) {
          // Из невидимого форма сразу встаёт по месту: появление — рост линзы,
          // а не растяжение.
          const d = s.stage === 'listening' || s.stage === 'error' ? null : (s.stage === 'done' ? DONE_D : DISC);
          this.w.snap(d || s.targetW);
          this.h.snap(d || BASE_H);
          this.flower.snap(0);
          this.morph.reset();
          this.dy.snap(0);
          this.dx.snap(0);
        }
        this.shakePending = s.stage === 'error';
      }

      const listening = s.stage === 'listening';
      const thinking = s.stage === 'transcribing' || s.stage === 'polishing';
      const done = s.stage === 'done';
      const error = s.stage === 'error';

      // ---- материализация: на уходе быстрее и без перелёта (как у «Линзы»)
      if (s.shown) { this.mat.response = 0.4; this.mat.damping = 0.8; }
      else { this.mat.response = 0.32; this.mat.damping = 1.0; }
      const m = this.mat.set(s.shown ? 1 : 0).step(dt);
      const mc = clamp01(m);
      this.status.step(s);

      // ---- голос: свет фразами, акцент — по редкому пику
      // Спад ведёт уровень, а не «говорит сейчас»: вентиль фразы гаснет полсекунды,
      // и короткая пауза между фразами в нём тонула бы; вентиль лишь страхует от
      // шума. Второе сглаживание (140 мс) и пружина гасят рябь слогов 4–6 Гц.
      // Окно 0.4…0.9 оставляет разницу тихой и громкой фразы (0.6 против 1).
      const lv = clamp01((s.level - 0.4) / 0.5);
      this.lvSlow += (lv - this.lvSlow) * (1 - Math.exp(-dt / 0.14));
      const drive = listening ? this.lvSlow * smooth(0, 0.5, s.speech) : 0;
      // Кот подхватывает голос мягче, «живее» — быстрее; в паузах оба замирают.
      // После «Слушаю» свет гаснет быстрее: иначе ореол точки и свечение ещё висели
      // бы на месте значка, когда капсула уже стягивается в диск.
      this.voice.response = listening ? T(0.36, 0.28) : 0.2;
      const v = clamp01(this.voice.set(drive).step(dt));
      if (listening) {
        for (const e of s.events) {
          if (e.type === 'peak') this.accent.velocity += T(13, 19) * (0.5 + 0.5 * e.strength);
        }
      }
      this.accent.response = T(0.55, 0.42);
      const acc = Math.max(0, this.accent.set(0).step(dt));

      // ---- форма: капсула под подпись, диск в работе и в «Готово»
      let tw = this.w.target;
      let th = this.h.target;
      if (s.shown) {
        if (listening || error) { tw = s.targetW; th = BASE_H; }
        else if (thinking) {
          const hold = this.from === 'listening' && s.stage === 'transcribing' && s.t < CONTRACT_DELAY;
          if (!hold) { tw = DISC; th = DISC; }
        } else if (done) { tw = DONE_D; th = DONE_D; }
      }
      if (thinking) { this.w.response = 0.5; this.w.damping = 0.86; }
      else if (done) { this.w.response = 0.42; this.w.damping = 0.8; }
      else { this.w.response = 0.46; this.w.damping = 0.84; }
      this.h.response = this.w.response;
      this.h.damping = this.w.damping;
      const w = this.w.set(tw).step(dt);
      const h = this.h.set(th).step(dt);

      // Лепестки растут, только когда капсула почти стала кругом: иначе цветок на капсуле.
      const round = clamp01(1 - (Math.abs(w - h) - 3) / 8);
      const flowerOn = thinking && round > 0.9 && w < DISC + 8;
      if (done) { this.flower.response = 0.4; this.flower.damping = T(0.72, 0.6); }
      else if (error || !s.shown) { this.flower.response = 0.26; this.flower.damping = 1.0; }
      else { this.flower.response = 0.5; this.flower.damping = 0.85; }
      // Перелёт ниже нуля — доля лепестков наизнанку: диск «круглеет» с затухающим
      // вздрагиванием, но глубже 0.15 это уже не круг.
      const fs = Math.max(-0.15, Math.min(1.05, this.flower.set(flowerOn ? 1 : 0).step(dt)));
      // Лепестки живут только на круглом теле: на раскрывающейся капсуле ошибки
      // остаток овала перекашивал её на пару кадров.
      const f = fs * round;
      // Цикл M3 идёт, когда лепестки уже набрались; в «Готово» форма замирает там,
      // где её застал итог, и круглеет — без скачка к первой форме.
      this.morph.p.damping = T(0.7, 0.6);
      if (thinking && fs > 0.5) this.morph.step(dt, T(1, 1.12) * (s.stage === 'polishing' ? 1.08 : 1));
      // Сброс к первой форме — только когда вздрагивание круга совсем улеглось:
      // на переходе через ноль лепестки ещё есть, и смена формы была бы скачком.
      else if (!thinking && Math.abs(fs) < 0.003 && Math.abs(this.flower.velocity) < 0.05) this.morph.reset();
      const mu = this.morph.uniforms;
      const maxM = Math.max(LG.shapes[this.morph.from].max, LG.shapes[this.morph.to].max);

      // ---- реакция Дарви в «Готово»: вертикаль тела на одной пружине
      let dyT = 0;
      if (done) {
        const t = s.t;
        if (s.emotion === 'joy') {
          // Радость делит: подскок. Кот — один мягкий, без отскока; «живее» —
          // приседает перед прыжком и приземляется с отскоком 0.35.
          // Высота подскока — 12–18% диска: меньше 5 px глаз на 56-пиксельном теле
          // не отличал от кивка. Старт — на спаде зелёной вспышки (её пик ~0.2 с) и
          // после того, как диск округлился: иначе подскок сливался со статусом и не
          // читался отдельной интонацией.
          const crouch = T(0.8, 2.2);
          const top = T(0.52, 0.48);
          // Приземление: у кота ζ 0.86 — улёгся без отскока; у «живее» ζ 0.45 —
          // один видимый отскок ~20% высоты (DARVI.md: «отскок 0.3»), при 0.65 он
          // был полпикселя и «живее» читался просто котом повыше.
          if (t > 0.22 && t < 0.3) { dyT = crouch; this.dy.response = 0.12; this.dy.damping = 1; }
          else if (t >= 0.3 && t < top) { dyT = -T(7.5, 10.5); this.dy.response = T(0.3, 0.24); this.dy.damping = T(1, 0.9); }
          else if (t >= top) { dyT = 0; this.dy.response = T(0.48, 0.42); this.dy.damping = T(0.86, 0.45); }
        } else if (s.emotion === 'sad') {
          // На грусть — бережно: медленно оседает и сплющивается, как вздох, и так
          // и остаётся до ухода. У кота перед оседанием короткий вдох вверх:
          // предвосхищение объясняет движение вниз, и тихое тело читается как «вздохнул».
          // У «живее» оседание глубже и быстрее, с сочувственным кивком: ζ 0.6 даёт
          // перелёт ~10% и мягкий возврат — ему вдох не нужен. При ζ 0.82 перелёт
          // был 0.05 px, и кот с «живее» в грусти различались только на пиксель.
          const inhale = T(1.2, 0);
          if (t > 0.15 && t < 0.35 && inhale > 0.05) { dyT = -inhale; this.dy.response = 0.2; this.dy.damping = 1; }
          else if (t > 0.15) { dyT = T(5, 7); this.dy.response = T(0.95, 0.7); this.dy.damping = T(1, 0.6); }
        } else {
          // Нейтральное «Готово» — удовлетворённое оседание, короткий кивок. Кивок —
          // на спаде зелёной вспышки (её пик ~0.2 с) и после округления диска:
          // начатый раньше, он тонул в статусе, как раньше тонула радость.
          if (t > 0.24 && t < 0.36) { dyT = T(3, 3.8); this.dy.response = 0.2; this.dy.damping = 1; }
          else if (t >= 0.36) { dyT = 0; this.dy.response = T(0.42, 0.38); this.dy.damping = T(0.85, 0.72); }
        }
      } else if (s.shown) {
        this.dy.response = 0.4; this.dy.damping = 1;
      }
      // На уходе вертикаль стоит: реакция «держится и на уходе после него».
      const dy = s.shown ? this.dy.set(dyT).step(dt) : this.dy.value;
      const vy = this.dy.velocity;

      // ---- ошибка: «мотает головой» — смущённое «нет-нет»: качок и полтора
      // затухающих колебания. Один качок с возвратом в пиксель на листе почти не
      // читался; ζ 0.34 даёт вторую, втрое меньшую отмашку — жест, но без тревоги.
      // Качок — после раскрытия капсулы и на спаде красной вспышки: начатый раньше,
      // он читался как кривое раскрытие, а не как отдельный жест.
      if (this.shakePending && error && (Math.abs(w - s.targetW) < 5 || s.t > 0.32)) {
        // Импульс — на ~6 px у кота и ~9 px у «живее»: при ζ 0.34 отмашка растёт,
        // и прежние 240/320 давали коту 7 px — это уже тревожнее, чем «смущённо».
        this.dx.velocity += T(215, 300);
        this.shakePending = false;
      }
      this.dx.response = 0.3;
      this.dx.damping = T(0.34, 0.3);
      const dx = this.dx.set(0).step(dt);

      // ---- свет у кромки: покой 0.2, в работе ярче — лепестки искрят; в грусти тише
      let specT = 0.2;
      if (thinking) specT = 0.7;
      else if (done && s.emotion === 'sad' && s.t > 0.15) specT = 0.1;
      const spec = this.spec.set(specT).step(dt);
      // Радость — блик вспыхивает на вершине подскока: стекло поймало свет.
      let glint = 0;
      if (done && s.emotion === 'joy') glint = T(0.35, 0.55) * smooth(0.32, 0.44, s.t) * (1 - smooth(0.52, 0.95, s.t));

      // ---- сжатие и растяжение от вертикали: вниз от покоя — сплющивается,
      // быстрое движение — вытягивается по ходу. Объём держится: что ушло по высоте,
      // пришло в ширину.
      const press = Math.max(0, dy);
      const stretch = Math.min(1, Math.abs(vy) / 260) * T(1.5, 3);
      let bw = w - 0.6 * stretch + 0.6 * press;
      let bh = h + stretch - 0.75 * press;
      // Дыхание голосом: до 3–4 px по высоте, толщина стекла от него не меняется.
      const breath = T(3, 3.6) * v + T(0.4, 1) * acc;
      bw += 1.2 * breath;
      bh += breath;

      const scale = 0.96 + 0.04 * m;
      const cx = ctx.W / 2 + dx;
      const cy = ctx.H / 2 + dy;
      const W = Math.max(bw, 8) * scale;
      const H = Math.max(bh, 8) * scale;
      const R = 0.5 * Math.min(W, H);
      const lensExt = R * (maxM - 1) * Math.max(0, f);

      // ---- оптика «Линзы»: толщина как размер^0.3 от 13/41 для 56 px; размер —
      // меньшая сторона без дыхания и реакции, поэтому голос толщину не трогает.
      // A идёт как m (на уходе m²): иначе зеркальная полоса ломала бы фон, когда
      // тело линзы уже растаяло.
      const size = Math.min(w, h) + 2 * lensExt;
      const thick = Math.pow(Math.max(size, 20) / BASE_H, 0.3);
      const fade = s.shown ? mc : mc * mc;
      const amp = 41 * thick * fade;
      const bevel = 13 * thick * (0.35 + 0.65 * mc);

      // ---- источник голоса — значок микрофона основы (иконка 16 px слева в подписи)
      const iconX = cx - s.contentW / 2 + 8;
      const src = listening || this.lastSrc == null ? [iconX, cy] : this.lastSrc;
      if (listening) { this.lastSrc = src; this.dotColor = s.accent; }
      // Свет гаснет к дальнему торцу: засвеченная целиком кромка читалась бы как
      // рамка фокуса, а не как свет, пришедший от микрофона. Фраза держит свет на
      // ~0.7, запас до 1 — у ударных мест (пиков): иначе в ровной речи свет стоял бы
      // «включённым», а акцент упирался бы в потолок.
      const vz = Math.min(1, 0.72 * v + 0.4 * acc);
      // На тёмном — короткая узкая белая полоса (до середины капсулы доходит только
      // на пике), на светлом — тёмное ребро: во фразе у середины капсулы ~половина
      // силы, в правой трети — меньше четверти (см. шейдер). Длинное, 24 + 70·v,
      // тянулось почти по всей кромке и читалось контуром фокуса.
      const reach = 14 + 34 * v + 30 * acc;
      const reachLight = 18 + 24 * v + 22 * acc;
      const wide = 1.8 + 0.6 * vz;
      // Свечение кольцом вокруг точки (окно в шейдере), поэтому радиус чуть больше:
      // кольцо должно читаться боковым зрением, а не прятаться под значком.
      const glowA = Math.min(1, 0.64 * v + 0.36 * acc);
      const glowR = 18 + 6 * v + 5 * acc;
      // Ореол точки: в паузе его нет, во фразе он держится, на пике чуть набухает.
      // Гаусс радиусом 12–16 px: у первой буквы (18 px от центра точки) во фразе
      // ~5% подмеса, на пике до ~15% — подпись остаётся на спокойном стекле, её
      // контраст на пике не падает (contrast.py).
      const dotA = Math.min(0.7, 0.56 * v + 0.2 * acc);
      const dotR = 6 + 7 * v + 3 * acc;

      // ---- подпись: последней, только когда форма вмещает её целиком
      // fit — страховка на каждом кадре; проявление же начинается, только когда
      // форма уже вместила подпись с запасом, иначе растущая капсула открывала бы
      // её за три кадра.
      const fit = clamp01((W - s.contentW - 16) / 10);
      let labT = 0;
      if (s.shown && mc > 0.8) {
        if (listening || error) labT = fit >= 0.999 || (this.label.target === 1 && fit > 0) ? 1 : 0;
        else if (done) labT = s.t > 0.08 && fs < 0.35 ? 1 : 0;
      }
      this.label.response = labT > this.label.value ? 0.2 : 0.1;
      const lab = clamp01(this.label.set(labT).step(dt));
      const opacity = lab * fit * smooth(0.8, 0.97, mc);
      // «Готово» проступает из короткого размытия: так читается «проявился».
      const blur = (1 - lab) * (done ? 4 : 2);

      // ---- галочка: единственное содержимое «Готово», поэтому ей нужен контраст
      // значка (3:1). Зелёный основы #4FDCA6 на тёмном даёт 4.5–5.7, а на белом и
      // светлых обоях ~1.5. Там галочка тёмно-зелёная #07472F: это всё ещё зелёный
      // итога, а сам цвет статуса несёт кромка. Пока галочка едва проступает (или
      // тон ещё не выбран — «Готово» сразу из невидимого), цвет встаёт сразу: на
      // появлении она не перекрашивается на глазах. Пружина — только для смены тона
      // посреди «Готово», когда плашка переехала на другой фон.
      const tone = this.labelEl ? this.labelEl.dataset.tone : '';
      const inkT = done && tone === 'dark' ? 1 : 0;
      if (opacity < 0.35 || !this.toneKnown) this.ink.snap(inkT); else this.ink.set(inkT).step(dt);
      this.toneKnown = !!tone && s.shown;
      const ink = clamp01(this.ink.value);
      const mixc = (a, b) => Math.round(a + (b - a) * ink);
      const iconColor = done ? `rgb(${mixc(79, 7)}, ${mixc(220, 71)}, ${mixc(166, 47)})` : undefined;

      ctx.draw(this.prog, {
        uCenter: [cx, cy], uSize: [W, H], uFlower: f, uLensExt: lensExt,
        uA: mu.A, uAe: mu.Ae, uB: mu.B, uBe: mu.Be, uMorph: [mu.t, mu.rot],
        uMat: m, uBevel: bevel, uAmp: amp,
        uLight: [Math.cos(LIGHT0), Math.sin(LIGHT0)],
        uSpec: spec + glint, uLobe: 6 - 2.5 * glint,
        uVoice: [src[0], src[1], vz, reach],
        uReach: [reachLight, wide],
        uGlow: [glowA, glowR],
        uDot: [src[0], src[1], dotA, dotR],
        uDotColor: this.dotColor,
        uStatus: this.status.uniform,
      });

      return {
        cx, cy,
        labelOpacity: opacity,
        // В «Готово» галочка — всё содержимое диска. Значок основы 16 px занимал
        // меньше пятой части диаметра, и когда зелёная кромка гасла, боковым
        // зрением диск читался пустым. ×1.4 — ~40% диаметра, как у системных
        // галочек Apple, и штрих толще в ту же долю: на обоях заметнее при том же
        // цвете. Масштаб основа ставит вокруг центра подписи, то есть вокруг cx/cy.
        labelScale: done ? 1.4 : 1,
        labelBlur: blur,
        hideLabel: thinking || opacity < 0.01,
        iconColor,
        // light — видимая сила света голоса (фраза + акцент пика), dot — ореол точки,
        // h — дыхание, w — ширина, petal — сила лепестков морфа, dy — реакция Дарви,
        // dx — встряска, ink — доля тёмно-зелёного в галочке.
        trace: { light: vz, dot: dotA, w: W, h: H, petal: f, dy, dx, ink },
      };
    },
  });
})();
