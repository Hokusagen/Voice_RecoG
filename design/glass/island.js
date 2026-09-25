/* «Остров»: тёмное плотное стекло в духе Dynamic Island и Siri iOS 27.
 *
 * Единственный тёмный материал из шести: самый читаемый поверх любого фона и
 * самые большие смены силуэта — капля → капсула → «думающий» диск → капсула.
 * Всё тело — одно поле расстояний: капсула, лепестки диска и капля-якорь
 * появления сшиты в одной функции shape(), поэтому блик и линза кромки
 * непрерывны на всех кадрах морфа.
 */
(function () {
  'use strict';

  const FONT = '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif';
  const HEIGHT = 56;
  const DROP_BELOW = 45;          // капля набухает на 45 px ниже центра плашки
  const LOBES = [5, 7, 4];        // лепестки диска по кругу
  // Глубина лепестков в долях радиуса: у 7 мельче, чтобы вершины не стали
  // острее бортика линзы (иначе в преломлении видна складка по медиальной оси).
  const LOBE_AMP = [0.1, 0.07, 0.115];
  const WAVE_W = 64;              // ширина осциллограммы в «Слушаю»
  const HIST = 24;

  const SHAPE = `
uniform vec4 uBody;     // центр xy и полный размер wh основного тела
uniform vec3 uAnchor;   // капля-якорь появления: центр xy и радиус
uniform float uK;       // вздутие smin, px
uniform vec4 uLobe;     // сила лепестков, глубина A, глубина B, прогресс A→B
uniform vec3 uLobeN;    // число лепестков A, B и поворот
float shape(vec2 p) {
  vec2 q = p - uBody.xy;
  vec2 hs = max(uBody.zw * 0.5, vec2(0.01));
  // Радиус всегда половина меньшей стороны: иначе в середине морфа «плечи».
  float r = min(hs.x, hs.y);
  float d = sdRoundBox(q, hs, r);
  if (uLobe.x > 0.001) {
    // Многолистник r(θ)=R·(1+a·cos(nθ+φ)); две формы смешиваются по прогрессу,
    // поэтому n меняется без разрыва на θ=±π (дробное n дало бы шов).
    float th = atan(q.y, q.x) - uLobeN.z;
    float off = r * mix(uLobe.y * cos(uLobeN.x * th), uLobe.z * cos(uLobeN.y * th), uLobe.w);
    // Гасим лепестки к центру как (ρ/R)²: иначе угловая производная ~1/ρ
    // взрывает градиент, и от центра расходятся «спицы» ложной кромки.
    float rho = min(length(q) / r, 1.0);
    d -= off * uLobe.x * rho * rho;
  }
  if (uAnchor.z > 0.05) {
    // Неактивную каплю гасим множителем на k, иначе она раздувает тело изнутри.
    float pres = clamp(uAnchor.z / 11.0, 0.0, 1.0);
    d = smin(d, length(p - uAnchor.xy) - uAnchor.z, uK * pres);
  }
  return d;
}
`;

  const MAIN = `
uniform vec4 uBox;       // рамка, за которой пиксель — просто фон
uniform float uMat;      // материализация 0..1
uniform float uBevel;
uniform float uAmp;
uniform vec3 uGlowCol;
uniform float uGlow;
uniform vec4 uWave;      // x0, x1, y центра, видимость
uniform vec3 uWaveCol;
uniform float uHist[${HIST}];

const vec3 TINT = vec3(0.043, 0.043, 0.055);   // #0B0B0E

vec3 vibrant(vec3 c) {
  float l = luma(c);
  return clamp(1.45 * (vec3(l) + 2.07 * (c - vec3(l))) + 0.05, 0.0, 1.0);
}

// Жидкая осциллограмма: амплитуда по истории уровня (слева старое), форма —
// две медленные синусоиды, чтобы линия текла, а не дёргалась по сэмплам.
vec3 wave(vec2 p, vec3 col) {
  float span = uWave.y - uWave.x;
  float u = (p.x - uWave.x) / span;
  if (u < 0.0 || u > 1.0 || abs(p.y - uWave.z) > 24.0) return col;
  float fi = u * float(${HIST - 1});
  int i0 = int(floor(fi));
  int i1 = min(i0 + 1, ${HIST - 1});
  float fr = fract(fi);
  // Кривая Эрмита между точками истории: без изломов на вершинах.
  float a = mix(uHist[i0], uHist[i1], fr * fr * (3.0 - 2.0 * fr));
  float win = pow(sin(3.14159 * u), 1.4);
  float amp = (1.2 + 12.5 * a) * win;
  float x = p.x * 0.17;
  float s1 = sin(x - uTime * 6.1), s2 = sin(x * 1.83 + uTime * 3.4 + 1.3);
  float y = uWave.z + amp * (0.64 * s1 + 0.36 * s2);
  // Производная для честной толщины линии на крутых участках.
  float dy = amp * 0.17 * (0.64 * cos(x - uTime * 6.1) + 0.36 * 1.83 * cos(x * 1.83 + uTime * 3.4 + 1.3));
  float dist = abs(p.y - y) / sqrt(1.0 + dy * dy);
  float core = exp(-dist * dist / 0.9);
  float glow = exp(-dist * dist / 22.0);
  // Вторая, тихая линия в противофазе — объём «ленты», а не второй ритм.
  float y2 = uWave.z - amp * 0.55 * (0.5 * s1 + 0.5 * sin(x * 1.3 - uTime * 2.2));
  float c2 = exp(-pow(p.y - y2, 2.0) / 1.6) * 0.28;
  float fade = smoothstep(0.0, 0.08, u) * smoothstep(1.0, 0.92, u);
  vec3 hot = mix(uWaveCol, vec3(1.0, 0.86, 0.88), 0.35);
  return col + (hot * core * 0.95 + uWaveCol * (glow * 0.32 + c2)) * uWave.w * fade;
}

vec3 island(vec2 p, vec3 bg) {
  float m = uMat;
  vec2 n;
  float dist = shapeDist(p, n);
  // Тень плотнее, чем у прозрачных стёкол: тёмному телу нужна опора на фоне.
  float sd = shape(p - vec2(0.0, 9.0));
  float yb = (p.y - uBody.y) / max(uBody.w * 0.5, 1.0);
  // Сверху тень почти не видна: свет падает сверху, ореол вокруг выглядел бы грязью.
  float shadow = m * 0.17 * exp(-max(sd, 0.0) / 17.0) * smoothstep(-17.0, 0.0, sd)
               * (1.0 - smoothstep(40.0, 70.0, sd)) * mix(0.3, 1.0, smoothstep(-1.2, 1.0, yb));
  vec3 under = bg * (1.0 - shadow);
  // Свечение стадии снаружи кромки: широкое и мягкое, чтобы читалось как свет
  // из стекла, а не как вторая обводка. На светлом фоне гасим — там цветная
  // линия отрывалась от силуэта наклейкой.
  float outside = max(dist, 0.0);
  under += uGlowCol * uGlow * m * 0.18 * exp(-outside / 9.0) * (1.0 - 0.6 * luma(bg));
  float cover = clamp(0.5 - dist * uDpr, 0.0, 1.0);
  if (cover <= 0.0) return under;

  float inside = max(-dist, 0.0);
  // Линза кромки как у общего стекла: выборка внутрь по нормали, A > h.
  float t = clamp(1.0 - inside / uBevel, 0.0, 1.0);
  float d = uAmp * m * uRefraction * (1.0 - sqrt(max(1.0 - t * t, 0.0)));
  float edge = smoothstep(0.0, uBevel * 0.9, inside);
  // В глубине размытие сильнее: сквозь плотную тонировку не должны читаться
  // строки документа, а у кромки фон остаётся узнаваемым.
  float sig = mix(3.2, 5.5, edge) * m;
  vec3 ref = sceneBlur(p - n * d, sig);
  if (d > 0.5) {
    // Лёгкая дисперсия только в бортике (там d > 0): край ломает свет на цвета.
    ref.r = sceneBlur(p - n * d * 1.08, sig).r;
    ref.b = sceneBlur(p - n * d * 0.92, sig).b;
  }
  ref = ref * 1.015 + 0.06;
  // Тонировка плотная в глубине и заметно тоньше в бортике: сквозь кромку
  // виден преломлённый фон — иначе с /flat не отличить, это и есть линза.
  float ta = mix(0.45, 0.87, edge) * m;
  vec3 col = mix(ref, TINT, ta);
  // Полировка: мягкое отражение студийного света в верхней части тела.
  float yn = (p.y - uBody.y) / max(uBody.w * 0.5, 1.0);
  col += vec3(0.9, 0.93, 1.0) * 0.045 * m * smoothstep(0.35, -1.0, yn) * smoothstep(0.0, 6.0, inside);
  // Блик 1 px цвета контента (до тонировки), чуть внутри кромки: снаружи
  // от него тёмный срез силуэта, поэтому на белом фоне край остаётся резким.
  vec2 L = normalize(vec2(0.62, -0.78));
  float w = pow(max(dot(n, L), 0.0), 2.0) + 0.5 * pow(max(-dot(n, L), 0.0), 2.0);
  vec3 vib = vibrant(ref);
  // Пол у блика: на тёмном фоне контент тёмный, и без него кромка пропала бы.
  vib = max(vib, vec3(0.36));
  float hair = exp(-pow(inside - 1.5, 2.0) / 0.5);
  col = mix(col, vib, hair * (0.22 + 0.78 * w) * m);
  float cut = 1.0 - smoothstep(0.2, 1.0, inside);
  col = mix(col, TINT * 0.7, cut * 0.75 * m);
  // Второй, мягкий отсвет на 3–4 px глубже: толщина стекла.
  float inner = exp(-pow(inside - 3.5, 2.0) / 3.0);
  col += vib * inner * 0.06 * (0.3 + w) * m;
  // Свечение стадии изнутри кромки.
  col += uGlowCol * uGlow * m * (0.55 * exp(-inside / 2.0) + 0.08 * exp(-inside / 9.0));
  if (uWave.w > 0.01) col = wave(p, col);
  return mix(under, col, cover);
}

void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  // Дальние пиксели — одна выборка фона, без поля расстояний.
  if (p.x < uBox.x || p.x > uBox.z || p.y < uBox.y || p.y > uBox.w) {
    outColor = vec4(sceneAt(p, 0.0), 1.0);
    return;
  }
  outColor = vec4(island(p, sceneAt(p, 0.0)), 1.0);
}
`;

  function hexRgb(hex) {
    const v = parseInt(hex.slice(1), 16);
    return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
  }

  const measure = document.createElement('canvas').getContext('2d');
  // Ширина содержимого HTML-текста: иконка 16 + два зазора по 10 + заголовок + деталь.
  function contentWidth(title, detail) {
    measure.font = `600 14px ${FONT}`;
    let w = 16 + 10 + measure.measureText(title).width + 10;
    measure.font = `400 13px ${FONT}`;
    if (detail) w += measure.measureText(detail).width;
    return Math.ceil(w);
  }

  LG.register({
    id: 'island',

    setup(ctx) {
      this.prog = ctx.program(ctx.glsl.header + ctx.glsl.common + SHAPE + ctx.glsl.glass + MAIN);
      const S = ctx.Spring;
      this.bx = new S(0, 0.4, 0.8);
      this.by = new S(0, 0.34, 0.72);
      this.bw = new S(0, 0.45, 0.7);
      this.bh = new S(0, 0.45, 0.75);
      this.ar = new S(0, 0.16, 0.9);
      this.ay = new S(0, 0.25, 0.8);
      this.mat = new S(0, 0.22, 0.9);
      this.shake = new S(0, 0.16, 0.22);
      this.flower = new S(0, 0.5, 0.8);
      this.label = new S(0, 0.22, 1.0);
      this.glow = new S(0, 0.35, 0.9);
      this.waveOn = new S(0, 0.3, 1.0);
      // Морф лепестков: пружина прогресса как у индикатора M3, но без
      // прыгучести 0.6 — ζ 0.72 спокойнее для стекла.
      this.morph = new S(0, 0.6, 0.72);
      this.morphIdx = 0;
      this.morphHold = 0;
      this.glowCol = [1, 1, 1];
      this.stage = 'hidden';
      this.appear = 99;
      this.hist = new Float32Array(HIST);
      this.listenContent = contentWidth('Слушаю', '0:00');
    },

    frame(ctx, s) {
      const dt = s.dt;
      const cx0 = ctx.W / 2;
      const cy0 = ctx.H / 2;

      if (s.stage !== this.stage) {
        const from = this.stage;
        this.stage = s.stage;
        if (from === 'hidden' && s.shown) {
          // Появление всегда из капли, в какую бы стадию ни шли.
          this.appear = 0;
          this.bx.snap(cx0);
          this.by.snap(cy0 + DROP_BELOW);
          this.bw.snap(0);
          this.bh.snap(0);
          this.ar.snap(0);
          this.ay.snap(cy0 + DROP_BELOW);
          this.mat.snap(0);
          this.flower.snap(0);
          this.label.snap(0);
        }
        // Встряску не даём сразу: на растущей ширине её не видно. Толчок — когда
        // капсула почти раскрылась (ниже по кадру).
        this.shook = s.stage !== 'error';
      }
      if (s.shown) this.appear += dt;

      // ---- цели геометрии
      const ap = this.appear;
      const doneContent = contentWidth(s.text.title, s.text.detail);
      let tw, th, ty = cy0, ar = 0, mat = s.shown ? 1 : 0;
      const listenW = 20 + this.listenContent + 14 + WAVE_W + 22;
      const thinking = s.stage === 'transcribing' || s.stage === 'polishing';
      if (s.shown && ap < 0.14) {
        // Набухает капля у нижнего края.
        tw = th = 30; ty = cy0 + DROP_BELOW; ar = 11;
        this.bw.response = 0.28; this.bw.damping = 0.62;
        this.bh.response = 0.28; this.bh.damping = 0.62;
      } else if (s.shown && ap < 0.27) {
        // Тянется вверх на шейке; якорь остаётся и рвёт перемычку, уходя.
        tw = th = 28; ty = cy0; ar = this.neckBroken ? 0 : 11;
      } else if (s.stage === 'listening') {
        tw = listenW; th = HEIGHT;
      } else if (thinking) {
        tw = th = HEIGHT;
      } else if (s.stage === 'done' || s.stage === 'error') {
        tw = doneContent + 48; th = HEIGHT;
      } else {
        // Уход: стягивается в каплю и опускается туда, откуда пришла.
        if (s.t < 0.14) { tw = th = 44; } else { tw = th = 0; ty = cy0 + 26; }
        mat = s.t < 0.14 ? 1 : 0;
      }

      if (s.shown && ap >= 0.27) {
        if (s.stage === 'done') { this.bw.response = 0.5; this.bw.damping = 0.7; }
        else if (thinking) { this.bw.response = 0.42; this.bw.damping = 0.8; }
        else { this.bw.response = 0.42; this.bw.damping = 0.7; }
        this.bh.response = 0.42; this.bh.damping = 0.78;
      } else if (!s.shown) {
        this.bw.response = this.bh.response = 0.3; this.bw.damping = this.bh.damping = 0.9;
      }

      this.bx.set(cx0).step(dt);
      this.by.set(ty).step(dt);
      this.bw.set(tw).step(dt);
      this.bh.set(th).step(dt);
      // Шейка рвётся, когда зазор между каплей и якорем превысил ~1.6k:
      // дальше якорь втягивается вверх, вслед за оторвавшейся каплей.
      if (s.shown && ap < 0.02) this.neckBroken = false;
      const bodyBottom = this.by.value + Math.max(0, this.bh.value) / 2;
      const gap = (this.ay.value - Math.max(0, this.ar.value)) - bodyBottom;
      if (!this.neckBroken && ap > 0.14 && gap > 11) this.neckBroken = true;
      if (this.neckBroken) ar = 0;
      // После разрыва остаток капли тянется к низу тела и сливается с ним
      // через smin — жидкость втягивается, а не висит отдельной точкой.
      this.ar.response = this.neckBroken ? 0.1 : 0.16;
      const bodyLow = this.by.value + Math.max(0, this.bh.value) / 2 - 4;
      this.ay.set(this.neckBroken ? bodyLow : cy0 + DROP_BELOW).step(dt);
      this.ar.set(ar).step(dt);
      this.mat.set(mat).step(dt);
      if (!this.shook && s.stage === 'error' && s.t > 0.2 && this.bw.value > 0.9 * tw) {
        this.shook = true;
        this.shake.velocity = 560;
      }
      const shake = this.shake.set(0).step(dt);

      // Лепестки только когда капсула уже почти диск: иначе цветок на капсуле.
      this.flower.response = thinking ? 0.55 : 0.28;
      this.flower.damping = thinking ? 0.8 : 0.95;
      this.flower.set(thinking && this.bw.value < 66 && ap > 0.4 ? 1 : 0).step(dt);
      // Лепестки живут только на почти круглом теле: на капсуле «Готово»
      // они дали бы волну по длинной кромке.
      const round = Math.max(0, Math.min(1, 1 - (this.bw.value - this.bh.value) / 22));
      const f = Math.max(0, this.flower.value) * round;
      // Цикл всегда начинается с пяти лепестков: пока цветок набухает, морф стоит.
      if ((thinking && this.flower.value < 0.6) || (!thinking && f < 0.002)) {
        this.morphIdx = 0; this.morph.snap(0); this.morphHold = 0;
      }

      // Цикл 5 → 7 → 4 лепестков; держим форму ~0.35 с после оседания пружины.
      const mp = this.morph.set(1).step(dt);
      if (Math.abs(mp - 1) < 0.01 && Math.abs(this.morph.velocity) < 0.05) {
        this.morphHold += dt;
        if (this.morphHold > 0.35) {
          this.morphIdx = (this.morphIdx + 1) % LOBES.length;
          this.morph.snap(0);
          this.morphHold = 0;
        }
      }
      const ia = this.morphIdx;
      const ib = (ia + 1) % LOBES.length;
      // Поворот на ту же пружину, что и морф, плюс очень медленный дрейф:
      // глаз читает это как одно движение.
      const rot = 0.38 * (ia + this.morph.value) + 0.12 * s.time;

      // ---- тело с учётом скорости: капля вытягивается на подъёме, капсула
      // приседает, пока быстро растёт в ширину.
      const vy = this.by.velocity;
      const stretch = Math.min(14, Math.max(0, -vy * 0.04)) * (ap < 0.6 ? 1 : 0);
      let w = Math.max(0, this.bw.value);
      let h = Math.max(0, this.bh.value) + stretch;
      if (w > 70) h *= 1 - 0.06 * Math.tanh(this.bw.velocity / 1400);
      w = Math.max(w, 0);
      const bx = this.bx.value + shake;
      // Вытягивается хвостом вниз: верх ведёт, низ отстаёт к якорю.
      const by = this.by.value + stretch * 0.4;

      // k по правилу основы: 5.25 в покое, до 8 в движении, никогда больше 10.
      const moving = Math.min(1, Math.abs(vy) / 250 + Math.abs(this.bh.velocity) / 400);
      const k = 5.25 + 2.75 * moving;

      // ---- свечение стадии
      let glowT = 0;
      if (thinking) glowT = 0.9 * Math.min(1, f * 1.4);
      else if (s.stage === 'error') glowT = s.t < 1.2 ? 1 : 0.6;
      else if (s.stage === 'done') glowT = 0.55 * Math.max(0, 1 - s.t / 0.9);
      const glow = Math.max(0, this.glow.set(glowT).step(dt));
      const a = Math.min(1, dt * 7);
      for (let i = 0; i < 3; i++) this.glowCol[i] += (s.accent[i] - this.glowCol[i]) * a;

      // ---- текст
      const listening = s.stage === 'listening';
      let labelT = 0;
      if (s.shown && ap > 0.3) {
        if (listening) labelT = 1;
        else if (s.stage === 'done' || s.stage === 'error') labelT = w > 0.7 * tw ? 1 : 0;
      }
      // Уход быстрее прихода (0.17 с против 0.22), без перелёта.
      this.label.response = labelT > this.label.value ? 0.22 : 0.17;
      const lab = Math.max(0, Math.min(1, this.label.set(labelT).step(dt)));
      const content = listening ? this.listenContent : doneContent;
      // Страховка: текст гаснет раньше, чем форма станет уже него.
      const need = listening ? content + 20 + 8 : content + 20;
      const fit = Math.max(0, Math.min(1, (w - need) / 20));
      const opacity = Math.min(lab, fit) * Math.min(1, this.mat.value * 1.5);
      const labelCx = listening ? bx - w / 2 + 20 + content / 2 : bx;

      // ---- осциллограмма
      // Линия привязана к тексту слева и видна, только когда целиком влезла
      // справа: пока капсула растёт, она не наезжает на таймер.
      const x0 = bx - w / 2 + 20 + this.listenContent + 14;
      const x1 = x0 + WAVE_W;
      const room = Math.max(0, Math.min(1, (bx + w / 2 - 16 - x1) / 8 + 1));
      const waveOn = Math.max(0, this.waveOn.set(listening && ap > 0.35 ? 1 : 0).step(dt)) * room;
      const hs = s.history;
      for (let i = 0; i < HIST; i++) {
        const j = Math.floor((i / (HIST - 1)) * (hs.length - 1));
        // Лёгкое сглаживание по соседям — линия «жидкая», без ступенек слогов.
        const at = (o) => hs[Math.max(0, Math.min(hs.length - 1, j + o))];
        const v = (at(-4) + 2 * at(-2) + 3 * at(0) + 2 * at(2) + at(4)) / 9;
        this.hist[i] = v;
      }

      // Бортик толще у большого стекла (размер^0.3), тоньше на лепестковом диске.
      const size = Math.max(20, Math.min(w, h));
      const bevel = 13 * Math.pow(size / HEIGHT, 0.3) * (1 - 0.3 * f);
      const amp = 41 * Math.pow(size / HEIGHT, 0.3) * (1 - 0.25 * f);

      const ancY = this.ay.value;
      // Остаток якоря меньше 4 px рисовался бы колечком от блика — убираем сразу;
      // к этому моменту он уже внутри тела.
      const arV = this.ar.value > 4 ? this.ar.value : 0;
      const margin = 72;
      const box = [
        Math.min(bx - w / 2, cx0 - arV) - margin,
        Math.min(by - h / 2, ancY - arV) - margin,
        Math.max(bx + w / 2, cx0 + arV) + margin,
        Math.max(by + h / 2, ancY + arV) + margin,
      ];
      const lobeAmpA = LOBE_AMP[ia];
      const lobeAmpB = LOBE_AMP[ib];

      ctx.draw(this.prog, {
        uBody: [bx, by, w, h],
        uAnchor: [cx0, this.ay.value, arV],
        uK: k,
        uLobe: [f, lobeAmpA, lobeAmpB, this.morph.value],
        uLobeN: [LOBES[ia], LOBES[ib], rot],
        uBox: box,
        uMat: Math.max(0, Math.min(1, this.mat.value)),
        uBevel: bevel,
        uAmp: amp,
        uGlowCol: this.glowCol,
        uGlow: glow,
        uWave: [x0, x1, by, waveOn],
        uWaveCol: hexRgb('#ff5f6d'),
        uHist: this.hist,
      });

      return {
        cx: labelCx,
        cy: by,
        labelOpacity: opacity,
        labelColor: 'light',
        labelBlur: (1 - opacity) * 5,
        hideLabel: opacity < 0.01,
      };
    },
  });
})();
